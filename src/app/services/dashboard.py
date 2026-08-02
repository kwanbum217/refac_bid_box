"""
src/app/services/dashboard.py

대시보드/비교분석 집계 (원본 apps/bids/dashboard_api.py 1:1 이식).
Django ORM 집계를 SQLAlchemy 2.0 표현식으로 옮기되 산출 값과 캐시 키 규칙은 원본과 동일합니다.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timedelta
from datetime import timezone as dt_timezone
from typing import Any

from sqlalchemy import BigInteger, String, case, func, literal, or_, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.models.bids import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    BidAnnouncement,
    BidDatasetSummary,
    BidResult,
    is_corrupted_display_text,
)

logger = logging.getLogger(__name__)

DASHBOARD_STATS_CACHE_TTL = 60 * 60 * 24
COMPARE_STATS_CACHE_TTL = 60 * 60 * 24
DASHBOARD_RESULT_SCOPE_START = datetime(2015, 1, 1, tzinfo=dt_timezone.utc).replace(tzinfo=None)
DASHBOARD_RESULT_SCOPE_LABEL = "2015년 ~ 현재"
UNIT_PRICE_RESULT_KEYWORDS = (
    "단가",
    "교복",
    "학생복",
)
UNCLASSIFIED_AGENCY_LABELS = {
    "기타 기관(분석불가)",
    "기타 기관 (분석 불가)",
}


def _display_agency_name(name: str | None) -> str | None:
    if name in UNCLASSIFIED_AGENCY_LABELS:
        return "미분류 기관"
    return name


def _is_readable_agency_name(name: str | None) -> bool:
    """업체 순위(`_is_readable_company_name`)와 같은 기준을 기관 순위에도 적용합니다.

    parquet 복구분에 인코딩이 깨진 기관명이 남아 있어, 걸러내지 않으면 순위 상단이
    읽을 수 없는 문자열로 채워집니다.
    """
    return bool(name) and not is_corrupted_display_text(name)


def _exclude_unit_price_results(stmt):
    for keyword in UNIT_PRICE_RESULT_KEYWORDS:
        stmt = stmt.where(
            or_(
                BidResult.bid_ntce_nm.is_(None),
                ~BidResult.bid_ntce_nm.contains(keyword),
            )
        )
    return stmt


def _extract_representative_company_name(raw_name: str | None) -> str:
    if not raw_name:
        return ""
    match = re.search(r"\^\s*(?:공동|단독)\^([^^\],]+)", raw_name)
    if match:
        return match.group(1).strip()
    return raw_name.strip()


def _is_readable_company_name(name: str) -> bool:
    if not name or "�" in name:
        return False
    return bool(re.search(r"[가-힣A-Za-z0-9]", name))


def _build_company_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    company_totals: dict[str, dict[str, Any]] = {}
    for row in rows:
        name = _extract_representative_company_name(row["bidwinnr_nm"])
        if not _is_readable_company_name(name):
            continue
        existing = company_totals.setdefault(name, {"name": name, "count": 0, "total_amt": 0})
        existing["count"] += row["cnt"]
        existing["total_amt"] += int(row["total_amt"] or 0)
    return sorted(company_totals.values(), key=lambda item: item["total_amt"], reverse=True)[:10]


def _dialect_name(db: Session) -> str:
    try:
        return db.get_bind().dialect.name
    except Exception:
        return "mysql"


def _month_bucket_expr(db: Session, column):
    """월 버킷 문자열(YYYY-MM) 표현식. 원본의 vendor 분기를 그대로 유지합니다."""
    vendor = _dialect_name(db)
    if vendor == "sqlite":
        return func.strftime("%Y-%m", column).cast(String)
    if vendor == "postgresql":
        return func.to_char(column, "YYYY-MM").cast(String)
    return func.date_format(column, "%Y-%m").cast(String)


def _build_monthly_counts(db: Session, base_stmt, column) -> list[dict[str, Any]]:
    subquery = base_stmt.where(column.is_not(None)).subquery()
    aliased_column = getattr(subquery.c, column.key)
    aliased_bucket = _month_bucket_expr(db, aliased_column)
    rows = db.execute(
        select(aliased_bucket.label("month"), func.count(subquery.c.id).label("cnt"))
        .group_by(aliased_bucket)
        .order_by(aliased_bucket)
    ).all()
    return [{"month": row.month, "count": row.cnt} for row in rows if row.month]


def _marker_value(value: datetime | None) -> str:
    if value is None:
        return "empty"
    return value.isoformat()


def _latest_collection_value(db: Session, model) -> datetime | None:
    return db.scalar(select(func.max(model.collected_at)))


def _dashboard_stats_cache_key(summary: BidDatasetSummary) -> str:
    return (
        "dashboard_basic_stats:v4:"
        f"{DASHBOARD_RESULT_SCOPE_START.isoformat()}:"
        f"{_marker_value(summary.source_latest_collected_at)}:"
        f"{_marker_value(summary.rebuilt_at)}"
    )


def _compare_stats_cache_key(
    announcement_summary: BidDatasetSummary,
    result_summary: BidDatasetSummary,
) -> str:
    return (
        "dashboard_compare_stats:"
        f"{_marker_value(announcement_summary.source_latest_collected_at)}:"
        f"{_marker_value(announcement_summary.rebuilt_at)}:"
        f"{_marker_value(result_summary.source_latest_collected_at)}:"
        f"{_marker_value(result_summary.rebuilt_at)}"
    )


def _model_for_dataset(dataset: str):
    if dataset == DATASET_ANNOUNCEMENT:
        return BidAnnouncement
    return BidResult


def _json_text(db: Session, column, key: str):
    """raw_data JSON 키를 텍스트로 추출합니다 (원본 KeyTextTransform 대응)."""
    if _dialect_name(db) == "mysql":
        return func.json_unquote(func.json_extract(column, f"$.{key}"))
    return func.json_extract(column, f"$.{key}")


def _announcement_amount_expr(db: Session):
    raw_amount = func.coalesce(
        func.nullif(_json_text(db, BidAnnouncement.raw_data, "asignBdgtAmt"), literal("")),
        func.nullif(_json_text(db, BidAnnouncement.raw_data, "bdgtAmt"), literal("")),
    )
    return case(
        (BidAnnouncement.raw_data.is_(None), BidAnnouncement.base_amount),
        else_=func.cast(raw_amount, BigInteger),
    )


def _build_summary_defaults(db: Session, dataset: str) -> dict[str, Any]:
    if dataset == DATASET_ANNOUNCEMENT:
        row = db.execute(
            select(
                func.count(BidAnnouncement.id),
                func.sum(_announcement_amount_expr(db)),
                func.max(BidAnnouncement.collected_at),
            )
        ).one()
        avg_rate = None
        total_count, total_amount, latest_collected_at = row
    else:
        row = db.execute(
            select(
                func.count(BidResult.id),
                func.sum(BidResult.sucsf_bid_amt),
                func.avg(BidResult.sucsf_bid_rate),
                func.max(BidResult.collected_at),
            )
        ).one()
        total_count, total_amount, avg_rate, latest_collected_at = row

    return {
        "total_count": total_count or 0,
        "total_amount": total_amount or 0,
        "avg_rate": avg_rate,
        "source_latest_collected_at": latest_collected_at,
    }


def rebuild_bid_dataset_summary(db: Session, dataset: str) -> BidDatasetSummary:
    defaults = _build_summary_defaults(db, dataset)
    summary = db.get(BidDatasetSummary, dataset)
    if summary is None:
        summary = BidDatasetSummary(dataset=dataset, **defaults)
        db.add(summary)
    else:
        for field, value in defaults.items():
            setattr(summary, field, value)
        summary.rebuilt_at = datetime.utcnow()
    db.commit()
    db.refresh(summary)
    return summary


def rebuild_bid_dataset_summaries(db: Session, datasets=None) -> dict[str, BidDatasetSummary]:
    datasets = list(datasets or (DATASET_ANNOUNCEMENT, DATASET_RESULT))
    return {dataset: rebuild_bid_dataset_summary(db, dataset) for dataset in datasets}


def get_bid_dataset_summary(db: Session, dataset: str) -> BidDatasetSummary:
    latest_collected_at = _latest_collection_value(db, _model_for_dataset(dataset))
    summary = db.get(BidDatasetSummary, dataset)
    if summary is None or summary.source_latest_collected_at != latest_collected_at:
        summary = rebuild_bid_dataset_summary(db, dataset)
    return summary


def get_dashboard_stats(db: Session) -> dict[str, Any]:
    """대시보드 기본 통계 데이터."""
    result_summary = get_bid_dataset_summary(db, DATASET_RESULT)
    cache_key = _dashboard_stats_cache_key(result_summary)
    data = cache.get(cache_key)
    if data:
        return data

    now = datetime.utcnow()
    one_year_ago = now - timedelta(days=365)

    scoped = db.execute(
        select(
            func.count(BidResult.id),
            func.sum(BidResult.sucsf_bid_amt),
            func.avg(BidResult.sucsf_bid_rate),
            func.max(BidResult.collected_at),
        ).where(BidResult.rl_openg_dt >= DASHBOARD_RESULT_SCOPE_START)
    ).one()
    scoped_count, scoped_amount, scoped_avg_rate, scoped_latest = scoped

    # 기관별 TOP 10 (최근 1년)
    by_agency = db.execute(
        select(
            BidResult.dminstt_nm,
            func.sum(BidResult.sucsf_bid_amt).label("total_amt"),
            func.count(BidResult.id).label("cnt"),
        )
        .where(BidResult.rl_openg_dt >= one_year_ago, BidResult.dminstt_nm.is_not(None))
        .group_by(BidResult.dminstt_nm)
        .order_by(func.sum(BidResult.sucsf_bid_amt).desc())
        .limit(10)
    ).all()

    # 업체별 TOP 10 (최근 1년) — 원본과 동일하게 상위 100건을 대표명으로 재집계
    company_stmt = select(
        BidResult.bidwinnr_nm,
        func.count(BidResult.id).label("cnt"),
        func.sum(BidResult.sucsf_bid_amt).label("total_amt"),
    ).where(
        BidResult.rl_openg_dt >= one_year_ago,
        BidResult.bidwinnr_nm.is_not(None),
        BidResult.bidwinnr_nm != "",
        BidResult.sucsf_bid_amt > 0,
    )
    company_stmt = _exclude_unit_price_results(company_stmt)
    by_company = db.execute(
        company_stmt.group_by(BidResult.bidwinnr_nm)
        .order_by(func.sum(BidResult.sucsf_bid_amt).desc())
        .limit(100)
    ).all()

    # 월별 추세 (최근 1년)
    by_month = _build_monthly_counts(
        db,
        select(BidResult.id, BidResult.rl_openg_dt).where(BidResult.rl_openg_dt >= one_year_ago),
        BidResult.rl_openg_dt,
    )

    data = {
        "scope_label": DASHBOARD_RESULT_SCOPE_LABEL,
        "total_count": scoped_count or 0,
        "total_amount": int(scoped_amount or 0),
        "avg_rate": round(float(scoped_avg_rate or 0), 2),
        "latest_collected": scoped_latest.isoformat() if scoped_latest else None,
        "by_agency": [
            {
                "name": _display_agency_name(row.dminstt_nm),
                "total_amt": int(row.total_amt or 0),
                "count": row.cnt,
            }
            for row in by_agency
            if _is_readable_agency_name(row.dminstt_nm)
        ],
        "by_company": _build_company_rows(
            [
                {"bidwinnr_nm": row.bidwinnr_nm, "cnt": row.cnt, "total_amt": row.total_amt}
                for row in by_company
            ]
        ),
        "by_month": by_month,
    }

    cache.set(cache_key, data, DASHBOARD_STATS_CACHE_TTL)
    return data


def get_compare_stats_data(db: Session) -> dict[str, Any]:
    """입찰공고 vs 낙찰 비교 통계."""
    announcement_summary = get_bid_dataset_summary(db, DATASET_ANNOUNCEMENT)
    result_summary = get_bid_dataset_summary(db, DATASET_RESULT)
    cache_key = _compare_stats_cache_key(announcement_summary, result_summary)
    data = cache.get(cache_key)
    if data:
        return data

    now = datetime.utcnow()
    one_year_ago = now - timedelta(days=365)

    # 매칭 데이터 (최근 1년)
    matched_count = db.scalar(
        select(func.count(BidAnnouncement.id)).where(
            BidAnnouncement.bid_ntce_no.in_(
                select(BidResult.bid_ntce_no).where(BidResult.rl_openg_dt >= one_year_ago)
            )
        )
    )

    announce_by_month = _build_monthly_counts(
        db,
        select(BidAnnouncement.id, BidAnnouncement.bid_ntce_dt).where(
            BidAnnouncement.bid_ntce_dt >= one_year_ago
        ),
        BidAnnouncement.bid_ntce_dt,
    )
    result_by_month = _build_monthly_counts(
        db,
        select(BidResult.id, BidResult.rl_openg_dt).where(BidResult.rl_openg_dt >= one_year_ago),
        BidResult.rl_openg_dt,
    )

    amount_expr = _announcement_amount_expr(db)
    agency_announce = db.execute(
        select(
            BidAnnouncement.dminstt_nm,
            func.sum(amount_expr).label("total_base_amount"),
            func.count(BidAnnouncement.id).label("cnt"),
        )
        .where(BidAnnouncement.bid_ntce_dt >= one_year_ago, BidAnnouncement.dminstt_nm.is_not(None))
        .group_by(BidAnnouncement.dminstt_nm)
        .order_by(func.sum(amount_expr).desc())
        .limit(10)
    ).all()

    announcement_total_amount = int(announcement_summary.total_amount or 0)

    data = {
        "announce_count": announcement_summary.total_count or 0,
        "announce_total_base_amount": announcement_total_amount,
        "announce_total_prce": announcement_total_amount,
        "result_count": result_summary.total_count or 0,
        "result_total_amt": int(result_summary.total_amount or 0),
        "matched_count": int(matched_count or 0),
        "announce_by_month": announce_by_month,
        "result_by_month": result_by_month,
        "agency_announce_top10": [
            {
                "name": row.dminstt_nm,
                "total_base_amount": int(row.total_base_amount or 0),
                "total_prce": int(row.total_base_amount or 0),
                "count": row.cnt,
            }
            for row in agency_announce
        ],
    }

    cache.set(cache_key, data, COMPARE_STATS_CACHE_TTL)
    return data


def warm_dashboard_stats_cache(db: Session) -> dict[str, Any]:
    """대시보드 첫 진입 전 기본 통계를 미리 적재합니다."""
    return get_dashboard_stats(db)


def warm_compare_stats_cache(db: Session) -> dict[str, Any]:
    """비교 분석 첫 진입 전 비교 통계를 미리 적재합니다."""
    return get_compare_stats_data(db)


def warm_dashboard_caches(db: Session) -> dict[str, Any]:
    """수집 직후 대시보드/비교 분석 통계를 모두 적재합니다."""
    return {
        "dashboard_stats": warm_dashboard_stats_cache(db),
        "compare_stats": warm_compare_stats_cache(db),
    }


__all__ = [
    "DASHBOARD_RESULT_SCOPE_LABEL",
    "get_bid_dataset_summary",
    "get_compare_stats_data",
    "get_dashboard_stats",
    "rebuild_bid_dataset_summaries",
    "rebuild_bid_dataset_summary",
    "warm_compare_stats_cache",
    "warm_dashboard_caches",
    "warm_dashboard_stats_cache",
]
