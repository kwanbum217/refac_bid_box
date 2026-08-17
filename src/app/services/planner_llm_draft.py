"""
src/app/services/planner_llm_draft.py

챗봇 LLM 기반 계획 수립(Drafting) 및 검증 모듈.
Gemini LLM을 호출하여 복합 질의에 대한 PlanStep 초안을 작성하고 허용된 capability 규칙에 맞게 검증합니다.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Literal, cast

from src.app.schemas.chat import ChatPlan, PlanStep
from src.app.services.action_catalog import ACTION_CATALOG, DEFAULT_POLL_AFTER_MS
from src.app.services.capability_registry import CAPABILITY_REGISTRY, get_capability
from src.app.services.planner_intent_signals import (
    FOLLOWUP_SPLITTERS,
    SEMANTIC_KEYWORDS,
    STATISTICS_KEYWORDS,
)

logger = logging.getLogger(__name__)

LLM_PLAN_DRAFT_ENV = "CHATBOT_ENABLE_LLM_PLAN_DRAFT"


def _llm_plan_draft_enabled() -> bool:
    return os.getenv(LLM_PLAN_DRAFT_ENV, "false").strip().lower() == "true"


def _should_try_llm_plan_draft(message: str, matched_actions: list) -> bool:
    normalized = (message or "").strip().lower()
    has_statistics = any(keyword in normalized for keyword in STATISTICS_KEYWORDS)
    has_semantic = any(keyword in normalized for keyword in SEMANTIC_KEYWORDS)
    has_followup_splitter = any(keyword in normalized for keyword in FOLLOWUP_SPLITTERS)
    return len(matched_actions) > 1 or (has_statistics and has_semantic) or has_followup_splitter


def _llm_system_instruction() -> str:
    capability_names = ", ".join(sorted(CAPABILITY_REGISTRY.keys()))
    return (
        "You are a planning assistant for BIDBOX. "
        "Return strict JSON only. "
        "Allowed plan step tools are limited to these capability names: "
        f"{capability_names}. "
        "Each step must include step_id, kind, tool, params, output_key. "
        "Never invent pipeline ids or arbitrary tools."
    )


def _request_llm_plan_draft(message: str) -> dict[str, Any] | None:
    api_key = os.getenv("GEMINI_API_KEY", "").strip()
    if not api_key:
        return None

    try:
        from google import genai
        from google.genai import types
    except ImportError:
        return None

    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-3.1-flash-lite-preview",
            contents=message,
            config=types.GenerateContentConfig(
                system_instruction=_llm_system_instruction(),
                response_mime_type="application/json",
            ),
        )
    # 규칙 기반 계획으로 폴백하지만 흔적은 남겨야 합니다. 키 만료나 할당량 소진이
    # 조용히 지나가면 계획 품질이 내려간 것을 아무도 모릅니다. 2026-08-05 에
    # ChromaDB 검색이 같은 방식으로 닷새 동안 실패하고 있었습니다.
    except Exception:
        logger.exception("LLM 계획 수립 실패, 규칙 기반으로 폴백합니다")
        return None

    text = getattr(response, "text", "") or ""
    if not text:
        return None

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _validate_llm_plan_draft(message: str, draft: dict[str, Any]) -> ChatPlan | None:
    steps_payload = draft.get("steps")
    if not isinstance(steps_payload, list) or not steps_payload:
        return None

    validated_steps: list[PlanStep] = []
    for index, step_payload in enumerate(steps_payload, start=1):
        if not isinstance(step_payload, dict):
            return None
        tool = str(step_payload.get("tool") or "").strip()
        capability = get_capability(tool)
        if not capability:
            return None

        kind = str(step_payload.get("kind") or "").strip()
        expected_kind = "pipeline" if capability.type == "pipeline" else "internal_tool"
        if kind != expected_kind:
            return None

        params = step_payload.get("params") or {}
        if not isinstance(params, dict):
            return None

        unknown_params = set(params.keys()) - set(capability.allowed_params)
        if unknown_params:
            return None

        validated_steps.append(
            PlanStep(
                step_id=str(step_payload.get("step_id") or f"s{index}"),
                kind=cast(Literal["internal_tool", "pipeline", "respond", "advisory"], kind),
                tool=tool,
                params=params,
                mutating=capability.mutating,
                requires_confirmation=capability.requires_confirmation,
                output_key=str(step_payload.get("output_key") or tool),
            )
        )

    if any(step.mutating for step in validated_steps[1:]):
        return None

    if validated_steps[0].kind == "pipeline":
        selected_action = ACTION_CATALOG.get(validated_steps[0].tool)
        if not selected_action or any(step.kind == "pipeline" for step in validated_steps[1:]):
            return None
        return ChatPlan(
            mode="action",
            intent_type=selected_action.intent,
            primary_action_key=selected_action.action_key,
            requires_confirmation=any(s.requires_confirmation for s in validated_steps),
            followup_query=message if selected_action.followup_after_completion else "",
            reason="llm draft validated",
            suggestions=["실행 상태 보기", "자동화 결과 요약 보기"],
            poll_after_ms=DEFAULT_POLL_AFTER_MS,
            steps=validated_steps,
            llm_draft_used=True,
        )

    validated_steps.append(
        PlanStep(
            step_id=f"s{len(validated_steps) + 1}",
            kind="respond",
            tool="respond",
            output_key="answer",
        )
    )
    return ChatPlan(
        mode="answer",
        intent_type=(
            "statistics_query"
            if any(step.tool == "bid_query_tool" for step in validated_steps)
            else "knowledge_query"
        ),
        requires_confirmation=False,
        reason="llm draft validated",
        suggestions=[],
        poll_after_ms=DEFAULT_POLL_AFTER_MS,
        steps=validated_steps,
        llm_draft_used=True,
    )


def _attempt_llm_plan_draft(message: str, matched_actions: list) -> ChatPlan | None:
    if not _llm_plan_draft_enabled():
        return None
    if not _should_try_llm_plan_draft(message, matched_actions):
        return None
    draft = _request_llm_plan_draft(message)
    if not draft:
        return None
    return _validate_llm_plan_draft(message, draft)
