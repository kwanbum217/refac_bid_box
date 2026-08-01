"""
src/tasks/worker.py

Arq 워커 진입점. 원본 Harness 파이프라인 실행 백엔드를 대체합니다.

실행:
    arq src.tasks.worker.WorkerSettings
"""

from __future__ import annotations

from arq.connections import RedisSettings

from src.app.core.config import settings
from src.tasks.automation_tasks import (
    collect_bids_task,
    manual_full_task,
    preflight_check_task,
    refresh_data_task,
    update_kb_task,
    validate_model_task,
)
from src.tasks.retrain_task import run_retrain_pipeline_task


class WorkerSettings:
    functions = [
        preflight_check_task,
        collect_bids_task,
        update_kb_task,
        validate_model_task,
        refresh_data_task,
        manual_full_task,
        run_retrain_pipeline_task,
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 4
    job_timeout = 1800
    keep_result = 3600
