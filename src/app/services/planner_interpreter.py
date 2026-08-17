"""
src/app/services/planner_interpreter.py

챗봇 질의 해석 모듈 (1단계 interpret_request).
사용자 메시지와 대화 문맥을 ChatExecutionPlan 으로 정규화합니다.
"""

from __future__ import annotations

from typing import Any, cast

from src.app.schemas.chat import ChatExecutionPlan, ChatPlan
from src.app.services.action_catalog import ACTION_CATALOG
from src.app.services.planner_intent_signals import (
    ADVISORY_KEYWORDS,
    AUTOMATION_STATUS_KEYWORDS,
    FOLLOWUP_CHART_KEYWORDS,
    FOLLOWUP_DETAIL_KEYWORDS,
    FOLLOWUP_RANKING_KEYWORDS,
    FOLLOWUP_RERUN_KEYWORDS,
    FOLLOWUP_RESULT_REFERENCE_KEYWORDS,
    FOLLOWUP_TREND_DETAIL_KEYWORDS,
    KB_KEYWORDS,
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
    _select_action,
)
from src.rag.engine import extract_result_limit, is_result_list_query


def _load_last_plan(context_state: dict[str, Any] | None) -> ChatPlan | None:
    if not context_state:
        return None
    plan_payload = context_state.get("last_plan_json") or {}
    if not isinstance(plan_payload, dict) or not plan_payload:
        return None
    try:
        return ChatPlan.model_validate(plan_payload)
    except Exception:
        return None


def _load_last_tool_results(context_state: dict[str, Any] | None) -> dict[str, Any]:
    if not context_state:
        return {}
    tool_results = context_state.get("last_tool_results") or {}
    if isinstance(tool_results, dict) and tool_results:
        return dict(tool_results)
    payload = context_state.get("last_result_payload") or {}
    embedded = payload.get("tool_results") if isinstance(payload, dict) else {}
    return dict(embedded) if isinstance(embedded, dict) else {}


def interpret_request(
    message: str, context_state: dict[str, Any] | None = None
) -> ChatExecutionPlan:
    """
    1단계: 사용자 메시지를 고도화된 질의 해석 객체(ChatExecutionPlan)로 변환한다.
    문맥(context_state)을 참조하여 후속 질문 여부와 누적된 필터를 처리한다.
    """
    normalized = (message or "").strip().lower()
    last_query = str((context_state or {}).get("last_query") or "").strip()
    last_plan = _load_last_plan(context_state)
    last_intent_type = last_plan.intent_type if last_plan else ""
    last_action_key = str((context_state or {}).get("last_action_key") or "").strip()
    last_response_mode = str((context_state or {}).get("last_response_mode") or "").strip()
    stored_filters = dict((context_state or {}).get("last_filters_json") or {})
    last_tool_results = _load_last_tool_results(context_state)

    execution_plan = ChatExecutionPlan(
        query_type="unknown",
        original_message=message,
        effective_query=message,
        last_intent_type=last_intent_type,
        last_query=last_query,
        last_action_key=last_action_key,
        last_response_mode=last_response_mode,
        confidence=1.0,
        filters=stored_filters,
    )

    if not normalized:
        execution_plan.query_type = "answer"
        execution_plan.reasoning = "empty request"
        return execution_plan

    # 1. 후속 질문 여부 판단 및 메시지 병합
    if last_query:
        execution_plan.is_followup = True
        region = _extract_followup_region(normalized)
        _, category_code = _extract_followup_category(normalized)
        wants_detail = any(keyword in normalized for keyword in FOLLOWUP_DETAIL_KEYWORDS)
        wants_chart = any(keyword in normalized for keyword in FOLLOWUP_CHART_KEYWORDS)
        wants_rerun = any(keyword in normalized for keyword in FOLLOWUP_RERUN_KEYWORDS)
        mentions_result_reference = any(
            keyword in normalized for keyword in FOLLOWUP_RESULT_REFERENCE_KEYWORDS
        )

        if any(
            (
                region,
                category_code,
                wants_detail,
                wants_chart,
                wants_rerun,
                mentions_result_reference,
            )
        ):
            execution_plan.effective_query = f"{last_query} {message}".strip()
            if mentions_result_reference:
                execution_plan.parameters["references_last_result"] = True

    # 2. 지역/분야 필터 추출 및 누적
    region = _extract_followup_region(normalized)
    _, category_code = _extract_followup_category(normalized)
    if region:
        execution_plan.filters["institution_name"] = region
    if category_code:
        execution_plan.filters["category"] = category_code

    # 3. Advisory 판단
    if any(keyword in normalized for keyword in ADVISORY_KEYWORDS):
        execution_plan.query_type = "advisory"
        execution_plan.requested_capabilities = ["subscription_advisory"]
        execution_plan.reasoning = "advisory keywords matched"
        return execution_plan

    # 4. 특정 공고 투찰가 예측은 파이프라인 모델 검증이 아니라 내부 예측 도구로 즉시 답변한다.
    if _is_bid_price_prediction_request(normalized):
        execution_plan.query_type = "answer"
        execution_plan.requested_capabilities = ["bid_prediction_tool"]
        execution_plan.parameters["query"] = message
        if category_code:
            execution_plan.parameters["category"] = category_code
        model_id = _extract_prediction_model_id(normalized)
        if model_id:
            execution_plan.parameters["model_id"] = model_id
        execution_plan.parameters["limit"] = _extract_prediction_limit(normalized)
        execution_plan.reasoning = "bid price prediction request"
        return execution_plan

    # 5. 작업 상태 조회
    wants_status = any(keyword in normalized for keyword in STATUS_QUERY_KEYWORDS)
    wants_automation_status = any(keyword in normalized for keyword in AUTOMATION_STATUS_KEYWORDS)
    wants_status_visualization = any(keyword in normalized for keyword in FOLLOWUP_CHART_KEYWORDS)
    last_job_id = str((context_state or {}).get("last_job_id") or "")
    if wants_automation_status or (wants_status and last_job_id):
        execution_plan.query_type = "answer"
        execution_plan.job_id = last_job_id
        execution_plan.requested_capabilities = ["automation_status_tool"]
        if wants_status_visualization:
            execution_plan.response_mode = "visual"
            execution_plan.parameters["prefer_visualization"] = True
        execution_plan.reasoning = f"job status inquiry for {last_action_key or 'last job'}"
        return execution_plan

    # 6. Action(Pipeline) 판단
    matched_actions = [
        action
        for action in ACTION_CATALOG.values()
        if any(keyword in normalized for keyword in action.keywords)
    ]
    if _has_prediction_action_intent(normalized):
        if _has_collection_context_only(normalized):
            matched_actions = [
                action for action in matched_actions if action.action_key != "collect_refresh"
            ]
        if not _has_collection_command(normalized) and not any(
            action.action_key == "prediction_validate" for action in matched_actions
        ):
            matched_actions.append(ACTION_CATALOG["prediction_validate"])

    wants_kb_refresh = _has_kb_refresh_intent(normalized)
    if wants_kb_refresh or matched_actions:
        execution_plan.query_type = "action"
        if wants_kb_refresh:
            is_complex = any(
                keyword in normalized for keyword in ("다시", "차트", "그래프", "상세", "자세히")
            )
            execution_plan.action_key = "data_refresh" if is_complex else "kb_refresh"
        elif matched_actions:
            selected_action = _select_action(message, matched_actions)
            execution_plan.action_key = selected_action.action_key

        execution_plan.requested_capabilities = [execution_plan.action_key]
        execution_plan.reasoning = f"action match: {execution_plan.action_key}"
        return execution_plan

    # 7. 결과 상세 분석 및 시각화
    if is_result_list_query(normalized):
        execution_plan.query_type = "answer"
        execution_plan.requested_capabilities = ["bid_query_tool"]
        execution_plan.parameters.update(
            _extract_bid_query_params(execution_plan.effective_query, execution_plan.filters)
        )
        execution_plan.parameters["limit"] = extract_result_limit(normalized)
        execution_plan.reasoning = "recent winning result list request"
        return execution_plan

    wants_detail = any(keyword in normalized for keyword in FOLLOWUP_DETAIL_KEYWORDS)
    wants_chart = any(keyword in normalized for keyword in FOLLOWUP_CHART_KEYWORDS)
    wants_ranking = any(keyword in normalized for keyword in FOLLOWUP_RANKING_KEYWORDS)
    wants_trend_detail = any(keyword in normalized for keyword in FOLLOWUP_TREND_DETAIL_KEYWORDS)

    has_bid_query = isinstance(last_tool_results.get("bid_query"), dict)
    has_trend_analysis = isinstance(last_tool_results.get("trend_analysis"), dict)
    has_chart_memory = bool((context_state or {}).get("last_chart_payload"))

    if (wants_chart or wants_detail or wants_ranking or wants_trend_detail) and (
        has_bid_query or has_trend_analysis or has_chart_memory
    ):
        execution_plan.query_type = "answer"
        capabilities = []
        if wants_chart:
            execution_plan.response_mode = "visual"
            source = "trend_analysis" if has_trend_analysis else "bid_query"
            execution_plan.parameters["chart_source"] = source
            capabilities.append("chart_builder")

        if wants_trend_detail or (wants_detail and not has_trend_analysis and has_bid_query):
            execution_plan.parameters["trend_source"] = "bid_query"
            capabilities.append("trend_analyzer")

        if capabilities:
            execution_plan.requested_capabilities = list(dict.fromkeys(capabilities))
            execution_plan.reasoning = "conversation result-object followup refinement"
            return execution_plan

    # 8. 일반 Answer 판단
    execution_plan.query_type = "answer"
    has_statistics = any(keyword in normalized for keyword in STATISTICS_KEYWORDS)
    has_semantic = any(keyword in normalized for keyword in SEMANTIC_KEYWORDS)
    has_kb = any(keyword in normalized for keyword in KB_KEYWORDS)

    if (
        execution_plan.is_followup
        and not has_statistics
        and last_intent_type == "statistics_query"
        and (wants_detail or wants_chart or region or category_code)
    ):
        has_statistics = True

    if wants_detail:
        execution_plan.response_mode = "detailed"
    elif wants_chart:
        execution_plan.response_mode = "visual"
    elif execution_plan.is_followup and last_response_mode in ("detailed", "visual"):
        execution_plan.response_mode = cast(Any, last_response_mode)

    capabilities = []
    if has_kb and not has_statistics and not has_semantic:
        capabilities.append("kb_status_tool")
        execution_plan.reasoning = "kb status request"
    elif has_statistics:
        capabilities.append("bid_query_tool")
        if has_semantic or wants_detail:
            capabilities.append("semantic_search_tool")
        if execution_plan.response_mode == "visual" or any(
            keyword in normalized for keyword in TREND_VISUAL_KEYWORDS
        ):
            capabilities.extend(["trend_analyzer", "chart_builder"])
            execution_plan.parameters["trend_source"] = "bid_query"
            execution_plan.parameters["chart_source"] = "trend_analysis"
        execution_plan.reasoning = "statistics request"
    elif has_semantic:
        capabilities.append("semantic_search_tool")
        execution_plan.reasoning = "semantic request"
    else:
        capabilities.append("semantic_search_tool")
        execution_plan.reasoning = "default answer request"

    execution_plan.requested_capabilities = list(dict.fromkeys(capabilities))

    # 9. 파라미터 확정 (Interpretation phase parameter extraction)
    for cap in execution_plan.requested_capabilities:
        if cap == "bid_query_tool":
            bid_params = _extract_bid_query_params(
                execution_plan.effective_query, execution_plan.filters
            )
            execution_plan.parameters.update(bid_params)
        elif cap == "semantic_search_tool":
            if "query" not in execution_plan.parameters:
                execution_plan.parameters["query"] = execution_plan.effective_query
        elif cap == "automation_status_tool":
            if "job_id" not in execution_plan.parameters:
                execution_plan.parameters["job_id"] = execution_plan.job_id

    return execution_plan


__all__ = [
    "_load_last_plan",
    "_load_last_tool_results",
    "interpret_request",
]
