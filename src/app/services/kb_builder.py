"""
src/app/services/kb_builder.py
하이브리드 지식베이스 구축 (bidding_kb 컬렉션 청크 스트리밍 색인).
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Callable, Sequence
from datetime import datetime, timedelta
from typing import Any, TypedDict

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    BidAnnouncement,
    BidResult,
)
from src.app.models.chatbot import KnowledgeBaseStatus
from src.app.services.kb_document_builder import (
    _build_announcement_document,
    _build_result_document,
    _join_key,
    _max_documents,
    _resolve_announcements,
    _resolve_delta_announcements,
)
from src.rag.embeddings import get_collection

logger = logging.getLogger(__name__)

COLLECTION_NAME = "bidding_kb"


class KbSyncStats(TypedDict):
    embedded: int
    unchanged: int
    removed: int
    mode: str


INDEX_BATCH_SIZE = 100
# 50만 건 메타데이터를 한 응답으로 읽으면 Chroma 응답 객체가 워커 메모리를
# 소진할 수 있습니다. 해시 비교용 조회도 페이지 단위로 제한합니다.
INDEX_LOOKUP_BATCH_SIZE = 10_000
INDEX_LOOKUP_MAX_ATTEMPTS = 2
INDEX_LOOKUP_RETRY_DELAY_SECONDS = 0.25

# 원본은 10 이었습니다. 그 값이 야간 재색인에 그대로 적용되면 목표 문서가 10건이
# 되고, 기존 색인 전부가 삭제 대상으로 계산됩니다. 2026-08-07 에 KB 를 50만 건으로
# 확대한 뒤로는 운영 규모와 맞는 값이어야 합니다.
DEFAULT_MAX_DOCUMENTS = 500_000

# 한 번의 증분 색인이 지울 수 있는 비율의 상한입니다. 이를 넘으면 색인을 중단하고
# 실패로 보고합니다. 상한값 설정 실수나 DB 일시 장애로 KB 가 통째로 사라지는 경로를
# 막습니다. 데이터 무손실(G1)은 벡터DB 에도 적용됩니다.
MAX_REMOVAL_RATIO = 0.5

# 문서 본문 포맷 버전.
#
# `_build_announcement_document` 나 `_build_result_document` 의 출력 형식을
# 바꾸면 반드시 이 값을 올리십시오. 증분 색인은 본문 해시로 변경을 판정하므로,
# 포맷을 바꾸고 버전을 그대로 두면 낡은 형식의 문서가 조용히 남습니다.
DOC_FORMAT_VERSION = 1

# 청크 스트리밍 단위 크기.
# 문서 본문 전체를 메모리에 모으지 않고 이 크기만큼 읽어 _flush 에 넘긴 뒤 해제합니다.
CHUNK_SIZE = 1_000

__all__ = [
    "CHUNK_SIZE",
    "COLLECTION_NAME",
    "DEFAULT_MAX_DOCUMENTS",
    "DOC_FORMAT_VERSION",
    "INDEX_BATCH_SIZE",
    "INDEX_LOOKUP_BATCH_SIZE",
    "INDEX_LOOKUP_MAX_ATTEMPTS",
    "INDEX_LOOKUP_RETRY_DELAY_SECONDS",
    "MAX_REMOVAL_RATIO",
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
    "_upsert_kb_status",
    "get_kb_document_count",
    "rebuild_knowledge_base",
]


def _document_hash(content: str) -> str:
    """문서 본문의 해시. 증분 색인의 변경 판정 기준입니다."""
    return hashlib.sha256(content.encode("utf-8")).hexdigest()


def _read_existing_index_value(operation: Callable[[], Any], operation_name: str) -> Any:
    """기존 색인 조회를 재시도하고, 계속 실패하면 변경 전에 중단합니다."""
    last_error: Exception | None = None
    for attempt in range(1, INDEX_LOOKUP_MAX_ATTEMPTS + 1):
        try:
            return operation()
        except Exception as exc:
            last_error = exc
            if attempt < INDEX_LOOKUP_MAX_ATTEMPTS:
                logger.warning(
                    "%s 실패 (%d/%d), 재시도합니다: %s",
                    operation_name,
                    attempt,
                    INDEX_LOOKUP_MAX_ATTEMPTS,
                    exc,
                )
                time.sleep(INDEX_LOOKUP_RETRY_DELAY_SECONDS)

    raise RuntimeError(
        f"{operation_name}에 {INDEX_LOOKUP_MAX_ATTEMPTS}회 실패했습니다. "
        "기존 색인을 보존한 채 중단합니다. 명시적 full 실행 전에 원인을 확인하십시오."
    ) from last_error


def _load_existing_index(collection) -> tuple[dict[str, str], bool]:
    """컬렉션에 이미 있는 id -> 본문 해시 맵을 읽습니다."""
    stored_count = _read_existing_index_value(
        lambda: int(collection.count()), "기존 색인 문서 수 조회"
    )

    if not stored_count:
        return {}, False

    hashes: dict[str, str] = {}
    for offset in range(0, stored_count, INDEX_LOOKUP_BATCH_SIZE):

        def read_page(page_offset: int = offset) -> tuple[list[str], list[dict[str, Any] | None]]:
            stored = collection.get(
                include=["metadatas"], limit=INDEX_LOOKUP_BATCH_SIZE, offset=page_offset
            )
            ids, metadatas = stored.get("ids") or [], stored.get("metadatas") or []
            if not ids or len(ids) != len(metadatas):
                raise RuntimeError(
                    f"offset {page_offset} 페이지 조회 오류 (ids={len(ids)}, metas={len(metadatas)})"
                )
            return ids, metadatas

        ids, metadatas = _read_existing_index_value(
            read_page, f"기존 색인 메타데이터 조회(offset={offset})"
        )
        for doc_id, meta in zip(ids, metadatas, strict=True):
            meta = meta or {}
            doc_hash = meta.get("doc_hash")
            if not doc_hash or int(meta.get("fmt", 0)) != DOC_FORMAT_VERSION:
                return {}, False
            hashes[doc_id] = str(doc_hash)

    if len(hashes) != stored_count:
        raise RuntimeError(
            "기존 색인 조회 중 문서 수가 달라졌습니다. "
            f"count={stored_count}, loaded={len(hashes)}. 기존 색인을 보존한 채 중단합니다."
        )

    return hashes, True


def _diff_index(
    existing: dict[str, str],
    ids: list[str],
    metadatas: list[dict[str, Any]],
) -> tuple[list[int], list[str]]:
    """재색인할 항목의 위치와 삭제할 id 를 계산합니다."""
    changed_positions = [
        pos for pos, doc_id in enumerate(ids) if existing.get(doc_id) != metadatas[pos]["doc_hash"]
    ]
    target_ids = set(ids)
    return changed_positions, [doc_id for doc_id in existing if doc_id not in target_ids]


def _upsert_kb_status(db: Session, **fields: Any) -> None:
    status = db.execute(
        select(KnowledgeBaseStatus).where(KnowledgeBaseStatus.kb_version == COLLECTION_NAME)
    ).scalar_one_or_none()
    if status is None:
        status = KnowledgeBaseStatus(kb_version=COLLECTION_NAME)
        db.add(status)
    for key, value in fields.items():
        setattr(status, key, value)
    status.updated_at = utcnow()
    db.commit()


def _sync_stream(
    collection: Any,
    items: Sequence[Any],
    make_id: Callable[[int, Any], str],
    make_doc: Callable[[int, Any], tuple[str, str, dict[str, Any]]],
    existing_hashes: dict[str, str],
    *,
    incremental: bool,
    delta_mode: bool,
    chunk_size: int,
) -> tuple[int, KbSyncStats]:
    if not items:
        if delta_mode:
            return collection.count(), {
                "mode": "delta",
                "embedded": 0,
                "unchanged": 0,
                "removed": 0,
            }
        return 0, {"mode": "full", "embedded": 0, "unchanged": 0, "removed": 0}

    removed_ids: list[str] = []
    if incremental:
        target_ids = {make_id(i, it) for i, it in enumerate(items)}
        removed_ids = [doc_id for doc_id in existing_hashes if doc_id not in target_ids]
        del target_ids
        removal_ratio = len(removed_ids) / len(existing_hashes) if existing_hashes else 0.0
        if removal_ratio > MAX_REMOVAL_RATIO:
            raise RuntimeError(
                f"삭제 대상이 기존 색인의 {removal_ratio:.1%} 입니다"
                f" (기존 {len(existing_hashes)}건, 삭제 {len(removed_ids)}건, 목표 {len(items)}건)."
                f" 상한 {MAX_REMOVAL_RATIO:.0%} 를 넘어 중단합니다."
                " KB_MAX_DOCUMENTS 설정과 DB 조회 결과를 확인하십시오."
            )

    embedded_count = 0
    unchanged_count = 0
    for start in range(0, len(items), chunk_size):
        chunk = items[start : start + chunk_size]
        docs: list[str] = []
        metas: list[dict[str, Any]] = []
        ids: list[str] = []
        for i_offset, it in enumerate(chunk):
            doc_id, content, meta = make_doc(start + i_offset, it)
            if incremental and existing_hashes.get(doc_id) == meta.get("doc_hash"):
                unchanged_count += 1
            else:
                docs.append(content)
                metas.append(meta)
                ids.append(doc_id)
        if docs:
            embedded_count += _flush(collection, docs, metas, ids)

    if incremental and removed_ids:
        collection.delete(ids=removed_ids)

    if delta_mode:
        return collection.count(), {
            "mode": "delta",
            "embedded": embedded_count,
            "unchanged": 0,
            "removed": 0,
        }
    if incremental:
        return len(items), {
            "mode": "incremental",
            "embedded": embedded_count,
            "unchanged": unchanged_count,
            "removed": len(removed_ids),
        }
    return len(items), {"mode": "full", "embedded": embedded_count, "unchanged": 0, "removed": 0}


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
            delta_since = collected_since
            if delta_since is None:
                raise ValueError("delta_mode requires collected_since")
            announcements, source_mode = _resolve_delta_announcements(db, delta_since)
        else:
            announcements, source_mode = _resolve_announcements(db, one_year_ago)

        results = (
            db.execute(
                select(BidResult).where(
                    BidResult.bid_ntce_no.in_({a.bid_ntce_no for a in announcements})
                    if delta_mode
                    else BidResult.rl_openg_dt >= one_year_ago
                )
            )
            .scalars()
            .all()
            if announcements
            else []
        )
        results_map = {_join_key(row): row for row in results}

        def make_ann_doc(_: int, ann: Any) -> tuple[str, str, dict[str, Any]]:
            result = results_map.get(_join_key(ann))
            content = _build_announcement_document(ann, result)
            return (
                f"bid_{ann.id}",
                content,
                {
                    "type": "bid_info",
                    "id": ann.id,
                    "category": ann.category,
                    "has_result": bool(result),
                    "doc_hash": _document_hash(content),
                    "fmt": DOC_FORMAT_VERSION,
                },
            )

        indexed_count, stats = _sync_stream(
            collection,
            announcements,
            lambda _, a: f"bid_{a.id}",
            make_ann_doc,
            existing_hashes,
            incremental=incremental,
            delta_mode=delta_mode,
            chunk_size=chunk_size,
        )

        if indexed_count == 0 and not delta_mode:
            source_mode = "results_only"
            fallback_results = (
                db.execute(
                    select(BidResult)
                    .where(BidResult.rl_openg_dt >= one_year_ago)
                    .order_by(BidResult.rl_openg_dt.desc())
                    .limit(limit)
                )
                .scalars()
                .all()
            )

            def make_res_doc(idx: int, res: Any) -> tuple[str, str, dict[str, Any]]:
                content = _build_result_document(res)
                return (
                    f"result_{res.bid_ntce_no}_{res.bid_ntce_ord}_{idx}",
                    content,
                    {
                        "type": "bid_result",
                        "category": res.category,
                        "has_result": True,
                        "doc_hash": _document_hash(content),
                        "fmt": DOC_FORMAT_VERSION,
                    },
                )

            indexed_count, stats = _sync_stream(
                collection,
                fallback_results,
                lambda idx, res: f"result_{res.bid_ntce_no}_{res.bid_ntce_ord}_{idx}",
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
                f" (증분: 갱신 {stats['embedded']}건 / 유지 {stats['unchanged']}건"
                f" / 삭제 {stats['removed']}건)"
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
        return {
            "status": "success",
            "summary": summary,
            "metrics": {
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
            },
        }
    except Exception as exc:
        logger.exception("지식베이스 구축 실패")
        _upsert_kb_status(db, status="failed", last_pipeline_run_id=pipeline_run_id, notes=str(exc))
        return {
            "status": "failed",
            "summary": str(exc),
            "metrics": {"collection_name": COLLECTION_NAME, "max_documents": limit},
        }


def _flush(collection, documents: list[str], metadatas: list[dict], ids: list[str]) -> int:
    """배치로 upsert 합니다. 같은 id 가 오면 제자리에서 갱신됩니다."""
    indexed = 0
    for start in range(0, len(documents), INDEX_BATCH_SIZE):
        end = start + INDEX_BATCH_SIZE
        chunk_ids = ids[start:end]
        if not chunk_ids:
            continue
        collection.upsert(
            documents=documents[start:end], metadatas=metadatas[start:end], ids=chunk_ids
        )
        indexed += len(chunk_ids)
    return indexed


def _sync(
    collection,
    documents: list[str],
    metadatas: list[dict[str, Any]],
    ids: list[str],
    existing_hashes: dict[str, str],
    incremental: bool,
) -> tuple[int, KbSyncStats]:
    """컬렉션을 목표 상태에 맞춥니다."""
    if not documents:
        return 0, {"embedded": 0, "unchanged": 0, "removed": 0, "mode": "full"}
    return _sync_stream(
        collection,
        ids,
        lambda idx, _: ids[idx],
        lambda idx, _: (ids[idx], documents[idx], metadatas[idx]),
        existing_hashes,
        incremental=incremental,
        delta_mode=False,
        chunk_size=len(ids) or 1,
    )


def get_kb_document_count(db: Session) -> int:
    return int(db.scalar(select(func.count(BidAnnouncement.id))) or 0)
