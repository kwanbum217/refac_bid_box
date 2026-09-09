"""
src/tasks/worker.py

Arq 워커 진입점. 원본 Harness 파이프라인 실행 백엔드를 대체합니다.

실행:
    arq src.tasks.worker.WorkerSettings
"""

from __future__ import annotations

import asyncio
import logging
import os
import socket
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from datetime import UTC, datetime
from typing import Any, cast

from arq import cron
from arq.connections import RedisSettings
from arq.worker import func as arq_func

from src.app.core.cache import CacheLayer
from src.app.core.config import settings
from src.app.core.observability import (
    arq_on_job_end,
    arq_on_job_start,
    setup_observability,
    traced_worker_task,
)
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
    run_schedule_catchup_task,
    weekly_retrain_task,
)
from src.tasks.summary_tasks import rebuild_dataset_summary_task

logger = logging.getLogger(__name__)

_heavy_task_lock: asyncio.Lock | None = None
_running_heavy_tasks: set[str] = set()
_in_heavy_task: ContextVar[bool] = ContextVar("_in_heavy_task", default=False)

HEAVY_TASK_NAMES: frozenset[str] = frozenset(
    {
        "collect_bids_task",
        "update_kb_task",
        "manual_full_task",
        "refresh_data_task",
        "manual_retrain_task",
    }
)

HEAVY_RUN_MODES: frozenset[str] = frozenset(
    {
        "collect_only",
        "kb_only",
        "manual_full",
        "refresh_data",
        "retrain_only",
        "nightly_schedule",
    }
)


def get_heavy_task_lock() -> asyncio.Lock:
    """무거운 태스크 상호 배제 잠금을 반환합니다."""
    global _heavy_task_lock
    if _heavy_task_lock is None:
        _heavy_task_lock = asyncio.Lock()
    return _heavy_task_lock


def reset_heavy_task_lock(lock: asyncio.Lock | None = None) -> None:
    """테스트 격리를 위해 잠금 인스턴스를 재설정하거나 주입합니다."""
    global _heavy_task_lock
    _heavy_task_lock = lock
    _running_heavy_tasks.clear()


def get_running_heavy_tasks() -> set[str]:
    """현재 실행 중인 무거운 태스크 이름 집합을 반환합니다."""
    return set(_running_heavy_tasks)


def is_in_heavy_task() -> bool:
    """현재 비동기 컨텍스트가 무거운 태스크 가드 내부인지 확인합니다."""
    return _in_heavy_task.get()


@asynccontextmanager
async def heavy_task_guard(task_name: str) -> AsyncIterator[None]:
    """무거운 태스크 단일 실행 잠금 (Heavy Task Single Execution Lock).

    [설계 근거]
    1. 메모리 폭주 방지: update_kb_task, collect_bids_task, manual_full_task 등
       DB 전량 또는 KB 전량을 다루는 무거운 태스크는 단일 실행 시에도 수 GB의 메모리를 사용합니다.
       동시에 여러 건이 실행되면 컨테이너 메모리 한계(OOM)를 초과하여 워커가 소멸합니다.
       따라서 무거운 태스크 간에는 상호 배제(동시 실행 상한 = 1)가 필수적입니다.
    2. 가벼운 태스크 처리량 유지:
       WorkerSettings.max_jobs = 4 는 유지하며, preflight_check_task, validate_model_task 등
       가벼운 태스크는 잠금을 획득하지 않고 병렬 실행됩니다.
    3. 재시도 보존 (No Retry Burn):
       arq 의 Retry(defer) 예외를 사용해 재큐잉하면 arq.worker.run_job 내부의
       incr(retry_key_prefix + job_id) 로 인해 매번 job_try 가 증가하여
       기본 max_tries(5)를 빠르게 소진하고 태스크가 영구 소멸됩니다.
       실측 사례에서도 장애 재기동 시 태스크들이 이미 try=3, try=2 상태였으므로
       Retry(defer) 방식은 태스크 유실을 초래합니다.
       반면 asyncio 잠금 대기는 try 카운트를 소진하지 않고 안전하게 순차 실행합니다.

    [기각된 대안]
    - 대안 1 (max_jobs = 1 로 일괄 축소): 가벼운 태스크까지 직렬화되어 전체 처리량이 저하됨 (기각).
    - 대안 2 (태스크별 개별 세마포어): update_kb_task 와 collect_bids_task 가 동시에 돌면
      서로 다른 태스크라도 메모리 합산으로 워커가 사망하므로 태스크 간 상호 배제가 필수 (기각).
    - 대안 3 (중복 작업 조용한 폐기): 실패한 작업의 재시도는 시스템 일관성에 필수적이므로
      버려서는 안 됨 (기각).
    - 대안 4 (arq Retry deferral): retry_key_prefix 카운트 소진으로 재시도 한도 초과 실패 유발 (기각).
    """
    if _in_heavy_task.get():
        yield
        return

    lock = get_heavy_task_lock()
    if lock.locked():
        logger.info("무거운 태스크 '%s' 실행 잠금 대기 중...", task_name)
    async with lock:
        _in_heavy_task.set(True)
        _running_heavy_tasks.add(task_name)
        logger.info(
            "무거운 태스크 '%s' 실행 잠금 획득 (현재 실행 중인 무거운 태스크: %s)",
            task_name,
            list(_running_heavy_tasks),
        )
        try:
            yield
        finally:
            _running_heavy_tasks.discard(task_name)
            _in_heavy_task.set(False)
            logger.info("무거운 태스크 '%s' 실행 잠금 해제 완료", task_name)


WORKER_HEARTBEAT_KEY = "bidbox:worker:heartbeat"
QUEUE_BACKLOG_KEY = "bidbox:worker:queue_backlog"
SCHEDULE_STATUS_KEY = "bidbox:worker:schedules"
OBSERVATION_TTL_SECONDS = 7 * 24 * 60 * 60
ARQ_QUEUE_KEY = "arq:queue"
SCHEDULE_CATCHUP_JOB_NAME = "run_schedule_catchup_task"
SCHEDULE_CATCHUP_JOB_ID = "schedule-catchup-startup"
SCHEDULE_CATCHUP_JOB_TIMEOUT_SECONDS = 10800
_worker_cache = CacheLayer()
_worker_id = f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:12]}"


def _now_iso() -> str:
    return datetime.now(UTC).isoformat()


def _redis_queue_metrics(now_ms: int | None = None) -> dict[str, int] | None:
    """Arq 큐 적체 지표를 정렬 집합(ZSET) 기준으로 조회합니다.

    - pending: 현재 시각 이하 score (지금 즉시 실행 대기 중인 작업 수)
    - total: 큐의 전체 작업 수 (zcard)
    - deferred: 미래 예약 작업 수 (total - pending)

    Redis 장애는 관측 실패(None)로 처리합니다.
    """
    try:
        client = getattr(_worker_cache, "client", lambda: None)()
        if client is None and hasattr(_worker_cache, "_conn"):
            conn = _worker_cache._conn
            if hasattr(conn, "client"):
                client = conn.client()
        if client is None:
            return None

        current_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
        ready = int(client.zcount(ARQ_QUEUE_KEY, "-inf", current_ms))
        total = int(client.zcard(ARQ_QUEUE_KEY))
        deferred = max(0, total - ready)
        return {
            "pending": ready,
            "total": total,
            "deferred": deferred,
        }
    except Exception:
        return None


def _redis_queue_length() -> int | None:
    """Arq 큐의 즉시 실행 대기 작업 수(pending)를 반환합니다.

    하위 호환성을 위해 유지합니다.
    """
    metrics = _redis_queue_metrics()
    return metrics["pending"] if metrics is not None else None


def record_worker_heartbeat() -> None:
    """워커 생존 시각, 식별자와 관측 시점의 큐 적체를 기록합니다."""
    now = _now_iso()
    try:
        _worker_cache.set(
            WORKER_HEARTBEAT_KEY,
            {"worker_id": _worker_id, "last_seen_at": now},
            OBSERVATION_TTL_SECONDS,
        )
    except Exception:
        logger.debug("워커 heartbeat 기록 실패 (무시됨)")

    try:
        metrics = _redis_queue_metrics()
        if metrics is not None:
            _worker_cache.set(
                QUEUE_BACKLOG_KEY,
                {
                    "status": "ok",
                    "pending": metrics["pending"],
                    "total": metrics["total"],
                    "deferred": metrics["deferred"],
                    "observed_at": now,
                },
                OBSERVATION_TTL_SECONDS,
            )
        else:
            _worker_cache.set(
                QUEUE_BACKLOG_KEY,
                {
                    "status": "unavailable",
                    "pending": None,
                    "total": None,
                    "deferred": None,
                    "observed_at": now,
                },
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


def _record_catchup_enqueue_failure(error: str) -> None:
    """큐 적재 실패를 원장에 남기되, 기록 실패가 워커를 죽이지 않게 합니다."""
    try:
        from src.tasks.scheduled_tasks import build_catchup_ledger, record_catchup_attempt

        record_catchup_attempt(
            ledger=build_catchup_ledger(
                status="failed",
                reason="enqueue_failed",
                failed=[{"name": "schedule_catchup", "error": error}],
            ),
            apply_cooldown=False,
        )
    except Exception:
        logger.debug("따라잡기 원장 기록 실패 (무시됨)")


async def _enqueue_startup_catchup(ctx: dict[str, Any]) -> None:
    """따라잡기를 Arq 큐에 넣어 max_jobs 상한 안에서 실행되게 합니다."""
    redis = ctx.get("redis")
    enqueue_job = getattr(redis, "enqueue_job", None)
    if redis is None or enqueue_job is None:
        message = "Arq redis 연결이 없어 따라잡기를 큐에 넣을 수 없습니다."
        logger.error(message)
        _record_catchup_enqueue_failure(message)
        return

    job = await enqueue_job(
        SCHEDULE_CATCHUP_JOB_NAME,
        _job_id=SCHEDULE_CATCHUP_JOB_ID,
    )
    if job is None:
        logger.info("스케줄 따라잡기 작업이 이미 큐에 있거나 결과가 남아 중복 등록을 건너뜁니다.")


async def _run_catchup_background(ctx: dict[str, Any]) -> None:
    """따라잡기 큐 적재를 백그라운드에서 수행하며 예외를 격리합니다.

    실제 수집은 Arq 정규 잡으로 돌아가 max_jobs 에 포함됩니다. 기동 경로에서
    run_schedule_catchup_task 를 직접 await 하지 않습니다.
    """
    catchup_ctx = dict(ctx)
    catchup_ctx["is_background_catchup"] = True
    try:
        await _enqueue_startup_catchup(catchup_ctx)
    except asyncio.CancelledError:
        logger.info("스케줄 따라잡기 백그라운드 태스크 정상 종료 (워커 셧다운)")
        raise
    except Exception as exc:
        # 따라잡기 실패가 워커 프로세스를 종료시켜서는 안 됩니다.
        logger.exception("스케줄 따라잡기 백그라운드 태스크 실행 중 예외 발생")
        _record_catchup_enqueue_failure(str(exc))


async def _on_startup(ctx: dict[str, Any]) -> None:
    if settings.OTEL_ENABLED:
        from src.app.core.db import engine

        setup_observability(engine=engine)
    record_worker_heartbeat()
    ctx["worker_heartbeat_task"] = asyncio.create_task(_heartbeat_loop())
    if settings.AUTOMATION_SCHEDULE_CATCHUP_ENABLED:
        ctx["schedule_catchup_task"] = asyncio.create_task(_run_catchup_background(ctx))


async def _on_shutdown(ctx: dict[str, Any]) -> None:
    ctx["worker_shutting_down"] = True
    heartbeat_task = ctx.pop("worker_heartbeat_task", None)
    if heartbeat_task is not None:
        heartbeat_task.cancel()
        await asyncio.gather(heartbeat_task, return_exceptions=True)

    catchup_task = ctx.pop("schedule_catchup_task", None)
    if catchup_task is not None and not catchup_task.done():
        catchup_task.cancel("worker_shutdown")
        await asyncio.gather(catchup_task, return_exceptions=True)


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
        run_schedule_catchup_task,
        rebuild_dataset_summary_task,
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
    # 무거운 태스크 동시 실행 제한 정책:
    # 1. max_jobs = 4 유지:
    #    가벼운 태스크(preflight, validate 등)의 동시 처리량을 유지하기 위해
    #    워커 전체 max_jobs 를 1 로 축소하지 않고 4 로 유지합니다.
    # 2. 무거운 태스크 단일 실행 잠금 (Heavy Task Single Execution Lock):
    #    update_kb_task, collect_bids_task, manual_full_task 등 DB 전량 또는 KB 전량을 다루는
    #    무거운 태스크들은 heavy_task_guard 를 통해 단 1개만 실행되도록 상호 배제(동시성=1)합니다.
    # 3. 재시도 보존 (No Retry Burn):
    #    재시도 큐에서 태스크가 한꺼번에 되살아나도 순차 실행되어 메모리 폭주(OOM)를 방지하며,
    #    arq Retry(defer) 예외를 사용하지 않아 job_try 카운트 소진(5회 초과 실패)을 방어합니다.
    # 4. 기각된 대안:
    #    - max_jobs = 1 축소: 가벼운 태스크까지 직렬화되어 처리량 저하 (기각)
    #    - 태스크별 개별 세마포어: 서로 다른 무거운 작업 동시 실행 시 메모리 합산 폭주 (기각)
    #    - 재시도 작업 조용한 버림: 작업 유실 및 파이프라인 일관성 훼손 (기각)
    #    - Arq Retry deferral: 재시도 한도(max_tries=5) 조기 소진으로 작업 소멸 유발 (기각)
    max_jobs = 4
    job_timeout = 1800
    keep_result = 3600
    # 원본은 Harness abort API 로 실행 중인 파이프라인을 죽였습니다. 이식본에서
    # 같은 동작을 하려면 워커가 abort 신호를 받아들여야 합니다.
    allow_abort_jobs = True
    on_startup = _on_startup
    on_shutdown = _on_shutdown
    on_job_start = arq_on_job_start
    on_job_end = arq_on_job_end


def is_task_traced(fn: Any) -> bool:
    """태스크 함수가 trace_worker_task 로 계측되었는지 확인합니다."""
    target = getattr(fn, "coroutine", fn)
    return getattr(target, "__traced_worker_task__", False) is True


def get_all_worker_tasks() -> list[Any]:
    """WorkerSettings 에 등록된 모든 고유 태스크 함수(일반 + 크론)를 반환합니다."""
    seen = set()
    tasks = []
    all_raw = list(WorkerSettings.functions)
    for c in WorkerSettings.cron_jobs:
        all_raw.append(c)
    for item in all_raw:
        target = getattr(item, "coroutine", item)
        if target not in seen:
            seen.add(target)
            tasks.append(target)
    return tasks


def ensure_all_worker_tasks_traced() -> None:
    """새 태스크 등록 시 배선 누락을 방어하기 위해 WorkerSettings.functions 의 계측을 보장합니다."""
    new_functions = []
    for fn in WorkerSettings.functions:
        target = getattr(fn, "coroutine", fn)
        if not is_task_traced(target):
            wrapped = traced_worker_task(target)
            new_functions.append(wrapped)
        else:
            new_functions.append(fn)
    WorkerSettings.functions = new_functions


def _apply_catchup_job_timeout(functions: list[Any]) -> list[Any]:
    """따라잡기 잡은 야간 크론과 같은 3시간 제한을 쓰되 함수 목록의 __name__ 은 유지합니다."""
    updated: list[Any] = []
    for fn in functions:
        target = getattr(fn, "coroutine", fn)
        if getattr(target, "__name__", "") != SCHEDULE_CATCHUP_JOB_NAME:
            updated.append(fn)
            continue
        if getattr(fn, "timeout_s", None) is not None:
            updated.append(fn)
            continue
        wrapped = arq_func(
            target,
            name=SCHEDULE_CATCHUP_JOB_NAME,
            timeout=SCHEDULE_CATCHUP_JOB_TIMEOUT_SECONDS,
        )
        cast(Any, wrapped).__name__ = SCHEDULE_CATCHUP_JOB_NAME
        updated.append(wrapped)
    return updated


HEAVY_JOB_TIMEOUT_SECONDS = 10800  # 3시간 (야간 크론 및 따라잡기와 동일한 넉넉한 상한)


def _apply_heavy_task_settings(functions: list[Any]) -> list[Any]:
    """무거운 태스크는 큐 대기 시간과 실행 시간을 고려해 3시간 타임아웃을 적용합니다."""
    updated: list[Any] = []
    for fn in functions:
        target = getattr(fn, "coroutine", fn)
        fn_name = getattr(target, "__name__", "")
        if fn_name not in HEAVY_TASK_NAMES:
            updated.append(fn)
            continue
        if getattr(fn, "timeout_s", None) is not None:
            updated.append(fn)
            continue
        wrapped = arq_func(
            target,
            name=fn_name,
            timeout=HEAVY_JOB_TIMEOUT_SECONDS,
        )
        cast(Any, wrapped).__name__ = fn_name
        updated.append(wrapped)
    return updated


ensure_all_worker_tasks_traced()
WorkerSettings.functions = _apply_catchup_job_timeout(WorkerSettings.functions)
WorkerSettings.functions = _apply_heavy_task_settings(WorkerSettings.functions)
