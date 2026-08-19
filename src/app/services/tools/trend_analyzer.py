"""
src/app/services/tools/trend_analyzer.py

추세 분석 도구 (원본 apps/chatbot/tools/trend_analyzer.py 1:1 이식).
"""

from __future__ import annotations

from typing import Any


def _coerce_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _resolve_source_result(context: dict[str, Any], source_key: str) -> dict[str, Any]:
    tool_results = dict((context or {}).get("tool_results") or {})
    source = tool_results.get(source_key) or {}
    if isinstance(source, dict) and isinstance(source.get("result"), dict):
        return dict(source["result"])
    if isinstance(source, dict):
        return dict(source)
    return {}


def execute(
    *,
    context: dict[str, Any] | None = None,
    source_key: str = "bid_query",
    metric: str = "average_winning_rate",
    series_key: str = "time_series",
    top_n: int = 6,
) -> dict[str, Any]:
    source_result = _resolve_source_result(context or {}, source_key)
    summary = dict(source_result.get("summary") or {})
    raw_series = list(summary.get(series_key) or [])
    if top_n > 0:
        raw_series = raw_series[-int(top_n) :]

    series = []
    for row in raw_series:
        if not isinstance(row, dict):
            continue
        label = str(row.get("month") or row.get("label") or "").strip()
        if not label:
            continue
        series.append(
            {
                "label": label,
                "value": _coerce_float(
                    row.get("avg_rate") if "avg_rate" in row else row.get("value")
                ),
                "volume": int(row.get("bid_count") or row.get("volume") or 0),
            }
        )

    insights: list[str] = []
    direction = "insufficient"
    delta = 0.0
    volatility = 0.0
    peak: dict[str, Any] = {}
    trough: dict[str, Any] = {}

    if series:
        values: list[float] = [float(item["value"]) for item in series]
        volatility = round(max(values) - min(values), 4)
        peak = max(series, key=lambda item: item["value"])
        trough = min(series, key=lambda item: item["value"])

        if len(values) >= 2:
            delta = round(values[-1] - values[0], 4)
            if delta > 0.25:
                direction = "up"
                insights.append(f"최근 구간 평균 낙찰률이 {delta:.2f}p 상승했습니다.")
            elif delta < -0.25:
                direction = "down"
                insights.append(f"최근 구간 평균 낙찰률이 {abs(delta):.2f}p 하락했습니다.")
            else:
                direction = "flat"
                insights.append("최근 구간 평균 낙찰률이 큰 변동 없이 유지되고 있습니다.")

        if peak and trough:
            insights.append(
                f"최고 구간은 {peak['label']}({peak['value']:.2f}), "
                f"최저 구간은 {trough['label']}({trough['value']:.2f})입니다."
            )
        if volatility >= 1.5:
            insights.append("기간 내 변동 폭이 커서 추세 해석 시 주의가 필요합니다.")
        elif volatility > 0:
            insights.append("변동 폭은 비교적 안정적인 수준입니다.")
    else:
        insights.append("추세 분석에 사용할 시계열 데이터가 충분하지 않습니다.")

    return {
        "source_key": source_key,
        "metric": metric,
        "series_key": series_key,
        "series": series,
        "direction": direction,
        "delta": delta,
        "volatility": volatility,
        "peak": peak,
        "trough": trough,
        "insights": insights,
        "summary_text": " ".join(insights[:2]).strip(),
    }
