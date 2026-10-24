"""
tests/test_request_verb_routing.py

"줄래", "줄 수 있어", "부탁해" 같은 요청 동사 변형이 낙찰 결과·공고 목록으로
가고, 설명형·통계·공고번호 질의를 목록으로 덮어쓰지 않는지 검증합니다.
"""

import pytest

from src.app.services.planner_interpreter import interpret_request
from src.rag.query_planning import (
    build_retrieval_plan,
    extract_result_limit,
    is_announcement_list_query,
    is_result_list_query,
)


@pytest.mark.parametrize(
    "query",
    [
        "최근 낙찰 결과 줄래요",
        "최근 낙찰 결과 줄 수 있어?",
        "최근 낙찰 결과 부탁해",
        "낙찰 결과 좀 보여줄 수 있어?",
    ],
)
def test_polite_request_verbs_route_to_result_list(query):
    assert is_result_list_query(query) is True

    plan = build_retrieval_plan(query)
    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters.get("result_limit") == extract_result_limit(query)


def test_polite_request_verb_routes_announcement_list():
    query = "용역 공고 목록 좀 줄래"

    assert is_announcement_list_query(query) is True
    assert is_result_list_query(query) is False

    plan = build_retrieval_plan(query)
    assert plan.filters.get("announcement_limit") == 5
    assert "result_limit" not in plan.filters


@pytest.mark.parametrize(
    "query",
    [
        "낙찰 결과 확인하는 방법 알려줘",
        "낙찰 결과가 왜 이런지 설명해줘",
        "낙찰 결과 통계 줄 수 있어?",
        "공고번호 R26BK01778156 줄 수 있어?",
        "낙찰률 계산식 부탁해",
    ],
)
def test_request_verb_does_not_override_explanation(query):
    assert is_result_list_query(query) is False
    assert is_announcement_list_query(query) is False


def test_request_verb_reaches_planner_bid_query_tool():
    execution_plan = interpret_request("최근 낙찰 결과 줄래요")

    assert execution_plan.query_type == "answer"
    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("limit") == 5
    assert "announcement_limit" not in execution_plan.parameters
