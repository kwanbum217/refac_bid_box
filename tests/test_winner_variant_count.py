"""
tests/test_winner_variant_count.py

업체를 지목한 낙찰 건수·목록 응답이 정확 일치 값과, 상호에 그 이름이 들어간
다른 업체(지점·가맹점)의 건수를 구분해 알려주는지 검증합니다.

기본 값은 정규화 등호 기준 그대로 두고, 부분 일치 다른 상호가 1건 이상일
때만 같은 기간·분류·지역 조건의 건수와 합계를 한 줄 덧붙입니다.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.app.core.cache import cache
from src.app.models.bids import BidResult
from src.rag import query_planning
from src.rag.answer_format import _build_result_list_answer, _build_single_metric_answer
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data

FIXED_TODAY = date(2026, 10, 25)
COUNT_QUERY = "아이비클럽의 최근 30일 낙찰 건수 알려줘"


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


@pytest.fixture
def fixed_today(monkeypatch):
    """상대 기간 해석 기준일을 고정합니다."""

    class _FixedDate(date):
        @classmethod
        def today(cls):
            return FIXED_TODAY

    monkeypatch.setattr(query_planning, "date", _FixedDate)
    return FIXED_TODAY


def _seed_result(
    session,
    *,
    row_id: int,
    winner: str,
    opened_at: datetime,
    category: str = "Servc",
    institution: str = "서울특별시",
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"WIN-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"{institution} 공고 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=winner,
            sucsf_bid_amt=1000,
            sucsf_bid_rate=90.0,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


@pytest.fixture
def variant_db(isolated_db):
    # 정확 일치 3건: 법인 표기 변형은 같은 상호로 묶입니다.
    _seed_result(isolated_db, row_id=1, winner="아이비클럽", opened_at=datetime(2026, 10, 24, 9))
    _seed_result(isolated_db, row_id=2, winner="아이비클럽", opened_at=datetime(2026, 10, 20, 9))
    _seed_result(
        isolated_db, row_id=3, winner="주식회사 아이비클럽", opened_at=datetime(2026, 10, 10, 9)
    )
    # 상호에 이름이 들어간 다른 업체 2건.
    _seed_result(
        isolated_db, row_id=4, winner="아이비클럽 송파점", opened_at=datetime(2026, 10, 21, 9)
    )
    _seed_result(
        isolated_db, row_id=5, winner="여주 아이비클럽", opened_at=datetime(2026, 10, 12, 9)
    )
    # 기간 밖 지점은 세지 않습니다.
    _seed_result(
        isolated_db, row_id=6, winner="아이비클럽(아산점)", opened_at=datetime(2025, 12, 30, 9)
    )
    _seed_result(isolated_db, row_id=7, winner="대광기공", opened_at=datetime(2026, 10, 22, 9))
    isolated_db.commit()
    return isolated_db


@pytest.fixture
def exact_only_db(isolated_db):
    # 정확 일치 3건과 기간 밖 지점 1건만 있습니다.
    _seed_result(isolated_db, row_id=1, winner="아이비클럽", opened_at=datetime(2026, 10, 24, 9))
    _seed_result(isolated_db, row_id=2, winner="아이비클럽", opened_at=datetime(2026, 10, 20, 9))
    _seed_result(
        isolated_db, row_id=3, winner="(주)아이비클럽", opened_at=datetime(2026, 10, 10, 9)
    )
    _seed_result(
        isolated_db, row_id=4, winner="아이비클럽(아산점)", opened_at=datetime(2025, 12, 30, 9)
    )
    isolated_db.commit()
    return isolated_db


@pytest.fixture
def short_name_db(isolated_db):
    _seed_result(isolated_db, row_id=1, winner="한백", opened_at=datetime(2026, 10, 24, 9))
    _seed_result(isolated_db, row_id=2, winner="한백", opened_at=datetime(2026, 10, 20, 9))
    _seed_result(isolated_db, row_id=3, winner="한백건설", opened_at=datetime(2026, 10, 21, 9))
    isolated_db.commit()
    return isolated_db


def test_count_answer_keeps_exact_value_and_adds_variant_notice(variant_db, fixed_today):
    plan = build_retrieval_plan(COUNT_QUERY)

    assert plan.filters["winner_name"] == "아이비클럽"
    structured = retrieve_structured_data(variant_db, plan)

    assert structured["summary"]["total_bids"] == 3
    variant = structured["winner_variant"]
    assert variant["other_count"] == 2
    assert variant["total_count"] == 5

    answer = _build_single_metric_answer(plan, structured)
    assert "3건" in answer
    assert "다른 업체(지점 등) 낙찰은 같은 기간 2건" in answer
    assert "합치면 5건" in answer


def test_list_answer_appends_variant_notice(variant_db, fixed_today):
    plan = build_retrieval_plan("아이비클럽의 최근 30일 낙찰 결과 5건 보여줘")
    structured = retrieve_structured_data(variant_db, plan)

    answer = _build_result_list_answer(plan, structured)

    assert answer
    assert "합치면 5건" in answer
    # 목록 자체는 정확 일치 행만 보여 줍니다.
    assert "송파점" not in answer
    assert "여주 아이비클럽" not in answer


def test_no_notice_when_other_names_are_outside_window(exact_only_db, fixed_today):
    plan = build_retrieval_plan(COUNT_QUERY)
    structured = retrieve_structured_data(exact_only_db, plan)

    assert structured["summary"]["total_bids"] == 3
    assert "winner_variant" not in structured

    answer = _build_single_metric_answer(plan, structured)
    assert "3건" in answer
    assert "다른 업체(지점 등)" not in answer


def test_variant_count_honors_category_condition(variant_db, fixed_today):
    _seed_result(
        variant_db,
        row_id=9,
        winner="아이비클럽 건설지점",
        opened_at=datetime(2026, 10, 19, 9),
        category="Cnstwk",
    )
    variant_db.commit()
    plan = RetrievalPlan(
        use_sql=True,
        filters={
            "winner_name": "아이비클럽",
            "category": "Servc",
            "date_from": "2026-09-26",
            "date_to": "2026-10-25",
        },
        semantic_query=COUNT_QUERY,
    )
    structured = retrieve_structured_data(variant_db, plan)

    assert structured["summary"]["total_bids"] == 3
    assert structured["winner_variant"]["other_count"] == 2


def test_two_character_name_skips_variant_notice(short_name_db, fixed_today):
    plan = build_retrieval_plan("한백의 최근 30일 낙찰 건수 알려줘")
    structured = retrieve_structured_data(short_name_db, plan)

    assert structured["summary"]["total_bids"] == 2
    assert "winner_variant" not in structured
    assert "다른 업체(지점 등)" not in _build_single_metric_answer(plan, structured)


def test_variant_notice_mentions_period_and_other_count(variant_db, fixed_today):
    plan = build_retrieval_plan(COUNT_QUERY)
    structured = retrieve_structured_data(variant_db, plan)

    notice = structured["winner_variant"]["notice"]
    assert "상호에 아이비클럽이 들어간" in notice
    assert "2건" in notice
    assert "5건" in notice
