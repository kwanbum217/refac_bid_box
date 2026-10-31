"""정의·차이 질문에서 제도명·계약방식이 기관명으로 오추출되지 않는지 고정합니다.

q092 "적격심사와 최저가낙찰제의 차이가 무엇인가요" 는 제도명(적격심사)과
계약방식(최저가낙찰제)을 기관명으로 뽑아 SQL 비교 질의로 승격됐습니다.
비교 대상 추출과 기관 나열 추출이 NON_INSTITUTION_SUFFIXES 를 함께 쓰므로
접미사 사전 한 곳에서 두 오염 경로를 동시에 막습니다.
"""

import pytest

from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan

Q092 = "적격심사와 최저가낙찰제의 차이가 무엇인가요"


def test_non_institution_suffixes_include_institution_and_contract_terms():
    """제도명·계약방식 접미사 네 개가 배제 사전에 등록되어 있습니다."""
    expected = {"낙찰제", "심사", "계약방식", "입찰방식"}

    assert expected <= set(query_planning.NON_INSTITUTION_SUFFIXES)


def test_q092_definition_question_no_longer_routes_to_sql_comparison():
    """q092 는 기관 필터 없이 기본 벡터 질의로 처리됩니다."""
    plan = build_retrieval_plan(Q092)

    assert plan.use_sql is False
    assert plan.use_vector is True
    assert plan.route_reason == "기본 벡터 질의"
    assert "institution_names" not in plan.filters
    assert "institution_name" not in plan.filters


def test_q092_both_extractors_stop_returning_institution_candidates():
    """비교 대상 추출과 기관 나열 추출이 모두 후보를 비웁니다."""
    assert query_planning._extract_comparison_targets(Q092) == ([], [])
    assert query_planning._extract_institution_list(Q092) == []


@pytest.mark.parametrize(
    ("query", "institution_name"),
    [
        ("한국농어촌공사 공고 최근 거 5개만 뽑아줘", "한국농어촌공사"),
        ("조달청 용역 공고 3건 뽑아줘", "조달청"),
        ("서울특별시 중구의 최근 60일 용역 평균 낙찰률 얼마야?", "서울특별시 중구"),
        ("공주시 최근 공고 5개만 리스트로 보여줘", "공주시"),
        ("서울특별시 용역 공고 알려줘", "서울"),
    ],
)
def test_real_institution_scope_is_preserved(query, institution_name):
    """실제 기관명은 접미사 추가 뒤에도 그대로 기관 범위로 남습니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.filters.get("institution_name") == institution_name


def test_time_comparison_keeps_its_dimension():
    """기간 비교는 기관 비교로 새지 않고 시간 축을 유지합니다."""
    plan = build_retrieval_plan("작년 대비 올해 용역 공고 건수 알려줘")

    assert plan.use_sql is True
    assert plan.route_reason == "정형 통계 질의"
    assert plan.filters.get("comparison_dimension") == "time"
    assert plan.filters.get("metric") == "announcement_count"
    assert "institution_names" not in plan.filters


def test_region_comparison_keeps_its_region_scope():
    """지역 비교는 기관 비교로 새지 않고 지역 합집합 조건을 유지합니다."""
    plan = build_retrieval_plan("부산이랑 대구 최근 30일 공고 건수 비교해줘")

    assert plan.use_sql is True
    assert plan.route_reason == "정형 통계 질의"
    assert plan.filters.get("region_scope_names") == ["부산", "대구"]
    assert "institution_names" not in plan.filters
