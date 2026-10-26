"""
tests/test_candidate_verb_regression.py

관형형(올라온·등록된·마감인)·부사·수량어를 기관 후보로 잡아 미해석 안내로
빠지던 회귀를 고정합니다. 실제 기관명은 기관 조건으로 남아야 합니다.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan, is_announcement_list_query

# 기간 창과 마감 창이 2026-10-26 에 고정되도록 기준일을 고정합니다.
_TODAY = date(2026, 10, 26)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _TODAY


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


def _institution_filters(plan) -> dict:
    return {key: value for key, value in plan.filters.items() if "institution" in key}


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        (
            "최근 7일 동안 올라온 공고 총 몇 건이야",
            {"date_from": "2026-10-20", "date_to": "2026-10-26"},
        ),
        (
            "이번 달 새로 등록된 용역 공고 몇 건",
            {"date_from": "2026-10-01", "date_to": "2026-10-26", "category": "Servc"},
        ),
        (
            "오늘 나온 공사 공고 보여줘",
            {
                "date_from": "2026-10-26",
                "date_to": "2026-10-26",
                "category": "Cnstwk",
                "announcement_limit": 5,
            },
        ),
        (
            "최근 들어온 공고 5개",
            {
                "date_from": "2026-10-20",
                "date_to": "2026-10-26",
                "announcement_limit": 5,
            },
        ),
        (
            "올해 발주된 공사 공고 몇 건",
            {"date_from": "2026-01-01", "date_to": "2026-10-26", "category": "Cnstwk"},
        ),
        ("마감된 용역 공고 몇 건", {"category": "Servc"}),
        (
            "최근 공고 전체 몇 건",
            {"date_from": "2026-10-20", "date_to": "2026-10-26"},
        ),
        ("진행중인 공고 몇 건", {}),
    ],
)
def test_predicate_forms_route_without_institution(query: str, expected: dict):
    """관형형·수량어는 기관 조건 없이 기존 통계·목록 경로로 갑니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert _institution_filters(plan) == {}
    for key, value in expected.items():
        assert plan.filters.get(key) == value


def test_close_window_with_predicate_in_keeps_tomorrow_window():
    """서술격 '인' 은 기관 후보가 아니고 내일 마감 창은 그대로 남습니다."""
    plan = build_retrieval_plan("내일 마감인 공고 몇 건이야?")

    assert plan.use_sql is True
    assert _institution_filters(plan) == {}
    assert plan.filters.get("close_from") == "2026-10-27"
    assert plan.filters.get("close_to") == "2026-10-27"
    assert "date_from" not in plan.filters


MODIFIER_AND_ADVERB_QUERIES = [
    "오늘 올라온 용역 공고 알려줘",
    "이번 주 새로 올라온 공고 몇 건",
    "오늘 등록된 물품 공고 몇 건",
    "최근 게시된 공사 공고 몇 건",
    "오늘 나온 용역 공고 몇 건",
    "어제 나온 공고 몇 건",
    "최근 들어온 낙찰 공고 몇 건",
    "이번 달 발주된 용역 공고 몇 건",
    "지난달 마감된 공고 몇 건",
    "남은 공고 몇 건",
    "새로운 공고 몇 건",
    "새로 올라온 공고 몇 건",
    "진행중인 용역 공고 몇 건",
    "낙찰된 용역 공고 몇 건",
    "오늘 마감인 공사 공고 몇 건",
    "최근 공고 전체 몇 건",
    "전체 공고 몇 건",
    "모두 공고 몇 건",
    "총 공고 몇 건",
    "전부 공고 몇 건",
    "대략 공고 몇 건",
    "약 공고 몇 건",
    "혹시 공고 몇 건",
    "좀 공고 몇 건",
    "전체 낙찰 건수",
    "모두 낙찰 건수",
]


@pytest.mark.parametrize("query", MODIFIER_AND_ADVERB_QUERIES)
def test_modifier_and_adverb_never_become_institution(query: str):
    """관형형·부사·수량어 반례가 기관 조건으로 승격되지 않습니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert _institution_filters(plan) == {}


@pytest.mark.parametrize(
    ("query", "institution"),
    [
        ("기술보증기금 올해 공고 건수", "기술보증기금"),
        ("서울대학교병원 올해 공고 건수", "서울대학교병원"),
        ("한국전력공사 작년 대비 올해 공고 건수", "한국전력공사"),
        ("공주시 공고 몇 건", "공주시"),
        ("경기도교육청 올해 공고 건수", "경기도교육청"),
        ("한국인터넷진흥원 평균 낙찰률", "한국인터넷진흥원"),
        ("한국과학기술연구원 올해 공고 건수", "한국과학기술연구원"),
        ("한국국제협력단 올해 공고 건수", "한국국제협력단"),
    ],
)
def test_real_institution_candidates_are_kept(query: str, institution: str):
    """기관 카탈로그에 있는 실제 이름은 ㄴ·ㄹ 받침과 무관하게 후보로 남습니다."""
    plan = build_retrieval_plan(query)

    assert plan.filters.get("institution_name") == institution


def test_unknown_institution_candidate_still_goes_to_unresolved_path():
    """확인되지 않는 기관 후보는 기존처럼 카탈로그 해석 대상으로 남깁니다."""
    plan = build_retrieval_plan("없는기관진흥원 올해 공고 건수")

    assert plan.filters.get("institution_name") == "없는기관진흥원"


@pytest.mark.parametrize(
    "query",
    [
        "공고가 나온 이유",
        "공고가 나온 이유는?",
        "나온 공고의 정의를 말해줘",
        "공고가 나온 것과 기한 사이의 관계",
        "공고가 나온 배경",
        "공고가 나온 배경 알려줘",
        "공고가 나온 사정",
        "들어온 공고 요점 알려줘",
        "나온 공고가 뭐야",
        "들어온 공고의 특징",
        "공고가 들어온 경로 설명",
    ],
)
def test_explanatory_query_with_added_freshness_marker_stays_on_llm_path(query: str):
    """'나온'·'들어온' 은 공고 목록 요청 구조가 아니면 설명형 질의로 남습니다."""
    assert is_announcement_list_query(query) is False

    plan = build_retrieval_plan(query)
    assert plan.use_sql is False
    assert "announcement_limit" not in plan.filters


@pytest.mark.parametrize(
    "query",
    [
        "오늘 나온 공사 공고 보여줘",
        "나온 공고 찾아줘",
        "들어온 공고 알려줘",
        "들어온 용역 공고 5개 보여줘",
        "새로 나온 입찰 공고 목록",
    ],
)
def test_added_freshness_marker_list_query_stays_on_list_path(query: str):
    """'나온'·'들어온' 뒤에 공고 목록 요청 구조가 이어지면 목록 경로를 유지합니다."""
    assert is_announcement_list_query(query) is True

    plan = build_retrieval_plan(query)
    assert plan.use_sql is True
    assert plan.filters.get("announcement_limit") == 5
