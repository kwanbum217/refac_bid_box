"""
tests/test_prediction_routing.py

공고번호가 붙은 낙찰가 예측 요청이 단건 조회나 모델 검증으로 새지 않고
낙찰가 예측 도구로 가는지 고정합니다.

- 예상 낙찰금액·낙찰 예상금액 같은 예측 가격 표지와 예측 동작 표지를 인정합니다.
- 공고번호가 있는 예측 요청은 단건 조회보다 우선합니다.
- 실제 낙찰 결과 조회와 모델 검증 요청은 기존 경로를 유지합니다.
"""

from __future__ import annotations

import pytest

from src.app.services.planner_interpreter import interpret_request
from src.rag.query_planning import build_retrieval_plan, is_bid_number_query

_BID_NO = "R26BK01789522"


@pytest.mark.parametrize(
    "query",
    [
        f"{_BID_NO} 공고 낙찰가 예측해줘",
        f"이번에 올라온 용역 공고 {_BID_NO} 투찰가 예측 부탁해",
        f"{_BID_NO} 건 예상 낙찰금액 얼마로 보여?",
        f"최근 공사 공고 {_BID_NO} 낙찰가 예측해줘",
        f"{_BID_NO} 예측 모델 돌려줘",
        f"이 공고 {_BID_NO} 낙찰가 예측해줘",
        f"{_BID_NO} 예측해줘",
        f"{_BID_NO} 얼마에 넣어야 해?",
    ],
)
def test_bid_number_prediction_routes_to_prediction_tool(query):
    """공고번호 예측 요청은 낙찰가 예측 도구로 갑니다."""
    plan = interpret_request(query)

    assert plan.requested_capabilities == ["bid_prediction_tool"]
    assert plan.parameters["query"] == query


@pytest.mark.parametrize(
    "query",
    [
        "예측 모델 검증해줘",
        "모델 성능 검증 결과 알려줘",
        f"{_BID_NO} 예측 모델 검증해줘",
    ],
)
def test_model_validation_stays_on_validation_pipeline(query):
    """모델 검증 표지가 있으면 예측 가격 요청보다 검증이 우선합니다."""
    assert interpret_request(query).requested_capabilities == ["prediction_validate"]


_MAIN_VALIDATION_QUERY_TYPE = "action"
_MAIN_VALIDATION_CAPABILITIES = ["prediction_validate"]


@pytest.mark.parametrize(
    "query",
    [
        "예측 검증해줘",
        "예측 결과 검증해",
        "예측해줘",
        "예측 실행해",
        "예측 모델 검증해줘",
    ],
)
def test_validation_requests_match_main_routing(query):
    """공고번호 없는 검증 요청은 main 과 같은 Action 경로를 유지합니다."""
    plan = interpret_request(query)

    assert plan.query_type == _MAIN_VALIDATION_QUERY_TYPE
    assert plan.requested_capabilities == _MAIN_VALIDATION_CAPABILITIES


@pytest.mark.parametrize(
    "query",
    [
        "R26BK01788818 건 낙찰금액 얼마야?",
        f"{_BID_NO} 공고 뭐야?",
        "R26BK01778156 낙찰 결과 알려줘",
    ],
)
def test_lookup_requests_stay_on_single_lookup(query):
    """실제 결과·공고 단건 조회는 예측으로 끌려가지 않습니다."""
    assert interpret_request(query).requested_capabilities == ["bid_query_tool"]


_MAIN_PRICE_QUERY_TYPE = "answer"
_MAIN_BID_QUERY_CAPABILITIES = ["bid_query_tool"]
_MAIN_PREDICTION_CAPABILITIES = ["bid_prediction_tool"]
_MAIN_SEMANTIC_CAPABILITIES = ["semantic_search_tool"]


@pytest.mark.parametrize(
    ("query", "capabilities"),
    [
        ("예상금액 통계 보여줘", _MAIN_BID_QUERY_CAPABILITIES),
        ("예상 낙찰금액 평균 알려줘", _MAIN_BID_QUERY_CAPABILITIES),
        ("낙찰 하한가 기준 알려줘", _MAIN_SEMANTIC_CAPABILITIES),
    ],
)
def test_price_keywords_without_bid_number_match_main(query, capabilities):
    """공고번호 없는 예상금액 계열 판정은 main 과 같습니다."""
    plan = interpret_request(query)

    assert plan.query_type == _MAIN_PRICE_QUERY_TYPE
    assert plan.requested_capabilities == capabilities


@pytest.mark.parametrize(
    ("query", "capabilities"),
    [
        (f"{_BID_NO} 예상금액 얼마야?", _MAIN_BID_QUERY_CAPABILITIES),
        (f"{_BID_NO} 낙찰 예상금액 얼마야?", _MAIN_PREDICTION_CAPABILITIES),
        (f"{_BID_NO} 사정률이 뭐야?", _MAIN_SEMANTIC_CAPABILITIES),
        (f"{_BID_NO} 공고 뭐야?", _MAIN_BID_QUERY_CAPABILITIES),
        (f"{_BID_NO} 낙찰 하한가 계산해줘", _MAIN_BID_QUERY_CAPABILITIES),
        (f"{_BID_NO} 추정가격 얼마야?", _MAIN_BID_QUERY_CAPABILITIES),
        (f"{_BID_NO} 기초금액 알려줘", _MAIN_BID_QUERY_CAPABILITIES),
    ],
)
def test_bid_number_price_vocabulary_routing(query, capabilities):
    """맨 예상금액·추정가격·기초금액은 조회, 낙찰 예측 표지는 예측 도구입니다."""
    plan = interpret_request(query)

    assert plan.query_type == _MAIN_PRICE_QUERY_TYPE
    assert plan.requested_capabilities == capabilities


def test_explanation_marker_after_bid_number():
    """조사 결합형 설명 표지는 단건 조회를 끄고, 공고 뭐야 는 단건 조회를 유지합니다."""
    assert is_bid_number_query(f"{_BID_NO} 사정률이 뭐야?") is False
    assert is_bid_number_query(f"{_BID_NO} 공고 뭐야?") is True


def test_public_announcement_question_is_single_lookup():
    """공고번호 단건 판정은 맨 뭐야 에 꺼지지 않습니다."""
    query = f"{_BID_NO} 공고 뭐야?"

    assert is_bid_number_query(query) is True
    plan = build_retrieval_plan(query)
    assert plan.filters.get("bid_ntce_no") == _BID_NO
    assert plan.use_sql is True
    assert plan.use_vector is False


def test_how_to_calculate_is_not_single_lookup():
    """계산 방법을 묻는 설명형은 단건 조회로 보내지 않습니다."""
    query = "R26BK01778156 낙찰률 계산 방법 알려줘"

    assert is_bid_number_query(query) is False
    assert "bid_ntce_no" not in build_retrieval_plan(query).filters
