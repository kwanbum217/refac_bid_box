"""정의·차이 질문의 제도·계약 용어가 기관명으로 새지 않는지 고정합니다.

q092 후속 조사에서 합성 정의 질문 108건 중 11건이 여전히 SQL 로 샜습니다.
원인은 기관 나열 추출이 정의 의도를 보지 않는 것과 비교 대상 절단이
"총액입찰" 안의 "입찰" 에서 잘리는 것이었습니다. 두 경로 모두
NON_INSTITUTION_SUFFIXES 를 공유하므로 접미사 사전 보강과 정의 의도 가드를
함께 적용했고, 실제 비교·통계 질문의 판정은 그대로 둡니다.
"""

import pytest

from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan

LEAK_QUERIES = [
    "제한경쟁입찰과 일반경쟁입찰의 차이가 뭐야",
    "지명경쟁과 수의계약의 차이가 뭐야",
    "지역제한과 공동도급의 차이가 뭐야",
    "입찰보증금과 계약보증금의 차이가 뭐야",
    "하자보수와 물가변동의 차이가 뭐야",
    "부정당업자와 지역제한의 차이가 뭐야",
    "공동도급과 지역제한의 차이가 뭐야",
    "간접노무비와 총액입찰의 차이가 뭐야",
    "간접노무비와 총액입찰 차이점 알려줘",
    "단가계약과 총액입찰의 차이가 뭐야",
    "단가계약과 총액입찰 차이점 알려줘",
]

INSTITUTION_COMPARISONS = [
    ("한국전력공사와 한국도로공사 낙찰 건수 비교해줘", ["한국전력공사", "한국도로공사"]),
    ("조달청과 국방부 공고 수 차이 알려줘", ["조달청", "국방부"]),
    ("한국수자원공사와 한국가스공사 최근 1년 낙찰 건수 비교", ["한국수자원공사", "한국가스공사"]),
    ("한국농어촌공사와 한국토지주택공사 공고 건수 차이", ["한국농어촌공사", "한국토지주택공사"]),
    ("조달청과 행정안전부 낙찰 건수 비교해줘", ["조달청", "행정안전부"]),
    ("한국전력공사와 조달청 공고 수 비교", ["한국전력공사", "조달청"]),
    ("한국전력공사와 한국도로공사 낙찰 건수가 뭐야", ["한국전력공사", "한국도로공사"]),
    ("조달청과 국방부 공고 수 차이가 뭐야", ["조달청", "국방부"]),
]

REGION_COMPARISONS = [
    ("서울과 부산 최근 30일 공고 건수 비교해줘", "region_scope_names", ["서울", "부산"]),
    ("부산이랑 대구 최근 30일 공고 건수 비교해줘", "region_scope_names", ["부산", "대구"]),
    ("경기도와 강원도 공고 건수 비교해줘", "region_names", ["경기", "강원"]),
    ("서울시와 경기도 낙찰 건수 차이 알려줘", "region_names", ["서울", "경기"]),
]

DIMENSION_COMPARISONS = [
    ("작년 대비 올해 용역 공고 건수 알려줘", "time"),
    ("용역 대비 공사 공고 건수 비교해줘", "category"),
]

UNLEARNED_TERMS = [
    "공동수급체",
    "직접생산",
    "우선구매",
    "혁신제품",
    "사회적기업",
    "장애인기업",
    "녹색제품",
    "소액수의",
    "분할발주",
    "유찰",
    "재공고",
    "전자공고",
]
UNLEARNED_PAIRS = [
    ("공동수급체", "직접생산"),
    ("우선구매", "혁신제품"),
    ("사회적기업", "장애인기업"),
    ("소액수의", "분할발주"),
    ("유찰", "재공고"),
    ("녹색제품", "전자공고"),
]


def _has_ending_consonant(word: str) -> bool:
    return "가" <= word[-1] <= "힣" and (ord(word[-1]) - 44032) % 28 != 0


def _unlearned_definition_queries() -> list[str]:
    queries = [
        f"{a}{'과' if _has_ending_consonant(a) else '와'} {b}{template}"
        for a, b in UNLEARNED_PAIRS
        for template in ("의 차이가 뭐야", " 차이점 알려줘")
    ]
    queries.extend(
        f"{term}{'이' if _has_ending_consonant(term) else '가'}{template}"
        for term in UNLEARNED_TERMS
        for template in (" 무엇인가요", " 뜻 알려줘", "은 어떻게 진행돼")
    )
    return queries


@pytest.mark.parametrize("query", LEAK_QUERIES)
def test_definition_questions_do_not_leak_institution_filters(query):
    """제도·계약 용어의 뜻·차이를 묻는 질의는 기관명 필터를 만들지 않습니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is False
    assert "institution_names" not in plan.filters
    assert "institution_name" not in plan.filters


@pytest.mark.parametrize("query", LEAK_QUERIES)
def test_definition_questions_skip_both_extractors(query):
    """정의 의도 가드가 비교 대상 추출과 기관 나열 추출을 모두 건너뜁니다."""
    assert query_planning._extract_comparison_targets(query) == ([], [])
    assert query_planning._extract_institution_list(query) == []


@pytest.mark.parametrize(("query", "institution_names"), INSTITUTION_COMPARISONS)
def test_institution_comparisons_keep_their_scope(query, institution_names):
    """실제 기관 비교 질의는 기관명 조건과 SQL 경로를 그대로 유지합니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.filters.get("institution_names") == institution_names


@pytest.mark.parametrize(("query", "filter_key", "region_names"), REGION_COMPARISONS)
def test_region_comparisons_keep_their_scope(query, filter_key, region_names):
    """지역 비교 질의는 지역 조건을 그대로 유지합니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.filters.get(filter_key) == region_names
    assert "institution_names" not in plan.filters


@pytest.mark.parametrize(("query", "dimension"), DIMENSION_COMPARISONS)
def test_dimension_comparisons_keep_their_dimension(query, dimension):
    """기간·분류 비교 질의는 기관 비교로 새지 않고 축을 유지합니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.route_reason == "정형 통계 질의"
    assert plan.filters.get("comparison_dimension") == dimension
    assert "institution_names" not in plan.filters


@pytest.mark.parametrize(
    "query",
    [
        "조달청과 국방부 공고 수 차이 알려줘",
        "조달청과 국방부 공고 수 차이가 뭐야",
    ],
)
def test_metric_difference_questions_keep_sql_comparison(query):
    """공고 수 차이 표현은 정의 질문이 아니라 실제 지표 비교입니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.filters.get("institution_names") == ["조달청", "국방부"]
    assert plan.filters.get("metric") == "announcement_count"


def test_definition_intent_guard_excludes_metric_and_list_queries():
    """가드는 정의 표지가 있어도 지표·목록 의도가 함께 있으면 성립하지 않습니다."""
    assert query_planning._is_definition_intent_query("적격심사가 무엇인가요") is True
    assert (
        query_planning._is_definition_intent_query("조달청과 국방부 공고 수 차이가 뭐야") is False
    )
    assert query_planning._is_definition_intent_query("한국전력공사 낙찰 건수가 뭐야") is False
    assert (
        query_planning._is_definition_intent_query("한국전력공사와 한국도로공사 낙찰 건수 비교")
        is False
    )


def test_non_institution_suffixes_cover_institution_and_contract_terms():
    """DB 의 기관명·업체명과 겹치지 않는 제도·계약 어미만 등록되어 있습니다."""
    expected = {
        "경쟁",
        "계약",
        "도급",
        "보증금",
        "노무비",
        "물가변동",
        "지역제한",
        "부정당업자",
        "하한율",
        "총액",
    }

    assert expected <= set(query_planning.NON_INSTITUTION_SUFFIXES)
    # "입찰"·"보수" 는 bid_results.bidwinnr_nm 에서 각각 업체명 3건과
    # 충돌하므로 접미사로 쓰지 않고 정의 의도 가드가 막습니다.
    assert "입찰" not in query_planning.NON_INSTITUTION_SUFFIXES
    assert "보수" not in query_planning.NON_INSTITUTION_SUFFIXES


@pytest.mark.parametrize("query", _unlearned_definition_queries())
def test_unlearned_vocabulary_definition_questions_do_not_leak(query):
    """접미사 사전에 없는 어휘도 정의 표지가 있으면 기관명으로 새지 않습니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is False
    assert "institution_names" not in plan.filters
    assert "institution_name" not in plan.filters
