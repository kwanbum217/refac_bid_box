"""챗봇 API (POST /chat, POST /chat/stream, POST /session/new, POST /query)."""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from src.app.api.v1.accounts import get_current_user
from src.app.api.v1.chatbot_confirmation import (
    _build_automation_status_payload,
    _build_confirmed_automation_response,
    _build_missing_confirmation_response,
    _find_pending_confirmation_request,
    _is_text_confirmation_message,
)
from src.app.api.v1.chatbot_format import (
    _append_kb_status,
    _build_advisory_bundle,
    _build_answer_tool_context,
    _build_direct_tool_answer,
    _format_bid_number,
    _format_model_summary,
    _format_percent,
    _format_won,
    _markdown_cell,
    _plan_steps_payload,
)
from src.app.core.db import SessionLocal, get_db
from src.app.core.security import enforce_anonymous_api_quota
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from src.app.schemas.chatbot import (
    ChatbotQueryRequest,
    ChatbotQueryResponse,
    ChatRequest,
    ChatResponse,
)
from src.app.services.automation_orchestrator import (
    build_action_response,
    create_automation_request,
    get_automation_request,
    resolve_confirmation_token,
)
from src.app.services.conversation_state import (
    ensure_session_key,
    load_conversation_context,
    remember_chat_interaction,
)
from src.app.services.plan_executor import execute_plan_steps
from src.app.services.planner import plan_chat_request
from src.app.services.tools.kb_status_tool import get_latest_kb_status_payload
from src.rag.engine import rag_engine

# fmt: off
__all__ = ["RESTRICTED_KEYWORDS", "SECURITY_BLOCK_ANSWER", "STREAM_ERROR_MESSAGE", "_PendingRagAnswer", "_append_kb_status", "_build_advisory_bundle", "_build_answer_tool_context", "_build_automation_status_payload", "_build_confirmed_automation_response", "_build_direct_tool_answer", "_build_missing_confirmation_response", "_finalize_rag_answer", "_find_pending_confirmation_request", "_format_bid_number", "_format_model_summary", "_format_percent", "_format_won", "_is_text_confirmation_message", "_markdown_cell", "_new_trace_id", "_plan_steps_payload", "_prepare_chat", "_run_chat", "_sse", "chat_api", "chat_stream_api", "new_chat_session_api", "query_chatbot", "router"]
# fmt: on

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chatbot", tags=["Chatbot"])

# fmt: off
RESTRICTED_KEYWORDS = ("분류 코드체계", "코드 베이스", "베이스 코드", "내부 식별", "내부 코드", "분류코드")
# fmt: on
SECURITY_BLOCK_ANSWER = (
    "보안상의 이유로 시스템 내부 분류 코드체계 및 코드 베이스 관련 정보는 제공할 수 없습니다. "
    "시스템 관리자에게 문의하시기 바랍니다."
)


@dataclass
class _PendingRagAnswer:
    """플래너와 도구 실행까지 끝나고 RAG 본문만 남은 상태입니다.

    이 지점 이전의 분기(세션 전환, 보안 차단, 자동화 확인·실행, 자동화 상태)는
    생성할 토큰이 없어 스트리밍할 것이 없습니다. 스트리밍은 여기서부터 갈라집니다.
    """

    message: str
    session_key: str
    history: list[dict]
    kb_status: dict[str, Any] | None
    plan: Any
    tool_context: dict
    user_id: int | None


def _prepare_chat(
    db: Session, payload: ChatRequest, user_id: int | None = None
) -> ChatResponse | _PendingRagAnswer:
    """RAG 답변 직전까지 진행합니다.

    즉답이 가능한 분기는 완성된 ChatResponse 를, RAG 가 필요하면
    _PendingRagAnswer 를 돌려줍니다.
    """
    message = (payload.message or "").strip()
    session_key = ensure_session_key(payload.session_key, user_id=user_id)
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
            last_query=context_state.get("last_query", ""),
            history=list(history),
        )

    if not message:
        return ChatResponse(
            status="error", message="메시지를 입력해주세요.", session_key=session_key
        )

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

    # 실행 확인은 계획 수립보다 먼저 처리합니다 (원본 동일).
    confirmation_token = (payload.confirmation_token or "").strip()
    if confirmation_token:
        job_id = resolve_confirmation_token(confirmation_token)
        request_obj = get_automation_request(db, job_id)
        if request_obj is None or request_obj.user_id != user_id:
            raise HTTPException(status_code=404, detail="자동화 요청을 찾을 수 없습니다.")
        return _build_confirmed_automation_response(
            db, request_obj, message, kb_status, session_key, user_id
        )

    if _is_text_confirmation_message(message):
        request_obj = _find_pending_confirmation_request(db, user_id)
        if request_obj is not None:
            return _build_confirmed_automation_response(
                db, request_obj, message, kb_status, session_key, user_id
            )
        return _build_missing_confirmation_response(message, kb_status, session_key)

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
                "자동화 실행은 로그인 후 이용할 수 있습니다. 로그인 뒤 다시 요청해주세요.",
                kb_status,
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

    pending = _PendingRagAnswer(
        message=message,
        session_key=session_key,
        history=list(history),
        kb_status=kb_status,
        plan=plan,
        tool_context=tool_context,
        user_id=user_id,
    )

    direct_answer = _build_direct_tool_answer(tool_context)
    if direct_answer:
        return _finalize_rag_answer(db, pending, direct_answer)
    return pending


def _finalize_rag_answer(
    db: Session,
    pending: _PendingRagAnswer,
    answer_text: str,
    provenance: dict[str, Any] | None = None,
    latency_ms: float = 0.0,
) -> ChatResponse:
    """RAG 본문이 확정된 뒤의 마무리입니다. 동기 경로와 스트리밍 경로가 공유합니다.

    세션 저장과 선제 제안이 여기 있으므로, 스트리밍이라도 이 함수를 건너뛰면
    대화가 기록되지 않고 사이드바 세션 목록이 갱신되지 않습니다.
    """
    kb_status = pending.kb_status
    plan = pending.plan
    answer_text = _append_kb_status(answer_text, kb_status)
    visualizations = list((pending.tool_context or {}).get("visualizations") or [])

    remember_chat_interaction(
        db,
        pending.session_key,
        user_id=pending.user_id,
        message=pending.message,
        plan=plan,
        tool_context=pending.tool_context,
        answer_text=answer_text,
        visualizations=visualizations,
        kb_version=str((kb_status or {}).get("kb_version") or ""),
    )

    # 원본은 답변 모드에서도 선제 운영 제안을 함께 실어 보냅니다. 답변 본문에는
    # 섞지 않고 advisory_signals/suggestions 로만 분리해 전달합니다.
    suggestions, advisory_signals = _build_advisory_bundle(
        db, plan.suggestions, user_id=pending.user_id
    )

    return ChatResponse(
        mode=plan.mode if plan.mode in ("answer", "action") else "answer",
        intent=plan.intent_type,
        answer=answer_text,
        kb_status=kb_status,
        suggestions=suggestions,
        advisory_signals=advisory_signals,
        visualizations=visualizations,
        provenance=provenance,
        plan_steps=_plan_steps_payload(plan),
        session_key=pending.session_key,
        llm_backend=rag_engine.backend_name,
        latency_ms=latency_ms,
    )


def _open_session() -> tuple[Session, bool]:
    """스레드 작업용 세션을 엽니다. 테스트 환경의 dependency_overrides 를 반영합니다."""
    from src.app.main import app

    if get_db in app.dependency_overrides:
        res = app.dependency_overrides[get_db]()
        return (next(res), False) if hasattr(res, "__next__") else (res, True)
    return SessionLocal(), True


def _prepare_chat_sync(
    payload: ChatRequest, user_id: int | None = None
) -> ChatResponse | _PendingRagAnswer:
    db, should_close = _open_session()
    try:
        return _prepare_chat(db, payload, user_id)
    finally:
        if should_close:
            db.close()


def _finalize_rag_answer_sync(
    pending: _PendingRagAnswer,
    answer_text: str,
    provenance: dict[str, Any] | None = None,
    latency_ms: float = 0.0,
) -> ChatResponse:
    db, should_close = _open_session()
    try:
        return _finalize_rag_answer(db, pending, answer_text, provenance, latency_ms)
    finally:
        if should_close:
            db.close()


def _run_chat(
    payload_or_db: Session | ChatRequest,
    payload: ChatRequest | None = None,
    user_id: int | None = None,
) -> ChatResponse:
    """계획 수립 -> 도구 실행 -> RAG 답변 생성을 한 번에 수행합니다 (비스트리밍)."""
    if isinstance(payload_or_db, Session):
        req_payload = payload or ChatRequest(message="")
        uid = user_id
        session = payload_or_db
        should_close = False
    else:
        req_payload = payload_or_db
        uid = payload if isinstance(payload, int) else user_id
        session, should_close = _open_session()

    try:
        prepared = _prepare_chat(session, req_payload, uid)
        if isinstance(prepared, ChatResponse):
            return prepared
        bundle = rag_engine.get_answer_sync(
            prepared.message,
            db=session,
            history=prepared.history,
            tool_context=prepared.tool_context or None,
        )
        return _finalize_rag_answer(
            session, prepared, bundle.answer, bundle.provenance.model_dump(), bundle.latency_ms
        )
    finally:
        if should_close:
            session.close()


@router.post("/chat", response_model=ChatResponse, summary="챗봇 대화")
async def chat_api(
    payload: ChatRequest,
    request: Request,
    user: CustomUser | None = Depends(get_current_user),
):
    """계획 수립 -> 도구 실행 -> RAG 답변 생성의 원본 파이프라인을 그대로 수행합니다."""
    enforce_anonymous_api_quota(request, user)
    return await asyncio.to_thread(_run_chat, payload, user.id if user else None)


def _sse(event: str, data: dict[str, Any]) -> str:
    return f"event: {event}\ndata: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"


# 사용자에게 나가는 스트리밍 실패 문구입니다. 예외 문자열에는 DB 접속 정보,
# 내부 경로, 스택 조각이 섞일 수 있어 원문은 서버 로그로만 보냅니다.
STREAM_ERROR_MESSAGE = "응답 생성에 실패했습니다. 잠시 후 다시 시도해 주십시오."


def _new_trace_id() -> str:
    """src/rag/engine.py 의 provenance.trace_id 와 같은 형식으로 추적 id 를 만듭니다.

    스트리밍이 `done` 이벤트까지 도달하면 그 이벤트의 trace_id 를 쓰고, 그 전에
    끊기면 이 값으로 사용자 응답과 서버 로그를 잇습니다. 형식을 맞춰 두면 두
    경로의 id 를 같은 검색으로 찾을 수 있습니다.
    """
    return datetime.now().strftime("%Y%m%d%H%M%S") + os.urandom(4).hex()


@router.post("/chat/stream", summary="챗봇 대화 (SSE 스트리밍)")
async def chat_stream_api(
    payload: ChatRequest,
    request: Request,
    user: CustomUser | None = Depends(get_current_user),
):
    """POST /chat 와 동일한 파이프라인을 SSE 로 흘립니다.

    이벤트 순서는 stage -> (plan) -> (token...) -> final 입니다. `final` 은
    비스트리밍 응답과 완전히 같은 ChatResponse 라, 화면은 기존 렌더 로직을
    그대로 쓰면 됩니다. 토큰은 체감 속도를 위한 것이고 정본은 `final` 입니다.
    """
    enforce_anonymous_api_quota(request, user)
    user_id = user.id if user else None

    async def event_generator():
        trace_id = _new_trace_id()
        try:
            yield _sse("stage", {"stage": "planning", "message": "요청을 분석하고 있습니다"})

            prepared = await asyncio.to_thread(_prepare_chat_sync, payload, user_id)
            if isinstance(prepared, ChatResponse):
                yield _sse("final", prepared.model_dump())
                return

            yield _sse(
                "plan",
                {
                    "plan_steps": _plan_steps_payload(prepared.plan),
                    "intent": prepared.plan.intent_type,
                },
            )
            yield _sse("stage", {"stage": "answering", "message": "답변을 작성하고 있습니다"})

            answer_text = ""
            latency_started = utcnow()
            async for event in rag_engine.stream_tokens(
                prepared.message,
                history=prepared.history,
                tool_context=prepared.tool_context or None,
            ):
                kind = event.get("type")
                if kind == "token":
                    text = str(event.get("text") or "")
                    answer_text += text
                    yield _sse("token", {"text": text})
                elif kind == "done":
                    # 출처 표기와 Answer Guard 교정이 반영된 정본입니다.
                    answer_text = str(event.get("final_answer") or answer_text)
                    trace_id = str(event.get("trace_id") or trace_id)
                elif kind == "docs":
                    yield _sse("docs", {"docs": event.get("docs") or []})

            latency_ms = (utcnow() - latency_started).total_seconds() * 1000
            final = await asyncio.to_thread(
                _finalize_rag_answer_sync, prepared, answer_text, None, round(latency_ms, 2)
            )
            yield _sse("final", final.model_dump())
        except Exception:
            logger.exception("SSE 챗봇 스트리밍 실패 (trace_id=%s)", trace_id)
            yield _sse("error", {"message": STREAM_ERROR_MESSAGE, "trace_id": trace_id})

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/session/new", summary="새 대화 세션 생성")
def new_chat_session_api(request: Request, user: CustomUser | None = Depends(get_current_user)):
    enforce_anonymous_api_quota(request, user)
    return {"status": "success", "session_key": ensure_session_key()}


@router.post(
    "/query",
    response_model=ChatbotQueryResponse,
    response_model_exclude_none=True,
    summary="단발 질의 (간이 계약)",
)
async def query_chatbot(
    payload: ChatbotQueryRequest,
    response: Response,
    db: Session = Depends(get_db),
):
    bundle = await rag_engine.get_answer(payload.query, db=db)
    if bundle.provenance and bundle.provenance.trace_id:
        response.headers["X-RAG-Trace-Id"] = bundle.provenance.trace_id
    return ChatbotQueryResponse(
        query=payload.query,
        response=bundle.answer,
        retrieved_docs=bundle.retrieved_docs,
        latency_ms=bundle.latency_ms,
        route_reason=bundle.route_reason,
        citations=bundle.citations,
        segment_metrics=bundle.segment_metrics,
    )
