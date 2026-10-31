"""
tests/test_region_fallback_boundary.py

지역 키워드 폴백이 낱말 내부의 부분 문자열을 지역 조건으로 승격하지 않는지
검증합니다. "환경기술" 안의 "경기" 같은 오탐은 사라지고, 어절 시작에서 나온
정상 지역 질문의 판정은 그대로여야 합니다.
"""

from __future__ import annotations

from datetime import date

import pytest

from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan

# 날짜 창이 고정되도록 오늘을 2026-10-31 로 고정합니다.
_FROZEN_TODAY = date(2026, 10, 31)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _FROZEN_TODAY


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


@pytest.mark.parametrize(
    "query",
    [
        "○○환경기술이 낙찰받은 용역 결과 알려줘",
        "농업부산물 처리 용역 공고 5개 보여줘",
        "동서울터미널 리모델링 공사 공고 보여줘",
        "관광주간 운영 용역 공고 보여줘",
        "북대구역사 환경정비 공사 공고 보여줘",
        "연구과제주관기관 공고 보여줘",
        "친환경기술 개발 용역 공고 보여줘",
        "안전보건울산물류 공사 공고 보여줘",
    ],
)
def test_word_internal_region_is_not_institution_scope(query: str):
    filters = build_retrieval_plan(query).filters

    assert "institution_name" not in filters
    assert "institution_names" not in filters


def test_reported_environment_technology_utterance_drops_region():
    filters = build_retrieval_plan("○○환경기술이 낙찰받은 용역 결과 알려줘").filters

    assert filters.get("category") == "Servc"
    assert "institution_name" not in filters


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("경기 지역 용역 공고", "경기"),
        ("경기도 공사 공고 보여줘", "경기도"),
        ("서울 공고 최근 5건", "서울"),
        ("부산 공사 낙찰 결과", "부산"),
        ("(경기) 용역 공고", "경기"),
        ("광주광역시 공고", "광주"),
        ("서울시 공고", "서울"),
        ("부산에서 공고", "부산"),
        ("경기권 공고", "경기"),
        ("충북 공고 최근 5개 보여줘", "충북"),
        ("제주 공고 몇 건", "제주"),
        ("세종시 공고", "세종"),
    ],
)
def test_region_at_word_start_is_institution_scope(query: str, expected: str):
    assert build_retrieval_plan(query).filters.get("institution_name") == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("환경기술 경기 용역 공고", "경기"),
        ("환경기술 서울 공고 최근 5건", "서울"),
        ("농업부산물 부산 공고", "부산"),
    ],
)
def test_later_word_start_occurrence_still_matches(query: str, expected: str):
    assert build_retrieval_plan(query).filters.get("institution_name") == expected


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("2026서울 공고 보여줘", "서울"),
        ("2026경기도 공고", "경기"),
        ("2026부산 공고 최근 5건", "부산"),
    ],
)
def test_region_right_after_number_is_institution_scope(query: str, expected: str):
    assert build_retrieval_plan(query).filters.get("institution_name") == expected


@pytest.mark.parametrize(
    "query",
    [
        "2026년서울 공고",
        "1차서울 용역 공고",
        "올해서울 공고",
    ],
)
def test_region_attached_to_korean_word_is_not_institution_scope(query: str):
    filters = build_retrieval_plan(query).filters

    assert "institution_name" not in filters
    assert "institution_names" not in filters
