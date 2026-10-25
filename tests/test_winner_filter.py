"""
tests/test_winner_filter.py

특정 업체를 지목한 낙찰 이력 질의의 업체명 추출과 winner_name 조건 적용을
검증합니다.

업체명이 필터로 승격되지 않으면 업체 조건 없는 전체 최신 목록이 그 업체
실적처럼 답해집니다(조용한 범위 확대). 추출은 법인 형태 표지·업종 접미사·
"<업체>이/가 낙찰" 구조에서만 하고, 기관·분야어·순위 질의는 업체로 읽지
않습니다. 조회는 업체 조건이 걸린 행만 돌려주고, 없는 업체는 전체 목록으로
새지 않고 빈 결과를 냅니다.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.app.core.cache import cache
from src.app.models.bids import BidResult
from src.app.services.planner_interpreter import interpret_request
from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan, extract_winner_name
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import _snapshot_scope, retrieve_structured_data

FIXED_TODAY = date(2026, 10, 25)


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
def winner_db(isolated_db):
    _seed_result(isolated_db, row_id=1, winner="한백", opened_at=datetime(2026, 10, 24, 9, 0, 0))
    _seed_result(isolated_db, row_id=2, winner="한백", opened_at=datetime(2026, 10, 20, 9, 0, 0))
    # 작년 낙찰은 "올해" 창 밖이므로 업체 조건이 걸린 목록에서도 빠져야 합니다.
    _seed_result(isolated_db, row_id=3, winner="한백", opened_at=datetime(2025, 12, 30, 9, 0, 0))
    _seed_result(
        isolated_db, row_id=4, winner="대광기공", opened_at=datetime(2026, 10, 23, 9, 0, 0)
    )
    _seed_result(
        isolated_db, row_id=5, winner="대광기공", opened_at=datetime(2026, 10, 22, 9, 0, 0)
    )
    _seed_result(
        isolated_db, row_id=6, winner="가나종합건설", opened_at=datetime(2026, 10, 21, 9, 0, 0)
    )
    # 법인 표기 변형은 같은 업체로 묶고, 접미사가 붙은 다른 업체는 섞이지 않아야 합니다.
    _seed_result(
        isolated_db, row_id=7, winner="주식회사 한백", opened_at=datetime(2026, 10, 19, 9, 0, 0)
    )
    _seed_result(
        isolated_db, row_id=8, winner="(주)한백", opened_at=datetime(2026, 10, 18, 9, 0, 0)
    )
    _seed_result(
        isolated_db, row_id=9, winner="한백건설", opened_at=datetime(2026, 10, 17, 9, 0, 0)
    )
    isolated_db.commit()
    return isolated_db


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("주식회사 한백 최근 낙찰 내역 5건", "한백"),
        ("(주)대광기공 낙찰 결과 보여줘", "대광기공"),
        ("한백이 올해 낙찰받은 공고 목록 뽑아줘", "한백"),
        ("한백의 최근 30일 낙찰 건수 알려줘", "한백"),
        ("대성건설 낙찰 이력 알려줘", "대성건설"),
        ("㈜가나산업이 낙찰받은 공고 보여줘", "가나산업"),
    ],
)
def test_extract_winner_name_cases(query: str, expected: str):
    assert extract_winner_name(query) == expected


@pytest.mark.parametrize(
    "query",
    [
        "한국농어촌공사 낙찰 결과",
        "한국농어촌공사가 낙찰받은 공고 보여줘",
        "가장 많이 낙찰받은 업체는?",
        "업체별 낙찰 건수 알려줘",
        "최근 낙찰 결과 5건 보여줘",
        "건설 공사 낙찰 결과",
        "서울 낙찰 결과 5건 보여줘",
    ],
)
def test_extract_winner_name_skips_institution_field_and_ranking(query: str):
    """기관·분야어·순위 질의는 업체명으로 읽지 않습니다."""
    assert extract_winner_name(query) == ""


@pytest.mark.parametrize(
    "query",
    [
        "종합건설 공사 낙찰 결과 보여줘",
        "서울시 종합건설 낙찰 결과",
        "종합건설 낙찰 건수 알려줘",
    ],
)
def test_generic_industry_word_is_not_a_winner(query: str):
    """업종 접미사 앞부분이 일반 업종어뿐이면 업체명이 아닙니다."""
    assert extract_winner_name(query) == ""
    assert "winner_name" not in build_retrieval_plan(query).filters


def test_corporate_marker_makes_generic_stem_a_winner():
    """법인 표지가 붙으면 앞부분이 일반 업종어여도 업체로 봅니다."""
    plan = build_retrieval_plan("주식회사 종합건설 낙찰 결과 보여줘")

    assert plan.filters["winner_name"] == "종합건설"


def test_company_name_before_industry_suffix_is_a_winner():
    """고유명사가 앞에 남으면 업종 접미사가 붙어도 업체명입니다."""
    plan = build_retrieval_plan("주식회사 가나종합건설 낙찰 결과 보여줘")

    assert plan.filters["winner_name"] == "가나종합건설"


def test_plan_applies_winner_filter_to_result_queries():
    plan = build_retrieval_plan("한백이 올해 낙찰받은 공고 목록 뽑아줘")

    assert plan.filters["winner_name"] == "한백"
    assert plan.filters["result_limit"] == 5
    assert plan.use_sql is True


def test_plan_does_not_apply_winner_filter_to_announcement_lists():
    """아직 낙찰 전인 공고 목록에는 업체 조건을 걸지 않습니다."""
    plan = build_retrieval_plan("한백건설 공고 최근 5개 보여줘")

    assert "winner_name" not in plan.filters


def test_plan_keeps_winner_axis_untouched():
    """업체를 지목하지 않은 순위 질의는 업체 조건을 만들지 않습니다."""
    plan = build_retrieval_plan("가장 많이 낙찰받은 업체는?")

    assert plan.filters["group_by"] == "winner"
    assert "winner_name" not in plan.filters


def test_chat_path_query_keeps_winner_condition():
    """채팅 경로가 도구에 넘기는 질의도 같은 업체 조건으로 다시 계획됩니다."""
    execution_plan = interpret_request("한백이 올해 낙찰받은 공고 목록 뽑아줘")

    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters["limit"] == 5
    replanned = build_retrieval_plan(execution_plan.parameters["query"])
    assert replanned.filters["winner_name"] == "한백"


def test_result_list_returns_only_named_winner_rows(winner_db, fixed_today):
    plan = build_retrieval_plan("한백이 올해 낙찰받은 공고 목록 뽑아줘")
    summary = retrieve_structured_data(winner_db, plan)["summary"]
    recent = summary["recent_results"]

    assert {row["bidwinnr_nm"] for row in recent} == {"한백", "주식회사 한백", "(주)한백"}
    assert [row["bid_ntce_no"] for row in recent] == ["WIN-1", "WIN-2", "WIN-7", "WIN-8"]
    assert summary["total_bids"] == 4


def test_partial_name_does_not_broaden_to_similar_company(winner_db, fixed_today):
    """업체명 부분 일치는 "한백" 질의에 "한백건설" 행을 섞지 않습니다."""
    plan = build_retrieval_plan("한백이 올해 낙찰받은 공고 목록 뽑아줘")

    assert plan.filters["winner_name"] == "한백"
    recent = retrieve_structured_data(winner_db, plan)["summary"]["recent_results"]
    assert "한백건설" not in {row["bidwinnr_nm"] for row in recent}


def test_suffixed_winner_query_returns_only_that_company(winner_db, fixed_today):
    plan = build_retrieval_plan("한백건설이 올해 낙찰받은 공고 목록 뽑아줘")

    assert plan.filters["winner_name"] == "한백건설"
    recent = retrieve_structured_data(winner_db, plan)["summary"]["recent_results"]
    assert [row["bidwinnr_nm"] for row in recent] == ["한백건설"]


def test_result_count_does_not_count_other_winners(winner_db, fixed_today):
    plan = RetrievalPlan(
        use_sql=True,
        filters={"winner_name": "대광기공", "result_limit": 5},
    )
    summary = retrieve_structured_data(winner_db, plan)["summary"]

    assert [row["bidwinnr_nm"] for row in summary["recent_results"]] == ["대광기공", "대광기공"]
    assert summary["total_bids"] == 2


def test_unknown_winner_returns_empty_without_global_fallback(winner_db, fixed_today):
    """업체 조건이 걸린 0건은 전체 최신 목록으로 새지 않습니다."""
    plan = build_retrieval_plan("없는업체가 올해 낙찰받은 공고 목록 뽑아줘")

    assert plan.filters["winner_name"] == "없는업체"
    summary = retrieve_structured_data(winner_db, plan)["summary"]

    assert summary["recent_results"] == []
    assert summary["total_bids"] == 0


def test_result_without_winner_name_keeps_global_list(winner_db, fixed_today):
    """업체를 지목하지 않은 기존 질의는 전체 최신 목록을 그대로 냅니다."""
    plan = build_retrieval_plan("최근 낙찰 결과 5건 보여줘")

    assert "winner_name" not in plan.filters
    recent = retrieve_structured_data(winner_db, plan)["summary"]["recent_results"]

    assert len(recent) == 5
    assert len({row["bidwinnr_nm"] for row in recent}) > 1


def test_winner_condition_skips_ranking_snapshot():
    """특정 업체 조회는 전체 업체 순위 스냅샷을 쓰지 않습니다."""
    plan = RetrievalPlan(use_sql=True, filters={"winner_name": "한백"})

    assert _snapshot_scope(plan) is None
