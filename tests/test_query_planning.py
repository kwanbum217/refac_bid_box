"""
tests/test_query_planning.py

하이브리드 RAG 쿼리 플래너 및 개체 조회/통계 라우팅 회귀 테스트.
- 개체 지정 질의(entity-specific lookup)의 독립 벡터/SQL 활성화 검증
- 순수 집계 질의(pure aggregation)의 SQL 전용 라우팅 유지 검증
- 결과 목록 질의의 result_limit 추출 및 회귀 검증
- data/eval/llm_quality_fixture_v1.json 기반 q03/q07 질문 실측 회귀 검증
"""

import json
from pathlib import Path

import pytest

from src.rag.query_planning import (
    build_retrieval_plan,
    extract_result_limit,
    is_entity_specific_query,
    is_result_list_query,
)


def _load_fixture_data() -> dict:
    fixture_path = Path("data/eval/llm_quality_fixture_v1.json")
    with open(fixture_path, encoding="utf-8") as f:
        return json.load(f)


def _get_fixture_question(item_id: str) -> str:
    data = _load_fixture_data()
    for item in data.get("items", []):
        if item.get("id") == item_id:
            return item["question"]
    raise KeyError(f"Fixture item {item_id} not found in llm_quality_fixture_v1.json")


def test_independent_routing_both_sql_and_vector_can_be_true():
    """use_sql 과 use_vector 가 상호 배타가 아니라 독립적으로 동시에 True 가 될 수 있어야 합니다."""
    plan = build_retrieval_plan(
        "대구불로초등학교 급식시설 개선공사의 낙찰업체와 낙찰금액 및 낙찰률을 알려줘"
    )
    assert plan.use_sql is True
    assert plan.use_vector is True
    assert "개체 지정 질의" in plan.route_reason


def test_entity_specific_mixed_with_statistics_keywords_keeps_vector_enabled():
    """개체 지정 신호와 통계 키워드(낙찰률, 통계, 평균)가 혼합되어도 벡터 검색이 꺼지지 않아야 합니다."""
    query = "봉화 공설운동장 리모델링 사업 건축공사 감리 용역의 공고번호, 수요기관, 낙찰업체 및 낙찰금액을 알려줘"
    plan = build_retrieval_plan(query)

    assert is_entity_specific_query(query) is True
    assert plan.use_vector is True
    assert plan.use_sql is True
    assert "개체 지정 질의" in plan.route_reason


def test_pure_aggregation_queries_maintain_sql_centric_routing():
    """순수 집계 질의(기간/통계 표현이 있고 개체 지목이 없음)는 종전대로 SQL 중심으로 유지되어야 합니다."""
    pure_queries = [
        "최근 7일 서울 공사의 낙찰률 추세를 알려줘",
        "최근 1년 낙찰률 추세를 보여줘",
        "최근 1년 입찰 통계를 보여줘",
        "낙찰률 추세 비교해줘",
        "서울 지역 용역 공고 흐름 알려줘",
        "2025년 1월부터 3월까지 물품 공고 건수와 평균 낙찰률 알려줘",
        "최근 한 달 동안 공사 분야 평균 낙찰률과 경쟁률 집계해줘",
    ]
    for q in pure_queries:
        assert not is_entity_specific_query(q), f"순수 집계 질의가 개체 질의로 오인되었습니다: {q}"
        plan = build_retrieval_plan(q)
        assert plan.use_sql is True, f"use_sql 이 False 입니다: {q}"
        assert plan.use_vector is False, f"use_vector 가 True 로 켜졌습니다: {q}"
        assert "정형 통계 질의" in plan.route_reason


def test_result_list_query_and_limit_extraction():
    """결과 목록 질의의 판정 및 result_limit 추출 동작이 회귀하지 않아야 합니다."""
    query_5 = "최근 낙찰된 용역 사업 5개만 리스트 해봐라"
    assert is_result_list_query(query_5) is True
    assert extract_result_limit(query_5) == 5

    plan_5 = build_retrieval_plan(query_5)
    assert plan_5.use_sql is True
    assert plan_5.use_vector is False
    assert plan_5.filters.get("result_limit") == 5
    assert "낙찰 결과 목록 질의" in plan_5.route_reason

    query_10 = "최근 낙찰 결과 10건 뽑아줘"
    assert is_result_list_query(query_10) is True
    assert extract_result_limit(query_10) == 10

    plan_10 = build_retrieval_plan(query_10)
    assert plan_10.filters.get("result_limit") == 10


def test_fixture_q03_question_enables_vector_search():
    """fixture q03 질문 문자열을 fixture 파일에서 직접 읽어 use_vector 가 True 임을 검증합니다."""
    q03_text = _get_fixture_question("q03")
    assert (
        q03_text
        == "대구불로초등학교 급식시설 환경개선 및 기타 전기공사 재해예방기술지도 용역의 낙찰업체와 낙찰금액 및 낙찰률을 알려줘"
    )

    plan = build_retrieval_plan(q03_text)
    assert plan.use_vector is True
    assert plan.use_sql is True
    assert "개체 지정 질의" in plan.route_reason


def test_fixture_q07_question_enables_vector_search():
    """fixture q07 질문 문자열을 fixture 파일에서 직접 읽어 use_vector 가 True 임을 검증합니다."""
    q07_text = _get_fixture_question("q07")
    assert (
        q07_text
        == "인천공항 T2 단기 주차타워 건립 사전 타당성조사 용역의 수요기관, 낙찰업체 및 낙찰률을 알려줘"
    )

    plan = build_retrieval_plan(q07_text)
    assert plan.use_vector is True
    assert plan.use_sql is True
    assert "개체 지정 질의" in plan.route_reason


def test_all_context_sufficient_fixture_questions_enable_vector_search():
    """정본 fixture 의 모든 context_sufficient 질의(q01~q16)에서 use_vector 가 True 여야 합니다."""
    data = _load_fixture_data()
    for item in data.get("items", []):
        if item.get("context_sufficient"):
            item_id = item["id"]
            question = item["question"]
            plan = build_retrieval_plan(question)
            assert plan.use_vector is True, (
                f"[{item_id}] context_sufficient 질의에서 use_vector 가 꺼졌습니다: {question}"
            )


@pytest.mark.parametrize(
    "query",
    [
        "'2026년 봉화 도로포장' 공사의 낙찰자 알려줘",
        "공고번호 R26BK01659912-001 낙찰 정보 확인해줘",
        "bid_10015925 건의 낙찰금액이 얼마인가요?",
        "연세대학교 미래캠퍼스 장비 구매의 낙찰업체 알려줘",
        "충북대학교병원 개선공사의 수요기관과 낙찰업체",
        "주식회사 진성의 낙찰 내역",
    ],
)
def test_various_entity_specific_signals(query):
    """다양한 개체 지정 신호(인용구, 공고번호, 기관/학교, 업체명)가 정상 감지되어야 합니다."""
    assert is_entity_specific_query(query) is True
    plan = build_retrieval_plan(query)
    assert plan.use_vector is True
    assert plan.use_sql is True


def test_unclassified_general_queries_default_to_vector():
    """특정 통계/문맥/개체 키워드가 없는 일반/모호한 질의는 기본 벡터 질의로 처리합니다."""
    plan = build_retrieval_plan("안내 부탁드립니다")
    assert plan.use_sql is False
    assert plan.use_vector is True
    assert "문맥/의미 질의" in plan.route_reason
