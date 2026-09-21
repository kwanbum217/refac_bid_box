"""워커 관측 기록(heartbeat, 스케줄 결과)의 스레드 오프로드 검증.

D9: heartbeat 기록과 스케줄 결과 기록이 이벤트 루프에서 동기 Redis 왕복을 수행했습니다.
호출 성공만 확인하는 것으로는 오프로드를 증명할 수 없으므로, 기록 함수가 이벤트 루프
스레드가 아닌 실행 스레드에서 호출됨을 스레드 식별자로 단언합니다.
"""

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable
from typing import Any

import pytest

from src.app.core.config import settings
from src.tasks import worker
from src.tasks.scheduled_tasks import _record_schedule


async def _wait_until(
    predicate: Callable[[], bool], *, attempts: int = 200, interval: float = 0.005
) -> None:
    """이벤트 루프를 점유하지 않고 조건이 참이 될 때까지 양보하며 기다립니다."""
    for _ in range(attempts):
        if predicate():
            return
        await asyncio.sleep(interval)


@pytest.mark.asyncio
async def test_heartbeat_loop_records_off_event_loop_thread(monkeypatch):
    """주기 heartbeat 기록이 이벤트 루프 스레드가 아닌 스레드에서 실행된다."""
    loop_thread_id = threading.get_ident()
    run_loop = asyncio.get_running_loop()
    recorded = asyncio.Event()
    recorded_thread_ids: list[int] = []

    def fake_record(key: str = worker.WORKER_HEARTBEAT_KEY) -> None:
        recorded_thread_ids.append(threading.get_ident())
        run_loop.call_soon_threadsafe(recorded.set)

    monkeypatch.setattr(worker, "record_worker_heartbeat", fake_record)

    task = asyncio.create_task(worker._heartbeat_loop())
    try:
        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(recorded.wait(), timeout=5)
        assert recorded.is_set(), "heartbeat 기록이 호출되지 않았습니다."
        assert recorded_thread_ids, "기록 실행 스레드를 확인하지 못했습니다."
        assert loop_thread_id not in recorded_thread_ids, (
            "heartbeat 기록이 이벤트 루프 스레드에서 실행되었습니다."
        )
    finally:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_heartbeat_recording_does_not_block_event_loop(monkeypatch):
    """기록이 오래 걸려도 이벤트 루프는 계속 돌아야 한다.

    대조군으로 같은 기록을 이벤트 루프에서 동기 실행하면 루프가 멈춰 이 단언이 깨집니다.
    """
    record_entered = threading.Event()
    record_release = threading.Event()
    record_exited = threading.Event()

    def blocking_record(key: str = worker.WORKER_HEARTBEAT_KEY) -> None:
        record_entered.set()
        record_release.wait(timeout=5)
        record_exited.set()

    monkeypatch.setattr(worker, "record_worker_heartbeat", blocking_record)

    task = asyncio.create_task(worker._heartbeat_loop())
    try:
        await _wait_until(record_entered.is_set)
        assert record_entered.is_set(), "heartbeat 기록이 시작되지 않았습니다."
        await asyncio.sleep(0.05)
        assert not record_exited.is_set(), "기록이 이벤트 루프를 점유해 루프가 멈췄습니다."
    finally:
        record_release.set()
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task


@pytest.mark.asyncio
async def test_on_startup_records_heartbeat_off_event_loop_thread(monkeypatch):
    """워커 기동 경로의 heartbeat 기록도 이벤트 루프 밖에서 실행된다."""
    loop_thread_id = threading.get_ident()
    recorded_thread_ids: list[int] = []

    def fake_record(key: str = worker.WORKER_HEARTBEAT_KEY) -> None:
        recorded_thread_ids.append(threading.get_ident())

    async def idle_heartbeat_loop(key: str = worker.WORKER_HEARTBEAT_KEY) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()

    monkeypatch.setattr(settings, "OTEL_ENABLED", False)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", False)
    monkeypatch.setattr(worker, "record_worker_heartbeat", fake_record)
    monkeypatch.setattr(worker, "_heartbeat_loop", idle_heartbeat_loop)

    ctx: dict[str, Any] = {}
    await worker._on_startup(ctx)
    try:
        assert recorded_thread_ids, "기동 시 heartbeat 기록이 호출되지 않았습니다."
        assert loop_thread_id not in recorded_thread_ids, (
            "기동 시 heartbeat 기록이 이벤트 루프 스레드에서 실행되었습니다."
        )
    finally:
        await worker._on_shutdown(ctx)


@pytest.mark.asyncio
async def test_backup_startup_records_heartbeat_off_event_loop_thread(monkeypatch):
    """백업 워커 기동 경로의 heartbeat 기록도 이벤트 루프 밖에서 실행된다."""
    loop_thread_id = threading.get_ident()
    recorded_thread_ids: list[int] = []

    def fake_record(key: str = worker.WORKER_HEARTBEAT_KEY) -> None:
        recorded_thread_ids.append(threading.get_ident())

    async def idle_heartbeat_loop(key: str = worker.WORKER_HEARTBEAT_KEY) -> None:
        with contextlib.suppress(asyncio.CancelledError):
            await asyncio.Event().wait()

    monkeypatch.setattr(settings, "OTEL_ENABLED", False)
    monkeypatch.setattr(worker, "record_worker_heartbeat", fake_record)
    monkeypatch.setattr(worker, "_heartbeat_loop", idle_heartbeat_loop)

    ctx: dict[str, Any] = {}
    await worker._on_backup_startup(ctx)
    try:
        assert recorded_thread_ids, "백업 워커 기동 시 heartbeat 기록이 호출되지 않았습니다."
        assert loop_thread_id not in recorded_thread_ids, (
            "백업 워커 기동 시 heartbeat 기록이 이벤트 루프 스레드에서 실행되었습니다."
        )
    finally:
        await worker._on_backup_shutdown(ctx)


@pytest.mark.asyncio
async def test_record_schedule_records_off_event_loop_thread(monkeypatch):
    """스케줄 결과 기록이 이벤트 루프 밖에서 실행되고 기록 내용과 실패 정책이 유지된다."""
    loop_thread_id = threading.get_ident()
    calls: list[tuple[int, str, Any, bool]] = []

    def fake_record(schedule_name: str, outcome: Any, success: bool) -> None:
        calls.append((threading.get_ident(), schedule_name, outcome, success))

    monkeypatch.setattr(worker, "record_schedule_result", fake_record)

    async def succeeding_task(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"status": "success"}

    tracked = _record_schedule("nightly")(succeeding_task)
    assert await tracked({}) == {"status": "success"}

    class TaskFailure(RuntimeError):
        pass

    async def failing_task(_ctx: dict[str, Any]) -> dict[str, Any]:
        raise TaskFailure("expected")

    tracked_failure = _record_schedule("weekly")(failing_task)
    with pytest.raises(TaskFailure, match=r"^expected$"):
        await tracked_failure({})

    assert [(name, outcome, success) for _, name, outcome, success in calls] == [
        ("nightly", {"status": "success"}, True),
        ("weekly", None, False),
    ]
    assert loop_thread_id not in [thread_id for thread_id, *_ in calls], (
        "스케줄 결과 기록이 이벤트 루프 스레드에서 실행되었습니다."
    )
