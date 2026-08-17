"""
src/app/services/automation_jobs.py

자동화 Arq 태스크 큐 연동, 실행 등록 및 중단 제어 모듈.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from typing import Any

from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.chatbot import PipelineExecution

logger = logging.getLogger(__name__)

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_FAILED = "failed"

# run_mode -> Arq 태스크 이름
RUN_MODE_TASKS = {
    "preflight_only": "preflight_check_task",
    "collect_only": "collect_bids_task",
    "kb_only": "update_kb_task",
    "predict_only": "validate_model_task",
    "refresh_data": "refresh_data_task",
    "manual_full": "manual_full_task",
    "retrain_only": "manual_retrain_task",
}


def _run_arq_coroutine(factory: Callable[[], Any], timeout: float = 10) -> Any:
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
    enqueue_fn: Any = None,
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
            started_at=utcnow(),
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

    push = enqueue_fn or _enqueue_arq_job
    enqueued = push(
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
            execution.ended_at = utcnow()
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
