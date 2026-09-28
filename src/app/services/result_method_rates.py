"""
src/app/services/result_method_rates.py

낙찰결과 매칭률을 분류 x 규모 x 입찰방식별로 집계한다.

docs/analysis/thng_match_rate_20260824.md 8절 A3 는 직찰·우편·상시 등 비전자
방식의 매칭률이 2026-03 이후 3~8% 로 구조적으로 낮아 전체 매칭률을 끌어내린다고
짚었다. 사용자는 이 방식을 대형 매칭률 표본에서 분리하는 대신 별도 리포트
지표로만 두기로 승인했다. 이 모듈은 최근 성숙 개찰 주를 합산해 방식별 매칭률과
전체 대비 비중을 돌려준다. 경고 판정에는 쓰지 않는다.

읽기 전용 함수다. DB 쓰기는 하지 않는다. 매칭 정의, 취소공고 제외, 대형 임계,
차수 정규화, 성숙 주 계산은 result_coverage.py 정의를 그대로 가져다 쓴다(값을
복제하지 않는다). 입찰방식 목록은 데이터에서 뽑으며 하드코딩하지 않는다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import or_
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.result_coverage import (
    BAND_LARGE,
    BAND_SMALL,
    CANCELLED_NTCE_KIND,
    LARGE_PRICE_THRESHOLD,
    MYSQL_EXECUTION_LIMIT_HINT,
    NOTICE_LOOKBACK_DAYS,
    NULL_METHOD_LABEL,
    TARGET_CATEGORIES,
    _mature_week_starts,
    normalize_ord,
    week_start,
)

# 결과 조회 폭은 result_coverage.py 와 맞춘다. 개찰일보다 늦게 등록된 결과를
# 놓치지 않도록 앞뒤로 여유를 둔다.
RESULT_LOOKBACK_DAYS = 14
RESULT_LOOKAHEAD_DAYS = 90


def _with_mysql_execution_limit(stmt: Any) -> Any:
    return stmt.prefix_with(MYSQL_EXECUTION_LIMIT_HINT, dialect="mysql")


def compute_method_match_rates(
    db: Session,
    *,
    as_of: date,
    weeks: int = 4,
    min_elapsed_days: int = 28,
) -> list[dict[str, Any]]:
    """최근 성숙 개찰 주 weeks 개를 합산해 분류 x 규모 x 입찰방식별 매칭률을 계산한다.

    대상 공고는 openg_dt 가 성숙 주(월요일 시작 7일) 안에 들고 ntce_kind_nm 이
    '취소공고' 가 아닌 것(NULL 포함)이다. 대형은 presmpt_prce >=
    LARGE_PRICE_THRESHOLD, 그 밖(NULL 포함)은 소형이다. 매칭은
    (bid_ntce_no, category, 정규화 차수)가 낙찰결과에 존재하는 것이다.
    입찰방식은 bid_methd_nm 이며 NULL 은 NULL_METHOD_LABEL 로 묶는다. 방식 목록은
    데이터에서 뽑고 하드코딩하지 않는다.

    반환 행은 (분류, 규모, 방식) 조합마다 하나씩이며 각 행은 category, band,
    method, announcements, matched, rate, share 를 가진다. share 는 그 행의
    announcements 를 전체 합계로 나눈 비중이라 모든 행의 share 합은 1 이다.
    공고가 하나도 없으면 빈 목록을 돌려준다.

    조회는 성숙 주 구간을 한 블록으로 좁혀 공고는 bid_ntce_dt 를
    [블록 시작 - NOTICE_LOOKBACK_DAYS 일, 블록 끝], openg_dt 를 [블록 시작,
    블록 끝]로, 결과는 rl_openg_dt 를 [블록 시작 - RESULT_LOOKBACK_DAYS 일,
    블록 끝 + RESULT_LOOKAHEAD_DAYS 일]로 가져온다. 읽기 전용이다.
    """
    mature_starts = _mature_week_starts(as_of, weeks, min_elapsed_days)
    if not mature_starts:
        return []

    target_weeks = set(mature_starts)
    block_start = min(mature_starts)
    block_end = max(mature_starts) + timedelta(days=6)
    block_start_dt = datetime.combine(block_start, time.min)
    block_end_dt = datetime.combine(block_end, time.max)

    announcement_rows: list[Any] = _with_mysql_execution_limit(
        db.query(
            BidAnnouncement.bid_ntce_no,
            BidAnnouncement.bid_ntce_ord,
            BidAnnouncement.category,
            BidAnnouncement.presmpt_prce,
            BidAnnouncement.openg_dt,
            BidAnnouncement.bid_methd_nm,
        ).filter(
            BidAnnouncement.bid_ntce_dt
            >= datetime.combine(block_start - timedelta(days=NOTICE_LOOKBACK_DAYS), time.min),
            BidAnnouncement.bid_ntce_dt <= block_end_dt,
            BidAnnouncement.openg_dt >= block_start_dt,
            BidAnnouncement.openg_dt <= block_end_dt,
            BidAnnouncement.category.in_(TARGET_CATEGORIES),
            or_(
                BidAnnouncement.ntce_kind_nm.is_(None),
                BidAnnouncement.ntce_kind_nm != CANCELLED_NTCE_KIND,
            ),
        )
    ).all()
    if not announcement_rows:
        return []

    result_rows: list[Any] = _with_mysql_execution_limit(
        db.query(
            BidResult.bid_ntce_no,
            BidResult.bid_ntce_ord,
            BidResult.category,
        ).filter(
            BidResult.category.in_(TARGET_CATEGORIES),
            BidResult.rl_openg_dt
            >= datetime.combine(block_start - timedelta(days=RESULT_LOOKBACK_DAYS), time.min),
            BidResult.rl_openg_dt
            <= datetime.combine(block_end + timedelta(days=RESULT_LOOKAHEAD_DAYS), time.max),
        )
    ).all()
    result_keys = {(no, category, normalize_ord(ord_)) for no, ord_, category in result_rows}

    counts: dict[tuple[str, str, str], list[int]] = {}
    for no, ord_, category, presmpt_prce, openg_dt, bid_methd_nm in announcement_rows:
        if openg_dt is None:
            continue
        if week_start(openg_dt.date()) not in target_weeks:
            continue
        band = BAND_LARGE if (presmpt_prce or 0) >= LARGE_PRICE_THRESHOLD else BAND_SMALL
        method = bid_methd_nm if bid_methd_nm is not None else NULL_METHOD_LABEL
        bucket = counts.setdefault((category, band, method), [0, 0])
        bucket[0] += 1
        if (no, category, normalize_ord(ord_)) in result_keys:
            bucket[1] += 1

    total_announcements = sum(bucket[0] for bucket in counts.values())
    if total_announcements <= 0:
        return []

    rows: list[dict[str, Any]] = []
    for category in TARGET_CATEGORIES:
        for band in (BAND_LARGE, BAND_SMALL):
            methods = sorted(
                method for (cat, bnd, method) in counts if cat == category and bnd == band
            )
            for method in methods:
                announcements, matched = counts[(category, band, method)]
                rows.append(
                    {
                        "category": category,
                        "band": band,
                        "method": method,
                        "announcements": announcements,
                        "matched": matched,
                        "rate": matched / announcements,
                        "share": announcements / total_announcements,
                    }
                )
    return rows
