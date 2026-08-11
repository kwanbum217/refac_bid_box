"""
tests/test_chatbot_core.py

원본 apps/chatbot/tests.py 중 이식 가능한 핵심 검증을 FastAPI 환경으로 변환.
Django 템플릿 렌더링, 챗봇 API 통합 테스트는 React 프론트엔드 및 Arq 전환으로 제외.
 - CapabilityRegistryTests: 능력 레지스트리 키 무결성
 - HybridRAGRoutingTests: RAG 검색 라우팅 규칙
"""

import pytest

from src.app.services.capability_registry import CAPABILITY_REGISTRY
from src.app.services.tools import semantic_search_tool
from src.rag import engine as rag_engine
from src.rag.engine import build_retrieval_plan
from src.rag.schemas import DEFAULT_VECTOR_TOP_K, RetrievalPlan

EXPECTED_CAPABILITIES = {
    "preflight_check",
    "collect_refresh",
    "kb_refresh",
    "prediction_validate",
    "data_refresh",
    "full_validation",
    "kb_status_tool",
    "automation_status_tool",
    "bid_query_tool",
    "bid_prediction_tool",
    "semantic_search_tool",
    "trend_analyzer",
    "chart_builder",
}


def test_registry_contains_expected_capabilities():
    assert set(CAPABILITY_REGISTRY.keys()) == EXPECTED_CAPABILITIES


def test_pipeline_capabilities_carry_run_mode():
    for name in ("data_refresh", "full_validation", "collect_refresh"):
        cap = CAPABILITY_REGISTRY[name]
        assert cap.type == "pipeline"
        assert cap.run_mode, f"{name}에 run_mode가 없습니다"


def test_internal_tools_are_non_mutating():
    for name in (
        "kb_status_tool",
        "automation_status_tool",
        "bid_query_tool",
        "bid_prediction_tool",
        "semantic_search_tool",
        "trend_analyzer",
        "chart_builder",
    ):
        cap = CAPABILITY_REGISTRY[name]
        assert cap.type == "internal_tool"
        assert cap.mutating is False


def test_build_retrieval_plan_routes_statistics_query_to_sql():
    plan = build_retrieval_plan("최근 30일 서울 공고의 낙찰률 추세를 보여줘")
    assert plan.use_sql is True
    assert plan.use_kb_status is False
    assert plan.filters["institution_name"] == "서울"
    assert plan.filters["analysis_mode"] == "trend"
    assert plan.filters["date_from"]


def test_build_retrieval_plan_routes_result_list_query_to_sql():
    plan = build_retrieval_plan("최근 낙찰된 용역 사업 5개만 리스트 해봐라")
    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters["category"] == "Servc"
    assert plan.filters["result_limit"] == 5
    assert plan.filters["date_from"]


def test_build_retrieval_plan_routes_hybrid_query_to_sql_and_vector():
    plan = build_retrieval_plan("최근 한 달 낙찰률 추세와 위험 사례를 같이 알려줘")
    assert plan.use_sql is True
    assert plan.use_vector is True
    assert plan.time_bias == "recent"
    assert plan.semantic_query


def test_build_retrieval_plan_parses_explicit_korean_date_range():
    plan = build_retrieval_plan("2026년 4월 19일부터 2026년 4월 25일까지 서울 용역 낙찰률 추세")
    assert plan.filters["date_from"] == "2026-04-19"
    assert plan.filters["date_to"] == "2026-04-25"
    assert plan.filters["institution_name"] == "서울"
    assert plan.filters["category"] == "Servc"
    assert plan.filters["analysis_mode"] == "trend"


@pytest.mark.parametrize(
    ("query", "expected_from", "expected_to"),
    [
        ("2025년 물품 낙찰 평균 낙찰률 알려줘", "2025-01-01", "2025-12-31"),
        ("2025년 3월 낙찰률 알려줘", "2025-03-01", "2025-03-31"),
        ("2025년 1월부터 3월까지 물품 낙찰률", "2025-01-01", "2025-03-31"),
        # 해를 넘기는 구간. 뒤 연도를 앞 연도로 덮어쓰면 기간이 뒤집힙니다.
        ("2024년 11월부터 2025년 2월까지 낙찰률", "2024-11-01", "2025-02-28"),
        # 윤년 말일. 30일을 더하는 방식으로는 맞출 수 없습니다.
        ("2024년 2월 낙찰률", "2024-02-01", "2024-02-29"),
    ],
)
def test_build_retrieval_plan_parses_year_and_month_without_day(
    query, expected_from, expected_to
):
    """일자 없이 연/월만 말해도 기간 조건이 걸려야 한다.

    이 표현들이 파싱되지 않던 동안, 질의는 기간 조건 없이 전 기간을 집계하고도
    해당 연도를 답한 것처럼 응답했습니다. 느린 것보다 나쁜 침묵하는 오답입니다.
    """
    filters = build_retrieval_plan(query).filters
    assert filters["date_from"] == expected_from
    assert filters["date_to"] == expected_to


def test_build_retrieval_plan_keeps_full_date_range_over_year_month_rule():
    """완전한 날짜 쌍이 연월 규칙보다 우선해야 한다.

    연월 규칙이 먼저 걸리면 "2026년 4월 19일부터 25일까지" 가 4월 한 달로
    넓어집니다. 규칙 순서가 계약입니다.
    """
    filters = build_retrieval_plan("2026년 4월 19일부터 2026년 4월 25일까지 낙찰률").filters
    assert filters["date_from"] == "2026-04-19"
    assert filters["date_to"] == "2026-04-25"


def test_build_retrieval_plan_ignores_four_digit_numbers_without_year_marker():
    """네 자리 숫자만으로 연도를 추정하지 않는다.

    공고번호나 금액이 연도로 잡히면 엉뚱한 기간이 걸립니다.
    """
    filters = build_retrieval_plan("공고번호 2025 관련 낙찰 알려줘").filters
    assert "date_from" not in filters


def test_build_retrieval_plan_defaults_to_vector_when_no_keyword_matches():
    plan = build_retrieval_plan("안녕하세요")
    assert plan.use_vector is True
    assert plan.top_k == DEFAULT_VECTOR_TOP_K


def test_retrieval_plan_uses_the_shared_vector_top_k_default():
    assert RetrievalPlan().top_k == DEFAULT_VECTOR_TOP_K == 5


def test_semantic_search_tool_uses_the_shared_vector_top_k_default(monkeypatch):
    monkeypatch.setattr(semantic_search_tool, "retrieve_semantic_context", lambda plan: [])

    result = semantic_search_tool.execute(query="적격심사 사례")

    assert result["retrieval_plan"]["top_k"] == DEFAULT_VECTOR_TOP_K


def test_recent_detail_search_uses_the_shared_vector_top_k_default(monkeypatch):
    captured: list[RetrievalPlan] = []

    def retrieve(plan: RetrievalPlan):
        captured.append(plan)
        return []

    monkeypatch.setattr(rag_engine, "retrieve_semantic_context", retrieve)

    assert "찾지 못했습니다" in rag_engine.search_recent_details("적격심사 사례")
    assert captured[0].top_k == DEFAULT_VECTOR_TOP_K
