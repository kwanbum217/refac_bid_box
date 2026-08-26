"""
scripts/benchmark_arq_business_e2e.py

실제 등록 업무 task 종단(E2E) Arq 벤치마크 하네스.

기존 benchmark_arq_container.py / benchmark_arq_throughput.py 가 합성
benchmark_noop_task 만 돌려 production business-task 경로가 미측정으로
남아 있던 점을 보완한다. 본 스크립트는 다음 두 가지를 강제한다.

  1. 측정 대상 task 를 preflight_check_task, validate_model_task 두 개로
     제한한다. 두 task 는 모두 데이터를 변경하지 않는다. preflight_check_task
     는 run_mode preflight_only 이고 RUN_MODE_STEP_ORDER 의 스텝이 빈
     튜플이라 아무 스텝도 실행하지 않으며, validate_model_task 는
     run_mode predict_only 로 _step_predict 만 수행하고 쓰기 경로가
     없다. 그 밖의 task 이름(collect_bids_task, update_kb_task,
     manual_retrain_task, refresh_data_task, manual_full_task,
     run_retrain_pipeline_task, development_data_refresh_task)은 데이터를
     바꾸므로 인자로 들어와도 거부한다.
  2. 운영 큐 arq:queue 를 읽거나 쓰지 않는다. 실행마다 격리 큐
     arq:benchmark:business-e2e:<uuid> 를 새로 만들고, 종료 시 그 큐와
     부속 키를 정리한다.

enqueue 시 execution_id 를 넘기지 않아 run_automation_pipeline 안의
PipelineExecution 조회 분기가 None 으로 떨어지므로 상태 갱신 커밋이
발생하지 않는다.

본 스크립트는 측정 하네스(스크립트 + 단위 테스트)까지가 범위이며 실제
Docker 기동과 실측 실행은 코디네이터 측 별도 과제다.

실행(코디네이터 측 실측 시):
    uv run python scripts/benchmark_arq_business_e2e.py \
        --repetitions 3 --jobs 5 --timeout 30 \
        --output data/benchmarks/arq_business_e2e.json
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import math
import platform
import statistics
import sys
import time
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from arq.connections import ArqRedis, RedisSettings

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

try:
    from scripts._strict_json import dump_strict_json
except (ModuleNotFoundError, ImportError):
    from _strict_json import dump_strict_json  # type: ignore[no-redef]

logger = logging.getLogger("benchmark_arq_business_e2e")


PRODUCTION_QUEUE_NAME = "arq:queue"

ALLOWED_BUSINESS_TASKS: tuple[str, ...] = (
    "preflight_check_task",
    "validate_model_task",
)

MUTATING_BUSINESS_TASKS: frozenset[str] = frozenset(
    {
        "collect_bids_task",
        "update_kb_task",
        "manual_retrain_task",
        "refresh_data_task",
        "manual_full_task",
        "run_retrain_pipeline_task",
        "development_data_refresh_task",
    }
)

# enqueue 시 kwargs 로 execution_id 를 넘기지 않으므로 run_automation_pipeline
# 의 PipelineExecution SELECT 가 None 으로 떨어져 상태 갱신 커밋 경로가
# 비활성화된다. 이 사실은 코드로 강제되며, 주석으로도 명시한다.
NO_EXECUTION_ID_SENTINEL: str = ""


class BenchmarkArgumentError(ValueError):
    """CLI/인자 검증 실패 시 발생하는 예외."""


def generate_business_e2e_queue_name(prefix: str = "arq:benchmark:business-e2e") -> str:
    """격리 큐 이름을 실행마다 새로 생성한다.

    운영 큐 arq:queue 와 절대 겹치지 않으며 동일 프로세스 내/외 호출에서
    충돌하지 않도록 uuid.hex 접미사를 붙인다.
    """
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


def calculate_latency_percentiles(values: list[float]) -> dict[str, float]:
    """주요 백분위수와 기술 통계량을 ms 단위 딕셔너리로 반환합니다."""
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


def validate_requested_tasks(task_names: list[str]) -> list[str]:
    """측정 대상 task 목록을 화이트리스트 검증으로 확정한다.

    화이트리스트는 ALLOWED_BUSINESS_TASKS 두 개뿐이며, 이 밖의 이름이
    들어오면 MUTATING_BUSINESS_TASKS 에 속하든 아니든 거부한다. 실수로
    데이터를 변경하는 task 가 큐에 들어가는 경로를 차단하는 것이
    1차 목적이다.
    """
    if not task_names:
        raise BenchmarkArgumentError("최소 1개 이상의 측정 대상 task 가 필요합니다.")
    deduped: list[str] = []
    seen: set[str] = set()
    for name in task_names:
        if name in seen:
            continue
        seen.add(name)
        deduped.append(name)

    allowed_set = set(ALLOWED_BUSINESS_TASKS)
    rejected: list[str] = [name for name in deduped if name not in allowed_set]
    if rejected:
        allowed_repr = ", ".join(ALLOWED_BUSINESS_TASKS)
        raise BenchmarkArgumentError(
            f"허용되지 않은 task 가 포함되어 있습니다: {rejected}. "
            f"허용 목록: [{allowed_repr}]. 데이터를 변경하는 task 는 절대 큐에 넣지 않습니다."
        )
    return deduped


def assert_queue_isolation(queue_name: str) -> None:
    """격리 큐 이름이 운영 큐와 다른지 코드에서 강제한다."""
    if not queue_name:
        raise BenchmarkArgumentError("격리 큐 이름이 비어 있습니다.")
    if queue_name == PRODUCTION_QUEUE_NAME:
        raise BenchmarkArgumentError(
            f"격리 큐 이름이 운영 큐({PRODUCTION_QUEUE_NAME})와 일치합니다. "
            "운영 큐를 오염시키지 않도록 격리 큐만 사용해야 합니다."
        )


def aggregate_task_metrics(
    task_name: str,
    latencies_ms: list[float],
    successes: int,
    failures: int,
    missing: int,
) -> dict[str, Any]:
    """단일 task 의 지표와 카운트를 결정론적으로 집계한다."""
    latency_stats = calculate_latency_percentiles(latencies_ms)
    return {
        "task": task_name,
        "enqueued": successes + failures + missing,
        "successful": successes,
        "failed": failures,
        "missing": missing,
        "latency_ms": {
            **latency_stats,
            "values_ms": [round(v, 3) for v in latencies_ms],
        },
    }


def build_business_e2e_result(
    *,
    queue_name: str,
    repetitions: int,
    jobs_per_repetition: int,
    task_names: list[str],
    per_task: dict[str, dict[str, Any]],
    timeout_sec: float,
    extra_errors: list[str] | None = None,
    started_at: datetime | None = None,
    finished_at: datetime | None = None,
) -> dict[str, Any]:
    """벤치마크 결과를 직렬화 가능한 dict 로 만든다.

    per_task 는 task 이름별 {latencies_ms, successes, failures, missing}을
    포함하는 dict 이다. 본 함수는 회차 단위 통계의 합계와 task 별 지표를
    결합해 반환한다.
    """
    assert_queue_isolation(queue_name)

    tasks_section: list[dict[str, Any]] = []
    total_successful = 0
    total_failed = 0
    total_missing = 0
    total_enqueued = 0
    for name in task_names:
        slot = per_task.get(name) or {}
        latencies = list(slot.get("latencies_ms") or [])
        successes = int(slot.get("successes") or 0)
        failures = int(slot.get("failures") or 0)
        missing = int(slot.get("missing") or 0)
        total_successful += successes
        total_failed += failures
        total_missing += missing
        total_enqueued += successes + failures + missing
        tasks_section.append(aggregate_task_metrics(name, latencies, successes, failures, missing))

    overall_latencies: list[float] = []
    for slot in per_task.values():
        overall_latencies.extend(slot.get("latencies_ms") or [])
    overall_latency_stats = calculate_latency_percentiles(overall_latencies)

    extra_errors = list(extra_errors or [])
    empty_results = total_enqueued == 0
    if empty_results:
        extra_errors.append("수신된 결과가 0건입니다.")
    if total_missing > 0:
        extra_errors.append(f"{total_missing}개 회차가 타임아웃 또는 누락으로 집계되지 못했습니다.")

    overall_status = (
        "success"
        if (not empty_results and total_failed == 0 and total_missing == 0 and not extra_errors)
        else "failed"
    )

    summary = {
        "repetitions": repetitions,
        "jobs_per_repetition": jobs_per_repetition,
        "total_enqueued": total_enqueued,
        "successful": total_successful,
        "failed": total_failed,
        "missing": total_missing,
        "error_count": total_failed
        + total_missing
        + (1 if empty_results else 0)
        + len(extra_errors),
    }

    result = {
        "status": overall_status,
        "timestamp": (finished_at or datetime.now(UTC)).isoformat(),
        "started_at": (started_at or finished_at or datetime.now(UTC)).isoformat(),
        "finished_at": (finished_at or datetime.now(UTC)).isoformat(),
        "is_synthetic": False,
        "target_tasks": list(task_names),
        "allowed_target_tasks": list(ALLOWED_BUSINESS_TASKS),
        "rejected_target_tasks": sorted(MUTATING_BUSINESS_TASKS),
        "production_queue": PRODUCTION_QUEUE_NAME,
        "isolated_queue": queue_name,
        "timeout_sec": float(timeout_sec),
        "summary": summary,
        "per_task": tasks_section,
        "latency_ms": overall_latency_stats,
        "errors": extra_errors,
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "benchmark_worker_mode": "in_process_business",
        },
    }
    return result


def should_exit_nonzero(result: dict[str, Any]) -> bool:
    """결과에서 성공/실패 종료를 판정한다.

    결과가 0건이거나 실패/누락 회차가 하나라도 있으면 0이 아닌 종료
    코드를 반환한다. 빈 결과를 통과로 승격하지 않는다.
    """
    summary = result.get("summary") or {}
    if int(summary.get("total_enqueued", 0)) <= 0:
        return True
    if int(summary.get("failed", 0)) > 0:
        return True
    if int(summary.get("missing", 0)) > 0:
        return True
    return result.get("status") != "success"


@dataclass
class BusinessE2EConfig:
    queue_name: str
    task_names: tuple[str, ...]
    repetitions: int
    jobs_per_repetition: int
    timeout_sec: float


def build_business_e2e_config(
    *,
    task_names: list[str],
    repetitions: int,
    jobs_per_repetition: int,
    timeout_sec: float,
) -> BusinessE2EConfig:
    """인자 검증을 통과한 BusinessE2EConfig 를 생성한다."""
    if repetitions < 1:
        raise BenchmarkArgumentError("repetitions 은 1 이상이어야 합니다.")
    if jobs_per_repetition < 1:
        raise BenchmarkArgumentError("jobs_per_repetition 은 1 이상이어야 합니다.")
    if timeout_sec <= 0 or not math.isfinite(timeout_sec):
        raise BenchmarkArgumentError("timeout_sec 은 유한한 양수여야 합니다.")
    validated_tasks = validate_requested_tasks(task_names)
    queue_name = generate_business_e2e_queue_name()
    assert_queue_isolation(queue_name)
    return BusinessE2EConfig(
        queue_name=queue_name,
        task_names=tuple(validated_tasks),
        repetitions=repetitions,
        jobs_per_repetition=jobs_per_repetition,
        timeout_sec=float(timeout_sec),
    )


async def enqueue_business_task(
    redis: ArqRedis,
    *,
    queue_name: str,
    task_name: str,
    job_id: str,
) -> Any:
    """단일 task 를 격리 큐로 enqueue 한다. execution_id 는 의도적으로
    넘기지 않는다. run_automation_pipeline 의 PipelineExecution SELECT
    가 None 으로 떨어져 상태 갱신 커밋이 일어나지 않는다.
    """
    assert_queue_isolation(queue_name)
    return await redis.enqueue_job(
        task_name,
        _job_id=job_id,
        _queue_name=queue_name,
    )


async def collect_business_results(
    redis: ArqRedis,
    queue_name: str,
    expected_count: int,
    timeout_sec: float,
) -> tuple[list[dict[str, Any]], list[str]]:
    """격리 큐의 결과 키에서 회차별 완료 신호를 수집한다.

    arq 는 정상 완료 시 `arq:result:<job_id>` 에 JSON 직렬화된
    결과를 기록한다. 해당 키를 polldir 하여 회차 수만큼 모은다.
    실제 측정 실행 시 호출되며 본 스크립트의 단위 테스트는
    redis 를 mocking 하거나 호출하지 않는다.
    """
    assert_queue_isolation(queue_name)
    collected: list[dict[str, Any]] = []
    errors: list[str] = []
    deadline = time.perf_counter() + timeout_sec
    seen_job_ids: set[str] = set()
    while len(collected) < expected_count and time.perf_counter() < deadline:
        cursor = 0
        new_in_batch = 0
        while True:
            cursor, matched = await redis.scan(cursor=cursor, match="arq:result:*", count=200)
            for key in matched:
                key_str = (
                    key.decode("utf-8", errors="ignore") if isinstance(key, bytes) else str(key)
                )
                if queue_name not in key_str:
                    continue
                job_id = key_str.split(":", 2)[-1]
                if job_id in seen_job_ids:
                    continue
                try:
                    raw = await redis.get(key_str)
                except Exception as exc:  # pragma: no cover - 실측 경로
                    errors.append(f"결과 조회 실패 ({job_id}): {exc}")
                    continue
                if raw is None:
                    continue
                try:
                    payload = json.loads(
                        raw.decode("utf-8") if isinstance(raw, (bytes, bytearray)) else str(raw)
                    )
                except Exception as exc:  # pragma: no cover - 실측 경로
                    errors.append(f"결과 파싱 실패 ({job_id}): {exc}")
                    continue
                seen_job_ids.add(job_id)
                collected.append(
                    {
                        "job_id": job_id,
                        "latency_ms": float(payload.get("latency_ms", 0.0)),
                        "success": bool(payload.get("success", True)),
                        "error": payload.get("error"),
                    }
                )
                new_in_batch += 1
            if cursor == 0:
                break
        if new_in_batch == 0:
            await asyncio.sleep(0.05)
    if len(collected) < expected_count:
        errors.append(
            f"타임아웃({timeout_sec}초) 내에 {expected_count}개 회차 결과를 수집하지 못했습니다 "
            f"(수신: {len(collected)}/{expected_count})."
        )
    return collected, errors


async def cleanup_business_e2e_resources(
    redis: ArqRedis,
    queue_name: str,
    job_ids: list[str] | None = None,
) -> int:
    """격리 큐와 부속 키를 안전하게 정리한다.

    운영 큐 arq:queue 는 절대 건드리지 않으며, 격리 큐 이름 패턴으로
    매칭된 키만 삭제한다.
    """
    assert_queue_isolation(queue_name)
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
            cursor, matched = await redis.scan(cursor=cursor, match=f"*{queue_name}*", count=200)
            for k in matched:
                if isinstance(k, bytes):
                    keys_to_delete.add(k.decode("utf-8", errors="ignore"))
                else:
                    keys_to_delete.add(str(k))
            if cursor == 0:
                break
    except Exception as scan_err:  # pragma: no cover - 실측 경로
        logger.warning("Redis 스캔 중 예외 발생 (정리 지속): %s", scan_err)

    if not keys_to_delete:
        return 0

    deleted_count = 0
    key_list = list(keys_to_delete)
    for i in range(0, len(key_list), 100):
        chunk = key_list[i : i + 100]
        try:
            res = await redis.delete(*chunk)
            deleted_count += res
        except Exception as del_err:  # pragma: no cover - 실측 경로
            logger.warning("키 삭제 중 오류 발생: %s", del_err)

    return deleted_count


def run_single_repetition_sync(
    config: BusinessE2EConfig,
    redis_url: str,
    repetition_index: int,
) -> dict[str, Any]:
    """단일 회차의 enqueue/수집/정리를 동기적으로 실행한다.

    본 함수는 실측 시 사용되며 단위 테스트는 직접 호출하지 않는다.
    """
    return asyncio.run(
        run_single_repetition_async(
            config=config,
            redis_url=redis_url,
            repetition_index=repetition_index,
        )
    )


async def run_single_repetition_async(
    config: BusinessE2EConfig,
    redis_url: str,
    repetition_index: int,
) -> dict[str, Any]:
    """단일 회차의 enqueue/수집/정리를 비동기적으로 실행한다."""
    assert_queue_isolation(config.queue_name)
    redis_settings = RedisSettings.from_dsn(redis_url)
    redis_pool: ArqRedis = await _create_redis_pool(redis_settings)
    job_ids: list[str] = []
    per_task_results: dict[str, dict[str, Any]] = {
        name: {"latencies_ms": [], "successes": 0, "failures": 0, "missing": 0}
        for name in config.task_names
    }
    errors: list[str] = []
    started = time.perf_counter()

    try:
        for task_name in config.task_names:
            for i in range(config.jobs_per_repetition):
                job_id = (
                    f"biz-{config.queue_name.split(':')[-1]}-r{repetition_index}-{task_name}-{i}"
                )
                job_ids.append(job_id)
                try:
                    await enqueue_business_task(
                        redis_pool,
                        queue_name=config.queue_name,
                        task_name=task_name,
                        job_id=job_id,
                    )
                except Exception as exc:  # pragma: no cover - 실측 경로
                    errors.append(f"enqueue 실패 ({task_name}/{job_id}): {exc}")

        expected = len(config.task_names) * config.jobs_per_repetition
        collected, collect_errors = await collect_business_results(
            redis_pool,
            config.queue_name,
            expected_count=expected,
            timeout_sec=config.timeout_sec,
        )
        errors.extend(collect_errors)

        received_by_task: dict[str, int] = dict.fromkeys(config.task_names, 0)
        for item in collected:
            # job_id 인코딩: biz-<queue>-r<idx>-<task>-<i>
            parts = item["job_id"].split("-")
            task_marker = parts[3] if len(parts) >= 5 and parts[2].startswith("r") else ""
            task_name = task_marker if task_marker in per_task_results else ""
            if not task_name:
                continue
            per_task_results[task_name]["latencies_ms"].append(item["latency_ms"])
            received_by_task[task_name] += 1
            if item.get("success"):
                per_task_results[task_name]["successes"] += 1
            else:
                per_task_results[task_name]["failures"] += 1

        for task_name in config.task_names:
            expected_for_task = config.jobs_per_repetition
            received = received_by_task[task_name]
            missing = max(0, expected_for_task - received)
            per_task_results[task_name]["missing"] = missing
    finally:
        with contextlib.suppress(Exception):
            await cleanup_business_e2e_resources(redis_pool, config.queue_name, job_ids)
        with contextlib.suppress(Exception):
            await redis_pool.aclose()

    duration = time.perf_counter() - started
    return {
        "repetition_index": repetition_index,
        "duration_sec": duration,
        "per_task": per_task_results,
        "errors": errors,
    }


async def _create_redis_pool(redis_settings: RedisSettings) -> ArqRedis:
    """arq Redis 풀을 생성한다. 실측 시에만 호출된다."""
    from arq import create_pool  # 지연 임포트로 단위 테스트의 의존성 분리

    return await create_pool(redis_settings)


def aggregate_repetitions(
    config: BusinessE2EConfig,
    repetition_results: list[dict[str, Any]],
    started_at: datetime,
    finished_at: datetime,
) -> dict[str, Any]:
    """회차 결과를 합산해 최종 결과 dict 를 만든다."""
    per_task: dict[str, dict[str, Any]] = {
        name: {"latencies_ms": [], "successes": 0, "failures": 0, "missing": 0}
        for name in config.task_names
    }
    extra_errors: list[str] = []
    for rep in repetition_results:
        rep_errors = rep.get("errors") or []
        for err in rep_errors:
            extra_errors.append(f"rep{rep.get('repetition_index')}: {err}")
        for name, slot in (rep.get("per_task") or {}).items():
            target = per_task.setdefault(
                name,
                {"latencies_ms": [], "successes": 0, "failures": 0, "missing": 0},
            )
            target["latencies_ms"].extend(slot.get("latencies_ms") or [])
            target["successes"] += int(slot.get("successes") or 0)
            target["failures"] += int(slot.get("failures") or 0)
            target["missing"] += int(slot.get("missing") or 0)

    return build_business_e2e_result(
        queue_name=config.queue_name,
        repetitions=config.repetitions,
        jobs_per_repetition=config.jobs_per_repetition,
        task_names=list(config.task_names),
        per_task=per_task,
        timeout_sec=config.timeout_sec,
        extra_errors=extra_errors,
        started_at=started_at,
        finished_at=finished_at,
    )


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="실제 등록 업무 task Arq E2E 벤치마크 하네스 (격리 큐, 데이터 무변경)"
    )
    parser.add_argument(
        "--repetitions",
        "-r",
        type=int,
        default=1,
        help="반복 측정 회차 수 (기본값: 1)",
    )
    parser.add_argument(
        "--jobs",
        "-n",
        type=int,
        default=5,
        help="회차당 task 별 enqueue 작업 수 (기본값: 5)",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="회차당 결과 수집 타임아웃(초) (기본값: 30.0)",
    )
    parser.add_argument(
        "--redis-url",
        default="redis://localhost:6379/0",
        help="Redis 접속 URL (기본값: redis://localhost:6379/0)",
    )
    parser.add_argument(
        "--tasks",
        nargs="+",
        default=list(ALLOWED_BUSINESS_TASKS),
        help=(
            "측정 대상 task 이름 목록. 기본은 허용 화이트리스트 전체. "
            "허용되지 않은 이름이 포함되면 즉시 종료 코드 2로 중단한다."
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
        "--quiet",
        "-q",
        action="store_true",
        help="요약 리포트 출력을 생략합니다",
    )
    return parser


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    return build_arg_parser().parse_args(argv)


def report_result(result: dict[str, Any]) -> None:
    """결과 요약을 stdout 으로 출력한다."""
    print("=" * 68)
    print("Arq 실제 등록 업무 task E2E 벤치마크 결과")
    print("=" * 68)
    print(f"상태: {result.get('status', 'unknown').upper()}")
    print(f"격리 큐: {result.get('isolated_queue')}")
    print(f"대상 task: {result.get('target_tasks')}")
    print(f"is_synthetic: {result.get('is_synthetic')}")
    summary = result.get("summary") or {}
    print(
        f"총 enqueued: {summary.get('total_enqueued', 0)} | "
        f"성공: {summary.get('successful', 0)} | "
        f"실패: {summary.get('failed', 0)} | "
        f"누락: {summary.get('missing', 0)}"
    )
    print("-" * 68)
    print("종단 지연 P50/P95/P99 (ms):")
    latency = result.get("latency_ms") or {}
    print(
        f"  P50: {latency.get('p50_ms', 0.0):.2f}ms | "
        f"P95: {latency.get('p95_ms', 0.0):.2f}ms | "
        f"P99: {latency.get('p99_ms', 0.0):.2f}ms"
    )
    print("=" * 68)


def save_result(result: dict[str, Any], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(dump_strict_json(result), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        config = build_business_e2e_config(
            task_names=list(args.tasks),
            repetitions=args.repetitions,
            jobs_per_repetition=args.jobs,
            timeout_sec=args.timeout,
        )
    except BenchmarkArgumentError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    if not args.quiet:
        print(
            f"격리 큐 {config.queue_name} 에서 {config.repetitions}회 측정, "
            f"task={list(config.task_names)}, 회차당 작업 수={config.jobs_per_repetition}."
        )

    started_at = datetime.now(UTC)
    repetition_results: list[dict[str, Any]] = []
    for rep_idx in range(1, config.repetitions + 1):
        if config.repetitions > 1 and not args.quiet:
            print(f"\n>>> [회차 {rep_idx}/{config.repetitions}] 실측 시작...")
        try:
            rep_result = run_single_repetition_sync(
                config=config,
                redis_url=args.redis_url,
                repetition_index=rep_idx,
            )
        except Exception as exc:
            print(f"회차 {rep_idx} 실행 실패: {exc}", file=sys.stderr)
            return 1
        repetition_results.append(rep_result)
        if config.repetitions > 1 and not args.quiet:
            print(
                f"회차 {rep_idx} 완료: 소요 {rep_result['duration_sec']:.3f}초, "
                f"per_task={rep_result['per_task']}"
            )

    finished_at = datetime.now(UTC)
    result = aggregate_repetitions(
        config=config,
        repetition_results=repetition_results,
        started_at=started_at,
        finished_at=finished_at,
    )

    if not args.quiet:
        report_result(result)

    if args.output:
        try:
            save_result(result, args.output)
            if not args.quiet:
                print(f"\n결과 저장 완료: {args.output}")
        except Exception as exc:
            print(f"결과 저장 실패: {exc}", file=sys.stderr)
            return 1

    if should_exit_nonzero(result):
        if not args.quiet:
            print(
                f"\n벤치마크 결과 실패: status={result.get('status')}, "
                f"errors={result.get('errors')}",
                file=sys.stderr,
            )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
