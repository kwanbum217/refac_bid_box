"""
src/app/services/result_presenter.py

자동화 결과 표현 계층 (원본 apps/chatbot/services/result_presenter.py 1:1 이식).
결과 페이로드를 해석해 시각화와 최종 답변 텍스트를 구성합니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from src.app.models.chatbot import AutomationRequest
from src.app.services.metric_interpreter import MetricInterpreter

STATUS_FAILED = "failed"


def _callback_metadata(request_obj: AutomationRequest) -> dict[str, Any]:
    payload = dict(request_obj.payload or {})
    return {
        "callback_mode": str(payload.get("callback_mode") or "polling"),
        "callback_configured": bool(payload.get("callback_configured")),
        "callback_reason": str(payload.get("callback_reason") or ""),
    }


def build_result_intelligence(result_payload: dict | None) -> dict[str, Any]:
    return MetricInterpreter().interpret(result_payload)


def build_presentable_result_payload(result_payload: dict | None) -> dict[str, Any]:
    payload = dict(result_payload or {})
    intelligence = build_result_intelligence(payload)
    payload["health_status"] = intelligence["health_status"]
    payload["insights"] = intelligence["insights"]
    payload["recommended_actions"] = intelligence["recommended_actions"]
    return payload


def build_visualizations(result_payload: dict | None) -> list[dict[str, Any]]:
    payload = result_payload or {}
    steps = payload.get("steps") or {}
    visualizations: list[dict[str, Any]] = []

    inspect_metrics = (steps.get("inspect") or {}).get("metrics") or {}
    predict_metrics = (steps.get("predict") or {}).get("metrics") or {}
    kb_metrics = (steps.get("rag") or {}).get("metrics") or {}

    inspect_labels: list[str] = []
    inspect_values: list[float] = []
    metric_order = (
        ("today_rows", "오늘 수집"),
        ("recent_bid_results", "최근 낙찰"),
        ("recent_bid_announcements", "최근 공고"),
        ("fresh_ingest_results", "최근 수집 낙찰"),
        ("fresh_ingest_announcements", "최근 수집 공고"),
        ("vector_count", "KB 벡터"),
    )
    for key, label in metric_order:
        value = inspect_metrics.get(key)
        if value is None:
            continue
        inspect_labels.append(label)
        inspect_values.append(float(value))

    if inspect_labels:
        visualizations.append(
            {
                "type": "chart",
                "chart_type": "bar",
                "title": "최신 데이터 점검 결과",
                "labels": inspect_labels,
                "values": inspect_values,
                "unit": "건",
                "x_label": "점검 항목",
                "y_label": "건수 (건)",
            }
        )

    if "avg_r2" in predict_metrics:
        visualizations.append(
            {
                "type": "chart",
                "chart_type": "bar",
                "title": "예측 모델 검증",
                "labels": ["avg_r2"],
                "values": [float(predict_metrics["avg_r2"])],
                "unit": "점",
                "x_label": "검증 지표",
                "y_label": "점수",
            }
        )

    if "source_bid_count" in kb_metrics:
        visualizations.append(
            {
                "type": "chart",
                "chart_type": "bar",
                "title": "KB 색인 원본 문서 수",
                "labels": ["원본 문서"],
                "values": [float(kb_metrics["source_bid_count"])],
                "unit": "건",
                "x_label": "색인 항목",
                "y_label": "문서 수 (건)",
            }
        )

    if visualizations:
        return visualizations

    reused_execution = payload.get("reused_execution") or {}
    duration_minutes = _execution_duration_minutes(reused_execution)
    if duration_minutes is None:
        duration_minutes = _outline_duration_minutes(payload.get("outline") or {})
    if duration_minutes is not None:
        visualizations.append(
            {
                "type": "chart",
                "chart_type": "bar",
                "title": "자동화 실행 소요 시간",
                "labels": ["전체 실행"],
                "values": [duration_minutes],
                "unit": "분",
                "x_label": "실행 구간",
                "y_label": "소요 시간 (분)",
            }
        )

    return visualizations


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def _execution_duration_minutes(execution_payload: dict) -> float | None:
    started_at = _parse_datetime(execution_payload.get("started_at"))
    ended_at = _parse_datetime(execution_payload.get("ended_at"))
    if not started_at or not ended_at:
        return None
    seconds = max((ended_at - started_at).total_seconds(), 0)
    return round(seconds / 60, 2)


def _outline_duration_minutes(outline_payload: dict) -> float | None:
    start_ts = outline_payload.get("startTs") or outline_payload.get("createdAt")
    end_ts = outline_payload.get("endTs") or outline_payload.get("lastUpdatedAt")
    try:
        if start_ts is None or end_ts is None:
            return None
        seconds = max((float(end_ts) - float(start_ts)) / 1000, 0)
    except (TypeError, ValueError):
        return None
    return round(seconds / 60, 2)


def build_terminal_answer(request_obj: AutomationRequest) -> str:
    presentable_payload = build_presentable_result_payload(request_obj.result_payload)
    steps = presentable_payload.get("steps") or {}
    callback_metadata = _callback_metadata(request_obj)
    lines: list[str] = []

    original_query = request_obj.followup_query or request_obj.requested_text
    if original_query:
        lines.append(f"요청하신 작업이 완료되었습니다: `{original_query}`")
    else:
        lines.append("자동화 작업이 완료되었습니다.")

    if request_obj.result_summary:
        lines.append("")
        lines.append(request_obj.result_summary)

    if callback_metadata["callback_mode"] == "polling":
        lines.append("")
        if steps:
            lines.append("공개 callback URL이 없어 일부 결과를 polling 기준으로 반영했습니다.")
        else:
            lines.append(
                callback_metadata["callback_reason"]
                or "공개 callback URL이 없어 상세 step callback 대신 실행 상태 polling 결과만 반영했습니다."
            )

    for step_name in ("preflight", "collect", "rag", "predict", "inspect", "final"):
        step_payload = steps.get(step_name) or {}
        if not step_payload:
            continue
        summary = step_payload.get("summary")
        status = step_payload.get("status")
        if summary:
            lines.append(f"- {step_name}: `{status or '-'}` / {summary}")

    health_status = presentable_payload.get("health_status") or "unknown"
    insights = presentable_payload.get("insights") or []
    lines.append("")
    lines.append("운영 해석:")
    lines.append(f"- health_status: `{health_status}`")
    if insights:
        for insight in insights:
            lines.append(f"- insights: {insight}")
    else:
        lines.append("- insights: 추가 위험 신호는 감지되지 않았습니다.")

    recommended_actions = presentable_payload.get("recommended_actions") or []
    lines.append("")
    lines.append("권장 액션:")
    if recommended_actions:
        for action in recommended_actions:
            lines.append(f"- recommended_actions: {action}")
    else:
        lines.append("- recommended_actions: 즉시 필요한 추가 조치는 없습니다.")

    if request_obj.error_message and request_obj.status == STATUS_FAILED:
        lines.append("")
        lines.append(f"오류: {request_obj.error_message}")

    return "\n".join(lines)
