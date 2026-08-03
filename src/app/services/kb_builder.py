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
   임베딩 모델은 기존 컬렉션 정합성 때문에 교체하지 않습니다.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    CATEGORY_LABELS,
    BidAnnouncement,
    BidResult,
    extract_business_budget,
    normalize_bid_ntce_ord,
)
from src.app.models.chatbot import KnowledgeBaseStatus

logger = logging.getLogger(__name__)

COLLECTION_NAME = "bidding_kb"
INDEX_BATCH_SIZE = 100
DEFAULT_MAX_DOCUMENTS = 10


def _max_documents() -> int:
    raw = os.getenv("KB_MAX_DOCUMENTS", "").strip()
    if not raw:
        return DEFAULT_MAX_DOCUMENTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_DOCUMENTS
    return value if value > 0 else DEFAULT_MAX_DOCUMENTS


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


def _resolve_announcements(db: Session, one_year_ago: datetime) -> tuple[list[BidAnnouncement], str]:
    """공고일 기준 → 수집일 기준 순으로 폴백합니다 (원본 _resolve_announcement_queryset)."""
    limit = _max_documents()

    by_notice = (
        db.execute(
            select(BidAnnouncement)
            .where(BidAnnouncement.bid_ntce_dt >= one_year_ago)
            .order_by(BidAnnouncement.bid_ntce_dt.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if by_notice:
        return list(by_notice), "announcements_by_notice_date"

    by_collected = (
        db.execute(
            select(BidAnnouncement)
            .where(BidAnnouncement.collected_at >= one_year_ago)
            .order_by(BidAnnouncement.collected_at.desc())
            .limit(limit)
        )
        .scalars()
        .all()
    )
    if by_collected:
        return list(by_collected), "announcements_by_collected_at"

    return [], "announcements_unavailable"


def _join_key(row: BidAnnouncement | BidResult) -> str:
    """공고와 낙찰을 잇는 키. 차수 자리수를 맞추지 않으면 거의 이어지지 않습니다."""
    return f"{row.bid_ntce_no}-{normalize_bid_ntce_ord(row.bid_ntce_ord)}-{row.category}"


def _build_announcement_document(ann: BidAnnouncement, result: BidResult | None) -> str:
    resolved_base_amount = extract_business_budget(ann.raw_data)
    if resolved_base_amount is None and ann.raw_data is None:
        resolved_base_amount = ann.base_amount

    content = f"[공고명] {ann.bid_ntce_nm}\n"
    content += f"[공고번호] {ann.bid_ntce_no}-{ann.bid_ntce_ord}\n"
    content += f"[수요기관] {ann.dminstt_nm}\n"
    if resolved_base_amount is not None:
        content += f"[기초금액] {resolved_base_amount}원\n"
    if ann.presmpt_prce is not None:
        content += f"[추정가격] {ann.presmpt_prce}원\n"
    content += f"[분류] {CATEGORY_LABELS.get(ann.category, ann.category)}\n"
    content += f"[공고일시] {ann.bid_ntce_dt}\n"

    if result is not None:
        content += f"[낙찰업체] {result.bidwinnr_nm}\n"
        content += f"[낙찰금액] {result.sucsf_bid_amt}원\n"
        content += f"[낙찰률] {result.sucsf_bid_rate}%\n"
        content += f"[개찰일시] {result.rl_openg_dt}\n"
    else:
        content += "[낙찰상태] 진행 중 또는 결과 미수집\n"
    return content


def _build_result_document(result: BidResult) -> str:
    content = f"[낙찰공고번호] {result.bid_ntce_no}-{result.bid_ntce_ord}\n"
    content += f"[수요기관] {result.dminstt_nm}\n"
    content += f"[분류] {CATEGORY_LABELS.get(result.category, result.category)}\n"
    content += f"[낙찰업체] {result.bidwinnr_nm}\n"
    content += f"[낙찰금액] {result.sucsf_bid_amt}원\n"
    content += f"[낙찰률] {result.sucsf_bid_rate}%\n"
    content += f"[개찰일시] {result.rl_openg_dt}\n"
    return content


def rebuild_knowledge_base(db: Session, pipeline_run_id: str = "") -> dict[str, Any]:
    """최근 1년 데이터로 bidding_kb 컬렉션을 재구축합니다."""
    limit = _max_documents()
    try:
        import chromadb

        chroma_path = str(settings.CHROMA_DB_PATH)
        os.makedirs(chroma_path, exist_ok=True)
        chroma_client = chromadb.PersistentClient(path=chroma_path)

        try:
            chroma_client.delete_collection(COLLECTION_NAME)
        # 없는 컬렉션 삭제는 정상 흐름이라 무시합니다
        except Exception:  # nosec B110
            pass
        collection = chroma_client.create_collection(name=COLLECTION_NAME)

        one_year_ago = utcnow() - timedelta(days=365)
        announcements, source_mode = _resolve_announcements(db, one_year_ago)

        results = (
            db.execute(select(BidResult).where(BidResult.rl_openg_dt >= one_year_ago))
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
            documents.append(_build_announcement_document(ann, result))
            metadatas.append(
                {
                    "type": "bid_info",
                    "id": ann.id,
                    "category": ann.category,
                    "has_result": bool(result),
                }
            )
            ids.append(f"bid_{ann.id}")

        indexed_count = _flush(collection, documents, metadatas, ids)

        if indexed_count == 0:
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
                documents.append(_build_result_document(result))
                metadatas.append(
                    {"type": "bid_result", "category": result.category, "has_result": True}
                )
                ids.append(f"result_{result.bid_ntce_no}_{result.bid_ntce_ord}_{index}")
            indexed_count = _flush(collection, documents, metadatas, ids)

        if indexed_count == 0:
            raise RuntimeError("최근 1년 기준으로 인덱싱할 공고/낙찰 데이터가 없습니다.")

        embedded_at = utcnow()
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
            },
        }
    except Exception as exc:
        logger.exception("지식베이스 구축 실패")
        _upsert_kb_status(
            db, status="failed", last_pipeline_run_id=pipeline_run_id, notes=str(exc)
        )
        return {
            "status": "failed",
            "summary": str(exc),
            "metrics": {"collection_name": COLLECTION_NAME, "max_documents": limit},
        }


def _flush(collection, documents: list[str], metadatas: list[dict], ids: list[str]) -> int:
    indexed = 0
    for start in range(0, len(documents), INDEX_BATCH_SIZE):
        end = start + INDEX_BATCH_SIZE
        chunk_ids = ids[start:end]
        if not chunk_ids:
            continue
        collection.add(
            documents=documents[start:end], metadatas=metadatas[start:end], ids=chunk_ids
        )
        indexed += len(chunk_ids)
    return indexed


def get_kb_document_count(db: Session) -> int:
    return int(db.scalar(select(func.count(BidAnnouncement.id))) or 0)
