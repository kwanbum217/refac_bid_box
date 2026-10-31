"""금액대별 집계 축을 계획·경계·조회·응답 네 층에서 고정합니다.

금액대별 질문은 group_by 를 amount_band 로 기록하고, 공고 건수는 추정가격이
없을 때 기초금액을 쓰며, 두 값이 모두 없으면 금액 미상으로 셉니다. 경계값
1억·5억·10억은 상위 구간에 들어가고 표는 경계 오름차순을 유지합니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidResult
from src.rag.answer_format import _build_axis_answer
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import (
    AMOUNT_BAND_LABELS,
    AMOUNT_BAND_UNKNOWN_LABEL,
    retrieve_structured_data,
)

WINDOW = {"date_from": "2026-01-01", "date_to": "2026-12-31"}
SEEDED_AT = datetime(2026, 5, 1, 9, 0, 0)


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


def _seed_announcement(
    session,
    row_id: int,
    *,
    presmpt_prce: int | None,
    base_amount: int | None = None,
) -> None:
    session.add(
        BidAnnouncement(
            id=row_id,
            bid_ntce_no=f"BAND-ANN-{row_id:03d}",
            bid_ntce_ord="000",
            bid_ntce_nm=f"금액 구간 공고 {row_id}",
            dminstt_nm="서울특별시",
            bid_ntce_dt=SEEDED_AT,
            category="Servc",
            presmpt_prce=presmpt_prce,
            base_amount=base_amount,
            raw_data=None,
        )
    )


def _seed_result(
    session,
    row_id: int,
    *,
    sucsf_bid_amt: int | None,
    rate: float | None = 90.0,
) -> None:
    session.add(
        BidResult(
            id=row_id,
            bid_ntce_no=f"BAND-RES-{row_id:03d}",
            bid_ntce_ord="00",
            bid_ntce_nm=f"금액 구간 낙찰 {row_id}",
            dminstt_nm="서울특별시",
            bidwinnr_nm=f"업체{row_id}",
            sucsf_bid_amt=sucsf_bid_amt,
            sucsf_bid_rate=rate,
            rl_openg_dt=SEEDED_AT,
            category="Servc",
        )
    )


def test_amount_band_question_plan_sets_axis_and_metric():
    """문제 발화가 amount_band 축과 공고 건수 지표로 계획됩니다."""
    plan = build_retrieval_plan("금액대별 용역 공고 건수 보여줘")

    assert plan.use_sql is True
    assert plan.use_vector is False
    assert plan.route_reason == "정형 통계 질의"
    assert plan.filters.get("category") == "Servc"
    assert plan.filters.get("group_by") == "amount_band"
    assert plan.filters.get("metric") == "announcement_count"
    assert plan.filters.get("group_limit") == 20


@pytest.mark.parametrize(
    "query",
    [
        "금액대별 용역 공고 건수 보여줘",
        "금액별 공고 건수 알려줘",
        "가격대별 공고 건수",
        "규모별 공고 건수",
        "금액 구간별 공고 건수",
        "금액구간별 공고 건수",
    ],
)
def test_amount_band_markers_set_group_by(query: str):
    """금액대·금액·가격대·규모 표지가 모두 같은 축으로 묶입니다."""
    filters = build_retrieval_plan(query).filters

    assert filters.get("group_by") == "amount_band"
    assert filters.get("metric") == "announcement_count"


@pytest.mark.parametrize(
    ("query", "axis"),
    [
        ("분류별 공고 건수", "category"),
        ("기관별 낙찰 건수", "institution"),
        ("지역별 공고 건수", "region"),
        ("업체별 낙찰 건수", "winner"),
    ],
)
def test_other_axes_keep_their_group_by(query: str, axis: str):
    """기존 축 판정은 금액 축 추가 뒤에도 바뀌지 않습니다."""
    assert build_retrieval_plan(query).filters.get("group_by") == axis


def test_amount_band_boundaries_and_amount_basis(isolated_db):
    """경계값·기초금액 대체·둘 다 NULL 을 구간별로 셉니다."""
    seeded = (
        (1, 0, None),
        (2, 99_999_999, None),
        (3, 100_000_000, None),
        (4, 499_999_999, None),
        (5, 500_000_000, None),
        (6, 999_999_999, None),
        (7, 1_000_000_000, None),
        # 추정가격이 없으면 기초금액으로 구간을 정합니다.
        (8, None, 200_000_000),
        # 추정가격이 있으면 기초금액이 더 커도 무시합니다.
        (9, 50_000_000, 700_000_000),
        # 둘 다 없으면 금액 미상입니다.
        (10, None, None),
    )
    for row_id, presmpt_prce, base_amount in seeded:
        _seed_announcement(
            isolated_db,
            row_id,
            presmpt_prce=presmpt_prce,
            base_amount=base_amount,
        )
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={
            **WINDOW,
            "category": "Servc",
            "group_by": "amount_band",
            "metric": "announcement_count",
        },
    )
    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    assert summary["aggregate_meta"]["group_by"] == "amount_band"
    assert [item["label"] for item in summary["axis_breakdown"]] == [
        *AMOUNT_BAND_LABELS,
        AMOUNT_BAND_UNKNOWN_LABEL,
    ]
    counts = {item["label"]: item["announcement_count"] for item in summary["axis_breakdown"]}
    assert counts == {
        "1억 미만": 3,
        "1억~5억": 3,
        "5억~10억": 2,
        "10억 이상": 1,
        "금액 미상": 1,
    }


def test_amount_band_result_metrics_use_winning_amount(isolated_db):
    """낙찰 건수·낙찰률 축은 낙찰금액 기준으로 같은 구간을 씁니다."""
    _seed_result(isolated_db, row_id=1, sucsf_bid_amt=99_999_999)
    _seed_result(isolated_db, row_id=2, sucsf_bid_amt=100_000_000)
    _seed_result(isolated_db, row_id=3, sucsf_bid_amt=1_000_000_000)
    _seed_result(isolated_db, row_id=4, sucsf_bid_amt=None)
    isolated_db.commit()

    plan = RetrievalPlan(
        use_sql=True,
        filters={
            **WINDOW,
            "category": "Servc",
            "group_by": "amount_band",
            "metric": "bid_count",
        },
    )
    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    counts = {item["label"]: item["bid_count"] for item in summary["axis_breakdown"]}
    assert counts == {
        "1억 미만": 1,
        "1억~5억": 1,
        "5억~10억": 0,
        "10억 이상": 1,
        "금액 미상": 1,
    }


def test_amount_band_answer_keeps_bucket_order_and_ratio():
    """응답 표는 네 구간을 경계 순서로 내고 비율과 기준 문장을 붙입니다."""
    plan = RetrievalPlan(filters={"group_by": "amount_band", "metric": "announcement_count"})
    structured = {
        "summary": {
            "axis_breakdown": [
                {"label": "1억 미만", "key": "1억 미만", "announcement_count": 6},
                {"label": "1억~5억", "key": "1억~5억", "announcement_count": 3},
                {"label": "5억~10억", "key": "5억~10억", "announcement_count": 1},
                {"label": "10억 이상", "key": "10억 이상", "announcement_count": 0},
            ],
            "aggregate_meta": {
                "group_by": "amount_band",
                "metric": "announcement_count",
                "limit": 20,
                "truncated": False,
            },
        }
    }

    answer = _build_axis_answer(plan, structured)

    assert answer.splitlines()[0] == "금액대별 공고 건수입니다."
    assert "| 금액대 | 공고 건수 | 비율 |" in answer
    positions = [
        answer.index(f"| {label} |") for label in ("1억 미만", "1억~5억", "5억~10억", "10억 이상")
    ]
    assert positions == sorted(positions)
    assert "| 1억 미만 | 6 | 60.00% |" in answer
    assert "| 1억~5억 | 3 | 30.00% |" in answer
    assert "| 5억~10억 | 1 | 10.00% |" in answer
    assert "| 10억 이상 | 0 | 0.00% |" in answer
    assert "구간 기준 금액은 공고 추정가격이며, 값이 없으면 기초금액을 사용합니다." in answer
    assert "상위 4건만 표시했습니다." not in answer


def test_amount_band_result_answer_states_winning_amount_basis():
    """낙찰 지표 표는 기준 금액이 낙찰금액임을 밝힙니다."""
    plan = RetrievalPlan(filters={"group_by": "amount_band", "metric": "bid_count"})
    structured = {
        "summary": {
            "axis_breakdown": [
                {"label": "1억 미만", "key": "1억 미만", "bid_count": 2},
                {"label": "1억~5억", "key": "1억~5억", "bid_count": 0},
                {"label": "5억~10억", "key": "5억~10억", "bid_count": 0},
                {"label": "10억 이상", "key": "10억 이상", "bid_count": 1},
            ],
            "aggregate_meta": {
                "group_by": "amount_band",
                "metric": "bid_count",
                "limit": 20,
                "truncated": False,
            },
        }
    }

    answer = _build_axis_answer(plan, structured)

    assert answer.splitlines()[0] == "금액대별 낙찰 건수입니다."
    assert "구간 기준 금액은 낙찰금액입니다." in answer
    assert "추정가격" not in answer
