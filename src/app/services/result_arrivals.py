"""
src/app/services/result_arrivals.py

조달청 상류가 늦게라도 낙찰결과를 보충하는지 추적하는 지표.

docs/analysis/servc_upstream_recheck_20260928.md 는 2026-09-28 기준으로 대형 용역
공백이 지연이 아니라 영구 누락 성분 우세라고 판정했다. 상류가 나중에 등록을
시작하면 이 지표가 올라간다. 최근 창에 수집된 낙찰결과 중, 매칭되는 공고의
개찰일이 오래된(늦은 도착) 건수를 분류 x 규모(large/small)별로 센다. 별도 상태
저장 없이 bid_results.collected_at 과 공고 개찰일만으로 계산한다.

읽기 전용 함수다. DB 쓰기는 하지 않는다. 조회는 bid_results 를 collected_at
범위로 먼저 좁히고(인덱스 bid_results_collected_at_25a564b9 사용), 공고는 그
결과의 공고번호 집합으로만 조회한다. 대형 임계, 분류 목록, 차수 정규화, MySQL
실행 시간 힌트는 result_coverage.py 정의를 그대로 import 해 쓴다(값을 복제하지
않는다).
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.result_coverage import (
    BAND_LARGE,
    BAND_SMALL,
    CANCELLED_NTCE_KIND,
    LARGE_PRICE_THRESHOLD,
    MYSQL_EXECUTION_LIMIT_HINT,
    TARGET_CATEGORIES,
    normalize_ord,
)

# 공고 조회는 결과의 공고번호 집합을 IN 절로 넘긴다. 운영 7일 창은 수만 건에
# 이를 수 있어 SQLite 변수 한도와 MySQL 패킷 한도를 피하려고 나눠 조회한다
# (src/app/models/bids.py 의 preload_matching_announcements 와 같은 500 단위).
NOTICE_CHUNK_SIZE = 500


def _with_mysql_execution_limit(stmt: Any) -> Any:
    return stmt.prefix_with(MYSQL_EXECUTION_LIMIT_HINT, dialect="mysql")


def _empty_rows() -> list[dict[str, Any]]:
    return [
        {
            "category": category,
            "band": band,
            "late_arrivals": 0,
            "total_arrivals": 0,
        }
        for category in TARGET_CATEGORIES
        for band in (BAND_LARGE, BAND_SMALL)
    ]


def compute_late_arrivals(
    db: Session,
    *,
    as_of: date,
    window_days: int = 7,
    late_after_days: int = 28,
) -> list[dict[str, Any]]:
    """최근 창에 수집된 낙찰결과의 늦은 도착 건수를 분류 x 규모별로 계산한다.

    collected_at 이 [as_of - window_days, as_of) 에 드는 결과만 대상으로 한다.
    결과는 (bid_ntce_no, category, 정규화 차수)가 일치하고 ntce_kind_nm 이
    '취소공고' 가 아닌 공고와 매칭될 때만 센다. 규모는 그 공고의 presmpt_prce 로
    정하며(대형은 LARGE_PRICE_THRESHOLD 이상), 매칭된 결과의 개찰일 openg_dt 가
    collected_at 보다 late_after_days 일 이상 앞서면 '늦은 도착' 이다.

    반환 행은 TARGET_CATEGORIES x (large, small) 마다 하나씩이며 각 행은
    category, band, late_arrivals, total_arrivals 를 가진다. total_arrivals 는
    창 안에서 수집되어 공고가 매칭된 전체 결과 수다. 공고가 없거나 취소공고만
    있는 결과는 late 와 total 어디에도 세지 않는다.

    조회는 bid_results 를 collected_at 범위로 먼저 좁히고, 공고는 그 결과의
    공고번호 집합으로 NOTICE_CHUNK_SIZE 단위로 나눠 가져온다. 읽기 전용이다.
    """
    window_start_dt = datetime.combine(as_of - timedelta(days=max(window_days, 0)), time.min)
    window_end_dt = datetime.combine(as_of, time.min)

    result_rows: list[Any] = _with_mysql_execution_limit(
        db.query(
            BidResult.bid_ntce_no,
            BidResult.bid_ntce_ord,
            BidResult.category,
            BidResult.collected_at,
        ).filter(
            BidResult.category.in_(TARGET_CATEGORIES),
            BidResult.collected_at >= window_start_dt,
            BidResult.collected_at < window_end_dt,
        )
    ).all()
    if not result_rows:
        return _empty_rows()

    notice_numbers = sorted({row[0] for row in result_rows})
    announcement_rows: list[Any] = []
    for start in range(0, len(notice_numbers), NOTICE_CHUNK_SIZE):
        chunk = notice_numbers[start : start + NOTICE_CHUNK_SIZE]
        announcement_rows.extend(
            _with_mysql_execution_limit(
                db.query(
                    BidAnnouncement.bid_ntce_no,
                    BidAnnouncement.bid_ntce_ord,
                    BidAnnouncement.category,
                    BidAnnouncement.presmpt_prce,
                    BidAnnouncement.openg_dt,
                    BidAnnouncement.ntce_kind_nm,
                ).filter(
                    BidAnnouncement.bid_ntce_no.in_(chunk),
                    BidAnnouncement.category.in_(TARGET_CATEGORIES),
                )
            ).all()
        )

    announcements: dict[tuple[str, str, str], tuple[int | None, datetime | None]] = {}
    for no, ord_, category, presmpt_prce, openg_dt, ntce_kind_nm in announcement_rows:
        if ntce_kind_nm == CANCELLED_NTCE_KIND:
            continue
        announcements[(no, category, normalize_ord(ord_))] = (presmpt_prce, openg_dt)

    late_threshold = timedelta(days=max(late_after_days, 0))
    counts: dict[tuple[str, str], list[int]] = {}
    for no, ord_, category, collected_at in result_rows:
        announcement = announcements.get((no, category, normalize_ord(ord_)))
        if announcement is None:
            continue
        presmpt_prce, openg_dt = announcement
        band = BAND_LARGE if (presmpt_prce or 0) >= LARGE_PRICE_THRESHOLD else BAND_SMALL
        bucket = counts.setdefault((category, band), [0, 0])
        bucket[0] += 1
        if openg_dt is not None and collected_at - openg_dt >= late_threshold:
            bucket[1] += 1

    return [
        {
            "category": category,
            "band": band,
            "late_arrivals": counts.get((category, band), [0, 0])[1],
            "total_arrivals": counts.get((category, band), [0, 0])[0],
        }
        for category in TARGET_CATEGORIES
        for band in (BAND_LARGE, BAND_SMALL)
    ]
