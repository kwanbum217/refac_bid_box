"""
src/app/services/automation_responses.py

자동화 응답 문안, 진행 상황 안내, 시각화 및 결과 페이로드 빌더 모듈.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.models.chatbot import AutomationRequest, PipelineExecution
from src.app.schemas.chat import ChatPlan, PlanStep
from src.app.services.action_catalog import DEFAULT_POLL_AFTER_MS, get_action
from src.app.services.automation_callbacks import _callback_metadata, _callback_status_lines
from src.app.services.automation_tokens import make_confirmation_token
from src.app.services.capability_registry import get_capability
from src.app.services.result_presenter import (
    build_presentable_result_payload,
    build_terminal_answer,
    build_visualizations,
)

STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"


@dataclass
class AutomationResponse:
    mode: str
    intent: str
    message: str
    answer: str
    suggestions: list[str]
    job: dict
    visualizations: list[dict]
    result_payload: dict
    confirmation_token: str


def _load_plan_from_request_payload(request_obj: AutomationRequest) -> ChatPlan | None:
    plan_payload = dict(request_obj.payload or {}).get("plan")
    if not isinstance(plan_payload, dict):
        return None
    try:
        return ChatPlan.model_validate(plan_payload)
    except Exception:
        return None


def _get_pipeline_step(plan: ChatPlan | None) -> PlanStep | None:
    if not plan:
        return None
    for step in plan.steps:
        if step.kind == "pipeline":
            return step
    return None


def _get_pipeline_execution(
    db: Session, request_obj: AutomationRequest
) -> PipelineExecution | None:
    execution_key = request_obj.plan_execution_id or request_obj.harness_execution_id
    if not execution_key:
        return None
    return db.execute(
        select(PipelineExecution)
        .where(PipelineExecution.execution_id == execution_key)
        .order_by(PipelineExecution.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _step_status_lines(request_obj: AutomationRequest) -> list[str]:
    steps = (request_obj.result_payload or {}).get("steps") or {}
    if not isinstance(steps, dict) or not steps:
        return []

    lines = ["", "Step 진행 상황:"]
    ordered_names = ("preflight", "collect", "rag", "predict", "inspect", "final")
    ordered_steps = [name for name in ordered_names if name in steps]
    ordered_steps.extend(name for name in steps if name not in ordered_steps)
    for step_name in ordered_steps:
        step_payload = steps.get(step_name) or {}
        if not isinstance(step_payload, dict):
            continue
        summary = step_payload.get("summary") or ""
        suffix = f" / {summary}" if summary else ""
        lines.append(f"- {step_name}: `{step_payload.get('status') or '-'}`{suffix}")
    return lines


def _job_payload(
    db: Session,
    request_obj: AutomationRequest,
    pipeline_execution: PipelineExecution | None = None,
) -> dict[str, Any]:
    pipeline_execution = pipeline_execution or _get_pipeline_execution(db, request_obj)
    action = get_action(request_obj.action_key)
    plan = _load_plan_from_request_payload(request_obj)
    pipeline_step = _get_pipeline_step(plan)
    capability = get_capability(pipeline_step.tool) if pipeline_step else None
    run_mode = (
        pipeline_execution.run_mode
        if pipeline_execution
        else (action.run_mode if action else (capability.run_mode if capability else ""))
    )
    pipeline_id = request_obj.pipeline_name or (
        action.pipeline_id if action else (capability.pipeline_id if capability else "")
    )
    callback_metadata = _callback_metadata(request_obj)
    return {
        "job_id": str(request_obj.request_id),
        "action_key": request_obj.action_key,
        "pipeline_id": pipeline_id,
        "pipeline": pipeline_id,
        "run_mode": run_mode,
        "plan_execution_id": request_obj.plan_execution_id,
        "execution_id": request_obj.harness_execution_id or request_obj.plan_execution_id,
        "execution_url": request_obj.execution_url
        or (pipeline_execution.external_url if pipeline_execution else ""),
        "status": request_obj.status,
        "stage_name": pipeline_execution.stage_name if pipeline_execution else "",
        "stage_status": pipeline_execution.stage_status if pipeline_execution else "",
        "result_summary": request_obj.result_summary,
        "error_message": request_obj.error_message,
        "poll_after_ms": DEFAULT_POLL_AFTER_MS,
        "requires_confirmation": request_obj.requires_confirmation and not request_obj.confirmed_at,
        "callback_mode": callback_metadata["callback_mode"],
        "callback_configured": callback_metadata["callback_configured"],
        "callback_reason": callback_metadata["callback_reason"],
    }


def _build_in_progress_answer(request_obj: AutomationRequest) -> str:
    lines = [
        "요청이 접수되었습니다.",
        f"- 작업: `{request_obj.action_key or request_obj.intent_type}`",
        f"- 파이프라인: `{request_obj.pipeline_name or '-'}`",
        f"- 상태: `{request_obj.status}`",
        f"- Job ID: `{request_obj.request_id}`",
    ]
    lines.extend(_callback_status_lines(request_obj))
    lines.extend(_step_status_lines(request_obj))
    if request_obj.plan_execution_id:
        lines.append(f"- Plan Execution ID: `{request_obj.plan_execution_id}`")
    if request_obj.execution_url:
        lines.append(f"- 실행 URL: `{request_obj.execution_url}`")
    return "\n".join(lines)


def _build_confirmation_answer(db: Session, request_obj: AutomationRequest) -> str:
    action = get_action(request_obj.action_key)
    display_name = (
        action.display_name if action else (request_obj.action_key or request_obj.intent_type)
    )
    run_mode = action.run_mode if action else (_job_payload(db, request_obj).get("run_mode") or "-")
    lines = [
        "고비용 자동화로 분류되어 실행 확인이 필요합니다.",
        f"- 작업: `{display_name}`",
        f"- 실행 모드: `{run_mode}`",
        f"- Job ID: `{request_obj.request_id}`",
    ]
    lines.extend(_callback_status_lines(request_obj))
    lines.extend(["", "아래 확인 버튼을 누르거나 confirmation API를 호출하면 실행됩니다."])
    return "\n".join(lines)


def _build_failure_answer(request_obj: AutomationRequest) -> str:
    lines = ["자동화 실행에 실패했습니다."]
    if request_obj.result_summary:
        lines.append(request_obj.result_summary)
    metadata = _callback_metadata(request_obj)
    if metadata["callback_mode"] == "polling" and metadata["callback_reason"]:
        lines.append(metadata["callback_reason"])
    if request_obj.error_message:
        lines.append(f"오류: {request_obj.error_message}")
    return "\n".join(lines)


def _build_canceled_answer(request_obj: AutomationRequest) -> str:
    lines = ["요청을 중지했습니다."]
    if request_obj.result_summary:
        lines.append(request_obj.result_summary)
    if request_obj.plan_execution_id:
        lines.append(f"Plan Execution ID: `{request_obj.plan_execution_id}`")
    if request_obj.error_message:
        lines.append(f"안내: {request_obj.error_message}")
    return "\n".join(lines)


def build_action_response(db: Session, request_obj: AutomationRequest) -> dict[str, Any]:
    pipeline_execution = _get_pipeline_execution(db, request_obj)
    presentable_result_payload = build_presentable_result_payload(request_obj.result_payload)

    if request_obj.status == STATUS_CANCELED:
        mode = "error"
        answer = _build_canceled_answer(request_obj)
        message = request_obj.result_summary or "요청이 중지되었습니다."
        suggestions = ["다시 시도하기"]
        # 비밀번호가 아니라 확인 토큰 없음 표시입니다
        confirmation_token = ""  # nosec B105
        visualizations: list[dict] = []
    elif request_obj.requires_confirmation and not request_obj.confirmed_at:
        mode = "confirmation"
        answer = _build_confirmation_answer(db, request_obj)
        message = "고비용 실행 확인이 필요합니다."
        suggestions = ["실행 확인", "실행 상태 보기"]
        confirmation_token = make_confirmation_token(str(request_obj.request_id))
        visualizations = []
    elif request_obj.status == STATUS_SUCCESS:
        mode = "result"
        answer = build_terminal_answer(request_obj)
        message = request_obj.result_summary or "자동화 작업이 완료되었습니다."
        suggestions = [
            "자동화 결과 요약 보기",
            "그래프로 다시 보기",
            *presentable_result_payload.get("recommended_actions", [])[:2],
        ]
        # 비밀번호가 아니라 확인 토큰 없음 표시입니다
        confirmation_token = ""  # nosec B105
        visualizations = build_visualizations(request_obj.result_payload)
    elif request_obj.status == STATUS_FAILED:
        mode = "error"
        answer = _build_failure_answer(request_obj)
        message = request_obj.result_summary or "자동화 작업이 실패했습니다."
        suggestions = [
            "실행 상태 보기",
            "다시 시도하기",
            *presentable_result_payload.get("recommended_actions", [])[:2],
        ]
        # 비밀번호가 아니라 확인 토큰 없음 표시입니다
        confirmation_token = ""  # nosec B105
        visualizations = build_visualizations(request_obj.result_payload)
    else:
        mode = "action" if request_obj.status == STATUS_RUNNING else "progress"
        answer = _build_in_progress_answer(request_obj)
        message = request_obj.result_summary or "자동화 작업이 등록되었습니다."
        suggestions = ["실행 상태 보기", "자동화 결과 요약 보기"]
        # 비밀번호가 아니라 확인 토큰 없음 표시입니다
        confirmation_token = ""  # nosec B105
        visualizations = []

    return asdict(
        AutomationResponse(
            mode=mode,
            intent=request_obj.intent_type,
            message=message,
            answer=answer,
            suggestions=suggestions,
            job=_job_payload(db, request_obj, pipeline_execution=pipeline_execution),
            visualizations=visualizations,
            result_payload=presentable_result_payload,
            confirmation_token=confirmation_token,
        )
    )
