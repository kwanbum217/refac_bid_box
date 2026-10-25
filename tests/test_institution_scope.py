"""
tests/test_institution_scope.py

시·군·구, 공공기관, 광역 단축명을 지목한 목록·집계 질의의 기관 범위 추출과
RAG·채팅 플래너 필터 적용, SQLite 픽스처 조회를 검증합니다.
"""

from datetime import datetime

import pytest

from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.planner_interpreter import interpret_request
from src.rag.query_planning import (
    build_retrieval_plan,
    extract_institution_scope,
)
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import (
    _announcement_conditions,
    _result_conditions,
    _snapshot_scope,
    retrieve_structured_data,
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("공주시 최근 공고 5개만 리스트로 보여줘", {"institution_name": "공주시"}),
        (
            "한국농어촌공사 공고 최근 거 5개만 뽑아줘",
            {"institution_name": "한국농어촌공사"},
        ),
        ("서울 지역 공고 최근 5개 보여줘", {"institution_name": "서울"}),
        ("부산 쪽 최근 공고 5개만 보여줘", {"institution_name": "부산"}),
        (
            "충남 공고 최근 5개 보여줘",
            {"institution_name": "충남", "institution_aliases": ["충남", "충청남도"]},
        ),
        (
            "경북 최근 공고 5개 보여줘",
            {"institution_name": "경북", "institution_aliases": ["경북", "경상북도"]},
        ),
        ("공주시 낙찰 결과 5개 보여줘", {"institution_name": "공주시"}),
        ("한국농어촌공사 낙찰률 알려줘", {"institution_name": "한국농어촌공사"}),
        ("공주시 공고 건수 알려줘", {"institution_name": "공주시"}),
        ("공주시청 공고 5개 보여줘", {"institution_name": "공주시"}),
        ("대전 유성구 공고 5개 보여줘", {"institution_name": "유성구"}),
        (
            "한국농어촌공사 경남지역본부 공고 5개",
            {"institution_name": "한국농어촌공사 경남지역본부"},
        ),
        ("공주시장 공고 5개 보여줘", {}),
        ("공고 최근 5개 보여줘", {}),
        ("없는시 공고 5개 보여줘", {"institution_name": "없는시"}),
        (
            "경북 인입철도 공사 공고",
            {"institution_name": "경북", "institution_aliases": ["경북", "경상북도"]},
        ),
        ("도시철도 공사 공고 5개", {}),
        ("경기도 공고 5개", {"institution_name": "경기도"}),
        ("충청남도 공고 5개", {"institution_name": "충청남도"}),
        ("수도 공사 공고", {}),
        ("제주특별자치도 공고", {"institution_name": "제주특별자치도"}),
    ],
)
def test_extract_institution_scope_cases(query: str, expected: dict):
    assert extract_institution_scope(query) == expected


@pytest.mark.parametrize(
    "word",
    [
        "인입철도",
        "도시철도",
        "지하철도",
        "고속도",
        "궤도",
        "보도",
        "수도",
        "시도",
        "제도",
        "지도",
        "정도",
        "속도",
        "강도",
        "온도",
        "습도",
        "한도",
    ],
)
def test_extract_institution_scope_rejects_non_administrative_do_words(word: str):
    assert extract_institution_scope(f"{word} 공고 5개") == {}


@pytest.mark.parametrize(
    "query",
    [
        "시설 공사 공고 5개",
        "도로 공사 공고 5개",
        "시스템 구축 용역 공고",
        "공주시장 공고 5개 보여줘",
    ],
)
def test_extract_institution_scope_excludes_general_nouns(query: str):
    assert extract_institution_scope(query) == {}


def test_rag_plan_applies_announcement_institution_scope():
    plan = build_retrieval_plan("공주시 최근 공고 5개만 리스트로 보여줘")

    assert plan.filters.get("institution_name") == "공주시"
    assert plan.filters.get("announcement_limit") == 5


def test_rag_plan_does_not_read_corporation_suffix_as_category():
    plan = build_retrieval_plan("한국농어촌공사 공고 최근 거 5개만 뽑아줘")

    assert plan.filters.get("institution_name") == "한국농어촌공사"
    assert "category" not in plan.filters
    assert plan.filters.get("announcement_limit") == 5


def test_rag_plan_keeps_short_region_aliases():
    plan = build_retrieval_plan("충남 공고 최근 5개 보여줘")

    assert plan.filters.get("institution_name") == "충남"
    assert plan.filters.get("institution_aliases") == ["충남", "충청남도"]


def test_rag_plan_applies_result_list_institution_scope():
    plan = build_retrieval_plan("공주시 낙찰 결과 5개 보여줘")

    assert plan.filters.get("institution_name") == "공주시"
    assert plan.filters.get("result_limit") == 5


def test_rag_plan_skips_institution_scope_for_explanatory_query():
    plan = build_retrieval_plan("공주시 공고 5개 목록을 보는 방법 설명해줘")

    assert "institution_name" not in plan.filters
    assert plan.use_sql is False


def test_chat_plan_fills_institution_without_category_misread():
    execution_plan = interpret_request("한국농어촌공사 공고 최근 거 5개만 뽑아줘")

    assert execution_plan.requested_capabilities == ["bid_query_tool"]
    assert execution_plan.parameters.get("institution_name") == "한국농어촌공사"
    assert "category" not in execution_plan.parameters


@pytest.mark.parametrize(
    ("query", "expected_name"),
    [
        ("공주시 최근 공고 5개만 리스트로 보여줘", "공주시"),
        ("공주시청 공고 5개 보여줘", "공주시"),
        ("대전 유성구 공고 5개 보여줘", "유성구"),
        ("한국농어촌공사 경남지역본부 공고 5개", "한국농어촌공사 경남지역본부"),
    ],
)
def test_chat_plan_uses_extracted_institution_name(query: str, expected_name: str):
    execution_plan = interpret_request(query)

    assert execution_plan.parameters.get("institution_name") == expected_name


def test_chat_plan_carries_region_aliases():
    execution_plan = interpret_request("충남 공고 최근 5개 보여줘")

    assert execution_plan.parameters.get("institution_name") == "충남"
    assert execution_plan.parameters.get("institution_aliases") == ["충남", "충청남도"]


@pytest.mark.parametrize(
    ("query", "expected_name", "expected_aliases"),
    [
        ("대전 유성구 공고 5개 보여줘", "유성구", None),
        ("충남 공주시 최근 공고 5개", "공주시", None),
        ("경기 수원시 낙찰 결과 5개 보여줘", "수원시", None),
        ("서울 지역 공고 최근 5개 보여줘", "서울", None),
        ("충남 공고 최근 5개 보여줘", "충남", ["충남", "충청남도"]),
    ],
)
def test_both_planners_use_specific_scope_over_region_dictionary(
    query: str, expected_name: str, expected_aliases: list[str] | None
):
    plan = build_retrieval_plan(query)
    execution_plan = interpret_request(query)

    assert plan.filters.get("institution_name") == expected_name
    assert execution_plan.parameters.get("institution_name") == expected_name
    if expected_aliases:
        assert plan.filters.get("institution_aliases") == expected_aliases
        assert execution_plan.parameters.get("institution_aliases") == expected_aliases
    else:
        assert "institution_aliases" not in plan.filters
        assert "institution_aliases" not in execution_plan.parameters


@pytest.mark.parametrize(
    ("query", "expected_name", "expected_aliases"),
    [
        ("경북 인입철도 공사 공고", "경북", ["경북", "경상북도"]),
        ("경기도 공고 5개", "경기도", None),
        ("충청남도 공고 5개", "충청남도", None),
        ("제주특별자치도 공고 5개", "제주특별자치도", None),
    ],
)
def test_both_planners_use_official_province_names(
    query: str, expected_name: str, expected_aliases: list[str] | None
):
    plan = build_retrieval_plan(query)
    execution_plan = interpret_request(query)

    assert plan.filters.get("institution_name") == expected_name
    assert execution_plan.filters.get("institution_name") == expected_name
    if expected_aliases:
        assert plan.filters.get("institution_aliases") == expected_aliases
        assert execution_plan.filters.get("institution_aliases") == expected_aliases
    else:
        assert "institution_aliases" not in plan.filters
        assert "institution_aliases" not in execution_plan.filters


@pytest.mark.parametrize(
    "query", ["도시철도 공사 공고 5개", "수도 공사 공고", "수도 공사 공고 5개"]
)
def test_both_planners_skip_institution_for_non_administrative_do_words(query: str):
    plan = build_retrieval_plan(query)
    execution_plan = interpret_request(query)

    assert "institution_name" not in plan.filters
    assert "institution_names" not in plan.filters
    assert "institution_name" not in execution_plan.filters
    assert "institution_names" not in execution_plan.filters


@pytest.mark.parametrize(
    ("query", "expected_category"),
    [
        ("시설 공사 공고 5개", "Cnstwk"),
        ("도로 공사 공고 5개", "Cnstwk"),
        ("시스템 구축 용역 공고 5개", "Servc"),
    ],
)
def test_chat_plan_keeps_category_for_field_queries(query: str, expected_category: str):
    execution_plan = interpret_request(query)

    assert execution_plan.parameters.get("category") == expected_category
    assert "institution_name" not in execution_plan.parameters


def _announcement(
    bid_ntce_no: str,
    institution: str,
    day: int,
    *,
    category: str = "Servc",
) -> BidAnnouncement:
    return BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="000",
        category=category,
        bid_ntce_nm=f"공고 {bid_ntce_no}",
        dminstt_nm=institution,
        presmpt_prce=1000000,
        bid_ntce_dt=datetime(2026, 10, day),
        bid_clse_dt=datetime(2026, 10, day + 1),
        collected_at=datetime(2026, 10, day),
    )


def _result(
    bid_ntce_no: str,
    institution: str,
    day: int,
    *,
    category: str = "Servc",
) -> BidResult:
    return BidResult(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord="00",
        bid_ntce_nm=f"낙찰 {bid_ntce_no}",
        bidwinnr_nm=f"업체 {bid_ntce_no}",
        sucsf_bid_amt=1000000,
        sucsf_bid_rate=90.0,
        rl_openg_dt=datetime(2026, 10, day),
        dminstt_nm=institution,
        category=category,
        collected_at=datetime(2026, 10, day),
    )


@pytest.fixture
def institution_db(isolated_db):
    isolated_db.add_all(
        [
            _announcement("ANN-001", "충청남도 공주시", 1),
            _announcement("ANN-002", "충청남도 공주시 농업기술센터", 2),
            _announcement("ANN-003", "충청남도 서산시", 3),
            _announcement("ANN-004", "서울특별시", 4),
            _announcement("ANN-005", "충남개발공사", 5),
            _announcement("ANN-006", "충청남도교육청", 6),
            _announcement("ANN-007", "한국농어촌공사 경남지역본부 진주.산청지사", 7),
            _announcement("ANN-008", "한국농어촌공사", 8),
            _announcement("ANN-009", "대전광역시 유성구청", 9),
            _announcement("ANN-010", "대전광역시 서구청", 10),
        ]
    )
    isolated_db.add_all(
        [
            _result("RES-001", "충청남도 공주시", 1),
            _result("RES-002", "충청남도 공주시 농업기술센터", 2),
            _result("RES-003", "서울특별시", 3),
            _result("RES-004", "한국농어촌공사 경남지역본부", 4),
        ]
    )
    isolated_db.commit()
    return isolated_db


def _sample_announcements(db, filters: dict) -> list[dict]:
    plan = RetrievalPlan(use_sql=True, filters=filters)
    return retrieve_structured_data(db, plan)["summary"]["sample_announcements"]


def test_announcement_query_returns_only_scoped_institution(institution_db):
    samples = _sample_announcements(
        institution_db, {"institution_name": "공주시", "announcement_limit": 20}
    )

    assert {sample["bid_ntce_no"] for sample in samples} == {"ANN-001", "ANN-002"}
    assert all("공주시" in sample["dminstt_nm"] for sample in samples)


def test_announcement_query_does_not_return_global_rows_for_unknown_institution(
    institution_db,
):
    samples = _sample_announcements(
        institution_db, {"institution_name": "없는시", "announcement_limit": 5}
    )

    assert samples == []


def test_alias_union_includes_short_and_full_region_names(institution_db):
    samples = _sample_announcements(
        institution_db,
        {
            "institution_name": "충남",
            "institution_aliases": ["충남", "충청남도"],
            "announcement_limit": 20,
        },
    )

    assert {sample["bid_ntce_no"] for sample in samples} == {
        "ANN-001",
        "ANN-002",
        "ANN-003",
        "ANN-005",
        "ANN-006",
    }


def test_district_scope_returns_only_that_district(institution_db):
    scope = extract_institution_scope("대전 유성구 공고 5개 보여줘")
    samples = _sample_announcements(institution_db, {**scope, "announcement_limit": 5})

    assert {sample["bid_ntce_no"] for sample in samples} == {"ANN-009"}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("대전 유성구 공고 5개 보여줘", {"ANN-009"}),
        ("충남 공주시 공고 5개 보여줘", {"ANN-001", "ANN-002"}),
        ("경기 수원시 공고 5개 보여줘", set()),
    ],
)
def test_rag_plan_scope_filters_sql_rows(institution_db, query: str, expected: set[str]):
    plan = build_retrieval_plan(query)
    samples = _sample_announcements(institution_db, plan.filters)

    assert {sample["bid_ntce_no"] for sample in samples} == expected


def test_result_query_returns_only_scoped_institution(institution_db):
    plan = RetrievalPlan(
        use_sql=True,
        filters={"institution_name": "공주시", "result_limit": 5},
    )
    recent = retrieve_structured_data(institution_db, plan)["summary"]["recent_results"]

    assert {row["bid_ntce_no"] for row in recent} == {"RES-001", "RES-002"}
    assert all("공주시" in row["dminstt_nm"] for row in recent)


def test_conditions_accept_resolved_names_without_institution_name():
    plan = RetrievalPlan(
        use_sql=True,
        filters={"institution_aliases": ["충청남도"]},
    )

    assert len(_announcement_conditions(plan, institution_names=["충청남도 공주시"])) == 1
    assert len(_result_conditions(plan, institution_names=["충청남도 공주시"])) == 1


def test_snapshot_scope_is_disabled_for_institution_aliases():
    plan = RetrievalPlan(
        use_sql=True,
        filters={"institution_name": "충남", "institution_aliases": ["충남", "충청남도"]},
    )
    alias_only = RetrievalPlan(
        use_sql=True,
        filters={"institution_aliases": ["충남", "충청남도"]},
    )

    assert _snapshot_scope(plan) is None
    assert _snapshot_scope(alias_only) is None
