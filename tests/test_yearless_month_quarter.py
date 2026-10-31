"""연도를 적지 않은 월·분기 표지의 기간 해석 회귀 테스트.

2026-10-31 을 오늘로 고정하면 연도가 없는 표지는 이미 시작된 가장 최근 기간을
가리켜야 합니다.

- "10월" 은 2026-10-01 ~ 2026-10-31, "11월" 은 2025-11-01 ~ 2025-11-30 입니다.
- "3분기" 는 2026-07-01 ~ 2026-09-30, "4분기" 는 2026-10-01 ~ 2026-12-31 입니다.

연도를 적은 형태와 이번달·지난달·최근 N개월 같은 다른 기간 표지의 판정은
그대로이고, 월이 아닌 숫자(12개월, 대상월, 공고번호, 비율)는 월로 읽지 않습니다.
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


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


@pytest.mark.parametrize(
    ("query", "expected_from", "expected_to"),
    [
        ("10월 공고 건수", "2026-10-01", "2026-10-31"),
        ("11월 공고 건수", "2025-11-01", "2025-11-30"),
        ("3분기 낙찰 건수", "2026-07-01", "2026-09-30"),
        ("4분기 낙찰 건수", "2026-10-01", "2026-12-31"),
        ("1월 공고 건수", "2026-01-01", "2026-01-31"),
        ("12월 공고 건수", "2025-12-01", "2025-12-31"),
        ("1분기 낙찰 건수", "2026-01-01", "2026-03-31"),
        ("2분기 낙찰 건수", "2026-04-01", "2026-06-30"),
    ],
)
def test_yearless_marker_uses_most_recent_started_window(query, expected_from, expected_to):
    plan = build_retrieval_plan(query)

    assert plan.filters.get("date_from") == expected_from
    assert plan.filters.get("date_to") == expected_to
    assert plan.use_sql is True
    assert plan.route_reason == "정형 통계 질의"


@pytest.mark.parametrize(
    ("query", "expected_from", "expected_to"),
    [
        ("2025년 10월 공고 건수", "2025-10-01", "2025-10-31"),
        ("2026년 3분기 낙찰 건수", "2026-07-01", "2026-09-30"),
        ("2026년 1분기 용역 낙찰 통계 알려줘", "2026-01-01", "2026-03-31"),
        ("이번달 공고 건수", "2026-10-01", "2026-10-31"),
        ("지난달 공고 건수", "2026-09-01", "2026-09-30"),
        ("최근 3개월 공고 건수", "2026-08-03", "2026-10-31"),
        ("올해 공고 건수", "2026-01-01", "2026-10-31"),
        ("작년 공고 건수", "2025-01-01", "2025-12-31"),
    ],
)
def test_existing_period_markers_unchanged(query, expected_from, expected_to):
    plan = build_retrieval_plan(query)

    assert plan.filters.get("date_from") == expected_from
    assert plan.filters.get("date_to") == expected_to


@pytest.mark.parametrize(
    "query",
    [
        "12개월 공고 건수",
        "10월말 공고 건수",
        "1차 3월 분 공고",
        "10월부터 12월까지 공고 건수",
        "10월과 11월 공고 건수 비교",
        "서로 다른 달(예: 4월 공고, 5월 개찰)에 걸친 건은 어떻게 세나요?",
        "3분기와 4분기 낙찰 비교",
        "R26BK01778156 낙찰률 높은 편이야?",
        "사정률 90% 공고 건수",
    ],
)
def test_month_like_numbers_do_not_create_window(query):
    plan = build_retrieval_plan(query)

    assert "date_from" not in plan.filters
    assert "date_to" not in plan.filters
