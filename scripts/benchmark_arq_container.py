"""
scripts/benchmark_arq_container.py

실제 Docker 컨테이너 Arq 워커 대상 처리량 및 Enqueue-to-Complete 지연 벤치마크 하네스.

운영 워커(src/tasks/worker.py) 및 운영 큐(arq:queue)를 일체 변경/오염시키지 않고,
동일한 Docker 이미지(refac_bid_box-worker:latest)로 벤치마크 전용 WorkerSettings
(scripts/_bench_worker_settings.py)를 실행하는 일회성 컨테이너를 기동하여
업무 큐 처리량(jobs/sec), 동시성(max_jobs=4), P50/P95/P99 지연 및 실패율을 실측합니다.
종료 시 일회성 컨테이너와 Redis 키를 안전하게 정리합니다.

실행:
    uv run python scripts/benchmark_arq_container.py --jobs 600 --concurrency 4
    uv run python scripts/benchmark_arq_container.py --jobs 600 --concurrency 4 --output data/benchmarks/arq_container_measure_20260823.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import importlib.metadata
import json
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
        _parse_source_mount,
        is_source_dirty,
        single_host_load_sample,
    )
except (ModuleNotFoundError, ImportError):
    from benchmark_provenance import (  # type: ignore[no-redef]
        BuildProvenanceError,
        _parse_source_mount,
        is_source_dirty,
        single_host_load_sample,
    )

try:
    from src.app.core.config import settings

    DEFAULT_REDIS_URL = settings.REDIS_URL
except Exception:
    DEFAULT_REDIS_URL = "redis://localhost:6379/0"

logger = logging.getLogger("benchmark_arq_container")


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


def get_host_memory() -> dict[str, int | None]:
    """호스트 물리 메모리 크기(total, available)를 바이트 단위로 안전하게 수집합니다."""
    total_bytes: int | None = None
    available_bytes: int | None = None

    if hasattr(os, "sysconf"):
        try:
            pages = os.sysconf("SC_PHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if (
                isinstance(pages, int)
                and isinstance(page_size, int)
                and pages > 0
                and page_size > 0
            ):
                total_bytes = pages * page_size
        except (ValueError, OSError):
            pass
        try:
            avail_pages = os.sysconf("SC_AVPHYS_PAGES")
            page_size = os.sysconf("SC_PAGE_SIZE")
            if (
                isinstance(avail_pages, int)
                and isinstance(page_size, int)
                and avail_pages > 0
                and page_size > 0
            ):
                available_bytes = avail_pages * page_size
        except (ValueError, OSError):
            pass

    if total_bytes is None and Path("/proc/meminfo").exists():
        with contextlib.suppress(Exception):
            meminfo = Path("/proc/meminfo").read_text(encoding="utf-8")
            for line in meminfo.splitlines():
                if line.startswith("MemTotal:"):
                    total_bytes = int(line.split()[1]) * 1024
                elif line.startswith("MemAvailable:"):
                    available_bytes = int(line.split()[1]) * 1024

    if total_bytes is None and platform.system() == "Darwin":
        with contextlib.suppress(Exception):
            out = subprocess.check_output(  # nosec B603 B607
                ["sysctl", "-n", "hw.memsize"],
                text=True,
            ).strip()
            total_bytes = int(out)

    return {
        "total_bytes": total_bytes,
        "available_bytes": available_bytes,
    }


def get_git_status(path: Path | str | None = None) -> tuple[str, bool | None]:
    """지정된 디렉터리의 Git SHA 및 dirty 상태를 반환합니다.

    Returns:
        tuple[git_sha, is_dirty]
        - git_sha: 커밋 SHA 또는 "unknown"
        - is_dirty: True (dirty), False (clean), None (unknown/Git 오류)
    """
    target_path = Path(path).resolve() if path is not None else PROJECT_ROOT
    try:
        sha = subprocess.check_output(  # nosec B603 B607
            ["git", "-C", str(target_path), "rev-parse", "HEAD"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        sha = "unknown"

    try:
        status = subprocess.check_output(  # nosec B603 B607
            ["git", "-C", str(target_path), "status", "--porcelain"],
            text=True,
        ).strip()
        is_dirty = is_source_dirty(status)
    except (OSError, subprocess.CalledProcessError):
        is_dirty = None

    return sha, is_dirty


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
            "Target container/image/source provenance changed during benchmark measurement: "
            + ", ".join(mismatches)
        )
        if strict:
            raise BuildProvenanceError(err_msg)
        return False
    return True


def build_provenance_dict(
    *,
    host_cpu_count: int,
    host_load_avg_1m: float | None,
    host_memory: dict[str, int | None],
    redis_url: str,
    redis_container_id: str,
    redis_container_name: str,
    redis_image: str,
    redis_image_id: str,
    redis_server_version: str,
    redis_server_mode: str,
    arq_version: str,
    redis_py_version: str,
    benchmark_worker_mode: str,
    worker_settings_module: str,
    worker_functions: list[str],
    is_synthetic: bool,
    worker_max_jobs: int,
    worker_poll_delay: float,
    worker_job_timeout: int,
    docker_version: str,
    worker_container_id: str | None,
    worker_container_name: str | None,
    worker_image: str | None,
    worker_image_id: str | None,
    source_mount: str | None,
    source_git_sha: str | None,
    source_git_dirty: bool | None,
) -> dict[str, Any]:
    """공통 4계층 Provenance 딕셔너리 구조를 생성합니다."""
    return {
        "host": {
            "python_version": platform.python_version(),
            "platform": platform.platform(),
            "cpu_count": host_cpu_count,
            "load_avg_1m": host_load_avg_1m,
            "memory_total_bytes": host_memory.get("total_bytes"),
            "memory_available_bytes": host_memory.get("available_bytes"),
        },
        "redis": {
            "redis_url": redis_url,
            "container_id": redis_container_id,
            "container_name": redis_container_name,
            "image": redis_image,
            "image_id": redis_image_id,
            "server_version": redis_server_version,
            "server_mode": redis_server_mode,
        },
        "arq": {
            "arq_version": arq_version,
            "redis_py_version": redis_py_version,
            "benchmark_worker_mode": benchmark_worker_mode,
            "worker_settings_module": worker_settings_module,
            "worker_functions": list(worker_functions),
            "is_synthetic": is_synthetic,
            "worker_max_jobs": worker_max_jobs,
            "worker_poll_delay": worker_poll_delay,
            "worker_job_timeout": worker_job_timeout,
        },
        "docker": {
            "docker_version": docker_version,
            "worker_container_id": worker_container_id,
            "worker_container_name": worker_container_name,
            "worker_image": worker_image,
            "worker_image_id": worker_image_id,
            "source_mount": source_mount,
            "source_git_sha": source_git_sha,
            "source_git_dirty": source_git_dirty,
        },
    }


class RedisConnectionError(Exception):
    """Redis 연결 실패 또는 통신 불가 시 발생하는 예외."""


class ContainerLifecycleError(Exception):
    """Docker 컨테이너 생성, 기동, 조회 또는 삭제 실패 시 예외."""


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


def get_git_sha() -> str:
    try:
        return subprocess.check_output(  # nosec B603 B607
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def get_docker_version() -> str:
    try:
        return subprocess.check_output(  # nosec B603 B607
            ["docker", "--version"],
            text=True,
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unknown"


def inspect_redis_container() -> dict[str, Any]:
    """현재 기동 중인 Redis 컨테이너 정보를 조회합니다."""
    info: dict[str, Any] = {
        "container_id": "unknown",
        "container_name": "unknown",
        "image": "unknown",
        "image_id": "unknown",
        "network": "arq-docker-measure_default",
    }
    try:
        ps_out = subprocess.check_output(  # nosec B603 B607
            ["docker", "ps", "--filter", "name=redis", "--format", "{{json .}}"],
            text=True,
        ).strip()
        lines = [line for line in ps_out.splitlines() if line]
        if lines:
            c = json.loads(lines[0])
            cid = c.get("ID", "")
            info["container_id"] = cid
            info["container_name"] = c.get("Names", "")
            info["image"] = c.get("Image", "")

            inspect_out = subprocess.check_output(  # nosec B603 B607
                ["docker", "inspect", cid],
                text=True,
            )
            data = json.loads(inspect_out)[0]
            info["image_id"] = data.get("Image", "")
            nets = list(data.get("NetworkSettings", {}).get("Networks", {}).keys())
            if nets:
                info["network"] = nets[0]
    except Exception as exc:
        logger.warning("Redis 컨테이너 정보 조회 중 예외: %s", exc)
    return info


def inspect_image_id(image_name: str) -> str:
    try:
        inspect_out = subprocess.check_output(  # nosec B603 B607
            ["docker", "inspect", "--format", "{{.Id}}", image_name],
            text=True,
        ).strip()
        return inspect_out
    except Exception:
        return "unknown"


async def cleanup_benchmark_resources(
    redis: ArqRedis,
    queue_name: str,
    job_ids: list[str] | None = None,
) -> int:
    """벤치마크 수행 중 생성된 전용 큐 및 작업 키를 정리합니다."""
    keys_to_delete: set[str] = set()
    if queue_name:
        keys_to_delete.add(queue_name)
        keys_to_delete.add(f"{queue_name}:done")
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
class ContainerBenchmarkConfig:
    queue_name: str
    total_jobs: int
    concurrency: int
    job_delay_ms: float
    poll_delay_sec: float
    timeout_sec: float
    simulate_error_rate: float
    redis_url: str
    container_image: str
    container_network: str
    source_mount: str


@dataclass
class BenchmarkResult:
    status: str
    git_sha: str
    timestamp: str
    environment: dict[str, Any]
    config: ContainerBenchmarkConfig
    summary: dict[str, Any]
    latency_ms: dict[str, Any]
    errors: list[str] = field(default_factory=list)
    benchmark_worker_mode: str = "docker_container"
    provenance: dict[str, Any] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "git_sha": self.git_sha,
            "timestamp": self.timestamp,
            "benchmark_worker_mode": self.benchmark_worker_mode,
            "provenance": self.provenance,
            "environment": self.environment,
            "config": asdict(self.config),
            "summary": self.summary,
            "latency_ms": self.latency_ms,
            "errors": self.errors,
        }

    def report(self) -> bool:
        print("=" * 68)
        print("Arq Docker 컨테이너 워커 처리량 및 지연 실측 결과")
        print("=" * 68)
        print(f"상태: {self.status.upper()}")
        print(f"대상 큐: {self.config.queue_name}")
        print(f"동시성(max_jobs): {self.config.concurrency} | 작업 수: {self.config.total_jobs}")
        print(f"워커 컨테이너 ID: {self.environment.get('worker_container_id', 'N/A')[:12]}")
        print(f"워커 이미지: {self.config.container_image}")
        print(f"Redis 컨테이너 ID: {self.environment.get('redis_container_id', 'N/A')[:12]}")
        print(f"작업 인위 지연: {self.config.job_delay_ms:.1f}ms")
        print("-" * 68)
        print(f"총 소요 시간: {self.summary.get('total_duration_sec', 0.0):.4f}초")
        print(f"처리량 (Throughput): {self.summary.get('jobs_per_second', 0.0):.2f} jobs/sec")
        print(
            f"성공: {self.summary.get('successful_jobs', 0)} / "
            f"실패: {self.summary.get('failed_jobs', 0)} / "
            f"오류 수: {self.summary.get('error_count', 0)}"
        )
        print("-" * 68)
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
        print("=" * 68)
        return self.status == "success" and self.summary.get("error_count", 0) == 0


class DockerWorkerContainerManager:
    """일회성 벤치마크 워커 컨테이너를 기동 및 관리/정리하는 컨텍스트 관리자."""

    def __init__(
        self,
        image: str,
        network: str,
        queue_name: str,
        concurrency: int = 4,
        poll_delay_sec: float = 0.01,
        container_redis_url: str = "redis://redis:6379/0",
        source_mount: Path | str | None = None,
    ) -> None:
        self.image = image
        self.network = network
        self.queue_name = queue_name
        self.concurrency = concurrency
        self.poll_delay_sec = poll_delay_sec
        self.container_redis_url = container_redis_url
        self.source_mount = str(
            Path(source_mount).resolve() if source_mount is not None else PROJECT_ROOT.resolve()
        )
        self.container_name = f"arq-bench-worker-{uuid.uuid4().hex[:8]}"
        self.container_id: str | None = None
        self.mounted_source: str | None = None

    def start(self) -> str:
        """컨테이너를 기동하고 컨테이너 ID를 반환합니다."""
        cmd = [
            "docker",
            "run",
            "-d",
            "--name",
            self.container_name,
            "--network",
            self.network,
            "-e",
            f"REDIS_URL={self.container_redis_url}",
            "-e",
            f"BENCH_QUEUE_NAME={self.queue_name}",
            "-e",
            f"BENCH_MAX_JOBS={self.concurrency}",
            "-e",
            f"BENCH_POLL_DELAY={self.poll_delay_sec}",
            "-v",
            f"{self.source_mount}:/app",
            "-w",
            "/app",
            self.image,
            "arq",
            "scripts._bench_worker_settings.WorkerSettings",
        ]
        try:
            cid = subprocess.check_output(cmd, text=True).strip()  # nosec B603 B607
            self.container_id = cid
            logger.info("워커 컨테이너 기동 완료: %s (%s)", self.container_name, cid[:12])

            try:
                raw_mounts = subprocess.check_output(  # nosec B603 B607
                    ["docker", "inspect", "-f", "{{json .Mounts}}", cid],
                    text=True,
                ).strip()
                self.mounted_source = _parse_source_mount(raw_mounts, "/app")
            except Exception as m_err:
                logger.warning("워커 컨테이너 마운트 조회 중 예외: %s", m_err)
                self.mounted_source = None

            return cid
        except subprocess.CalledProcessError as err:
            raise ContainerLifecycleError(f"워커 컨테이너 기동 실패: {err}") from err

    def wait_ready(self, timeout_sec: float = 10.0) -> bool:
        """워커 컨테이너가 정상 기동되어 대기 상태가 될 때까지 확인합니다."""
        t_start = time.perf_counter()
        while time.perf_counter() - t_start < timeout_sec:
            with contextlib.suppress(Exception):
                logs = subprocess.check_output(  # nosec B603 B607
                    ["docker", "logs", "--tail", "20", self.container_name],
                    text=True,
                    stderr=subprocess.STDOUT,
                )
                if "Starting worker for 1 functions" in logs:
                    return True
            time.sleep(0.1)
        raise ContainerLifecycleError(
            f"워커 컨테이너가 {timeout_sec}초 내에 준비 상태에 도달하지 못했습니다."
        )

    def stop_and_remove(self) -> None:
        """컨테이너를 강제 정지 및 제거합니다."""
        if self.container_name:
            try:
                subprocess.run(  # nosec B603 B607
                    ["docker", "rm", "-f", self.container_name],
                    check=False,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                logger.info("워커 컨테이너 정리 완료: %s", self.container_name)
            except Exception as exc:
                logger.warning("워커 컨테이너 정리 중 예외: %s", exc)


async def run_container_worker_benchmark(
    redis_url: str = DEFAULT_REDIS_URL,
    total_jobs: int = 600,
    concurrency: int = 4,
    job_delay_ms: float = 0.0,
    poll_delay_sec: float = 0.01,
    timeout_sec: float = 60.0,
    simulate_error_rate: float = 0.0,
    container_image: str = "refac_bid_box-worker:latest",
    container_network: str | None = None,
    container_redis_url: str = "redis://redis:6379/0",
    strict: bool = True,
    source_mount: Path | str | None = None,
) -> BenchmarkResult:
    """실제 Docker 컨테이너 워커를 대상으로 벤치마크를 수행합니다."""
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

    redis_info = inspect_redis_container()
    network = container_network or redis_info.get("network", "arq-docker-measure_default")
    queue_name = generate_benchmark_queue_name("arq:container-bench")

    config = ContainerBenchmarkConfig(
        queue_name=queue_name,
        total_jobs=total_jobs,
        concurrency=concurrency,
        job_delay_ms=job_delay_ms,
        poll_delay_sec=poll_delay_sec,
        timeout_sec=timeout_sec,
        simulate_error_rate=simulate_error_rate,
        redis_url=redis_url,
        container_image=container_image,
        container_network=network,
        source_mount=str(target_source),
    )

    redis_settings = RedisSettings.from_dsn(redis_url)
    try:
        redis_pool: ArqRedis = await create_pool(redis_settings)
        await redis_pool.ping()
    except Exception as exc:
        raise RedisConnectionError(f"Redis 연결 실패 ({redis_url}): {exc}") from exc

    start_server_info = await fetch_redis_server_info(redis_pool)

    if strict and redis_info.get("container_id") == "unknown":
        await redis_pool.aclose()
        raise BuildProvenanceError("Redis container inspection failed (container_id unknown)")

    worker_mgr = DockerWorkerContainerManager(
        image=container_image,
        network=network,
        queue_name=queue_name,
        concurrency=concurrency,
        poll_delay_sec=poll_delay_sec,
        container_redis_url=container_redis_url,
        source_mount=target_source,
    )

    collected_results: list[dict[str, Any]] = []
    all_job_ids: list[str] = []
    extra_errors: list[str] = []
    t_enq_map: dict[str, float] = {}

    try:
        # 1. 컨테이너 기동 및 준비 대기
        cid = worker_mgr.start()
        if not worker_mgr.container_id:
            worker_mgr.container_id = cid
        worker_cid = worker_mgr.container_id or cid
        worker_image_id = inspect_image_id(container_image)

        if strict:
            if worker_image_id == "unknown":
                raise BuildProvenanceError(f"Worker image ID lookup failed: {container_image}")
            if worker_mgr.mounted_source is None:
                raise BuildProvenanceError(
                    f"Worker container '{cid[:12]}' /app mount lookup failed"
                )
            if Path(worker_mgr.mounted_source).resolve() != target_source:
                raise BuildProvenanceError(
                    f"Worker mount mismatch: container /app is mounted from '{worker_mgr.mounted_source}', expected '{target_source}'"
                )

        start_identity = {
            "worker_container_id": worker_cid,
            "worker_image_id": worker_image_id,
            "redis_container_id": redis_info.get("container_id", "unknown"),
            "redis_image_id": redis_info.get("image_id", "unknown"),
            "redis_server_version": start_server_info.get("server_version", "unknown"),
            "redis_server_mode": start_server_info.get("server_mode", "unknown"),
            "source_mount": str(target_source),
            "source_git_sha": git_sha,
            "source_git_dirty": git_dirty,
        }

        worker_mgr.wait_ready(timeout_sec=10.0)

        # 2. 결과 수집 비동기 리스너 정의
        done_key = f"{queue_name}:done"

        async def result_listener() -> None:
            while len(collected_results) < total_jobs:
                # blpop 으로 1초 단위 대기
                pop_res = await redis_pool.blpop(done_key, timeout=1)
                if pop_res:
                    t_done = time.perf_counter()
                    _, raw_data = pop_res
                    try:
                        data = json.loads(raw_data.decode("utf-8"))
                        jid = data.get("job_id", "")
                        enq_time = t_enq_map.get(jid, t_done)
                        latency_ms = (t_done - enq_time) * 1000.0
                        collected_results.append(
                            {
                                "job_id": jid,
                                "latency_ms": latency_ms,
                                "success": data.get("success", False),
                                "error": data.get("error"),
                            }
                        )
                    except Exception as parse_err:
                        extra_errors.append(f"결과 파싱 오류: {parse_err}")

                    # 큐에 남아있는 추가 완료 건 일괄 drain (최대 100개)
                    batch = await redis_pool.lpop(done_key, count=100)
                    if batch:
                        t_batch = time.perf_counter()
                        for raw_b in batch:
                            try:
                                data = json.loads(
                                    raw_b.decode("utf-8")
                                    if isinstance(raw_b, bytes)
                                    else str(raw_b)
                                )
                                jid = data.get("job_id", "")
                                enq_time = t_enq_map.get(jid, t_batch)
                                latency_ms = (t_batch - enq_time) * 1000.0
                                collected_results.append(
                                    {
                                        "job_id": jid,
                                        "latency_ms": latency_ms,
                                        "success": data.get("success", False),
                                        "error": data.get("error"),
                                    }
                                )
                            except Exception as parse_b_err:
                                extra_errors.append(f"배치 결과 파싱 오류: {parse_b_err}")

        listener_task = asyncio.create_task(result_listener())

        # 3. 작업 적재 시작
        t_start = time.perf_counter()
        enqueue_tasks = []
        for i in range(total_jobs):
            job_id = f"cntr-{queue_name.split(':')[-1]}-{i}"
            all_job_ids.append(job_id)
            should_fail = (simulate_error_rate > 0.0) and ((i / total_jobs) < simulate_error_rate)
            t_enq = time.perf_counter()
            t_enq_map[job_id] = t_enq
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

        # 4. 전체 완료 대기
        try:
            await asyncio.wait_for(listener_task, timeout=timeout_sec)
        except TimeoutError:
            extra_errors.append(
                f"지정된 타임아웃({timeout_sec}초) 내에 모든 작업이 완료되지 못했습니다 (수신: {len(collected_results)}/{total_jobs})."
            )
            listener_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener_task

        t_end = time.perf_counter()
        total_duration = t_end - t_start

        # End identity check
        end_redis_info = inspect_redis_container()
        end_server_info = await fetch_redis_server_info(redis_pool)
        end_git_sha, end_git_dirty = get_git_status(target_source)
        end_worker_image_id = inspect_image_id(container_image)

        end_identity = {
            "worker_container_id": worker_cid,
            "worker_image_id": end_worker_image_id,
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

    finally:
        worker_mgr.stop_and_remove()
        await cleanup_benchmark_resources(redis_pool, queue_name, all_job_ids)
        await redis_pool.aclose()

    # 지표 집계
    latencies: list[float] = []
    successful_jobs = 0
    failed_jobs = 0
    errors = list(extra_errors)

    for r in collected_results:
        lat = float(r.get("latency_ms", 0.0))
        latencies.append(lat)
        if r.get("success", False):
            successful_jobs += 1
        else:
            failed_jobs += 1
            if r.get("error"):
                errors.append(f"Job {r.get('job_id')}: {r.get('error')}")

    missing = max(0, total_jobs - len(collected_results))
    if missing > 0:
        failed_jobs += missing
        errors.append(f"{missing}개 작업이 완료되지 못하고 누락되었습니다.")

    error_count = failed_jobs + len(extra_errors)
    jobs_per_sec = round(successful_jobs / total_duration, 2) if total_duration > 0 else 0.0
    status = "success" if (error_count == 0 and len(collected_results) == total_jobs) else "failed"

    percentiles = calculate_percentiles(latencies)
    latency_data = {
        **percentiles,
        "values_ms": [round(val, 3) for val in latencies],
    }

    summary = {
        "total_duration_sec": round(total_duration, 4),
        "jobs_per_second": jobs_per_sec,
        "total_enqueued": total_jobs,
        "successful_jobs": successful_jobs,
        "failed_jobs": failed_jobs,
        "error_count": error_count,
    }

    worker_image_id = inspect_image_id(container_image)
    load_sample = single_host_load_sample()
    host_mem = get_host_memory()
    arq_ver = get_arq_version()
    redis_py_ver = get_redis_py_version()
    dock_ver = get_docker_version()
    effective_git_sha = git_sha or get_git_sha()
    effective_dirty = git_dirty if git_dirty is not None else get_git_status(target_source)[1]

    provenance = build_provenance_dict(
        host_cpu_count=int(load_sample.get("cpu_count") or os.cpu_count() or 1),
        host_load_avg_1m=load_sample.get("load_1m"),  # type: ignore[arg-type]
        host_memory=host_mem,
        redis_url=redis_url,
        redis_container_id=redis_info.get("container_id", "unknown"),
        redis_container_name=redis_info.get("container_name", "unknown"),
        redis_image=redis_info.get("image", "unknown"),
        redis_image_id=redis_info.get("image_id", "unknown"),
        redis_server_version=start_server_info.get("server_version", "unknown"),
        redis_server_mode=start_server_info.get("server_mode", "unknown"),
        arq_version=arq_ver,
        redis_py_version=redis_py_ver,
        benchmark_worker_mode="docker_container",
        worker_settings_module="scripts._bench_worker_settings.WorkerSettings",
        worker_functions=["benchmark_noop_task"],
        is_synthetic=True,
        worker_max_jobs=concurrency,
        worker_poll_delay=poll_delay_sec,
        worker_job_timeout=60,
        docker_version=dock_ver,
        worker_container_id=worker_cid,
        worker_container_name=worker_mgr.container_name,
        worker_image=container_image,
        worker_image_id=worker_image_id,
        source_mount=str(target_source),
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
        "redis_url": redis_url,
        "redis_container_id": provenance["redis"]["container_id"],
        "redis_container_name": provenance["redis"]["container_name"],
        "redis_image": provenance["redis"]["image"],
        "redis_image_id": provenance["redis"]["image_id"],
        "redis_server_version": provenance["redis"]["server_version"],
        "redis_server_mode": provenance["redis"]["server_mode"],
        # 3. Arq
        "arq_version": arq_ver,
        "redis_py_version": redis_py_ver,
        "worker_type": "docker_container",
        "benchmark_worker_mode": "docker_container",
        "worker_settings_module": "scripts._bench_worker_settings.WorkerSettings",
        "worker_functions": ["benchmark_noop_task"],
        "is_synthetic": True,
        "worker_max_jobs": concurrency,
        "worker_poll_delay": poll_delay_sec,
        "worker_job_timeout": 60,
        # 4. Docker / Container
        "docker_version": dock_ver,
        "worker_container_id": worker_cid or "unknown",
        "worker_container_name": worker_mgr.container_name,
        "worker_image": container_image,
        "worker_image_id": worker_image_id,
        "source_mount": str(target_source),
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
        benchmark_worker_mode="docker_container",
        provenance=provenance,
    )


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="실제 Docker 컨테이너 Arq 워커 대상 처리량 및 지연 벤치마크 하네스"
    )
    parser.add_argument(
        "--jobs",
        "-n",
        type=int,
        default=600,
        help="적재할 총 작업 수 (기본값: 600)",
    )
    parser.add_argument(
        "--concurrency",
        "-c",
        type=int,
        default=4,
        help="워커 최대 동시 처리 수 max_jobs (기본값: 4, 운영 WorkerSettings 기준)",
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
        help=f"호스트 Redis 접속 URL (기본값: {DEFAULT_REDIS_URL})",
    )
    parser.add_argument(
        "--container-redis-url",
        default="redis://redis:6379/0",
        help="컨테이너 내부 Redis 접속 URL (기본값: redis://redis:6379/0)",
    )
    parser.add_argument(
        "--image",
        default="refac_bid_box-worker:latest",
        help="워커 컨테이너 이미지 (기본값: refac_bid_box-worker:latest)",
    )
    parser.add_argument(
        "--network",
        default=None,
        help="도커 네트워크 (미지정 시 Redis 컨테이너 네트워크 자동 감지)",
    )
    parser.add_argument(
        "--source-mount",
        default=None,
        help=f"호스트 소스 마운트 경로 (기본값: {PROJECT_ROOT})",
    )
    parser.add_argument(
        "--allow-unknown-provenance",
        action="store_true",
        default=False,
        help="Docker/Git provenance 조회 실패 또는 dirty 상태 시에도 측정을 강제 진행합니다 (기본: 거부)",
    )
    parser.add_argument(
        "--output",
        "-o",
        type=Path,
        default=None,
        help="결과 JSON 저장 경로",
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
    return parser.parse_args(argv)


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

    strict = not args.allow_unknown_provenance
    results: list[BenchmarkResult] = []
    saved_paths: list[Path] = []

    for run_idx in range(1, args.repetitions + 1):
        if args.repetitions > 1 and not args.quiet:
            print(f"\n>>> [회차 {run_idx}/{args.repetitions}] 실측 시작...")

        try:
            result = asyncio.run(
                run_container_worker_benchmark(
                    redis_url=args.redis_url,
                    total_jobs=args.jobs,
                    concurrency=args.concurrency,
                    job_delay_ms=args.job_delay_ms,
                    poll_delay_sec=args.poll_delay,
                    timeout_sec=args.timeout,
                    simulate_error_rate=args.simulate_error_rate,
                    container_image=args.image,
                    container_network=args.network,
                    container_redis_url=args.container_redis_url,
                    strict=strict,
                    source_mount=args.source_mount,
                )
            )
            results.append(result)
        except RedisConnectionError as r_err:
            print(f"Redis 연결 오류: {r_err}", file=sys.stderr)
            return 2
        except ContainerLifecycleError as c_err:
            print(f"컨테이너 관리 오류: {c_err}", file=sys.stderr)
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
        if args.output and args.repetitions > 1:
            stem = args.output.stem
            suffix = args.output.suffix
            r_path = args.output.parent / f"{stem}_r{run_idx}{suffix}"
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

    if args.output and args.repetitions > 1:
        for r_idx, r_path in enumerate(saved_paths, start=1):
            if not r_path.exists() or r_path.stat().st_size == 0:
                print(f"오류: 회차 {r_idx} 결과 파일 누락 또는 0바이트: {r_path}", file=sys.stderr)
                return 1

    # 대표 결과 선정: P95 기준 최악 대표값
    worst_result = max(results, key=lambda r: float(r.latency_ms.get("p95_ms", 0.0)))

    if args.output:
        try:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(
                dump_strict_json(worst_result.as_dict()),
                encoding="utf-8",
            )
            if not args.quiet:
                print(f"\n최종 대표 결과 저장 완료: {args.output}")
        except Exception as out_err:
            print(f"대표 결과 저장 실패: {out_err}", file=sys.stderr)
            return 1

    all_success = all(
        r.status == "success" and r.summary.get("error_count", 0) == 0 for r in results
    )
    return 0 if all_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
