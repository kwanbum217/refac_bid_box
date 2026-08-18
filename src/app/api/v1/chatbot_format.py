"""
src/app/api/v1/chatbot_format.py

챗봇 답변 포맷팅 및 컨텍스트/도구 결과 번들링 헬퍼.
"""

from __future__ import annotations

from html import escape
from typing import Any

from sqlalchemy.orm import Session

from src.app.schemas.chat import ChatPlan
from src.app.services.advisory_engine import AdvisoryEngine
from src.app.services.tools.kb_status_tool import build_kb_status_summary


def _append_kb_status(answer_text: str, kb_status: dict | None) -> str:
    summary = build_kb_status_summary(kb_status)
    if not summary:
        return answer_text
    return f"{answer_text}\n\n{summary}"


def _format_won(value: Any) -> str:
    try:
        return f"{int(value):,}원"
    except (TypeError, ValueError):
        return "-"


def _format_percent(value: Any) -> str:
    try:
        return f"{float(value):.1f}%"
    except (TypeError, ValueError):
        return "-"


def _markdown_cell(value: Any, *, bold: bool = False, code: bool = False) -> str:
    text = escape(str(value or "-")).replace("|", "\\|").replace("\n", " ").strip()
    if not text:
        text = "-"
    if code and text != "-":
        return f"`{text}`"
    if bold and text != "-":
        return f"**{text}**"
    return text


def _format_bid_number(bid: dict) -> str:
    return f"{bid.get('bid_ntce_no') or '-'}-{bid.get('bid_ntce_ord') or '-'}"


def _format_model_summary(predictions: list[dict]) -> str:
    model_names: list[str] = []
    for item in predictions:
        # 산출하지 못한 공고는 사용한 모델이 없으므로 요약에서 뺍니다.
        if item.get("skipped"):
            continue
        model_name = item.get("model_name") or item.get("model_id") or "-"
        if model_name not in model_names:
            model_names.append(model_name)
    if not model_names:
        return ""
    return f"사용 모델: **{_markdown_cell(', '.join(model_names))}**"


def _single_rate_cell(prediction: dict) -> str:
    if prediction.get("skipped"):
        return "-"
    return _format_percent(prediction.get("prediction_rate"))


def _single_price_cell(prediction: dict) -> str:
    if prediction.get("skipped"):
        return "산출 불가"
    return _markdown_cell(_format_won(prediction.get("optimal_price")), bold=True)


def _build_direct_tool_answer(tool_context: dict | None) -> str:
    """예측 도구 결과는 LLM 을 거치지 않고 표로 직접 제시합니다 (원본 동일)."""
    tool_results = (tool_context or {}).get("tool_results") or {}
    prediction = tool_results.get("bid_prediction")
    if not isinstance(prediction, dict):
        return ""

    if prediction.get("status") != "success":
        return str(prediction.get("message") or "예측 결과를 만들지 못했습니다.")

    predictions = prediction.get("predictions") or []
    if isinstance(predictions, list) and len(predictions) > 1:
        result_count = prediction.get("result_count") or len(predictions)
        requested_count = prediction.get("requested_count") or result_count
        lines = [
            "### 투찰가 예측 결과",
            "",
            f"최근 수집된 물품 공고 **{result_count}건**을 기준으로 예측했습니다.",
            "",
            "| # | 공고 | 수요기관 | 기초금액 | 예상 낙찰률 | 추천 투찰가 |",
            "| ---: | --- | --- | ---: | ---: | ---: |",
        ]
        if requested_count and result_count < requested_count:
            lines.insert(
                3,
                f"요청하신 {requested_count}건 중 예측 가능한 공고 **{result_count}건**만 확인했습니다.",
            )
        for index, item in enumerate(predictions, start=1):
            bid = item.get("bid") or {}
            title_cell = (
                f"{_markdown_cell(bid.get('bid_ntce_nm'), bold=True)}<br>"
                f"{_markdown_cell(_format_bid_number(bid), code=True)}"
            )
            # 산출하지 못한 공고를 0원·0.0% 로 적으면 실패가 정상 예측으로 보입니다.
            skipped = bool(item.get("skipped"))
            rate_cell = "-" if skipped else _format_percent(item.get("prediction_rate"))
            price_cell = (
                "산출 불가"
                if skipped
                else _markdown_cell(_format_won(item.get("optimal_price")), bold=True)
            )
            lines.append(
                f"| {index} | {title_cell} "
                f"| {_markdown_cell(bid.get('dminstt_nm') or bid.get('ntce_instt_nm'))} "
                f"| {_format_won(item.get('reference_amount'))} "
                f"| {rate_cell} "
                f"| {price_cell} |"
            )
        skipped_items = [item for item in predictions if item.get("skipped")]
        if skipped_items:
            lines.extend(["", f"> {len(skipped_items)}건은 투찰가를 산출하지 못했습니다."])
            for reason in dict.fromkeys(
                str(item.get("skip_reason") or "").strip()
                for item in skipped_items
                if str(item.get("skip_reason") or "").strip()
            ):
                lines.append(f"> - {_markdown_cell(reason)}")
        model_summary = _format_model_summary(predictions)
        if model_summary:
            lines.extend(["", model_summary])
        if any(item.get("fallback_used") for item in predictions):
            lines.extend(
                ["", "> 일부 공고는 요청 모델 추론 실패로 기본 모델 fallback을 사용했습니다."]
            )
        return "\n".join(lines)

    bid = prediction.get("bid") or {}
    lines = [
        "### 투찰가 예측 결과",
        "",
        "최근 수집된 물품 공고 기준으로 예측했습니다.",
        "",
        "| 항목 | 내용 |",
        "| --- | --- |",
        f"| 공고명 | {_markdown_cell(bid.get('bid_ntce_nm'), bold=True)} |",
        f"| 공고번호 | {_markdown_cell(_format_bid_number(bid), code=True)} |",
        f"| 분야 | {_markdown_cell(bid.get('category_label') or bid.get('category'))} |",
        f"| 수요기관 | {_markdown_cell(bid.get('dminstt_nm') or bid.get('ntce_instt_nm'))} |",
        f"| 기초금액 | {_format_won(prediction.get('reference_amount'))} |",
        f"| 예상 낙찰률 | {_single_rate_cell(prediction)} |",
        f"| 추천 투찰가 | {_single_price_cell(prediction)} |",
        f"| 사용 모델 | {_markdown_cell(prediction.get('model_name') or prediction.get('model_id'), bold=True)} |",
    ]
    if prediction.get("skipped"):
        reason = str(prediction.get("skip_reason") or "").strip()
        lines.extend(
            ["", f"> {_markdown_cell(reason) if reason else '투찰가를 산출하지 못했습니다.'}"]
        )
    elif prediction.get("fallback_used"):
        lines.extend(
            [
                "",
                f"> 요청 모델 `{_markdown_cell(prediction.get('requested_model'))}` 추론이 실패해 "
                "기본 모델로 fallback했습니다.",
            ]
        )
    return "\n".join(lines)


def _build_advisory_bundle(
    db: Session,
    base_suggestions: list[str] | None,
    *,
    user_id: int | None = None,
    request_obj=None,
) -> tuple[list[str], list[dict[str, Any]]]:
    """원본 _build_advisory_bundle 대응. 제안 텍스트와 신호를 함께 구성합니다."""
    engine = AdvisoryEngine()
    advisory_signals = engine.suggest(db, user_id=user_id, request_obj=request_obj)
    suggestions = list(base_suggestions or [])
    for signal in advisory_signals:
        message = str(signal.get("message") or "").strip()
        if message and message not in suggestions:
            suggestions.append(message)
    return suggestions, advisory_signals


def _build_answer_tool_context(
    message: str,
    history: list[dict],
    context_state: dict,
    plan: ChatPlan,
    user_id: int | None = None,
) -> dict[str, Any]:
    tool_context: dict[str, Any] = {
        "user_message": message,
        "history": history,
        "context_state": context_state,
        "original_query": message,
        "user_id": user_id,
    }
    if "result-object" not in str(plan.reason or ""):
        return tool_context

    last_tool_results = context_state.get("last_tool_results") or {}
    if isinstance(last_tool_results, dict) and last_tool_results:
        tool_context["tool_results"] = dict(last_tool_results)

    last_chart_payload = context_state.get("last_chart_payload") or []
    if isinstance(last_chart_payload, list) and last_chart_payload:
        tool_context["visualizations"] = list(last_chart_payload)
    return tool_context


def _plan_steps_payload(plan: ChatPlan) -> list[dict[str, str]]:
    return [
        {"step_id": step.step_id, "kind": step.kind, "tool": step.tool}
        for step in (plan.steps or [])
    ]
