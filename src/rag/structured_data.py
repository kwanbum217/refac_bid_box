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

from src.app.models.bids import (
    CATEGORY_LABELS,
    CORRUPTED_TEXT_FALLBACKS,
    BidAnnouncement,
    BidResult,
    clean_display_text,
    is_corrupted_display_text,
)
from src.app.services.ranking_snapshots import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    REPLACEMENT_CHAR,
    exclude_corrupted,
    get_skipped_count,
    get_top_rankings,
)
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


def _snapshot_scope(plan: RetrievalPlan) -> str | None:
    """사전 집계 스냅샷을 쓸 수 있는 질의인지 판정합니다.

    스냅샷은 category 조합만 미리 계산해 둡니다. 날짜나 기관명이 걸리면 조합이
    사실상 무한하므로 실시간 집계로 넘깁니다. 반환값은 category 코드이며,
    필터가 전혀 없으면 빈 문자열(전체)입니다.
    """
    filters = plan.filters or {}
    date_from, date_to = _resolve_window(filters)
    if date_from or date_to:
        return None
    if _normalize_text(str(filters.get("institution_name") or "")):
        return None
    return _normalize_text(str(filters.get("category") or ""))


def _result_limit(plan: RetrievalPlan) -> int:
    raw_limit = (plan.filters or {}).get("result_limit")
    if raw_limit in (None, ""):
        return 0
    try:
        return min(max(int(raw_limit), 1), 20)
    except (TypeError, ValueError):
        return 0


def _result_availability_conditions(plan: RetrievalPlan) -> list:
    """날짜 필터를 제외한 결과 보유 범위 확인 조건을 만듭니다."""
    filters = plan.filters or {}
    institution_name = _normalize_text(str(filters.get("institution_name") or ""))
    category = _normalize_text(str(filters.get("category") or ""))
    conditions = []
    if institution_name:
        conditions.append(BidResult.dminstt_nm.contains(institution_name))
    if category:
        conditions.append(BidResult.category == category)
    return conditions


# U+FFFD 는 SQL 에서 먼저 쳐내므로 배수는 작아도 됩니다.
LIVE_OVERFETCH_FACTOR = 3


def _drop_corrupted(rows, limit: int) -> tuple[list, int]:
    """인코딩이 깨진 값을 순위에서 제외합니다.

    복구 불가능한 손상값(bid_results 의 41%)을 그대로 두면 순위 상위가 전부
    깨진 문자열로 채워집니다. 제외 건수를 함께 돌려 답변에 안내를 답니다.
    """
    kept: list = []
    dropped = 0
    for row in rows:
        if is_corrupted_display_text(row[0]):
            dropped += 1
            continue
        kept.append(row)
        if len(kept) >= limit:
            break
    return kept, dropped


def _top_rows(
    db: Session,
    *,
    scope: str | None,
    dataset: str,
    dimension: str,
    live_stmt,
    corrupted_probe,
    limit: int = 5,
) -> tuple[list, int]:
    """스냅샷이 있으면 그것을, 없으면 실시간 집계를 씁니다.

    스냅샷은 집계 시점에 이미 손상값을 걸러 두었으므로 그대로 씁니다.
    실시간 경로는 여기서 걸러냅니다.
    """
    if scope is not None:
        cached = get_top_rankings(db, dataset, dimension, scope, limit)
        if cached is not None:
            # 스냅샷은 집계 시점에 걸러냈으므로 그때 기록해 둔 표시를 씁니다.
            return cached, get_skipped_count(db, dataset, dimension, scope)

    rows = db.execute(live_stmt.limit(limit * LIVE_OVERFETCH_FACTOR)).all()
    kept, dropped = _drop_corrupted(rows, limit)
    if not dropped:
        # SQL 이 이미 U+FFFD 를 쳐냈으므로, 제외가 있었는지는 따로 확인합니다.
        # 첫 건에서 멈추므로 전체 스캔이 되지 않습니다.
        dropped = int(db.execute(corrupted_probe.limit(1)).first() is not None)
    return kept, dropped


def retrieve_structured_data(db: Session, plan: RetrievalPlan) -> dict[str, Any]:
    result_conditions = _result_conditions(plan)
    announcement_conditions = _announcement_conditions(plan)
    snapshot_scope = _snapshot_scope(plan)
    result_limit = _result_limit(plan)
    latest_available_result_at = None
    if result_limit:
        latest_available_result_at = db.scalar(
            select(func.max(BidResult.rl_openg_dt)).where(
                *_result_availability_conditions(plan)
            )
        )

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

    recent_results: list[dict[str, Any]] = []
    if result_limit:
        result_rows = db.execute(
            select(BidResult)
            .where(*result_conditions)
            .order_by(
                BidResult.rl_openg_dt.is_(None),
                BidResult.rl_openg_dt.desc(),
                BidResult.id.desc(),
            )
            .limit(result_limit * LIVE_OVERFETCH_FACTOR)
        ).scalars().all()
        for result in result_rows:
            if any(
                is_corrupted_display_text(value)
                for value in (
                    result.bid_ntce_nm,
                    result.dminstt_nm,
                    result.bidwinnr_nm,
                )
            ):
                continue
            recent_results.append(
                {
                    "id": result.id,
                    "bid_ntce_no": result.bid_ntce_no,
                    "bid_ntce_ord": result.bid_ntce_ord,
                    "bid_ntce_nm": clean_display_text(
                        result.bid_ntce_nm, CORRUPTED_TEXT_FALLBACKS["title"]
                    ),
                    "dminstt_nm": clean_display_text(
                        result.dminstt_nm, CORRUPTED_TEXT_FALLBACKS["agency"]
                    ),
                    "bidwinnr_nm": clean_display_text(
                        result.bidwinnr_nm, CORRUPTED_TEXT_FALLBACKS["winner"]
                    ),
                    "sucsf_bid_amt": (
                        int(result.sucsf_bid_amt) if result.sucsf_bid_amt is not None else None
                    ),
                    "sucsf_bid_rate": (
                        float(result.sucsf_bid_rate)
                        if result.sucsf_bid_rate is not None
                        else None
                    ),
                    "rl_openg_dt": (
                        result.rl_openg_dt.isoformat(sep=" ")
                        if result.rl_openg_dt is not None
                        else None
                    ),
                    "category": result.category,
                    "category_label": _category_label(result.category),
                }
            )
            if len(recent_results) >= result_limit:
                break

    winner_rows, dropped_winners = _top_rows(
        db,
        scope=snapshot_scope,
        dataset=DATASET_RESULT,
        dimension="bidwinnr_nm",
        live_stmt=select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .where(exclude_corrupted(BidResult.bidwinnr_nm), *result_conditions)
        .group_by(BidResult.bidwinnr_nm)
        .order_by(func.count(BidResult.id).desc()),
        corrupted_probe=select(BidResult.id).where(
            BidResult.bidwinnr_nm.contains(REPLACEMENT_CHAR), *result_conditions
        ),
    )
    top_winners = [
        {"bidwinnr_nm": _normalize_text(row[0]) if row[0] else row[0], "win_count": row[1]}
        for row in winner_rows
    ]

    institution_rows, dropped_institutions = _top_rows(
        db,
        scope=snapshot_scope,
        dataset=DATASET_ANNOUNCEMENT,
        dimension="dminstt_nm",
        live_stmt=select(BidAnnouncement.dminstt_nm, func.count(BidAnnouncement.id))
        .where(exclude_corrupted(BidAnnouncement.dminstt_nm), *announcement_conditions)
        .group_by(BidAnnouncement.dminstt_nm)
        .order_by(func.count(BidAnnouncement.id).desc()),
        corrupted_probe=select(BidAnnouncement.id).where(
            BidAnnouncement.dminstt_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
        ),
    )
    top_institutions = [
        {"dminstt_nm": _normalize_text(row[0]) if row[0] else row[0], "ntce_count": row[1]}
        for row in institution_rows
    ]

    announcement_rows, dropped_announcements = _top_rows(
        db,
        scope=snapshot_scope,
        dataset=DATASET_ANNOUNCEMENT,
        dimension="bid_ntce_nm",
        live_stmt=select(BidAnnouncement.bid_ntce_nm, func.count(BidAnnouncement.id))
        .where(exclude_corrupted(BidAnnouncement.bid_ntce_nm), *announcement_conditions)
        .group_by(BidAnnouncement.bid_ntce_nm)
        .order_by(func.count(BidAnnouncement.id).desc()),
        corrupted_probe=select(BidAnnouncement.id).where(
            BidAnnouncement.bid_ntce_nm.contains(REPLACEMENT_CHAR), *announcement_conditions
        ),
    )
    top_announcements = [
        {"bid_ntce_nm": _normalize_text(row[0]) if row[0] else row[0], "ntce_count": row[1]}
        for row in announcement_rows
    ]

    sample_announcements = [
        {
            "bid_ntce_no": row[0],
            # 표본은 순위와 달리 건너뛸 수 없으므로 화면과 같은 안내 문구로 대체합니다.
            "bid_ntce_nm": clean_display_text(row[1], CORRUPTED_TEXT_FALLBACKS["title"]),
            "dminstt_nm": clean_display_text(row[2], CORRUPTED_TEXT_FALLBACKS["agency"]),
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
    if result_limit and not recent_results:
        if latest_available_result_at:
            insufficiency.append(
                "요청 기간에 조건에 맞는 낙찰 결과가 없습니다. "
                f"DB에서 확인 가능한 해당 조건의 최신 개찰일은 "
                f"{latest_available_result_at.isoformat(sep=' ')}입니다."
            )
        else:
            insufficiency.append("해당 분야의 낙찰 결과 보유 데이터가 없습니다.")
    if not announcement_count and not result_limit:
        insufficiency.append("조건에 맞는 공고 데이터가 없어 추세 해석이 제한될 수 있습니다.")

    # 순위에서 손상값을 빼면 답이 읽히지만 집계 모수가 달라집니다. 숨기지 않고 알립니다.
    dropped_total = dropped_winners + dropped_institutions + dropped_announcements
    if dropped_total:
        insufficiency.append(
            "일부 항목은 원문 인코딩이 손상되어 순위 집계에서 제외했습니다. "
            "표시된 순위는 판독 가능한 값 기준입니다."
        )

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
            "recent_results": recent_results,
            "latest_available_result_at": (
                latest_available_result_at.isoformat(sep=" ")
                if latest_available_result_at
                else None
            ),
            "time_series": time_series,
        },
        "insufficiency_hints": insufficiency,
    }
