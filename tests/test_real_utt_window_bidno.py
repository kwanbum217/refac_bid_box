"""실사용 발화 점검에서 확인된 기간 표지·공고번호 기관 오인 회귀 테스트.

2026-10-31 점검(main 기준)에서 두 결함을 확인했습니다.

- "지난 한 달" 처럼 숫자가 없는 기간 표지가 날짜 필터를 만들지 못했습니다.
  "지난 한 달 용역 공고 5개만" 은 filters 에 날짜 키 없이 공고 목록으로 갔습니다.
- 공고번호 단건 통계 질의에서 공고번호 문자열이 institution_name 으로도
  들어갔습니다. "R26BK01778156 낙찰률 높은 편이야?" 의 filters 는
  `{"bid_ntce_no": "R26BK01778156", "institution_name": "r26bk01778156"}` 였습니다.

"지난 한 달" 계열은 "최근 한 달" 과 같은 오늘 포함 30일 창을 내야 하고,
"지난달" 단독은 달력상 전월이라는 기존 동작을 그대로 유지합니다.
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


@pytest.mark.parametrize(
    ("query", "expected_filters"),
    [
        (
            "지난 한 달 용역 공고 5개만",
            {
                "date_from": "2026-10-02",
                "date_to": "2026-10-31",
                "category": "Servc",
                "announcement_limit": 5,
            },
        ),
        (
            "지난 한달 용역 공고 5개만",
            {
                "date_from": "2026-10-02",
                "date_to": "2026-10-31",
                "category": "Servc",
                "announcement_limit": 5,
            },
        ),
        (
            "최근 한 달 용역 공고 5개만",
            {
                "date_from": "2026-10-02",
                "date_to": "2026-10-31",
                "category": "Servc",
                "announcement_limit": 5,
            },
        ),
    ],
)
def test_last_one_month_window_matches_recent_one_month(monkeypatch, query, expected_filters):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    plan = build_retrieval_plan(query)

    assert plan.filters == expected_filters
    assert plan.use_sql is True
    assert plan.route_reason == "공고 목록 질의"


@pytest.mark.parametrize(
    ("query", "expected_from", "expected_to"),
    [
        ("지난달 물품 공고 몇 건이었어?", "2026-09-01", "2026-09-30"),
        ("지난달 공사 낙찰 건수 몇 건이야?", "2026-09-01", "2026-09-30"),
    ],
)
def test_previous_calendar_month_unchanged(monkeypatch, query, expected_from, expected_to):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    plan = build_retrieval_plan(query)

    assert plan.filters.get("date_from") == expected_from
    assert plan.filters.get("date_to") == expected_to
    assert plan.route_reason == "정형 통계 질의"


@pytest.mark.parametrize(
    ("query", "expected_bid_ntce_no"),
    [
        ("R26BK01778156 낙찰률 높은 편이야?", "R26BK01778156"),
        ("123456789012 낙찰률 높은 편이야?", ""),
    ],
)
def test_bid_number_is_not_institution_name(monkeypatch, query, expected_bid_ntce_no):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    plan = build_retrieval_plan(query)

    assert "institution_name" not in plan.filters
    assert plan.filters.get("bid_ntce_no", "") == expected_bid_ntce_no
    assert plan.use_sql is True
    assert "정형 통계 질의" in plan.route_reason


def test_bid_number_single_query_keeps_route_reason(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)

    plan = build_retrieval_plan("R26BK01778156 낙찰률 높은 편이야?")

    assert plan.filters == {"bid_ntce_no": "R26BK01778156"}
    assert plan.route_reason == "공고번호 단건 질의, 정형 통계 질의"
