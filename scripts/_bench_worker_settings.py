"""
scripts/_bench_worker_settings.py

Docker 컨테이너 전용 Arq 워커 벤치마크 WorkerSettings 모듈.

운영 워커(src/tasks/worker.py)의 무결성을 100% 보존하고,
운영 WorkerSettings.functions 목록을 오염시키지 않으면서
동일한 Docker 이미지 및 런타임 환경에서 독립 큐(arq:benchmark:<id>)를
폴링하는 전용 WorkerSettings 를 정의합니다.
"""

from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any, ClassVar

from arq.connections import RedisSettings


async def benchmark_noop_task(
    ctx: dict[str, Any],
    job_id: str,
    enqueue_time_perf: float = 0.0,
    simulate_delay_sec: float = 0.0,
    should_fail: bool = False,
) -> dict[str, Any]:
    """컨테이너 워커 프로세스에서 실행되는 무해한 벤치마크 합성 태스크."""
    redis = ctx.get("redis")
    queue_name = ctx.get("queue_name") or os.environ.get("BENCH_QUEUE_NAME", "arq:benchmark")
    try:
        if simulate_delay_sec > 0:
            await asyncio.sleep(simulate_delay_sec)
        if should_fail:
            raise RuntimeError(f"Simulated benchmark failure for job {job_id}")

        result_payload = {
            "job_id": job_id,
            "success": True,
            "error": None,
            "worker_time": time.time(),
        }
        if redis:
            await redis.rpush(f"{queue_name}:done", json.dumps(result_payload))
        return result_payload
    except Exception as exc:
        result_payload = {
            "job_id": job_id,
            "success": False,
            "error": str(exc),
            "worker_time": time.time(),
        }
        if redis:
            await redis.rpush(f"{queue_name}:done", json.dumps(result_payload))
        raise


async def startup(ctx: dict[str, Any]) -> None:
    """워커 시작 시 컨텍스트 초기화."""
    ctx["queue_name"] = os.environ.get("BENCH_QUEUE_NAME", "arq:benchmark")


class WorkerSettings:
    """벤치마크 전용 WorkerSettings."""

    is_synthetic: ClassVar[bool] = True
    benchmark_worker_mode: ClassVar[str] = "docker_container"
    worker_settings_module: ClassVar[str] = "scripts._bench_worker_settings.WorkerSettings"

    functions: ClassVar[list[Any]] = [benchmark_noop_task]
    on_startup = startup
    redis_settings = RedisSettings.from_dsn(os.environ.get("REDIS_URL", "redis://localhost:6379/0"))
    queue_name = os.environ.get("BENCH_QUEUE_NAME", "arq:benchmark")
    max_jobs = int(os.environ.get("BENCH_MAX_JOBS", "4"))
    poll_delay = float(os.environ.get("BENCH_POLL_DELAY", "0.01"))
    job_timeout = int(os.environ.get("BENCH_JOB_TIMEOUT", "60"))
    keep_result = 3600
    allow_abort_jobs = True
    health_check_key = os.environ.get("BENCH_HEALTH_KEY", f"{queue_name}:health-check")
