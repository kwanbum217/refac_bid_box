"""
src/app/services/automation_orchestrator.py

자동화 실행 오케스트레이터.

원본 apps/chatbot/services/automation_orchestrator.py 는 Harness 파이프라인을 트리거했습니다.
리팩토링본은 실행 백엔드만 Arq 태스크 큐로 교체하되, 요청 레코드(automation_requests)와
실행 이력(pipeline_executions)의 상태 전이 계약은 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.models.chatbot import AutomationRequest, PipelineExecution
from src.app.schemas.chat import ChatPlan

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"

# run_mode -> Arq 태스크 이름
RUN_MODE_TASKS = {
    "preflight_only": "preflight_check_task",
    "collect_only": "collect_bids_task",
    "kb_only": "update_kb_task",
    "predict_only": "validate_model_task",
    "refresh_data": "refresh_data_task",
    "manual_full": "manual_full_task",
}


def create_automation_request(
    db: Session,
    *,
    plan: ChatPlan,
    message: str,
    user_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> AutomationRequest:
    """챗봇 action 모드에서 자동화 요청 레코드를 생성합니다."""
    request_obj = AutomationRequest(
        request_id=str(uuid.uuid4()),
        user_id=user_id,
        intent_type=plan.intent_type,
        requested_text=message,
        action_key=plan.primary_action_key,
        pipeline_name=_pipeline_name_for(plan),
        status=STATUS_QUEUED,
        payload={**(payload or {}), "plan": plan.model_dump()},
        requires_confirmation=plan.requires_confirmation,
        followup_query=plan.followup_query,
    )
    db.add(request_obj)
    db.commit()
    db.refresh(request_obj)
    return request_obj


def _pipeline_name_for(plan: ChatPlan) -> str:
    from src.app.services.capability_registry import get_capability

    capability = get_capability(plan.primary_action_key)
    return capability.pipeline_id if capability else ""


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

    if db is not None and execution is not None and not enqueued:
        execution.status = STATUS_FAILED
        execution.logs_summary = "Arq 브로커에 연결하지 못해 실행을 등록하지 못했습니다."
        execution.ended_at = datetime.utcnow()
        db.commit()

    return {
        "execution_id": execution_id,
        "pipeline_name": pipeline_name,
        "run_mode": run_mode,
        "task_name": task_name,
        "status": STATUS_QUEUED if enqueued else STATUS_FAILED,
        "enqueued": enqueued,
    }


def _enqueue_arq_job(task_name: str, **kwargs: Any) -> bool:
    try:
        import asyncio

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

        # 이미 이벤트 루프 안이면 별도 루프에서 처리합니다.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(asyncio.run, _push()).result(timeout=10)
        return True
    except Exception as exc:
        logger.warning("Arq 작업 등록 실패 (%s): %s", task_name, exc)
        return False


def get_execution_status(db: Session, execution_id: str) -> dict[str, Any] | None:
    execution = db.execute(
        select(PipelineExecution).where(PipelineExecution.execution_id == execution_id)
    ).scalar_one_or_none()
    if execution is None:
        return None
    return {
        "execution_id": execution.execution_id,
        "pipeline_name": execution.pipeline_name,
        "run_mode": execution.run_mode,
        "status": execution.status,
        "stage_name": execution.stage_name,
        "stage_status": execution.stage_status,
        "started_at": execution.started_at.isoformat() if execution.started_at else None,
        "ended_at": execution.ended_at.isoformat() if execution.ended_at else None,
        "metrics": dict(execution.metrics_json or {}),
        "logs_summary": execution.logs_summary or "",
    }
