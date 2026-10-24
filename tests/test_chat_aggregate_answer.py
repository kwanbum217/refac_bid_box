"""
tests/test_chat_aggregate_answer.py

축별 집계와 공고 건수 시계열의 직접 응답(LLM 미사용) 계약을 검증합니다.

표는 지표 하나만 냅니다. 공고 건수 질문에 낙찰 건수를 섞으면 S06 결함이
재발하므로, 시계열 딕셔너리의 bid_count 가 표에 나오지 않는지 확인합니다.
"""

from __future__ import annotations

from datetime import datetime

from src.app.models.bids import BidAnnouncement, BidResult
from src.rag.answer_format import (
    _build_axis_answer,
    _build_series_answer,
)
from src.rag.engine import HybridRAGEngine
from src.rag.query_planning import build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data


class _RecordingBackend:
    name = "recording"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, *args, **kwargs) -> str:
        self.calls += 1
        return "LLM 응답"


def _axis_structured_data() -> dict:
    return {
        "filters": {"group_by": "category", "metric": "avg_rate"},
        "summary": {
            "axis_breakdown": [
                {
                    "label": "용역",
                    "key": "Servc",
                    "announcement_count": 1022938,
                    "bid_count": 551246,
                    "avg_rate": 90.0146,
                    "sample_count": 551246,
                },
                {
                    "label": "외자",
                    "key": "Frgcpt",
                    "announcement_count": 11075,
                    "bid_count": 4092,
                    "avg_rate": None,
                    "sample_count": 0,
                },
            ],
            "aggregate_meta": {
                "group_by": "category",
                "metric": "avg_rate",
                "limit": 20,
                "truncated": False,
            },
        },
        "insufficiency_hints": [],
    }


def test_direct_axis_answer_renders_markdown_table_without_llm():
    """축 표는 백엔드를 부르지 않고 LLM 앞에서 만들어진다."""
    engine = HybridRAGEngine()
    backend = _RecordingBackend()
    engine._backend_resolved = True
    engine._backend = backend

    bundle = engine.get_answer_sync(
        "분류별 평균 낙찰률 알려줘",
        tool_context={"tool_results": {"bid_query": {"result": _axis_structured_data()}}},
    )

    assert backend.calls == 0
    assert "분류별 평균 낙찰률입니다." in bundle.answer
    assert "| 분류 | 평균 낙찰률 |" in bundle.answer
    assert "| 용역 | 90.0146% |" in bundle.answer
    assert "| 외자 | - |" in bundle.answer


def test_axis_answer_skips_when_breakdown_missing():
    plan = RetrievalPlan(filters={"group_by": "category", "metric": "avg_rate"})
    structured = {"summary": {"axis_breakdown": []}}

    assert _build_axis_answer(plan, structured) == ""


def test_quarter_series_announcement_metric_renders_announcement_count_only():
    """공고 건수 지표를 골랐으면 낙찰 건수는 표에 나오지 않습니다."""
    plan = RetrievalPlan(filters={"group_by": "time", "metric": "announcement_count"})
    structured = {
        "summary": {
            "time_series": [
                {
                    "label": "2026년 1분기",
                    "period": "quarter",
                    "avg_rate": 88.0,
                    "bid_count": 79981,
                    "announcement_count": 134037,
                    "ntce_count": 134037,
                },
                {
                    "label": "2026년 2분기",
                    "period": "quarter",
                    "avg_rate": 89.0,
                    "bid_count": 85820,
                    "announcement_count": 135823,
                    "ntce_count": 135823,
                },
            ],
            "aggregate_meta": {"group_by": "time", "metric": "announcement_count"},
        }
    }

    answer = _build_series_answer(plan, structured)

    assert "분기별 공고 건수입니다." in answer
    assert "| 분기 | 공고 건수 |" in answer
    assert "134,037" in answer
    assert "135,823" in answer
    assert "79,981" not in answer
    assert "85,820" not in answer
    assert "낙찰 건수" not in answer


def test_series_answer_skips_when_metric_missing():
    """지표 기록이 없는 기존 추세 응답은 건드리지 않습니다."""
    plan = RetrievalPlan(filters={"analysis_mode": "trend"})
    structured = {
        "summary": {
            "time_series": [
                {
                    "label": "2026-04",
                    "period": "month",
                    "avg_rate": 90.0,
                    "bid_count": 10,
                }
            ]
        }
    }

    assert _build_series_answer(plan, structured) == ""


def test_quarter_announcement_count_end_to_end_uses_announcement_column(isolated_db):
    """S06 질문은 구조화 조회에서도 공고 건수 열만 표로 냅니다."""
    for index in range(3):
        isolated_db.add(
            BidAnnouncement(
                bid_ntce_no=f"ANN-{index}",
                bid_ntce_ord="000",
                bid_ntce_nm="용역 공고",
                dminstt_nm="서울특별시",
                bid_ntce_dt=datetime(2026, 2, index + 1),
                category="Servc",
            )
        )
    for index in range(2):
        isolated_db.add(
            BidAnnouncement(
                bid_ntce_no=f"ANN-Q2-{index}",
                bid_ntce_ord="000",
                bid_ntce_nm="용역 공고",
                dminstt_nm="서울특별시",
                bid_ntce_dt=datetime(2026, 5, index + 1),
                category="Servc",
            )
        )
    for index in range(9):
        isolated_db.add(
            BidResult(
                bid_ntce_no=f"RES-{index}",
                bid_ntce_ord="00",
                bid_ntce_nm="용역 공고",
                dminstt_nm="서울특별시",
                bidwinnr_nm="업체",
                sucsf_bid_rate=90.0,
                rl_openg_dt=datetime(2026, 2, index + 1),
                category="Servc",
            )
        )
    for index in range(8):
        isolated_db.add(
            BidResult(
                bid_ntce_no=f"RES-Q2-{index}",
                bid_ntce_ord="00",
                bid_ntce_nm="용역 공고",
                dminstt_nm="서울특별시",
                bidwinnr_nm="업체",
                sucsf_bid_rate=90.0,
                rl_openg_dt=datetime(2026, 5, index + 1),
                category="Servc",
            )
        )
    isolated_db.commit()

    plan = build_retrieval_plan("2026년 분기별 공고 건수 추이 알려줘")
    summary = retrieve_structured_data(isolated_db, plan)["summary"]

    assert summary["aggregate_meta"]["group_by"] == "time"
    assert summary["aggregate_meta"]["metric"] == "announcement_count"
    assert summary["time_series"][0]["bid_count"] == 9
    assert summary["time_series"][0]["announcement_count"] == 3

    answer = _build_series_answer(plan, {"summary": summary})
    assert "| 2026년 1분기 | 3 |" in answer
    assert "| 2026년 2분기 | 2 |" in answer
    assert "9" not in answer
    assert "8" not in answer
