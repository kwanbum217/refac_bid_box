"""
src/app/services/tools/chart_builder.py

차트 구성 도구 (원본 apps/chatbot/tools/chart_builder.py 1:1 이식).
"""

from __future__ import annotations

from typing import Any


def _chart_from_trend_result(
    trend_result: dict[str, Any],
    *,
    chart_type: str,
    title: str,
    max_points: int,
) -> dict[str, Any] | None:
    series = list(trend_result.get("series") or [])
    if max_points > 0:
        series = series[-int(max_points) :]
    if not series:
        return None

    labels = [str(item.get("label") or "") for item in series if item.get("label")]
    values = [float(item.get("value") or 0) for item in series if item.get("label")]
    if not labels or len(labels) != len(values):
        return None

    return {
        "type": "chart",
        "chart_type": chart_type or "line",
        "title": title or "최근 낙찰률 추세",
        "labels": labels,
        "values": values,
        "unit": "%",
        "x_label": "기간",
        "y_label": "낙찰률 (%)",
    }


def _chart_from_bid_query_result(
    bid_query_result: dict[str, Any],
    *,
    chart_type: str,
    title: str,
    max_points: int,
) -> dict[str, Any] | None:
    source_result = dict(bid_query_result.get("result") or bid_query_result or {})
    summary = dict(source_result.get("summary") or {})

    time_series = list(summary.get("time_series") or [])
    if max_points > 0:
        time_series = time_series[-int(max_points) :]
    if time_series:
        labels = [
            str(item.get("label") or item.get("month") or "")
            for item in time_series
            if item.get("label") or item.get("month")
        ]
        values = [
            float(item.get("avg_rate") or 0)
            for item in time_series
            if item.get("label") or item.get("month")
        ]
        if labels and len(labels) == len(values):
            return {
                "type": "chart",
                "chart_type": chart_type or "line",
                "title": title or "최근 낙찰률 추세",
                "labels": labels,
                "values": values,
                "unit": "%",
                "x_label": "기간",
                "y_label": "낙찰률 (%)",
            }

    top_winners = list(summary.get("top_winners") or [])[: max_points or 5]
    if not top_winners:
        return None
    labels = [str(item.get("bidwinnr_nm") or "-") for item in top_winners]
    values = [float(item.get("win_count") or 0) for item in top_winners]
    return {
        "type": "chart",
        "chart_type": "bar",
        "title": title or "상위 낙찰 업체",
        "labels": labels,
        "values": values,
        "unit": "건",
        "x_label": "업체",
        "y_label": "낙찰 건수 (건)",
    }


def execute(
    *,
    context: dict[str, Any] | None = None,
    source_key: str = "trend_analysis",
    chart_type: str = "line",
    title: str = "",
    max_points: int = 12,
) -> dict[str, Any]:
    tool_results = dict((context or {}).get("tool_results") or {})
    source_result = tool_results.get(source_key) or {}

    visualization = None
    chart_basis = ""
    if source_key == "trend_analysis" and isinstance(source_result, dict):
        visualization = _chart_from_trend_result(
            source_result, chart_type=chart_type, title=title, max_points=max_points
        )
        chart_basis = "trend_analysis"

    if visualization is None and isinstance(source_result, dict):
        visualization = _chart_from_bid_query_result(
            source_result, chart_type=chart_type, title=title, max_points=max_points
        )
        chart_basis = "bid_query"

    if visualization is None and "bid_query" in tool_results:
        visualization = _chart_from_bid_query_result(
            tool_results["bid_query"], chart_type=chart_type, title=title, max_points=max_points
        )
        chart_basis = "bid_query"

    visualizations = [visualization] if visualization else []
    return {
        "source_key": source_key,
        "chart_basis": chart_basis,
        "visualizations": visualizations,
    }
