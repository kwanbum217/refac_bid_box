"""
src/app/services/kb_builder.py

하이브리드 지식베이스 구축 (원본 apps/chatbot/management/commands/update_hybrid_kb.py 이식).

원본과 동일하게 최근 1년 공고에 낙찰 결과를 조인해 ChromaDB `bidding_kb` 컬렉션을
재구축하고 knowledge_base_status 를 갱신합니다. 문서 본문 포맷과 메타데이터,
공고가 없을 때 낙찰 단독 색인으로 폴백하는 규칙까지 그대로 보존합니다.

원본 대비 의도적으로 바꾼 두 가지
1. 색인 상한(MAX_DOCUMENTS)이 원본에 10 으로 하드코딩되어 KB 가 10건에 머물러 있었습니다.
   기본값은 원본과 동일하게 두되 KB_MAX_DOCUMENTS 로 조정할 수 있게 했습니다.
2. 원본은 GEMINI_API_KEY 를 요구했지만 실제 임베딩에는 사용하지 않았습니다
   (`_ = client`). ChromaDB 기본 임베딩 함수를 그대로 쓰므로 키 요구를 제거했습니다.
   임베딩은 2026-08-06 에 bge-m3 로 교체했습니다(`src/rag/embeddings.py`).
   ChromaDB 기본 모델은 영어 전용이라 한국어 top-5 적중률이 4% 였습니다.
"""

from __future__ import annotations

import hashlib
import logging
import os
import time
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any

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

__all__ = [
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
    """문서 본문의 해시. 증분 색인의 변경 판정 기준입니다.

    DB 시각을 쓰지 않는 이유가 있습니다. `collected_at` 은 `default=utcnow` 라
    INSERT 시각이며, 재수집으로 값이 갱신돼도 시각이 그대로일 수 있습니다.
    본문 해시는 어떤 경로로 값이 바뀌었든 잡아냅니다.
    """
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
    """컬렉션에 이미 있는 id -> 본문 해시 맵을 읽습니다.

    두 번째 반환값은 증분을 적용할 수 있는지 여부입니다. 해시가 없거나 포맷
    버전이 다른 문서가 하나라도 있으면 비교 기준이 서지 않으므로 전량
    재구축으로 떨어집니다.
    """
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
            ids = stored.get("ids") or []
            metadatas = stored.get("metadatas") or []
            if not ids:
                raise RuntimeError(f"offset {page_offset} 페이지가 비어 있습니다.")
            if len(ids) != len(metadatas):
                raise RuntimeError(
                    f"offset {page_offset} 페이지의 ID {len(ids)}건과 "
                    f"메타데이터 {len(metadatas)}건이 일치하지 않습니다."
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
        position
        for position, doc_id in enumerate(ids)
        if existing.get(doc_id) != metadatas[position]["doc_hash"]
    ]
    # 집합을 반드시 밖에서 한 번만 만듭니다. 컴프리헨션 안에 두면 기존 문서마다
    # 재구축해 O(기존 x 대상) 이 되고, 10만 x 50만 규모에서는 끝나지 않습니다.
    target_ids = set(ids)
    removed_ids = [doc_id for doc_id in existing if doc_id not in target_ids]
    return changed_positions, removed_ids


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


def rebuild_knowledge_base(
    db: Session,
    pipeline_run_id: str = "",
    *,
    full: bool = False,
    collected_since: datetime | None = None,
) -> dict[str, Any]:
    """최근 1년 데이터로 bidding_kb 컬렉션을 갱신합니다.

    기본은 증분입니다. 본문 해시가 그대로인 문서는 다시 임베딩하지 않습니다.
    `full=True` 면 컬렉션을 비우고 전량 재구축합니다.

    **컬렉션을 먼저 지우지 않습니다.** 예전에는 `delete_collection` 뒤에
    재색인했는데, 그 사이 챗봇 질의가 빈 KB 를 조회해 근거 없이 답했고 색인이
    실패하면 KB 가 빈 채로 남았습니다.
    """
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
            announcements, source_mode = _resolve_delta_announcements(db, collected_since)
        else:
            announcements, source_mode = _resolve_announcements(db, one_year_ago)

        results = (
            db.execute(
                select(BidResult).where(
                    BidResult.bid_ntce_no.in_(
                        {announcement.bid_ntce_no for announcement in announcements}
                    )
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

        documents: list[str] = []
        metadatas: list[dict[str, Any]] = []
        ids: list[str] = []

        for ann in announcements:
            result = results_map.get(_join_key(ann))
            content = _build_announcement_document(ann, result)
            documents.append(content)
            metadatas.append(
                {
                    "type": "bid_info",
                    "id": ann.id,
                    "category": ann.category,
                    "has_result": bool(result),
                    "doc_hash": _document_hash(content),
                    "fmt": DOC_FORMAT_VERSION,
                }
            )
            ids.append(f"bid_{ann.id}")

        if delta_mode:
            embedded = _flush(collection, documents, metadatas, ids) if documents else 0
            indexed_count = collection.count()
            stats = {
                "mode": "delta",
                "embedded": embedded,
                "unchanged": 0,
                "removed": 0,
            }
        else:
            indexed_count, stats = _sync(
                collection, documents, metadatas, ids, existing_hashes, incremental
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
            documents, metadatas, ids = [], [], []
            for index, result in enumerate(fallback_results):
                content = _build_result_document(result)
                documents.append(content)
                metadatas.append(
                    {
                        "type": "bid_result",
                        "category": result.category,
                        "has_result": True,
                        "doc_hash": _document_hash(content),
                        "fmt": DOC_FORMAT_VERSION,
                    }
                )
                ids.append(f"result_{result.bid_ntce_no}_{result.bid_ntce_ord}_{index}")
            indexed_count, stats = _sync(
                collection, documents, metadatas, ids, existing_hashes, incremental
            )

        if indexed_count == 0 and not delta_mode:
            raise RuntimeError("최근 1년 기준으로 인덱싱할 공고/낙찰 데이터가 없습니다.")

        embedded_at = utcnow()
        if stats["mode"] == "incremental":
            summary = (
                f"최근 1년 데이터 기준 {indexed_count}건 인덱싱 완료"
                f" (증분: 갱신 {stats['embedded']}건 / 유지 {stats['unchanged']}건"
                f" / 삭제 {stats['removed']}건)"
            )
        elif stats["mode"] == "delta":
            summary = (
                f"이번 수집분 {embedded}건 반영 완료 "
                f"(KB 전체 {indexed_count}건, 기준 {collected_since.isoformat()})"
            )
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
) -> tuple[int, dict[str, int]]:
    """컬렉션을 목표 상태에 맞춥니다.

    반환하는 건수는 **컬렉션에 있어야 할 전체 문서 수**입니다. 이번에 임베딩한
    수가 아닙니다. `knowledge_base_status.source_bid_count` 가 KB 규모를 뜻하는
    값이라, 증분 실행에서 변경분만 기록하면 KB 가 줄어든 것처럼 보입니다.
    """
    if not documents:
        return 0, {"embedded": 0, "unchanged": 0, "removed": 0, "mode": "full"}

    if not incremental:
        embedded = _flush(collection, documents, metadatas, ids)
        return embedded, {
            "embedded": embedded,
            "unchanged": 0,
            "removed": 0,
            "mode": "full",
        }

    changed_positions, removed_ids = _diff_index(existing_hashes, ids, metadatas)

    # 임베딩을 시작하기 전에 막습니다. 이 비율을 넘는 삭제는 데이터가 실제로
    # 사라진 것이 아니라 상한값이나 DB 조회가 잘못된 경우입니다. 그대로 두면
    # 야간 재색인 한 번에 KB 가 통째로 비고, 챗봇은 근거 없이 답하게 됩니다.
    removal_ratio = len(removed_ids) / len(existing_hashes) if existing_hashes else 0.0
    if removal_ratio > MAX_REMOVAL_RATIO:
        raise RuntimeError(
            f"삭제 대상이 기존 색인의 {removal_ratio:.1%} 입니다"
            f" (기존 {len(existing_hashes)}건, 삭제 {len(removed_ids)}건, 목표 {len(ids)}건)."
            f" 상한 {MAX_REMOVAL_RATIO:.0%} 를 넘어 중단합니다."
            " KB_MAX_DOCUMENTS 설정과 DB 조회 결과를 확인하십시오."
        )

    embedded = 0
    if changed_positions:
        embedded = _flush(
            collection,
            [documents[position] for position in changed_positions],
            [metadatas[position] for position in changed_positions],
            [ids[position] for position in changed_positions],
        )

    # 삭제는 재색인 뒤에 합니다. 먼저 지우면 색인이 실패했을 때 문서만 사라집니다.
    if removed_ids:
        collection.delete(ids=removed_ids)

    return len(ids), {
        "embedded": embedded,
        "unchanged": len(ids) - embedded,
        "removed": len(removed_ids),
        "mode": "incremental",
    }


def get_kb_document_count(db: Session) -> int:
    return int(db.scalar(select(func.count(BidAnnouncement.id))) or 0)
