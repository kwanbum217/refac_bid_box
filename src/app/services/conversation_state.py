"""
src/app/services/conversation_state.py

대화 상태 관리 (원본 apps/chatbot/services/conversation_state.py 이식).
Django 세션 대신 session_key 를 명시 전달받아 chat_session_states 테이블에 영속화합니다.
필터 누적, 차트 페이로드 파생, 히스토리 10턴 유지 규칙을 원본 그대로 보존합니다.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.models.chatbot import ChatSessionState
from src.app.schemas.chat import ChatPlan

MAX_HISTORY_TURNS = 10


def ensure_session_key(session_key: str | None = None) -> str:
    return (session_key or "").strip() or uuid.uuid4().hex


def _get_state_by_key(
    db: Session, session_key: str, *, user_id: int | None = None, create: bool = True
) -> ChatSessionState | None:
    state = db.execute(
        select(ChatSessionState).where(ChatSessionState.session_key == session_key)
    ).scalar_one_or_none()
    if state is None and create:
        state = ChatSessionState(session_key=session_key, user_id=user_id)
        db.add(state)
        db.commit()
        db.refresh(state)
    return state


def _last_user_message_from_history(history: list[dict]) -> str:
    for item in reversed(history or []):
        if item.get("role") == "user":
            return str(item.get("text") or "")
    return ""


def _history_from_state(state: ChatSessionState | None) -> list[dict]:
    if not state:
        return []

    history = list(state.chat_history_json or [])
    last_query = str(state.last_query or "")
    if not last_query:
        return history

    # 오래된 행은 last_query 만 갱신되고 chat_history_json 이 낡아 있을 수 있습니다.
    # 이 경우 잘못된 대화를 여는 대신 최소 재구성을 사용합니다.
    if _last_user_message_from_history(history) == last_query:
        return history

    rebuilt = [{"role": "user", "text": last_query}]
    if state.last_result_summary:
        rebuilt.append({"role": "model", "text": state.last_result_summary})
    return rebuilt


def _as_dict(value: Any) -> dict[str, Any]:
    if hasattr(value, "model_dump"):
        value = value.model_dump()
    return dict(value) if isinstance(value, dict) else {}


def _extract_filters(tool_context: dict | None) -> dict[str, Any]:
    filters: dict[str, Any] = {}
    tool_results = (tool_context or {}).get("tool_results") or {}
    if not isinstance(tool_results, dict):
        return filters

    for result in tool_results.values():
        result_payload = _as_dict(result)
        retrieval_plan = _as_dict(result_payload.get("retrieval_plan"))
        extracted = retrieval_plan.get("filters") or {}
        if isinstance(extracted, dict):
            filters.update(extracted)
    return filters


def _derive_chart_payload(tool_context: dict | None) -> list[dict]:
    visualizations = list((tool_context or {}).get("visualizations") or [])
    if visualizations:
        return visualizations

    tool_results = (tool_context or {}).get("tool_results") or {}
    if not isinstance(tool_results, dict):
        return []

    bid_query = _as_dict(tool_results.get("bid_query"))
    summary = _as_dict(_as_dict(bid_query.get("result")).get("summary"))
    time_series = summary.get("time_series") or []
    if not isinstance(time_series, list) or not time_series:
        return []

    labels = [
        str(item.get("month") or "")
        for item in time_series
        if isinstance(item, dict) and item.get("month")
    ]
    values = [
        float(item.get("avg_rate") or 0)
        for item in time_series
        if isinstance(item, dict) and item.get("month")
    ]
    if not labels or len(labels) != len(values):
        return []

    return [
        {
            "type": "chart",
            "chart_type": "line",
            "title": "Recent bid rate trend",
            "labels": labels,
            "values": values,
        }
    ]


def _extract_tool_results(result_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = _as_dict(result_payload)
    embedded = payload.get("tool_results")
    return dict(embedded) if isinstance(embedded, dict) else {}


def _serialize_state(state: ChatSessionState | None) -> dict[str, Any]:
    if not state:
        return {}
    return {
        "session_key": state.session_key,
        "last_query": state.last_query or "",
        "last_plan_json": dict(state.last_plan_json or {}),
        "last_filters_json": dict(state.last_filters_json or {}),
        "last_result_summary": state.last_result_summary or "",
        "last_chart_payload": list(state.last_chart_payload or []),
        "last_result_payload": dict(state.last_result_payload or {}),
        "last_job_id": state.last_job_id or "",
        "last_action_key": state.last_action_key or "",
        "last_kb_version": state.last_kb_version or "",
        "last_response_mode": state.last_response_mode or "",
        "chat_history": _history_from_state(state),
    }


def load_conversation_context(
    db: Session, session_key: str, *, user_id: int | None = None
) -> dict[str, Any]:
    payload = _serialize_state(_get_state_by_key(db, session_key, user_id=user_id, create=False))
    return {
        **payload,
        "session_key": payload.get("session_key") or session_key,
        "last_tool_results": _extract_tool_results(payload.get("last_result_payload")),
    }


def remember_chat_interaction(
    db: Session,
    session_key: str,
    *,
    user_id: int | None = None,
    message: str = "",
    plan: ChatPlan | None = None,
    tool_context: dict | None = None,
    answer_text: str = "",
    visualizations: list[dict] | None = None,
    result_payload: dict[str, Any] | None = None,
    job_id: str = "",
    action_key: str = "",
    kb_version: str = "",
) -> ChatSessionState | None:
    state = _get_state_by_key(db, session_key, user_id=user_id)
    if state is None:
        return None

    chart_payload = (
        list(visualizations) if visualizations else _derive_chart_payload(tool_context)
    )
    filters = _extract_filters(tool_context)
    merged_filters = dict(state.last_filters_json or {})
    merged_filters.update(filters)

    stored_result_payload = dict(result_payload or {})
    if tool_context and isinstance(tool_context.get("tool_results"), dict):
        stored_result_payload["tool_results"] = tool_context["tool_results"]

    history = list(state.chat_history_json or [])
    if message:
        history.append({"role": "user", "text": message})
    if answer_text:
        history.append({"role": "model", "text": answer_text})

    state.last_query = message or state.last_query
    if plan is not None:
        state.last_plan_json = plan.model_dump()
        if plan.response_mode:
            state.last_response_mode = plan.response_mode
    state.last_filters_json = merged_filters
    if answer_text:
        state.last_result_summary = answer_text
    state.last_chart_payload = chart_payload
    if stored_result_payload:
        state.last_result_payload = stored_result_payload
    if job_id:
        state.last_job_id = job_id
    if action_key:
        state.last_action_key = action_key
    if kb_version:
        state.last_kb_version = kb_version
    state.chat_history_json = history[-(MAX_HISTORY_TURNS * 2) :]
    state.updated_at = datetime.utcnow()

    db.commit()
    db.refresh(state)
    return state
