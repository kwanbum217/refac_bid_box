"""SQL 판정과 route_reason 진단 문구가 어긋나지 않는지 고정합니다.

묶음 6 계획 비교에서 q097, q101 은 SQL 로 바뀌었는데 route_reason 이 기본 벡터
질의로 남았습니다. SQL 을 켠 조건이 사유에 남는지만 검증하고, 정의·차이 질문인
q092 가 기관 비교로 승격되지 않는 것도 함께 고정합니다.
"""

from datetime import date

import pytest

from src.rag import query_planning
from src.rag.query_planning import build_retrieval_plan

_FROZEN_TODAY = date(2026, 10, 28)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _FROZEN_TODAY


@pytest.fixture
def frozen_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


def test_q097_institution_amount_ranking_keeps_axis_reason(frozen_today):
    """축별 낙찰 금액 순위는 SQL 이고 사유가 기본 벡터 질의로 남지 않습니다."""
    plan = build_retrieval_plan("최근 30일 수요기관별 낙찰 금액 상위는 어디야")

    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters == {
        "date_from": "2026-09-29",
        "date_to": "2026-10-28",
        "group_by": "institution",
        "metric": "award_amount",
        "group_limit": 20,
    }
    assert "축별 집계 질의" in plan.route_reason
    assert "기본 벡터 질의" not in plan.route_reason


def test_q101_award_trend_keeps_trend_reason(frozen_today):
    """낙찰 동향의 시계열 조회는 SQL 이고 사유가 추이 질의입니다."""
    plan = build_retrieval_plan("공사 부문 최근 30일 낙찰 동향 알려줘")

    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters == {
        "date_from": "2026-09-29",
        "date_to": "2026-10-28",
        "category": "Cnstwk",
        "analysis_mode": "trend",
        "metric": "bid_count",
    }
    assert "추이 질의" in plan.route_reason
    assert "기본 벡터 질의" not in plan.route_reason


def test_q092_definition_question_keeps_default_vector_reason():
    """정의·차이 질문은 기관 비교로 승격되지 않고 기본 벡터 질의로 처리됩니다.

    제도명(적격심사)과 계약방식(최저가낙찰제)은 NON_INSTITUTION_SUFFIXES 에서
    배제되어 SQL 판정과 기관 필터가 생기지 않습니다.
    """
    plan = build_retrieval_plan("적격심사와 최저가낙찰제의 차이가 무엇인가요")

    assert plan.use_sql is False
    assert plan.use_vector is True
    assert plan.filters == {}
    assert plan.route_reason == "기본 벡터 질의"


@pytest.mark.parametrize(
    ("query", "use_vector"),
    [
        ("최근 30일 수요기관별 낙찰 금액 상위는 어디야", False),
        ("공사 부문 최근 30일 낙찰 동향 알려줘", False),
    ],
)
def test_sql_decision_never_reports_default_vector_reason(query, use_vector):
    """SQL 판정인 두 질문은 어떤 경우에도 기본 벡터 질의 문구를 쓰지 않습니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.use_vector is use_vector
    assert plan.route_reason
    assert "기본 벡터 질의" not in plan.route_reason


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("최근 3개월 평균 낙찰금액 추세를 알려줘", "정형 통계 질의"),
        ("3억 넘는 낙찰 건수 알려줘", "정형 통계 질의"),
        ("최근 낙찰된 용역 사업 5개만 리스트 해봐라", "낙찰 결과 목록 질의"),
    ],
)
def test_existing_sql_route_reasons_are_unchanged(query, expected):
    """이미 사유가 있던 SQL 경로의 문자열은 그대로 유지합니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.route_reason == expected


def test_default_vector_query_keeps_default_reason():
    """SQL 이 아닌 기본 질의는 기존 기본 벡터 질의 문구를 유지합니다."""
    plan = build_retrieval_plan("안내 부탁드립니다")

    assert plan.use_sql is False
    assert plan.use_vector is True
    assert plan.route_reason == "기본 벡터 질의"
