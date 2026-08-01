"""
src/app/api/v1/chatbot.py

챗봇 API (원본 apps/chatbot/views.py chat_api 이식).

| 원본 Django 라우트 | 본 API |
| --- | --- |
| `chatbot:chat_api` | `POST /api/v1/chatbot/chat` |
| `chatbot:new_chat_session` | `POST /api/v1/chatbot/session/new` |
| (신규) 스트리밍 | `GET /api/v1/chatbot/stream` |
"""

from __future__ import annotations

import asyncio
import json
import logging
from html import escape
from typing import Any

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.app.api.v1.accounts import get_current_user
from src.app.core.db import SessionLocal, get_db
from src.app.models.accounts import CustomUser
from src.app.schemas.chat import ChatPlan
from src.app.schemas.chatbot import (
    ChatbotQueryRequest,
    ChatbotQueryResponse,
    ChatRequest,
    ChatResponse,
)
from src.app.services.advisory_engine import AdvisoryEngine
from src.app.services.automation_orchestrator import build_action_response, create_automation_request
from src.app.services.conversation_state import (
    ensure_session_key,
    load_conversation_context,
    remember_chat_interaction,
)
from src.app.services.plan_executor import execute_plan_steps
from src.app.services.planner import plan_chat_request
from src.app.services.tools.kb_status_tool import (
    build_kb_status_summary,
    get_latest_kb_status_payload,
)
from src.rag.engine import rag_engine

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

RESTRICTED_KEYWORDS = (
    "분류 코드체계",
    "코드 베이스",
    "베이스 코드",
    "내부 식별",
    "내부 코드",
    "분류코드",
)
SECURITY_BLOCK_ANSWER = (
    "보안상의 이유로 시스템 내부 분류 코드체계 및 코드 베이스 관련 정보는 제공할 수 없습니다. "
    "시스템 관리자에게 문의하시기 바랍니다."
)


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
        model_name = item.get("model_name") or item.get("model_id") or "-"
        if model_name not in model_names:
            model_names.append(model_name)
    if not model_names:
        return ""
    return f"사용 모델: **{_markdown_cell(', '.join(model_names))}**"


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
            lines.append(
                f"| {index} | {title_cell} "
                f"| {_markdown_cell(bid.get('dminstt_nm') or bid.get('ntce_instt_nm'))} "
                f"| {_format_won(item.get('reference_amount'))} "
                f"| {_format_percent(item.get('prediction_rate'))} "
                f"| {_markdown_cell(_format_won(item.get('optimal_price')), bold=True)} |"
            )
        model_summary = _format_model_summary(predictions)
        if model_summary:
            lines.extend(["", model_summary])
        if any(item.get("fallback_used") for item in predictions):
            lines.extend(["", "> 일부 공고는 요청 모델 추론 실패로 기본 모델 fallback을 사용했습니다."])
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
        f"| 예상 낙찰률 | {_format_percent(prediction.get('prediction_rate'))} |",
        f"| 추천 투찰가 | {_markdown_cell(_format_won(prediction.get('optimal_price')), bold=True)} |",
        f"| 사용 모델 | {_markdown_cell(prediction.get('model_name') or prediction.get('model_id'), bold=True)} |",
    ]
    if prediction.get("fallback_used"):
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


def _build_automation_status_payload(tool_context: dict | None) -> dict | None:
    payload = ((tool_context or {}).get("tool_results") or {}).get("automation_status")
    return payload if isinstance(payload, dict) else None


def _plan_steps_payload(plan: ChatPlan) -> list[dict[str, str]]:
    return [
        {"step_id": step.step_id, "kind": step.kind, "tool": step.tool}
        for step in (plan.steps or [])
    ]


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


def _run_chat(db: Session, payload: ChatRequest, user_id: int | None = None) -> ChatResponse:
    message = (payload.message or "").strip()
    session_key = ensure_session_key(payload.session_key)
    context_state = load_conversation_context(db, session_key, user_id=user_id)
    history = context_state.get("chat_history", [])
    kb_status = get_latest_kb_status_payload(db)

    # 세션 전환 요청 (메시지 없이 session_key 만 전달)
    if not message and payload.session_key:
        return ChatResponse(
            mode="switch",
            session_key=session_key,
            answer=context_state.get("last_result_summary", ""),
            visualizations=list(context_state.get("last_chart_payload") or []),
            kb_status=kb_status,
        )

    if not message:
        return ChatResponse(status="error", message="메시지를 입력해주세요.", session_key=session_key)

    compact = message.replace(" ", "")
    if any(keyword in compact or keyword in message for keyword in RESTRICTED_KEYWORDS):
        answer_text = _append_kb_status(SECURITY_BLOCK_ANSWER, kb_status)
        return ChatResponse(
            mode="answer",
            intent="security_block",
            answer=answer_text,
            kb_status=kb_status,
            suggestions=["최근 공고 보여줘", "투찰가 예측해줘"],
            session_key=session_key,
        )

    plan = plan_chat_request(message, context_state=context_state)

    if plan.mode == "advisory":
        suggestions, advisory_signals = _build_advisory_bundle(db, plan.suggestions)
        answer_text = _append_kb_status(
            "자동화 구독 설정으로 전환할 수 있는 요청으로 보입니다.\n"
            "원하는 주기/조건을 알려주시면 등록 가능한 정책으로 정리해드리겠습니다.\n\n"
            "추천 항목:\n- " + "\n- ".join(suggestions),
            kb_status,
        )
        remember_chat_interaction(
            db, session_key, user_id=user_id, message=message, plan=plan, answer_text=answer_text
        )
        return ChatResponse(
            mode="advisory",
            intent=plan.intent_type,
            message="자동화 정책 제안 요청으로 분류했습니다.",
            answer=answer_text,
            suggestions=suggestions,
            advisory_signals=advisory_signals,
            kb_status=kb_status,
            session_key=session_key,
            plan_steps=_plan_steps_payload(plan),
        )

    # 자동화 실행 요청은 자동화 요청 레코드를 만들고 실행 카드를 반환합니다 (원본 동일).
    if plan.mode == "action":
        if user_id is None:
            answer_text = _append_kb_status(
                "자동화 실행은 로그인 후 이용할 수 있습니다. 로그인 뒤 다시 요청해주세요.", kb_status
            )
            return ChatResponse(
                status="error",
                mode="error",
                intent=plan.intent_type,
                message="로그인이 필요합니다.",
                answer=answer_text,
                kb_status=kb_status,
                session_key=session_key,
                plan_steps=_plan_steps_payload(plan),
            )

        request_obj = create_automation_request(
            db,
            plan=plan,
            message=message,
            user_id=user_id,
            payload={"source": "chat_api"},
        )
        action_payload = build_action_response(db, request_obj)
        suggestions, advisory_signals = _build_advisory_bundle(
            db, action_payload.get("suggestions"), user_id=user_id, request_obj=request_obj
        )
        answer_text = _append_kb_status(action_payload["answer"], kb_status)
        remember_chat_interaction(
            db,
            session_key,
            user_id=user_id,
            message=message,
            plan=plan,
            answer_text=answer_text,
            visualizations=action_payload["visualizations"],
            result_payload=action_payload["result_payload"],
            job_id=str(request_obj.request_id),
            action_key=request_obj.action_key,
        )
        return ChatResponse(
            mode=action_payload["mode"],
            intent=action_payload["intent"],
            message=action_payload["message"],
            answer=answer_text,
            job=action_payload["job"],
            suggestions=suggestions,
            advisory_signals=advisory_signals,
            visualizations=action_payload["visualizations"],
            result_payload=action_payload["result_payload"],
            confirmation_token=action_payload["confirmation_token"],
            kb_status=kb_status,
            session_key=session_key,
            plan_steps=_plan_steps_payload(plan),
        )

    tool_context: dict[str, Any] = {}
    if plan.steps:
        tool_context = execute_plan_steps(
            plan,
            _build_answer_tool_context(message, history, context_state, plan, user_id=user_id),
            db=db,
        )

    # 자동화 상태 질의는 도구 결과를 그대로 응답 계약에 실어 보냅니다 (원본 동일).
    automation_status_payload = _build_automation_status_payload(tool_context)
    if automation_status_payload:
        answer_text = _append_kb_status(
            str(
                automation_status_payload.get("answer")
                or automation_status_payload.get("message")
                or "자동화 상태를 확인했습니다."
            ),
            kb_status,
        )
        base_suggestions = automation_status_payload.get("suggestions") or []
        suggestions, advisory_signals = _build_advisory_bundle(
            db, base_suggestions if isinstance(base_suggestions, list) else [], user_id=user_id
        )
        visualizations = list(
            automation_status_payload.get("visualizations")
            or (tool_context or {}).get("visualizations")
            or []
        )
        job_payload = automation_status_payload.get("job")
        job_payload = job_payload if isinstance(job_payload, dict) else None
        result_payload = automation_status_payload.get("result_payload")
        result_payload = result_payload if isinstance(result_payload, dict) else {}

        remember_chat_interaction(
            db,
            session_key,
            user_id=user_id,
            message=message,
            plan=plan,
            tool_context=tool_context,
            answer_text=answer_text,
            visualizations=visualizations,
            result_payload=result_payload,
            job_id=str((job_payload or {}).get("job_id") or ""),
            action_key=str((job_payload or {}).get("action_key") or ""),
        )
        return ChatResponse(
            mode=str(automation_status_payload.get("mode") or "answer"),
            intent=str(automation_status_payload.get("intent") or plan.intent_type),
            message=str(automation_status_payload.get("message") or "자동화 상태를 확인했습니다."),
            answer=answer_text,
            job=job_payload,
            suggestions=suggestions,
            advisory_signals=advisory_signals,
            visualizations=visualizations,
            result_payload=result_payload,
            confirmation_token=str(automation_status_payload.get("confirmation_token") or ""),
            kb_status=kb_status,
            session_key=session_key,
            plan_steps=_plan_steps_payload(plan),
        )

    direct_answer = _build_direct_tool_answer(tool_context)
    provenance = None
    latency_ms = 0.0
    if direct_answer:
        answer_text = direct_answer
    else:
        bundle = rag_engine.get_answer_sync(
            message, db=db, history=history, tool_context=tool_context or None
        )
        answer_text = bundle.answer
        provenance = bundle.provenance.model_dump()
        latency_ms = bundle.latency_ms

    answer_text = _append_kb_status(answer_text, kb_status)
    visualizations = list((tool_context or {}).get("visualizations") or [])

    remember_chat_interaction(
        db,
        session_key,
        user_id=user_id,
        message=message,
        plan=plan,
        tool_context=tool_context,
        answer_text=answer_text,
        visualizations=visualizations,
        kb_version=str((kb_status or {}).get("kb_version") or ""),
    )

    return ChatResponse(
        mode=plan.mode if plan.mode in ("answer", "action") else "answer",
        intent=plan.intent_type,
        answer=answer_text,
        kb_status=kb_status,
        visualizations=visualizations,
        provenance=provenance,
        plan_steps=_plan_steps_payload(plan),
        session_key=session_key,
        llm_backend=rag_engine.backend_name,
        latency_ms=latency_ms,
    )


@router.post("/chat", response_model=ChatResponse, summary="챗봇 대화")
async def chat_api(
    payload: ChatRequest,
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
):
    """계획 수립 -> 도구 실행 -> RAG 답변 생성의 원본 파이프라인을 그대로 수행합니다."""
    return await asyncio.to_thread(_run_chat, db, payload, user.id if user else None)


@router.post("/session/new", summary="새 대화 세션 생성")
def new_chat_session_api():
    return {"status": "success", "session_key": ensure_session_key()}


@router.post("/query", response_model=ChatbotQueryResponse, summary="단발 질의 (간이 계약)")
async def query_chatbot(payload: ChatbotQueryRequest, db: Session = Depends(get_db)):
    bundle = await rag_engine.get_answer(payload.query, db=db)
    return ChatbotQueryResponse(
        query=payload.query,
        response=bundle.answer,
        retrieved_docs=bundle.retrieved_docs,
        latency_ms=bundle.latency_ms,
        route_reason=bundle.route_reason,
        citations=bundle.citations,
    )


@router.get("/stream", summary="SSE 스트리밍 응답")
async def stream_chatbot(query: str, session_key: str = ""):
    async def event_generator():
        db = SessionLocal()
        try:
            history = (
                load_conversation_context(db, session_key).get("chat_history", [])
                if session_key
                else []
            )
            async for event in rag_engine.stream_tokens(query, db=db, history=history):
                yield f"data: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                await asyncio.sleep(0)
        finally:
            db.close()

    return StreamingResponse(event_generator(), media_type="text/event-stream")
