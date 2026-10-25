"""
tests/test_statistics_window_default.py

기간을 말하지 않은 통계 질의가 진입 경로와 무관하게 최근 5년 기본 창을 쓰는지
고정합니다. 도구 경로(bid_query_tool)와 엔진 직접 경로(_prepare_context)를 같은
질문으로 실행해 해석된 창과 응답 안내를 비교합니다.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from src.rag import query_planning
from src.rag import structured_data as structured_data_module
from src.rag.answer_format import _build_single_metric_answer, _winner_axis_caption
from src.rag.engine import HybridRAGEngine, get_bidding_statistics
from src.rag.query_planning import (
    apply_default_statistics_window,
    build_retrieval_plan,
)
from src.rag.schemas import DEFAULT_STATISTICS_WINDOW_YEARS, RetrievalPlan
from src.rag.snapshots import _extract_statistical_snapshot
from src.rag.structured_data import (
    _build_time_series,
    _resolve_time_series_granularity,
    _resolve_window,
    _snapshot_scope,
)

_TODAY = date(2026, 10, 24)
_WINDOW_START = "2021-10-26"
_WINDOW_END = "2026-10-24"
_STAT_QUERY = "지역별 공고 건수 알려줘"
_MONTHLY_QUERY = "월별 공고 건수 추이 알려줘"
_SINGLE_METRIC_QUERY = "전체 공고 건수 알려줘"
_RECENT_FIVE_YEARS_QUERY = "최근 5년 공고 건수 알려줘"
_QUARTER_QUERY = "분기별 공고 건수 알려줘"


class _FrozenDate(date):
    @classmethod
    def today(cls) -> date:
        return _TODAY


@pytest.fixture(autouse=True)
def frozen_today(monkeypatch):
    """기간 해석과 분기 기본값이 실행 날짜에 흔들리지 않도록 기준일을 고정합니다."""
    monkeypatch.setattr(structured_data_module, "date", _FrozenDate)
    monkeypatch.setattr(query_planning, "date", _FrozenDate)


def _structured_payload(
    filters: dict[str, Any], summary: dict[str, Any] | None = None
) -> dict[str, Any]:
    base_summary: dict[str, Any] = {
        "total_bids": 0,
        "announcement_count": 0,
        "average_winning_rate": 0.0,
        "top_winners": [],
        "top_institutions": [],
        "top_announcements": [],
        "sample_announcements": [],
        "recent_results": [],
        "latest_available_result_at": None,
        "time_series": [],
    }
    base_summary.update(summary or {})
    return {
        "filters": dict(filters),
        "summary": base_summary,
        "insufficiency_hints": [],
    }


def _run_tool(
    monkeypatch,
    query: str,
    *,
    summary: dict[str, Any] | None = None,
    **kwargs: Any,
) -> tuple[dict[str, Any], RetrievalPlan]:
    """도구 경로를 DB 없이 실행하고 실제로 조회에 쓰인 계획을 돌려줍니다."""
    from src.app.services.tools import bid_query_tool

    captured: dict[str, RetrievalPlan] = {}

    def fake_retrieve(db, plan: RetrievalPlan) -> dict[str, Any]:
        captured["plan"] = plan
        return _structured_payload(plan.filters or {}, summary)

    monkeypatch.setattr(bid_query_tool, "retrieve_structured_data", fake_retrieve)
    result = bid_query_tool.execute(db=None, query=query, **kwargs)
    return result, captured["plan"]


def _run_engine(monkeypatch, query: str) -> tuple[Any, RetrievalPlan]:
    """엔진 직접 SQL 경로를 DB 없이 실행하고 그 계획을 돌려줍니다."""
    import src.rag.engine as engine_module

    captured: dict[str, RetrievalPlan] = {}

    def fake_retrieve(db, plan: RetrievalPlan) -> dict[str, Any]:
        captured["plan"] = plan
        return _structured_payload(plan.filters or {})

    monkeypatch.setattr(engine_module, "retrieve_structured_data", fake_retrieve)
    prepared = HybridRAGEngine()._prepare_context(query, db=object())
    return prepared, captured["plan"]


def test_tool_and_engine_share_default_window(monkeypatch):
    """같은 통계 질의는 도구 경로와 엔진 경로 모두 최근 5년 창을 씁니다."""
    _, tool_plan = _run_tool(monkeypatch, _STAT_QUERY)
    _, engine_plan = _run_engine(monkeypatch, _STAT_QUERY)

    assert tool_plan.filters["relative_years"] == DEFAULT_STATISTICS_WINDOW_YEARS
    assert engine_plan.filters["relative_years"] == DEFAULT_STATISTICS_WINDOW_YEARS
    assert _resolve_window(tool_plan.filters) == _resolve_window(engine_plan.filters)

    window_start, window_end = _resolve_window(engine_plan.filters)
    assert window_start is not None
    assert window_end is not None
    assert window_start.date().isoformat() == _WINDOW_START
    assert window_end.date().isoformat() == _WINDOW_END


def test_explicit_period_wins_over_default(monkeypatch):
    """명시 기간이 있으면 기본 창을 만들지 않습니다."""
    original = {"date_from": "2026-01-01", "date_to": "2026-03-31"}
    assert apply_default_statistics_window(original) == original
    assert original == {"date_from": "2026-01-01", "date_to": "2026-03-31"}

    _, tool_plan = _run_tool(monkeypatch, _STAT_QUERY, date_from="2026-01-01", date_to="2026-03-31")
    assert tool_plan.filters["date_from"] == "2026-01-01"
    assert tool_plan.filters["date_to"] == "2026-03-31"
    assert "relative_years" not in tool_plan.filters

    _, engine_plan = _run_engine(monkeypatch, "2026년 1분기 공고 건수 알려줘")
    assert engine_plan.filters["date_from"] == "2026-01-01"
    assert engine_plan.filters["date_to"] == "2026-03-31"
    assert "relative_years" not in engine_plan.filters


def test_quarter_bucket_without_year_keeps_four_quarters(monkeypatch, isolated_db):
    """연도 없는 분기 질의는 기본 창을 주입하지 않고 올해 4분기를 유지합니다."""
    monkeypatch.setattr(structured_data_module, "_cached_rows", lambda db, stmt: [])

    _, tool_plan = _run_tool(monkeypatch, _QUARTER_QUERY, years=5)
    assert tool_plan.filters["time_bucket"] == "quarter"
    assert "relative_years" not in tool_plan.filters
    assert _resolve_window(tool_plan.filters) == (None, None)

    series = _build_time_series(isolated_db, tool_plan, [])
    assert [item["label"] for item in series] == [
        "2026년 1분기",
        "2026년 2분기",
        "2026년 3분기",
        "2026년 4분기",
    ]

    _, engine_plan = _run_engine(monkeypatch, _QUARTER_QUERY)
    assert engine_plan.filters["time_bucket"] == "quarter"
    assert "relative_years" not in engine_plan.filters


def test_default_window_hint_is_not_whole_period(monkeypatch):
    """기본 창이 걸린 응답 안내는 전체 기준이 아니라 최근 5년 기준입니다."""
    result, _ = _run_tool(monkeypatch, _STAT_QUERY)
    tool_hints = "\n".join(result["retrieval_plan"]["insufficiency_hints"])
    assert "전체 기준" not in tool_hints
    assert "최근 5년" in tool_hints

    prepared, engine_plan = _run_engine(monkeypatch, _STAT_QUERY)
    engine_hints = "\n".join(engine_plan.insufficiency_hints)
    assert "전체 기준" not in engine_hints
    assert "최근 5년" in engine_hints
    assert "전체 기준" not in "\n".join(prepared.provenance.insufficiency_hints)

    tool_context = {
        "tool_results": {"bid_query": {"result": _structured_payload({"relative_years": 5})}}
    }
    prepared_tool = HybridRAGEngine()._prepare_context(_STAT_QUERY, tool_context=tool_context)
    tool_engine_hints = "\n".join(prepared_tool.provenance.insufficiency_hints)
    assert "전체 기준" not in tool_engine_hints
    assert "최근 5년" in tool_engine_hints

    _, zero_plan = _run_tool(monkeypatch, _STAT_QUERY, years=0)
    assert any("전체 기준" in hint for hint in zero_plan.insufficiency_hints), (
        "명시적 전체 기간(years=0)은 전체 기준 안내를 유지해야 합니다."
    )


def test_years_zero_keeps_whole_period(monkeypatch):
    """years=0 은 명시적 전체 기간으로 남고 스냅샷 경로도 유지됩니다."""
    import src.rag.engine as engine_module

    captured: dict[str, RetrievalPlan] = {}

    def fake_retrieve(db, plan: RetrievalPlan) -> dict[str, Any]:
        captured["plan"] = plan
        return _structured_payload(plan.filters or {})

    monkeypatch.setattr(engine_module, "retrieve_structured_data", fake_retrieve)

    get_bidding_statistics(db=object(), years=0)

    plan = captured["plan"]
    assert "relative_years" in plan.filters
    assert plan.filters["relative_years"] == 0
    assert plan.time_bias == ""
    assert _snapshot_scope(plan) == ""


def test_build_retrieval_plan_does_not_inject_default_window():
    """하위 계층의 계획 수립은 기본 창을 만들지 않습니다."""
    plan = build_retrieval_plan(_STAT_QUERY)

    assert "relative_years" not in plan.filters
    assert "date_from" not in plan.filters
    assert plan.insufficiency_hints == [
        "기간 조건이 명시되지 않아 전체 기준 통계를 사용할 수 있습니다."
    ]


def test_snapshot_scope_is_unchanged_by_entry_default(monkeypatch):
    """진입점이 만든 창은 스냅샷을 배제하고, 직접 만든 빈 계획은 전체 스냅샷입니다."""
    _, tool_plan = _run_tool(monkeypatch, _STAT_QUERY)

    assert _snapshot_scope(tool_plan) is None
    assert _snapshot_scope(RetrievalPlan(use_sql=True, filters={})) == ""


def test_recent_five_years_is_explicit_window(monkeypatch):
    """'최근 5년' 은 파서가 만든 명시 창이라 기본 창 주입 대상이 아닙니다."""
    _, tool_plan = _run_tool(monkeypatch, _RECENT_FIVE_YEARS_QUERY)

    assert tool_plan.filters["date_from"] == _WINDOW_START
    assert tool_plan.filters["date_to"] == _WINDOW_END
    assert "relative_years" not in tool_plan.filters

    _, engine_plan = _run_engine(monkeypatch, _RECENT_FIVE_YEARS_QUERY)
    assert engine_plan.filters["date_from"] == _WINDOW_START
    assert "relative_years" not in engine_plan.filters


def test_monthly_trend_uses_five_year_default(monkeypatch):
    """월별 추이는 두 경로 모두 최근 5년 월 버킷 창을 씁니다."""
    _, tool_plan = _run_tool(monkeypatch, _MONTHLY_QUERY)
    _, engine_plan = _run_engine(monkeypatch, _MONTHLY_QUERY)

    for plan in (tool_plan, engine_plan):
        assert plan.filters["relative_years"] == DEFAULT_STATISTICS_WINDOW_YEARS
        assert _resolve_window(plan.filters) == _resolve_window(tool_plan.filters)
        assert _resolve_time_series_granularity(plan) == "month"

    window_start, window_end = _resolve_window(tool_plan.filters)
    assert window_start is not None
    assert window_end is not None
    assert (window_end - window_start).days == (365 * DEFAULT_STATISTICS_WINDOW_YEARS) - 1


def test_single_metric_answer_shows_default_window(monkeypatch):
    """단일 지표 직접 응답과 적용 조건 줄에 실제 기본 창이 드러납니다."""
    _, tool_plan = _run_tool(
        monkeypatch, _SINGLE_METRIC_QUERY, summary={"announcement_count": 10165}
    )
    structured = _structured_payload(tool_plan.filters, {"announcement_count": 10165})

    answer = _build_single_metric_answer(tool_plan, structured)
    assert "전체 기간" not in answer
    assert "최근 5년" in answer
    assert "10,165건" in answer

    snapshot = _extract_statistical_snapshot(structured)
    assert "- 적용 조건: 기간 최근 5년, 분류 전체" in snapshot

    caption = _winner_axis_caption(
        tool_plan,
        {"filters": {}},
        "낙찰 건수",
        {"window": {"date_from": None, "date_to": None}},
    )
    assert "전체 기간" not in caption
    assert "최근 5년 기준" in caption
