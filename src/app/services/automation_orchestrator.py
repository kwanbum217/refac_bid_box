"""
src/app/services/automation_orchestrator.py

자동화 실행 오케스트레이터 (원본 apps/chatbot/services/automation_orchestrator.py 이식).

원본은 Harness 파이프라인을 트리거했습니다. 리팩토링본은 실행 백엔드만 Arq 태스크 큐로
교체하되, 요청 레코드(automation_requests)와 실행 이력(pipeline_executions)의 상태 전이,
확인 토큰 규약, 응답 페이로드 계약은 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.chatbot import AutomationRequest, PipelineExecution
from src.app.schemas.chat import ChatPlan, PlanStep
from src.app.services.action_catalog import DEFAULT_POLL_AFTER_MS, get_action
from src.app.services.automation_callbacks import (
    CALLBACK_PATH_TEMPLATE,
    CallbackDelivery,
    _callback_metadata,
    _callback_status_lines,
    _is_worker_unreachable_host,
    resolve_callback_delivery,
)
from src.app.services.automation_jobs import (
    RUN_MODE_TASKS,
    _enqueue_arq_job,
    _run_arq_coroutine,
    abort_arq_job,
    enqueue_pipeline_run,
)
from src.app.services.automation_responses import (
    AutomationResponse,
    _build_canceled_answer,
    _build_confirmation_answer,
    _build_failure_answer,
    _build_in_progress_answer,
    _get_pipeline_execution,
    _get_pipeline_step,
    _job_payload,
    _load_plan_from_request_payload,
    _step_status_lines,
    build_action_response,
)
from src.app.services.automation_tokens import (
    CALLBACK_SALT,
    CONFIRMATION_MAX_AGE,
    CONFIRMATION_SALT,
    AutomationError,
    _sign,
    _unsign,
    make_callback_token,
    make_confirmation_token,
    resolve_confirmation_token,
    verify_callback_token,
)
from src.app.services.capability_registry import get_capability

logger = logging.getLogger(__name__)

# 원본 AutomationRequest.Status 값 그대로
STATUS_PENDING_CONFIRMATION = "pending_confirmation"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"
TERMINAL_STATUSES = {STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELED}

# 최근 성공 이력을 재사용할 고비용 작업 (원본 REUSABLE_STAGING_ACTIONS 동일)
REUSABLE_ACTIONS = {"full_validation"}
REUSE_MAX_AGE_HOURS = 72

__all__ = [
    "CALLBACK_PATH_TEMPLATE",
    "CALLBACK_SALT",
    "CONFIRMATION_MAX_AGE",
    "CONFIRMATION_SALT",
    "REUSABLE_ACTIONS",
    "REUSE_MAX_AGE_HOURS",
    "RUN_MODE_TASKS",
    "STATUS_CANCELED",
    "STATUS_FAILED",
    "STATUS_PENDING_CONFIRMATION",
    "STATUS_QUEUED",
    "STATUS_RUNNING",
    "STATUS_SUCCESS",
    "TERMINAL_STATUSES",
    "AutomationError",
    "AutomationResponse",
    "CallbackDelivery",
    "_attach_reused_execution",
    "_build_canceled_answer",
    "_build_confirmation_answer",
    "_build_failure_answer",
    "_build_in_progress_answer",
    "_callback_metadata",
    "_callback_status_lines",
    "_enqueue_arq_job",
    "_find_reusable_execution",
    "_get_pipeline_execution",
    "_get_pipeline_step",
    "_is_worker_unreachable_host",
    "_job_payload",
    "_load_plan_from_request_payload",
    "_run_arq_coroutine",
    "_sign",
    "_step_status_lines",
    "_try_reuse_recent_execution",
    "_unsign",
    "abort_arq_job",
    "apply_callback_payload",
    "build_action_response",
    "build_confirmation_from_plan",
    "cancel_automation_request",
    "confirm_automation_request",
    "create_action_request",
    "create_automation_request",
    "enqueue_pipeline_run",
    "get_automation_request",
    "make_callback_token",
    "make_confirmation_token",
    "plan_requires_confirmation",
    "resolve_callback_delivery",
    "resolve_confirmation_token",
    "start_automation_request",
    "sync_automation_status",
    "verify_callback_token",
]


# --------------------------------------------------------------------------- #
# 조회 헬퍼
# --------------------------------------------------------------------------- #


def get_automation_request(db: Session, job_id: str) -> AutomationRequest | None:
    return db.execute(
        select(AutomationRequest).where(AutomationRequest.request_id == str(job_id))
    ).scalar_one_or_none()


def plan_requires_confirmation(plan: ChatPlan) -> bool:
    return any(step.requires_confirmation for step in plan.steps)


def build_confirmation_from_plan(plan: ChatPlan) -> dict[str, Any]:
    return {
        "primary_action_key": plan.primary_action_key,
        "requires_confirmation": plan_requires_confirmation(plan),
        "steps": [step.model_dump() for step in plan.steps],
    }


# --------------------------------------------------------------------------- #
# 생명주기
# --------------------------------------------------------------------------- #


def create_automation_request(
    db: Session,
    *,
    plan: ChatPlan,
    message: str,
    user_id: int,
    payload: dict[str, Any] | None = None,
) -> AutomationRequest:
    """automation_requests.user_id 는 NOT NULL 입니다. 익명 요청은 만들 수 없습니다."""
    action = get_action(plan.primary_action_key)
    pipeline_step = _get_pipeline_step(plan)
    capability = get_capability(pipeline_step.tool) if pipeline_step else None
    requires_confirmation = plan_requires_confirmation(plan)

    # 콜백 URL 에 job_id 가 들어가므로 레코드 생성 전에 확정합니다.
    request_id = str(uuid.uuid4())
    request_payload = dict(payload or {})
    request_payload["plan"] = plan.model_dump()
    request_payload.update(resolve_callback_delivery(request_id).as_payload())

    request_obj = AutomationRequest(
        request_id=request_id,
        user_id=user_id,
        intent_type=plan.intent_type,
        action_key=plan.primary_action_key,
        requested_text=message,
        followup_query=plan.followup_query,
        payload=request_payload,
        pipeline_name=action.pipeline_id
        if action
        else (capability.pipeline_id if capability else ""),
        status=STATUS_PENDING_CONFIRMATION if requires_confirmation else STATUS_QUEUED,
        requires_confirmation=requires_confirmation,
        result_summary="고비용 실행 확인 대기 중입니다." if requires_confirmation else "",
    )
    db.add(request_obj)
    db.commit()
    db.refresh(request_obj)

    if requires_confirmation:
        return request_obj

    return start_automation_request(db, request_obj)


def create_action_request(
    db: Session,
    *,
    action_key: str,
    message: str,
    user_id: int,
    payload: dict[str, Any] | None = None,
) -> AutomationRequest:
    action = get_action(action_key)
    if not action:
        raise AutomationError(f"Unknown action_key: {action_key}")

    capability = get_capability(action.action_key)
    if capability is None:
        raise AutomationError(f"Unknown capability: {action.action_key}")

    plan = ChatPlan(
        mode="action",
        intent_type=action.intent,
        primary_action_key=action.action_key,
        requires_confirmation=action.high_cost,
        followup_query=message if action.followup_after_completion else "",
        reason=f"direct action: {action.action_key}",
        suggestions=["실행 상태 보기"],
        poll_after_ms=DEFAULT_POLL_AFTER_MS,
        steps=[
            PlanStep(
                step_id="s1",
                kind="pipeline",
                tool=action.action_key,
                params={"run_mode": action.run_mode},
                mutating=capability.mutating,
                requires_confirmation=capability.requires_confirmation,
                output_key="pipeline",
            )
        ],
    )
    return create_automation_request(
        db, plan=plan, message=message, user_id=user_id, payload=payload
    )


def start_automation_request(db: Session, request_obj: AutomationRequest) -> AutomationRequest:
    plan = _load_plan_from_request_payload(request_obj)
    pipeline_step = _get_pipeline_step(plan)
    action_key = request_obj.action_key or (pipeline_step.tool if pipeline_step else "")
    action = get_action(action_key)

    if not action and not pipeline_step:
        # action_key 가 비어 있는 것과 카탈로그에 없는 것은 다릅니다. 후자는
        # 잘못된 요청이며, 이를 성공으로 종결하면 오타 하나가 완료로 기록됩니다.
        if action_key:
            request_obj.status = STATUS_FAILED
            request_obj.result_summary = f"등록되지 않은 액션입니다: {action_key}"
        else:
            request_obj.status = STATUS_SUCCESS
            request_obj.result_summary = "실행 파이프라인이 필요하지 않은 요청입니다."
        request_obj.completed_at = utcnow()
        db.commit()
        db.refresh(request_obj)
        return request_obj

    if request_obj.requires_confirmation and not request_obj.confirmed_at:
        return request_obj

    capability = get_capability(action_key)
    run_mode = action.run_mode if action else (capability.run_mode if capability else "manual_full")
    pipeline_name = request_obj.pipeline_name or (action.pipeline_id if action else "")

    # callback 모드일 때만 워커가 HTTP 로 보고합니다. direct/polling 이면 빈 값을
    # 넘겨 워커가 DB 에 직접 기록하도록 둡니다.
    delivery = _callback_metadata(request_obj)
    callback_url = delivery["callback_url"] if delivery["callback_mode"] == "callback" else ""

    trigger = enqueue_pipeline_run(
        db=db,
        action_key=action_key,
        run_mode=run_mode,
        pipeline_name=pipeline_name,
        original_query=request_obj.followup_query or request_obj.requested_text,
        automation_request_id=str(request_obj.request_id),
        callback_url=callback_url,
        callback_token=make_callback_token(str(request_obj.request_id)) if callback_url else "",
        enqueue_fn=_enqueue_arq_job,
    )

    request_obj.plan_execution_id = trigger["execution_id"]
    request_obj.harness_execution_id = trigger["execution_id"]
    request_obj.started_at = utcnow()
    if trigger["enqueued"]:
        request_obj.status = STATUS_RUNNING
        request_obj.result_summary = "자동화 작업이 실행 큐에 등록되었습니다."
    else:
        request_obj.status = STATUS_FAILED
        request_obj.completed_at = utcnow()
        request_obj.result_summary = "자동화 작업 등록에 실패했습니다."
        request_obj.error_message = "Arq 브로커(Redis)에 연결하지 못했습니다."
    db.commit()
    db.refresh(request_obj)
    return request_obj


def _find_reusable_execution(
    db: Session, *, pipeline_name: str, run_mode: str
) -> PipelineExecution | None:
    """원본 _find_local_reusable_pipeline_execution 대응.

    같은 파이프라인에서 run_mode 가 정확히 일치하는 최근 성공 실행을 찾습니다.
    신선도 창을 벗어난 이력은 재사용하지 않습니다.

    run_mode 는 필수입니다. 빈 값을 허용하면 필터가 사라져 아무 실행이나
    걸리는데, 여러 액션이 같은 pipeline_id 를 공유하므로 그 순간 무엇을
    실행했는지 구별할 수 없게 됩니다.
    """
    if not pipeline_name or not run_mode or REUSE_MAX_AGE_HOURS <= 0:
        return None

    stmt = select(PipelineExecution).where(
        PipelineExecution.pipeline_name == pipeline_name,
        PipelineExecution.status == STATUS_SUCCESS,
        PipelineExecution.run_mode == run_mode,
    )
    stmt = stmt.order_by(
        PipelineExecution.ended_at.desc(),
        PipelineExecution.started_at.desc(),
        PipelineExecution.created_at.desc(),
    ).limit(20)

    cutoff = utcnow() - timedelta(hours=REUSE_MAX_AGE_HOURS)
    for execution in db.execute(stmt).scalars().all():
        reference_time = execution.ended_at or execution.started_at or execution.created_at
        if reference_time and reference_time >= cutoff:
            return execution
    return None


def _attach_reused_execution(
    db: Session,
    request_obj: AutomationRequest,
    execution: PipelineExecution,
    *,
    requested_run_mode: str,
    exact_run_mode: bool,
) -> AutomationRequest:
    """원본 _attach_reused_pipeline_execution 대응. 새 실행 없이 기존 결과에 연결합니다."""
    payload = dict(request_obj.payload or {})
    payload.update(
        {
            "reuse_mode": "recent_execution",
            "reused_execution_id": execution.execution_id,
            "reused_run_mode": execution.run_mode,
            "requested_run_mode": requested_run_mode,
            "reuse_exact_run_mode": exact_run_mode,
        }
    )
    run_mode_label = execution.run_mode or "manual_full"
    if exact_run_mode:
        summary = f"최근 성공한 자동화 실행({run_mode_label}) 결과를 재사용했습니다."
    else:
        summary = (
            f"요청한 `{requested_run_mode}` 성공 이력은 최근 범위에 없어 "
            f"최근 성공한 자동화 실행(`{run_mode_label}`) 결과를 재사용했습니다."
        )

    request_obj.payload = payload
    request_obj.plan_execution_id = execution.execution_id
    request_obj.harness_execution_id = execution.execution_id
    request_obj.execution_url = execution.external_url or ""
    request_obj.started_at = execution.started_at or request_obj.started_at or utcnow()
    request_obj.completed_at = execution.ended_at or utcnow()
    request_obj.status = STATUS_SUCCESS
    request_obj.result_summary = summary
    request_obj.result_payload = {
        "summary": summary,
        "outline": execution.raw_status_payload or {},
        "sync_mode": "reused_recent_execution",
        "reused_execution": {
            "execution_id": execution.execution_id,
            "pipeline_name": execution.pipeline_name,
            "run_mode": execution.run_mode,
            "requested_run_mode": requested_run_mode,
            "status": execution.status,
            "started_at": execution.started_at.isoformat() if execution.started_at else None,
            "ended_at": execution.ended_at.isoformat() if execution.ended_at else None,
            "external_url": execution.external_url or "",
        },
    }
    db.commit()
    db.refresh(request_obj)
    return request_obj


def _try_reuse_recent_execution(
    db: Session, request_obj: AutomationRequest
) -> AutomationRequest | None:
    """고비용 작업은 최근 성공 이력이 있으면 새로 돌리지 않습니다 (원본 동일).

    원본은 Harness 클라우드 이력도 함께 조회했습니다. 이식본은 워커가 로컬이라
    pipeline_executions 가 유일한 진실 원천이므로 DB 조회만 수행합니다.
    """
    if request_obj.action_key not in REUSABLE_ACTIONS or not settings.AUTOMATION_REUSE_RECENT:
        return None

    action = get_action(request_obj.action_key)
    requested_run_mode = action.run_mode if action else ""
    pipeline_name = request_obj.pipeline_name or (action.pipeline_id if action else "")
    if not pipeline_name or not requested_run_mode:
        return None

    # run_mode 가 다른 이력으로 대체하지 않습니다. action_catalog 의 7개 액션이
    # 모두 같은 pipeline_id 를 공유하므로, 대체를 허용하면 collect_only 성공
    # 하나로 full_validation 이 아무것도 검증하지 않고 성공으로 보고됩니다.
    exact = _find_reusable_execution(db, pipeline_name=pipeline_name, run_mode=requested_run_mode)
    if exact is None:
        return None
    return _attach_reused_execution(
        db, request_obj, exact, requested_run_mode=requested_run_mode, exact_run_mode=True
    )


def confirm_automation_request(db: Session, request_obj: AutomationRequest) -> AutomationRequest:
    if request_obj.confirmed_at:
        return request_obj
    request_obj.confirmed_at = utcnow()
    request_obj.status = STATUS_QUEUED
    request_obj.result_summary = "실행 확인이 완료되었습니다."
    db.commit()
    db.refresh(request_obj)

    reused = _try_reuse_recent_execution(db, request_obj)
    if reused is not None:
        return reused

    return start_automation_request(db, request_obj)


def cancel_automation_request(db: Session, request_obj: AutomationRequest) -> AutomationRequest:
    if request_obj.status in TERMINAL_STATUSES:
        return request_obj

    execution = _get_pipeline_execution(db, request_obj)
    running = bool(execution and execution.status in {STATUS_QUEUED, STATUS_RUNNING})

    # 원본은 Harness abort API 를 호출했습니다. 이식본은 같은 자리에서 Arq 작업을
    # 중단합니다. 확인 대기 등 아직 큐에 들어가지 않은 건은 호출하지 않습니다.
    arq_job_id = (
        str((execution.raw_status_payload or {}).get("arq_job_id") or "") if execution else ""
    )
    abort_succeeded = abort_arq_job(arq_job_id) if (running and arq_job_id) else False

    payload = dict(request_obj.payload or {})
    payload["canceled_by_user"] = {
        "requested_at": utcnow().isoformat(),
        "plan_execution_id": request_obj.plan_execution_id,
        "arq_job_id": arq_job_id,
        "worker_abort_requested": abort_succeeded,
    }
    request_obj.payload = payload
    request_obj.status = STATUS_CANCELED
    request_obj.completed_at = utcnow()
    request_obj.result_summary = "사용자 요청으로 분석 실행을 중지했습니다."
    request_obj.error_message = ""

    if running:
        raw_payload = dict(execution.raw_status_payload or {})
        raw_payload["canceled_by_user"] = payload["canceled_by_user"]
        execution.raw_status_payload = raw_payload
        execution.status = STATUS_FAILED
        execution.stage_status = STATUS_CANCELED
        execution.ended_at = utcnow()
        execution.logs_summary = "사용자 요청으로 중지되었습니다."

    db.commit()
    db.refresh(request_obj)
    return request_obj


def sync_automation_status(db: Session, request_obj: AutomationRequest) -> AutomationRequest:
    """pipeline_executions 의 최신 상태를 요청 레코드에 반영합니다."""
    if request_obj.status in TERMINAL_STATUSES or request_obj.status == STATUS_PENDING_CONFIRMATION:
        return request_obj
    execution = _get_pipeline_execution(db, request_obj)
    if execution is None:
        return request_obj

    request_obj.status = execution.status
    request_obj.execution_url = execution.external_url or request_obj.execution_url
    if execution.status in TERMINAL_STATUSES and not request_obj.completed_at:
        request_obj.completed_at = execution.ended_at or utcnow()
    if execution.logs_summary and not request_obj.result_summary:
        request_obj.result_summary = execution.logs_summary
    db.commit()
    db.refresh(request_obj)
    return request_obj


def apply_callback_payload(
    db: Session, request_obj: AutomationRequest, payload: dict[str, Any]
) -> AutomationRequest:
    """워커가 보고한 단계별 결과를 요청 레코드에 누적합니다 (원본 계약 동일)."""
    step = str(payload.get("step") or "unknown")
    status = str(payload.get("status") or "queued").lower()
    summary = str(payload.get("summary") or "")
    metrics = payload.get("metrics") or {}
    artifacts = payload.get("artifacts") or {}
    is_final = bool(payload.get("final"))
    # 이미 종료된 요청은 늦게 도착한 final 콜백으로 되살아나지 않습니다.
    # canceled 만 막으면 success 로 끝난 건이 뒤늦은 failed 보고로 뒤집히고,
    # 그 반대도 성립합니다. 단계 기록은 계속 누적하되 종결 상태만 고정합니다.
    was_terminal = request_obj.status in TERMINAL_STATUSES

    result_payload = dict(request_obj.result_payload or {})
    steps = dict(result_payload.get("steps") or {})
    steps[step] = {
        "status": status,
        "summary": summary,
        "metrics": metrics,
        "artifacts": artifacts,
        "received_at": utcnow().isoformat(),
    }
    result_payload["steps"] = steps
    request_obj.result_payload = result_payload

    if summary:
        request_obj.result_summary = summary

    if is_final and not was_terminal:
        request_obj.status = STATUS_SUCCESS if status in {"success", "succeeded"} else STATUS_FAILED
        request_obj.completed_at = utcnow()
        if request_obj.status == STATUS_FAILED and not request_obj.error_message:
            request_obj.error_message = summary or "자동화 실행이 실패했습니다."

        execution = _get_pipeline_execution(db, request_obj)
        if execution is not None:
            execution.status = request_obj.status
            execution.ended_at = utcnow()
            execution.metrics_json = metrics or execution.metrics_json
            execution.logs_summary = summary or execution.logs_summary

    db.commit()
    db.refresh(request_obj)
    return request_obj
