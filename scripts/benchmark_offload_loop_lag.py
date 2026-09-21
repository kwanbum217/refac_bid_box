"""
scripts/benchmark_offload_loop_lag.py

이벤트 루프 오프로드(D1, D2, D7, D9)의 효과를 실측하는 loop lag 하니스.

배경
    docs/analysis/write_path_g3_scan_20260920.md 3장이 D1·D2·D7·D9 의 측정 방법으로
    loop lag 를 규정했으나 저장소에 측정 도구가 없었습니다. 본 하니스가 그 도구입니다.

측정 구조
    - A 집단: 대상 동기 함수를 코루틴 안에서 그대로 호출합니다. 오프로드 전 동작입니다.
    - B 집단: ``await asyncio.to_thread(대상 함수)`` 로 호출합니다. 현재 동작입니다.
    - 두 집단을 같은 프로세스에서 한 반복마다 ABBA 순서로 교차 실행합니다.
    - 별도 탐침 코루틴이 interval(기본 1ms) 동안 asyncio.sleep 한 뒤 loop.time() 으로
      실제 경과를 재어 초과분을 지연 표본(ms)으로 쌓습니다. 호출 한 번마다 탐침을 먼저
      띄우고 대상 호출이 끝나면 멈춥니다.

부수효과 격리
    - D2 는 하니스 전용 claim key 로만 잡고 해제하며, 측정 전후로 잔여 키를 정리합니다.
    - D9 는 하니스 전용 heartbeat key 와 하니스 전용 schedule_name 으로만 기록하고,
      종료 시 그 항목을 삭제합니다.
    - D1 은 파생 요약 테이블과 기관명 캐시를 갱신하는 운영과 같은 연산입니다. 원본
      테이블(bid_announcements, bid_results)에는 어떤 쓰기도 하지 않습니다.

실행
    uv run python scripts/benchmark_offload_loop_lag.py --list
    uv run python scripts/benchmark_offload_loop_lag.py --targets D9 --rounds 3

주의
    본 하니스는 Docker/DB/Redis 가 떠 있는 환경에서 코디네이터가 직접 실행합니다.
    단위 테스트는 대상 함수를 time.sleep 대역으로 바꿔 외부 서비스 없이 돕니다.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import platform
import statistics
import subprocess  # nosec B404
import sys
import threading
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.benchmark_provenance import get_git_status  # noqa: E402

SCHEMA = "ORCA_OFFLOAD_LOOP_LAG_V1"

# A 집단은 동기 직접 호출(오프로드 전), B 집단은 asyncio.to_thread(현재)입니다.
ARM_SYNC = "A"
ARM_OFFLOAD = "B"

HARNESS_KEY_PREFIX = "bidbox:benchmark:offload_loop_lag:"
HARNESS_SCHEDULE_CLAIM_KEY = HARNESS_KEY_PREFIX + "schedule_claim"
HARNESS_WORKER_HEARTBEAT_KEY = HARNESS_KEY_PREFIX + "worker_heartbeat"
HARNESS_SCHEDULE_NAME = "benchmark_offload_loop_lag"
HARNESS_CLAIM_OWNER = "benchmark_offload_loop_lag"
HARNESS_CLAIM_TTL_SECONDS = 60

# D3(드리프트 PSI)은 이 환경에 data/model_files/*/baseline 이 없어 운영 경로 자체가
# 건너뛰어지므로 대상에서 제외합니다.
D3_EXCLUSION_REASON = (
    "이 환경에는 data/model_files/*/baseline 디렉터리가 없어 운영에서 드리프트 계산 "
    "경로 자체가 건너뛰어집니다."
)
EXCLUDED_TARGETS: dict[str, str] = {"D3": D3_EXCLUSION_REASON}

DEFAULT_ROUNDS = 3
DEFAULT_WARMUP = 1
DEFAULT_INTERVAL_MS = 1.0
LOAD_SAMPLE_INTERVAL_SECONDS = 5.0
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "data" / "benchmarks" / "offload_loop_lag"


@dataclass
class TargetSpec:
    """측정 대상 하나. build() 가 호출할 동기 함수를 만들고 cleanup() 이 부수효과를 지웁니다."""

    target_id: str
    defect: str
    description: str
    default_repeats: int
    writes: bool
    side_effect_note: str
    build: Callable[[], Callable[[], Any]]
    cleanup: Callable[[], None] | None = None


@dataclass
class CallRecord:
    """대상 호출 한 번의 기록."""

    round: int
    repeat: int
    order: int
    arm: str
    warmup: bool
    wall_ms: float
    sample_count: int
    lag_max_ms: float
    lag_p50_ms: float
    lag_p95_ms: float

    def to_dict(self) -> dict[str, Any]:
        return {
            "round": self.round,
            "repeat": self.repeat,
            "order": self.order,
            "arm": self.arm,
            "warmup": self.warmup,
            "wall_ms": round(self.wall_ms, 4),
            "probe_sample_count": self.sample_count,
            "probe_lag_max_ms": round(self.lag_max_ms, 4),
            "probe_lag_p50_ms": round(self.lag_p50_ms, 4),
            "probe_lag_p95_ms": round(self.lag_p95_ms, 4),
        }


def percentile(values: Sequence[float], pct: float) -> float | None:
    """선형 보간 백분위수. 표본이 없으면 None."""
    if not values:
        return None
    ordered = sorted(float(v) for v in values)
    if len(ordered) == 1:
        return ordered[0]
    rank = (pct / 100.0) * (len(ordered) - 1)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return ordered[low]
    return ordered[low] + (ordered[high] - ordered[low]) * (rank - low)


def _median_or_none(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


class LoopLagProbe:
    """이벤트 루프 지연 탐침 코루틴.

    interval 동안 asyncio.sleep 한 뒤 loop.time() 으로 실제 경과를 재어 초과분을
    지연 표본(ms)으로 쌓습니다. request_stop() 은 진행 중인 sleep 이 끝난 뒤 한 표본을
    더 기록하고 종료시키므로, 동기 호출이 루프를 멈춘 동안 발생한 큰 지연이 취소로
    유실되지 않습니다.
    """

    def __init__(self, interval_ms: float) -> None:
        self.interval_seconds = interval_ms / 1000.0
        self.samples_ms: list[float] = []
        self._stop = False

    def request_stop(self) -> None:
        self._stop = True

    async def run(self) -> None:
        loop = asyncio.get_running_loop()
        interval = self.interval_seconds
        while not self._stop:
            started = loop.time()
            await asyncio.sleep(interval)
            elapsed = loop.time() - started
            lag_ms = (elapsed - interval) * 1000.0
            self.samples_ms.append(lag_ms if lag_ms > 0.0 else 0.0)


async def _invoke(arm: str, target_fn: Callable[[], Any]) -> Any:
    """집단별 호출 방식. A 는 동기 직접 호출, B 는 asyncio.to_thread 입니다."""
    if arm == ARM_SYNC:
        return target_fn()
    return await asyncio.to_thread(target_fn)


async def measure_single_call(
    target_fn: Callable[[], Any],
    *,
    arm: str,
    interval_ms: float,
    round_index: int,
    repeat_index: int,
    order_index: int,
    warmup: bool,
) -> tuple[CallRecord, list[float]]:
    """탐침을 먼저 띄우고 대상 호출 한 번을 계측한 뒤 탐침을 멈춥니다."""
    probe = LoopLagProbe(interval_ms)
    probe_task = asyncio.create_task(probe.run())
    # 탐침이 첫 sleep 에 들어간 뒤에 대상 호출을 시작합니다.
    await asyncio.sleep(0)

    started = time.perf_counter()
    try:
        await _invoke(arm, target_fn)
    finally:
        wall_ms = (time.perf_counter() - started) * 1000.0
        probe.request_stop()
        await probe_task

    samples = list(probe.samples_ms)
    record = CallRecord(
        round=round_index,
        repeat=repeat_index,
        order=order_index,
        arm=arm,
        warmup=warmup,
        wall_ms=wall_ms,
        sample_count=len(samples),
        lag_max_ms=max(samples) if samples else 0.0,
        lag_p50_ms=percentile(samples, 50.0) or 0.0,
        lag_p95_ms=percentile(samples, 95.0) or 0.0,
    )
    return record, samples


def _run_cleanup(cleanup: Callable[[], None] | None) -> None:
    if cleanup is None:
        return
    try:
        cleanup()
    except Exception as exc:  # 정리 실패가 측정 결과 기록을 막지 않습니다.
        print(f"[경고] 부수효과 정리 실패: {exc}", file=sys.stderr)


def summarize_arm(
    arm_records: Sequence[CallRecord],
    pooled_samples: dict[tuple[int, str], list[float]],
    *,
    rounds: int,
    arm: str,
) -> dict[str, Any]:
    """집단별 집계. warmup 제외 표본만 넘어옵니다."""
    wall_values = [r.wall_ms for r in arm_records]
    per_round: list[dict[str, Any]] = []
    for round_index in range(1, rounds + 1):
        round_calls = [r for r in arm_records if r.round == round_index]
        samples = pooled_samples.get((round_index, arm), [])
        per_round.append(
            {
                "round": round_index,
                "call_count": len(round_calls),
                "wall_ms_median": _median_or_none([r.wall_ms for r in round_calls]),
                "probe_sample_count": len(samples),
                "probe_p95_ms": percentile(samples, 95.0),
                "probe_max_ms": max(samples) if samples else None,
            }
        )
    p95_by_round = [b["probe_p95_ms"] for b in per_round if b["probe_p95_ms"] is not None]
    max_by_round = [b["probe_max_ms"] for b in per_round if b["probe_max_ms"] is not None]
    return {
        "call_count": len(arm_records),
        "wall_ms_median": _median_or_none(wall_values),
        "call_lag_max_ms_median": _median_or_none([r.lag_max_ms for r in arm_records]),
        "probe_p95_ms_by_round": p95_by_round,
        "probe_max_ms_by_round": max_by_round,
        "probe_p95_worst_round_ms": max(p95_by_round) if p95_by_round else None,
        "probe_max_worst_round_ms": max(max_by_round) if max_by_round else None,
        "rounds": per_round,
    }


def summarize_target(
    records: Sequence[CallRecord],
    pooled_samples: dict[tuple[int, str], list[float]],
    *,
    rounds: int,
) -> dict[str, Any]:
    sync_records = [r for r in records if r.arm == ARM_SYNC and not r.warmup]
    offload_records = [r for r in records if r.arm == ARM_OFFLOAD and not r.warmup]
    summary = {
        ARM_SYNC: summarize_arm(sync_records, pooled_samples, rounds=rounds, arm=ARM_SYNC),
        ARM_OFFLOAD: summarize_arm(offload_records, pooled_samples, rounds=rounds, arm=ARM_OFFLOAD),
    }
    a_max = summary[ARM_SYNC]["probe_max_worst_round_ms"]
    b_max = summary[ARM_OFFLOAD]["probe_max_worst_round_ms"]
    summary["lag_max_ratio_a_over_b"] = (
        a_max / b_max if a_max is not None and b_max not in (None, 0.0) else None
    )
    return summary


async def measure_target(
    spec: TargetSpec,
    *,
    rounds: int,
    repeats: int,
    warmup: int,
    interval_ms: float,
) -> dict[str, Any]:
    """대상 하나를 A/B 집단으로 ABBA 교차 실행하며 계측합니다."""
    records: list[CallRecord] = []
    pooled_samples: dict[tuple[int, str], list[float]] = {}

    # 이전 실행이 남긴 하니스 전용 키를 먼저 지웁니다.
    _run_cleanup(spec.cleanup)
    try:
        target_fn = spec.build()
        for round_index in range(1, rounds + 1):
            for repeat_index in range(repeats):
                # 한 반복마다 ABBA 로 교차합니다.
                arms = (ARM_SYNC, ARM_OFFLOAD) if repeat_index % 2 == 0 else (ARM_OFFLOAD, ARM_SYNC)
                for order_index, arm in enumerate(arms):
                    is_warmup = repeat_index < warmup
                    record, samples = await measure_single_call(
                        target_fn,
                        arm=arm,
                        interval_ms=interval_ms,
                        round_index=round_index,
                        repeat_index=repeat_index,
                        order_index=order_index,
                        warmup=is_warmup,
                    )
                    records.append(record)
                    if not is_warmup:
                        pooled_samples.setdefault((round_index, arm), []).extend(samples)
    finally:
        _run_cleanup(spec.cleanup)

    return {
        "target_id": spec.target_id,
        "defect": spec.defect,
        "description": spec.description,
        "writes": spec.writes,
        "side_effect_note": spec.side_effect_note,
        "repeats": repeats,
        "warmup": warmup,
        "records": [r.to_dict() for r in records],
        "summary": summarize_target(records, pooled_samples, rounds=rounds),
    }


# --------------------------------------------------------------------------- #
# 측정 환경 기록 (docs/ops/latency_gate_protocol.md 5.3, 5.4)
# --------------------------------------------------------------------------- #


def _read_cpu_count() -> int:
    try:
        out = subprocess.check_output(  # nosec B603 B607
            ["sysctl", "-n", "hw.ncpu"], text=True
        ).strip()
        return int(out)
    except (OSError, subprocess.CalledProcessError, ValueError):
        return os.cpu_count() or 1


def _read_system_load_1m() -> float | None:
    """sysctl vm.loadavg 의 1분 값을 읽고 실패하면 os.getloadavg 로 대체합니다."""
    try:
        out = subprocess.check_output(  # nosec B603 B607
            ["sysctl", "-n", "vm.loadavg"], text=True
        ).strip()
        parts = out.strip("{} \n").split()
        if parts:
            return float(parts[0])
    except (OSError, subprocess.CalledProcessError, ValueError):
        pass
    try:
        return float(os.getloadavg()[0])
    except (OSError, AttributeError):
        return None


class LoadAverageSampler:
    """5초 간격으로 정규화 1분 load average(%)를 표본하는 백그라운드 로거."""

    def __init__(
        self,
        interval_seconds: float = LOAD_SAMPLE_INTERVAL_SECONDS,
        reader: Callable[[], float | None] | None = None,
        cpu_count: int | None = None,
    ) -> None:
        self.interval_seconds = interval_seconds
        self.samples: list[dict[str, Any]] = []
        self._reader = reader or _read_system_load_1m
        self._cpu_count = cpu_count
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def cpu_count(self) -> int:
        if self._cpu_count is None:
            self._cpu_count = _read_cpu_count()
        return self._cpu_count

    def _sample(self) -> None:
        load_1m = self._reader()
        cpu_count = self.cpu_count or 1
        pct = (100.0 * load_1m / cpu_count) if load_1m is not None else None
        self.samples.append(
            {
                "load_1m": load_1m,
                "cpu_count": cpu_count,
                "normalized_load_1m_percent": round(pct, 4) if pct is not None else None,
            }
        )

    def _run(self) -> None:
        self._sample()
        while not self._stop_event.wait(self.interval_seconds):
            self._sample()

    def start(self) -> LoadAverageSampler:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        return self

    def stop(self) -> dict[str, Any]:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)
        if not self.samples:
            self._sample()
        return self.summary()

    def summary(self) -> dict[str, Any]:
        pcts = [
            float(s["normalized_load_1m_percent"])
            for s in self.samples
            if s["normalized_load_1m_percent"] is not None
        ]
        return {
            "metric": "normalized_load_1m_percent",
            "interval_seconds": self.interval_seconds,
            "cpu_count": self.cpu_count,
            "protocol": {"median_limit_percent": 30.0, "max_limit_percent": 50.0},
            "min": min(pcts) if pcts else None,
            "median": statistics.median(pcts) if pcts else None,
            "max": max(pcts) if pcts else None,
            "samples": self.samples,
        }


def _default_sql_executor(sql: str) -> list[tuple[Any, ...]]:
    from sqlalchemy import text

    from src.app.core.db import engine

    with engine.connect() as conn:
        return [tuple(row) for row in conn.execute(text(sql))]


def collect_db_environment(
    sql_executor: Callable[[str], list[tuple[Any, ...]]] | None = None,
) -> dict[str, Any]:
    """DB 버퍼풀 크기와 가동 시간을 기록합니다. 실패는 사유로 남기고 중단하지 않습니다."""
    run = sql_executor or _default_sql_executor
    env: dict[str, Any] = {
        "buffer_pool_size_bytes": None,
        "buffer_pool_size_gb": None,
        "uptime_seconds": None,
        "status": "ok",
        "error": None,
    }
    try:
        rows = run("SELECT @@innodb_buffer_pool_size")
        if rows:
            size_bytes = int(rows[0][0])
            env["buffer_pool_size_bytes"] = size_bytes
            env["buffer_pool_size_gb"] = round(size_bytes / (1024**3), 3)
        rows = run("SHOW GLOBAL STATUS LIKE 'Uptime'")
        if rows:
            env["uptime_seconds"] = int(rows[0][1])
    except Exception as exc:  # DB 미가동 시 기록만 남기고 계속합니다.
        env["status"] = "unavailable"
        env["error"] = str(exc)
    return env


def collect_environment(
    load_summary: dict[str, Any],
    db_environment: dict[str, Any],
) -> dict[str, Any]:
    git_sha, git_dirty = get_git_status()
    return {
        "git": {"sha": git_sha, "dirty": git_dirty},
        "host_load": load_summary,
        "db": db_environment,
        "python_version": platform.python_version(),
        "platform": platform.platform(),
    }


async def run_benchmark(
    *,
    specs: Sequence[TargetSpec],
    rounds: int = DEFAULT_ROUNDS,
    repeats_override: int | None = None,
    warmup: int = DEFAULT_WARMUP,
    interval_ms: float = DEFAULT_INTERVAL_MS,
    sampler: LoadAverageSampler | None = None,
    sql_executor: Callable[[str], list[tuple[Any, ...]]] | None = None,
) -> dict[str, Any]:
    """선택된 대상을 모두 계측하고 결과 JSON 본문을 만듭니다."""
    load_sampler = sampler or LoadAverageSampler()
    load_sampler.start()
    results: dict[str, Any] = {}
    try:
        for spec in specs:
            repeats = repeats_override if repeats_override is not None else spec.default_repeats
            results[spec.target_id] = await measure_target(
                spec,
                rounds=rounds,
                repeats=repeats,
                warmup=warmup,
                interval_ms=interval_ms,
            )
    finally:
        load_summary = load_sampler.stop()

    return {
        "schema": SCHEMA,
        "generated_at": datetime.now(UTC).isoformat(),
        "config": {
            "rounds": rounds,
            "repeats_override": repeats_override,
            "warmup": warmup,
            "interval_ms": interval_ms,
            "targets": [s.target_id for s in specs],
        },
        "environment": collect_environment(
            load_summary,
            collect_db_environment(sql_executor),
        ),
        "excluded_targets": dict(EXCLUDED_TARGETS),
        "results": results,
    }


# --------------------------------------------------------------------------- #
# 대상 정의
# --------------------------------------------------------------------------- #


def build_d1_announcement_target() -> TargetSpec:
    def build() -> Callable[[], Any]:
        from src.app.services.dashboard import DATASET_ANNOUNCEMENT
        from src.tasks.summary_tasks import _rebuild_bid_dataset_summary

        return lambda: _rebuild_bid_dataset_summary(DATASET_ANNOUNCEMENT)

    return TargetSpec(
        target_id="D1.announcement",
        defect="D1",
        description="공고 데이터셋 요약 재집계 (_rebuild_bid_dataset_summary)",
        default_repeats=3,
        writes=True,
        side_effect_note=(
            "파생 요약 테이블을 갱신합니다. bid_announcements/bid_results 에는 쓰지 않습니다."
        ),
        build=build,
    )


def build_d1_result_target() -> TargetSpec:
    def build() -> Callable[[], Any]:
        from src.app.services.dashboard import DATASET_RESULT
        from src.tasks.summary_tasks import _rebuild_bid_dataset_summary

        return lambda: _rebuild_bid_dataset_summary(DATASET_RESULT)

    return TargetSpec(
        target_id="D1.result",
        defect="D1",
        description="낙찰 데이터셋 요약 재집계 (_rebuild_bid_dataset_summary)",
        default_repeats=3,
        writes=True,
        side_effect_note=(
            "파생 요약 테이블을 갱신합니다. bid_announcements/bid_results 에는 쓰지 않습니다."
        ),
        build=build,
    )


def build_d1_catalogs_target() -> TargetSpec:
    def build() -> Callable[[], Any]:
        from src.tasks.summary_tasks import _refresh_institution_catalogs

        return _refresh_institution_catalogs

    return TargetSpec(
        target_id="D1.catalogs",
        defect="D1",
        description="기관명 목록 캐시 갱신 (_refresh_institution_catalogs)",
        default_repeats=3,
        writes=True,
        side_effect_note="기관명 캐시를 갱신합니다. 원본 테이블에는 쓰지 않습니다.",
        build=build,
    )


def build_d2_claim_cycle_target(
    *,
    acquire: Callable[..., Any] | None = None,
    release: Callable[..., Any] | None = None,
    key: str = HARNESS_SCHEDULE_CLAIM_KEY,
    owner: str = HARNESS_CLAIM_OWNER,
    ttl_seconds: int = HARNESS_CLAIM_TTL_SECONDS,
    redis_deleter: Callable[..., Any] | None = None,
) -> TargetSpec:
    """스케줄 claim 획득·해제 한 주기. 운영 키가 아닌 하니스 전용 key 를 씁니다."""

    def build() -> Callable[[], Any]:
        acquire_fn = acquire
        release_fn = release
        if acquire_fn is None or release_fn is None:
            from src.tasks.scheduled_tasks import (
                acquire_schedule_claim,
                release_schedule_claim,
            )

            acquire_fn = acquire_fn or acquire_schedule_claim
            release_fn = release_fn or release_schedule_claim

        def cycle() -> Any:
            claim = acquire_fn(owner, key=key, ttl_seconds=ttl_seconds)
            if claim.acquired:
                release_fn(claim.key, token=claim.token)
            return claim.status.value

        return cycle

    def cleanup() -> None:
        (redis_deleter or _delete_redis_keys)(key)

    return TargetSpec(
        target_id="D2.claim_cycle",
        defect="D2",
        description="스케줄 claim 획득·해제 한 주기 (acquire_schedule_claim/release)",
        default_repeats=20,
        writes=True,
        side_effect_note=f"하니스 전용 key({key})만 쓰고 측정 전후로 정리합니다.",
        build=build,
        cleanup=cleanup,
    )


def build_d2_catchup_check_target(
    *,
    checker: Callable[[], Any] | None = None,
) -> TargetSpec:
    def build() -> Callable[[], Any]:
        if checker is not None:
            return checker
        from src.tasks.scheduled_tasks import check_schedule_catchup_needed

        return check_schedule_catchup_needed

    return TargetSpec(
        target_id="D2.catchup_check",
        defect="D2",
        description="기동 따라잡기 필요 여부 판정 (check_schedule_catchup_needed)",
        default_repeats=20,
        writes=False,
        side_effect_note="읽기 전용입니다.",
        build=build,
    )


def build_d7_count_today_target(
    *,
    session_factory: Callable[[], Any] | None = None,
    counter: Callable[[Any], Any] | None = None,
) -> TargetSpec:
    def build() -> Callable[[], Any]:
        session_factory_fn = session_factory
        counter_fn = counter
        if session_factory_fn is None:
            from src.app.core.db import SessionLocal

            session_factory_fn = SessionLocal
        if counter_fn is None:
            from src.tasks.automation_steps import _count_today_announcements_sync

            counter_fn = _count_today_announcements_sync

        def count_once() -> Any:
            db = session_factory_fn()
            try:
                return counter_fn(db)
            finally:
                db.close()

        return count_once

    return TargetSpec(
        target_id="D7.count_today",
        defect="D7",
        description="오늘 적재 공고 수 동기 COUNT (_count_today_announcements_sync)",
        default_repeats=20,
        writes=False,
        side_effect_note="하니스가 연 SELECT 전용 세션을 호출 뒤 닫습니다.",
        build=build,
    )


def build_d9_heartbeat_target(
    *,
    heartbeat: Callable[..., Any] | None = None,
    key: str = HARNESS_WORKER_HEARTBEAT_KEY,
    redis_deleter: Callable[..., Any] | None = None,
) -> TargetSpec:
    def build() -> Callable[[], Any]:
        heartbeat_fn = heartbeat
        if heartbeat_fn is None:
            from src.tasks.worker import record_worker_heartbeat

            heartbeat_fn = record_worker_heartbeat

        return lambda: heartbeat_fn(key)

    def cleanup() -> None:
        (redis_deleter or _delete_redis_keys)(key)

    return TargetSpec(
        target_id="D9.heartbeat",
        defect="D9",
        description="워커 heartbeat 기록 (record_worker_heartbeat)",
        default_repeats=30,
        writes=True,
        side_effect_note=f"하니스 전용 key({key})만 쓰고 측정 전후로 정리합니다.",
        build=build,
        cleanup=cleanup,
    )


def build_d9_schedule_result_target(
    *,
    recorder: Callable[..., Any] | None = None,
    schedule_name: str = HARNESS_SCHEDULE_NAME,
    entry_remover: Callable[..., Any] | None = None,
) -> TargetSpec:
    def build() -> Callable[[], Any]:
        recorder_fn = recorder
        if recorder_fn is None:
            from src.tasks.worker import record_schedule_result

            recorder_fn = record_schedule_result
        outcome = {"status": "success"}

        return lambda: recorder_fn(schedule_name, outcome, True)

    def cleanup() -> None:
        (entry_remover or _remove_schedule_status_entry)(schedule_name)

    return TargetSpec(
        target_id="D9.schedule_result",
        defect="D9",
        description="스케줄 결과 기록 (record_schedule_result)",
        default_repeats=30,
        writes=True,
        side_effect_note=(
            f"하니스 전용 schedule_name({schedule_name}) 항목만 쓰고 측정 전후로 삭제합니다."
        ),
        build=build,
        cleanup=cleanup,
    )


def build_target_specs() -> list[TargetSpec]:
    return [
        build_d1_announcement_target(),
        build_d1_result_target(),
        build_d1_catalogs_target(),
        build_d2_claim_cycle_target(),
        build_d2_catchup_check_target(),
        build_d7_count_today_target(),
        build_d9_heartbeat_target(),
        build_d9_schedule_result_target(),
    ]


# --------------------------------------------------------------------------- #
# 부수효과 정리
# --------------------------------------------------------------------------- #


def _delete_redis_keys(*keys: str) -> dict[str, int]:
    """하니스 전용 Redis 키를 삭제합니다."""
    from src.app.core.cache import RedisConnection

    connection = RedisConnection(label="benchmark_offload_loop_lag")
    client = connection.client()
    if client is None:
        return dict.fromkeys(keys, 0)
    deleted: dict[str, int] = {}
    for key in keys:
        try:
            deleted[key] = int(client.delete(key))
        except Exception as exc:
            connection.invalidate(exc)
            deleted[key] = 0
    return deleted


def _remove_schedule_status_entry(
    schedule_name: str,
    *,
    cache_layer: Any | None = None,
) -> bool:
    """공유 스케줄 상태 dict 에서 하니스 전용 schedule_name 항목만 지웁니다.

    운영 스케줄 항목은 남깁니다. 항목이 비면 키만 삭제합니다.
    """
    from src.tasks.worker import (
        OBSERVATION_TTL_SECONDS,
        SCHEDULE_STATUS_KEY,
        _worker_cache,
    )

    layer = cache_layer if cache_layer is not None else _worker_cache
    current = layer.get(SCHEDULE_STATUS_KEY)
    if not isinstance(current, dict) or schedule_name not in current:
        return False
    remaining = {k: v for k, v in current.items() if k != schedule_name}
    if remaining:
        layer.set(SCHEDULE_STATUS_KEY, remaining, OBSERVATION_TTL_SECONDS)
    else:
        layer.delete(SCHEDULE_STATUS_KEY)
    return True


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #


def select_specs(specs: Sequence[TargetSpec], tokens: Sequence[str] | None) -> list[TargetSpec]:
    """쉼표 구분 토큰으로 대상 선택. 전체 id 또는 결함 그룹(D1 등)과 일치합니다."""
    if not tokens:
        return list(specs)
    wanted = [t.strip().lower() for t in tokens if t.strip()]
    known = {s.target_id.lower() for s in specs} | {s.defect.lower() for s in specs}
    unknown = sorted({t for t in wanted if t not in known})
    if unknown:
        raise ValueError(f"알 수 없는 대상: {', '.join(unknown)}")
    return [
        spec for spec in specs if spec.target_id.lower() in wanted or spec.defect.lower() in wanted
    ]


def format_target_list(specs: Sequence[TargetSpec]) -> str:
    lines = ["대상 목록:"]
    for spec in specs:
        marker = "writes" if spec.writes else "read-only"
        lines.append(
            f"  {spec.target_id:<20} [{spec.defect}, {marker}, "
            f"기본 반복 {spec.default_repeats}] {spec.description}"
        )
        if spec.writes:
            lines.append(f"      부수효과: {spec.side_effect_note}")
    lines.append("제외 대상:")
    for defect, reason in EXCLUDED_TARGETS.items():
        lines.append(f"  {defect}: {reason}")
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="이벤트 루프 오프로드(D1, D2, D7, D9) loop lag 실측 하니스",
    )
    parser.add_argument("--list", action="store_true", help="대상 목록과 제외 대상을 출력합니다.")
    parser.add_argument("--targets", default=None, help="쉼표 구분 대상 선택 (예: D1,D9.heartbeat)")
    parser.add_argument("--rounds", type=int, default=DEFAULT_ROUNDS, help="회차 수 (기본 3)")
    parser.add_argument("--repeats", type=int, default=None, help="대상별 집단당 반복 수 덮어쓰기")
    parser.add_argument(
        "--warmup", type=int, default=DEFAULT_WARMUP, help="집계에서 뺄 선행 반복 수"
    )
    parser.add_argument(
        "--interval-ms", type=float, default=DEFAULT_INTERVAL_MS, help="탐침 간격 (기본 1ms)"
    )
    parser.add_argument("--output", type=Path, default=None, help="원시 결과 JSON 경로")
    return parser


def default_output_path() -> Path:
    timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    return DEFAULT_OUTPUT_DIR / f"offload_loop_lag_{timestamp}.json"


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    specs = build_target_specs()

    if args.list:
        print(format_target_list(specs))
        return 0

    if args.rounds < 1:
        print("[오류] --rounds 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2
    if args.interval_ms <= 0:
        print("[오류] --interval-ms 는 0 보다 커야 합니다.", file=sys.stderr)
        return 2
    if args.repeats is not None and args.repeats < 1:
        print("[오류] --repeats 는 1 이상이어야 합니다.", file=sys.stderr)
        return 2

    try:
        selected = select_specs(specs, args.targets.split(",") if args.targets else None)
    except ValueError as exc:
        print(f"[오류] {exc}", file=sys.stderr)
        return 2
    if not selected:
        print("[오류] 선택된 대상이 없습니다.", file=sys.stderr)
        return 2

    effective_repeats = {
        spec.target_id: (args.repeats if args.repeats is not None else spec.default_repeats)
        for spec in selected
    }
    smallest = min(effective_repeats.values())
    if args.warmup < 0 or args.warmup >= smallest:
        print(
            f"[오류] --warmup({args.warmup}) 은 반복 수({smallest}) 보다 작아야 합니다.",
            file=sys.stderr,
        )
        return 2

    result = asyncio.run(
        run_benchmark(
            specs=selected,
            rounds=args.rounds,
            repeats_override=args.repeats,
            warmup=args.warmup,
            interval_ms=args.interval_ms,
        )
    )

    output_path = args.output or default_output_path()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    print(f"결과 저장: {output_path}")
    for spec in selected:
        summary = result["results"][spec.target_id]["summary"]
        print(
            f"  {spec.target_id}: A 최악 회차 최대 {summary[ARM_SYNC]['probe_max_worst_round_ms']}ms, "
            f"B 최악 회차 최대 {summary[ARM_OFFLOAD]['probe_max_worst_round_ms']}ms"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
