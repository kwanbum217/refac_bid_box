"""
tests/test_multi_institution_list.py

기관 둘 이상을 나열한 목록 질의의 기관 추출, RAG·채팅 플래너 필터, SQLite
조회를 검증합니다.

- "공주시와 서산시의 공고 최근 5개 보여줘", "공주시랑 서산시 공고 5개" 는 두
  기관을 모두 institution_names 로 담고 공고 목록을 조회합니다.
- "한국전력공사와 한국농어촌공사 낙찰 결과 5건" 은 기관 접미사 때문에 개체
  지정으로 판정되던 질의이므로 전용 판정으로 낙찰 결과 목록 경로에 보냅니다.
- 단일 기관, 지역 비교, 기관 없는 목록은 기존 동작을 유지합니다.
- 조회 결과는 요청한 기관 행만 담고, 없는 기관만 지목하면 전체 목록으로
  넓어지지 않습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.planner_interpreter import interpret_request
from src.rag.query_planning import (
    build_retrieval_plan,
    extract_institution_scope,
    is_multi_institution_result_list_query,
)
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import (
    _announcement_conditions,
    _result_conditions,
    retrieve_structured_data,
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("공주시와 서산시의 공고 최근 5개 보여줘", ["공주시", "서산시"]),
        ("공주시랑 서산시 공고 5개", ["공주시", "서산시"]),
        ("공주시, 서산시 공고 5개", ["공주시", "서산시"]),
        ("공주시 및 서산시 공고 5개", ["공주시", "서산시"]),
        ("한국전력공사와 한국농어촌공사 낙찰 결과 5건", ["한국전력공사", "한국농어촌공사"]),
    ],
)
def test_extract_multi_institution_scope(query: str, expected: list[str]):
    assert extract_institution_scope(query, multiple=True) == {"institution_names": expected}


@pytest.mark.parametrize(
    "query",
    [
        "공주시 공고 5개",
        "대전 유성구 공고 5개 보여줘",
        "낙찰금액과 추정가격의 차이를 설명해줘",
        "공고 최근 5개 보여줘",
    ],
)
def test_extract_multi_institution_scope_keeps_single_or_empty(query: str):
    assert "institution_names" not in extract_institution_scope(query, multiple=True)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("공주시와 서산시의 공고 최근 5개 보여줘", ["공주시", "서산시"]),
        ("공주시랑 서산시 공고 5개", ["공주시", "서산시"]),
    ],
)
def test_both_planners_carry_all_enumerated_institutions(query: str, expected: list[str]):
    plan = build_retrieval_plan(query)
    execution_plan = interpret_request(query)

    assert plan.filters.get("institution_names") == expected
    assert "institution_name" not in plan.filters
    assert execution_plan.filters.get("institution_names") == expected
    assert execution_plan.parameters.get("institution_names") == expected
    assert "institution_name" not in execution_plan.filters
    assert "institution_name" not in execution_plan.parameters


def test_both_planners_route_multi_institution_result_list():
    query = "한국전력공사와 한국농어촌공사 낙찰 결과 5건"

    plan = build_retrieval_plan(query)
    execution_plan = interpret_request(query)

    assert plan.filters.get("institution_names") == ["한국전력공사", "한국농어촌공사"]
    assert plan.filters.get("result_limit") == 5
    assert "institution_name" not in plan.filters
    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("institution_names") == [
        "한국전력공사",
        "한국농어촌공사",
    ]
    assert execution_plan.parameters.get("limit") == 5
    assert "category" not in execution_plan.parameters


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("한국전력공사와 한국농어촌공사 낙찰 결과 5건", True),
        ("한국전력공사와 한국농어촌공사 낙찰 결과 목록", True),
        ("한국전력공사 낙찰 결과 5건", False),
        ("부산이랑 대구 공고 건수 비교해줘", False),
        ("공주시랑 서산시 공고 5개", False),
    ],
)
def test_multi_institution_result_list_predicate(query: str, expected: bool):
    assert is_multi_institution_result_list_query(query) is expected


def test_single_institution_keeps_existing_contract():
    query = "공주시 공고 5개"

    plan = build_retrieval_plan(query)
    execution_plan = interpret_request(query)

    assert plan.filters.get("institution_name") == "공주시"
    assert "institution_names" not in plan.filters
    assert execution_plan.parameters.get("institution_name") == "공주시"
    assert "institution_names" not in execution_plan.parameters


def test_region_comparison_keeps_comparison_path():
    query = "부산이랑 대구 공고 건수 비교해줘"

    plan = build_retrieval_plan(query)

    assert plan.filters.get("region_names") == ["부산", "대구"]
    assert plan.filters.get("metric") == "announcement_count"
    assert "institution_names" not in plan.filters


def test_conditions_accept_multiple_resolved_institution_names():
    plan = RetrievalPlan(use_sql=True, filters={"institution_names": ["공주시", "서산시"]})

    announcement_conditions = _announcement_conditions(
        plan, institution_names=["충청남도 공주시", "충청남도 서산시"]
    )
    result_conditions = _result_conditions(
        plan, institution_names=["충청남도 공주시", "충청남도 서산시"]
    )

    assert len(announcement_conditions) == 1
    assert len(result_conditions) == 1


def _announcement(bid_ntce_no: str, institution: str, days_ago: int) -> BidAnnouncement:
    published_at = datetime.now() - timedelta(days=days_ago)
    return BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        category="Servc",
        bid_ntce_nm=f"공고 {bid_ntce_no}",
        dminstt_nm=institution,
        presmpt_prce=1000000,
        bid_ntce_dt=published_at,
        bid_clse_dt=published_at + timedelta(days=1),
        collected_at=published_at,
    )


def _result(bid_ntce_no: str, institution: str, days_ago: int) -> BidResult:
    opened_at = datetime.now() - timedelta(days=days_ago)
    return BidResult(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="00",
        bid_ntce_nm=f"낙찰 {bid_ntce_no}",
        bidwinnr_nm=f"업체 {bid_ntce_no}",
        sucsf_bid_amt=1000000,
        sucsf_bid_rate=90.0,
        rl_openg_dt=opened_at,
        dminstt_nm=institution,
        category="Servc",
        collected_at=opened_at,
    )


@pytest.fixture
def multi_institution_db(isolated_db):
    isolated_db.add_all(
        [
            _announcement("ANN-001", "충청남도 공주시", 0),
            _announcement("ANN-002", "충청남도 공주시 농업기술센터", 1),
            _announcement("ANN-003", "충청남도 서산시", 2),
            _announcement("ANN-004", "서울특별시", 3),
            _announcement("ANN-005", "한국전력공사", 4),
            _announcement("ANN-006", "한국농어촌공사", 5),
        ]
    )
    isolated_db.add_all(
        [
            _result("RES-001", "충청남도 공주시", 0),
            _result("RES-002", "충청남도 서산시", 1),
            _result("RES-003", "서울특별시", 2),
            _result("RES-004", "한국전력공사", 3),
            _result("RES-005", "한국농어촌공사", 4),
        ]
    )
    isolated_db.commit()
    return isolated_db


@pytest.mark.parametrize(
    "query",
    [
        "공주시와 서산시의 공고 최근 5개 보여줘",
        "공주시랑 서산시 공고 5개",
    ],
)
def test_multi_institution_announcement_list_returns_only_requested_rows(
    multi_institution_db, query: str
):
    plan = build_retrieval_plan(query)
    result = retrieve_structured_data(multi_institution_db, plan)
    samples = result["summary"]["sample_announcements"]
    returned = {sample["bid_ntce_no"] for sample in samples}

    assert returned == {"ANN-001", "ANN-002", "ANN-003"}
    assert all(
        "공주시" in sample["dminstt_nm"] or "서산시" in sample["dminstt_nm"] for sample in samples
    )
    assert result["filters"].get("institution_names") == ["공주시", "서산시"]
    assert "ANN-004" not in returned
    assert "ANN-005" not in returned


def test_multi_institution_result_list_returns_only_requested_rows(multi_institution_db):
    plan = build_retrieval_plan("한국전력공사와 한국농어촌공사 낙찰 결과 5건")
    result = retrieve_structured_data(multi_institution_db, plan)
    recent = result["summary"]["recent_results"]
    returned = {row["bid_ntce_no"] for row in recent}

    assert returned == {"RES-004", "RES-005"}
    assert all(
        "한국전력공사" in row["dminstt_nm"] or "한국농어촌공사" in row["dminstt_nm"]
        for row in recent
    )
    assert result["filters"].get("institution_names") == ["한국전력공사", "한국농어촌공사"]


@pytest.mark.parametrize(
    "filters",
    [
        {"institution_names": ["완전히없는기관A", "완전히없는기관B"], "announcement_limit": 5},
        {"institution_names": ["완전히없는기관A", "완전히없는기관B"], "result_limit": 5},
    ],
)
def test_unknown_multi_institutions_do_not_fall_back_to_global_list(
    multi_institution_db, filters: dict
):
    result = retrieve_structured_data(
        multi_institution_db, RetrievalPlan(use_sql=True, filters=filters)
    )

    assert result["query_skipped"] is True
    assert result["summary"]["sample_announcements"] == []
    assert result["summary"]["recent_results"] == []
    assert any("확인하지 못해" in hint for hint in result["insufficiency_hints"])
