"""
src/app/services/planner.py

챗봇 2단계 플래너 (원본 apps/chatbot/services/planner.py 1:1 이식).
1단계 interpret_request 가 사용자 메시지를 ChatExecutionPlan 으로 정규화하고,
2단계 compile_plan 이 실행 가능한 ChatPlan(PlanStep 목록)으로 컴파일합니다.
"""

from __future__ import annotations

import json
import os
from typing import Any, Literal, cast

from src.app.schemas.chat import ChatExecutionPlan, ChatPlan, PlanStep
from src.app.services.action_catalog import ACTION_CATALOG, DEFAULT_POLL_AFTER_MS
from src.app.services.capability_registry import CAPABILITY_REGISTRY, get_capability
from src.rag.engine import extract_result_limit, is_result_list_query

LLM_PLAN_DRAFT_ENV = "CHATBOT_ENABLE_LLM_PLAN_DRAFT"

ADVISORY_KEYWORDS = ("매일", "매주", "알림", "구독", "자동으로", "정기")
STATISTICS_KEYWORDS = (
    "통계",
    "평균",
    "추세",
    "비교",
    "건수",
    "낙찰률",
    "경쟁률",
    "집계",
    "그래프",
    "차트",
    "흐름",
)
SEMANTIC_KEYWORDS = (
    "최근",
    "여부",
    "상세",
    "자세히",
    "설명",
    "왜",
    "특징",
    "문맥",
    "무엇",
    "어떤",
    "원인",
    "리스크",
)
KB_KEYWORDS = ("kb", "지식베이스", "벡터", "임베딩", "인덱스", "색인")
FOLLOWUP_SPLITTERS = ("그리고", "필요하면", "이상하면", "같이", "함께")
CATEGORY_KEYWORDS = {
    "공사": "Cnstwk",
    "물품": "Thng",
    "용역": "Servc",
    "외자": "Frgcpt",
}
REGION_KEYWORDS = (
    "서울",
    "부산",
    "대구",
    "인천",
    "광주",
    "대전",
    "울산",
    "세종",
    "경기",
    "강원",
    "충북",
    "충남",
    "전북",
    "전남",
    "경북",
    "경남",
    "제주",
)
FOLLOWUP_DETAIL_KEYWORDS = ("자세히", "더 자세히", "좀 더", "왜", "설명")
FOLLOWUP_CHART_KEYWORDS = ("그래프", "차트", "시각화")
FOLLOWUP_RERUN_KEYWORDS = ("다시", "이번엔", "이번에는", "방금", "그 결과", "재실행")
FOLLOWUP_KB_REFRESH_KEYWORDS = (
    "kb 갱신",
    "kb 업데이트",
    "kb 최신화",
    "지식베이스 갱신",
    "지식베이스 업데이트",
    "지식베이스 최신화",
    "벡터 갱신",
    "벡터 업데이트",
    "벡터 최신화",
    "임베딩 갱신",
    "임베딩 업데이트",
    "임베딩 최신화",
    "인덱스 갱신",
    "인덱스 업데이트",
    "인덱스 최신화",
    "색인 갱신",
    "색인 업데이트",
    "색인 최신화",
)
KB_REFRESH_TARGET_KEYWORDS = ("kb", "지식베이스", "벡터", "임베딩", "인덱스", "색인")
KB_REFRESH_COMMAND_KEYWORDS = ("갱신", "업데이트", "최신화", "재생성", "다시 구축", "새로 구축")
FOLLOWUP_RESULT_REFERENCE_KEYWORDS = (
    "그 결과",
    "방금 결과",
    "이전 결과",
    "그 차트",
    "방금 차트",
    "이 그래프",
    "결과",
    "상태",
    "성공",
    "실패",
)
FOLLOWUP_RANKING_KEYWORDS = ("상위 업체", "상위 낙찰업체", "top 업체", "우승 업체", "많이 나온 업체")
FOLLOWUP_TREND_DETAIL_KEYWORDS = (
    "감소한 구간",
    "하락 구간",
    "상승 구간",
    "피크",
    "최고 구간",
    "최저 구간",
    "변동폭",
)
TREND_VISUAL_KEYWORDS = ("추세", "흐름", "변동", "그래프", "차트", "시각화")
STATUS_QUERY_KEYWORDS = ("상태", "성공", "실패", "결과", "완료", "어떻게 됐어", "다 됐어")
AUTOMATION_STATUS_KEYWORDS = (
    "진행 상황",
    "진행상황",
    "점검 진행",
    "현재 점검",
    "실행 상태",
    "자동화 상태",
    "작업 상태",
    "방금 점검",
    "방금 실행",
    "전체 점검 최종",
)
PREDICTION_CONTEXT_KEYWORDS = (
    "예측",
    "투찰가",
    "투찰 금액",
    "입찰가",
    "낙찰가",
    "모델",
    "v13",
    "v25",
    "ssh_hist_premium",
    "quantum_leap",
)
PREDICTION_ACTION_KEYWORDS = (
    "예측해",
    "예측 해",
    "예측 실행",
    "예측 돌려",
    "예측 다시",
    "예측 재실행",
    "투찰가",
    "투찰 금액",
    "입찰가",
    "모델 검증",
    "검증해",
    "품질 기준",
    "기준 미달",
)
MODEL_VALIDATION_KEYWORDS = (
    "모델 검증",
    "예측 모델 검증",
    "품질 기준",
    "기준 미달",
    "성능 검증",
    "acceptance",
)
BID_PRICE_PREDICTION_KEYWORDS = (
    "투찰가",
    "투찰 금액",
    "투찰금액",
    "입찰가",
    "낙찰가",
)
COLLECTION_COMMAND_KEYWORDS = (
    "수집해",
    "수집하",
    "수집 실행",
    "수집 돌려",
    "수집하고",
    "데이터 수집",
    "입찰 수집",
    "공고 수집",
    "공고 업데이트",
    "신규 공고 반영",
)
COLLECTION_CONTEXT_KEYWORDS = ("수집된", "수집한", "수집 완료")


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


def _extract_bid_query_params(message: str, filters: dict[str, Any] | None = None) -> dict[str, Any]:
    params: dict[str, Any] = {"query": message, "years": 5}
    lowered = message.lower()

    if filters:
        for key in ("category", "institution_name", "years", "date_from", "date_to"):
            if key in filters:
                params[key] = filters[key]

    if "category" not in params:
        for keyword, category in CATEGORY_KEYWORDS.items():
            if keyword in lowered:
                params["category"] = category
                break

    if "years" not in params and any(kw in lowered for kw in ("최근", "요즘", "이번")):
        params["years"] = 1

    return params


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


def _extract_followup_region(message: str) -> str:
    normalized = (message or "").strip().lower()
    for region in REGION_KEYWORDS:
        if region in normalized:
            return region
    return ""


def _extract_followup_category(message: str) -> tuple[str, str]:
    normalized = (message or "").strip().lower()
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in normalized:
            return keyword, category
    return "", ""


def _has_prediction_action_intent(message: str) -> bool:
    has_prediction_context = any(keyword in message for keyword in PREDICTION_CONTEXT_KEYWORDS)
    has_prediction_command = any(keyword in message for keyword in PREDICTION_ACTION_KEYWORDS)
    return has_prediction_context and has_prediction_command


def _has_collection_command(message: str) -> bool:
    return any(keyword in message for keyword in COLLECTION_COMMAND_KEYWORDS)


def _has_collection_context_only(message: str) -> bool:
    return any(
        keyword in message for keyword in COLLECTION_CONTEXT_KEYWORDS
    ) and not _has_collection_command(message)


def _is_model_validation_request(message: str) -> bool:
    return any(keyword in message for keyword in MODEL_VALIDATION_KEYWORDS)


def _is_bid_price_prediction_request(message: str) -> bool:
    has_price_target = any(keyword in message for keyword in BID_PRICE_PREDICTION_KEYWORDS)
    has_prediction_signal = any(keyword in message for keyword in PREDICTION_CONTEXT_KEYWORDS)
    return has_price_target and has_prediction_signal and not _is_model_validation_request(message)


def _extract_prediction_model_id(message: str) -> str:
    if "quantum_leap_v25_pro" in message or "quantum leap" in message:
        return "quantum_leap_v25_pro"
    if "ssh_hist_premium" in message or "ssh" in message:
        return "ssh_hist_premium"
    if "v13_hybrid" in message or "v13" in message:
        return "v13_hybrid"
    if "v25" in message:
        return "v25"
    return ""


def _extract_prediction_limit(message: str) -> int:
    try:
        from src.app.services.tools.bid_prediction_tool import coerce_limit
    except ImportError:
        return 1
    return coerce_limit(0, message)


def _select_action(message: str, matched_actions: list) -> Any:
    wants_visual_answer = any(
        keyword in message for keyword in ("그래프", "차트", "시각화", "보여줘", "분석")
    )
    selected_action = matched_actions[0]
    if wants_visual_answer and any(
        action.action_key == "data_refresh" for action in matched_actions
    ):
        return ACTION_CATALOG["data_refresh"]
    if wants_visual_answer and selected_action.action_key in {"collect_refresh", "kb_refresh"}:
        return ACTION_CATALOG["data_refresh"]
    if len(matched_actions) > 1:
        return ACTION_CATALOG["full_validation"]
    return selected_action


def _has_kb_refresh_intent(message: str) -> bool:
    normalized = message or ""
    if any(keyword in normalized for keyword in FOLLOWUP_KB_REFRESH_KEYWORDS):
        return True
    has_target = any(keyword in normalized for keyword in KB_REFRESH_TARGET_KEYWORDS)
    has_command = any(keyword in normalized for keyword in KB_REFRESH_COMMAND_KEYWORDS)
    return has_target and has_command


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
    except Exception:
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
