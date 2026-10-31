"""기간 표지가 기관·지역명에 붙어 있을 때의 조건 오염·소실 회귀 테스트.

"10월서울", "3분기한국전력공사" 처럼 기간 표지와 기관·지역명이 띄어쓰기 없이
붙으면 기관 후보 추출기가 어절 전체를 이름으로 읽어 조건이 오염되거나 사라졌습니다.
`build_retrieval_plan` 진입부에서 기간 표지 뒤에 공백을 넣어, 붙여 쓴 질문이
띄어 쓴 대조 형태와 같은 판정을 내는지 고정합니다.

반대로 "2026년도", "3분기별" 처럼 표지가 단위·조사로 이어지는 형태는 분리하지
않아야 하므로, 수정 전 main 과 같은 판정을 유지하는지 함께 고정합니다.
"""

from datetime import date

import pytest

from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan

_FROZEN_TODAY = date(2026, 10, 31)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _FROZEN_TODAY


_ATTACHED_PAIRS = [
    ("10월서울 공고 건수", "10월 서울 공고 건수"),
    ("3분기한국전력공사 낙찰 건수", "3분기 한국전력공사 낙찰 건수"),
    ("올해한국도로공사 공고 수", "올해 한국도로공사 공고 수"),
    ("작년경기도 공고 건수", "작년 경기도 공고 건수"),
    ("상반기부산 공고 건수", "상반기 부산 공고 건수"),
    ("2025년조달청 공고 건수", "2025년 조달청 공고 건수"),
    ("10월부산 낙찰 건수", "10월 부산 낙찰 건수"),
    ("3분기서울특별시 공고 목록 보여줘", "3분기 서울특별시 공고 목록 보여줘"),
    ("올해한국수자원공사 공고 건수", "올해 한국수자원공사 공고 건수"),
    ("이번주국방부 낙찰 건수", "이번주 국방부 낙찰 건수"),
    ("지난달한국토지주택공사 공고 건수", "지난달 한국토지주택공사 공고 건수"),
    ("최근 30일조달청 공고 건수", "최근 30일 조달청 공고 건수"),
    ("지난 한 달한국전력공사 공고 건수", "지난 한 달 한국전력공사 공고 건수"),
    ("2025서울 공고 건수", "2025 서울 공고 건수"),
    ("이번달경기도 낙찰 건수", "이번달 경기도 낙찰 건수"),
]


@pytest.mark.parametrize(("attached", "spaced"), _ATTACHED_PAIRS)
def test_attached_period_matches_spaced_control(monkeypatch, attached, spaced):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    attached_filters = build_retrieval_plan(attached).filters
    spaced_filters = build_retrieval_plan(spaced).filters

    assert attached_filters.get("institution_name") == spaced_filters.get("institution_name")
    assert attached_filters.get("date_from") == spaced_filters.get("date_from")
    assert attached_filters.get("date_to") == spaced_filters.get("date_to")


@pytest.mark.parametrize(
    ("query", "expected_institution", "expected_from", "expected_to"),
    [
        # 연도 없는 월은 가장 최근에 시작된 그 달로 읽습니다(연도 없는 월·분기 병합 뒤).
        ("10월서울 공고 건수", "서울", "2026-10-01", "2026-10-31"),
        ("3분기한국전력공사 낙찰 건수", "한국전력공사", None, None),
        ("올해한국도로공사 공고 수", None, "2026-01-01", "2026-10-31"),
        ("작년경기도 공고 건수", "경기도", "2025-01-01", "2025-12-31"),
        ("상반기부산 공고 건수", "부산", "2026-01-01", "2026-06-30"),
        ("2025년조달청 공고 건수", "조달청", "2025-01-01", "2025-12-31"),
    ],
)
def test_attached_period_keeps_institution_and_date(
    monkeypatch, query, expected_institution, expected_from, expected_to
):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    filters = build_retrieval_plan(query).filters

    assert filters.get("institution_name") == expected_institution
    assert filters.get("date_from") == expected_from
    assert filters.get("date_to") == expected_to


@pytest.mark.parametrize(
    ("query", "expected_filters"),
    [
        ("2026년도 공고", {"date_from": "2026-01-01", "date_to": "2026-12-31"}),
        ("10월에 공고", {"date_from": "2026-10-01", "date_to": "2026-10-31"}),
        ("3분기별 낙찰", {"time_bucket": "quarter", "analysis_mode": "trend"}),
        ("2025년간 낙찰", {"date_from": "2025-01-01", "date_to": "2025-12-31"}),
        ("이번주에 공고", {"date_from": "2026-10-25", "date_to": "2026-10-31"}),
        ("10월말 공고", {}),
    ],
)
def test_unit_suffix_is_not_split(monkeypatch, query, expected_filters):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    assert query_planning._split_attached_period(query) == query

    assert build_retrieval_plan(query).filters == expected_filters
