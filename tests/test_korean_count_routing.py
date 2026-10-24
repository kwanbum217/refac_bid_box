"""
tests/test_korean_count_routing.py

한글 수사 개수(한~스무)가 목록 개수로 읽히는지, 수사 글자가 다른 낱말이나
다른 단위에 붙었을 때는 개수로 읽히지 않는지 검증합니다.
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
    ("query", "expected"),
    [
        ("최근 낙찰 결과 다섯 건 보여줘", 5),
        ("최근 낙찰 결과 세 개 알려줘", 3),
        ("낙찰 결과 열 개 보여줘", 10),
        ("공고 목록 두 건 보여줘", 2),
        ("최근 낙찰 결과 스무 개 보여줘", 20),
        ("최근 낙찰 결과 열한 건 보여줘", 11),
    ],
)
def test_korean_numeral_limit_maps_to_number(query, expected):
    assert extract_result_limit(query) == expected
    assert extract_result_limit(query, default=7) == expected


@pytest.mark.parametrize(
    "query",
    [
        "최근 낙찰 결과 다섯 건 보여줘",
        "최근 낙찰 결과 세 개 알려줘",
        "낙찰 결과 열 개 보여줘",
        "최근 낙찰 결과 스무 개 보여줘",
    ],
)
def test_korean_numeral_marks_result_list(query):
    assert is_result_list_query(query) is True

    plan = build_retrieval_plan(query)
    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters.get("result_limit") == extract_result_limit(query)


def test_korean_numeral_marks_announcement_list():
    query = "공고 목록 두 건 보여줘"

    assert is_announcement_list_query(query) is True
    plan = build_retrieval_plan(query)
    assert plan.filters.get("announcement_limit") == 2
    assert "result_limit" not in plan.filters


@pytest.mark.parametrize(
    "query",
    [
        "최근 한 달 낙찰 결과 보여줘",
        "한국전력공사 낙찰 결과 보여줘",
        "낙찰 결과 몇 개야?",
        "다섯 개 분야별 낙찰률 알려줘",
        "세부 공고 목록 보여줘",
        "열린 공고 목록 보여줘",
    ],
)
def test_korean_numeral_excludes_month_unit(query):
    assert is_result_list_query(query) is False


@pytest.mark.parametrize(
    "query",
    [
        "최근 한 달 낙찰 결과 보여줘",
        "한국전력공사 낙찰 결과 보여줘",
        "낙찰 결과 몇 개야?",
        "세부 공고 목록 보여줘",
        "열린 공고 목록 보여줘",
    ],
)
def test_numeral_letters_outside_count_unit_do_not_set_limit(query):
    assert extract_result_limit(query, default=7) == 7


def test_korean_numeral_limit_reaches_planner_bid_query_tool():
    execution_plan = interpret_request("최근 낙찰 결과 다섯 건 보여줘")

    assert execution_plan.query_type == "answer"
    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("limit") == 5
    assert "announcement_limit" not in execution_plan.parameters
