"""
tests/test_arq_worker_concurrency.py

Arq 워커 무거운 태스크 동시 실행 방지 및 재시도 폭풍(Retry Storm) 방어 회귀 테스트.
실제 Redis, Chroma, Ollama, MySQL 실물을 일절 호출하지 않고 테스트 대역(Test Double)으로만 검증합니다.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import patch

import pytest

from src.tasks.automation_tasks import (
    collect_bids_task,
    manual_full_task,
    preflight_check_task,
    run_automation_pipeline,
    update_kb_task,
    validate_model_task,
)
from src.tasks.worker import (
    HEAVY_JOB_TIMEOUT_SECONDS,
    HEAVY_TASK_NAMES,
    WorkerSettings,
    get_heavy_task_lock,
    get_running_heavy_tasks,
    reset_heavy_task_lock,
)


@pytest.fixture(autouse=True)
def reset_concurrency_lock():
    """각 테스트 전후로 무거운 태스크 잠금을 초기화합니다."""
    reset_heavy_task_lock()
    yield
    reset_heavy_task_lock()


@pytest.mark.asyncio
async def test_heavy_tasks_cannot_run_concurrently():
    """무거운 태스크 여러 건이 동시에 큐에 있어도 동시에 실행되지 않고 직렬화됨을 단언합니다."""
    active_heavy_tasks = 0
    max_concurrent_heavy_tasks = 0
    execution_order: list[str] = []

    async def mock_pipeline(
        ctx: dict[str, Any], *, run_mode: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal active_heavy_tasks, max_concurrent_heavy_tasks
        active_heavy_tasks += 1
        max_concurrent_heavy_tasks = max(max_concurrent_heavy_tasks, active_heavy_tasks)
        execution_order.append(f"start:{run_mode}")
        await asyncio.sleep(0.05)
        execution_order.append(f"end:{run_mode}")
        active_heavy_tasks -= 1
        return {"status": "success", "run_mode": run_mode, "completed_steps": [run_mode]}

    with patch("src.tasks.automation_tasks.run_automation_pipeline", side_effect=mock_pipeline):
        ctx: dict[str, Any] = {"job_id": "test_heavy"}
        results = await asyncio.gather(
            update_kb_task(ctx),
            collect_bids_task(ctx),
            manual_full_task(ctx),
        )

    assert len(results) == 3
    for r in results:
        assert r["status"] == "success"

    assert max_concurrent_heavy_tasks == 1
    assert active_heavy_tasks == 0
    assert len(execution_order) == 6
    for i in range(0, 6, 2):
        start_mode = execution_order[i].split(":")[1]
        end_mode = execution_order[i + 1].split(":")[1]
        assert start_mode == end_mode, f"태스크가 겹쳐서 실행되었습니다: {execution_order}"


@pytest.mark.asyncio
async def test_retry_storm_three_update_kb_tasks_serialized():
    """2026-09-09 장애 실측 시나리오: 재시도 큐에서 3건의 update_kb_task 가 동시 발화할 때 직렬화 검증."""
    active_instances = 0
    max_concurrent_instances = 0
    completed_jobs: list[str] = []

    async def mock_pipeline(
        ctx: dict[str, Any], *, run_mode: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal active_instances, max_concurrent_instances
        active_instances += 1
        max_concurrent_instances = max(max_concurrent_instances, active_instances)
        job_id = str(ctx.get("job_id", "unknown"))
        await asyncio.sleep(0.04)
        completed_jobs.append(job_id)
        active_instances -= 1
        return {"status": "success", "run_mode": run_mode, "job_id": job_id}

    with patch("src.tasks.automation_tasks.run_automation_pipeline", side_effect=mock_pipeline):
        job_1 = {"job_id": "probe-kb-repro:update_kb_task", "job_try": 3}
        job_2 = {"job_id": "kb-verify-16g:update_kb_task", "job_try": 3}
        job_3 = {"job_id": "kb-peak-measure:update_kb_task", "job_try": 2}

        results = await asyncio.gather(
            update_kb_task(job_1),
            update_kb_task(job_2),
            update_kb_task(job_3),
        )

    assert len(results) == 3
    assert max_concurrent_instances == 1
    assert active_instances == 0
    assert len(completed_jobs) == 3


@pytest.mark.asyncio
async def test_light_tasks_run_concurrently_with_heavy_tasks():
    """가벼운 태스크는 무거운 태스크가 돌고 있어도 차단되지 않고 동시 실행됨을 단언합니다."""
    heavy_started = asyncio.Event()
    light_finished = asyncio.Event()
    light_executed_during_heavy = False

    async def mock_pipeline(
        ctx: dict[str, Any], *, run_mode: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal light_executed_during_heavy
        if run_mode == "kb_only":
            heavy_started.set()
            await light_finished.wait()
            return {"status": "success", "run_mode": run_mode}
        elif run_mode in ("preflight_only", "predict_only"):
            if heavy_started.is_set():
                light_executed_during_heavy = True
            return {"status": "success", "run_mode": run_mode}
        return {"status": "success", "run_mode": run_mode}

    with patch("src.tasks.automation_tasks.run_automation_pipeline", side_effect=mock_pipeline):
        ctx: dict[str, Any] = {"job_id": "test_light_heavy"}

        async def run_heavy():
            return await update_kb_task(ctx)

        async def run_lights():
            await heavy_started.wait()
            r1 = await preflight_check_task(ctx)
            r2 = await validate_model_task(ctx)
            light_finished.set()
            return [r1, r2]

        heavy_res, light_res = await asyncio.gather(run_heavy(), run_lights())

    assert heavy_res["status"] == "success"
    assert len(light_res) == 2
    assert light_executed_during_heavy is True
    assert WorkerSettings.max_jobs == 4


@pytest.mark.asyncio
async def test_retry_preservation_on_task_failure():
    """무거운 태스크 실패 시 잠금이 정상 해제되어 다음 작업/재시도가 차단되지 않음을 검증합니다."""
    call_count = 0

    async def mock_failing_pipeline(
        ctx: dict[str, Any], *, run_mode: str = "", **kwargs: Any
    ) -> dict[str, Any]:
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise RuntimeError("일시적 장애 발생")
        return {"status": "success", "run_mode": run_mode}

    with patch(
        "src.tasks.automation_tasks.run_automation_pipeline", side_effect=mock_failing_pipeline
    ):
        ctx: dict[str, Any] = {"job_id": "failing_task"}

        with pytest.raises(RuntimeError, match="일시적 장애 발생"):
            await update_kb_task(ctx)

        lock = get_heavy_task_lock()
        assert not lock.locked()
        assert len(get_running_heavy_tasks()) == 0

        res = await update_kb_task(ctx)
        assert res["status"] == "success"
        assert not lock.locked()


def test_worker_settings_preserves_concurrency_and_configuration():
    """WorkerSettings 계약 단언: max_jobs=4 유지, 무거운 태스크 타임아웃 3시간 적용."""
    assert WorkerSettings.max_jobs == 4
    assert WorkerSettings.job_timeout == 1800

    func_names = set()
    timeout_map = {}
    for fn in WorkerSettings.functions:
        target = getattr(fn, "coroutine", fn)
        name = getattr(target, "__name__", "")
        func_names.add(name)
        timeout_map[name] = getattr(fn, "timeout_s", None)

    for heavy_name in HEAVY_TASK_NAMES:
        assert heavy_name in func_names, f"{heavy_name} 이 WorkerSettings.functions 에 없습니다."
        assert timeout_map[heavy_name] == HEAVY_JOB_TIMEOUT_SECONDS, (
            f"{heavy_name} 에 HEAVY_JOB_TIMEOUT_SECONDS({HEAVY_JOB_TIMEOUT_SECONDS}) 가 적용되지 않았습니다: {timeout_map[heavy_name]}"
        )


@pytest.mark.asyncio
async def test_heavy_run_mode_protection_in_pipeline():
    """run_automation_pipeline 직접 호출 시에도 무거운 run_mode 는 잠금으로 보호됨을 검증합니다."""
    active = 0
    max_active = 0

    async def fake_runner(db: Any, **kwargs: Any) -> tuple[str, str, dict[str, Any]]:
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.04)
        active -= 1
        return "success", "done", {}

    with (
        patch(
            "src.tasks.automation_tasks.STEP_RUNNERS", {"collect": fake_runner, "rag": fake_runner}
        ),
        patch("src.tasks.automation_tasks.get_run_mode_steps", return_value=["collect"]),
        patch("src.tasks.automation_tasks.SessionLocal"),
        patch("src.tasks.automation_tasks._report"),
    ):
        ctx: dict[str, Any] = {}
        res1, res2 = await asyncio.gather(
            run_automation_pipeline(ctx, run_mode="kb_only"),
            run_automation_pipeline(ctx, run_mode="collect_only"),
        )

    assert res1["status"] == "success"
    assert res2["status"] == "success"
    assert max_active == 1
    assert active == 0
