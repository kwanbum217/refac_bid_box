"""
tests/test_result_coverage.py

개찰 완료 공고 대비 낙찰결과 매칭률 집계와 경고 판정 회귀 테스트.

conftest 의 SQLite 격리 DB(isolated_db)로 검증한다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any

import pytest
from sqlalchemy import event

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.result_coverage import (
    BASELINE_OFFSET_DAYS,
    BASELINE_WINDOW_WEEKS,
    LARGE_PRICE_THRESHOLD,
    MIN_WEEK_SAMPLES,
    NOTICE_LOOKBACK_DAYS,
    _is_later_cancelled,
    _is_offline_bid,
    compute_result_match_rates,
    evaluate_match_rate_alerts,
    normalize_ord,
    parse_alert_suppressions,
)

# 2026-08-24 는 월요일이다. as_of = W + 34 일(2026-09-27, 일요일)이면
# 개찰 주 끝(W+6)이 as_of - 28일과 정확히 같아 성숙 경계가 된다.
W = date(2026, 8, 24)
AS_OF = W + timedelta(days=34)


def _openg(day: date) -> datetime:
    return datetime.combine(day, time(10, 0))


def _add_announcement(
    db,
    no: str,
    ord_: str,
    category: str,
    openg_day: date,
    *,
    presmpt_prce: int | None = None,
    ntce_kind_nm: str | None = None,
    ntce_dt: datetime | None = None,
    bid_methd_nm: str | None = None,
) -> None:
    db.add(
        BidAnnouncement(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category=category,
            bid_ntce_dt=(
                ntce_dt if ntce_dt is not None else _openg(openg_day) - timedelta(days=14)
            ),
            openg_dt=_openg(openg_day),
            presmpt_prce=presmpt_prce,
            ntce_kind_nm=ntce_kind_nm,
            bid_methd_nm=bid_methd_nm,
        )
    )


def _add_result(db, no: str, ord_: str, category: str, openg_day: date) -> None:
    db.add(
        BidResult(
            bid_ntce_no=no,
            bid_ntce_ord=ord_,
            category=category,
            rl_openg_dt=_openg(openg_day),
        )
    )


def _add_method_batch(db, prefix, day, method, total, matched, category="Thng"):
    for i in range(total):
        no = f"{prefix}{i:05d}"
        _add_announcement(
            db,
            no,
            "001",
            category,
            day,
            presmpt_prce=LARGE_PRICE_THRESHOLD,
            bid_methd_nm=method,
        )
        if i < matched:
            _add_result(db, no, "001", category, day)


def _row_of(rows, category, band, week_start):
    matched = [
        row
        for row in rows
        if row["category"] == category
        and row["band"] == band
        and row["week_start"] == week_start.isoformat()
    ]
    assert len(matched) == 1
    return matched[0]


def _alert_row(
    *,
    rate=0.5,
    baseline_rate=0.6,
    adjusted_rate=0.5,
    baseline_multi_rate=0.6,
    announcements=MIN_WEEK_SAMPLES,
    baseline_announcements=MIN_WEEK_SAMPLES,
    baseline_multi_announcements=MIN_WEEK_SAMPLES,
    band="large",
    category="Servc",
    week_start="2026-08-24",
):
    return {
        "category": category,
        "week_start": week_start,
        "band": band,
        "announcements": announcements,
        "matched": 0,
        "rate": rate,
        "baseline_announcements": baseline_announcements,
        "baseline_matched": 0,
        "baseline_rate": baseline_rate,
        "baseline_multi_announcements": baseline_multi_announcements,
        "baseline_multi_matched": 0,
        "baseline_multi_rate": baseline_multi_rate,
        "adjusted_rate": adjusted_rate,
    }


def test_normalize_ord():
    assert normalize_ord("000") == "000"
    assert normalize_ord("0") == "000"
    assert normalize_ord("1") == "001"
    assert normalize_ord("001") == "001"
    assert normalize_ord(" 2 ") == "002"
    assert normalize_ord("0000") == "000"
    assert normalize_ord(None) == "000"


def test_cancelled_excluded_and_null_kind_included(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-A00001", "001", "Servc", W, ntce_kind_nm=None)
    _add_announcement(db, "2026-A00002", "001", "Servc", W, ntce_kind_nm="취소공고")
    _add_announcement(db, "2026-A00003", "001", "Servc", W, ntce_kind_nm="일반공고")
    _add_result(db, "2026-A00001", "001", "Servc", W)
    _add_result(db, "2026-A00002", "001", "Servc", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Servc", "small", W)
    assert row["announcements"] == 2
    assert row["matched"] == 1


def test_large_small_boundary_and_null_price(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-B00001", "001", "Cnstwk", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_announcement(db, "2026-B00002", "001", "Cnstwk", W, presmpt_prce=LARGE_PRICE_THRESHOLD - 1)
    _add_announcement(db, "2026-B00003", "001", "Cnstwk", W, presmpt_prce=None)
    _add_result(db, "2026-B00001", "001", "Cnstwk", W)
    _add_result(db, "2026-B00002", "001", "Cnstwk", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    large = _row_of(rows, "Cnstwk", "large", W)
    small = _row_of(rows, "Cnstwk", "small", W)
    assert large["announcements"] == 1
    assert large["matched"] == 1
    assert small["announcements"] == 2
    # B00002 만 결과가 있다. B00003(NULL 추정가격, 결과 없음)은 미매칭이다.
    assert small["matched"] == 1


def test_mature_week_selection_boundary(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-C00001", "001", "Servc", W)
    _add_result(db, "2026-C00001", "001", "Servc", W)
    db.commit()

    # 주 끝(W+6)이 as_of - 28일과 같으면 성숙이다. 3분류 x 2규모 행이 모두 W 주다.
    rows = compute_result_match_rates(db, as_of=W + timedelta(days=34), weeks=1)
    assert len(rows) == 6
    assert {row["week_start"] for row in rows} == {W.isoformat()}

    # 하루 이르면 W 주는 아직 성숙하지 않고 직전 주가 최근 성숙 주다.
    rows = compute_result_match_rates(db, as_of=W + timedelta(days=33), weeks=1)
    assert {row["week_start"] for row in rows} == {(W - timedelta(days=7)).isoformat()}


def test_baseline_year_ago_rate(isolated_db):
    db = isolated_db
    _add_announcement(db, "2026-D00001", "001", "Thng", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_announcement(db, "2026-D00002", "001", "Thng", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_result(db, "2026-D00001", "001", "Thng", W)

    baseline = W - timedelta(days=364)
    _add_announcement(
        db, "2025-D00001", "001", "Thng", baseline, presmpt_prce=LARGE_PRICE_THRESHOLD
    )
    _add_announcement(
        db, "2025-D00002", "001", "Thng", baseline, presmpt_prce=LARGE_PRICE_THRESHOLD
    )
    _add_result(db, "2025-D00001", "001", "Thng", baseline)
    _add_result(db, "2025-D00002", "001", "Thng", baseline)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Thng", "large", W)
    assert row["announcements"] == 2
    assert row["matched"] == 1
    assert row["rate"] == pytest.approx(0.5)
    assert row["baseline_announcements"] == 2
    assert row["baseline_matched"] == 2
    assert row["baseline_rate"] == pytest.approx(1.0)


def test_gap_rows_between_blocks_are_not_fetched(isolated_db):
    """두 블록 사이 간극 구간에 개찰한 공고와 결과는 DB 조회로 들어오지 않는다."""
    db = isolated_db
    # 현재 블록 시작(W) 200일 전은 전년 블록 끝(2025-08-31)과 현재 블록 시작 사이다.
    gap_day = W - timedelta(days=200)
    _add_announcement(db, "2026-F00001", "001", "Servc", gap_day)
    _add_result(db, "2026-F00001", "001", "Servc", gap_day)
    db.commit()

    captured: list[Any] = []

    def _capture(conn: Any, cursor: Any, statement: str, parameters: Any, *args: Any) -> None:
        if "bid_announcements" in statement:
            captured.append(parameters)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    row = _row_of(rows, "Servc", "small", W)
    assert row["announcements"] == 0
    assert row["matched"] == 0

    # 공고 조회는 블록 두 개다. 개찰 경계 인자에 간극 주 날짜가 없다.
    assert len(captured) == 2
    for params in captured:
        assert str(gap_day) not in str(params)


def test_returned_rows_match_previous_contract(isolated_db):
    """기존 픽스처 데이터에서 반환 행은 수정 전 계약과 같다."""
    db = isolated_db
    _add_announcement(db, "2026-G00001", "001", "Thng", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_result(db, "2026-G00001", "001", "Thng", W)
    baseline = W - timedelta(days=364)
    _add_announcement(
        db, "2025-G00001", "001", "Thng", baseline, presmpt_prce=LARGE_PRICE_THRESHOLD
    )
    _add_result(db, "2025-G00001", "001", "Thng", baseline)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    assert len(rows) == 6
    row = _row_of(rows, "Thng", "large", W)
    # 기존 필드 값은 수정 전 계약 그대로다.
    existing_fields = {
        "category": "Thng",
        "week_start": W.isoformat(),
        "band": "large",
        "announcements": 1,
        "matched": 1,
        "rate": 1.0,
        "baseline_announcements": 1,
        "baseline_matched": 1,
        "baseline_rate": 1.0,
    }
    assert {key: row[key] for key in existing_fields} == existing_fields
    # A1 다주 기저와 A2 보정률 필드가 추가됐다. 기저 5주에 이 주 하나뿐이라 1.0 이다.
    assert row["baseline_multi_announcements"] == 1
    assert row["baseline_multi_matched"] == 1
    assert row["baseline_multi_rate"] == 1.0
    assert row["adjusted_rate"] == 1.0


def test_overlapping_blocks_are_merged_without_double_count(isolated_db):
    """weeks 가 커서 전년 블록과 현재 블록이 겹치면 하나로 합쳐 중복 집계되지 않는다."""
    db = isolated_db
    _add_announcement(db, "2026-H00001", "001", "Servc", W)
    _add_result(db, "2026-H00001", "001", "Servc", W)
    baseline = W - timedelta(days=364)
    _add_announcement(db, "2025-H00001", "001", "Servc", baseline)
    _add_result(db, "2025-H00001", "001", "Servc", baseline)
    db.commit()

    captured: list[Any] = []

    def _capture(conn: Any, cursor: Any, statement: str, parameters: Any, *args: Any) -> None:
        if "bid_announcements" in statement:
            captured.append(parameters)

    engine = db.get_bind()
    event.listen(engine, "before_cursor_execute", _capture)
    try:
        rows = compute_result_match_rates(db, as_of=AS_OF, weeks=53)
    finally:
        event.remove(engine, "before_cursor_execute", _capture)

    # 53주면 블록이 겹치므로 공고 조회가 하나로 합쳐진다.
    assert len(captured) == 1
    row = _row_of(rows, "Servc", "small", W)
    assert row["announcements"] == 1
    assert row["matched"] == 1
    baseline_row = _row_of(rows, "Servc", "small", baseline)
    assert baseline_row["announcements"] == 1
    assert baseline_row["matched"] == 1


def test_notice_lookback_inclusive_lower_boundary(isolated_db):
    """공고일이 블록 시작 - 365일(당일 00:00)인 공고는 집계된다."""
    db = isolated_db
    _add_announcement(
        db,
        "2026-I00001",
        "001",
        "Servc",
        W,
        ntce_dt=datetime.combine(W - timedelta(days=NOTICE_LOOKBACK_DAYS), time.min),
    )
    _add_result(db, "2026-I00001", "001", "Servc", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Servc", "small", W)
    assert row["announcements"] == 1
    assert row["matched"] == 1


def test_notice_lookback_exclusive_lower_boundary(isolated_db):
    """공고일이 블록 시작 - 366일인 공고는 집계되지 않는다."""
    db = isolated_db
    _add_announcement(
        db,
        "2026-J00001",
        "001",
        "Servc",
        W,
        ntce_dt=datetime.combine(W - timedelta(days=NOTICE_LOOKBACK_DAYS + 1), time.min),
    )
    _add_result(db, "2026-J00001", "001", "Servc", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Servc", "small", W)
    assert row["announcements"] == 0
    assert row["matched"] == 0


def test_large_announcement_older_than_180_day_lookback_counted(isolated_db):
    """공고일이 개찰일보다 200일 앞선 대형 공고는 180일 하한에서는 빠졌지만 집계된다."""
    db = isolated_db
    _add_announcement(
        db,
        "2026-K00001",
        "001",
        "Cnstwk",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        ntce_dt=_openg(W) - timedelta(days=200),
    )
    _add_result(db, "2026-K00001", "001", "Cnstwk", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Cnstwk", "large", W)
    assert row["announcements"] == 1
    assert row["matched"] == 1


def _two_alert_weeks(**kwargs):
    return [
        _alert_row(week_start="2026-08-24", **kwargs),
        _alert_row(week_start="2026-08-17", **kwargs),
    ]


def test_alert_rule_boundaries():
    # 보정률 하락폭 경계 0.10, 표본 100 경계를 두 주 연속 만족하면 경고다.
    alerts = evaluate_match_rate_alerts(_two_alert_weeks())
    assert len(alerts) == 1
    assert alerts[0]["category"] == "Servc"
    assert alerts[0]["week_start"] == "2026-08-24"
    assert alerts[0]["previous_week_start"] == "2026-08-17"
    assert alerts[0]["adjusted_rate"] == 0.5
    assert alerts[0]["baseline_multi_rate"] == 0.6
    assert alerts[0]["previous_adjusted_rate"] == 0.5
    assert alerts[0]["previous_baseline_multi_rate"] == 0.6
    # 기존 키는 그대로 유지된다.
    assert alerts[0]["rate"] == 0.5
    assert alerts[0]["baseline_rate"] == 0.6
    assert alerts[0]["announcements"] == MIN_WEEK_SAMPLES

    # 보정률 하락폭 0.10 미만은 두 주 모두 만족해도 경고가 아니다.
    assert (
        evaluate_match_rate_alerts(_two_alert_weeks(adjusted_rate=0.501, baseline_multi_rate=0.6))
        == []
    )

    # 실측 공고 수 경계 미만은 경고가 아니다.
    assert evaluate_match_rate_alerts(_two_alert_weeks(announcements=MIN_WEEK_SAMPLES - 1)) == []

    # 다주 기저 공고 수 경계 미만은 경고가 아니다.
    assert (
        evaluate_match_rate_alerts(
            _two_alert_weeks(baseline_multi_announcements=MIN_WEEK_SAMPLES - 1)
        )
        == []
    )

    # 소형 행은 대상이 아니다.
    assert (
        evaluate_match_rate_alerts(
            [
                _alert_row(band="small", week_start="2026-08-24"),
                _alert_row(band="small", week_start="2026-08-17"),
            ]
        )
        == []
    )


def test_alert_requires_previous_week_row():
    # 직전 성숙 주 대형 행이 없으면 경고하지 않는다.
    assert evaluate_match_rate_alerts([_alert_row(week_start="2026-08-24")]) == []


def test_alert_requires_both_consecutive_weeks():
    # 최근 주만 조건을 넘고 직전 주는 미달이면 경고하지 않는다.
    rows = [
        _alert_row(week_start="2026-08-24", adjusted_rate=0.4, baseline_multi_rate=0.6),
        _alert_row(week_start="2026-08-17", adjusted_rate=0.55, baseline_multi_rate=0.6),
    ]
    assert evaluate_match_rate_alerts(rows) == []

    # 두 주 모두 조건을 넘으면 최근 주를 경고로 보고한다.
    rows = [
        _alert_row(week_start="2026-08-24", adjusted_rate=0.4, baseline_multi_rate=0.6),
        _alert_row(week_start="2026-08-17", adjusted_rate=0.45, baseline_multi_rate=0.6),
    ]
    alerts = evaluate_match_rate_alerts(rows)
    assert len(alerts) == 1
    assert alerts[0]["week_start"] == "2026-08-24"


def test_alert_uses_adjusted_rate_not_raw_rate():
    # 실측 매칭률은 크게 떨어졌지만 방식 구성 보정률이 다주 기저와 같으면 경고하지 않는다.
    rows = [
        _alert_row(
            week_start="2026-08-24",
            rate=0.5,
            baseline_rate=0.8,
            adjusted_rate=0.8,
            baseline_multi_rate=0.8,
        ),
        _alert_row(
            week_start="2026-08-17",
            rate=0.5,
            baseline_rate=0.8,
            adjusted_rate=0.8,
            baseline_multi_rate=0.8,
        ),
    ]
    assert evaluate_match_rate_alerts(rows) == []


def test_alert_requires_adjusted_and_multi_rates():
    # 보정률이나 다주 기저가 계산되지 않으면(None) 경고하지 않는다.
    rows = [
        _alert_row(week_start="2026-08-24", adjusted_rate=None),
        _alert_row(week_start="2026-08-17"),
    ]
    assert evaluate_match_rate_alerts(rows) == []

    rows = [
        _alert_row(week_start="2026-08-24", baseline_multi_rate=None),
        _alert_row(week_start="2026-08-17"),
    ]
    assert evaluate_match_rate_alerts(rows) == []


def test_baseline_multi_is_window_sum_not_mean_of_rates(isolated_db):
    """A1 다주 기저는 5주 합산 비율이며 주별 비율의 단순 평균이 아니다."""
    db = isolated_db
    center = W - timedelta(days=BASELINE_OFFSET_DAYS)
    # 중심 주는 10건 전부 미매칭(단일 주 기저 0.0).
    for i in range(10):
        _add_announcement(
            db, f"2025-W000{i}", "001", "Thng", center, presmpt_prce=LARGE_PRICE_THRESHOLD
        )
    # 앞뒤 2주도 10건 전부 미매칭.
    for offset in (-2, -1, 1):
        week = center + timedelta(days=7 * offset)
        for i in range(10):
            _add_announcement(
                db,
                f"2025-W1{offset}{i}",
                "001",
                "Thng",
                week,
                presmpt_prce=LARGE_PRICE_THRESHOLD,
            )
    # +2주만 100건 전부 매칭.
    far_week = center + timedelta(days=7 * BASELINE_WINDOW_WEEKS)
    for i in range(100):
        no = f"2025-W2{i:04d}"
        _add_announcement(db, no, "001", "Thng", far_week, presmpt_prce=LARGE_PRICE_THRESHOLD)
        _add_result(db, no, "001", "Thng", far_week)
    _add_announcement(db, "2026-W0001", "001", "Thng", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_result(db, "2026-W0001", "001", "Thng", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Thng", "large", W)
    # 단일 주 기저(중심 주)는 그대로 10건 0매칭이다.
    assert row["baseline_announcements"] == 10
    assert row["baseline_matched"] == 0
    assert row["baseline_rate"] == 0.0
    # 5주 합산은 140건 100매칭이다. 주별 비율 단순 평균(0.2)과 달라야 한다.
    assert row["baseline_multi_announcements"] == 140
    assert row["baseline_multi_matched"] == 100
    assert row["baseline_multi_rate"] == pytest.approx(100 / 140)
    assert row["baseline_multi_rate"] != pytest.approx(0.2)


def test_adjusted_rate_offsets_pure_composition_shift(isolated_db):
    """A2 구성만 바뀌고 방식별 매칭률이 같으면 보정률이 다주 기저와 같아진다."""
    db = isolated_db
    center = W - timedelta(days=BASELINE_OFFSET_DAYS)
    _add_method_batch(db, "2025-C1", center, "전자입찰", 50, 25)
    _add_method_batch(db, "2025-C2", center, "전자시담", 150, 135)
    # 구성만 뒤집고 방식별 매칭률은 유지한다.
    _add_method_batch(db, "2026-C1", W, "전자입찰", 150, 75)
    _add_method_batch(db, "2026-C2", W, "전자시담", 50, 45)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Thng", "large", W)
    assert row["announcements"] == 200
    assert row["rate"] == pytest.approx(0.6)
    assert row["baseline_multi_rate"] == pytest.approx(0.8)
    assert row["adjusted_rate"] == pytest.approx(0.8)


def test_adjusted_rate_substitutes_overall_for_missing_method(isolated_db):
    """현재 주에 공고가 없는 방식은 현재 주 전체 매칭률로 대체한다."""
    db = isolated_db
    center = W - timedelta(days=BASELINE_OFFSET_DAYS)
    _add_method_batch(db, "2025-D1", center, "전자입찰", 100, 50)
    _add_method_batch(db, "2025-D2", center, "전자시담", 100, 90)
    # 현재 주에는 전자시담이 없다.
    _add_method_batch(db, "2026-D1", W, "전자입찰", 100, 50)
    _add_method_batch(db, "2026-D2", W, "전자계약", 100, 100)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Thng", "large", W)
    assert row["rate"] == pytest.approx(0.75)
    assert row["baseline_multi_rate"] == pytest.approx(0.7)
    # 기저 구성비 0.5/0.5 에, 누락된 전자시담은 현재 전체 매칭률 0.75 로 대체된다.
    assert row["adjusted_rate"] == pytest.approx(0.5 * 0.5 + 0.5 * 0.75)


def test_null_bid_method_grouped_as_single_method(isolated_db):
    """NULL 입찰방식은 '(null)' 한 방식으로 묶여 기저 구성비가 1.0 이 된다."""
    db = isolated_db
    center = W - timedelta(days=BASELINE_OFFSET_DAYS)
    for i in range(200):
        no = f"2025-N{i:04d}"
        _add_announcement(db, no, "001", "Thng", center, presmpt_prce=LARGE_PRICE_THRESHOLD)
        if i < 100:
            _add_result(db, no, "001", "Thng", center)
    for i in range(100):
        no = f"2026-N{i:04d}"
        _add_announcement(
            db, no, "001", "Thng", W, presmpt_prce=LARGE_PRICE_THRESHOLD, bid_methd_nm=None
        )
        if i < 40:
            _add_result(db, no, "001", "Thng", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Thng", "large", W)
    assert row["baseline_multi_rate"] == pytest.approx(0.5)
    assert row["adjusted_rate"] == pytest.approx(0.4)
    assert row["adjusted_rate"] == pytest.approx(row["rate"])


def test_adjusted_rate_none_for_small_and_empty_week(isolated_db):
    """소형 행과 현재 주 공고가 0 인 행, 기저가 빈 행은 adjusted_rate 가 None 이다."""
    db = isolated_db
    center = W - timedelta(days=BASELINE_OFFSET_DAYS)
    _add_method_batch(db, "2025-E1", center, "전자입찰", 120, 60)
    for i in range(3):
        _add_announcement(db, f"2026-E1{i}", "001", "Servc", W)
    _add_announcement(db, "2026-E2001", "001", "Cnstwk", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_result(db, "2026-E2001", "001", "Cnstwk", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    # Servc 는 대형 공고가 없어 대형 행 adjusted_rate 가 None, 소형 행도 None 이다.
    assert _row_of(rows, "Servc", "large", W)["adjusted_rate"] is None
    assert _row_of(rows, "Servc", "small", W)["adjusted_rate"] is None
    # Cnstwk 대형은 공고가 1건이지만 기저 5주가 비어 보정할 수 없다.
    assert _row_of(rows, "Cnstwk", "large", W)["adjusted_rate"] is None
    # Thng 대형은 현재 주 공고가 0 이다.
    assert _row_of(rows, "Thng", "large", W)["adjusted_rate"] is None


@pytest.mark.asyncio
async def test_task_notifies_only_when_alert(isolated_db, monkeypatch):
    from src.app.core.config import settings
    from src.tasks import coverage_tasks

    # 로컬 .env 의 운영값과 무관하게 코드 기본값으로 고정한다.
    monkeypatch.setattr(settings, "RESULT_COVERAGE_ALERT_SUPPRESS", "")
    monkeypatch.setattr(settings, "RESULT_COVERAGE_EXCLUDE_LATER_CANCELLED", False)
    monkeypatch.setattr(settings, "RESULT_COVERAGE_EXCLUDE_OFFLINE_BIDS", False)

    db = isolated_db
    # 최근 성숙 주와 직전 성숙 주 모두 대형 Servc 공고 100건이 전부 미매칭이다(A6 2주 연속).
    for idx, start in enumerate((W, W - timedelta(days=7))):
        for i in range(MIN_WEEK_SAMPLES):
            _add_announcement(
                db,
                f"2026-E{idx}{i:04d}",
                "001",
                "Servc",
                start,
                presmpt_prce=LARGE_PRICE_THRESHOLD,
            )
    # 두 주의 5주 기저 창 합집합(6주)에 25건씩 모두 매칭을 둔다(합산 기저 1.0).
    for w in range(6):
        week = W - timedelta(days=385) + timedelta(days=7 * w)
        for i in range(25):
            no = f"2025-E{w}{i:04d}"
            _add_announcement(db, no, "001", "Servc", week, presmpt_prce=LARGE_PRICE_THRESHOLD)
            _add_result(db, no, "001", "Servc", week)
    db.commit()

    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    # 태스크는 date.today() 를 기준일로 쓴다. 실행일이 지나면 최근 성숙 주가 W 에서
    # 밀려나므로 시험 데이터의 기준일 AS_OF 로 고정한다.
    class _FrozenDate(date):
        @classmethod
        def today(cls) -> date:
            return AS_OF

    monkeypatch.setattr(coverage_tasks, "date", _FrozenDate)
    monkeypatch.setattr(coverage_tasks, "SessionLocal", lambda: db)
    monkeypatch.setattr(coverage_tasks, "notify", fake_notify)

    result = await coverage_tasks.result_coverage_monitor_task({})
    assert result["status"] == "ok"
    assert result["as_of"] == AS_OF.isoformat()
    assert len(result["alerts"]) == 1
    assert result["alerts"][0]["category"] == "Servc"
    assert result["alerts"][0]["week_start"] == W.isoformat()
    # 기본 weeks=8 이므로 8주 x 3분류 x 2규모 = 48 행이다.
    assert result["rows"] == 48
    assert len(sent) == 1
    title, lines, level = sent[0]
    assert level == "warning"
    assert "매칭률" in title
    body = "\n".join(lines)
    assert "uv run python scripts/result_match_rate_report.py" in body
    assert "2주 연속" in body


@pytest.mark.asyncio
async def test_task_silent_without_alert(isolated_db, monkeypatch):
    from src.tasks import coverage_tasks

    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    monkeypatch.setattr(coverage_tasks, "SessionLocal", lambda: isolated_db)
    monkeypatch.setattr(coverage_tasks, "notify", fake_notify)

    result = await coverage_tasks.result_coverage_monitor_task({})
    assert result["status"] == "ok"
    assert result["alerts"] == []
    assert sent == []


@pytest.mark.asyncio
async def test_task_returns_error_without_raising_on_db_failure(monkeypatch):
    from src.tasks import coverage_tasks

    def boom():
        raise RuntimeError("db unavailable")

    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    monkeypatch.setattr(coverage_tasks, "SessionLocal", boom)
    monkeypatch.setattr(coverage_tasks, "notify", fake_notify)

    result = await coverage_tasks.result_coverage_monitor_task({})
    assert result["status"] == "error"
    assert result["alerts"] == []
    assert sent == []


def test_worker_settings_register_task_and_cron():
    from src.tasks.worker import WorkerSettings

    names = [
        getattr(getattr(fn, "coroutine", fn), "__name__", "") for fn in WorkerSettings.functions
    ]
    assert "result_coverage_monitor_task" in names

    jobs = [
        job
        for job in WorkerSettings.cron_jobs
        if getattr(getattr(job, "coroutine", job), "__name__", "") == "result_coverage_monitor_task"
    ]
    assert len(jobs) == 1
    job = jobs[0]
    assert job.weekday in ("mon", {"mon"})
    assert job.hour in (5, {5})
    assert job.minute in (0, {0})
    assert job.run_at_startup is False
    assert job.timeout_s == 3600


def test_notice_dedup_keeps_latest_ord(isolated_db):
    """같은 공고번호·분류의 000/001 두 행은 보조 지표에서 최신 차수 하나만 센다."""
    db = isolated_db
    _add_announcement(db, "2026-L00001", "000", "Servc", W)
    _add_announcement(db, "2026-L00001", "001", "Servc", W)
    _add_result(db, "2026-L00001", "001", "Servc", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Servc", "small", W)
    # 기존 매칭률은 두 행을 그대로 센다.
    assert row["announcements"] == 2
    assert row["matched"] == 1
    assert row["rate"] == pytest.approx(0.5)
    # 보조 지표는 최신 차수 001 한 행만 센다.
    assert row["notice_announcements"] == 1
    assert row["notice_matched"] == 1
    assert row["notice_rate"] == pytest.approx(1.0)


def test_notice_dedup_matches_latest_ord_only(isolated_db):
    """결과가 000 에만 있고 공고가 000·001 이면 보조 지표는 001 기준이라 미매칭이다."""
    db = isolated_db
    _add_announcement(db, "2026-M00001", "000", "Servc", W)
    _add_announcement(db, "2026-M00001", "001", "Servc", W)
    _add_result(db, "2026-M00001", "000", "Servc", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Servc", "small", W)
    assert row["announcements"] == 2
    assert row["matched"] == 1
    assert row["notice_announcements"] == 1
    assert row["notice_matched"] == 0
    assert row["notice_rate"] == pytest.approx(0.0)


def test_notice_dedup_counts_in_latest_ord_week(isolated_db):
    """차수가 다른 주에 걸치면 최신 차수 행의 주에만 계수한다."""
    db = isolated_db
    older = W - timedelta(days=7)
    _add_announcement(db, "2026-P00001", "000", "Servc", older)
    _add_announcement(db, "2026-P00001", "001", "Servc", W)
    _add_result(db, "2026-P00001", "001", "Servc", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=2)
    latest_row = _row_of(rows, "Servc", "small", W)
    older_row = _row_of(rows, "Servc", "small", older)
    assert latest_row["notice_announcements"] == 1
    assert latest_row["notice_matched"] == 1
    assert latest_row["notice_rate"] == pytest.approx(1.0)
    assert older_row["notice_announcements"] == 0
    assert older_row["notice_matched"] == 0
    assert older_row["notice_rate"] is None
    # 기존 집계는 두 주에 각각 한 행씩 남는다.
    assert latest_row["announcements"] == 1
    assert older_row["announcements"] == 1


def test_notice_dedup_separates_categories(isolated_db):
    """분류가 다르면 같은 공고번호라도 별도 공고로 계수한다."""
    db = isolated_db
    _add_announcement(db, "2026-Q00001", "000", "Servc", W)
    _add_announcement(db, "2026-Q00001", "001", "Cnstwk", W)
    _add_result(db, "2026-Q00001", "001", "Cnstwk", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    servc = _row_of(rows, "Servc", "small", W)
    cnstwk = _row_of(rows, "Cnstwk", "small", W)
    assert servc["notice_announcements"] == 1
    assert servc["notice_matched"] == 0
    assert cnstwk["notice_announcements"] == 1
    assert cnstwk["notice_matched"] == 1


def test_baseline_notice_rate_uses_single_year_ago_week(isolated_db):
    """baseline_notice_* 는 364일 전 같은 단일 주에서 같은 방식으로 센 값이다."""
    db = isolated_db
    baseline = W - timedelta(days=BASELINE_OFFSET_DAYS)
    _add_announcement(db, "2026-R00001", "000", "Thng", W)
    _add_announcement(db, "2026-R00001", "001", "Thng", W)
    _add_result(db, "2026-R00001", "001", "Thng", W)
    _add_announcement(db, "2025-R00001", "000", "Thng", baseline)
    _add_announcement(db, "2025-R00001", "001", "Thng", baseline)
    _add_result(db, "2025-R00001", "001", "Thng", baseline)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Thng", "small", W)
    assert row["notice_announcements"] == 1
    assert row["notice_matched"] == 1
    assert row["notice_rate"] == pytest.approx(1.0)
    assert row["baseline_notice_announcements"] == 1
    assert row["baseline_notice_matched"] == 1
    assert row["baseline_notice_rate"] == pytest.approx(1.0)


def test_notice_metrics_do_not_feed_adjusted_rate(isolated_db):
    """보조 지표는 보정률(adjusted_rate)과 기존 필드 계산에 쓰이지 않는다."""
    db = isolated_db
    center = W - timedelta(days=BASELINE_OFFSET_DAYS)
    _add_method_batch(db, "2025-S1", center, "전자입찰", 100, 50)
    # 현재 주 대형 Thng 는 같은 공고번호 000/001 두 행이고 001 만 매칭이다.
    _add_announcement(
        db,
        "2026-S00001",
        "000",
        "Thng",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        bid_methd_nm="전자입찰",
    )
    _add_announcement(
        db,
        "2026-S00001",
        "001",
        "Thng",
        W,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        bid_methd_nm="전자입찰",
    )
    _add_result(db, "2026-S00001", "001", "Thng", W)
    db.commit()

    rows = compute_result_match_rates(db, as_of=AS_OF, weeks=1)
    row = _row_of(rows, "Thng", "large", W)
    # 기존 집계는 두 행을 세고, 보조 지표는 최신 차수 한 행만 센다.
    assert row["announcements"] == 2
    assert row["matched"] == 1
    assert row["notice_announcements"] == 1
    assert row["notice_matched"] == 1
    assert row["notice_rate"] == pytest.approx(1.0)
    # 보정률은 기존 방식별 집계(2건 중 1건, 기저 1.0 가중)를 그대로 쓴다.
    assert row["baseline_multi_rate"] == pytest.approx(0.5)
    assert row["adjusted_rate"] == pytest.approx(0.5)
    assert row["adjusted_rate"] == pytest.approx(row["rate"])
    assert row["adjusted_rate"] != pytest.approx(row["notice_rate"])


def test_alerts_ignore_notice_fields():
    """경고 판정은 보조 지표 필드가 있든 없든 같은 결과를 낸다."""
    rows = _two_alert_weeks()
    expected = evaluate_match_rate_alerts(rows)
    assert len(expected) == 1
    for row in rows:
        row.update(
            notice_announcements=1,
            notice_matched=0,
            notice_rate=0.0,
            baseline_notice_announcements=1,
            baseline_notice_matched=0,
            baseline_notice_rate=0.0,
        )
    assert evaluate_match_rate_alerts(rows) == expected


def test_parse_alert_suppressions_reads_valid_entries_with_whitespace():
    parsed = parse_alert_suppressions(" Servc : large : 2026-11-30 , Thng:large:2026-12-31 ")
    assert parsed == {
        ("Servc", "large"): date(2026, 11, 30),
        ("Thng", "large"): date(2026, 12, 31),
    }


def test_parse_alert_suppressions_empty_text_disables_suppression():
    assert parse_alert_suppressions("") == {}
    assert parse_alert_suppressions("   ") == {}
    assert parse_alert_suppressions(None) == {}


def test_parse_alert_suppressions_ignores_malformed_entries():
    # 항목 수 오류, 빈 분류·규모, 날짜 오류, 규모 오류 항목은 무시하고 정상 항목만 남긴다.
    parsed = parse_alert_suppressions(
        "Servc:large,"
        "Servc:large:2026-11-30:extra,"
        ":large:2026-11-30,"
        "Servc::2026-11-30,"
        "Servc:large:not-a-date,"
        "Servc:large:2026-13-01,"
        "Servc:medium:2026-11-30,"
        "Servc:large:2026-11-30"
    )
    assert parsed == {("Servc", "large"): date(2026, 11, 30)}


def test_parse_alert_suppressions_rejects_small_band():
    # 경고 판정은 대형만 하므로 소형 억제는 설정 실수로 보고 무시한다.
    assert parse_alert_suppressions("Servc:small:2026-11-30") == {}


def test_suppression_keeps_alert_and_marks_it():
    suppressions = {("Servc", "large"): date(2026, 11, 30)}
    alerts = evaluate_match_rate_alerts(
        _two_alert_weeks(), suppressions=suppressions, today=date(2026, 10, 1)
    )
    # 억제 대상도 반환 목록에서 빼지 않고 suppressed 표시로 남긴다.
    assert len(alerts) == 1
    assert alerts[0]["category"] == "Servc"
    assert alerts[0]["week_start"] == "2026-08-24"
    assert alerts[0]["suppressed"] is True
    assert alerts[0]["suppressed_until"] == "2026-11-30"


def test_suppression_expires_the_day_after():
    suppressions = {("Servc", "large"): date(2026, 10, 1)}
    # 만료일 당일은 억제된다.
    on_expiry = evaluate_match_rate_alerts(
        _two_alert_weeks(), suppressions=suppressions, today=date(2026, 10, 1)
    )
    assert on_expiry[0]["suppressed"] is True
    assert on_expiry[0]["suppressed_until"] == "2026-10-01"
    # 만료일 다음 날부터는 억제가 풀린다.
    after_expiry = evaluate_match_rate_alerts(
        _two_alert_weeks(), suppressions=suppressions, today=date(2026, 10, 2)
    )
    assert after_expiry[0]["suppressed"] is False
    assert after_expiry[0]["suppressed_until"] is None


def test_suppression_other_category_is_not_suppressed():
    suppressions = {("Thng", "large"): date(2026, 11, 30)}
    alerts = evaluate_match_rate_alerts(
        _two_alert_weeks(), suppressions=suppressions, today=date(2026, 10, 1)
    )
    assert alerts[0]["category"] == "Servc"
    assert alerts[0]["suppressed"] is False
    assert alerts[0]["suppressed_until"] is None


def test_suppression_none_matches_legacy_contract():
    legacy = evaluate_match_rate_alerts(_two_alert_weeks())
    with_none = evaluate_match_rate_alerts(
        _two_alert_weeks(), suppressions=None, today=date(2026, 10, 1)
    )
    assert len(legacy) == 1
    assert legacy[0]["suppressed"] is False
    assert legacy[0]["suppressed_until"] is None
    # 기존 키 값은 억제 인자와 무관하게 동일하다.
    for key in (
        "category",
        "week_start",
        "rate",
        "baseline_rate",
        "announcements",
        "adjusted_rate",
        "baseline_multi_rate",
        "previous_week_start",
        "previous_adjusted_rate",
        "previous_baseline_multi_rate",
    ):
        assert with_none[0][key] == legacy[0][key]


def test_later_cancelled_flag_toggles_denominator(isolated_db):
    """000 등록공고 미매칭 + 001 취소공고는 플래그 켜짐에서만 분모에서 빠진다."""
    db = isolated_db
    _add_announcement(db, "2026-T00001", "000", "Servc", W, ntce_kind_nm="일반공고")
    _add_announcement(db, "2026-T00001", "001", "Servc", W, ntce_kind_nm="취소공고")
    db.commit()

    off = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=False),
        "Servc",
        "small",
        W,
    )
    assert off["announcements"] == 1
    assert off["matched"] == 0
    assert off["rate"] == pytest.approx(0.0)
    assert off["later_cancelled_excluded"] == 1
    assert off["cancel_adjusted_announcements"] == 0
    assert off["cancel_adjusted_matched"] == 0
    assert off["cancel_adjusted_rate"] is None

    on = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Servc",
        "small",
        W,
    )
    assert on["announcements"] == 0
    assert on["matched"] == 0
    assert on["rate"] is None
    assert on["later_cancelled_excluded"] == 1
    assert on["cancel_adjusted_announcements"] == 0
    assert on["cancel_adjusted_matched"] == 0
    assert on["cancel_adjusted_rate"] is None


def test_later_cancelled_does_not_exclude_matched_rows(isolated_db):
    """더 큰 차수 취소공고가 있어도 매칭된 행은 분모에서 빠지지 않는다."""
    db = isolated_db
    _add_announcement(db, "2026-U00001", "000", "Servc", W, ntce_kind_nm="일반공고")
    _add_result(db, "2026-U00001", "000", "Servc", W)
    _add_announcement(db, "2026-U00001", "001", "Servc", W, ntce_kind_nm="취소공고")
    db.commit()

    row = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 1
    assert row["matched"] == 1
    assert row["rate"] == pytest.approx(1.0)
    assert row["later_cancelled_excluded"] == 0
    assert row["cancel_adjusted_announcements"] == 1
    assert row["cancel_adjusted_matched"] == 1
    assert row["cancel_adjusted_rate"] == pytest.approx(1.0)


def test_later_cancelled_smaller_ord_is_not_target(isolated_db):
    """취소공고 차수가 공고 차수보다 작으면 대상이 아니다(001 공고, 000 취소)."""
    db = isolated_db
    _add_announcement(db, "2026-V00001", "000", "Servc", W, ntce_kind_nm="취소공고")
    _add_announcement(db, "2026-V00001", "001", "Servc", W, ntce_kind_nm="일반공고")
    db.commit()

    row = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 1
    assert row["matched"] == 0
    assert row["later_cancelled_excluded"] == 0
    assert row["cancel_adjusted_announcements"] == 1


def test_later_cancelled_other_category_is_not_target(isolated_db):
    """분류가 다르면 같은 공고번호의 취소공고라도 대상이 아니다."""
    db = isolated_db
    _add_announcement(db, "2026-W00001", "000", "Servc", W)
    _add_announcement(db, "2026-W00001", "001", "Cnstwk", W, ntce_kind_nm="취소공고")
    db.commit()

    row = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 1
    assert row["later_cancelled_excluded"] == 0
    assert row["cancel_adjusted_announcements"] == 1


def test_later_cancelled_max_ord_wins(isolated_db):
    """취소공고가 여러 차수면 가장 큰 차수와 비교한다."""
    db = isolated_db
    _add_announcement(db, "2026-Y10001", "000", "Servc", W, ntce_kind_nm="일반공고")
    _add_announcement(db, "2026-Y10001", "001", "Servc", W, ntce_kind_nm="취소공고")
    _add_announcement(db, "2026-Y10001", "002", "Servc", W, ntce_kind_nm="취소공고")
    db.commit()

    on = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Servc",
        "small",
        W,
    )
    assert on["announcements"] == 0
    assert on["later_cancelled_excluded"] == 1


def test_later_cancelled_applies_to_baseline_single_week(isolated_db):
    """전년 단일 주 기저에도 같은 제외 규칙이 대칭 적용된다."""
    db = isolated_db
    baseline = W - timedelta(days=BASELINE_OFFSET_DAYS)
    _add_announcement(db, "2026-X00001", "001", "Thng", W)
    _add_result(db, "2026-X00001", "001", "Thng", W)
    _add_announcement(db, "2025-X00001", "000", "Thng", baseline)
    _add_announcement(db, "2025-X00001", "001", "Thng", baseline, ntce_kind_nm="취소공고")
    db.commit()

    off = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=False),
        "Thng",
        "small",
        W,
    )
    assert off["baseline_announcements"] == 1
    assert off["baseline_matched"] == 0
    assert off["baseline_cancel_adjusted_announcements"] == 0
    assert off["baseline_cancel_adjusted_matched"] == 0
    assert off["baseline_cancel_adjusted_rate"] is None

    on = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Thng",
        "small",
        W,
    )
    assert on["baseline_announcements"] == 0
    assert on["baseline_matched"] == 0
    assert on["baseline_rate"] is None
    assert on["baseline_cancel_adjusted_announcements"] == 0


def test_later_cancelled_excluded_from_baseline_multi_and_adjusted(isolated_db):
    """플래그 켜짐에서 baseline_multi 와 adjusted_rate 도 제외 집합 기준이다."""
    db = isolated_db
    center = W - timedelta(days=BASELINE_OFFSET_DAYS)
    _add_announcement(db, "2025-Z00001", "000", "Thng", center, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_announcement(
        db,
        "2025-Z00001",
        "001",
        "Thng",
        center,
        presmpt_prce=LARGE_PRICE_THRESHOLD,
        ntce_kind_nm="취소공고",
    )
    _add_announcement(db, "2026-Z00001", "001", "Thng", W, presmpt_prce=LARGE_PRICE_THRESHOLD)
    _add_result(db, "2026-Z00001", "001", "Thng", W)
    db.commit()

    off = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=False),
        "Thng",
        "large",
        W,
    )
    assert off["baseline_multi_announcements"] == 1
    assert off["baseline_multi_matched"] == 0
    assert off["baseline_multi_rate"] == pytest.approx(0.0)
    assert off["adjusted_rate"] == pytest.approx(1.0)

    on = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Thng",
        "large",
        W,
    )
    assert on["baseline_multi_announcements"] == 0
    assert on["baseline_multi_rate"] is None
    assert on["adjusted_rate"] is None


def test_later_cancelled_comparison_fields_always_present(isolated_db):
    """플래그가 꺼져 있어도 비교 필드가 항상 채워지고 기존 필드는 그대로다."""
    db = isolated_db
    _add_announcement(db, "2026-N10001", "001", "Servc", W)
    _add_result(db, "2026-N10001", "001", "Servc", W)
    _add_announcement(db, "2026-N10001", "002", "Servc", W, ntce_kind_nm="취소공고")
    db.commit()

    row = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=False),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 1
    assert row["matched"] == 1
    assert row["later_cancelled_excluded"] == 0
    assert row["cancel_adjusted_announcements"] == 1
    assert row["cancel_adjusted_matched"] == 1
    assert row["cancel_adjusted_rate"] == pytest.approx(1.0)
    assert row["baseline_cancel_adjusted_announcements"] == 0
    assert row["baseline_cancel_adjusted_matched"] == 0
    assert row["baseline_cancel_adjusted_rate"] is None
    # 002 취소공고는 매칭된 001 행을 대상으로 만들지 않는다.
    assert row["later_cancelled_excluded"] == 0


def test_later_cancelled_flag_defaults_from_settings(isolated_db, monkeypatch):
    """인자를 주지 않으면 설정값을 따른다. 기본값은 꺼짐이다."""
    from src.app.core.config import Settings, settings

    db = isolated_db
    _add_announcement(db, "2026-O00001", "000", "Servc", W)
    _add_announcement(db, "2026-O00001", "001", "Servc", W, ntce_kind_nm="취소공고")
    db.commit()

    # 로컬 .env 에서 켜 두었을 수 있으므로 실행 값이 아니라 코드 기본값을 검사한다.
    assert Settings.model_fields["RESULT_COVERAGE_EXCLUDE_LATER_CANCELLED"].default is False
    monkeypatch.setattr(settings, "RESULT_COVERAGE_EXCLUDE_LATER_CANCELLED", False)
    off = _row_of(compute_result_match_rates(db, as_of=AS_OF, weeks=1), "Servc", "small", W)
    assert off["announcements"] == 1

    monkeypatch.setattr(settings, "RESULT_COVERAGE_EXCLUDE_LATER_CANCELLED", True)
    on = _row_of(compute_result_match_rates(db, as_of=AS_OF, weeks=1), "Servc", "small", W)
    assert on["announcements"] == 0


def test_later_cancelled_nonnumeric_announcement_ord_is_not_target(isolated_db):
    """공고 행 차수가 'A1' 이면 더 큰 차수 취소공고가 있어도 대상이 아니다."""
    db = isolated_db
    _add_announcement(db, "2026-A20001", "A1", "Servc", W, ntce_kind_nm="일반공고")
    _add_announcement(db, "2026-A20001", "001", "Servc", W, ntce_kind_nm="취소공고")
    db.commit()

    assert _is_later_cancelled("2026-A20001", "A1", "Servc", {("2026-A20001", "Servc"): 1}) is False

    row = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 1
    assert row["matched"] == 0
    assert row["rate"] == pytest.approx(0.0)
    assert row["later_cancelled_excluded"] == 0
    assert row["cancel_adjusted_announcements"] == 1
    assert row["cancel_adjusted_rate"] == pytest.approx(0.0)


def test_later_cancelled_nonnumeric_cancel_ord_is_ignored(isolated_db):
    """비숫자 취소 차수만 있는 공고는 숫자 공고 행의 대상이 아니다."""
    db = isolated_db
    _add_announcement(db, "2026-A30001", "000", "Servc", W, ntce_kind_nm="일반공고")
    _add_announcement(db, "2026-A30001", "A1", "Servc", W, ntce_kind_nm="취소공고")
    db.commit()

    row = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 1
    assert row["matched"] == 0
    assert row["later_cancelled_excluded"] == 0
    assert row["cancel_adjusted_announcements"] == 1


def test_later_cancelled_numeric_ord_still_target(isolated_db):
    """숫자 차수 000 공고 + 001 취소공고는 방어 추가 후에도 여전히 대상이다."""
    db = isolated_db
    _add_announcement(db, "2026-A40001", "000", "Servc", W, ntce_kind_nm="일반공고")
    _add_announcement(db, "2026-A40001", "001", "Servc", W, ntce_kind_nm="취소공고")
    db.commit()

    assert _is_later_cancelled("2026-A40001", "000", "Servc", {("2026-A40001", "Servc"): 1}) is True

    row = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_later_cancelled=True),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 0
    assert row["later_cancelled_excluded"] == 1


def test_is_offline_bid_classification():
    """전자로 시작하지 않는 입찰방식만 오프라인이고 None·공백은 오프라인이 아니다."""
    assert _is_offline_bid(None) is False
    assert _is_offline_bid("") is False
    assert _is_offline_bid("   ") is False
    assert _is_offline_bid("전자입찰") is False
    assert _is_offline_bid("전자시담") is False
    assert _is_offline_bid(" 전자시담(2인 이상) ") is False
    assert _is_offline_bid("직찰") is True
    assert _is_offline_bid(" 직찰 ") is True
    assert _is_offline_bid("직찰/우편") is True
    assert _is_offline_bid("우편/상시") is True


def test_offline_flag_excludes_unmatched_from_denominator(isolated_db):
    """직찰 미매칭 행은 플래그 켜짐에서만 분모에서 빠진다."""
    db = isolated_db
    _add_announcement(db, "2026-AA0001", "001", "Servc", W, bid_methd_nm="직찰")
    db.commit()

    off = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_offline_bids=False),
        "Servc",
        "small",
        W,
    )
    assert off["announcements"] == 1
    assert off["matched"] == 0
    assert off["rate"] == pytest.approx(0.0)
    assert off["offline_excluded"] == 1
    assert off["offline_adjusted_announcements"] == 0
    assert off["offline_adjusted_matched"] == 0
    assert off["offline_adjusted_rate"] is None

    on = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_offline_bids=True),
        "Servc",
        "small",
        W,
    )
    assert on["announcements"] == 0
    assert on["matched"] == 0
    assert on["rate"] is None
    assert on["offline_excluded"] == 1
    assert on["offline_adjusted_announcements"] == 0
    assert on["offline_adjusted_rate"] is None


def test_offline_flag_excludes_matched_from_numerator_and_denominator(isolated_db):
    """오프라인 매칭 행도 켜짐에서 분모와 분자 모두에서 빠진다."""
    db = isolated_db
    _add_announcement(db, "2026-AB0001", "001", "Servc", W, bid_methd_nm="직찰/우편")
    _add_result(db, "2026-AB0001", "001", "Servc", W)
    db.commit()

    off = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_offline_bids=False),
        "Servc",
        "small",
        W,
    )
    assert off["announcements"] == 1
    assert off["matched"] == 1
    assert off["rate"] == pytest.approx(1.0)
    assert off["offline_excluded"] == 1

    on = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_offline_bids=True),
        "Servc",
        "small",
        W,
    )
    assert on["announcements"] == 0
    assert on["matched"] == 0
    assert on["rate"] is None
    assert on["offline_excluded"] == 1
    assert on["offline_adjusted_announcements"] == 0
    assert on["offline_adjusted_matched"] == 0
    assert on["offline_adjusted_rate"] is None


def test_offline_flag_applies_to_baseline_symmetrically(isolated_db):
    """플래그가 전년 단일 주와 5주 기저에도 대칭 적용된다."""
    db = isolated_db
    center = W - timedelta(days=BASELINE_OFFSET_DAYS)
    _add_announcement(db, "2026-AC0001", "001", "Thng", W, bid_methd_nm="직찰")
    _add_result(db, "2026-AC0001", "001", "Thng", W)
    _add_announcement(db, "2025-AC0001", "001", "Thng", center, bid_methd_nm="직찰")
    _add_announcement(
        db, "2025-AC0002", "001", "Thng", center + timedelta(days=7), bid_methd_nm="우편/상시"
    )
    db.commit()

    off = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_offline_bids=False),
        "Thng",
        "small",
        W,
    )
    assert off["announcements"] == 1
    assert off["matched"] == 1
    assert off["baseline_announcements"] == 1
    assert off["baseline_matched"] == 0
    assert off["baseline_rate"] == pytest.approx(0.0)
    assert off["baseline_multi_announcements"] == 2
    assert off["baseline_multi_matched"] == 0
    assert off["offline_excluded"] == 1
    assert off["baseline_offline_adjusted_announcements"] == 0
    assert off["baseline_offline_adjusted_matched"] == 0
    assert off["baseline_offline_adjusted_rate"] is None

    on = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_offline_bids=True),
        "Thng",
        "small",
        W,
    )
    assert on["announcements"] == 0
    assert on["matched"] == 0
    assert on["rate"] is None
    assert on["baseline_announcements"] == 0
    assert on["baseline_matched"] == 0
    assert on["baseline_rate"] is None
    assert on["baseline_multi_announcements"] == 0
    assert on["baseline_multi_matched"] == 0
    assert on["baseline_multi_rate"] is None
    assert on["adjusted_rate"] is None
    assert on["offline_excluded"] == 1
    assert on["baseline_offline_adjusted_announcements"] == 0
    assert on["baseline_offline_adjusted_rate"] is None


def test_offline_comparison_fields_always_present(isolated_db):
    """플래그가 꺼져 있어도 비교 필드가 채워지고 기존 필드는 오프라인 행을 포함한다."""
    db = isolated_db
    _add_announcement(db, "2026-AD0001", "001", "Servc", W, bid_methd_nm="전자입찰")
    _add_result(db, "2026-AD0001", "001", "Servc", W)
    _add_announcement(db, "2026-AD0002", "001", "Servc", W, bid_methd_nm="우편/상시")
    db.commit()

    row = _row_of(
        compute_result_match_rates(db, as_of=AS_OF, weeks=1, exclude_offline_bids=False),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 2
    assert row["matched"] == 1
    assert row["rate"] == pytest.approx(0.5)
    assert row["offline_excluded"] == 1
    assert row["offline_adjusted_announcements"] == 1
    assert row["offline_adjusted_matched"] == 1
    assert row["offline_adjusted_rate"] == pytest.approx(1.0)
    assert row["baseline_offline_adjusted_announcements"] == 0
    assert row["baseline_offline_adjusted_matched"] == 0
    assert row["baseline_offline_adjusted_rate"] is None


def test_offline_flag_defaults_from_settings(isolated_db, monkeypatch):
    """인자를 주지 않으면 설정값을 따르며 기본값은 꺼짐이다."""
    from src.app.core.config import Settings, settings

    db = isolated_db
    _add_announcement(db, "2026-AE0001", "001", "Servc", W, bid_methd_nm="직찰")
    db.commit()

    # 로컬 .env 값에 의존하지 않도록 코드 기본값을 검사한다.
    assert Settings.model_fields["RESULT_COVERAGE_EXCLUDE_OFFLINE_BIDS"].default is False
    monkeypatch.setattr(settings, "RESULT_COVERAGE_EXCLUDE_OFFLINE_BIDS", False)
    off = _row_of(compute_result_match_rates(db, as_of=AS_OF, weeks=1), "Servc", "small", W)
    assert off["announcements"] == 1

    monkeypatch.setattr(settings, "RESULT_COVERAGE_EXCLUDE_OFFLINE_BIDS", True)
    on = _row_of(compute_result_match_rates(db, as_of=AS_OF, weeks=1), "Servc", "small", W)
    assert on["announcements"] == 0


def test_both_exclusion_flags_apply_each_rule_independently(isolated_db):
    """두 플래그가 함께 켜지면 두 규칙 모두 적용되고 비교 필드는 각자 자기 규칙만 반영한다."""
    db = isolated_db
    # 직찰 매칭 행은 오프라인 규칙만 뺀다.
    _add_announcement(db, "2026-AF0001", "001", "Servc", W, bid_methd_nm="직찰")
    _add_result(db, "2026-AF0001", "001", "Servc", W)
    # 000 일반공고 미매칭 + 001 취소공고는 취소 규칙만 뺀다.
    _add_announcement(
        db, "2026-AF0002", "000", "Servc", W, ntce_kind_nm="일반공고", bid_methd_nm="전자입찰"
    )
    _add_announcement(db, "2026-AF0002", "001", "Servc", W, ntce_kind_nm="취소공고")
    # 순수 매칭 행은 어느 규칙도 빼지 않는다.
    _add_announcement(db, "2026-AF0003", "001", "Servc", W, bid_methd_nm="전자입찰")
    _add_result(db, "2026-AF0003", "001", "Servc", W)
    db.commit()

    row = _row_of(
        compute_result_match_rates(
            db,
            as_of=AS_OF,
            weeks=1,
            exclude_later_cancelled=True,
            exclude_offline_bids=True,
        ),
        "Servc",
        "small",
        W,
    )
    assert row["announcements"] == 1
    assert row["matched"] == 1
    assert row["rate"] == pytest.approx(1.0)
    assert row["later_cancelled_excluded"] == 1
    assert row["offline_excluded"] == 1
    # 취소 규칙만 반영한 비교 필드는 오프라인 매칭 행을 유지한다.
    assert row["cancel_adjusted_announcements"] == 2
    assert row["cancel_adjusted_matched"] == 2
    assert row["cancel_adjusted_rate"] == pytest.approx(1.0)
    # 오프라인 규칙만 반영한 비교 필드는 취소 대상 행을 유지한다.
    assert row["offline_adjusted_announcements"] == 2
    assert row["offline_adjusted_matched"] == 1
    assert row["offline_adjusted_rate"] == pytest.approx(0.5)
