"""
tests/test_announcement_count_conditions.py

공고 건수·금액 정렬 공고 목록이 금액과 마감일 조건을 실제로 걸고 세는지,
지난 마감 표현과 이번 주 마감 창을 사용자 결정대로 해석하는지, 기간을
말하지 않은 공고 질문의 기본 창이 최근 30일인지 검증합니다. 기준일은
일요일(2026-10-25)과 평일(2026-10-21) 두 날짜로 고정합니다.
"""

from datetime import date, datetime, timedelta

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.tools import bid_query_tool
from src.rag import query_planning
from src.rag import structured_data as structured_data_module
from src.rag.answer_format import _build_single_metric_answer
from src.rag.query_planning import RECENT_ANNOUNCEMENT_WINDOW_DAYS
from src.rag.schemas import RetrievalPlan

FROZEN_TODAYS = (date(2026, 10, 25), date(2026, 10, 21))


@pytest.fixture(params=FROZEN_TODAYS, ids=["sunday", "weekday"])
def frozen_today(request, monkeypatch):
    frozen = request.param

    class _FrozenDate(date):
        @classmethod
        def today(cls) -> date:
            return frozen

    monkeypatch.setattr(query_planning, "date", _FrozenDate)
    monkeypatch.setattr(structured_data_module, "date", _FrozenDate)
    return frozen


def _at(day: date, hour: int = 9) -> datetime:
    return datetime.combine(day, datetime.min.time()).replace(hour=hour)


def _shift(day: date, days: int) -> datetime:
    return _at(day + timedelta(days=days))


def _announcement_rows(today: date) -> dict[int, dict]:
    month_start = today.replace(day=1)
    prev_month_end = month_start - timedelta(days=1)
    this_year_start = date(today.year, 1, 1)
    last_year_end = this_year_start - timedelta(days=1)
    return {
        1: {
            "category": "Cnstwk",
            "ntce": _shift(today, -1),
            "close": _shift(today, 5),
            "presmpt_prce": 100_000_000,
            "base_amount": 300_000_001,
        },
        2: {
            "category": "Cnstwk",
            "ntce": _shift(today, -2),
            "close": _shift(today, 6),
            "presmpt_prce": 100_000_000,
            "base_amount": 300_000_000,
        },
        3: {
            "category": "Cnstwk",
            "ntce": _shift(today, -30),
            "close": _shift(today, 7),
            "presmpt_prce": 100_000_000,
            "base_amount": 500_000_000,
        },
        4: {
            "category": "Servc",
            "ntce": _shift(today, -3),
            "close": _shift(today, -20),
            "presmpt_prce": 100_000_000,
            "base_amount": 900_000_000,
        },
        5: {
            "category": "Cnstwk",
            "ntce": _shift(today, -29),
            "close": _shift(today, 8),
            "presmpt_prce": 100_000_000,
            "base_amount": 400_000_000,
        },
        6: {
            "category": "Servc",
            "ntce": _shift(today, -2),
            "close": _shift(today, -21),
            "presmpt_prce": 500_000_000,
            "base_amount": 50_000_000,
        },
        7: {
            "category": "Servc",
            "ntce": _shift(today, -3),
            "close": _shift(today, -22),
            "presmpt_prce": 499_999_999,
            "base_amount": 50_000_000,
        },
        8: {
            "category": "Servc",
            "ntce": _shift(today, -30),
            "close": _shift(today, -23),
            "presmpt_prce": 9_999_000_000,
            "base_amount": 50_000_000,
        },
        9: {
            "category": "Cnstwk",
            "ntce": _shift(today, -1),
            "close": _shift(today, -1),
            "presmpt_prce": 900_000_000,
            "base_amount": 50_000_000,
        },
        10: {
            "category": "Cnstwk",
            "ntce": _shift(today, -60),
            "close": _at(month_start),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        11: {
            "category": "Cnstwk",
            "ntce": _shift(today, -60),
            "close": _at(today, 12),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        12: {
            "category": "Cnstwk",
            "ntce": _shift(today, -60),
            "close": _shift(today, 1),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        13: {
            "category": "Cnstwk",
            "ntce": _shift(today, -60),
            "close": _at(prev_month_end),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        14: {
            "category": "Servc",
            "ntce": _shift(today, -60),
            "close": _shift(today, -2),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        15: {
            "category": "Servc",
            "ntce": _shift(today, -60),
            "close": _at(today, 12),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        16: {
            "category": "Servc",
            "ntce": _shift(today, -60),
            "close": _shift(today, 6),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        17: {
            "category": "Servc",
            "ntce": _shift(today, -60),
            "close": _shift(today, 7),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        18: {
            "category": "Cnstwk",
            "ntce": _shift(today, -60),
            "close": _shift(today, 2),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
        19: {
            "category": "Servc",
            "ntce": _shift(today, -1),
            "close": _shift(today, 9),
            "presmpt_prce": 700_000_000,
            "base_amount": 50_000_000,
        },
        20: {
            "category": "Servc",
            "ntce": _shift(today, -2),
            "close": _shift(today, 10),
            "presmpt_prce": 2_000_000_000,
            "base_amount": 50_000_000,
        },
        21: {
            "category": "Servc",
            "ntce": _shift(today, -30),
            "close": _shift(today, -25),
            "presmpt_prce": 4_497_181_844_971_810,
            "base_amount": 50_000_000,
        },
        22: {
            "category": "Cnstwk",
            "ntce": _at(date(today.year, 2, 1)),
            "close": _shift(today, 11),
            "presmpt_prce": 7_000_000_000,
            "base_amount": 50_000_000,
        },
        23: {
            "category": "Cnstwk",
            "ntce": _at(last_year_end),
            "close": _shift(today, 12),
            "presmpt_prce": 8_000_000_000,
            "base_amount": 50_000_000,
        },
        24: {
            "category": "Servc",
            "ntce": _at(prev_month_end),
            "close": _shift(today, -5),
            "presmpt_prce": 50_000_000,
            "base_amount": 50_000_000,
        },
    }


@pytest.fixture
def announcement_specs(frozen_today):
    return _announcement_rows(frozen_today)


@pytest.fixture
def announcement_rows(isolated_db, announcement_specs):
    rows = []
    for index, spec in announcement_specs.items():
        rows.append(
            BidAnnouncement(
                bid_ntce_no=f"CNT-{index:03d}",
                bid_ntce_ord="000",
                category=spec["category"],
                bid_ntce_nm=f"조건 공고 {index}",
                dminstt_nm="수요기관",
                presmpt_prce=spec["presmpt_prce"],
                base_amount=spec["base_amount"],
                bid_ntce_dt=spec["ntce"],
                bid_clse_dt=spec["close"],
                collected_at=spec["ntce"],
            )
        )
    isolated_db.add_all(rows)
    isolated_db.commit()
    return rows


@pytest.fixture
def result_rows(isolated_db, frozen_today):
    rows = [
        _result(1, rl_openg_dt=_shift(frozen_today, -100)),
        _result(2, rl_openg_dt=_shift(frozen_today, -3)),
        _result(3, rl_openg_dt=_shift(frozen_today, -1830)),
    ]
    isolated_db.add_all(rows)
    isolated_db.commit()
    return rows


def _result(index: int, *, rl_openg_dt: datetime) -> BidResult:
    return BidResult(
        bid_ntce_no=f"CNT-RES-{index:03d}",
        bid_ntce_ord="000",
        category="Servc",
        bid_ntce_nm=f"조건 낙찰 {index}",
        dminstt_nm="수요기관",
        bidwinnr_nm="낙찰업체",
        sucsf_bid_amt=100_000_000,
        rl_openg_dt=rl_openg_dt,
        collected_at=rl_openg_dt,
    )


def _execute(db, query: str) -> tuple[dict, RetrievalPlan]:
    result = bid_query_tool.execute(db=db, query=query)
    filters = dict(result["retrieval_plan"]["filters"])
    plan = RetrievalPlan(use_sql=True, filters=filters, semantic_query=query)
    return result, plan


def _count(specs: dict[int, dict], predicate) -> int:
    return sum(1 for spec in specs.values() if predicate(spec))


def _day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time())


def test_amount_condition_and_recent_window_count_construction_announcements(
    frozen_today, isolated_db, announcement_specs, announcement_rows
):
    query = "기초금액 3억 넘는 공사 공고 몇 건이야?"
    result, plan = _execute(isolated_db, query)

    expected = _count(
        announcement_specs,
        lambda spec: (
            spec["category"] == "Cnstwk"
            and spec["base_amount"] > 300_000_000
            and _day_start(frozen_today) - timedelta(days=RECENT_ANNOUNCEMENT_WINDOW_DAYS - 1)
            <= spec["ntce"]
            <= _day_start(frozen_today) + timedelta(days=1)
        ),
    )
    assert plan.filters["min_amount"] == 300_000_001
    assert plan.filters["amount_field"] == "base_amount"
    assert plan.filters["recent_days"] == RECENT_ANNOUNCEMENT_WINDOW_DAYS
    assert result["result"]["summary"]["announcement_count"] == expected == 2


def test_estimated_price_condition_counts_only_above_bound(
    frozen_today, isolated_db, announcement_specs, announcement_rows
):
    query = "추정가격 5억 이상 용역 공고 몇 건이야"
    result, plan = _execute(isolated_db, query)

    expected = _count(
        announcement_specs,
        lambda spec: (
            spec["category"] == "Servc"
            and spec["presmpt_prce"] >= 500_000_000
            and spec["ntce"]
            >= _day_start(frozen_today) - timedelta(days=RECENT_ANNOUNCEMENT_WINDOW_DAYS - 1)
        ),
    )
    assert plan.filters["min_amount"] == 500_000_000
    assert plan.filters["amount_field"] == "presmpt_prce"
    assert result["result"]["summary"]["announcement_count"] == expected == 3


def test_past_this_month_deadlines_use_close_window_without_notice_window(
    frozen_today, isolated_db, announcement_specs, announcement_rows
):
    query = "이번 달 마감일이 지난 공사 공고 몇 건이야?"
    result, plan = _execute(isolated_db, query)

    month_start = frozen_today.replace(day=1)
    expected = _count(
        announcement_specs,
        lambda spec: (
            spec["category"] == "Cnstwk"
            and _day_start(month_start) <= spec["close"] < _day_start(frozen_today)
        ),
    )
    assert plan.filters["close_from"] == month_start.isoformat()
    assert plan.filters["close_to"] == (frozen_today - timedelta(days=1)).isoformat()
    assert "date_from" not in plan.filters
    assert "date_to" not in plan.filters
    assert result["result"]["summary"]["announcement_count"] == expected == 2


def test_this_week_deadline_list_includes_today_through_six_days_later(
    frozen_today, isolated_db, announcement_specs, announcement_rows
):
    query = "이번 주 마감되는 용역 공고 5개만 보여줘"
    result, plan = _execute(isolated_db, query)

    expected = _count(
        announcement_specs,
        lambda spec: (
            spec["category"] == "Servc"
            and _day_start(frozen_today)
            <= spec["close"]
            < _day_start(frozen_today + timedelta(days=7))
        ),
    )
    samples = result["result"]["summary"]["sample_announcements"]
    assert plan.filters["close_from"] == frozen_today.isoformat()
    assert plan.filters["close_to"] == (frozen_today + timedelta(days=6)).isoformat()
    assert len(samples) == expected == 2
    for sample in samples:
        assert (
            frozen_today.isoformat()
            <= sample["bid_clse_dt"][:10]
            <= (frozen_today + timedelta(days=6)).isoformat()
        )


def test_periodless_service_count_uses_recent_30_days(
    frozen_today, isolated_db, announcement_specs, announcement_rows
):
    query = "용역 공고 몇 건이야"
    result, plan = _execute(isolated_db, query)

    window_start = _day_start(frozen_today) - timedelta(days=RECENT_ANNOUNCEMENT_WINDOW_DAYS - 1)
    expected = _count(
        announcement_specs,
        lambda spec: (
            spec["category"] == "Servc"
            and window_start <= spec["ntce"] < _day_start(frozen_today) + timedelta(days=1)
        ),
    )
    assert plan.filters["date_from"] == window_start.date().isoformat()
    assert plan.filters["date_to"] == frozen_today.isoformat()
    assert result["result"]["summary"]["announcement_count"] == expected == 6

    answer = _build_single_metric_answer(plan, result["result"])
    assert "최근 30일" in answer
    assert "6건" in answer


def test_amount_sorted_list_uses_recent_30_days_and_ignores_outside_values(
    frozen_today, isolated_db, announcement_specs, announcement_rows
):
    query = "추정가격 높은 순으로 용역 공고 5개 보여줘"
    result, plan = _execute(isolated_db, query)

    window_start = _day_start(frozen_today) - timedelta(days=RECENT_ANNOUNCEMENT_WINDOW_DAYS - 1)
    amounts = sorted(
        (
            spec["presmpt_prce"]
            for spec in announcement_specs.values()
            if spec["category"] == "Servc"
            and window_start <= spec["ntce"] < _day_start(frozen_today) + timedelta(days=1)
        ),
        reverse=True,
    )
    samples = result["result"]["summary"]["sample_announcements"]

    assert plan.filters["recent_days"] == RECENT_ANNOUNCEMENT_WINDOW_DAYS
    assert [sample["presmpt_prce"] for sample in samples] == amounts[:5]
    assert samples[0]["presmpt_prce"] == 2_000_000_000
    for sample in samples:
        assert sample["bid_ntce_dt"][:10] >= window_start.date().isoformat()


def test_this_year_amount_sorted_list_keeps_this_year_window(
    frozen_today, isolated_db, announcement_specs, announcement_rows
):
    query = "올해 추정가격 높은 순 공사 공고"
    result, plan = _execute(isolated_db, query)

    year_start = date(frozen_today.year, 1, 1)
    samples = result["result"]["summary"]["sample_announcements"]
    assert plan.filters["date_from"] == year_start.isoformat()
    assert plan.filters["date_to"] == frozen_today.isoformat()
    assert "recent_days" not in plan.filters
    assert samples[0]["bid_ntce_no"] == "CNT-022"
    assert all(sample["bid_ntce_no"] != "CNT-023" for sample in samples)


def test_periodless_result_count_keeps_five_year_window(
    frozen_today, isolated_db, result_rows, announcement_rows
):
    query = "낙찰 건수 몇 건이야"
    result, plan = _execute(isolated_db, query)

    assert plan.filters["relative_years"] == 5
    assert "recent_days" not in plan.filters
    assert result["result"]["summary"]["total_bids"] == 2


def test_this_month_service_count_keeps_explicit_notice_window(
    frozen_today, isolated_db, announcement_specs, announcement_rows
):
    query = "이번 달 용역 공고 몇 건"
    result, plan = _execute(isolated_db, query)

    month_start = frozen_today.replace(day=1)
    expected = _count(
        announcement_specs,
        lambda spec: (
            spec["category"] == "Servc"
            and _day_start(month_start)
            <= spec["ntce"]
            < _day_start(frozen_today) + timedelta(days=1)
        ),
    )
    assert plan.filters["date_from"] == month_start.isoformat()
    assert plan.filters["date_to"] == frozen_today.isoformat()
    assert "recent_days" not in plan.filters
    assert result["result"]["summary"]["announcement_count"] == expected == 5
