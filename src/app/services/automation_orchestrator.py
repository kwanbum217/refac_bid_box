"""
src/app/services/automation_orchestrator.py

자동화 실행 오케스트레이터 (원본 apps/chatbot/services/automation_orchestrator.py 이식).

원본은 Harness 파이프라인을 트리거했습니다. 리팩토링본은 실행 백엔드만 Arq 태스크 큐로
교체하되, 요청 레코드(automation_requests)와 실행 이력(pipeline_executions)의 상태 전이,
확인 토큰 규약, 응답 페이로드 계약은 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.models.chatbot import AutomationRequest, PipelineExecution
from src.app.schemas.chat import ChatPlan, PlanStep
from src.app.services.action_catalog import DEFAULT_POLL_AFTER_MS, get_action
from src.app.services.capability_registry import get_capability
from src.app.services.result_presenter import (
    build_presentable_result_payload,
    build_terminal_answer,
    build_visualizations,
)

logger = logging.getLogger(__name__)

CONFIRMATION_SALT = "bidbox.automation.confirmation"
CALLBACK_SALT = "bidbox.automation.callback"
CONFIRMATION_MAX_AGE = 60 * 30

# 원본 AutomationRequest.Status 값 그대로
STATUS_PENDING_CONFIRMATION = "pending_confirmation"
STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_CANCELED = "canceled"
TERMINAL_STATUSES = {STATUS_SUCCESS, STATUS_FAILED, STATUS_CANCELED}

# run_mode -> Arq 태스크 이름
RUN_MODE_TASKS = {
    "preflight_only": "preflight_check_task",
    "collect_only": "collect_bids_task",
    "kb_only": "update_kb_task",
    "predict_only": "validate_model_task",
    "refresh_data": "refresh_data_task",
    "manual_full": "manual_full_task",
}


class AutomationError(RuntimeError):
    """자동화 실행 계층 오류 (원본 HarnessTriggerError 대응)."""


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


# --------------------------------------------------------------------------- #
# 서명 토큰 (원본 django.core.signing.TimestampSigner 대체, 표준 라이브러리만 사용)
# --------------------------------------------------------------------------- #


def _sign(value: str, salt: str) -> str:
    timestamp = str(int(time.time()))
    payload = f"{value}:{timestamp}"
    digest = hmac.new(
        f"{settings.SECRET_KEY}:{salt}".encode(),
        payload.encode(),
        hashlib.sha256,
    ).digest()
    signature = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"{payload}:{signature}"


def _unsign(token: str, salt: str, max_age: int | None = None) -> str:
    try:
        value, timestamp, signature = token.rsplit(":", 2)
    except ValueError as exc:
        raise AutomationError("서명 형식이 올바르지 않습니다.") from exc

    payload = f"{value}:{timestamp}"
    expected = hmac.new(
        f"{settings.SECRET_KEY}:{salt}".encode(),
        payload.encode(),
        hashlib.sha256,
    ).digest()
    expected_signature = base64.urlsafe_b64encode(expected).decode().rstrip("=")
    if not hmac.compare_digest(signature, expected_signature):
        raise AutomationError("서명이 일치하지 않습니다.")

    if max_age is not None and (time.time() - int(timestamp)) > max_age:
        raise AutomationError("토큰이 만료되었습니다.")
    return value


def make_confirmation_token(job_id: str) -> str:
    return _sign(job_id, CONFIRMATION_SALT)


def resolve_confirmation_token(token: str, max_age: int = CONFIRMATION_MAX_AGE) -> str:
    return _unsign(token, CONFIRMATION_SALT, max_age)


def make_callback_token(job_id: str) -> str:
    return _sign(job_id, CALLBACK_SALT)


def verify_callback_token(job_id: str, token: str) -> bool:
    if not token:
        return False
    try:
        return _unsign(token, CALLBACK_SALT) == str(job_id)
    except AutomationError:
        return False


# --------------------------------------------------------------------------- #
# 조회 헬퍼
# --------------------------------------------------------------------------- #


def get_automation_request(db: Session, job_id: str) -> AutomationRequest | None:
    return db.execute(
        select(AutomationRequest).where(AutomationRequest.request_id == str(job_id))
    ).scalar_one_or_none()


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


def _get_pipeline_execution(db: Session, request_obj: AutomationRequest) -> PipelineExecution | None:
    execution_key = request_obj.plan_execution_id or request_obj.harness_execution_id
    if not execution_key:
        return None
    return db.execute(
        select(PipelineExecution)
        .where(PipelineExecution.execution_id == execution_key)
        .order_by(PipelineExecution.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def plan_requires_confirmation(plan: ChatPlan) -> bool:
    return any(step.requires_confirmation for step in plan.steps)


def build_confirmation_from_plan(plan: ChatPlan) -> dict[str, Any]:
    return {
        "primary_action_key": plan.primary_action_key,
        "requires_confirmation": plan_requires_confirmation(plan),
        "steps": [step.model_dump() for step in plan.steps],
    }


def _callback_metadata(request_obj: AutomationRequest) -> dict[str, Any]:
    payload = dict(request_obj.payload or {})
    return {
        "callback_mode": str(payload.get("callback_mode") or "polling"),
        "callback_configured": bool(payload.get("callback_configured")),
        "callback_reason": str(payload.get("callback_reason") or ""),
        "callback_url": str(payload.get("callback_url") or ""),
        "callback_base_url": str(payload.get("callback_base_url") or ""),
    }


def _callback_status_lines(request_obj: AutomationRequest) -> list[str]:
    metadata = _callback_metadata(request_obj)
    if metadata["callback_mode"] == "callback":
        return ["- 결과 수신 방식: `callback`"]

    reason = metadata["callback_reason"] or "워커 콜백이 설정되지 않아 polling으로 상태를 확인합니다."
    return ["- 결과 수신 방식: `polling`", f"- 안내: {reason}"]


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
    db: Session, request_obj: AutomationRequest, pipeline_execution: PipelineExecution | None = None
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


# --------------------------------------------------------------------------- #
# 답변 빌더
# --------------------------------------------------------------------------- #


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
    display_name = action.display_name if action else (request_obj.action_key or request_obj.intent_type)
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
        confirmation_token = ""
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
        suggestions = ["자동화 결과 요약 보기", "그래프로 다시 보기"] + presentable_result_payload.get(
            "recommended_actions", []
        )[:2]
        confirmation_token = ""
        visualizations = build_visualizations(request_obj.result_payload)
    elif request_obj.status == STATUS_FAILED:
        mode = "error"
        answer = _build_failure_answer(request_obj)
        message = request_obj.result_summary or "자동화 작업이 실패했습니다."
        suggestions = ["실행 상태 보기", "다시 시도하기"] + presentable_result_payload.get(
            "recommended_actions", []
        )[:2]
        confirmation_token = ""
        visualizations = build_visualizations(request_obj.result_payload)
    else:
        mode = "action" if request_obj.status == STATUS_RUNNING else "progress"
        answer = _build_in_progress_answer(request_obj)
        message = request_obj.result_summary or "자동화 작업이 등록되었습니다."
        suggestions = ["실행 상태 보기", "자동화 결과 요약 보기"]
        confirmation_token = ""
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


# --------------------------------------------------------------------------- #
# 생명주기
# --------------------------------------------------------------------------- #


def create_automation_request(
    db: Session,
    *,
    plan: ChatPlan,
    message: str,
    user_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> AutomationRequest:
    action = get_action(plan.primary_action_key)
    pipeline_step = _get_pipeline_step(plan)
    capability = get_capability(pipeline_step.tool) if pipeline_step else None
    requires_confirmation = plan_requires_confirmation(plan)

    request_payload = dict(payload or {})
    request_payload["plan"] = plan.model_dump()
    request_payload.update(
        {
            "callback_mode": "polling",
            "callback_configured": False,
            "callback_reason": "Arq 워커는 폴링으로 상태를 반영합니다.",
        }
    )

    request_obj = AutomationRequest(
        request_id=str(uuid.uuid4()),
        user_id=user_id,
        intent_type=plan.intent_type,
        action_key=plan.primary_action_key,
        requested_text=message,
        followup_query=plan.followup_query,
        payload=request_payload,
        pipeline_name=action.pipeline_id if action else (capability.pipeline_id if capability else ""),
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
    user_id: int | None = None,
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
        request_obj.status = STATUS_SUCCESS
        request_obj.result_summary = "실행 파이프라인이 필요하지 않은 요청입니다."
        request_obj.completed_at = datetime.utcnow()
        db.commit()
        db.refresh(request_obj)
        return request_obj

    if request_obj.requires_confirmation and not request_obj.confirmed_at:
        return request_obj

    capability = get_capability(action_key)
    run_mode = action.run_mode if action else (capability.run_mode if capability else "manual_full")
    pipeline_name = request_obj.pipeline_name or (action.pipeline_id if action else "")

    trigger = enqueue_pipeline_run(
        db=db,
        action_key=action_key,
        run_mode=run_mode,
        pipeline_name=pipeline_name,
        original_query=request_obj.followup_query or request_obj.requested_text,
        automation_request_id=str(request_obj.request_id),
    )

    request_obj.plan_execution_id = trigger["execution_id"]
    request_obj.harness_execution_id = trigger["execution_id"]
    request_obj.started_at = datetime.utcnow()
    if trigger["enqueued"]:
        request_obj.status = STATUS_RUNNING
        request_obj.result_summary = "자동화 작업이 실행 큐에 등록되었습니다."
    else:
        request_obj.status = STATUS_FAILED
        request_obj.completed_at = datetime.utcnow()
        request_obj.result_summary = "자동화 작업 등록에 실패했습니다."
        request_obj.error_message = "Arq 브로커(Redis)에 연결하지 못했습니다."
    db.commit()
    db.refresh(request_obj)
    return request_obj


def confirm_automation_request(db: Session, request_obj: AutomationRequest) -> AutomationRequest:
    if request_obj.confirmed_at:
        return request_obj
    request_obj.confirmed_at = datetime.utcnow()
    request_obj.status = STATUS_QUEUED
    request_obj.result_summary = "실행 확인이 완료되었습니다."
    db.commit()
    db.refresh(request_obj)
    return start_automation_request(db, request_obj)


def cancel_automation_request(db: Session, request_obj: AutomationRequest) -> AutomationRequest:
    if request_obj.status in TERMINAL_STATUSES:
        return request_obj

    payload = dict(request_obj.payload or {})
    payload["canceled_by_user"] = {
        "requested_at": datetime.utcnow().isoformat(),
        "plan_execution_id": request_obj.plan_execution_id,
    }
    request_obj.payload = payload
    request_obj.status = STATUS_CANCELED
    request_obj.completed_at = datetime.utcnow()
    request_obj.result_summary = "사용자 요청으로 분석 실행을 중지했습니다."
    request_obj.error_message = ""

    execution = _get_pipeline_execution(db, request_obj)
    if execution and execution.status in {STATUS_QUEUED, STATUS_RUNNING}:
        raw_payload = dict(execution.raw_status_payload or {})
        raw_payload["canceled_by_user"] = payload["canceled_by_user"]
        execution.raw_status_payload = raw_payload
        execution.status = STATUS_FAILED
        execution.ended_at = datetime.utcnow()
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
        request_obj.completed_at = execution.ended_at or datetime.utcnow()
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
    was_canceled = request_obj.status == STATUS_CANCELED

    result_payload = dict(request_obj.result_payload or {})
    steps = dict(result_payload.get("steps") or {})
    steps[step] = {
        "status": status,
        "summary": summary,
        "metrics": metrics,
        "artifacts": artifacts,
        "received_at": datetime.utcnow().isoformat(),
    }
    result_payload["steps"] = steps
    request_obj.result_payload = result_payload

    if summary:
        request_obj.result_summary = summary

    if is_final and not was_canceled:
        request_obj.status = STATUS_SUCCESS if status in {"success", "succeeded"} else STATUS_FAILED
        request_obj.completed_at = datetime.utcnow()
        if request_obj.status == STATUS_FAILED and not request_obj.error_message:
            request_obj.error_message = summary or "자동화 실행이 실패했습니다."

        execution = _get_pipeline_execution(db, request_obj)
        if execution is not None:
            execution.status = request_obj.status
            execution.ended_at = datetime.utcnow()
            execution.metrics_json = metrics or execution.metrics_json
            execution.logs_summary = summary or execution.logs_summary

    db.commit()
    db.refresh(request_obj)
    return request_obj


# --------------------------------------------------------------------------- #
# Arq 연동
# --------------------------------------------------------------------------- #


def enqueue_pipeline_run(
    *,
    db: Session | None,
    action_key: str,
    run_mode: str,
    pipeline_name: str,
    original_query: str = "",
    automation_request_id: str = "",
) -> dict[str, Any]:
    """Arq 큐에 실행을 등록하고 pipeline_executions 이력을 남깁니다."""
    execution_id = f"{run_mode}-{uuid.uuid4().hex[:12]}"
    task_name = RUN_MODE_TASKS.get(run_mode, "manual_full_task")

    execution = None
    if db is not None:
        execution = PipelineExecution(
            execution_id=execution_id,
            pipeline_name=pipeline_name or "refac_bid_box_pipeline",
            run_mode=run_mode,
            status=STATUS_QUEUED,
            source="chatbot",
            started_at=datetime.utcnow(),
            raw_status_payload={
                "action_key": action_key,
                "task_name": task_name,
                "original_query": original_query,
                "automation_request_id": automation_request_id,
            },
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

    enqueued = _enqueue_arq_job(
        task_name,
        execution_id=execution_id,
        action_key=action_key,
        run_mode=run_mode,
        original_query=original_query,
        automation_request_id=automation_request_id,
    )

    if db is not None and execution is not None:
        if enqueued:
            execution.status = STATUS_RUNNING
        else:
            execution.status = STATUS_FAILED
            execution.logs_summary = "Arq 브로커에 연결하지 못해 실행을 등록하지 못했습니다."
            execution.ended_at = datetime.utcnow()
        db.commit()

    return {
        "execution_id": execution_id,
        "pipeline_name": pipeline_name,
        "run_mode": run_mode,
        "task_name": task_name,
        "status": STATUS_RUNNING if enqueued else STATUS_FAILED,
        "enqueued": enqueued,
    }


def _enqueue_arq_job(task_name: str, **kwargs: Any) -> bool:
    try:
        import asyncio
        import concurrent.futures

        from arq import create_pool
        from arq.connections import RedisSettings

        async def _push() -> None:
            pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
            try:
                await pool.enqueue_job(task_name, **kwargs)
            finally:
                await pool.close()

        try:
            asyncio.get_running_loop()
        except RuntimeError:
            asyncio.run(_push())
            return True

        # 이미 이벤트 루프 안이면 별도 스레드의 루프에서 처리합니다.
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, _push()).result(timeout=10)
        return True
    except Exception as exc:
        logger.warning("Arq 작업 등록 실패 (%s): %s", task_name, exc)
        return False
