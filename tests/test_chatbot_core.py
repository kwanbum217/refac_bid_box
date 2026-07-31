"""
tests/test_chatbot_core.py

원본 apps/chatbot/tests.py 중 이식 가능한 핵심 검증을 FastAPI 환경으로 변환.
Django 템플릿 렌더링, 챗봇 API 통합 테스트는 React 프론트엔드 및 Arq 전환으로 제외.
 - CapabilityRegistryTests: 능력 레지스트리 키 무결성
 - HybridRAGRoutingTests: RAG 검색 라우팅 규칙
"""

from src.app.services.capability_registry import CAPABILITY_REGISTRY
from src.rag.engine import build_retrieval_plan


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


def test_build_retrieval_plan_defaults_to_vector_when_no_keyword_matches():
    plan = build_retrieval_plan("안녕하세요")
    assert plan.use_vector is True
