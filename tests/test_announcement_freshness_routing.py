"""
tests/test_announcement_freshness_routing.py

목록 표지 없이 요청 동사와 신선도 표지(올라온·등록된·게시된·신규·최신)만 있는
최신 공고 요청이 정형 조회 목록으로 가고, 설명형·필드 조회·통계 질의는
목록으로 새지 않는지 검증합니다.
"""

import pytest

from src.app.services.planner_interpreter import interpret_request
from src.rag.query_planning import (
    build_retrieval_plan,
    is_announcement_list_query,
    is_result_list_query,
)


@pytest.mark.parametrize(
    "query",
    [
        "오늘 올라온 용역 공고 알려줘",
        "최신 공사 공고 보여줘",
        "오늘 등록된 물품 공고 알려줘",
        "이번 주 신규 용역 공고 알려줘",
    ],
)
def test_today_announcement_without_list_marker_routes_to_sql(query):
    assert is_announcement_list_query(query) is True
    assert is_result_list_query(query) is False

    plan = build_retrieval_plan(query)
    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters.get("announcement_limit") == 5
    assert "result_limit" not in plan.filters


def test_list_marker_alone_routes_to_announcement_list():
    query = "용역 공고 목록 좀"

    assert is_announcement_list_query(query) is True
    assert is_result_list_query(query) is False

    plan = build_retrieval_plan(query)
    assert plan.filters.get("announcement_limit") == 5
    assert plan.filters.get("category") == "Servc"
    assert "result_limit" not in plan.filters


@pytest.mark.parametrize(
    "query",
    [
        "공고번호 R26BK01778156 알려줘",
        "공고명 R26BK01778156 알려줘",
    ],
)
def test_bid_number_field_lookup_is_not_announcement_list(query):
    assert is_announcement_list_query(query) is False
    assert is_result_list_query(query) is False
    assert build_retrieval_plan(query).filters == {}


@pytest.mark.parametrize(
    "query",
    [
        "최신 공고 번호 알려줘",
        "최신 공고 번호 줄래요",
        "오늘 올라온 공고 명 알려줘",
    ],
)
def test_spaced_bid_number_field_lookup_is_not_announcement_list(query):
    assert is_announcement_list_query(query) is False
    assert is_result_list_query(query) is False
    assert "announcement_limit" not in build_retrieval_plan(query).filters


@pytest.mark.parametrize(
    "query",
    [
        "공고번호 R26BK01778156 알려줘",
        "공고 목록 작성 방법 알려줘",
        "공고 알림 설정하고 싶어",
        "용역 공고 낙찰률 평균 알려줘",
        "전체 공고 건수 알려줘",
        "공고 알려줘",
    ],
)
def test_freshness_route_excludes_explanation_field_and_statistics(query):
    assert is_announcement_list_query(query) is False


@pytest.mark.parametrize(
    "query",
    [
        "최신 공고 평균 알려줘",
        "최신 공고 건수 알려줘",
        "올라온 공고 건수 알려줘",
        "최신 공고 추이 알려줘",
        "최신 공고 비교 보여줘",
        "신규 공고 통계 보여줘",
    ],
)
def test_freshness_route_does_not_override_statistics(query):
    assert is_announcement_list_query(query) is False


@pytest.mark.parametrize(
    "query",
    [
        "오늘 올라온 용역 공고 알려줘",
        "용역 공고 목록 좀",
        "최신 공사 공고 보여줘",
        "오늘 등록된 물품 공고 알려줘",
        "이번 주 신규 용역 공고 알려줘",
        "공고 목록 두 건 보여줘",
    ],
)
def test_freshness_route_keeps_list_cases(query):
    assert is_announcement_list_query(query) is True


def test_freshness_request_reaches_planner_bid_query_tool():
    execution_plan = interpret_request("오늘 올라온 용역 공고 알려줘")

    assert execution_plan.query_type == "answer"
    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("announcement_limit") == 5
    assert "limit" not in execution_plan.parameters
