"""src/app/services/kb_builder.py - 하이브리드 지식베이스 구축.

최근 1년 공고에 낙찰 결과를 조인해 ChromaDB `bidding_kb` 컬렉션을 재구축하고
knowledge_base_status 를 갱신합니다. 문서 본문 포맷, 메타데이터, 폴백 규칙을 보존합니다.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.core.timeutil import kst_now, utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.chatbot import KnowledgeBaseStatus
from src.app.services.kb_document_builder import (
    DEFAULT_MAX_DOCUMENTS,
    PagedQuerySequence,
    _build_announcement_document,
    _build_result_document,
    _join_key,
    _max_documents,
    _resolve_announcements,
    _resolve_delta_announcements,
    _resolve_delta_stale_ids,
)
from src.app.services.kb_index_sync import (
    CHUNK_SIZE,
    DOC_FORMAT_VERSION,
    INDEX_BATCH_SIZE,
    INDEX_LOOKUP_BATCH_SIZE,
    INDEX_LOOKUP_MAX_ATTEMPTS,
    INDEX_LOOKUP_RETRY_DELAY_SECONDS,
    MAX_REMOVAL_RATIO,
    KbSyncStats,
    _diff_index,
    _document_hash,
    _flush,
    _load_existing_index,
    _read_existing_index_value,
    _sync,
    _sync_stream,
    delete_in_batches,
)
from src.rag.embeddings import get_collection

logger = logging.getLogger(__name__)

COLLECTION_NAME = "bidding_kb"

# 과거 results_only 비상 경로가 남긴 결과 문서의 id 접두와 메타데이터 타입입니다.
RESULT_DOC_ID_PREFIX = "result_"
RESULT_DOC_TYPE = "bid_result"

# fmt: off
__all__ = (
    "CHUNK_SIZE",
    "COLLECTION_NAME",
    "DEFAULT_MAX_DOCUMENTS",
    "DOC_FORMAT_VERSION",
    "INDEX_BATCH_SIZE",
    "INDEX_LOOKUP_BATCH_SIZE",
    "INDEX_LOOKUP_MAX_ATTEMPTS",
    "INDEX_LOOKUP_RETRY_DELAY_SECONDS",
    "MAX_REMOVAL_RATIO",
    "KbSyncStats",
    "PagedQuerySequence",
    "_build_announcement_document",
    "_build_result_document",
    "_cleanup_stale_result_documents",
    "_collect_result_document_ids",
    "_diff_index",
    "_document_hash",
    "_flush",
    "_join_key",
    "_load_existing_index",
    "_max_documents",
    "_read_existing_index_value",
    "_resolve_announcements",
    "_resolve_delta_announcements",
    "_resolve_delta_stale_ids",
    "_sync",
    "_sync_stream",
    "_upsert_kb_status",
    "get_kb_document_count",
    "rebuild_knowledge_base",
)
# fmt: on


def _upsert_kb_status(db: Session, **fields: Any) -> None:
    query = select(KnowledgeBaseStatus).where(KnowledgeBaseStatus.kb_version == COLLECTION_NAME)
    status = db.execute(query).scalar_one_or_none()
    if status is None:
        status = KnowledgeBaseStatus(kb_version=COLLECTION_NAME)
        db.add(status)
    for key, value in fields.items():
        setattr(status, key, value)
    status.updated_at = utcnow()
    db.commit()


def _collect_result_document_ids(collection: Any) -> list[str]:
    """컬렉션에 남아 있는 낙찰 결과 문서 id 를 타입 메타데이터로 조회합니다."""
    ids: list[str] = []
    batch_size = INDEX_LOOKUP_BATCH_SIZE
    offset = 0
    while True:
        page = collection.get(
            where={"type": RESULT_DOC_TYPE},
            include=[],
            limit=batch_size,
            offset=offset,
        )
        page_ids = [str(doc_id) for doc_id in (page.get("ids") or [])]
        ids.extend(page_ids)
        if len(page_ids) < batch_size:
            return ids
        offset += batch_size


def _cleanup_stale_result_documents(collection: Any, ids: Sequence[str]) -> int:
    """과거 results_only 경로가 남긴 result_ 문서를 지우고 정리 건수를 돌려줍니다."""
    stale_ids = list(ids)
    if not stale_ids:
        return 0
    delete_in_batches(collection, stale_ids)
    logger.info("잔존 낙찰 결과 문서 %d건을 정리했습니다.", len(stale_ids))
    return len(stale_ids)


def rebuild_knowledge_base(
    db: Session,
    pipeline_run_id: str = "",
    *,
    full: bool = False,
    collected_since: datetime | None = None,
    chunk_size: int = CHUNK_SIZE,
) -> dict[str, Any]:
    """최근 1년 데이터로 bidding_kb 컬렉션을 갱신합니다.

    기본은 증분입니다. 본문 해시가 그대로인 문서는 다시 임베딩하지 않습니다.
    `full=True` 면 컬렉션을 비우고 전량 재구축합니다.

    **컬렉션을 먼저 지우지 않습니다.** 예전에는 `delete_collection` 뒤에
    재색인했는데, 그 사이 챗봇 질의가 빈 KB 를 조회해 근거 없이 답했고 색인이
    실패하면 KB 가 빈 채로 남았습니다.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be greater than 0")

    limit = _max_documents()
    try:
        import chromadb

        chroma_path = str(settings.CHROMA_DB_PATH)
        os.makedirs(chroma_path, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=chroma_path)

        collection_reset = False
        if full:
            try:
                chroma_client.delete_collection(COLLECTION_NAME)
                # 삭제에 실패하면 기존 컬렉션이 그대로 남아 이전 문서가 살아 있습니다.
                collection_reset = True
            # 없는 컬렉션 삭제는 정상 흐름이라 무시합니다
            except Exception:  # nosec B110 - 없는 컬렉션 삭제 실패는 정상 흐름이라 무시합니다
                pass
        # 질의 경로(vector_store)와 반드시 같은 임베딩 함수여야 합니다.
        collection = get_collection(chroma_client, COLLECTION_NAME, create=True)

        delta_mode = collected_since is not None and not full
        existing_hashes, incremental = (
            ({}, False) if full or delta_mode else _load_existing_index(collection)
        )
        # 과거 results_only 비상 경로가 만든 result_ 문서는 공고 원천 색인의 목표가
        # 아니므로 증분 비교에서 빠집니다. 삭제 후보로 넘기기 전에 원본 키에서 모아
        # 두었다가, 공고 원천 색인이 성공한 뒤에만 정리합니다.
        stale_result_ids: list[str] = []
        if incremental:
            stale_result_ids = [
                doc_id for doc_id in existing_hashes if doc_id.startswith(RESULT_DOC_ID_PREFIX)
            ]
            # 공고 원천의 목표 문서는 bid_ 접두뿐입니다. 낙찰 결과 등 다른 접두 문서를
            # 삭제 후보에 넣으면 증분 색인이 결과 문서까지 지웁니다.
            existing_hashes = {
                doc_id: doc_hash
                for doc_id, doc_hash in existing_hashes.items()
                if doc_id.startswith("bid_")
            }
        elif not delta_mode and not (full and collection_reset) and collection.count() > 0:
            # 증분 비교 기준이 서지 않았거나(fmt 불일치 등) 컬렉션 삭제가 실패해
            # 기존 문서가 남은 경로입니다. 여기서도 같은 result_ 문서가 정리 대상입니다.
            stale_result_ids = _collect_result_document_ids(collection)

        now = utcnow()
        one_year_ago = kst_now(now) - timedelta(days=365)
        collected_one_year_ago = now - timedelta(days=365)
        delta_stale_ids: list[str] = []
        if delta_mode:
            if collected_since is None:
                raise ValueError("delta_mode requires collected_since")
            announcements, source_mode = _resolve_delta_announcements(db, collected_since)
            # 델타 원천에서 빠진 같은 공고의 이전 차수 문서와, 최신 차수가 취소공고가
            # 되어 원천에서 빠진 문서를 컬렉션에서 제거합니다. 이번에 다시 쓰는 문서는
            # 경합으로 삭제 대상에 들어도 건드리지 않습니다.
            target_ids = {announcement.id for announcement in announcements}
            delta_stale_ids = [
                f"bid_{row_id}"
                for row_id in _resolve_delta_stale_ids(db, collected_since)
                if row_id not in target_ids
            ]
        else:
            announcements, source_mode = _resolve_announcements(
                db, one_year_ago, collected_one_year_ago
            )

        # 1년치 BidResult 전량을 한번에 메모리에 올려 results_map(O(N))을 구성하면
        # 수십만 건 ORM 객체로 워커 메모리가 소진됩니다.
        # 청크 단위로 필요한 BidResult 만 페이지 조회하여 메모리 상한을 유지합니다.
        current_chunk_results_map: dict[str, Any] = {}

        def prepare_ann_chunk(chunk: Sequence[Any]) -> None:
            nonlocal current_chunk_results_map
            current_chunk_results_map.clear()
            chunk_ntce_nos = {
                announcement.bid_ntce_no
                for announcement in chunk
                if getattr(announcement, "bid_ntce_no", None)
            }
            if chunk_ntce_nos:
                stmt = select(BidResult).where(BidResult.bid_ntce_no.in_(chunk_ntce_nos))
                res_rows = list(db.execute(stmt).scalars().all())
                for r in res_rows:
                    db.expunge(r)
                current_chunk_results_map = {_join_key(r): r for r in res_rows}

        def make_ann_doc(_: int, announcement: Any) -> tuple[str, str, dict[str, Any]]:
            result = current_chunk_results_map.get(_join_key(announcement))
            content = _build_announcement_document(announcement, result)
            meta = {
                "type": "bid_info",
                "id": announcement.id,
                "category": announcement.category,
                "has_result": bool(result),
                "doc_hash": _document_hash(content),
                "fmt": DOC_FORMAT_VERSION,
            }
            return f"bid_{announcement.id}", content, meta

        indexed_count, stats = _sync_stream(
            collection,
            announcements,
            lambda _, announcement: f"bid_{announcement.id}",
            make_ann_doc,
            existing_hashes,
            incremental=incremental,
            delta_mode=delta_mode,
            chunk_size=chunk_size,
            prepare_chunk=prepare_ann_chunk,
        )
        current_chunk_results_map.clear()

        # 재색인 뒤에 지웁니다. 먼저 지우면 색인이 실패했을 때 문서만 사라집니다.
        if delta_stale_ids:
            delete_in_batches(collection, list(delta_stale_ids))
        if delta_mode:
            indexed_count = collection.count()

        if indexed_count == 0 and not delta_mode:
            source_mode = "results_only"
            stmt = (
                select(BidResult)
                .where(BidResult.rl_openg_dt >= one_year_ago)
                .order_by(BidResult.rl_openg_dt.desc())
                .limit(limit)
            )
            fallback_results = list(db.execute(stmt).scalars().all())
            for r in fallback_results:
                db.expunge(r)

            def make_res_doc(index: int, result: Any) -> tuple[str, str, dict[str, Any]]:
                content = _build_result_document(result)
                meta = {
                    "type": "bid_result",
                    "category": result.category,
                    "has_result": True,
                    "doc_hash": _document_hash(content),
                    "fmt": DOC_FORMAT_VERSION,
                }
                return f"result_{result.bid_ntce_no}_{result.bid_ntce_ord}_{index}", content, meta

            indexed_count, stats = _sync_stream(
                collection,
                fallback_results,
                lambda index, result: f"result_{result.bid_ntce_no}_{result.bid_ntce_ord}_{index}",
                make_res_doc,
                existing_hashes,
                incremental=incremental,
                delta_mode=False,
                chunk_size=chunk_size,
            )

        if indexed_count == 0 and not delta_mode:
            raise RuntimeError("최근 1년 기준으로 인덱싱할 공고/낙찰 데이터가 없습니다.")

        # 잔존 result_ 문서 정리는 공고 원천 색인이 성공한 뒤에만 합니다. 먼저 지우면
        # 색인이 실패했을 때 문서만 사라집니다. 공고 원천 0건(results_only)이면 방금
        # 만든 결과 문서를 지울 수 있으므로 건드리지 않습니다.
        cleaned_result_count = 0
        if not delta_mode and source_mode != "results_only" and indexed_count > 0:
            cleaned_result_count = _cleanup_stale_result_documents(collection, stale_result_ids)
            # KB 상태의 source_bid_count 가 실제 문서 수와 맞도록 다시 읽습니다.
            indexed_count = collection.count()
        if cleaned_result_count:
            stats["removed"] += cleaned_result_count

        existing_hashes.clear()

        embedded_at = utcnow()
        if stats["mode"] == "incremental":
            summary = (
                f"최근 1년 데이터 기준 {indexed_count}건 인덱싱 완료"
                f" (증분: 갱신 {stats['embedded']}건 / 유지 {stats['unchanged']}건 / 삭제 {stats['removed']}건)"
            )
        elif stats["mode"] == "delta":
            since_repr = collected_since.isoformat() if collected_since is not None else ""
            summary = f"이번 수집분 {stats['embedded']}건 반영 완료 (KB 전체 {indexed_count}건, 기준 {since_repr})"
        else:
            summary = f"최근 1년 데이터 기준 {indexed_count}건 인덱싱 완료"
            if cleaned_result_count:
                summary += f" (잔존 결과 문서 {cleaned_result_count}건 정리)"
        _upsert_kb_status(
            db,
            status="ready",
            source_bid_count=indexed_count,
            last_embedding_at=embedded_at,
            last_pipeline_run_id=pipeline_run_id,
            notes=f"{summary} (source={source_mode})",
        )
        metrics = {
            "source_bid_count": indexed_count,
            "collection_name": COLLECTION_NAME,
            "source_mode": source_mode,
            "max_documents": limit,
            "last_pipeline_run_id": pipeline_run_id,
            "last_embedding_at": embedded_at.isoformat(),
            "index_mode": stats["mode"],
            "embedded_count": stats["embedded"],
            "unchanged_count": stats["unchanged"],
            "removed_count": stats["removed"],
        }
        return {"status": "success", "summary": summary, "metrics": metrics}
    except Exception as exc:
        logger.exception("지식베이스 구축 실패")
        _upsert_kb_status(db, status="failed", last_pipeline_run_id=pipeline_run_id, notes=str(exc))
        metrics = {"collection_name": COLLECTION_NAME, "max_documents": limit}
        return {"status": "failed", "summary": str(exc), "metrics": metrics}


def get_kb_document_count(db: Session) -> int:
    return int(db.scalar(select(func.count(BidAnnouncement.id))) or 0)
