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
    is_result_query,
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


def test_coordinator_counterexamples_pure_aggregation():
    """코디네이터 지적 반례: 속성어(낙찰금액) 혼합이나 단순 카테고리 괄호가 개체로 오분류되지 않아야 합니다."""
    q1 = "최근 3개월 평균 낙찰금액 추세를 알려줘"
    assert not is_entity_specific_query(q1)
    plan1 = build_retrieval_plan(q1)
    assert plan1.use_sql is True
    assert plan1.use_vector is False
    assert plan1.route_reason == "정형 통계 질의"

    q2 = "평균 낙찰률(용역) 추세"
    assert not is_entity_specific_query(q2)
    plan2 = build_retrieval_plan(q2)
    assert plan2.use_sql is True
    assert plan2.use_vector is False
    assert plan2.route_reason == "정형 통계 질의"


def test_unclassified_general_queries_default_to_vector():
    """특정 통계/문맥/개체 키워드가 없는 일반/모호한 질의는 기본 벡터 질의로 처리합니다."""
    plan = build_retrieval_plan("안내 부탁드립니다")
    assert plan.use_sql is False
    assert plan.use_vector is True
    assert "기본 벡터 질의" in plan.route_reason


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("봉화 공설운동장 리모델링 사업 감리 용역의 낙찰업체와 낙찰금액을 알려줘", True),
        ("안녕 자두야 포스트프로덕션 용역의 최종 낙찰금액 및 낙찰률", True),
        ("대구불로초등학교 급식시설 개선공사의 낙찰업체", True),
        ("도로포장 공사의 낙찰자 알려줘", True),
        ("공고번호 R26BK01659912-001 낙찰 정보 확인해줘", True),
        ("bid_10015925 건의 낙찰금액이 얼마인가요?", True),
        ("최근 낙찰된 용역 사업 목록", True),
        ("주식회사 진성의 낙찰 내역", True),
        ("서울 지역 공사 공고 목록", False),
        ("충북대학교병원 개선공사의 수요기관과 입찰 참가 조건", False),
        ("2026년 봉화 도로포장 공사의 공고번호와 수요기관", False),
        ("적격심사 세부기준 안내", False),
        ("안내 부탁드립니다", False),
    ],
)
def test_is_result_query_detection(query: str, expected: bool):
    """낙찰 결과를 묻는 질의와 단순 공고/기준 질의를 정확히 변별해야 합니다."""
    assert is_result_query(query) is expected


def test_category_keyword_last_occurrence_precedence_with_fixture():
    """복합 카테고리 수식어(예: 공사 감리 용역)에서 마지막에 등장하는 핵어가 카테고리로 판정되어야 합니다."""
    # q01: "봉화 공설운동장 리모델링 사업 건축공사 감리 용역..." -> 용역 (Servc)
    q01_text = _get_fixture_question("q01")
    plan_q01 = build_retrieval_plan(q01_text)
    assert plan_q01.filters.get("category") == "Servc"

    # q02: "애니메이션 극장판 ... 포스트프로덕션 용역..." -> 용역 (Servc)
    q02_text = _get_fixture_question("q02")
    plan_q02 = build_retrieval_plan(q02_text)
    assert plan_q02.filters.get("category") == "Servc"

    # q03: "대구불로초등학교 급식시설 환경개선 및 기타 전기공사 재해예방기술지도 용역..." -> 용역 (Servc)
    q03_text = _get_fixture_question("q03")
    plan_q03 = build_retrieval_plan(q03_text)
    assert plan_q03.filters.get("category") == "Servc"

    # q08: "2026년 금정산성 남문계단 및 문루 보수정비공사..." -> 공사 (Cnstwk)
    q08_text = _get_fixture_question("q08")
    plan_q08 = build_retrieval_plan(q08_text)
    assert plan_q08.filters.get("category") == "Cnstwk"

    # q09: "갈산고등학교 기숙사 수선 기계설비공사..." -> 공사 (Cnstwk)
    q09_text = _get_fixture_question("q09")
    plan_q09 = build_retrieval_plan(q09_text)
    assert plan_q09.filters.get("category") == "Cnstwk"

    # q14: "2026년 김량장 브랜드 홍보물품 제작..." -> 물품 (Thng)
    q14_text = _get_fixture_question("q14")
    plan_q14 = build_retrieval_plan(q14_text)
    assert plan_q14.filters.get("category") == "Thng"

    # 카테고리 키워드가 없는 질의는 category 필터가 생성되지 않아야 함
    plan_none = build_retrieval_plan("안내 부탁드립니다")
    assert "category" not in plan_none.filters


def test_entity_query_does_not_promote_implicit_year_month_to_filter():
    """공고명에 든 사업연도·대상월이 게시 기간 필터로 승격되면 안 됩니다.

    2026-08-27 blind fixture 측정에서 "2026년 9월분 학교급식물품" 질의가
    date_from=2026-09-01 필터를 얻어 검색 결과가 0건이 됐습니다. 실제 공고는
    2026-08-13 게시분이었습니다.
    docs/analysis/retrieval_miss_investigation_20260827.md
    """
    plan_month = build_retrieval_plan(
        "2026년 9월분 충주중앙탑초 외4개교 학교급식물품(부식) 공동구매 입찰 공고의 "
        "공고번호, 수요기관, 낙찰업체 및 최종 낙찰금액과 낙찰률을 알려줘"
    )
    assert "date_from" not in plan_month.filters
    assert "date_to" not in plan_month.filters
    # 카테고리 판정과 최신성 힌트는 유지되어야 합니다.
    assert plan_month.filters.get("category") == "Thng"
    assert plan_month.time_bias == "recent"

    plan_year = build_retrieval_plan(
        "(긴급)2025년 조사료 경영체 기계장비 지원사업(굴착기) 구매의 "
        "공고번호, 수요기관, 낙찰업체 및 최종 낙찰금액과 낙찰률을 알려줘"
    )
    assert "date_from" not in plan_year.filters
    assert "date_to" not in plan_year.filters


def test_explicit_period_still_becomes_filter_even_for_entity_query():
    """명시적 기간 한정 표현은 개체 질의에서도 그대로 필터가 되어야 합니다."""
    plan = build_retrieval_plan(
        "2025년 1월부터 3월까지 주식회사 백화가 낙찰받은 공고의 낙찰금액 알려줘"
    )
    assert plan.filters.get("date_from") == "2025-01-01"
    assert plan.filters.get("date_to") == "2025-03-31"


def test_non_entity_statistics_query_keeps_year_filter():
    """개체를 지목하지 않은 통계 질의의 연도는 기간 필터로 유지되어야 합니다."""
    plan = build_retrieval_plan("2025년 용역 낙찰률 평균 통계 알려줘")
    assert plan.filters.get("date_from") == "2025-01-01"
    assert plan.filters.get("date_to") == "2025-12-31"
