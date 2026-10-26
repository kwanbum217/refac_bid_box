"""
tests/test_deadline_amount_sort.py

마감일·금액·정렬 조건을 공통 파서가 읽고 정형 조회가 실제로 거르는지 검증합니다.
기준일은 2026-10-25(일요일)로 고정합니다.
"""

from datetime import date, datetime

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag import query_planning
from src.rag.answer_format import (
    _build_announcement_list_answer,
    _build_result_list_answer,
    _build_single_metric_answer,
)
from src.rag.query_planning import build_retrieval_plan, extract_result_limit
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

FROZEN_TODAY = date(2026, 10, 25)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return FROZEN_TODAY


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


def test_this_week_deadline_window_uses_close_dates(frozen_today):
    plan = build_retrieval_plan("이번 주 마감되는 용역 공고 5개만 보여줘")

    assert plan.use_sql is True
    assert plan.filters.get("close_from") == "2026-10-25"
    assert plan.filters.get("close_to") == "2026-10-31"
    assert "date_from" not in plan.filters
    assert "date_to" not in plan.filters
    assert plan.filters.get("category") == "Servc"
    assert plan.filters.get("announcement_limit") == 5


@pytest.mark.parametrize(
    "query,close_from,close_to",
    [
        ("내일 마감인 공고 목록 보여줘", "2026-10-26", "2026-10-26"),
        ("오늘 마감인 공사 공고 목록 보여줘", "2026-10-25", "2026-10-25"),
        ("마감 임박한 용역 공고 5개 보여줘", "2026-10-25", "2026-10-28"),
    ],
)
def test_relative_deadline_windows(frozen_today, query, close_from, close_to):
    plan = build_retrieval_plan(query)

    assert plan.filters.get("close_from") == close_from
    assert plan.filters.get("close_to") == close_to
    assert "date_from" not in plan.filters
    assert "date_to" not in plan.filters


@pytest.mark.parametrize(
    "query,expected",
    [
        (
            "추정가격 5억 이상 용역 공고 5개 보여줘",
            {"min_amount": 500_000_000, "amount_field": "presmpt_prce"},
        ),
        (
            "1억 이하 물품 공고 리스트로 알려줘",
            {"max_amount": 100_000_000, "amount_field": "presmpt_prce"},
        ),
        (
            "기초금액 3억 넘는 공사 공고 찾아줘",
            {"min_amount": 300_000_001, "amount_field": "base_amount"},
        ),
        (
            "낙찰금액 10억 이상인 공사 결과 보여줘",
            {"min_amount": 1_000_000_000, "amount_field": "sucsf_bid_amt"},
        ),
    ],
)
def test_amount_boundaries(query, expected):
    plan = build_retrieval_plan(query)

    for key, value in expected.items():
        assert plan.filters.get(key) == value


def test_amount_condition_is_not_read_as_list_limit():
    plan = build_retrieval_plan("참가업체 수 10개 이상인 공고 보여줘")

    assert plan.filters.get("announcement_limit") == 5
    assert "min_amount" not in plan.filters
    assert extract_result_limit("참가업체 수 10개 이상인 공고 보여줘") == 5
    assert extract_result_limit("추정가격 5억 이상 용역 공고 5개 보여줘") == 5
    assert extract_result_limit("추정가격 3억 이상인 공고 12건 보여줘") == 12


def test_number_without_unit_or_amount_noun_is_not_an_amount_condition():
    plan = build_retrieval_plan("5 이상 공고 보여줘")

    assert plan.filters == build_retrieval_plan("공고 보여줘").filters
    assert "min_amount" not in plan.filters
    assert "max_amount" not in plan.filters
    assert "amount_field" not in plan.filters


def test_result_query_without_amount_field_uses_winning_amount():
    plan = build_retrieval_plan("3억 넘는 낙찰 결과 5건")

    assert plan.filters.get("min_amount") == 300_000_001
    assert plan.filters.get("amount_field") == "sucsf_bid_amt"
    assert plan.filters.get("result_limit") == 5


def test_announcement_query_keeps_estimated_price_field():
    plan = build_retrieval_plan("5억 이상 용역 공고 5개")

    assert plan.filters.get("min_amount") == 500_000_000
    assert plan.filters.get("amount_field") == "presmpt_prce"
    assert plan.filters.get("announcement_limit") == 5


@pytest.mark.parametrize(
    "query,order_by,order_dir",
    [
        ("추정가격 높은 순으로 용역 공고 5개 보여줘", "presmpt_prce", "desc"),
        ("추정가격 낮은 순으로 용역 공고 5개 보여줘", "presmpt_prce", "asc"),
        ("금액순으로 용역 공고 정렬해줘", "presmpt_prce", "desc"),
        ("마감 임박순으로 용역 공고 5개 보여줘", "bid_clse_dt", "asc"),
    ],
)
def test_sort_filters(query, order_by, order_dir):
    plan = build_retrieval_plan(query)

    assert plan.filters.get("order_by") == order_by
    assert plan.filters.get("order_dir") == order_dir


@pytest.mark.parametrize(
    "query",
    [
        "마감 임박순 공고 5개",
        "마감 임박순으로 용역 공고 5개 보여줘",
        "마감 빠른 순 용역 공고",
        "마감일 순으로 용역 공고 5개 보여줘",
    ],
)
def test_deadline_sort_expression_does_not_create_close_window(frozen_today, query):
    plan = build_retrieval_plan(query)

    assert "close_from" not in plan.filters
    assert "close_to" not in plan.filters
    assert plan.filters.get("order_by") == "bid_clse_dt"
    assert plan.filters.get("order_dir") == "asc"


def test_deadline_sort_keeps_list_limit(frozen_today):
    plan = build_retrieval_plan("마감 임박순 공고 5개")

    assert plan.filters.get("announcement_limit") == 5


def test_deadline_imminent_without_sort_suffix_keeps_window(frozen_today):
    plan = build_retrieval_plan("마감 임박 공고 보여줘")

    assert plan.filters.get("close_from") == "2026-10-25"
    assert plan.filters.get("close_to") == "2026-10-28"
    assert "order_by" not in plan.filters


@pytest.mark.parametrize(
    "query,filters_key",
    [
        ("공고 10건 이상 보여줘", "announcement_limit"),
        ("낙찰 결과 10개 이상 보여줘", "result_limit"),
    ],
)
def test_list_count_with_comparator_is_still_a_limit(query, filters_key):
    plan = build_retrieval_plan(query)

    assert plan.filters.get(filters_key) == 10
    assert extract_result_limit(query) == 10


def test_queries_without_new_markers_keep_existing_filters(frozen_today):
    list_plan = build_retrieval_plan("최근 용역 공고 5개만 리스트해줘")
    assert list_plan.filters == {
        "date_from": "2026-10-19",
        "date_to": "2026-10-25",
        "category": "Servc",
        "announcement_limit": 5,
    }

    count_plan = build_retrieval_plan("이번 주 공고 몇 건이야")
    assert count_plan.filters == {"date_from": "2026-10-19", "date_to": "2026-10-25"}

    explicit_plan = build_retrieval_plan(
        "2025년 12월 31일 23시 59분에 마감된 공고와 2026년 1월 1일 00시에 공고된 사업의 "
        "연도 구분을 정확히 하여 2026년도 신규 사업만 골라줘"
    )
    assert explicit_plan.filters == {"date_from": "2025-12-31", "date_to": "2026-01-01"}


def _announcement(
    index: int,
    *,
    bid_ntce_dt: datetime,
    bid_clse_dt: datetime,
    presmpt_prce: int,
) -> BidAnnouncement:
    return BidAnnouncement(
        bid_ntce_no=f"SERVC-{index:03d}",
        bid_ntce_ord="000",
        category="Servc",
        bid_ntce_nm=f"용역 공고 {index}",
        dminstt_nm="수요기관",
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=bid_ntce_dt,
        bid_clse_dt=bid_clse_dt,
        collected_at=bid_ntce_dt,
    )


@pytest.fixture
def announcement_rows(isolated_db):
    rows = [
        _announcement(
            1,
            bid_ntce_dt=datetime(2026, 10, 10),
            bid_clse_dt=datetime(2026, 10, 18),
            presmpt_prce=900_000_000,
        ),
        _announcement(
            2,
            bid_ntce_dt=datetime(2026, 10, 11),
            bid_clse_dt=datetime(2026, 10, 19),
            presmpt_prce=100_000_000,
        ),
        _announcement(
            3,
            bid_ntce_dt=datetime(2026, 10, 12),
            bid_clse_dt=datetime(2026, 10, 22),
            presmpt_prce=600_000_000,
        ),
        _announcement(
            4,
            bid_ntce_dt=datetime(2026, 10, 13),
            bid_clse_dt=datetime(2026, 10, 25),
            presmpt_prce=200_000_000,
        ),
        _announcement(
            5,
            bid_ntce_dt=datetime(2026, 10, 14),
            bid_clse_dt=datetime(2026, 10, 26),
            presmpt_prce=800_000_000,
        ),
        _announcement(
            6,
            bid_ntce_dt=datetime(2026, 10, 15),
            bid_clse_dt=datetime(2026, 10, 20),
            presmpt_prce=400_000_000,
        ),
    ]
    for row in rows:
        isolated_db.add(row)
    isolated_db.commit()
    return rows


def test_close_window_excludes_rows_outside_this_week(frozen_today, isolated_db, announcement_rows):
    plan = build_retrieval_plan("이번 주 마감되는 용역 공고 5개 보여줘")
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    assert [sample["bid_ntce_no"] for sample in samples] == [
        "SERVC-005",
        "SERVC-004",
    ]
    for sample in samples:
        assert "2026-10-25" <= sample["bid_clse_dt"][:10] <= "2026-10-31"


def test_min_amount_excludes_rows_below_bound(isolated_db, announcement_rows):
    plan = build_retrieval_plan("추정가격 5억 이상 용역 공고 5개 보여줘")
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    assert [sample["bid_ntce_no"] for sample in samples] == [
        "SERVC-005",
        "SERVC-003",
        "SERVC-001",
    ]
    for sample in samples:
        assert sample["presmpt_prce"] >= 500_000_000


def test_descending_amount_sort_puts_largest_first(isolated_db, announcement_rows):
    plan = build_retrieval_plan("추정가격 높은 순으로 용역 공고 5개 보여줘")
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    amounts = [sample["presmpt_prce"] for sample in samples]
    assert len(samples) == 5
    assert amounts == sorted(amounts, reverse=True)
    assert samples[0]["bid_ntce_no"] == "SERVC-001"


def test_deadline_sort_puts_earliest_deadline_first(isolated_db, announcement_rows):
    plan = build_retrieval_plan("마감일 순으로 용역 공고 5개 보여줘")
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]

    deadlines = [sample["bid_clse_dt"][:10] for sample in samples]
    assert deadlines == sorted(deadlines)


def test_deadline_and_amount_filters_apply_to_counts(frozen_today, isolated_db, announcement_rows):
    close_plan = build_retrieval_plan("이번 주 마감되는 용역 공고 몇 건이야")
    close_count = retrieve_structured_data(isolated_db, close_plan)["summary"]["announcement_count"]

    assert close_count == 2

    amount_plan = build_retrieval_plan("추정가격 5억 이상 용역 공고 몇 건이야")
    amount_count = retrieve_structured_data(isolated_db, amount_plan)["summary"][
        "announcement_count"
    ]

    assert amount_count == 3


def _result(index: int, *, sucsf_bid_amt: int, rl_openg_dt: datetime) -> BidResult:
    return BidResult(
        bid_ntce_no=f"RES-{index:03d}",
        bid_ntce_ord="000",
        category="Servc",
        bid_ntce_nm=f"용역 낙찰 {index}",
        dminstt_nm="수요기관",
        bidwinnr_nm="낙찰업체",
        sucsf_bid_amt=sucsf_bid_amt,
        rl_openg_dt=rl_openg_dt,
        collected_at=datetime(2026, 10, 20),
    )


@pytest.fixture
def result_rows(isolated_db):
    rows = [
        _result(1, sucsf_bid_amt=400_000_000, rl_openg_dt=datetime(2026, 10, 20)),
        _result(2, sucsf_bid_amt=300_000_000, rl_openg_dt=datetime(2026, 10, 21)),
        _result(3, sucsf_bid_amt=250_000_000, rl_openg_dt=datetime(2026, 10, 22)),
    ]
    for row in rows:
        isolated_db.add(row)
    isolated_db.commit()
    return rows


def test_result_amount_condition_excludes_rows_below_bound(isolated_db, result_rows):
    plan = build_retrieval_plan("3억 넘는 낙찰 결과 5건")
    recent = retrieve_structured_data(isolated_db, plan)["summary"]["recent_results"]

    assert [row["bid_ntce_no"] for row in recent] == ["RES-001"]
    for row in recent:
        assert row["sucsf_bid_amt"] > 300_000_000


UNAPPLIED_NOTICE = "그 조건 없이 조회했습니다"


def test_unapplied_estimated_price_condition_is_reported(isolated_db, result_rows):
    plan = build_retrieval_plan("추정가격 5억 이상 낙찰 결과 5건")
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("amount_field") == "presmpt_prce"
    assert structured_data["unapplied_conditions"] == [{"kind": "amount", "field": "presmpt_prce"}]
    assert any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])
    answer = _build_result_list_answer(plan, structured_data)
    assert "추정가격 정보가 없어" in answer
    assert UNAPPLIED_NOTICE in answer


def test_unapplied_deadline_sort_is_reported(isolated_db, result_rows):
    plan = build_retrieval_plan("마감 임박순 낙찰 결과 5건")
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("order_by") == "bid_clse_dt"
    assert structured_data["unapplied_conditions"] == [{"kind": "order", "field": "bid_clse_dt"}]
    assert any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])
    answer = _build_result_list_answer(plan, structured_data)
    assert "마감일 정보가 없어" in answer
    assert UNAPPLIED_NOTICE in answer


def test_unapplied_amount_and_sort_conditions_are_combined(isolated_db, result_rows):
    plan = build_retrieval_plan("추정가격 5억 이상 마감 임박순 낙찰 결과 5건")
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert structured_data["unapplied_conditions"] == [
        {"kind": "amount", "field": "presmpt_prce"},
        {"kind": "order", "field": "bid_clse_dt"},
    ]
    assert "추정가격·마감일 정보가 없어" in _build_result_list_answer(plan, structured_data)


def test_supported_result_amount_condition_has_no_notice(isolated_db, result_rows):
    plan = build_retrieval_plan("낙찰금액 10억 이상 낙찰 결과 5건")
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("amount_field") == "sucsf_bid_amt"
    assert structured_data["unapplied_conditions"] == []
    assert not any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])
    assert UNAPPLIED_NOTICE not in _build_result_list_answer(plan, structured_data)


def test_announcement_conditions_are_not_reported_as_unapplied(isolated_db, announcement_rows):
    plan = build_retrieval_plan("추정가격 5억 이상 용역 공고 5개 보여줘")
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert structured_data["unapplied_conditions"] == []
    assert not any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])


@pytest.mark.parametrize(
    "query,close_from,close_to",
    [
        ("이번 주 마감되는 낙찰 결과 5건", "2026-10-25", "2026-10-31"),
        ("마감 임박 낙찰 결과 보여줘", "2026-10-25", "2026-10-28"),
    ],
)
def test_unapplied_close_window_is_reported_for_result_lists(
    frozen_today, isolated_db, result_rows, query, close_from, close_to
):
    plan = build_retrieval_plan(query)
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("close_from") == close_from
    assert plan.filters.get("close_to") == close_to
    assert structured_data["unapplied_conditions"] == [
        {"kind": "close_window", "field": "bid_clse_dt"}
    ]
    assert any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])
    answer = _build_result_list_answer(plan, structured_data)
    assert "마감일 정보가 없어" in answer
    assert UNAPPLIED_NOTICE in answer


def test_close_window_applies_to_announcements_without_notice(
    frozen_today, isolated_db, announcement_rows
):
    plan = build_retrieval_plan("이번 주 마감되는 용역 공고 5개만 보여줘")
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("close_from") == "2026-10-25"
    assert plan.filters.get("close_to") == "2026-10-31"
    assert structured_data["unapplied_conditions"] == []
    assert not any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])
    samples = structured_data["summary"]["sample_announcements"]
    assert samples
    for sample in samples:
        assert "2026-10-25" <= sample["bid_clse_dt"][:10] <= "2026-10-31"


def test_announcement_list_answer_shows_applied_conditions():
    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "category": "Servc",
            "announcement_limit": 1,
            "close_from": "2026-10-19",
            "close_to": "2026-10-25",
            "min_amount": 500_000_000,
            "amount_field": "presmpt_prce",
            "order_by": "presmpt_prce",
            "order_dir": "desc",
        },
    )
    structured_data = {
        "filters": {"category": "Servc", "category_label": "용역"},
        "summary": {"sample_announcements": [_sample_row()]},
    }

    answer = _build_announcement_list_answer(plan, structured_data)
    condition_line = answer.splitlines()[2]

    assert answer.splitlines()[0] == "조건에 맞는 용역 공고 1건입니다."
    assert condition_line.startswith("적용 조건: ")
    assert "마감일 2026-10-19~2026-10-25" in condition_line
    assert "추정가격 500,000,000원 이상" in condition_line
    assert "추정가격 내림차순" in condition_line


def _sample_row() -> dict:
    return {
        "bid_ntce_no": "SERVC-001",
        "bid_ntce_nm": "용역 공고 1",
        "dminstt_nm": "수요기관",
        "presmpt_prce": 900_000_000,
        "bid_ntce_dt": "2026-10-10 09:00:00",
        "bid_clse_dt": "2026-10-25 18:00:00",
    }


@pytest.mark.parametrize(
    "query,scope,limit_key",
    [
        ("10억 넘는 낙찰 결과 보여줘", "result", "result_limit"),
        ("5억 이상 용역 공고 보여줘", "announcement", "announcement_limit"),
        ("마감 임박순 공고 보여줘", "announcement", "announcement_limit"),
    ],
)
def test_parsed_condition_is_a_list_scope_marker(frozen_today, query, scope, limit_key):
    plan = build_retrieval_plan(query)

    assert query_planning.is_result_list_query(query) is (scope == "result")
    assert query_planning.is_announcement_list_query(query) is (scope == "announcement")
    assert plan.use_sql is True
    assert plan.filters.get(limit_key) == 5


def test_condition_only_result_list_uses_winning_amount():
    plan = build_retrieval_plan("10억 넘는 낙찰 결과 보여줘")

    assert plan.filters.get("min_amount") == 1_000_000_001
    assert plan.filters.get("amount_field") == "sucsf_bid_amt"
    assert plan.filters.get("result_limit") == 5


def test_condition_only_result_list_excludes_rows_below_bound(isolated_db, result_rows):
    isolated_db.add(_result(4, sucsf_bid_amt=1_500_000_000, rl_openg_dt=datetime(2026, 10, 23)))
    isolated_db.commit()

    plan = build_retrieval_plan("10억 넘는 낙찰 결과 보여줘")
    recent = retrieve_structured_data(isolated_db, plan)["summary"]["recent_results"]

    assert [row["bid_ntce_no"] for row in recent] == ["RES-004"]
    for row in recent:
        assert row["sucsf_bid_amt"] > 1_000_000_000


def test_condition_with_statistics_marker_stays_statistics():
    query = "3억 넘는 낙찰 건수 알려줘"
    plan = build_retrieval_plan(query)

    assert query_planning.is_result_list_query(query) is False
    assert query_planning.is_announcement_list_query(query) is False
    assert "result_limit" not in plan.filters
    assert "announcement_limit" not in plan.filters
    assert plan.route_reason == "정형 통계 질의"


def test_result_count_query_without_amount_field_uses_winning_amount():
    query = "3억 넘는 낙찰 건수 알려줘"
    plan = build_retrieval_plan(query)

    assert plan.filters.get("min_amount") == 300_000_001
    assert plan.filters.get("amount_field") == "sucsf_bid_amt"
    assert plan.route_reason == "정형 통계 질의"
    assert query_planning.is_result_amount_scope(query) is True


def test_result_count_aggregate_excludes_rows_below_bound(isolated_db, result_rows):
    plan = build_retrieval_plan("3억 넘는 낙찰 건수 알려줘")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    assert summary["total_bids"] == 1


def test_average_winning_rate_query_without_amount_field_uses_winning_amount():
    plan = build_retrieval_plan("5억 이상 낙찰 평균 낙찰률 알려줘")

    assert plan.filters.get("min_amount") == 500_000_000
    assert plan.filters.get("amount_field") == "sucsf_bid_amt"
    assert plan.route_reason == "정형 통계 질의"


def test_announcement_count_query_keeps_estimated_price_field():
    query = "5억 이상 용역 공고 몇 건이야"
    plan = build_retrieval_plan(query)

    assert plan.filters.get("min_amount") == 500_000_000
    assert plan.filters.get("amount_field") == "presmpt_prce"
    assert query_planning.is_result_amount_scope(query) is False


def test_estimated_price_result_count_reports_unapplied_condition(isolated_db, result_rows):
    query = "추정가격 5억 이상 낙찰 건수"
    plan = build_retrieval_plan(query)
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("amount_field") == "presmpt_prce"
    assert plan.route_reason == "정형 통계 질의"
    assert structured_data["unapplied_conditions"] == [{"kind": "amount", "field": "presmpt_prce"}]
    assert any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])
    assert UNAPPLIED_NOTICE in _build_single_metric_answer(plan, structured_data)


def test_list_without_conditions_keeps_main_judgment():
    assert query_planning.is_result_list_query("낙찰 결과 보여줘") is True
    assert build_retrieval_plan("낙찰 결과 보여줘").filters == {"result_limit": 5}

    assert query_planning.is_announcement_list_query("공고 보여줘") is False
    assert build_retrieval_plan("공고 보여줘").filters == {}
    assert build_retrieval_plan("공고 보여줘").use_sql is False


@pytest.mark.parametrize(
    "query,order_dir,expected_order",
    [
        ("낙찰 결과 금액 낮은 순 3건", "asc", ["RES-003", "RES-002", "RES-001"]),
        ("낙찰금액 높은 순 낙찰 결과 5건", "desc", ["RES-001", "RES-002", "RES-003"]),
        ("금액 큰 순 낙찰 결과 보여줘", "desc", ["RES-001", "RES-002", "RES-003"]),
    ],
)
def test_result_amount_sort_without_field_uses_winning_amount(
    isolated_db, result_rows, query, order_dir, expected_order
):
    plan = build_retrieval_plan(query)

    assert plan.filters.get("order_by") == "sucsf_bid_amt"
    assert plan.filters.get("order_dir") == order_dir

    structured_data = retrieve_structured_data(isolated_db, plan)
    recent = structured_data["summary"]["recent_results"]

    assert [row["bid_ntce_no"] for row in recent] == expected_order
    assert structured_data["unapplied_conditions"] == []
    assert not any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])
    assert UNAPPLIED_NOTICE not in _build_result_list_answer(plan, structured_data)


def test_estimated_price_result_sort_keeps_unapplied_notice(isolated_db, result_rows):
    plan = build_retrieval_plan("추정가격 높은 순 낙찰 결과")
    structured_data = retrieve_structured_data(isolated_db, plan)

    assert plan.filters.get("order_by") == "presmpt_prce"
    assert structured_data["unapplied_conditions"] == [{"kind": "order", "field": "presmpt_prce"}]
    assert any(UNAPPLIED_NOTICE in hint for hint in structured_data["insufficiency_hints"])


def test_estimated_price_announcement_sort_stays_estimated_price():
    plan = build_retrieval_plan("추정가격 높은 순으로 용역 공고 5개 보여줘")

    assert plan.filters.get("order_by") == "presmpt_prce"
    assert plan.filters.get("order_dir") == "desc"
    assert plan.filters.get("announcement_limit") == 5
