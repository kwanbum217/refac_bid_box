"""
tests/test_scoped_list_request.py

개수·목록·신선도 표지 없이 기관·지역 범위와 요청 동사만 있는 공고 질문이
공고 목록으로 판정되고, 그 기관·지역 조건이 조회 플랜에 유지되는지 검증합니다.
설명형·통계형·명사구 단독·분야 단독 질의는 기존 경로를 그대로 씁니다.
"""

import pytest

from src.rag.query_planning import (
    build_retrieval_plan,
    is_announcement_list_query,
)


@pytest.mark.parametrize(
    ("query", "expected_institution", "expected_category"),
    [
        ("서울특별시 용역 공고 알려줘", "서울", "Servc"),
        ("서울특별시 용역 공고 보여줘", "서울", "Servc"),
        ("부산 물품 공고 알려줘", "부산", "Thng"),
        ("한국전력공사 공사 공고 알려줘", "한국전력공사", "Cnstwk"),
        ("조달청 용역 공고 알려줘", "조달청", "Servc"),
        ("최근 서울특별시 수요기관의 용역 공고 알려줘", "서울", "Servc"),
    ],
)
def test_scoped_announcement_request_is_list_query(
    query: str, expected_institution: str, expected_category: str
):
    assert is_announcement_list_query(query) is True

    plan = build_retrieval_plan(query)
    assert plan.use_sql is True
    assert plan.filters.get("announcement_limit") == 5
    assert plan.filters.get("institution_name") == expected_institution
    assert plan.filters.get("category") == expected_category
    assert "result_limit" not in plan.filters


@pytest.mark.parametrize(
    "query",
    [
        "서울특별시 용역 공고 절차 알려줘",
        "한국전력공사 공고 기준 알려줘",
        "부산 물품 공고 몇 건",
        "부산 물품 공고",
        "용역 공고 알려줘",
        "한국전력공사가 뭐야",
        "한국전력공사 입찰 방법 알려줘",
        "최신 한국전력공사 공고 보여줘",
        "오늘 올라온 한국농어촌공사 공고 알려줘",
    ],
)
def test_unscoped_or_non_list_announcement_query_is_not_list(query: str):
    assert is_announcement_list_query(query) is False
    assert "announcement_limit" not in build_retrieval_plan(query).filters
