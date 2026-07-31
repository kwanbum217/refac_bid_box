"""
src/rag/structured_data.py

RAG 엔진용 정형 DB 집계 (원본 rag_engine.retrieve_structured_data SQLAlchemy 이식).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag.schemas import RetrievalPlan

CATEGORY_LABELS = {
    "Thng": "물품",
    "Cnstwk": "건설",
    "Servc": "용역",
    "Frgcpt": "외자",
}


def _parse_date(value: str | date | datetime | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def _category_label(category: str | None) -> str:
    return CATEGORY_LABELS.get(str(category or ""), category or "-")


def _apply_result_filters(stmt, plan: RetrievalPlan):
    filters = plan.filters or {}
    date_from = _parse_date(filters.get("date_from"))
    date_to = _parse_date(filters.get("date_to"))
    institution_name = str(filters.get("institution_name") or "").strip()
    category = str(filters.get("category") or "").strip()

    if date_from:
        stmt = stmt.where(BidResult.rl_openg_dt >= date_from)
    if date_to:
        stmt = stmt.where(BidResult.rl_openg_dt <= date_to + timedelta(days=1))
    if institution_name:
        stmt = stmt.where(BidResult.dminstt_nm.contains(institution_name))
    if category:
        stmt = stmt.where(BidResult.category == category)
    return stmt


def _apply_announcement_filters(stmt, plan: RetrievalPlan):
    filters = plan.filters or {}
    date_from = _parse_date(filters.get("date_from"))
    date_to = _parse_date(filters.get("date_to"))
    institution_name = str(filters.get("institution_name") or "").strip()
    category = str(filters.get("category") or "").strip()

    if date_from:
        stmt = stmt.where(BidAnnouncement.bid_ntce_dt >= date_from)
    if date_to:
        stmt = stmt.where(BidAnnouncement.bid_ntce_dt <= date_to + timedelta(days=1))
    if institution_name:
        stmt = stmt.where(BidAnnouncement.dminstt_nm.contains(institution_name))
    if category:
        stmt = stmt.where(BidAnnouncement.category == category)
    return stmt


def retrieve_structured_data(db: Session, plan: RetrievalPlan) -> dict[str, Any]:
    result_stmt = _apply_result_filters(select(BidResult), plan)
    ann_stmt = _apply_announcement_filters(select(BidAnnouncement), plan)

    stats = db.execute(
        select(
            func.count(BidResult.id),
            func.avg(BidResult.sucsf_bid_rate),
            func.sum(BidResult.sucsf_bid_amt),
        ).select_from(result_stmt.subquery())
    ).one()

    announcement_count = db.scalar(select(func.count()).select_from(ann_stmt.subquery())) or 0

    top_winners = [
        {"bidwinnr_nm": row[0], "win_count": row[1]}
        for row in db.execute(
            select(BidResult.bidwinnr_nm, func.count(BidResult.id))
            .select_from(result_stmt.subquery())
            .group_by(BidResult.bidwinnr_nm)
            .order_by(func.count(BidResult.id).desc())
            .limit(5)
        ).all()
    ]

    insufficiency: list[str] = []
    total_bids = int(stats[0] or 0)
    if not total_bids:
        insufficiency.append("조건에 맞는 낙찰 결과가 충분하지 않습니다.")
    if announcement_count == 0:
        insufficiency.append("조건에 맞는 공고 데이터가 없어 추세 해석이 제한될 수 있습니다.")

    response_filters = dict(plan.filters or {})
    if response_filters.get("category"):
        response_filters["category_label"] = _category_label(str(response_filters["category"]))

    return {
        "filters": response_filters,
        "summary": {
            "total_bids": total_bids,
            "announcement_count": int(announcement_count),
            "average_winning_rate": float(round(stats[1] or 0, 4)),
            "total_winning_amount": float(stats[2] or 0),
            "top_winners": top_winners,
        },
        "insufficiency_hints": insufficiency,
    }
