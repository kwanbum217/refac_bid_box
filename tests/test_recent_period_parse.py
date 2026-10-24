"""최근/지난 N년, 최근 N주 상대 기간 해석 회귀 테스트.

연, 주 단위 표현이 마지막 "최근" 7일 규칙으로 흘러가지 않아야 합니다.
기존 일, 개월, 분기 해석 결과도 함께 고정합니다.
"""

from datetime import date, timedelta

import pytest

from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan

_FROZEN_TODAY = date(2026, 10, 24)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _FROZEN_TODAY


@pytest.mark.parametrize(
    ("query", "expected_from", "expected_to"),
    [
        ("최근 5년 용역 평균 낙찰률 알려줘", "2021-10-26", "2026-10-24"),
        ("최근 3년 공고 건수 알려줘", "2023-10-26", "2026-10-24"),
        ("최근 1년 낙찰 결과 보여줘", "2025-10-25", "2026-10-24"),
        ("최근 2주 낙찰 결과 보여줘", "2026-10-11", "2026-10-24"),
        ("지난 2년 공고 건수", "2024-10-25", "2026-10-24"),
        ("최근 3년 반 공고 건수", "2023-04-26", "2026-10-24"),
        ("최근 5주년 행사 공고 알려줘", "2026-10-18", "2026-10-24"),
        ("최근 0년 공고 건수", "2025-10-25", "2026-10-24"),
        ("최근 0주 낙찰 결과 보여줘", "2026-10-18", "2026-10-24"),
        ("최근 30일 공고 건수", "2026-09-25", "2026-10-24"),
        ("최근 2개월 공고 건수", "2026-08-26", "2026-10-24"),
        ("최근 낙찰 결과 보여줘", "2026-10-18", "2026-10-24"),
        ("2026년 3분기 낙찰 결과 알려줘", "2026-07-01", "2026-09-30"),
    ],
)
def test_relative_period_window(monkeypatch, query, expected_from, expected_to):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    plan = build_retrieval_plan(query)

    assert plan.filters.get("date_from") == expected_from
    assert plan.filters.get("date_to") == expected_to


@pytest.mark.parametrize(
    ("query", "days"),
    [
        ("최근 5년 용역 낙찰률", 365 * 5 - 1),
        ("최근 3년 공고 건수", 365 * 3 - 1),
        ("최근 1년 낙찰 결과", 365 * 1 - 1),
        ("지난 2년 공고 건수", 365 * 2 - 1),
        ("최근 2주 낙찰 결과", 7 * 2 - 1),
        ("최근 3주 공고 건수", 7 * 3 - 1),
        ("최근 3년 반 공고 건수", (365 * 3) + 182),
        ("최근 5주년 행사 공고 알려줘", 6),
    ],
)
def test_relative_period_span_matches_today(monkeypatch, query, days):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    plan = build_retrieval_plan(query)

    assert plan.filters.get("date_to") == _FROZEN_TODAY.isoformat()
    assert plan.filters.get("date_from") == (_FROZEN_TODAY - timedelta(days=days)).isoformat()
