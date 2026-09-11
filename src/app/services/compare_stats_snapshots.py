"""
src/app/services/compare_stats_snapshots.py

비교 통계 사전 집계 스냅샷의 재집계와 조회.

GET /api/v1/bids/compare-stats 의 두 무거운 집계(기관별 상위 10,
매칭 건수)는 하루 한 번 도는 수집 크론으로만 바뀌는 데이터를 매 요청
실시간으로 다시 셉니다. 응답 캐시가 이미 24시간 TTL 이므로 인덱스가
아니라 사전 집계로 해결합니다.

스냅샷은 넷입니다. snapshot_key='agency_announce_top10' 의 payload 는
응답의 agency_announce_top10 리스트와 똑같은 배열이며 각 항목은 name,
total_base_amount, total_prce, count 네 키를 가집니다.
snapshot_key='matched_count' 의 payload 는 {"value": 정수} 입니다.
snapshot_key='announce_by_month' 및 snapshot_key='result_by_month' 의 payload 는
각각 공고/개찰결과 월별 추세 배열이며 각 항목은 month, count 두 키를 가집니다.
window_days 는 넷 모두 365 입니다.

금액 집계는 dashboard._announcement_amount_expr 를 그대로 재사용합니다.
다시 구현하면 이상치 상한 규칙이 갈라져 같은 화면에 다른 금액이 나옵니다.
기관명 손상값 제외는 넣지 않습니다. 현재 compare-stats 경로는 손상값을
거르지 않으며 여기서 새로 거르면 화면 순위가 바뀌는 별개 결정입니다.

나이 판정과 폴백 결정은 호출부(dashboard.get_compare_stats_data)가 합니다.
이 모듈은 재집계(upsert)와 스냅샷+나이 조회까지만 맡습니다.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.bids import (
    BidAnnouncement,
    BidCompareStatsSnapshot,
    BidResult,
)

logger = logging.getLogger(__name__)

SNAPSHOT_KEY_AGENCY_TOP10 = "agency_announce_top10"
SNAPSHOT_KEY_MATCHED_COUNT = "matched_count"
SNAPSHOT_KEY_ANNOUNCE_BY_MONTH = "announce_by_month"
SNAPSHOT_KEY_RESULT_BY_MONTH = "result_by_month"

# 기관 payload 한 항목이 가져야 하는 키입니다. 리스트라는 것만 보고 항목을 그대로
# 인덱싱하면 키가 빠진 항목에서 KeyError 가 나 compare-stats 전체가 실패합니다.
# 작성기는 이 형태만 쓰지만, 손으로 넣은 행이나 옛 형태가 남을 수 있으므로
# 사용 판정에서 항목까지 봅니다.
AGENCY_ITEM_KEYS = ("name", "total_base_amount", "total_prce", "count")


def is_agency_payload_usable(payload: object) -> bool:
    """기관 상위 10 payload 를 그대로 쓸 수 있는 형태인지 판정합니다."""
    if not isinstance(payload, list):
        return False
    return all(
        isinstance(item, dict) and all(key in item for key in AGENCY_ITEM_KEYS) for item in payload
    )


# 월별 payload 한 항목이 가져야 하는 키입니다.
# 항목이 dict 이고 month 와 count 키를 모두 가지며 올바른 타입인지 확인합니다.
MONTHLY_ITEM_KEYS = ("month", "count")


def is_monthly_payload_usable(payload: object) -> bool:
    """월별 집계 payload 를 그대로 쓸 수 있는 형태인지 판정합니다."""
    if not isinstance(payload, list):
        return False
    return all(
        isinstance(item, dict)
        and all(key in item for key in MONTHLY_ITEM_KEYS)
        and isinstance(item.get("month"), str)
        and isinstance(item.get("count"), int)
        for item in payload
    )


# 스냅샷의 집계 창(일). 응답의 최근 1년 구간과 같습니다.
COMPARE_STATS_WINDOW_DAYS = 365

# 스냅샷 신선도 임계(일). 수집 크론이 매일 02:00 에 돌므로 하루 거르는 것은
# 허용하고 이틀은 허용하지 않습니다. 판정은 호출부가 합니다.
COMPARE_STATS_SNAPSHOT_MAX_AGE_DAYS = 2


def is_snapshot_fresh(
    rebuilt_at: datetime | None,
    now: datetime | None = None,
    max_age_days: int = COMPARE_STATS_SNAPSHOT_MAX_AGE_DAYS,
) -> bool:
    """스냅샷 시각이 임계 이내인지 판정합니다. 없으면 낡은 것으로 봅니다."""
    if rebuilt_at is None:
        return False
    reference = now or utcnow()
    rebuilt = rebuilt_at
    if rebuilt.tzinfo is not None:
        rebuilt = rebuilt.astimezone(UTC).replace(tzinfo=None)
    base = reference
    if base.tzinfo is not None:
        base = base.astimezone(UTC).replace(tzinfo=None)
    age_days = (base - rebuilt).total_seconds() / 86400.0
    return age_days <= max_age_days


def get_compare_stats_snapshot(db: Session, snapshot_key: str) -> BidCompareStatsSnapshot | None:
    """스냅샷 행 하나를 읽습니다. 없으면 None 을 돌려 호출부가 폴백합니다."""
    return db.get(BidCompareStatsSnapshot, snapshot_key)


def get_snapshot_with_age(
    db: Session, snapshot_key: str
) -> tuple[Any, datetime | None, float | None]:
    """스냅샷 payload 와 갱신 시각, 나이(일)를 함께 돌려줍니다.

    나이 판정과 폴백 결정은 호출부가 합니다. 스냅샷이 없으면 payload 와
    시각, 나이 모두 None 입니다.
    """
    row = db.get(BidCompareStatsSnapshot, snapshot_key)
    if row is None:
        return None, None, None
    rebuilt_at = row.rebuilt_at
    if rebuilt_at is None:
        return row.payload, None, None
    normalized = rebuilt_at
    if normalized.tzinfo is not None:
        normalized = normalized.astimezone(UTC).replace(tzinfo=None)
    age_days = (utcnow() - normalized).total_seconds() / 86400.0
    return row.payload, rebuilt_at, age_days


def _compute_agency_top10_payload(db: Session, one_year_ago: datetime) -> list[dict[str, Any]]:
    """기관별 상위 10 payload 를 실시간 집계와 같은 식으로 계산합니다.

    손상된 기관명을 제외하지 않습니다. 같은 파일 대시보드 by_agency 의
    가독성 필터와 ranking_snapshots 의 손상 제외를 이 경로에 새로 넣으면
    화면 순위가 바뀌므로 두지 않습니다.
    """
    from src.app.services.dashboard import _announcement_amount_expr

    amount_expr = _announcement_amount_expr(db)
    rows = db.execute(
        select(
            BidAnnouncement.dminstt_nm,
            func.sum(amount_expr).label("total_base_amount"),
            func.count(BidAnnouncement.id).label("cnt"),
        )
        .where(
            BidAnnouncement.bid_ntce_dt >= one_year_ago,
            BidAnnouncement.dminstt_nm.is_not(None),
        )
        .group_by(BidAnnouncement.dminstt_nm)
        .order_by(func.sum(amount_expr).desc())
        .limit(10)
    ).all()
    return [
        {
            "name": row.dminstt_nm,
            "total_base_amount": int(row.total_base_amount or 0),
            "total_prce": int(row.total_base_amount or 0),
            "count": row.cnt,
        }
        for row in rows
    ]


def _compute_matched_count_payload(db: Session, one_year_ago: datetime) -> dict[str, int]:
    """매칭 공고 수 payload 를 실시간 집계와 같은 EXISTS 식으로 계산합니다."""
    matched_count = db.scalar(
        select(func.count(BidAnnouncement.id)).where(
            select(BidResult.id)
            .where(
                BidResult.bid_ntce_no == BidAnnouncement.bid_ntce_no,
                BidResult.rl_openg_dt >= one_year_ago,
            )
            .exists()
        )
    )
    return {"value": int(matched_count or 0)}


def _compute_announce_by_month_payload(db: Session, one_year_ago: datetime) -> list[dict[str, Any]]:
    """공고 월별 건수 payload 를 기존 _build_monthly_counts 로 계산합니다."""
    from src.app.services.dashboard import _build_monthly_counts

    return _build_monthly_counts(
        db,
        select(BidAnnouncement.id, BidAnnouncement.bid_ntce_dt).where(
            BidAnnouncement.bid_ntce_dt >= one_year_ago
        ),
        BidAnnouncement.bid_ntce_dt,
    )


def _compute_result_by_month_payload(db: Session, one_year_ago: datetime) -> list[dict[str, Any]]:
    """개찰결과 월별 건수 payload 를 기존 _build_monthly_counts 로 계산합니다."""
    from src.app.services.dashboard import _build_monthly_counts

    return _build_monthly_counts(
        db,
        select(BidResult.id, BidResult.rl_openg_dt).where(BidResult.rl_openg_dt >= one_year_ago),
        BidResult.rl_openg_dt,
    )


def rebuild_compare_stats_snapshots(db: Session) -> dict[str, Any]:
    """네 스냅샷을 다시 계산해 upsert 합니다. 야간과 수집 직후 경로에서 부릅니다."""
    started = utcnow()
    one_year_ago = started - timedelta(days=COMPARE_STATS_WINDOW_DAYS)
    agency_payload = _compute_agency_top10_payload(db, one_year_ago)
    matched_payload = _compute_matched_count_payload(db, one_year_ago)
    announce_by_month_payload = _compute_announce_by_month_payload(db, one_year_ago)
    result_by_month_payload = _compute_result_by_month_payload(db, one_year_ago)
    rebuilt_at = utcnow()
    for snapshot_key, payload in (
        (SNAPSHOT_KEY_AGENCY_TOP10, agency_payload),
        (SNAPSHOT_KEY_MATCHED_COUNT, matched_payload),
        (SNAPSHOT_KEY_ANNOUNCE_BY_MONTH, announce_by_month_payload),
        (SNAPSHOT_KEY_RESULT_BY_MONTH, result_by_month_payload),
    ):
        row = db.get(BidCompareStatsSnapshot, snapshot_key)
        if row is None:
            row = BidCompareStatsSnapshot(
                snapshot_key=snapshot_key,
                payload=payload,
                window_days=COMPARE_STATS_WINDOW_DAYS,
                rebuilt_at=rebuilt_at,
            )
            db.add(row)
        else:
            row.payload = payload
            row.window_days = COMPARE_STATS_WINDOW_DAYS
            row.rebuilt_at = rebuilt_at
    db.commit()
    elapsed = (utcnow() - started).total_seconds()
    logger.info(
        "비교 통계 스냅샷 재집계 완료 (4건, %.1fs)",
        elapsed,
    )
    return {
        "status": "success",
        "snapshots": [
            SNAPSHOT_KEY_AGENCY_TOP10,
            SNAPSHOT_KEY_MATCHED_COUNT,
            SNAPSHOT_KEY_ANNOUNCE_BY_MONTH,
            SNAPSHOT_KEY_RESULT_BY_MONTH,
        ],
        "window_days": COMPARE_STATS_WINDOW_DAYS,
        "rebuilt_at": rebuilt_at.isoformat(),
        "elapsed_seconds": elapsed,
    }


__all__ = [
    "COMPARE_STATS_SNAPSHOT_MAX_AGE_DAYS",
    "COMPARE_STATS_WINDOW_DAYS",
    "MONTHLY_ITEM_KEYS",
    "SNAPSHOT_KEY_AGENCY_TOP10",
    "SNAPSHOT_KEY_ANNOUNCE_BY_MONTH",
    "SNAPSHOT_KEY_MATCHED_COUNT",
    "SNAPSHOT_KEY_RESULT_BY_MONTH",
    "get_compare_stats_snapshot",
    "get_snapshot_with_age",
    "is_agency_payload_usable",
    "is_monthly_payload_usable",
    "is_snapshot_fresh",
    "rebuild_compare_stats_snapshots",
]
