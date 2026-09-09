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
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.chatbot import KnowledgeBaseStatus
from src.app.services.kb_document_builder import (
    PagedQuerySequence,
    _build_announcement_document,
    _build_result_document,
    _join_key,
    _max_documents,
    _resolve_announcements,
    _resolve_delta_announcements,
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
)
from src.rag.embeddings import get_collection

logger = logging.getLogger(__name__)

COLLECTION_NAME = "bidding_kb"

# 원본은 10 이었습니다. 그 값이 야간 재색인에 그대로 적용되면 목표 문서가 10건이
# 되고, 기존 색인 전부가 삭제 대상으로 계산됩니다. 2026-08-07 에 KB 를 50만 건으로
# 확대한 뒤로는 운영 규모와 맞는 값이어야 합니다.
DEFAULT_MAX_DOCUMENTS = 500_000

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
    "_diff_index",
    "_document_hash",
    "_flush",
    "_join_key",
    "_load_existing_index",
    "_max_documents",
    "_read_existing_index_value",
    "_resolve_announcements",
    "_resolve_delta_announcements",
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

        if full:
            try:
                chroma_client.delete_collection(COLLECTION_NAME)
            # 없는 컬렉션 삭제는 정상 흐름이라 무시합니다
            except Exception:  # nosec B110
                pass
        # 질의 경로(vector_store)와 반드시 같은 임베딩 함수여야 합니다.
        collection = get_collection(chroma_client, COLLECTION_NAME, create=True)

        delta_mode = collected_since is not None and not full
        existing_hashes, incremental = (
            ({}, False) if full or delta_mode else _load_existing_index(collection)
        )

        one_year_ago = utcnow() - timedelta(days=365)
        if delta_mode:
            if collected_since is None:
                raise ValueError("delta_mode requires collected_since")
            announcements, source_mode = _resolve_delta_announcements(db, collected_since)
        else:
            announcements, source_mode = _resolve_announcements(db, one_year_ago)

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
