"""
src/app/services/result_coverage.py

개찰 완료 공고 대비 낙찰결과 매칭률 집계와 경고 판정.

2026-09-26 C1 분석(docs/analysis/result_collection_gap_20260926.md 6절 R3)에서
대형 공고 낙찰결과가 조달청 API 쪽에서 미등록·지연되어 매칭률이 급락했지만,
수집 적재 건수만 보는 감시로는 잡히지 않았다. 이 모듈은 매칭률 자체를
분류 x 개찰 주 x 규모(대형/소형)로 계산해 전년 동기와 비교한다.

읽기 전용 함수다. DB 쓰기는 하지 않는다. openg_dt 에 인덱스가 없으므로 공고
조회는 반드시 bid_ntce_dt 범위(ix_bid_ann_dt_cat)로 먼저 좁힌 뒤 openg_dt
조건을 더한다. 차수 정규화와 주 집계는 파이썬에서 해 SQLite 테스트와 동작을
같게 유지한다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement, BidResult

LARGE_PRICE_THRESHOLD = 230_000_000
MIN_WEEK_SAMPLES = 100
RATE_DROP_ALERT = 0.10

TARGET_CATEGORIES = ("Servc", "Cnstwk", "Thng")

MYSQL_EXECUTION_LIMIT_HINT = "/*+ MAX_EXECUTION_TIME(120000) */"
CANCELLED_NTCE_KIND = "취소공고"
BASELINE_OFFSET_DAYS = 364

BAND_LARGE = "large"
BAND_SMALL = "small"


def normalize_ord(value: Any) -> str:
    """차수를 앞뒤 공백 제거, 선행 0 제거, 3자리 왼쪽 0 채움으로 정규화한다.

    '000'->'000', '0'->'000', '1'->'001', '001'->'001', ' 2 '->'002'.
    """
    text = str(value or "").strip()
    return (text.lstrip("0") or "0").zfill(3)


def week_start(day: date) -> date:
    """주 시작(월요일)을 돌려준다."""
    return day - timedelta(days=day.weekday())


def _mature_week_starts(as_of: date, weeks: int, min_elapsed_days: int) -> list[date]:
    """성숙 주(주 끝 날이 as_of - min_elapsed_days 이하) 시작 목록을 최신부터 돌려준다."""
    latest_limit = as_of - timedelta(days=min_elapsed_days)
    start = week_start(latest_limit - timedelta(days=6))
    return [start - timedelta(days=7 * i) for i in range(max(weeks, 0))]


def _rate(matched: int, announcements: int) -> float | None:
    if announcements <= 0:
        return None
    return matched / announcements


def _with_mysql_execution_limit(stmt: Any) -> Any:
    return stmt.prefix_with(MYSQL_EXECUTION_LIMIT_HINT, dialect="mysql")


def compute_result_match_rates(
    db: Session,
    *,
    as_of: date,
    weeks: int = 8,
    min_elapsed_days: int = 28,
) -> list[dict[str, Any]]:
    """분류 x 성숙 개찰 주 x 규모별 매칭률과 전년 동기 매칭률을 계산한다.

    공고는 openg_dt 가 개찰 주(월요일 시작 7일) 안에 들고 ntce_kind_nm 이
    '취소공고' 가 아닌 것(NULL 포함)만 센다. 대형은 presmpt_prce >=
    LARGE_PRICE_THRESHOLD, 그 밖(NULL 포함)은 소형이다. 매칭은
    (bid_ntce_no, category, 정규화 차수)가 낙찰결과에 존재하는 것이다.
    반환 행의 baseline_* 필드는 364일 전 같은 주의 값이다.
    """
    mature_starts = _mature_week_starts(as_of, weeks, min_elapsed_days)
    if not mature_starts:
        return []

    all_starts = sorted(
        set(mature_starts) | {s - timedelta(days=BASELINE_OFFSET_DAYS) for s in mature_starts}
    )
    range_start = all_starts[0] - timedelta(days=180)
    range_end = all_starts[-1] + timedelta(days=6)
    range_start_dt = datetime.combine(range_start, time.min)
    range_end_dt = datetime.combine(range_end, time.max)
    target_weeks = set(all_starts)

    announcement_rows = _with_mysql_execution_limit(
        db.query(
            BidAnnouncement.bid_ntce_no,
            BidAnnouncement.bid_ntce_ord,
            BidAnnouncement.category,
            BidAnnouncement.presmpt_prce,
            BidAnnouncement.openg_dt,
        ).filter(
            BidAnnouncement.bid_ntce_dt >= range_start_dt,
            BidAnnouncement.bid_ntce_dt <= range_end_dt,
            BidAnnouncement.openg_dt >= range_start_dt,
            BidAnnouncement.openg_dt <= range_end_dt,
            BidAnnouncement.category.in_(TARGET_CATEGORIES),
            or_(
                BidAnnouncement.ntce_kind_nm.is_(None),
                BidAnnouncement.ntce_kind_nm != CANCELLED_NTCE_KIND,
            ),
        )
    ).all()

    result_rows = _with_mysql_execution_limit(
        db.query(
            BidResult.bid_ntce_no,
            BidResult.bid_ntce_ord,
            BidResult.category,
        ).filter(
            BidResult.category.in_(TARGET_CATEGORIES),
            BidResult.rl_openg_dt >= datetime.combine(range_start - timedelta(days=14), time.min),
        )
    ).all()
    result_keys = {(no, category, normalize_ord(ord_)) for no, ord_, category in result_rows}

    counts: dict[tuple[str, date, str], list[int]] = {}
    for row in announcement_rows:
        no, ord_, category, presmpt_prce, openg_dt = row
        if openg_dt is None:
            continue
        start = week_start(openg_dt.date())
        if start not in target_weeks:
            continue
        band = BAND_LARGE if (presmpt_prce or 0) >= LARGE_PRICE_THRESHOLD else BAND_SMALL
        key = (category, start, band)
        bucket = counts.setdefault(key, [0, 0])
        bucket[0] += 1
        if (no, category, normalize_ord(ord_)) in result_keys:
            bucket[1] += 1

    rows: list[dict[str, Any]] = []
    for start in sorted(mature_starts):
        baseline = start - timedelta(days=BASELINE_OFFSET_DAYS)
        for category in TARGET_CATEGORIES:
            for band in (BAND_LARGE, BAND_SMALL):
                announcements, matched = counts.get((category, start, band), [0, 0])
                baseline_announcements, baseline_matched = counts.get(
                    (category, baseline, band), [0, 0]
                )
                rows.append(
                    {
                        "category": category,
                        "week_start": start.isoformat(),
                        "band": band,
                        "announcements": announcements,
                        "matched": matched,
                        "rate": _rate(matched, announcements),
                        "baseline_announcements": baseline_announcements,
                        "baseline_matched": baseline_matched,
                        "baseline_rate": _rate(baseline_matched, baseline_announcements),
                    }
                )
    return rows


def evaluate_match_rate_alerts(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """분류별 가장 최근 성숙 주의 대형 행에서 매칭률 급락 경고 대상을 판정한다.

    announcements >= MIN_WEEK_SAMPLES, baseline_announcements >=
    MIN_WEEK_SAMPLES, baseline_rate - rate >= RATE_DROP_ALERT 세 조건을
    모두 만족해야 경고 대상이다.
    """
    latest_large: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("band") != BAND_LARGE:
            continue
        category = str(row.get("category", ""))
        current = latest_large.get(category)
        if current is None or str(row["week_start"]) > str(current["week_start"]):
            latest_large[category] = row

    alerts: list[dict[str, Any]] = []
    for category in TARGET_CATEGORIES:
        candidate = latest_large.get(category)
        if candidate is None:
            continue
        row = candidate
        if row["announcements"] < MIN_WEEK_SAMPLES:
            continue
        if row["baseline_announcements"] < MIN_WEEK_SAMPLES:
            continue
        if row["rate"] is None or row["baseline_rate"] is None:
            continue
        # 0.6 - 0.5 같은 부동소수점 오차로 경계값 0.10 이 밀리지 않게 6자리에서 반올림한다.
        drop = round(row["baseline_rate"] - row["rate"], 6)
        if drop >= RATE_DROP_ALERT:
            alerts.append(
                {
                    "category": category,
                    "week_start": row["week_start"],
                    "rate": row["rate"],
                    "baseline_rate": row["baseline_rate"],
                    "announcements": row["announcements"],
                    "baseline_announcements": row["baseline_announcements"],
                }
            )
    return alerts
