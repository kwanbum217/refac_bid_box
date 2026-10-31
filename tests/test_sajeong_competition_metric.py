"""사정률·경쟁률 평균 질의의 계획·SQL 집계·응답을 고정합니다.

사정률 원천은 bid_prearng_prices.sajeong_rate, 경쟁률은 낙찰 1건당 평균
참가업체 수(bid_results.raw_data.prtcptCnum)입니다. 정의·계산법 질문은 기존
설명 경로를 유지하고, 기간·분류 조건과 표본 수를 응답에 함께 표기합니다.
"""

from __future__ import annotations

from datetime import date, datetime

import pytest

from src.app.models.bids import BidResult
from src.app.models.prearng_prices import BidPrearngPrice
from src.rag import query_planning
from src.rag.answer_format import _build_single_metric_answer, _single_metric
from src.rag.data_gap_guard import detect_data_gap
from src.rag.query_planning import build_retrieval_plan
from src.rag.structured_data import retrieve_structured_data

_TODAY = date(2026, 10, 31)


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _TODAY


@pytest.fixture(autouse=True)
def _freeze_today(monkeypatch):
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


def _seed_prearng(session) -> None:
    rows = [
        (1, datetime(2026, 10, 5, 9), "Servc", 90.0),
        (2, datetime(2026, 10, 20, 9), "Servc", 80.0),
        (3, datetime(2026, 10, 31, 9), "Servc", 70.0),
        # 사정률이 NULL 인 행은 표본 수에서 빠집니다.
        (4, datetime(2026, 10, 15, 9), "Servc", None),
        # 창 밖
        (5, datetime(2026, 9, 1, 9), "Servc", 60.0),
        # 원천은 용역만 대상입니다.
        (6, datetime(2026, 10, 10, 9), "Cnstwk", 50.0),
    ]
    for row_id, opened_at, category, rate in rows:
        session.add(
            BidPrearngPrice(
                id=row_id,
                bid_ntce_no=f"PRE-{row_id}",
                category=category,
                sajeong_rate=rate,
                rl_openg_dt=opened_at,
            )
        )


def _seed_results(session) -> None:
    rows = [
        (101, datetime(2026, 10, 3, 9), "Servc", {"prtcptCnum": 3}),
        (102, datetime(2026, 10, 12, 9), "Servc", {"prtcptCnum": "6"}),
        (103, datetime(2026, 10, 25, 9), "Servc", {"prtcptCnum": 9}),
        # 키가 NULL·없음·비숫자·0 인 행은 표본에서 빠집니다.
        (104, datetime(2026, 10, 6, 9), "Servc", {"prtcptCnum": None}),
        (105, datetime(2026, 10, 7, 9), "Servc", {}),
        (106, datetime(2026, 10, 8, 9), "Servc", {"prtcptCnum": "확인불가"}),
        (107, datetime(2026, 10, 9, 9), "Servc", {"prtcptCnum": 0}),
        # 창 밖
        (108, datetime(2026, 9, 10, 9), "Servc", {"prtcptCnum": 100}),
        # 분류 조건 밖
        (109, datetime(2026, 10, 11, 9), "Cnstwk", {"prtcptCnum": 100}),
    ]
    for row_id, opened_at, category, raw_data in rows:
        session.add(
            BidResult(
                id=row_id,
                bid_ntce_no=f"RES-{row_id}",
                bid_ntce_ord="00",
                bidwinnr_nm=f"업체{row_id}",
                sucsf_bid_amt=1_000_000,
                sucsf_bid_rate=90.0,
                rl_openg_dt=opened_at,
                category=category,
                raw_data=raw_data,
            )
        )


@pytest.fixture
def metric_db(isolated_db):
    _seed_prearng(isolated_db)
    _seed_results(isolated_db)
    isolated_db.commit()
    return isolated_db


@pytest.mark.parametrize(
    ("query", "metric"),
    [
        ("최근 한 달 용역 사정률 평균 알려줘", "avg_sajeong_rate"),
        ("최근 한 달 평균 경쟁률 알려줘", "avg_participants"),
    ],
)
def test_metric_questions_carry_detail_metric(query: str, metric: str) -> None:
    plan = build_retrieval_plan(query)

    assert plan.use_sql is True
    assert plan.filters.get("metric") == metric
    assert detect_data_gap(query) is None


@pytest.mark.parametrize(
    "query",
    [
        "사정률이 뭐야?",
        "사정률 계산 방법 알려줘",
        "경쟁률 뜻",
    ],
)
def test_definition_questions_keep_existing_path(query: str) -> None:
    plan = build_retrieval_plan(query)

    assert "metric" not in plan.filters
    assert _single_metric(query.lower()) == ""
    assert detect_data_gap(query) is None


def test_winning_rate_metric_is_unchanged() -> None:
    plan = build_retrieval_plan("최근 한 달 용역 평균 낙찰률 알려줘")

    assert "metric" not in plan.filters
    assert _single_metric("최근 한 달 용역 평균 낙찰률 알려줘") == "avg_rate"


def test_sajeong_rate_aggregate_uses_source_window_and_category(metric_db) -> None:
    plan = build_retrieval_plan("최근 한 달 용역 사정률 평균 알려줘")

    result = retrieve_structured_data(metric_db, plan)
    stats = result["summary"]["sajeong_rate"]

    assert stats["average"] == pytest.approx(80.0)
    assert stats["sample_count"] == 3
    assert _build_single_metric_answer(plan, result).startswith(
        "2026-10-02 ~ 2026-10-31 용역 평균 사정률은 80.0000%입니다. 표본 3건입니다."
    )


def test_sajeong_rate_without_category_reports_service_source(metric_db) -> None:
    plan = build_retrieval_plan("최근 한 달 사정률 평균 알려줘")

    result = retrieve_structured_data(metric_db, plan)
    answer = _build_single_metric_answer(plan, result)

    assert result["summary"]["sajeong_rate"]["average"] == pytest.approx(80.0)
    assert result["summary"]["sajeong_rate"]["sample_count"] == 3
    assert "용역 분류만 제공되므로 용역 표본으로 계산했습니다" in answer


def test_sajeong_rate_explicit_non_service_category_reports_missing_source(metric_db) -> None:
    plan = build_retrieval_plan("최근 한 달 공사 사정률 평균 알려줘")

    result = retrieve_structured_data(metric_db, plan)
    answer = _build_single_metric_answer(plan, result)

    assert result["summary"]["sajeong_rate"]["average"] is None
    assert result["summary"]["sajeong_rate"]["sample_count"] == 0
    assert "용역 분류만 제공되어" in answer


def test_participants_aggregate_excludes_null_and_non_numeric(metric_db) -> None:
    plan = build_retrieval_plan("최근 한 달 용역 평균 경쟁률 알려줘")

    result = retrieve_structured_data(metric_db, plan)
    stats = result["summary"]["participants"]

    assert stats["average"] == pytest.approx(6.0)
    assert stats["sample_count"] == 3


def test_participants_answer_has_label_unit_samples_and_limit(metric_db) -> None:
    plan = build_retrieval_plan("최근 한 달 용역 평균 경쟁률 알려줘")

    result = retrieve_structured_data(metric_db, plan)
    answer = _build_single_metric_answer(plan, result)

    assert "평균 참가업체 수는 6.00곳입니다" in answer
    assert "표본 3건입니다" in answer
    assert "유찰 공고는 표본에 포함되지 않습니다" in answer
