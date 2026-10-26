"""
tests/test_max_value_answer.py

공고 금액 최댓값·최솟값 질문이 벡터 검색이 아니라 SQL 정렬 조회로 가고,
조회 1위를 결정론적 문장으로 답하는지 검증합니다.
기준일은 2026-10-25(일요일)로 고정합니다.
"""

from datetime import date, datetime

import pytest

from src.app.models.bids import BidAnnouncement
from src.rag import query_planning
from src.rag.answer_format import _build_amount_extreme_answer
from src.rag.query_planning import apply_default_statistics_window, build_retrieval_plan
from src.rag.structured_data import retrieve_structured_data

FROZEN_TODAY = date(2026, 10, 25)
MAX_QUESTION = "용역 공고 중 추정가격이 가장 큰 건 얼마야?"


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return FROZEN_TODAY


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


def _announcement(
    index: int,
    *,
    category: str = "Servc",
    bid_ntce_dt: datetime,
    bid_ntce_nm: str | None = None,
    dminstt_nm: str = "수요기관",
    presmpt_prce: int | None = None,
    base_amount: int | None = None,
) -> BidAnnouncement:
    return BidAnnouncement(
        bid_ntce_no=f"NOTICE-{index:03d}",
        bid_ntce_ord="000",
        category=category,
        bid_ntce_nm=bid_ntce_nm or f"공고 {index}",
        dminstt_nm=dminstt_nm,
        presmpt_prce=presmpt_prce,
        base_amount=base_amount,
        bid_ntce_dt=bid_ntce_dt,
        bid_clse_dt=bid_ntce_dt,
        collected_at=bid_ntce_dt,
    )


def _windowed_plan(plan):
    filters = apply_default_statistics_window(plan.filters, query=plan.semantic_query)
    return plan.model_copy(update={"filters": filters})


def test_max_question_routes_to_sql_single_row(frozen_today):
    plan = build_retrieval_plan(MAX_QUESTION)

    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters.get("amount_extreme") == "max"
    assert plan.filters.get("amount_field") == "presmpt_prce"
    assert plan.filters.get("order_by") == "presmpt_prce"
    assert plan.filters.get("order_dir") == "desc"
    assert plan.filters.get("announcement_limit") == 1
    assert plan.filters.get("category") == "Servc"
    assert plan.route_reason == "공고 금액 최댓값 질의"

    windowed = apply_default_statistics_window(plan.filters, query=plan.semantic_query)
    assert windowed.get("recent_days") == 30
    assert windowed.get("date_from") == "2026-09-26"
    assert windowed.get("date_to") == "2026-10-25"


@pytest.fixture
def max_rows(isolated_db):
    rows = [
        _announcement(
            1,
            bid_ntce_dt=datetime(2026, 10, 10),
            bid_ntce_nm="용역 최대 후보 1",
            dminstt_nm="기관A",
            presmpt_prce=900_000_000,
        ),
        _announcement(
            2,
            bid_ntce_dt=datetime(2026, 10, 12),
            bid_ntce_nm="용역 최대 후보 2",
            dminstt_nm="기관B",
            presmpt_prce=1_200_000_000,
        ),
        _announcement(
            3,
            bid_ntce_dt=datetime(2026, 9, 1),
            bid_ntce_nm="창 밖 초대형 공고",
            presmpt_prce=5_000_000_000,
        ),
        _announcement(
            4,
            category="Cnstwk",
            bid_ntce_dt=datetime(2026, 10, 11),
            bid_ntce_nm="분야가 다른 초대형 공고",
            presmpt_prce=9_000_000_000,
        ),
        _announcement(
            5,
            bid_ntce_dt=datetime(2026, 10, 13),
            bid_ntce_nm="금액 없는 공고",
            presmpt_prce=None,
        ),
    ]
    for row in rows:
        isolated_db.add(row)
    isolated_db.commit()
    return rows


def test_max_answer_uses_recent_30_day_sql_row(frozen_today, isolated_db, max_rows):
    plan = _windowed_plan(build_retrieval_plan(MAX_QUESTION))
    structured_data = retrieve_structured_data(isolated_db, plan)

    samples = structured_data["summary"]["sample_announcements"]
    assert [sample["bid_ntce_no"] for sample in samples] == ["NOTICE-002"]
    assert samples[0]["presmpt_prce"] == 1_200_000_000

    answer = _build_amount_extreme_answer(plan, structured_data)
    assert answer == (
        "최근 30일 용역 공고 중 추정가격이 가장 큰 공고는 "
        "용역 최대 후보 2(NOTICE-002, 기관B)이며 추정가격은 1,200,000,000원입니다."
    )
    assert "5,000,000,000원" not in answer
    assert "9,000,000,000원" not in answer
    assert "제공된 검색 컨텍스트" not in answer
    assert "presmpt_prce" not in answer


@pytest.fixture
def min_base_rows(isolated_db):
    rows = [
        _announcement(
            1,
            category="Cnstwk",
            bid_ntce_dt=datetime(2026, 10, 10),
            bid_ntce_nm="공사 최소 후보 1",
            base_amount=300_000_000,
        ),
        _announcement(
            2,
            category="Cnstwk",
            bid_ntce_dt=datetime(2026, 10, 12),
            bid_ntce_nm="공사 최소 후보 2",
            dminstt_nm="기관B",
            base_amount=100_000_000,
        ),
        _announcement(
            3,
            category="Cnstwk",
            bid_ntce_dt=datetime(2026, 10, 13),
            bid_ntce_nm="기초금액 없는 공고",
            base_amount=None,
        ),
        _announcement(
            4,
            category="Servc",
            bid_ntce_dt=datetime(2026, 10, 11),
            bid_ntce_nm="분야가 다른 최소 공고",
            base_amount=50_000_000,
        ),
    ]
    for row in rows:
        isolated_db.add(row)
    isolated_db.commit()
    return rows


def test_min_base_amount_question_uses_ascending_sql_row(frozen_today, isolated_db, min_base_rows):
    plan = _windowed_plan(build_retrieval_plan("기초금액 가장 작은 공사 공고"))

    assert plan.filters.get("amount_extreme") == "min"
    assert plan.filters.get("amount_field") == "base_amount"
    assert plan.filters.get("order_by") == "base_amount"
    assert plan.filters.get("order_dir") == "asc"

    structured_data = retrieve_structured_data(isolated_db, plan)
    samples = structured_data["summary"]["sample_announcements"]
    assert [sample["bid_ntce_no"] for sample in samples] == ["NOTICE-002"]
    assert samples[0]["base_amount"] == 100_000_000

    answer = _build_amount_extreme_answer(plan, structured_data)
    assert answer == (
        "최근 30일 건설 공고 중 기초금액이 가장 작은 공고는 "
        "공사 최소 후보 2(NOTICE-002, 기관B)이며 기초금액은 100,000,000원입니다."
    )
    assert "300,000,000원" not in answer
    assert "50,000,000원" not in answer
    assert "base_amount" not in answer


@pytest.fixture
def year_rows(isolated_db):
    rows = [
        _announcement(
            1,
            bid_ntce_dt=datetime(2025, 6, 1),
            bid_ntce_nm="2025 용역 후보",
            presmpt_prce=700_000_000,
        ),
        _announcement(
            2,
            bid_ntce_dt=datetime(2025, 7, 1),
            bid_ntce_nm="2025 용역 최대",
            presmpt_prce=800_000_000,
        ),
        _announcement(
            3,
            bid_ntce_dt=datetime(2026, 6, 1),
            bid_ntce_nm="2026 용역 초대형",
            presmpt_prce=9_000_000_000,
        ),
    ]
    for row in rows:
        isolated_db.add(row)
    isolated_db.commit()
    return rows


def test_explicit_year_max_stays_inside_year_window(frozen_today, isolated_db, year_rows):
    query = "2025년 용역 공고 중 추정가격 최대"
    plan = _windowed_plan(build_retrieval_plan(query))

    assert plan.use_sql is True
    assert plan.filters.get("amount_extreme") == "max"
    assert plan.filters.get("date_from") == "2025-01-01"
    assert plan.filters.get("date_to") == "2025-12-31"
    assert "recent_days" not in plan.filters

    structured_data = retrieve_structured_data(isolated_db, plan)
    answer = _build_amount_extreme_answer(plan, structured_data)

    assert "800,000,000원" in answer
    assert "2025 용역 최대(NOTICE-002" in answer
    assert "9,000,000,000원" not in answer


def test_ranking_without_amount_axis_keeps_existing_route():
    plan = build_retrieval_plan("가장 큰 기관 알려줘")

    assert plan.use_sql is False
    assert "amount_extreme" not in plan.filters
    assert "announcement_limit" not in plan.filters


@pytest.mark.parametrize(
    "query",
    [
        "추정가격이 가장 큰 공고 5개 보여줘",
        "추정가격 5억 이상 용역 공고 최대 5개 보여줘",
    ],
)
def test_list_request_is_not_hijacked_as_single_value_question(query):
    plan = build_retrieval_plan(query)

    assert "amount_extreme" not in plan.filters
    assert plan.filters.get("announcement_limit") == 5
