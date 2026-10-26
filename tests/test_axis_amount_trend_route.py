"""
tests/test_axis_amount_trend_route.py

축별 낙찰 금액 순위와 동향 추이 질의의 라우팅·집계를 검증합니다.

축이 정해진 금액 질의는 낙찰 결과 테이블의 sucsf_bid_amt 합계로 SQL 집계하고,
"동향" 은 기존 시계열 추이 경로로 보냅니다. 기존 건수·낙찰률 축과 설명형
질의의 경로는 바뀌지 않아야 합니다.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta

import pytest
from sqlalchemy import func, select

from src.app.core.cache import cache
from src.app.models.bids import BidResult
from src.rag.answer_format import _build_axis_answer, _build_series_answer
from src.rag.query_planning import DEFAULT_GROUP_LIMIT, build_retrieval_plan
from src.rag.structured_data import retrieve_structured_data


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


def _seed_result(
    session,
    *,
    row_id: int,
    institution: str = "서울특별시",
    winner: str = "가나건설",
    amount: int = 1000,
    opened_at: datetime,
    category: str = "Cnstwk",
    rate: float | None = 90.0,
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"AMT-{row_id}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"공고 {row_id}",
            dminstt_nm=institution,
            bidwinnr_nm=winner,
            sucsf_bid_amt=amount,
            sucsf_bid_rate=rate,
            rl_openg_dt=opened_at,
            category=category,
        )
    )


@pytest.mark.parametrize(
    ("query", "axis"),
    [
        ("수요기관별 낙찰 금액 상위는 어디야", "institution"),
        ("업체별 낙찰 금액 순위", "winner"),
        ("분류별 낙찰 금액", "category"),
        ("지역별 낙찰 금액 상위", "region"),
    ],
)
def test_amount_axis_queries_route_to_sql_award_amount(query, axis):
    """축과 금액 표지가 있으면 공고 건수가 아니라 낙찰 금액 합계로 집계합니다."""
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters.get("group_by") == axis
    assert plan.filters.get("metric") == "award_amount"
    assert plan.filters.get("group_limit") == DEFAULT_GROUP_LIMIT


def test_institution_amount_ranking_matches_direct_sum(isolated_db):
    """기관별 표 1위와 값이 sucsf_bid_amt 직접 합계와 같습니다."""
    opened = datetime(2026, 5, 1, 9, 0, 0)
    _seed_result(isolated_db, row_id=1, institution="서울특별시", amount=1000, opened_at=opened)
    _seed_result(isolated_db, row_id=2, institution="서울특별시", amount=2000, opened_at=opened)
    _seed_result(isolated_db, row_id=3, institution="부산광역시", amount=5000, opened_at=opened)
    _seed_result(isolated_db, row_id=4, institution="대구광역시", amount=7000, opened_at=opened)
    _seed_result(
        isolated_db, row_id=5, institution="깨진\ufffd기관", amount=99999, opened_at=opened
    )
    isolated_db.commit()

    plan = build_retrieval_plan("수요기관별 낙찰 금액 상위는 어디야")
    result = retrieve_structured_data(isolated_db, plan)
    breakdown = result["summary"]["axis_breakdown"]

    direct_rows = isolated_db.execute(
        select(BidResult.dminstt_nm, func.sum(BidResult.sucsf_bid_amt))
        .where(BidResult.dminstt_nm.is_not(None), BidResult.dminstt_nm != "")
        .group_by(BidResult.dminstt_nm)
    ).all()
    direct_totals = {
        str(name): int(total or 0) for name, total in direct_rows if "\ufffd" not in str(name)
    }
    top_name = max(direct_totals, key=lambda name: direct_totals[name])

    assert breakdown[0]["label"] == top_name
    assert breakdown[0]["award_amount"] == direct_totals[top_name]
    assert [item["label"] for item in breakdown] == ["대구광역시", "부산광역시", "서울특별시"]

    answer = _build_axis_answer(plan, result)
    assert "기관별 낙찰 금액 합계입니다." in answer
    assert "| 기관 | 낙찰 금액 합계 |" in answer
    assert f"| {top_name} | {direct_totals[top_name]:,} |" in answer


def test_winner_amount_ranking_orders_by_sum_and_excludes_corrupted(isolated_db):
    """업체별 금액 순위는 합계 내림차순이고 손상·빈 업체명은 빠집니다."""
    opened = datetime(2026, 5, 1, 9, 0, 0)
    _seed_result(isolated_db, row_id=1, winner="가나건설", amount=2000, opened_at=opened)
    _seed_result(isolated_db, row_id=2, winner="가나건설", amount=1000, opened_at=opened)
    _seed_result(isolated_db, row_id=3, winner="다라건설", amount=5000, opened_at=opened)
    _seed_result(isolated_db, row_id=4, winner="깨진\ufffd업체", amount=99999, opened_at=opened)
    _seed_result(isolated_db, row_id=5, winner="", amount=88888, opened_at=opened)
    isolated_db.commit()

    plan = build_retrieval_plan("업체별 낙찰 금액 순위")
    assert plan.filters.get("group_by") == "winner"
    assert plan.filters.get("metric") == "award_amount"

    result = retrieve_structured_data(isolated_db, plan)
    breakdown = result["summary"]["axis_breakdown"]

    assert [(item["label"], item["award_amount"]) for item in breakdown] == [
        ("다라건설", 5000),
        ("가나건설", 3000),
    ]

    answer = _build_axis_answer(plan, result)
    assert "| 업체 | 낙찰 금액 합계 |" in answer
    assert "| 다라건설 | 5,000 |" in answer


def test_category_amount_ranking_sums_result_table(isolated_db):
    """분류별 낙찰 금액은 공고 테이블이 아니라 낙찰 결과 테이블에서 합산합니다."""
    opened = datetime(2026, 5, 1, 9, 0, 0)
    _seed_result(isolated_db, row_id=1, category="Cnstwk", amount=3000, opened_at=opened)
    _seed_result(isolated_db, row_id=2, category="Servc", amount=1000, opened_at=opened)
    _seed_result(isolated_db, row_id=3, category="Servc", amount=500, opened_at=opened)
    isolated_db.commit()

    plan = build_retrieval_plan("분류별 낙찰 금액")
    result = retrieve_structured_data(isolated_db, plan)
    breakdown = result["summary"]["axis_breakdown"]

    assert [(item["label"], item["award_amount"]) for item in breakdown] == [
        ("건설", 3000),
        ("용역", 1500),
    ]


def test_institution_rate_axis_keeps_avg_rate(isolated_db):
    """낙찰률 표지가 있는 축 질의는 기존 평균 낙찰률 지표를 유지합니다."""
    plan = build_retrieval_plan("기관별 평균 낙찰률 상위")

    assert plan.use_sql is True
    assert plan.filters.get("group_by") == "institution"
    assert plan.filters.get("metric") == "avg_rate"

    opened = datetime(2026, 5, 1, 9, 0, 0)
    _seed_result(isolated_db, row_id=1, institution="서울특별시", rate=80.0, opened_at=opened)
    _seed_result(isolated_db, row_id=2, institution="서울특별시", rate=90.0, opened_at=opened)
    isolated_db.commit()

    breakdown = retrieve_structured_data(isolated_db, plan)["summary"]["axis_breakdown"]
    assert breakdown[0]["avg_rate"] == pytest.approx(85.0, rel=1e-4)
    assert breakdown[0]["award_amount"] is None


def test_institution_bid_count_axis_keeps_bid_count_and_limit():
    """낙찰 건수 축 질의는 기존 지표와 요청 행 수를 그대로 유지합니다."""
    plan = build_retrieval_plan("기관별 낙찰 건수 상위 5곳")

    assert plan.use_sql is True
    assert plan.filters.get("group_by") == "institution"
    assert plan.filters.get("metric") == "bid_count"
    assert plan.filters.get("group_limit") == 5


def test_construction_recent_award_trend_uses_series_path(isolated_db):
    """동향 질의는 분류·기간 조건을 유지한 채 낙찰 건수 시계열로 답합니다."""
    opened = datetime.combine(date.today() - timedelta(days=1), time(9, 0))
    _seed_result(isolated_db, row_id=1, category="Cnstwk", opened_at=opened)
    _seed_result(isolated_db, row_id=2, category="Cnstwk", opened_at=opened)
    _seed_result(isolated_db, row_id=3, category="Servc", opened_at=opened)
    isolated_db.commit()

    plan = build_retrieval_plan("공사 부문 최근 낙찰 동향 알려줘")

    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.filters.get("analysis_mode") == "trend"
    assert plan.filters.get("category") == "Cnstwk"
    assert plan.filters.get("metric") == "bid_count"

    result = retrieve_structured_data(isolated_db, plan)
    series = result["summary"]["time_series"]
    assert sum(item["bid_count"] for item in series) == 2

    answer = _build_series_answer(plan, result)
    assert answer.startswith("일별 낙찰 건수 추이입니다.")


def test_service_rate_trend_keeps_avg_rate_metric(isolated_db):
    """낙찰률 동향은 평균 낙찰률 지표의 시계열로 답합니다."""
    opened = datetime(2026, 5, 1, 9, 0, 0)
    _seed_result(isolated_db, row_id=1, category="Servc", rate=80.0, opened_at=opened)
    _seed_result(isolated_db, row_id=2, category="Servc", rate=90.0, opened_at=opened)
    isolated_db.commit()

    plan = build_retrieval_plan("용역 낙찰률 동향")

    assert plan.use_sql is True
    assert plan.filters.get("analysis_mode") == "trend"
    assert plan.filters.get("category") == "Servc"
    assert plan.filters.get("metric") == "avg_rate"

    result = retrieve_structured_data(isolated_db, plan)
    answer = _build_series_answer(plan, result)
    assert "평균 낙찰률 추이입니다." in answer
    assert "85.00%" in answer


def test_explanatory_trend_word_is_not_trend_query():
    """뜻을 묻는 설명형 질의는 동향 추이 경로로 보내지 않습니다."""
    plan = build_retrieval_plan("동향이 무슨 뜻이야")

    assert plan.use_sql is False
    assert "analysis_mode" not in plan.filters
