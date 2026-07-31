"""
src/rag/structured_data.py

RAG 정형 검색 (원본 rag_engine.retrieve_structured_data / _apply_*_filters SQLAlchemy 이식).
필터 규칙, 집계 항목, 시계열 버킷 산출을 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import unicodedata
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.models.bids import CATEGORY_LABELS, BidAnnouncement, BidResult
from src.rag.schemas import RetrievalPlan


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def _category_label(category: str | None) -> str:
    category_code = _normalize_text(str(category or ""))
    return CATEGORY_LABELS.get(category_code, category_code or "-")


def _parse_date(value: str | date | datetime | None) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed.replace(tzinfo=None)


def _resolve_window(filters: dict[str, Any]) -> tuple[datetime | None, datetime | None]:
    date_from = _parse_date(filters.get("date_from"))
    date_to = _parse_date(filters.get("date_to"))
    relative_years = int(filters.get("relative_years") or 0)

    if relative_years and not date_from:
        today = date.today()
        date_from = _parse_date((today - timedelta(days=(365 * relative_years) - 1)).isoformat())
        date_to = date_to or _parse_date(today.isoformat())
    return date_from, date_to


def _result_conditions(plan: RetrievalPlan) -> list:
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))

    conditions = []
    if date_from:
        conditions.append(BidResult.rl_openg_dt >= date_from)
    if date_to:
        conditions.append(BidResult.rl_openg_dt <= date_to + timedelta(days=1))
    if institution_name:
        conditions.append(BidResult.dminstt_nm.contains(institution_name))
    if category:
        conditions.append(BidResult.category == category)
    return conditions


def _announcement_conditions(plan: RetrievalPlan) -> list:
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))

    conditions = []
    if date_from:
        conditions.append(BidAnnouncement.bid_ntce_dt >= date_from)
    if date_to:
        conditions.append(BidAnnouncement.bid_ntce_dt <= date_to + timedelta(days=1))
    if institution_name:
        conditions.append(BidAnnouncement.dminstt_nm.contains(institution_name))
    if category:
        conditions.append(BidAnnouncement.category == category)
    return conditions


def _resolve_time_series_granularity(plan: RetrievalPlan) -> str:
    date_from, date_to = _resolve_window(plan.filters or {})
    if date_from and date_to and (date_to.date() - date_from.date()).days <= 45:
        return "day"
    return "month"


def _time_series_bucket_key(opened_at: datetime, granularity: str) -> str:
    if granularity == "day":
        return opened_at.strftime("%Y-%m-%d")
    return opened_at.strftime("%Y-%m")


def retrieve_structured_data(db: Session, plan: RetrievalPlan) -> dict[str, Any]:
    result_conditions = _result_conditions(plan)
    announcement_conditions = _announcement_conditions(plan)

    total_count, avg_rate, total_amt = db.execute(
        select(
            func.count(BidResult.id),
            func.avg(BidResult.sucsf_bid_rate),
            func.sum(BidResult.sucsf_bid_amt),
        ).where(*result_conditions)
    ).one()
    announcement_count = db.scalar(
        select(func.count(BidAnnouncement.id)).where(*announcement_conditions)
    )

    top_winners = [
        {"bidwinnr_nm": _normalize_text(row[0]) if row[0] else row[0], "win_count": row[1]}
        for row in db.execute(
            select(BidResult.bidwinnr_nm, func.count(BidResult.id))
            .where(*result_conditions)
            .group_by(BidResult.bidwinnr_nm)
            .order_by(func.count(BidResult.id).desc())
            .limit(5)
        ).all()
    ]

    top_institutions = [
        {"dminstt_nm": _normalize_text(row[0]) if row[0] else row[0], "ntce_count": row[1]}
        for row in db.execute(
            select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
            .where(*announcement_conditions)
            .group_by(BidAnnouncement.dminstt_nm)
            .order_by(func.count(BidAnnouncement.id).desc())
            .limit(5)
        ).all()
    ]

    top_announcements = [
        {"bid_ntce_nm": _normalize_text(row[0]) if row[0] else row[0], "ntce_count": row[1]}
        for row in db.execute(
            select(BidAnnouncement.bid_ntce_nm, func.count(BidAnnouncement.id))
            .where(*announcement_conditions)
            .group_by(BidAnnouncement.bid_ntce_nm)
            .order_by(func.count(BidAnnouncement.id).desc())
            .limit(5)
        ).all()
    ]

    sample_announcements = [
        {
            "bid_ntce_no": row[0],
            "bid_ntce_nm": _normalize_text(row[1]),
            "dminstt_nm": _normalize_text(row[2]),
        }
        for row in db.execute(
            select(
                BidAnnouncement.bid_ntce_no,
                BidAnnouncement.bid_ntce_nm,
                BidAnnouncement.dminstt_nm,
            )
            .where(*announcement_conditions)
            .order_by(BidAnnouncement.bid_ntce_dt.desc())
            .limit(3)
        ).all()
    ]

    time_series: list[dict[str, Any]] = []
    if (plan.filters or {}).get("analysis_mode") == "trend":
        granularity = _resolve_time_series_granularity(plan)
        series_buckets: dict[str, dict[str, float]] = {}
        rows = db.execute(
            select(BidResult.rl_openg_dt, BidResult.sucsf_bid_rate)
            .where(*result_conditions)
            .order_by(BidResult.rl_openg_dt)
        ).all()
        for opened_at, bid_rate in rows:
            if not opened_at:
                continue
            bucket_key = _time_series_bucket_key(opened_at, granularity)
            bucket = series_buckets.setdefault(bucket_key, {"sum_rate": 0.0, "bid_count": 0})
            bucket["sum_rate"] += float(bid_rate or 0)
            bucket["bid_count"] += 1

        time_series = [
            {
                "label": bucket_key,
                "month": bucket_key,
                "period": granularity,
                "avg_rate": float(
                    round(
                        (bucket["sum_rate"] / bucket["bid_count"]) if bucket["bid_count"] else 0,
                        4,
                    )
                ),
                "bid_count": int(bucket["bid_count"]),
            }
            for bucket_key, bucket in sorted(series_buckets.items())
        ]

    insufficiency: list[str] = []
    if not total_count:
        insufficiency.append("조건에 맞는 낙찰 결과가 충분하지 않습니다.")
    if not announcement_count:
        insufficiency.append("조건에 맞는 공고 데이터가 없어 추세 해석이 제한될 수 있습니다.")

    response_filters = dict(plan.filters or {})
    if response_filters.get("category"):
        response_filters["category_label"] = _category_label(str(response_filters["category"]))

    return {
        "filters": response_filters,
        "summary": {
            "total_bids": int(total_count or 0),
            "announcement_count": int(announcement_count or 0),
            "average_winning_rate": float(round(avg_rate or 0, 4)),
            "total_winning_amount": float(total_amt or 0),
            "top_winners": top_winners,
            "top_institutions": top_institutions,
            "top_announcements": top_announcements,
            "sample_announcements": sample_announcements,
            "time_series": time_series,
        },
        "insufficiency_hints": insufficiency,
    }
