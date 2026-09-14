"""tests/test_backup_worker_settings.py

BackupWorkerSettings 전용 큐 및 작업 격리 검증 테스트.
- functions 및 cron_jobs 가 backup_schedule_task 만 포함하는지 검증
- queue_name 이 기본 큐와 격리된 전용 이름(BACKUP_QUEUE_NAME = 'arq:queue:backup')인지 검증
- WorkerSettings 의 cron_jobs 에서 backup_schedule_task 가 제거되었는지 검증
- on_startup 에서 수집 따라잡기(schedule catchup)가 배제되었는지 검증
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any
from unittest.mock import patch

import pytest

from src.tasks.worker import (
    BACKUP_QUEUE_NAME,
    BackupWorkerSettings,
    WorkerSettings,
    _on_backup_shutdown,
    _on_backup_startup,
    is_task_traced,
)


def test_backup_worker_settings_functions_only_backup():
    """BackupWorkerSettings.functions 에는 백업 작업(backup_schedule_task)만 등록되어야 합니다."""
    assert len(BackupWorkerSettings.functions) == 1
    fn = BackupWorkerSettings.functions[0]
    target = getattr(fn, "coroutine", fn)
    assert getattr(target, "__name__", "") == "backup_schedule_task"
    assert is_task_traced(target) is True


def test_backup_worker_settings_cron_jobs_only_backup():
    """BackupWorkerSettings.cron_jobs 에는 03:00 백업 크론 1건만 등록되어야 합니다."""
    assert len(BackupWorkerSettings.cron_jobs) == 1
    job = BackupWorkerSettings.cron_jobs[0]
    target = getattr(job, "coroutine", job)
    assert getattr(target, "__name__", "") == "backup_schedule_task"
    assert job.hour in (3, {3})
    assert job.minute in (0, {0})
    assert job.run_at_startup is False
    assert job.timeout_s == 10800


def test_backup_worker_settings_queue_name_isolated():
    """BackupWorkerSettings.queue_name 은 기본 큐('arq:queue')와 다른 전용 큐여야 합니다."""
    assert BackupWorkerSettings.queue_name == BACKUP_QUEUE_NAME
    assert BackupWorkerSettings.queue_name == "arq:queue:backup"
    worker_queue = getattr(WorkerSettings, "queue_name", "arq:queue")
    assert BackupWorkerSettings.queue_name != worker_queue


def test_worker_settings_cron_jobs_does_not_contain_backup():
    """WorkerSettings 의 cron_jobs 에는 backup_schedule_task 가 더 이상 등록되지 않아야 합니다."""
    cron_names = [
        getattr(getattr(job, "coroutine", job), "__name__", "") for job in WorkerSettings.cron_jobs
    ]
    assert "backup_schedule_task" not in cron_names
    assert len(WorkerSettings.cron_jobs) >= 5


def test_backup_worker_settings_shares_redis_and_concurrency_contract():
    """BackupWorkerSettings 는 Redis 설정을 공유하고 기본 동시성 계약(max_jobs=4, job_timeout=1800)을 유지합니다."""
    assert BackupWorkerSettings.redis_settings.host == WorkerSettings.redis_settings.host
    assert BackupWorkerSettings.redis_settings.port == WorkerSettings.redis_settings.port
    assert BackupWorkerSettings.max_jobs == 4
    assert BackupWorkerSettings.job_timeout == 1800
    assert BackupWorkerSettings.allow_abort_jobs is True


@pytest.mark.asyncio
async def test_backup_worker_startup_and_shutdown_lifecycle():
    """BackupWorkerSettings.on_startup 은 하트비트를 시작하되 수집 따라잡기를 등록하지 않습니다."""
    ctx: dict[str, Any] = {}

    async def fake_heartbeat_loop():
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()

    with (
        patch("src.tasks.worker.record_worker_heartbeat") as mock_record,
        patch("src.tasks.worker._heartbeat_loop", side_effect=fake_heartbeat_loop),
        patch("src.tasks.worker.configure_logging"),
    ):
        await _on_backup_startup(ctx)
        mock_record.assert_called_once()
        assert "worker_heartbeat_task" in ctx
        assert "schedule_catchup_task" not in ctx

        await _on_backup_shutdown(ctx)
        assert ctx.get("worker_shutting_down") is True
        heartbeat_task = ctx.get("worker_heartbeat_task")
        assert heartbeat_task is None or heartbeat_task.cancelled() or heartbeat_task.done()
