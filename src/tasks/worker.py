"""
src/tasks/worker.py

Arq 워커 진입점. 원본 Harness 파이프라인 실행 백엔드를 대체합니다.

실행:
    arq src.tasks.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import os
import socket
import uuid
from datetime import UTC, datetime
from typing import Any, cast

from arq import cron
from arq.connections import RedisSettings

from src.app.core.cache import CacheLayer
from src.app.core.config import settings
from src.tasks.automation_tasks import (
    collect_bids_task,
    manual_full_task,
    manual_retrain_task,
    preflight_check_task,
    refresh_data_task,
    update_kb_task,
    validate_model_task,
)
from src.tasks.retrain_task import run_retrain_pipeline_task
from src.tasks.scheduled_tasks import (
    backup_schedule_task,
    development_data_refresh_task,
    drift_monitor_task,
    nightly_schedule_task,
    weekly_retrain_task,
)

WORKER_HEARTBEAT_KEY = "bidbox:worker:heartbeat"
QUEUE_BACKLOG_KEY = "bidbox:worker:queue_backlog"
SCHEDULE_STATUS_KEY = "bidbox:worker:schedules"
OBSERVATION_TTL_SECONDS = 7 * 24 * 60 * 60
ARQ_QUEUE_KEY = "arq:queue"
_worker_cache = CacheLayer()
_worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _redis_queue_length() -> int | None:
    """Arq 큐 길이를 조회합니다. Redis 장애는 관측 실패로만 처리합니다."""
    try:
        client = _worker_cache._conn.client()
        if client is None:
            return None
        return int(client.llen(ARQ_QUEUE_KEY))
    except Exception:
        return None


def record_worker_heartbeat() -> None:
    """워커 생존 시각, 식별자와 관측 시점의 큐 적체를 기록합니다."""
    try:
        now = _now_iso()
        _worker_cache.set(
            WORKER_HEARTBEAT_KEY,
            {"worker_id": _worker_id, "last_seen_at": now},
            OBSERVATION_TTL_SECONDS,
        )
        queue_length = _redis_queue_length()
        if queue_length is not None:
            _worker_cache.set(
                QUEUE_BACKLOG_KEY,
                {"pending": queue_length, "observed_at": now},
                OBSERVATION_TTL_SECONDS,
            )
    except Exception:
        # 관측 기록은 워커의 본 작업을 방해하지 않습니다.
        return


def record_schedule_result(schedule_name: str, outcome: Any, success: bool) -> None:
    """스케줄별 마지막 실행 시각과 성공 여부를 기록합니다."""
    try:
        current = _worker_cache.get(SCHEDULE_STATUS_KEY)
        schedules = current if isinstance(current, dict) else {}
        schedules[schedule_name] = {
            "last_run_at": _now_iso(),
            "success": success,
        }
        _worker_cache.set(SCHEDULE_STATUS_KEY, schedules, OBSERVATION_TTL_SECONDS)
    except Exception:
        return


async def _heartbeat_loop() -> None:
    while True:
        record_worker_heartbeat()
        await asyncio.sleep(settings.WORKER_HEARTBEAT_INTERVAL_SECONDS)


async def _on_startup(ctx: dict[str, Any]) -> None:
    record_worker_heartbeat()
    ctx["worker_heartbeat_task"] = asyncio.create_task(_heartbeat_loop())


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    heartbeat_task = ctx.pop("worker_heartbeat_task", None)
    if heartbeat_task is not None:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)


class WorkerSettings:
    functions = [
        preflight_check_task,
        collect_bids_task,
        update_kb_task,
        validate_model_task,
        refresh_data_task,
        manual_full_task,
        manual_retrain_task,
        run_retrain_pipeline_task,
        development_data_refresh_task,
        drift_monitor_task,
        backup_schedule_task,
    ]
    # 원본 Harness 야간 트리거와 Airflow 주간 재학습 DAG 를 같은 시각으로 이식했습니다.
    # 워커가 여러 대여도 arq 는 크론을 한 번만 실행합니다.
    # 수집·색인과 전체 검증은 아래 job_timeout(30분)을 넘길 수 있어 개별 지정합니다.
    cron_jobs = [
        cron(
            cast(Any, development_data_refresh_task),
            hour=2,
            minute=0,
            run_at_startup=False,
            timeout=10800,
        ),
        cron(
            cast(Any, nightly_schedule_task), hour=2, minute=0, run_at_startup=False, timeout=10800
        ),
        cron(
            cast(Any, weekly_retrain_task),
            weekday="mon",
            hour=3,
            minute=0,
            run_at_startup=False,
            timeout=10800,
        ),
        cron(
            cast(Any, drift_monitor_task),
            hour=4,
            minute=0,
            run_at_startup=False,
            timeout=3600,
        ),
    ]
    if settings.BACKUP_SCHEDULE_ENABLED:
        cron_jobs.append(
            cron(
                cast(Any, backup_schedule_task),
                hour=3,
                minute=0,
                run_at_startup=False,
                timeout=10800,
            )
        )
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 4
    job_timeout = 1800
    keep_result = 3600
    # 원본은 Harness abort API 로 실행 중인 파이프라인을 죽였습니다. 이식본에서
    # 같은 동작을 하려면 워커가 abort 신호를 받아들여야 합니다.
    allow_abort_jobs = True
    on_startup = _on_startup
    on_shutdown = _on_shutdown
