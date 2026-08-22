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
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
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
    from src.app.core.config import settings

    DEFAULT_REDIS_URL = settings.REDIS_URL
except Exception:
    DEFAULT_REDIS_URL = "redis://localhost:6379/0"

logger = logging.getLogger("benchmark_arq_throughput")


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

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "git_sha": self.git_sha,
            "timestamp": self.timestamp,
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

    env_data = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "redis_url": config.redis_url,
    }

    return BenchmarkResult(
        status=status,
        git_sha=git_sha or get_git_sha(),
        timestamp=datetime.now(UTC).isoformat(),
        environment=env_data,
        config=config,
        summary=summary,
        latency_ms=latency_data,
        errors=errors,
    )


async def run_arq_throughput_benchmark(
    redis_url: str = DEFAULT_REDIS_URL,
    total_jobs: int = 100,
    concurrency: int = 10,
    job_delay_ms: float = 0.0,
    poll_delay_sec: float = 0.01,
    timeout_sec: float = 60.0,
    simulate_error_rate: float = 0.0,
) -> BenchmarkResult:
    """독립형 벤치마크를 비동기 실행하고 결과를 반환합니다."""
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

        await cleanup_benchmark_resources(redis_pool, queue_name, all_job_ids)
        await redis_pool.close()

    return aggregate_benchmark_metrics(
        config=config,
        collected_results=results_collector,
        total_duration_sec=total_duration,
        extra_errors=extra_errors,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
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
        "--output",
        "-o",
        type=Path,
        default=None,
        help="결과 JSON 저장 경로",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="요약 리포트 출력을 생략합니다",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)

    if args.jobs <= 0:
        print("오류: --jobs 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    if args.concurrency <= 0:
        print("오류: --concurrency 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2

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
            )
        )
    except RedisConnectionError as r_err:
        print(f"Redis 연결 오류: {r_err}", file=sys.stderr)
        print(
            "Redis 서버가 기동되어 있는지 확인하십시오 (예: docker compose up -d redis).",
            file=sys.stderr,
        )
        return 2
    except Exception as exc:
        print(f"벤치마크 실행 실패: {exc}", file=sys.stderr)
        return 1

    if not args.quiet:
        result.report()

    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(result.as_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        print(f"측정 결과 저장 완료: {args.output}")

    return 0 if (result.status == "success" and result.summary.get("error_count", 0) == 0) else 1


if __name__ == "__main__":
    raise SystemExit(main())
