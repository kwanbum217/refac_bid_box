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
import ipaddress
import logging
import time
import uuid
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta
from typing import Any
from urllib.parse import urlparse

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

# 최근 성공 이력을 재사용할 고비용 작업 (원본 REUSABLE_STAGING_ACTIONS 동일)
REUSABLE_ACTIONS = {"full_validation"}
REUSE_MAX_AGE_HOURS = 72

# 워커가 결과를 되돌려 보낼 API 경로 (automation 라우터와 일치해야 합니다)
CALLBACK_PATH_TEMPLATE = "/api/v1/automation/job/{job_id}/callback"

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


@dataclass(frozen=True)
class CallbackDelivery:
    """워커 실행 결과가 요청 레코드로 되돌아오는 경로."""

    mode: str
    configured: bool
    callback_url: str
    base_url: str
    reason: str

    def as_payload(self) -> dict[str, Any]:
        return {
            "callback_mode": self.mode,
            "callback_configured": self.configured,
            "callback_reason": self.reason,
            "callback_url": self.callback_url,
            "callback_base_url": self.base_url,
        }


def _is_worker_unreachable_host(hostname: str) -> bool:
    """워커가 도달할 수 없는 호스트인지 판정합니다.

    원본은 외부 SaaS(Harness)가 호출자였기 때문에 사설 대역 전체를 거부했습니다.
    Arq 워커는 같은 네트워크 안에 있으므로 그 규칙을 그대로 쓰면 안 됩니다.
    `http://app:8000`, `http://10.0.0.5` 같은 사설 주소가 오히려 정상 설정입니다.

    거부 대상은 루프백뿐입니다. 워커가 별도 컨테이너일 때 루프백은 앱이 아니라
    워커 자기 자신을 가리키므로 결과가 영영 돌아오지 않습니다.
    """
    host = (hostname or "").strip().lower().strip("[]")
    if not host:
        return True
    if host in {"localhost", "0.0.0.0", "::1"} or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # 호스트명은 컨테이너 서비스명일 수 있으므로 통과시킵니다.
        return False
    return bool(address.is_loopback or address.is_unspecified)


def resolve_callback_delivery(job_id: str) -> CallbackDelivery:
    """실행 결과 수신 경로를 결정합니다 (원본 resolve_callback_delivery 의 Arq 판)。

    | 조건 | 모드 |
    | --- | --- |
    | 콜백 주소 없음 + 워커가 DB 공유 | `direct` (워커가 DB 에 바로 기록) |
    | 콜백 주소 없음 + DB 미공유 | `polling` (되돌릴 경로 없음) |
    | 콜백 주소 형식 오류 / 루프백 | `polling` 또는 DB 공유 시 `direct` 로 강등 |
    | 콜백 주소 정상 | `callback` (워커가 HTTP 로 보고) |
    """
    base_url = (settings.AUTOMATION_CALLBACK_BASE_URL or "").strip()
    shares_db = bool(settings.AUTOMATION_WORKER_SHARES_DB)

    def _fallback(reason: str, checked_base_url: str = "") -> CallbackDelivery:
        if shares_db:
            return CallbackDelivery(
                mode="direct",
                configured=True,
                callback_url="",
                base_url=checked_base_url,
                reason=reason,
            )
        return CallbackDelivery(
            mode="polling",
            configured=False,
            callback_url="",
            base_url=checked_base_url,
            reason=reason,
        )

    if not base_url:
        return _fallback(
            "워커가 앱과 같은 DB 에 결과를 직접 기록합니다."
            if shares_db
            else "워커 콜백 주소가 없고 DB 도 공유하지 않아 상태 조회로만 확인합니다."
        )

    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return _fallback("워커 콜백 주소 형식이 올바르지 않습니다.", base_url)

    if _is_worker_unreachable_host(parsed.hostname or ""):
        return _fallback(
            "워커 콜백 주소가 루프백이라 별도 프로세스인 워커가 앱에 도달할 수 없습니다.",
            base_url.rstrip("/"),
        )

    normalized = base_url.rstrip("/")
    return CallbackDelivery(
        mode="callback",
        configured=True,
        callback_url=f"{normalized}{CALLBACK_PATH_TEMPLATE.format(job_id=job_id)}",
        base_url=normalized,
        reason="",
    )


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
    mode = metadata["callback_mode"]
    if mode in {"callback", "direct"}:
        lines = [f"- 결과 수신 방식: `{mode}`"]
        # direct 는 정상 경로지만 콜백 설정이 잘못돼 강등된 경우를 알려줍니다.
        if mode == "direct" and metadata["callback_base_url"]:
            lines.append(f"- 안내: {metadata['callback_reason']}")
        return lines

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


def _find_reusable_execution(
    db: Session, *, pipeline_name: str, run_mode: str = ""
) -> PipelineExecution | None:
    """원본 _find_local_reusable_pipeline_execution 대응.

    같은 파이프라인의 최근 성공 실행을 찾습니다. run_mode 를 주면 정확히 일치하는
    건만 봅니다. 신선도 창을 벗어난 이력은 재사용하지 않습니다.
    """
    if not pipeline_name or REUSE_MAX_AGE_HOURS <= 0:
        return None

    stmt = select(PipelineExecution).where(
        PipelineExecution.pipeline_name == pipeline_name,
        PipelineExecution.status == STATUS_SUCCESS,
    )
    if run_mode:
        stmt = stmt.where(PipelineExecution.run_mode == run_mode)
    stmt = stmt.order_by(
        PipelineExecution.ended_at.desc(),
        PipelineExecution.started_at.desc(),
        PipelineExecution.created_at.desc(),
    ).limit(20)

    cutoff = datetime.utcnow() - timedelta(hours=REUSE_MAX_AGE_HOURS)
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
    request_obj.started_at = execution.started_at or request_obj.started_at or datetime.utcnow()
    request_obj.completed_at = execution.ended_at or datetime.utcnow()
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
    if not pipeline_name:
        return None

    exact = _find_reusable_execution(
        db, pipeline_name=pipeline_name, run_mode=requested_run_mode
    )
    if exact is not None:
        return _attach_reused_execution(
            db, request_obj, exact, requested_run_mode=requested_run_mode, exact_run_mode=True
        )

    recent = _find_reusable_execution(db, pipeline_name=pipeline_name)
    if recent is not None:
        return _attach_reused_execution(
            db,
            request_obj,
            recent,
            requested_run_mode=requested_run_mode,
            exact_run_mode=recent.run_mode == requested_run_mode,
        )
    return None


def confirm_automation_request(db: Session, request_obj: AutomationRequest) -> AutomationRequest:
    if request_obj.confirmed_at:
        return request_obj
    request_obj.confirmed_at = datetime.utcnow()
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
    arq_job_id = str((execution.raw_status_payload or {}).get("arq_job_id") or "") if execution else ""
    abort_succeeded = abort_arq_job(arq_job_id) if (running and arq_job_id) else False

    payload = dict(request_obj.payload or {})
    payload["canceled_by_user"] = {
        "requested_at": datetime.utcnow().isoformat(),
        "plan_execution_id": request_obj.plan_execution_id,
        "arq_job_id": arq_job_id,
        "worker_abort_requested": abort_succeeded,
    }
    request_obj.payload = payload
    request_obj.status = STATUS_CANCELED
    request_obj.completed_at = datetime.utcnow()
    request_obj.result_summary = "사용자 요청으로 분석 실행을 중지했습니다."
    request_obj.error_message = ""

    if running:
        raw_payload = dict(execution.raw_status_payload or {})
        raw_payload["canceled_by_user"] = payload["canceled_by_user"]
        execution.raw_status_payload = raw_payload
        execution.status = STATUS_FAILED
        execution.stage_status = STATUS_CANCELED
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
    callback_url: str = "",
    callback_token: str = "",
) -> dict[str, Any]:
    """Arq 큐에 실행을 등록하고 pipeline_executions 이력을 남깁니다."""
    execution_id = f"{run_mode}-{uuid.uuid4().hex[:12]}"
    task_name = RUN_MODE_TASKS.get(run_mode, "manual_full_task")
    # 나중에 중지 요청이 오면 이 ID 로 Arq 작업을 붙잡아 abort 합니다.
    arq_job_id = f"arq-{execution_id}"

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
                "arq_job_id": arq_job_id,
            },
        )
        db.add(execution)
        db.commit()
        db.refresh(execution)

    enqueued = _enqueue_arq_job(
        task_name,
        arq_job_id=arq_job_id,
        execution_id=execution_id,
        action_key=action_key,
        run_mode=run_mode,
        original_query=original_query,
        automation_request_id=automation_request_id,
        callback_url=callback_url,
        callback_token=callback_token,
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
        "arq_job_id": arq_job_id,
        "pipeline_name": pipeline_name,
        "run_mode": run_mode,
        "task_name": task_name,
        "status": STATUS_RUNNING if enqueued else STATUS_FAILED,
        "enqueued": enqueued,
    }


def _run_arq_coroutine(factory, timeout: float = 10) -> Any:
    """이벤트 루프 안팎 어디서 불려도 Arq 코루틴을 안전하게 실행합니다."""
    import asyncio
    import concurrent.futures

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(factory())

    # 이미 이벤트 루프 안이면 별도 스레드의 루프에서 처리합니다.
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, factory()).result(timeout=timeout)


def abort_arq_job(arq_job_id: str) -> bool:
    """실행 중인 Arq 작업에 중단 신호를 보냅니다 (원본 abort_pipeline_execution 대응).

    arq 의 Job.abort() 는 신호를 넣은 뒤 워커의 확인 결과까지 기다립니다. 중지
    버튼이 워커 응답만큼 멈추게 되므로, 여기서는 대기 없이 신호 전달까지만 합니다.
    워커는 allow_abort_jobs 설정에 따라 큐에서 집어들 때 이 신호를 확인합니다.

    반환값은 "중단 신호를 전달했는가" 이지 "작업이 실제로 멈췄는가" 가 아닙니다.
    """
    if not arq_job_id:
        return False
    try:
        from arq import create_pool
        from arq.connections import RedisSettings
        from arq.constants import abort_jobs_ss, default_queue_name

        async def _abort() -> bool:
            pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
            try:
                # 예약 실행분은 큐 앞으로 당겨 워커가 곧바로 중단 신호를 보게 합니다.
                async with pool.pipeline(transaction=True) as tr:
                    tr.zrem(default_queue_name, arq_job_id)
                    tr.zadd(default_queue_name, {arq_job_id: 1})
                    tr.zadd(abort_jobs_ss, {arq_job_id: int(time.time() * 1000)})
                    await tr.execute()
                return True
            finally:
                await pool.close()

        return bool(_run_arq_coroutine(_abort, timeout=15))
    except Exception as exc:
        logger.warning("Arq 작업 중단 신호 전달에 실패했습니다: %s", exc)
        return False


def _enqueue_arq_job(task_name: str, arq_job_id: str = "", **kwargs: Any) -> bool:
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        async def _push() -> None:
            pool = await create_pool(RedisSettings.from_dsn(settings.REDIS_URL))
            try:
                await pool.enqueue_job(task_name, _job_id=arq_job_id or None, **kwargs)
            finally:
                await pool.close()

        _run_arq_coroutine(_push)
        return True
    except Exception as exc:
        logger.warning("Arq 작업 등록 실패 (%s): %s", task_name, exc)
        return False
