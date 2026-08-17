"""
src/app/api/v1/chatbot_confirmation.py

챗봇 자동화 실행 승인 및 상태 확인 헬퍼.
"""

from __future__ import annotations

from datetime import timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.api.v1.chatbot_format import _append_kb_status, _build_advisory_bundle
from src.app.core.timeutil import utcnow
from src.app.models.chatbot import AutomationRequest
from src.app.schemas.chatbot import ChatResponse
from src.app.services.automation_orchestrator import (
    STATUS_PENDING_CONFIRMATION,
    build_action_response,
    confirm_automation_request,
)
from src.app.services.conversation_state import remember_chat_interaction


def _is_text_confirmation_message(message: str) -> bool:
    """원본 _is_text_confirmation_message 1:1 이식.

    "승인 후 실행해줘" 처럼 버튼 대신 말로 승인하는 경우를 잡아냅니다.
    """
    normalized = "".join(str(message or "").lower().split())
    if not normalized:
        return False

    approval_terms = ("승인", "확인", "동의", "허용", "yes", "ok")
    run_terms = ("실행", "진행", "시작")
    if normalized in {"승인", "확인", "동의", "허용", "yes", "ok"}:
        return True
    return any(term in normalized for term in approval_terms) and any(
        term in normalized for term in run_terms
    )


def _find_pending_confirmation_request(
    db: Session, user_id: int | None
) -> AutomationRequest | None:
    """원본 _find_pending_confirmation_request 대응. 24시간 내 확인 대기 건을 찾습니다."""
    if user_id is None:
        return None
    cutoff = utcnow() - timedelta(hours=24)
    stmt = (
        select(AutomationRequest)
        .where(
            AutomationRequest.user_id == user_id,
            AutomationRequest.status == STATUS_PENDING_CONFIRMATION,
            AutomationRequest.requires_confirmation.is_(True),
            AutomationRequest.created_at >= cutoff,
        )
        .order_by(AutomationRequest.created_at.desc())
        .limit(1)
    )
    return db.execute(stmt).scalars().first()


def _build_confirmed_automation_response(
    db: Session,
    request_obj: AutomationRequest,
    message: str,
    kb_status: dict | None,
    session_key: str,
    user_id: int | None,
) -> ChatResponse:
    """원본 _build_confirmed_automation_response 대응. 승인 즉시 실행으로 넘깁니다."""
    confirm_automation_request(db, request_obj)
    action_payload = build_action_response(db, request_obj)
    suggestions, advisory_signals = _build_advisory_bundle(
        db, action_payload.get("suggestions"), user_id=user_id, request_obj=request_obj
    )
    answer_text = _append_kb_status(action_payload["answer"], kb_status)
    remember_chat_interaction(
        db,
        session_key,
        user_id=user_id,
        message=message or "실행 확인",
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
        kb_status=kb_status,
        session_key=session_key,
    )


def _build_missing_confirmation_response(
    message: str, kb_status: dict | None, session_key: str
) -> ChatResponse:
    """원본 _build_missing_confirmation_response 대응."""
    answer_text = _append_kb_status(
        "현재 승인 대기 중인 자동화 요청이 없습니다. 먼저 '전체 점검해줘'처럼 실행할 점검을 요청한 뒤 승인해 주세요.",
        kb_status,
    )
    return ChatResponse(
        mode="answer",
        intent="automation_confirmation",
        message="승인 대기 중인 자동화 요청이 없습니다.",
        answer=answer_text,
        suggestions=["전체 점검해줘", "사전 점검 실행해줘"],
        kb_status=kb_status,
        session_key=session_key,
    )


def _build_automation_status_payload(tool_context: dict | None) -> dict | None:
    payload = ((tool_context or {}).get("tool_results") or {}).get("automation_status")
    return payload if isinstance(payload, dict) else None
