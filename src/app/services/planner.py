"""
src/app/services/planner.py

챗봇 2단계 플래너 (원본 apps/chatbot/services/planner.py 1:1 이식).
1단계 interpret_request 가 사용자 메시지를 ChatExecutionPlan 으로 정규화하고,
2단계 compile_plan 이 실행 가능한 ChatPlan(PlanStep 목록)으로 컴파일합니다.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from src.app.schemas.chat import ChatExecutionPlan, ChatPlan, PlanStep
from src.app.services.action_catalog import ACTION_CATALOG, DEFAULT_POLL_AFTER_MS
from src.app.services.capability_registry import get_capability
from src.app.services.planner_intent_signals import (
    ADVISORY_KEYWORDS,
    AUTOMATION_STATUS_KEYWORDS,
    BID_PRICE_PREDICTION_KEYWORDS,
    CATEGORY_KEYWORDS,
    COLLECTION_COMMAND_KEYWORDS,
    COLLECTION_CONTEXT_KEYWORDS,
    FOLLOWUP_CHART_KEYWORDS,
    FOLLOWUP_DETAIL_KEYWORDS,
    FOLLOWUP_KB_REFRESH_KEYWORDS,
    FOLLOWUP_RANKING_KEYWORDS,
    FOLLOWUP_RERUN_KEYWORDS,
    FOLLOWUP_RESULT_REFERENCE_KEYWORDS,
    FOLLOWUP_SPLITTERS,
    FOLLOWUP_TREND_DETAIL_KEYWORDS,
    KB_KEYWORDS,
    KB_REFRESH_COMMAND_KEYWORDS,
    KB_REFRESH_TARGET_KEYWORDS,
    MODEL_VALIDATION_KEYWORDS,
    PREDICTION_ACTION_KEYWORDS,
    PREDICTION_CONTEXT_KEYWORDS,
    REGION_KEYWORDS,
    SEMANTIC_KEYWORDS,
    STATISTICS_KEYWORDS,
    STATUS_QUERY_KEYWORDS,
    TREND_VISUAL_KEYWORDS,
    _extract_bid_query_params,
    _extract_followup_category,
    _extract_followup_region,
    _extract_prediction_limit,
    _extract_prediction_model_id,
    _has_collection_command,
    _has_collection_context_only,
    _has_kb_refresh_intent,
    _has_prediction_action_intent,
    _is_bid_price_prediction_request,
    _is_model_validation_request,
    _select_action,
)
from src.app.services.planner_interpreter import (
    _load_last_plan,
    _load_last_tool_results,
    interpret_request,
)
from src.app.services.planner_llm_draft import (
    LLM_PLAN_DRAFT_ENV,
    _llm_plan_draft_enabled,
    _llm_system_instruction,
    _request_llm_plan_draft,
    _should_try_llm_plan_draft,
    _validate_llm_plan_draft,
)

logger = logging.getLogger(__name__)


def _step(
    step_id: str,
    kind: Literal["internal_tool", "pipeline", "respond", "advisory"],
    tool: str,
    *,
    params: dict[str, Any] | None = None,
    output_key: str = "",
) -> PlanStep:
    capability = get_capability(tool)
    return PlanStep(
        step_id=step_id,
        kind=kind,
        tool=tool,
        params=params or {},
        mutating=bool(capability.mutating) if capability else False,
        requires_confirmation=bool(capability.requires_confirmation) if capability else False,
        output_key=output_key,
    )


def _compute_requires_confirmation(steps: list[PlanStep]) -> bool:
    return any(step.requires_confirmation for step in steps)


def _default_answer_plan(
    intent_type: str, reason: str, steps: list[PlanStep] | None = None
) -> ChatPlan:
    resolved_steps = steps or [
        PlanStep(step_id="s1", kind="respond", tool="respond", output_key="answer")
    ]
    return ChatPlan(
        mode="answer",
        intent_type=intent_type,
        requires_confirmation=_compute_requires_confirmation(resolved_steps),
        followup_query="",
        reason=reason,
        suggestions=[],
        poll_after_ms=DEFAULT_POLL_AFTER_MS,
        steps=resolved_steps,
        llm_draft_used=False,
        response_mode="simple",
    )


def _build_advisory_plan() -> ChatPlan:
    return ChatPlan(
        mode="advisory",
        intent_type="create_scheduled_report",
        requires_confirmation=False,
        reason="advisory keywords matched",
        suggestions=[
            "매일 아침 신규 공고 요약 등록",
            "관심 키워드 공고 알림 등록",
            "주간 경쟁률 통계 리포트 등록",
        ],
        poll_after_ms=DEFAULT_POLL_AFTER_MS,
        steps=[
            PlanStep(
                step_id="s1", kind="advisory", tool="subscription_advisory", output_key="advisory"
            )
        ],
        llm_draft_used=False,
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


def compile_plan(execution_plan: ChatExecutionPlan) -> ChatPlan:
    """
    2단계: 정규화된 해석 객체를 바탕으로 실제 실행 가능한 ChatPlan을 생성한다.
    ChatExecutionPlan의 필드만을 사용하여 Plan을 구성한다 (Build-time decouple).
    """
    effective_query = execution_plan.effective_query
    original_message = execution_plan.original_message

    # 1. Advisory 처리
    if execution_plan.query_type == "advisory":
        return _build_advisory_plan()

    def _action_followup_query(action_key: str, action) -> str:
        if not action or not action.followup_after_completion:
            return ""
        if execution_plan.is_followup and action_key in {"data_refresh", "kb_refresh"}:
            return execution_plan.last_query
        return original_message

    # 2. Action 처리
    if execution_plan.query_type == "action":
        action_key = execution_plan.action_key or (
            execution_plan.requested_capabilities[0]
            if execution_plan.requested_capabilities
            else ""
        )
        if not action_key:
            return _default_answer_plan(
                "knowledge_query", "action requested but no action key found"
            )

        action = ACTION_CATALOG.get(action_key)
        if not action:
            return _default_answer_plan("knowledge_query", f"unknown action: {action_key}")

        capability = get_capability(action_key)
        steps = [
            PlanStep(
                step_id="s1",
                kind="pipeline",
                tool=action_key,
                params={"run_mode": action.run_mode},
                mutating=bool(capability.mutating) if capability else action.mutating,
                requires_confirmation=(
                    bool(capability.requires_confirmation) if capability else action.high_cost
                ),
                output_key="pipeline",
            )
        ]
        if action.followup_after_completion:
            steps.append(
                PlanStep(step_id="s2", kind="respond", tool="respond", output_key="answer")
            )

        return ChatPlan(
            mode="action",
            intent_type=action.intent,
            primary_action_key=action.action_key,
            requires_confirmation=any(s.requires_confirmation for s in steps),
            followup_query=_action_followup_query(action.action_key, action),
            reason=execution_plan.reasoning,
            suggestions=["실행 상태 보기", "자동화 결과 요약 보기", "그래프로 다시 보기"],
            poll_after_ms=DEFAULT_POLL_AFTER_MS,
            steps=steps,
            response_mode=execution_plan.response_mode,
        )

    # 3. Answer 처리
    if execution_plan.query_type == "answer":
        llm_plan = _attempt_llm_plan_draft(original_message, [])
        if llm_plan:
            return llm_plan

        steps: list[PlanStep] = []
        for cap in execution_plan.requested_capabilities:
            step_id = f"s{len(steps) + 1}"
            if cap == "automation_status_tool":
                job_id = execution_plan.parameters.get("job_id") or execution_plan.job_id
                params: dict[str, Any] = {"job_id": job_id}
                if execution_plan.parameters.get("prefer_visualization"):
                    params["prefer_visualization"] = True
                steps.append(
                    _step(
                        step_id,
                        "internal_tool",
                        cap,
                        params=params,
                        output_key="automation_status",
                    )
                )
            elif cap == "bid_query_tool":
                steps.append(
                    _step(
                        step_id,
                        "internal_tool",
                        cap,
                        params=execution_plan.parameters,
                        output_key="bid_query",
                    )
                )
            elif cap == "bid_prediction_tool":
                steps.append(
                    _step(
                        step_id,
                        "internal_tool",
                        cap,
                        params=execution_plan.parameters,
                        output_key="bid_prediction",
                    )
                )
            elif cap == "semantic_search_tool":
                query = execution_plan.parameters.get("query") or effective_query
                steps.append(
                    _step(
                        step_id,
                        "internal_tool",
                        cap,
                        params={"query": query},
                        output_key="semantic_search",
                    )
                )
            elif cap == "kb_status_tool":
                steps.append(_step(step_id, "internal_tool", cap, output_key="kb_status"))
            elif cap == "trend_analyzer":
                source = execution_plan.parameters.get("trend_source") or (
                    "bid_query"
                    if "bid_query_tool" in execution_plan.requested_capabilities
                    else "trend_analysis"
                )
                steps.append(
                    _step(
                        step_id,
                        "internal_tool",
                        cap,
                        params={"source_key": source, "series_key": "time_series", "top_n": 6},
                        output_key="trend_analysis",
                    )
                )
            elif cap == "chart_builder":
                source = execution_plan.parameters.get("chart_source") or (
                    "trend_analysis"
                    if "trend_analyzer" in execution_plan.requested_capabilities
                    else "bid_query"
                )
                steps.append(
                    _step(
                        step_id,
                        "internal_tool",
                        cap,
                        params={"source_key": source, "chart_type": "line"},
                        output_key="chart_payload",
                    )
                )

        steps.append(
            PlanStep(
                step_id=f"s{len(steps) + 1}", kind="respond", tool="respond", output_key="answer"
            )
        )

        if "automation_status_tool" in execution_plan.requested_capabilities:
            intent = "automation_status"
        elif "bid_prediction_tool" in execution_plan.requested_capabilities:
            intent = "prediction_query"
        elif "bid_query_tool" in execution_plan.requested_capabilities:
            intent = "statistics_query"
        else:
            intent = "knowledge_query"
        plan = _default_answer_plan(intent, execution_plan.reasoning, steps=steps)
        plan.response_mode = execution_plan.response_mode
        return plan

    return _default_answer_plan("knowledge_query", "fallback interpretation")


def plan_chat_request(message: str, context_state: dict[str, Any] | None = None) -> ChatPlan:
    """
    외부에서 호출하는 메인 엔트리 포인트.
    1단계(해석)와 2단계(컴파일)를 거쳐 실행 계획을 반환한다.
    """
    execution_plan = interpret_request(message, context_state)
    return compile_plan(execution_plan)


__all__ = [
    "ADVISORY_KEYWORDS",
    "AUTOMATION_STATUS_KEYWORDS",
    "BID_PRICE_PREDICTION_KEYWORDS",
    "CATEGORY_KEYWORDS",
    "COLLECTION_COMMAND_KEYWORDS",
    "COLLECTION_CONTEXT_KEYWORDS",
    "FOLLOWUP_CHART_KEYWORDS",
    "FOLLOWUP_DETAIL_KEYWORDS",
    "FOLLOWUP_KB_REFRESH_KEYWORDS",
    "FOLLOWUP_RANKING_KEYWORDS",
    "FOLLOWUP_RERUN_KEYWORDS",
    "FOLLOWUP_RESULT_REFERENCE_KEYWORDS",
    "FOLLOWUP_SPLITTERS",
    "FOLLOWUP_TREND_DETAIL_KEYWORDS",
    "KB_KEYWORDS",
    "KB_REFRESH_COMMAND_KEYWORDS",
    "KB_REFRESH_TARGET_KEYWORDS",
    "LLM_PLAN_DRAFT_ENV",
    "MODEL_VALIDATION_KEYWORDS",
    "PREDICTION_ACTION_KEYWORDS",
    "PREDICTION_CONTEXT_KEYWORDS",
    "REGION_KEYWORDS",
    "SEMANTIC_KEYWORDS",
    "STATISTICS_KEYWORDS",
    "STATUS_QUERY_KEYWORDS",
    "TREND_VISUAL_KEYWORDS",
    "_attempt_llm_plan_draft",
    "_build_advisory_plan",
    "_compute_requires_confirmation",
    "_default_answer_plan",
    "_extract_bid_query_params",
    "_extract_followup_category",
    "_extract_followup_region",
    "_extract_prediction_limit",
    "_extract_prediction_model_id",
    "_has_collection_command",
    "_has_collection_context_only",
    "_has_kb_refresh_intent",
    "_has_prediction_action_intent",
    "_is_bid_price_prediction_request",
    "_is_model_validation_request",
    "_llm_plan_draft_enabled",
    "_llm_system_instruction",
    "_load_last_plan",
    "_load_last_tool_results",
    "_request_llm_plan_draft",
    "_select_action",
    "_should_try_llm_plan_draft",
    "_step",
    "_validate_llm_plan_draft",
    "compile_plan",
    "interpret_request",
    "plan_chat_request",
]
