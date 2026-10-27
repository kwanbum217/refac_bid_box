"""
tests/test_query_lexicon_reexport.py

질의 표현 상수를 src/rag/query_lexicon.py 로 분리한 뒤에도 기존 import 경로
(src.rag.query_planning)에서 같은 객체를 그대로 가져갈 수 있는지 검증합니다.
"""

from __future__ import annotations

import inspect

import pytest

from src.rag import query_lexicon, query_planning

# 옮기기 전 query_planning.py 첫 함수(_strip_institution_particle) 앞에 있던
# 대문자 할당 이름 63개입니다.
CONSTANT_NAMES = (
    "STATISTICS_KEYWORDS",
    "COUNT_QUERY_PATTERN",
    "COUNT_QUERY_DOMAIN_MARKERS",
    "STATS_SINGLE_METRIC_RATE_TERMS",
    "LIST_REQUEST_MARKERS",
    "SEMANTIC_KEYWORDS",
    "KB_KEYWORDS",
    "CATEGORY_KEYWORDS",
    "CONSTRUCTION_CATEGORY_PATTERN",
    "PUBLIC_CORPORATION_PREFIXES",
    "PUBLIC_CORPORATION_STEMS",
    "PUBLIC_CORP_JOSA",
    "REGION_KEYWORDS",
    "REGION_ALIASES",
    "OFFICIAL_PROVINCE_NAMES",
    "OFFICIAL_BROAD_REGION_NAMES",
    "TREND_KEYWORDS",
    "TREND_LIST_MARKERS",
    "TREND_TITLE_FOLLOWER_PATTERN",
    "AGGREGATE_AXIS_MARKERS",
    "WINNER_AXIS_PATTERN",
    "STATS_SINGLE_METRIC_EXCLUDED_MARKERS",
    "AGGREGATE_RATE_MARKERS",
    "AGGREGATE_BID_MARKERS",
    "AGGREGATE_AWARD_AMOUNT_MARKERS",
    "AGGREGATE_ANNOUNCEMENT_MARKERS",
    "AXIS_RANKING_MARKERS",
    "DEFAULT_GROUP_LIMIT",
    "MAX_GROUP_LIMIT",
    "RESULT_QUERY_MARKERS",
    "RESULT_LIST_MARKERS",
    "KOREAN_NUMERALS",
    "KOREAN_NUMERAL_FRAGMENT",
    "COUNT_UNIT_BOUNDARY_PATTERN",
    "COUNT_PATTERN_FRAGMENT",
    "COUNT_PATTERN",
    "GROUP_FIRST_PATTERN",
    "GROUP_TOP_PATTERN",
    "GROUP_RANK_COUNT_PATTERN",
    "GROUP_SINGLE_TOP_MARKERS",
    "RESULT_LIST_REQUEST_VERB_PATTERN",
    "RESULT_LIST_VOCABULARY_WORDS",
    "RESULT_LIST_VOCABULARY_PATTERNS",
    "RESULT_LIST_TOKEN_SUFFIXES",
    "RESULT_LIST_TOKEN_SPLIT_PATTERN",
    "RESULT_LIST_SPACED_PERIOD_REPLACEMENTS",
    "RESULT_LIST_EXCLUDED_MARKERS",
    "RESULT_LIST_EXCLUDED_PATTERN",
    "RESULT_LIST_EXPLANATION_MARKERS",
    "RESULT_LIST_BID_NUMBER_PATTERN",
    "BID_NTCE_NO_PATTERN",
    "BID_NTCE_NO_EXPLANATION_MARKERS",
    "ENTITY_ORG_SUFFIXES",
    "ADMIN_REGION_PATTERN",
    "ADMIN_DISTRICT_PATTERN",
    "OFFICIAL_DISTRICT_PATTERN",
    "OFFICIAL_DISTRICT_ENUM_CONNECTORS",
    "ADMIN_REGION_OFFICE_SUFFIX",
    "INSTITUTION_SUBUNIT_SUFFIXES",
    "INSTITUTION_SCOPE_EXPLANATORY_MARKERS",
    "INSTITUTION_SCOPE_PARTICLES",
    "INSTITUTION_SCOPE_EXCLUDED_TERMS",
    "INSTITUTION_SCOPE_EXCLUDED_SUFFIXES",
)


@pytest.mark.parametrize("name", CONSTANT_NAMES)
def test_query_planning_reexports_same_object(name: str):
    assert hasattr(query_lexicon, name)
    assert hasattr(query_planning, name)
    assert getattr(query_planning, name) is getattr(query_lexicon, name)


def test_query_lexicon_holds_only_the_moved_constants():
    defined = {name for name in vars(query_lexicon) if name.isupper() and not name.startswith("_")}

    assert defined == set(CONSTANT_NAMES)


def test_query_lexicon_defines_no_functions():
    functions = [
        name
        for name, value in vars(query_lexicon).items()
        if inspect.isfunction(value) and value.__module__ == query_lexicon.__name__
    ]

    assert functions == []
