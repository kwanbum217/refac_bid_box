"""
tests/test_deadline_amount_sort.py

마감일·금액·정렬 조건을 공통 파서가 읽고 정형 조회가 실제로 거르는지 검증합니다.
기준일은 2026-10-25(일요일)로 고정합니다.
"""

from datetime import date, datetime

import pytest

from src.app.models.bids import BidAnnouncement
from src.rag import query_planning
from src.rag.answer_format import _build_announcement_list_answer
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
    assert plan.filters.get("close_from") == "2026-10-19"
    assert plan.filters.get("close_to") == "2026-10-25"
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
        "SERVC-006",
        "SERVC-004",
        "SERVC-003",
        "SERVC-002",
    ]
    for sample in samples:
        assert "2026-10-19" <= sample["bid_clse_dt"][:10] <= "2026-10-25"


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

    assert close_count == 4

    amount_plan = build_retrieval_plan("추정가격 5억 이상 용역 공고 몇 건이야")
    amount_count = retrieve_structured_data(isolated_db, amount_plan)["summary"][
        "announcement_count"
    ]

    assert amount_count == 3


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
