"""채팅 계획기의 건수·순위 라우팅과 지난 N일 기간 해석 회귀 테스트.

건수 질문은 의미 검색이 아니라 통계 도구(bid_query_tool)로 가야 하고, 목록·
공고번호 단건·의미·범위 밖·예측 질문의 기존 도구 선택은 그대로여야 합니다.
"지난 14일" 같은 지난 N일·N주·N개월 표현은 최근 N일·N주·N개월과 같은 창으로
읽고, 지난주·지난달처럼 붙여 쓴 기존 표기의 결과는 바꾸지 않습니다.
기준일은 2026-10-25 로 고정합니다.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.app.services.planner_interpreter import interpret_request
from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan

_TODAY = date(2026, 10, 25)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _TODAY


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    """기간 해석이 실행 날짜에 흔들리지 않도록 기준일을 고정합니다."""
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


COUNT_QUERIES = [
    "이번 달 용역 낙찰이 총 몇 건이야?",
    "최근 한 달 동안 가장 많이 낙찰받은 업체는 몇 건이야?",
    "최근 한 달 동안 공사 쪽에서 낙찰 많이 한 업체 1위는 몇 건이야?",
    "이번 달 용역 공고 몇 건 올라왔어?",
    "지난달 물품 공고 몇 건이었어?",
    "최근 7일 동안 올라온 공고 총 몇 건이야?",
    "최근 2주 동안 용역 낙찰 몇 건이야?",
    "이번 달 외자 공고 몇 건이야?",
]


@pytest.mark.parametrize("query", COUNT_QUERIES)
def test_count_and_rank_questions_route_to_bid_query_tool(query):
    """건수·순위 질문은 의미 검색이 아니라 통계 도구 하나로 갑니다."""
    plan = interpret_request(query)

    assert plan.requested_capabilities[0] == "bid_query_tool"
    assert "semantic_search_tool" not in plan.requested_capabilities
    assert plan.parameters.get("query") == query


@pytest.mark.parametrize(
    ("query", "expected_capability"),
    [
        ("최근 용역 공고 5개만 리스트해줘", "bid_query_tool"),
        ("R26BK01778156 낙찰 결과 알려줘", "bid_query_tool"),
        ("낙찰률이 무슨 뜻이야?", "bid_query_tool"),
        ("R26BK01789522 예측해줘", "bid_prediction_tool"),
    ],
)
def test_existing_routes_keep_main_tool(query, expected_capability):
    """목록·단건·의미·예측 질문의 도구 선택은 기존과 같습니다."""
    plan = interpret_request(query)

    assert plan.requested_capabilities[0] == expected_capability


def test_list_count_question_keeps_announcement_limit():
    """목록 표지가 붙은 질문은 통계로 승격하지 않고 목록 개수를 유지합니다."""
    plan = interpret_request("최근 용역 공고 5개만 리스트해줘")

    assert plan.parameters.get("announcement_limit") == 5


def test_out_of_scope_question_stays_out_of_scope():
    """범위 밖 판정이 통계 분기보다 먼저 이기는 순서를 유지합니다."""
    plan = interpret_request("1 더하기 1은 뭐야?")

    assert plan.requested_capabilities == []
    assert plan.parameters.get("out_of_scope") is True


@pytest.mark.parametrize(
    ("query", "date_from", "date_to"),
    [
        ("지난 14일 기준으로 알려줘", "2026-10-12", "2026-10-25"),
        ("공사 낙찰 평균 낙찰률 지난 14일 기준으로 알려줘", "2026-10-12", "2026-10-25"),
        ("지난 2주 동안 용역 낙찰 몇 건이야?", "2026-10-12", "2026-10-25"),
        ("지난 3개월 공고", "2026-07-28", "2026-10-25"),
        ("지난 30일 공고", "2026-09-26", "2026-10-25"),
        ("지난 1달 공고", "2026-09-26", "2026-10-25"),
    ],
)
def test_past_n_periods_parse_as_windows(monkeypatch, query, date_from, date_to):
    """지난 N일·N주·N개월을 최근 N일·N주·N개월과 같은 창으로 읽습니다."""
    plan = build_retrieval_plan(query)

    assert plan.filters.get("date_from") == date_from
    assert plan.filters.get("date_to") == date_to


@pytest.mark.parametrize(
    "suffix",
    [
        "14일 용역 공고",
        "2주 용역 낙찰",
        "3개월 용역 공고",
    ],
)
def test_past_and_recent_windows_are_identical(suffix):
    """지난 N 표현과 최근 N 표현의 기간 조건이 같습니다."""
    past = build_retrieval_plan(f"지난 {suffix}")
    recent = build_retrieval_plan(f"최근 {suffix}")

    assert past.filters == recent.filters


def test_attached_past_week_has_no_window():
    """붙여 쓴 지난주는 기존처럼 기간을 만들지 않습니다."""
    plan = build_retrieval_plan("지난주 공고")

    assert plan.filters.get("date_from") is None
    assert plan.filters.get("date_to") is None


def test_attached_past_month_keeps_previous_month_window():
    """붙여 쓴 지난달은 기존처럼 직전 달 전체입니다."""
    plan = build_retrieval_plan("지난달 공고")

    assert plan.filters.get("date_from") == "2026-09-01"
    assert plan.filters.get("date_to") == "2026-09-30"
