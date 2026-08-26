"""
src/app/services/conversation_state.py

대화 상태 관리 (원본 apps/chatbot/services/conversation_state.py 이식).
Django 세션 대신 session_key 를 명시 전달받아 chat_session_states 테이블에 영속화합니다.
필터 누적, 차트 페이로드 파생, 히스토리 10턴 유지 규칙을 원본 그대로 보존합니다.
"""

from __future__ import annotations

import uuid
from typing import Any, cast

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.chatbot import ChatSessionState
from src.app.schemas.chat import ChatPlan

MAX_HISTORY_TURNS = 10
USER_MEMORY_PREFIX = "user:"


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

    rebuilt: list[dict[str, Any]] = [{"role": "user", "text": last_query}]
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


def _resolve_user_memory_key(user_id: int | None) -> str:
    """원본 _resolve_user_memory_key 대응. 로그인 사용자별 고정 메모리 키입니다."""
    return f"{USER_MEMORY_PREFIX}{user_id}" if user_id is not None else ""


def _merge_state_dicts(primary: dict, secondary: dict) -> dict:
    """원본 _merge_state_dicts 1:1 이식.

    세션 메모리를 우선하되, 필터는 사용자 메모리 위에 덮어써 세션이 바뀌어도
    직전 필터가 이어지도록 합니다.
    """
    merged_filters = dict(secondary.get("last_filters_json") or {})
    merged_filters.update(dict(primary.get("last_filters_json") or {}))
    return {
        "session_key": primary.get("session_key") or secondary.get("session_key") or "",
        "last_query": primary.get("last_query") or secondary.get("last_query") or "",
        "last_plan_json": dict(
            primary.get("last_plan_json") or secondary.get("last_plan_json") or {}
        ),
        "last_filters_json": merged_filters,
        "last_result_summary": primary.get("last_result_summary")
        or secondary.get("last_result_summary")
        or "",
        "last_chart_payload": list(primary.get("last_chart_payload") or []),
        "last_result_payload": dict(
            primary.get("last_result_payload") or secondary.get("last_result_payload") or {}
        ),
        "last_job_id": primary.get("last_job_id") or secondary.get("last_job_id") or "",
        "last_action_key": primary.get("last_action_key") or secondary.get("last_action_key") or "",
        "last_kb_version": primary.get("last_kb_version") or secondary.get("last_kb_version") or "",
        "last_response_mode": primary.get("last_response_mode")
        or secondary.get("last_response_mode")
        or "",
        "chat_history": list(primary.get("chat_history") or []),
    }


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
    db: Session, session_key: str, user_id: int | None = None
) -> dict[str, Any]:
    """원본과 동일하게 세션 메모리와 사용자 메모리를 합쳐 돌려줍니다."""
    session_payload = _serialize_state(
        _get_state_by_key(db, session_key, user_id=user_id, create=False)
    )
    user_memory_key = _resolve_user_memory_key(user_id)
    user_payload = (
        _serialize_state(_get_state_by_key(db, user_memory_key, user_id=user_id, create=False))
        if user_memory_key
        else {}
    )
    merged = _merge_state_dicts(session_payload, user_payload)
    return {
        **merged,
        "session_key": session_payload.get("session_key") or session_key,
        "last_tool_results": _extract_tool_results(merged.get("last_result_payload")),
        "session_memory": session_payload,
        "user_memory": user_payload,
        "memory_policy": {
            "session_scope": "full conversation result context",
            "user_scope": "sticky filters and query summary",
        },
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

    chart_payload = list(visualizations) if visualizations else _derive_chart_payload(tool_context)
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
    state.last_chart_payload = cast(dict[str, Any], chart_payload)
    if stored_result_payload:
        state.last_result_payload = stored_result_payload
    if job_id:
        state.last_job_id = job_id
    if action_key:
        state.last_action_key = action_key
    if kb_version:
        state.last_kb_version = kb_version
    state.chat_history_json = history[-(MAX_HISTORY_TURNS * 2) :]
    state.updated_at = utcnow()

    db.commit()
    db.refresh(state)

    # 원본과 동일하게 사용자 메모리에는 고정 필터와 질의 요약만 남깁니다.
    # 대화 내역과 결과 페이로드는 세션 메모리에만 두어 세션 간 오염을 막습니다.
    user_memory_key = _resolve_user_memory_key(user_id)
    if user_memory_key:
        user_state = _get_state_by_key(db, user_memory_key, user_id=user_id)
        if user_state is not None:
            user_filters = dict(user_state.last_filters_json or {})
            user_filters.update(filters)
            user_state.last_query = message or user_state.last_query
            if plan is not None:
                user_state.last_plan_json = plan.model_dump()
            user_state.last_filters_json = user_filters
            user_state.updated_at = utcnow()
            db.commit()

    return state
