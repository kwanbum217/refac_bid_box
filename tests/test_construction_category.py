"""
tests/test_construction_category.py

건설 을 분야로 쓴 질의가 공사(Cnstwk)로 판정되고, 업체명·기관명·사업명 안의
건설 은 분야로 읽히지 않는지 RAG·채팅 두 플래너에서 검증합니다.
"""

import pytest

from src.app.services.planner_interpreter import interpret_request
from src.rag.query_planning import build_retrieval_plan, extract_category

CONSTRUCTION_QUERIES = (
    "이번 주 건설 공고 열 개 정리해줘",
    "건설 낙찰 결과 5건 보여줘",
    "건설 분야 평균 낙찰률 알려줘",
    "건설 쪽 공고 몇 건이야",
    "최근 건설 공고 5개",
    "건설은 공고 5개",
)

NO_CATEGORY_QUERIES = (
    "대한건설 낙찰 결과",
    "주식회사 한백건설 낙찰 내역",
    "대전광역시 종합건설본부 공고 5개",
    "건설기술연구원 공고",
)

SERVICE_CATEGORY_QUERIES = (
    "주택건설공사 감리 용역 공고",
    "건설사업관리 용역 낙찰 결과",
)


@pytest.mark.parametrize("query", CONSTRUCTION_QUERIES)
def test_extract_category_reads_construction_as_construction_work(query: str) -> None:
    assert extract_category(query) == ("건설", "Cnstwk")


@pytest.mark.parametrize("query", NO_CATEGORY_QUERIES)
def test_extract_category_ignores_construction_inside_names(query: str) -> None:
    assert extract_category(query) == ("", "")


@pytest.mark.parametrize("query", CONSTRUCTION_QUERIES)
def test_rag_plan_filters_construction_category(query: str) -> None:
    assert build_retrieval_plan(query).filters.get("category") == "Cnstwk"


@pytest.mark.parametrize("query", CONSTRUCTION_QUERIES)
def test_chat_plan_filters_construction_category(query: str) -> None:
    assert interpret_request(query).filters.get("category") == "Cnstwk"


@pytest.mark.parametrize("query", NO_CATEGORY_QUERIES)
def test_rag_plan_keeps_names_out_of_category(query: str) -> None:
    assert "category" not in build_retrieval_plan(query).filters


@pytest.mark.parametrize("query", NO_CATEGORY_QUERIES)
def test_chat_plan_keeps_names_out_of_category(query: str) -> None:
    assert "category" not in interpret_request(query).filters


@pytest.mark.parametrize("query", SERVICE_CATEGORY_QUERIES)
def test_both_planners_keep_service_keyword_as_service(query: str) -> None:
    assert build_retrieval_plan(query).filters.get("category") == "Servc"
    assert interpret_request(query).filters.get("category") == "Servc"


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("공사 공고 5개", "Cnstwk"),
        ("용역 공고 5개", "Servc"),
    ],
)
def test_existing_category_keywords_are_unchanged(query: str, expected: str) -> None:
    assert build_retrieval_plan(query).filters.get("category") == expected
    assert interpret_request(query).filters.get("category") == expected
