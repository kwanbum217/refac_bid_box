"""
scripts/benchmark_arq_throughput.py

운영 환경 격리형 Arq 처리량 및 Enqueue-to-Complete 지연 벤치마크 하네스.

운영 DB, ChromaDB, ML 가중치 모델 및 운영 Arq 큐(arq:queue)에 일체 접근하지 않고,
전용 고유 큐(arq:benchmark:<id>)와 무해한 합성 작업을 사용하여 Arq 워커의
처리량(jobs/sec), 동시성 처리 성능, enqueue-to-complete P50/P95/P99 지연을 측정합니다.
종료 시 생성된 Redis 키를 안전하게 정리합니다.

실행:
    uv run python scripts/benchmark_arq_throughput.py --jobs 100 --concurrency 10
    uv run python scripts/benchmark_arq_throughput.py --jobs 500 --concurrency 20 --output data/benchmarks/arq_throughput.json
    uv run python scripts/benchmark_arq_throughput.py --jobs 600 --concurrency 10 --repetitions 3 --output data/benchmarks/arq_inprocess_measure_20260823.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.metadata
import logging
import os
import platform
import statistics
import subprocess  # nosec B404
import sys
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arq import create_pool
from arq.connections import ArqRedis, RedisSettings
from arq.worker import Worker

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts._strict_json import dump_strict_json
except (ModuleNotFoundError, ImportError):
    from _strict_json import dump_strict_json  # type: ignore[no-redef]

try:
    from scripts.benchmark_provenance import (
        BuildProvenanceError,
        build_load_protocol_record,
        build_provenance_dict,
        check_ambient_load_protocol,
        compute_baseline_summary,
        enforce_provenance_required_fields,
        frozen_baseline_path,
        get_git_status,
        get_host_memory,
        host_load_metadata,
        resolve_redis_container,
        single_host_load_sample,
    )
except (ModuleNotFoundError, ImportError):
    from benchmark_provenance import (  # type: ignore[no-redef]
        BuildProvenanceError,
        build_load_protocol_record,
        build_provenance_dict,
        check_ambient_load_protocol,
        compute_baseline_summary,
        enforce_provenance_required_fields,
        frozen_baseline_path,
        get_git_status,
        get_host_memory,
        host_load_metadata,
        resolve_redis_container,
        single_host_load_sample,
    )

try:
    from src.app.core.config import settings

    DEFAULT_REDIS_URL = settings.REDIS_URL
except Exception:
    DEFAULT_REDIS_URL = "redis://localhost:6379/0"

logger = logging.getLogger("benchmark_arq_throughput")


async def fetch_redis_server_info(redis: ArqRedis) -> dict[str, str]:
    """Redis 서버 INFO server 섹션에서 버전 및 실행 모드를 조회합니다."""
    server_info = {"server_version": "unknown", "server_mode": "unknown"}
    try:
        raw_info = await redis.info("server")
        if isinstance(raw_info, dict):
            server_info["server_version"] = str(raw_info.get("redis_version", "unknown"))
            server_info["server_mode"] = str(raw_info.get("redis_mode", "standalone"))
    except Exception as exc:
        logger.warning("Redis INFO server 조회 중 예외: %s", exc)
    return server_info


def verify_identity_consistency(
    start_ident: dict[str, Any],
    end_ident: dict[str, Any],
    strict: bool = True,
) -> bool:
    """측정 시작과 종료 시점의 identity 일치 여부를 검증합니다."""
    mismatches: list[str] = []
    for key, start_val in start_ident.items():
        end_val = end_ident.get(key)
        if start_val != end_val:
            mismatches.append(f"{key} changed from '{start_val}' to '{end_val}'")

    if mismatches:
        err_msg = (
            "Target/container/source provenance changed during benchmark measurement: "
            + ", ".join(mismatches)
        )
        if strict:
            raise BuildProvenanceError(err_msg)
        return False
    return True


def get_arq_version() -> str:
    """arq 라이브러리 버전을 반환합니다."""
    try:
        return importlib.metadata.version("arq")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def get_redis_py_version() -> str:
    """redis-py 라이브러리 버전을 반환합니다."""
    try:
        return importlib.metadata.version("redis")
    except importlib.metadata.PackageNotFoundError:
        return "unknown"


def get_docker_version() -> str:
    """Docker 엔진 버전을 반환합니다."""
    try:
        return subprocess.check_output(  # nosec B603 B607
            ["docker", "--version"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def inspect_redis_container(
    redis_url: str = "",
    target: str | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """현재 기동 중인 Redis 컨테이너 정보를 명시 지정 또는 fail-closed 로 조회합니다.

    공통 모듈의 resolve_redis_container 에 위임합니다. 후보가 0개 또는 2개 이상이면
    자동 선택하지 않고 BuildProvenanceError 로 중단하며, 조회 예외를 unknown 성공으로
    흡수하지 않습니다.
    """
    return resolve_redis_container(redis_url=redis_url, target=target, strict=strict)


class RedisConnectionError(Exception):
    """Redis 연결 실패 또는 통신 불가 시 발생하는 예외."""


class BenchmarkExecutionError(Exception):
    """벤치마크 실행 도중 타임아웃 또는 치명적 오류 발생 시 예외."""


def generate_benchmark_queue_name(prefix: str = "arq:benchmark") -> str:
    """충돌을 방지하는 고유 벤치마크 큐 이름을 생성합니다."""
    return f"{prefix}:{uuid.uuid4().hex[:12]}"


def calculate_percentile(values: list[float], q: float) -> float:
    """선형 보간 기반 백분위수를 계산합니다 (0.0 <= q <= 100.0)."""
    if not values:
        return float("nan")
    ordered = sorted(values)
    position = (len(ordered) - 1) * (q / 100.0)
    lower = int(position)
    upper = min(lower + 1, len(ordered) - 1)
    weight = position - lower
    return ordered[lower] * (1 - weight) + ordered[upper] * weight


def calculate_percentiles(values: list[float]) -> dict[str, float]:
    """주요 백분위수와 기술 통계량을 딕셔너리로 반환합니다."""
    if not values:
        return {
            "p50_ms": 0.0,
            "p95_ms": 0.0,
            "p99_ms": 0.0,
            "min_ms": 0.0,
            "max_ms": 0.0,
            "mean_ms": 0.0,
        }
    return {
        "p50_ms": round(calculate_percentile(values, 50.0), 3),
        "p95_ms": round(calculate_percentile(values, 95.0), 3),
        "p99_ms": round(calculate_percentile(values, 99.0), 3),
        "min_ms": round(min(values), 3),
        "max_ms": round(max(values), 3),
        "mean_ms": round(statistics.fmean(values), 3),
    }


async def benchmark_noop_task(
    ctx: dict[str, Any],
    job_id: str,
    enqueue_time_perf: float,
    simulate_delay_sec: float = 0.0,
    should_fail: bool = False,
) -> dict[str, Any]:
    """운영 자원에 접근하지 않는 무해한 벤치마크 합성 태스크입니다."""
    results: list[dict[str, Any]] | None = ctx.get("results")
    total_expected: int = ctx.get("total_expected", 0)
    completion_event: asyncio.Event | None = ctx.get("completion_event")

    try:
        if simulate_delay_sec > 0:
            await asyncio.sleep(simulate_delay_sec)

        if should_fail:
            raise RuntimeError(f"Simulated benchmark failure for job {job_id}")

        t_complete = time.perf_counter()
        latency_ms = (t_complete - enqueue_time_perf) * 1000.0

        if results is not None:
            results.append(
                {
                    "job_id": job_id,
                    "latency_ms": latency_ms,
                    "success": True,
                    "error": None,
                }
            )
        return {"job_id": job_id, "latency_ms": latency_ms, "status": "success"}

    except Exception as exc:
        t_complete = time.perf_counter()
        latency_ms = (t_complete - enqueue_time_perf) * 1000.0
        if results is not None:
            results.append(
                {
                    "job_id": job_id,
                    "latency_ms": latency_ms,
                    "success": False,
                    "error": str(exc),
                }
            )
        raise
    finally:
        if results is not None and completion_event is not None and len(results) >= total_expected:
            completion_event.set()


async def cleanup_benchmark_resources(
    redis: ArqRedis,
    queue_name: str,
    job_ids: list[str] | None = None,
) -> int:
    """벤치마크 수행 중 생성된 전용 큐 및 작업 키를 정리합니다."""
    keys_to_delete: set[str] = set()
    if queue_name:
        keys_to_delete.add(queue_name)
        keys_to_delete.add(f"{queue_name}:health-check")

    if job_ids:
        for jid in job_ids:
            keys_to_delete.add(f"arq:job:{jid}")
            keys_to_delete.add(f"arq:result:{jid}")
            keys_to_delete.add(f"arq:retry:{jid}")
            keys_to_delete.add(f"arq:abort:{jid}")

    try:
        cursor = 0
        while True:
            cursor, matched = await redis.scan(cursor=cursor, match=f"*{queue_name}*", count=100)
            for k in matched:
                if isinstance(k, bytes):
                    keys_to_delete.add(k.decode("utf-8", errors="ignore"))
                else:
                    keys_to_delete.add(str(k))
            if cursor == 0:
                break
    except Exception as scan_err:
        logger.warning("Redis 스캔 중 예외 발생 (기존 등록 키 삭제 지속): %s", scan_err)

    if not keys_to_delete:
        return 0

    deleted_count = 0
    key_list = list(keys_to_delete)
    for i in range(0, len(key_list), 100):
        chunk = key_list[i : i + 100]
        try:
            res = await redis.delete(*chunk)
            deleted_count += res
        except Exception as del_err:
            logger.warning("키 삭제 중 오류 발생: %s", del_err)

    return deleted_count


@dataclass
class BenchmarkConfig:
    queue_name: str
    total_jobs: int
    concurrency: int
    job_delay_ms: float
    poll_delay_sec: float
    timeout_sec: float
    simulate_error_rate: float
    redis_url: str


@dataclass
class BenchmarkResult:
    status: str
    git_sha: str
    timestamp: str
    environment: dict[str, Any]
    config: BenchmarkConfig
    summary: dict[str, Any]
    latency_ms: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    benchmark_worker_mode: str = "in_process"
    provenance: dict[str, Any] = field(default_factory=dict)
    load_protocol: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "git_sha": self.git_sha,
            "timestamp": self.timestamp,
            "benchmark_worker_mode": self.benchmark_worker_mode,
            "provenance": self.provenance,
            "load_protocol": self.load_protocol,
            "environment": self.environment,
            "config": asdict(self.config),
            "summary": self.summary,
            "latency_ms": self.latency_ms,
            "errors": self.errors,
        }

    def report(self) -> bool:
        print("=" * 64)
        print("Arq 백그라운드 태스크 처리량 벤치마크 결과")
        print("=" * 64)
        print(f"상태: {self.status.upper()}")
        print(f"대상 큐: {self.config.queue_name}")
        print(f"동시성: {self.config.concurrency} | 작업 수: {self.config.total_jobs}")
        print(f"작업 인위 지연: {self.config.job_delay_ms:.1f}ms")
        print("-" * 64)
        print(f"총 소요 시간: {self.summary.get('total_duration_sec', 0.0):.3f}초")
        print(f"처리량 (Throughput): {self.summary.get('jobs_per_second', 0.0):.2f} jobs/sec")
        print(
            f"성공: {self.summary.get('successful_jobs', 0)} / "
            f"실패: {self.summary.get('failed_jobs', 0)} / "
            f"오류 수: {self.summary.get('error_count', 0)}"
        )
        print("-" * 64)
        print("Enqueue-to-Complete 지연 분포 (ms):")
        print(
            f"  P50: {self.latency_ms.get('p50_ms', 0.0):.2f}ms | "
            f"P95: {self.latency_ms.get('p95_ms', 0.0):.2f}ms | "
            f"P99: {self.latency_ms.get('p99_ms', 0.0):.2f}ms"
        )
        print(
            f"  Min: {self.latency_ms.get('min_ms', 0.0):.2f}ms | "
            f"Max: {self.latency_ms.get('max_ms', 0.0):.2f}ms | "
            f"평균: {self.latency_ms.get('mean_ms', 0.0):.2f}ms"
        )
        print("=" * 64)
        return self.status == "success" and self.summary.get("error_count", 0) == 0


def get_git_sha() -> str:
    try:
        return subprocess.check_output(  # nosec B603 B607
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def aggregate_benchmark_metrics(
    config: BenchmarkConfig,
    collected_results: list[dict[str, Any]],
    total_duration_sec: float,
    git_sha: str | None = None,
    extra_errors: list[str] | None = None,
    redis_container: dict[str, Any] | None = None,
    redis_server_version: str = "unknown",
    redis_server_mode: str = "unknown",
    source_mount: Path | str | None = None,
    source_git_sha: str | None = None,
    source_git_dirty: bool | None = None,
) -> BenchmarkResult:
    """수집된 작업 실행 결과 목록을 기반으로 지표를 결정론적으로 집계합니다."""
    errors = list(extra_errors or [])
    successful_jobs = 0
    failed_jobs = 0
    latencies: list[float] = []

    for r in collected_results:
        latency = float(r.get("latency_ms", 0.0))
        latencies.append(latency)
        if r.get("success", False):
            successful_jobs += 1
        else:
            failed_jobs += 1
            if r.get("error"):
                errors.append(f"Job {r.get('job_id')}: {r.get('error')}")

    total_enqueued = config.total_jobs
    missing_jobs = max(0, total_enqueued - len(collected_results))
    if missing_jobs > 0:
        failed_jobs += missing_jobs
        errors.append(f"{missing_jobs}개 작업이 완료되지 못하고 누락되었습니다.")

    error_count = failed_jobs + len(extra_errors or [])
    jobs_per_sec = round(successful_jobs / total_duration_sec, 2) if total_duration_sec > 0 else 0.0

    status = (
        "success" if (error_count == 0 and len(collected_results) == total_enqueued) else "failed"
    )

    percentiles = calculate_percentiles(latencies)
    latency_data = {
        **percentiles,
        "values_ms": [round(val, 3) for val in latencies],
    }

    summary = {
        "total_duration_sec": round(total_duration_sec, 4),
        "jobs_per_second": jobs_per_sec,
        "total_enqueued": total_enqueued,
        "successful_jobs": successful_jobs,
        "failed_jobs": failed_jobs,
        "error_count": error_count,
    }

    # 4계층 Provenance 수집
    if redis_container is not None:
        r_info = redis_container
    else:
        r_info = inspect_redis_container(redis_url=config.redis_url)
    load_sample = single_host_load_sample()
    host_mem = get_host_memory()
    target_mount = str(
        Path(source_mount).resolve() if source_mount is not None else PROJECT_ROOT.resolve()
    )
    effective_git_sha = git_sha or source_git_sha or get_git_sha()
    effective_dirty = (
        source_git_dirty if source_git_dirty is not None else get_git_status(target_mount)[1]
    )
    arq_ver = get_arq_version()
    redis_py_ver = get_redis_py_version()
    dock_ver = get_docker_version()

    provenance = build_provenance_dict(
        host_cpu_count=int(load_sample.get("cpu_count") or os.cpu_count() or 1),
        host_load_avg_1m=load_sample.get("load_1m"),  # type: ignore[arg-type]
        host_memory=host_mem,
        redis_url=config.redis_url,
        redis_container_id=r_info.get("container_id", "unknown"),
        redis_container_name=r_info.get("container_name", "unknown"),
        redis_image=r_info.get("image", "unknown"),
        redis_image_id=r_info.get("image_id", "unknown"),
        redis_server_version=redis_server_version,
        redis_server_mode=redis_server_mode,
        arq_version=arq_ver,
        redis_py_version=redis_py_ver,
        benchmark_worker_mode="in_process",
        worker_settings_module="in_process:Worker",
        worker_functions=["benchmark_noop_task"],
        is_synthetic=True,
        worker_max_jobs=config.concurrency,
        worker_poll_delay=config.poll_delay_sec,
        worker_job_timeout=int(config.timeout_sec),
        docker_version=dock_ver,
        worker_container_id=None,
        worker_container_name=None,
        worker_image=None,
        worker_image_id=None,
        source_mount=target_mount,
        source_git_sha=effective_git_sha,
        source_git_dirty=effective_dirty,
    )

    env_data = {
        # 1. Host
        "python": platform.python_version(),
        "platform": platform.platform(),
        "host_cpu_count": provenance["host"]["cpu_count"],
        "host_load_avg_1m": provenance["host"]["load_avg_1m"],
        "host_memory_total_bytes": provenance["host"]["memory_total_bytes"],
        "host_memory_available_bytes": provenance["host"]["memory_available_bytes"],
        # 2. Redis
        "redis_url": config.redis_url,
        "redis_container_id": provenance["redis"]["container_id"],
        "redis_container_name": provenance["redis"]["container_name"],
        "redis_image": provenance["redis"]["image"],
        "redis_image_id": provenance["redis"]["image_id"],
        "redis_server_version": provenance["redis"]["server_version"],
        "redis_server_mode": provenance["redis"]["server_mode"],
        # 3. Arq
        "arq_version": arq_ver,
        "redis_py_version": redis_py_ver,
        "benchmark_worker_mode": "in_process",
        "worker_settings_module": "in_process:Worker",
        "worker_functions": ["benchmark_noop_task"],
        "is_synthetic": True,
        "worker_max_jobs": config.concurrency,
        "worker_poll_delay": config.poll_delay_sec,
        "worker_job_timeout": int(config.timeout_sec),
        # 4. Docker / Source
        "docker_version": dock_ver,
        "source_mount": target_mount,
        "source_git_sha": effective_git_sha,
        "source_git_dirty": effective_dirty,
    }

    return BenchmarkResult(
        status=status,
        git_sha=effective_git_sha,
        timestamp=datetime.now(UTC).isoformat(),
        environment=env_data,
        config=config,
        summary=summary,
        latency_ms=latency_data,
        errors=errors,
        benchmark_worker_mode="in_process",
        provenance=provenance,
    )


async def run_arq_throughput_benchmark(
    redis_url: str = DEFAULT_REDIS_URL,
    total_jobs: int = 100,
    concurrency: int = 10,
    job_delay_ms: float = 0.0,
    poll_delay_sec: float = 0.01,
    timeout_sec: float = 60.0,
    simulate_error_rate: float = 0.0,
    strict: bool = True,
    source_mount: Path | str | None = None,
    redis_container: str | None = None,
    allow_load_violation: bool = False,
    load_sampler: Any = None,
    load_min_samples: int = 3,
    load_interval_seconds: float = 5.0,
) -> BenchmarkResult:
    """독립형 벤치마크를 비동기 실행하고 결과를 반환합니다."""
    target_source = (
        Path(source_mount).resolve() if source_mount is not None else PROJECT_ROOT.resolve()
    )
    git_sha, git_dirty = get_git_status(target_source)

    if strict:
        failures = []
        if git_sha == "unknown":
            failures.append(f"git_sha(source: {target_source})")
        if git_dirty is None:
            failures.append(f"git_dirty_unknown(source: {target_source})")
        elif git_dirty is True:
            failures.append(f"git_dirty(source: {target_source})")
        if failures:
            raise BuildProvenanceError(
                f"Host/Git provenance check failed (fail-closed): {', '.join(failures)}"
            )

    # 주변 부하 규약: 시작 시점 부하 통계 평가 (strict + 미우회 시 fail-closed)
    start_load_stats = host_load_metadata(
        min_samples=load_min_samples,
        interval_seconds=load_interval_seconds,
        sampler=load_sampler,
    )
    start_load_compliant, start_load_detail = check_ambient_load_protocol(start_load_stats)
    if not start_load_compliant and strict and not allow_load_violation:
        raise BuildProvenanceError(
            "Ambient load protocol violated at start "
            f"(median {start_load_detail.get('median_percent')}% > "
            f"{start_load_detail.get('median_limit_percent')}% or max "
            f"{start_load_detail.get('max_percent')}% > "
            f"{start_load_detail.get('max_limit_percent')}%)"
        )

    queue_name = generate_benchmark_queue_name()
    config = BenchmarkConfig(
        queue_name=queue_name,
        total_jobs=total_jobs,
        concurrency=concurrency,
        job_delay_ms=job_delay_ms,
        poll_delay_sec=poll_delay_sec,
        timeout_sec=timeout_sec,
        simulate_error_rate=simulate_error_rate,
        redis_url=redis_url,
    )

    redis_settings = RedisSettings.from_dsn(redis_url)
    try:
        redis_pool: ArqRedis = await create_pool(redis_settings)
        await redis_pool.ping()
    except Exception as exc:
        raise RedisConnectionError(f"Redis 연결 실패 ({redis_url}): {exc}") from exc

    start_redis_info = inspect_redis_container(
        redis_url=redis_url,
        target=redis_container,
        strict=strict,
    )
    start_server_info = await fetch_redis_server_info(redis_pool)

    if strict and start_redis_info.get("container_id") == "unknown":
        await redis_pool.aclose()
        raise BuildProvenanceError("Redis container inspection failed (container_id unknown)")

    start_identity = {
        "redis_container_id": start_redis_info.get("container_id", "unknown"),
        "redis_image_id": start_redis_info.get("image_id", "unknown"),
        "redis_server_version": start_server_info.get("server_version", "unknown"),
        "redis_server_mode": start_server_info.get("server_mode", "unknown"),
        "source_mount": str(target_source),
        "source_git_sha": git_sha,
        "source_git_dirty": git_dirty,
    }

    results_collector: list[dict[str, Any]] = []
    completion_event = asyncio.Event()
    all_job_ids: list[str] = []
    extra_errors: list[str] = []

    ctx_state = {
        "results": results_collector,
        "total_expected": total_jobs,
        "completion_event": completion_event,
    }

    worker = Worker(
        functions=[benchmark_noop_task],
        queue_name=queue_name,
        redis_pool=redis_pool,
        max_jobs=concurrency,
        poll_delay=poll_delay_sec,
        burst=False,
        health_check_key=f"{queue_name}:health-check",
        ctx=ctx_state,
    )

    worker_task = asyncio.create_task(worker.async_run())
    t_start = time.perf_counter()

    try:
        enqueue_tasks = []
        for i in range(total_jobs):
            job_id = f"bench-{queue_name.split(':')[-1]}-{i}"
            all_job_ids.append(job_id)
            should_fail = (simulate_error_rate > 0.0) and ((i / total_jobs) < simulate_error_rate)
            t_enq = time.perf_counter()
            enqueue_tasks.append(
                redis_pool.enqueue_job(
                    "benchmark_noop_task",
                    job_id=job_id,
                    enqueue_time_perf=t_enq,
                    simulate_delay_sec=job_delay_ms / 1000.0,
                    should_fail=should_fail,
                    _job_id=job_id,
                    _queue_name=queue_name,
                )
            )
        await asyncio.gather(*enqueue_tasks)

        try:
            await asyncio.wait_for(completion_event.wait(), timeout=timeout_sec)
        except TimeoutError:
            extra_errors.append(
                f"지정된 타임아웃({timeout_sec}초) 내에 모든 작업이 완료되지 못했습니다."
            )

    except Exception as exc:
        extra_errors.append(f"작업 실행 중 예외 발생: {exc}")
    finally:
        t_end = time.perf_counter()
        total_duration = t_end - t_start

        await worker.close()
        worker_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await worker_task

        # End identity check
        end_redis_info = inspect_redis_container(
            redis_url=redis_url,
            target=redis_container,
            strict=strict,
        )
        end_server_info = await fetch_redis_server_info(redis_pool)
        end_git_sha, end_git_dirty = get_git_status(target_source)

        end_identity = {
            "redis_container_id": end_redis_info.get("container_id", "unknown"),
            "redis_image_id": end_redis_info.get("image_id", "unknown"),
            "redis_server_version": end_server_info.get("server_version", "unknown"),
            "redis_server_mode": end_server_info.get("server_mode", "unknown"),
            "source_mount": str(target_source),
            "source_git_sha": end_git_sha,
            "source_git_dirty": end_git_dirty,
        }

        try:
            verify_identity_consistency(start_identity, end_identity, strict=strict)
        except BuildProvenanceError as b_err:
            extra_errors.append(str(b_err))

        # 주변 부하 규약: 종료 시점 부하 통계 평가
        end_load_stats = host_load_metadata(
            min_samples=load_min_samples,
            interval_seconds=load_interval_seconds,
            sampler=load_sampler,
        )
        end_load_compliant, end_load_detail = check_ambient_load_protocol(end_load_stats)
        if not end_load_compliant and strict and not allow_load_violation:
            extra_errors.append(
                "Ambient load protocol violated at end "
                f"(median {end_load_detail.get('median_percent')}% > "
                f"{end_load_detail.get('median_limit_percent')}% or max "
                f"{end_load_detail.get('max_percent')}% > "
                f"{end_load_detail.get('max_limit_percent')}%)"
            )

        await cleanup_benchmark_resources(redis_pool, queue_name, all_job_ids)
        await redis_pool.aclose()

    result = aggregate_benchmark_metrics(
        config=config,
        collected_results=results_collector,
        total_duration_sec=total_duration,
        git_sha=git_sha,
        extra_errors=extra_errors,
        redis_container=end_redis_info,
        redis_server_version=end_server_info.get("server_version", "unknown"),
        redis_server_mode=end_server_info.get("server_mode", "unknown"),
        source_mount=target_source,
        source_git_sha=end_git_sha,
        source_git_dirty=end_git_dirty,
    )
    enforce_provenance_required_fields(result.provenance, strict=strict)
    result.load_protocol = build_load_protocol_record(
        start_compliant=start_load_compliant,
        start_detail=start_load_detail,
        end_compliant=end_load_compliant,
        end_detail=end_load_detail,
        strict=strict,
        allow_violation=allow_load_violation,
    )
    return result


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="운영 격리형 Arq 처리량 및 지연 벤치마크 하네스")
    parser.add_argument(
        "--jobs",
        "-n",
        type=int,
        default=100,
        help="적재할 총 작업 수 (기본값: 100)",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=10,
        help="워커 최대 동시 처리 수 (기본값: 10)",
    )
    parser.add_argument(
        "--job-delay-ms",
        "-d",
        type=float,
        default=0.0,
        help="작업별 인위 지연 시간(ms) (기본값: 0.0)",
    )
    parser.add_argument(
        "--poll-delay",
        type=float,
        default=0.01,
        help="워커 큐 폴링 주기(초) (기본값: 0.01)",
    )
    parser.add_argument(
        "--simulate-error-rate",
        type=float,
        default=0.0,
        help="인위 실패율 (0.0~1.0, 기본값: 0.0)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=60.0,
        help="벤치마크 최대 타임아웃(초) (기본값: 60.0)",
    )
    parser.add_argument(
        "--redis-url",
        default=DEFAULT_REDIS_URL,
        help=f"Redis 접속 URL (기본값: {DEFAULT_REDIS_URL})",
    )
    parser.add_argument(
        "--source-mount",
        default=None,
        help=f"호스트 소스 마운트 경로 (기본값: {PROJECT_ROOT})",
    )
    parser.add_argument(
        "--redis-container",
        default=None,
        help=(
            "측정 대상 Redis 컨테이너 이름/ID 또는 docker compose 서비스명. "
            "미지정 시 name=redis 후보가 정확히 1개일 때만 자동 채택하고, "
            "0개 또는 2개 이상이면 오류로 중단합니다 (fail-closed)"
        ),
    )
    parser.add_argument(
        "--allow-unknown-provenance",
        action="store_true",
        default=False,
        help="Docker/Git provenance 조회 실패 또는 dirty 상태 시에도 측정을 강제 진행합니다 (기본: 거부)",
    )
    parser.add_argument(
        "--allow-load-protocol-violation",
        action="store_true",
        default=False,
        help=(
            "주변 부하 규약(중앙값 30%%, 최대 50%%) 위반에도 측정을 진행합니다. "
            "우회 측정은 결과에 미준수 표시를 남기며 정본 evidence 가 아닙니다 (기본: 거부)"
        ),
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="결과 JSON 저장 경로",
    )
    parser.add_argument(
        "--frozen-baseline",
        action="store_true",
        default=False,
        help=(
            "frozen baseline 경로 규약으로 결과를 저장합니다. "
            "data/benchmarks/frozen/arq/<mode>/<git_sha_short>/ 경로를 자동 구성하고 "
            "중간 디렉터리를 자동 생성하므로 사전 mkdir 이 필요 없습니다. "
            "--output 보다 우선합니다"
        ),
    )
    parser.add_argument(
        "--repetitions",
        "-r",
        type=int,
        default=1,
        help="반복 측정 횟수 (기본값: 1)",
    )
    parser.add_argument(
        "--run-interval-sec",
        type=float,
        default=30.0,
        help="반복 측정 간 대기 시간(초) (기본값: 30.0)",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="요약 리포트 출력을 생략합니다",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.jobs <= 0:
        print("오류: --jobs 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    if args.concurrency <= 0:
        print("오류: --concurrency 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    if args.repetitions < 1:
        print("오류: --repetitions 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2

    # frozen baseline 경로 규약 우선, 미지정 시 기존 --output 동작 유지 (하위 호환)
    if args.frozen_baseline:
        output_path = frozen_baseline_path(mode="inprocess", git_sha=get_git_sha())
    else:
        output_path = args.output

    strict = not args.allow_unknown_provenance
    results: list[BenchmarkResult] = []
    saved_paths: list[Path] = []

    for run_idx in range(1, args.repetitions + 1):
        if args.repetitions > 1 and not args.quiet:
            print(f"\n>>> [회차 {run_idx}/{args.repetitions}] 실측 시작...")

        try:
            result = asyncio.run(
                run_arq_throughput_benchmark(
                    redis_url=args.redis_url,
                    total_jobs=args.jobs,
                    concurrency=args.concurrency,
                    job_delay_ms=args.job_delay_ms,
                    poll_delay_sec=args.poll_delay,
                    timeout_sec=args.timeout,
                    simulate_error_rate=args.simulate_error_rate,
                    strict=strict,
                    source_mount=args.source_mount,
                    redis_container=args.redis_container,
                    allow_load_violation=args.allow_load_protocol_violation,
                )
            )
            results.append(result)
        except RedisConnectionError as r_err:
            print(f"Redis 연결 오류: {r_err}", file=sys.stderr)
            return 2
        except BuildProvenanceError as b_err:
            print(f"Provenance 검증 실패: {b_err}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"벤치마크 실행 실패: {exc}", file=sys.stderr)
            return 1

        if not args.quiet:
            result.report()

        # 개별 회차 파일 저장 (output 지정 시 _r1, _r2 등 접미사)
        if output_path and args.repetitions > 1:
            stem = output_path.stem
            suffix = output_path.suffix
            r_path = output_path.parent / f"{stem}_r{run_idx}{suffix}"
            try:
                r_path.parent.mkdir(parents=True, exist_ok=True)
                r_path.write_text(dump_strict_json(result.as_dict()), encoding="utf-8")
                saved_paths.append(r_path)
                if not args.quiet:
                    print(f"회차 {run_idx} 결과 저장: {r_path}")
            except Exception as w_err:
                print(f"회차 {run_idx} 파일 저장 실패: {w_err}", file=sys.stderr)
                return 1

        # 다음 회차 전 대기
        if run_idx < args.repetitions and args.run_interval_sec > 0:
            if not args.quiet:
                print(f"다음 회차 전 {args.run_interval_sec}초 대기 중...")
            time.sleep(args.run_interval_sec)

    # 반복 회차 검증 계약: repetitions 수만큼 정상 결과 및 파일 수집 확인
    if len(results) != args.repetitions:
        print(
            f"오류: 요청된 {args.repetitions}회 중 {len(results)}회만 완료되었습니다.",
            file=sys.stderr,
        )
        return 1

    if output_path and args.repetitions > 1:
        for r_idx, r_path in enumerate(saved_paths, start=1):
            if not r_path.exists() or r_path.stat().st_size == 0:
                print(f"오류: 회차 {r_idx} 결과 파일 누락 또는 0바이트: {r_path}", file=sys.stderr)
                return 1

    # 대표 결과 선정: P95 기준 최악 대표값
    worst_result = max(results, key=lambda r: float(r.latency_ms.get("p95_ms", 0.0)))

    if output_path:
        try:
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(
                dump_strict_json(worst_result.as_dict()),
                encoding="utf-8",
            )
            if not args.quiet:
                print(f"\n최종 대표 결과 저장 완료: {output_path}")
        except Exception as out_err:
            print(f"대표 결과 저장 실패: {out_err}", file=sys.stderr)
            return 1

    # 설계서 6장 중앙값 기준선 요약 자동 산출 (별도 파일로 저장, 기존 대표 파일은 유지)
    if output_path and len(results) > 1:
        baseline_summary = compute_baseline_summary([r.as_dict() for r in results])
        summary_path = output_path.with_name(
            f"{output_path.stem}_baseline_summary{output_path.suffix}"
        )
        try:
            summary_path.write_text(
                dump_strict_json(baseline_summary),
                encoding="utf-8",
            )
            if not args.quiet:
                print(f"\n기준선 요약 저장 완료: {summary_path}")
        except Exception as sum_err:
            print(f"기준선 요약 저장 실패: {sum_err}", file=sys.stderr)
            return 1

    all_success = all(
        r.status == "success" and r.summary.get("error_count", 0) == 0 for r in results
    )
    return 0 if all_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
