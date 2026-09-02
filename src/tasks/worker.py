"""
src/tasks/worker.py

Arq 워커 진입점. 원본 Harness 파이프라인 실행 백엔드를 대체합니다.

실행:
    arq src.tasks.worker.WorkerSettings
"""

from __future__ import annotations

from arq import cron
from arq.connections import RedisSettings

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
    development_data_refresh_task,
    drift_monitor_task,
    nightly_schedule_task,
    weekly_retrain_task,
)


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
    ]
    # 원본 Harness 야간 트리거와 Airflow 주간 재학습 DAG 를 같은 시각으로 이식했습니다.
    # 워커가 여러 대여도 arq 는 크론을 한 번만 실행합니다.
    # 수집·색인과 전체 검증은 아래 job_timeout(30분)을 넘길 수 있어 개별 지정합니다.
    cron_jobs = [
        cron(development_data_refresh_task, hour=2, minute=0, run_at_startup=False, timeout=10800),
        cron(nightly_schedule_task, hour=2, minute=0, run_at_startup=False, timeout=10800),
        cron(
            weekly_retrain_task,
            weekday="mon",
            hour=3,
            minute=0,
            run_at_startup=False,
            timeout=10800,
        ),
        cron(
            drift_monitor_task,
            hour=4,
            minute=0,
            run_at_startup=False,
            timeout=3600,
        ),
    ]
    redis_settings = RedisSettings.from_dsn(settings.REDIS_URL)
    max_jobs = 4
    job_timeout = 1800
    keep_result = 3600
    # 원본은 Harness abort API 로 실행 중인 파이프라인을 죽였습니다. 이식본에서
    # 같은 동작을 하려면 워커가 abort 신호를 받아들여야 합니다.
    allow_abort_jobs = True
