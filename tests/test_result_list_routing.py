"""
tests/test_result_list_routing.py

개수·목록 표현이 없는 낙찰 결과 요청과 추이 질의의 라우팅을 검증합니다.
"""

import pytest

from src.app.services.planner_interpreter import interpret_request
from src.rag.query_planning import build_retrieval_plan, is_result_list_query


@pytest.mark.parametrize(
    "query",
    [
        "최근 낙찰 결과 보여줘",
        "최근 물품 낙찰 10개 리스트해줘",
        "최근 30일 동안 낙찰된 공고 좀 보여줄래?",
        "요즘 낙찰된 공고 좀 보여줄래?",
        "2026년 3분기 낙찰 결과 알려줘",
        "최근 낙찰 결과 5개만 보여줘",
        "최근 용역 낙찰 결과 5건 알려줘",
        "최근 낙찰 공고 5개 보여줘",
        "용역 낙찰된 공고 5개 리스트해줘",
        "지난달 낙찰 결과 5개 보여줘",
        "이번주 낙찰 결과 알려줘",
        "용역 낙찰 결과 보여줘",
    ],
)
def test_result_list_query_matches_result_request(query):
    assert is_result_list_query(query) is True


@pytest.mark.parametrize(
    "query",
    [
        "분류별 평균 낙찰률 알려줘",
        "용역 평균 낙찰률은 얼마야?",
        "기관별 평균 낙찰률 알려줘",
        "낙찰 많이 받은 업체 top 5 순위 알려줘",
        "공고번호 R26BK01778156 낙찰 결과 알려줘",
        "R26BK01778156 낙찰률 높은 편이야?",
        "월별 공고 건수 추이 알려줘",
        "낙찰 결과 확인하는 방법 알려줘",
        "최근 용역 공고 5개만 리스트해줘",
        "도화엔지니어링 낙찰 결과 알려줘",
        "한국종합기술 낙찰 결과 보여줘",
        "건화 낙찰된 공고 보여줘",
    ],
)
def test_result_list_query_excludes_statistics_bid_number_and_explanation(query):
    assert is_result_list_query(query) is False


@pytest.mark.parametrize(
    "query",
    [
        "최근 낙찰 결과 보여줘",
        "2026년 3분기 낙찰 결과 알려줘",
    ],
)
def test_planner_routes_result_list_request_to_bid_query_tool(query):
    execution_plan = interpret_request(query)

    assert execution_plan.query_type == "answer"
    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("limit") == 5
    assert "announcement_limit" not in execution_plan.parameters


def test_monthly_query_is_routed_to_trend_analysis_mode():
    plan = build_retrieval_plan("월별 공고 건수 추이 알려줘")

    assert plan.filters.get("analysis_mode") == "trend"
    assert "result_limit" not in plan.filters
