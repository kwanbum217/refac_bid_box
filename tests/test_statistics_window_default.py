"""
tests/test_statistics_window_default.py

기간을 말하지 않은 통계 질의의 기본 창이 한 곳에서 정해지고, 진입점 세 곳이
같은 값을 쓰는지 검증합니다. 플랜 단계(build_retrieval_plan)는 창을 주입하지
않아 스냅샷 범위 계약을 지켜야 합니다.
"""

from __future__ import annotations

from src.app.services.tools import bid_query_tool
from src.rag import engine
from src.rag.query_planning import apply_default_statistics_window, build_retrieval_plan
from src.rag.schemas import DEFAULT_STATISTICS_WINDOW_YEARS
from src.rag.structured_data import _resolve_window


def _fake_retrieve(captured: dict):
    def retrieve(_session, plan):
        captured["filters"] = dict(plan.filters or {})
        return {"filters": dict(plan.filters or {}), "summary": {}}

    return retrieve


def _capture_tool_filters(monkeypatch, **kwargs) -> dict:
    captured: dict = {}
    monkeypatch.setattr(bid_query_tool, "retrieve_structured_data", _fake_retrieve(captured))
    bid_query_tool.execute(db=None, query="전체 공고 건수 알려줘", **kwargs)
    return captured["filters"]


def _capture_prepare_context_filters(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(engine, "retrieve_structured_data", _fake_retrieve(captured))
    engine.HybridRAGEngine()._prepare_context("전체 공고 건수 알려줘", db=object())
    return captured["filters"]


def _capture_statistics_filters(monkeypatch) -> dict:
    captured: dict = {}
    monkeypatch.setattr(engine, "retrieve_structured_data", _fake_retrieve(captured))
    engine.get_bidding_statistics(object(), query="전체 공고 건수 알려줘")
    return captured["filters"]


def test_entry_points_share_default_window(monkeypatch):
    """도구·엔진 직접 조회·통계 함수가 같은 기본 창을 씁니다."""
    tool_filters = _capture_tool_filters(monkeypatch)
    prepare_filters = _capture_prepare_context_filters(monkeypatch)
    statistics_filters = _capture_statistics_filters(monkeypatch)

    for filters in (tool_filters, prepare_filters, statistics_filters):
        assert filters.get("relative_years") == DEFAULT_STATISTICS_WINDOW_YEARS
        assert filters.get("date_from") in (None, "")
        assert filters.get("date_to") in (None, "")

    windows = {
        _resolve_window(filters) for filters in (tool_filters, prepare_filters, statistics_filters)
    }
    assert len(windows) == 1


def test_explicit_period_wins_over_default_window(monkeypatch):
    """명시한 기간이 기본 창을 이깁니다."""
    filters = _capture_tool_filters(
        monkeypatch,
        date_from="2026-01-01",
        date_to="2026-12-31",
    )

    assert filters["date_from"] == "2026-01-01"
    assert filters["date_to"] == "2026-12-31"
    assert "relative_years" not in filters

    explicit = apply_default_statistics_window({"date_from": "2026-01-01"})
    assert "relative_years" not in explicit


def test_explicit_years_wins_over_default_window(monkeypatch):
    filters = _capture_tool_filters(monkeypatch, years=1)

    assert filters["relative_years"] == 1


def test_build_retrieval_plan_does_not_inject_default_window():
    """플랜 단계에 창을 주입하면 스냅샷 계약이 깨집니다."""
    plan = build_retrieval_plan("전체 공고 건수 알려줘")

    assert "relative_years" not in plan.filters
    assert "date_from" not in plan.filters
    assert "date_to" not in plan.filters


def test_default_window_helper_uses_single_constant():
    assert apply_default_statistics_window({})["relative_years"] == (
        DEFAULT_STATISTICS_WINDOW_YEARS
    )
