"""
tests/test_schedule_run_log_dup_20261113.py

같은 schedule_name·같은 started_at 으로 schedule_run_log 행이 여러 개 남는 원인 고정.

한 번의 태스크 실행이 `_record_schedule_run` 을 정확히 한 번만 부르는지 세고, 크론
경로와 기동 따라잡기 경로가 같은 초에 겹치면 두 행이 같은 started_at 으로 보이는
것을 재현합니다. MySQL `DateTime`(fsp 없음)은 초 단위로 잘리므로 서로 다른 두
실행도 같은 started_at 으로 보일 수 있습니다.

SQLite 인메모리와 대역 캐시만 쓰며 Redis·MySQL·Docker 에 연결하지 않습니다.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.db import Base
from src.app.models.schedule_run_log import ScheduleRunLog
from src.tasks import scheduled_tasks, worker
from src.tasks.scheduled_tasks import _record_schedule

FIXED_START = datetime(2026, 11, 11, 3, 0, 0, 120_000)


class _FakeCache:
    """get·set 만 있는 Redis 대역."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.data[key] = value


@pytest.fixture
def session_factory() -> Iterator[sessionmaker[Session]]:
    # to_thread 기록 스레드와 시험 스레드가 같은 인메모리 DB 를 보도록 연결을 공유합니다.
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine, tables=[ScheduleRunLog.__table__])
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


@pytest.fixture
def recording_env(
    monkeypatch: pytest.MonkeyPatch, session_factory: sessionmaker[Session]
) -> _FakeCache:
    cache = _FakeCache()
    monkeypatch.setattr(worker, "_worker_cache", cache)
    monkeypatch.setattr(worker, "SessionLocal", session_factory)
    return cache


def _rows(session_factory: sessionmaker[Session]) -> list[ScheduleRunLog]:
    with session_factory() as session:
        return list(session.scalars(select(ScheduleRunLog).order_by(ScheduleRunLog.id)))


def _count_record_runs(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    calls: list[str] = []
    original = worker._record_schedule_run

    def counting(schedule_name: str, outcome: Any, success: bool) -> None:
        calls.append(schedule_name)
        original(schedule_name, outcome, success)

    monkeypatch.setattr(worker, "_record_schedule_run", counting)
    return calls


async def test_success_execution_writes_exactly_one_row(
    recording_env: _FakeCache,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls = _count_record_runs(monkeypatch)

    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"status": "success"}

    tracked = _record_schedule("drift_monitor")(task)
    assert await tracked({}) == {"status": "success"}

    assert calls == ["drift_monitor"]
    rows = _rows(session_factory)
    assert len(rows) == 1
    assert rows[0].schedule_name == "drift_monitor"


async def test_exception_execution_writes_exactly_one_row(
    recording_env: _FakeCache,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class TaskFailure(RuntimeError):
        pass

    calls = _count_record_runs(monkeypatch)

    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        raise TaskFailure("expected")

    tracked = _record_schedule("weekly_retrain")(task)
    with pytest.raises(TaskFailure, match=r"^expected$"):
        await tracked({})

    assert calls == ["weekly_retrain"]
    rows = _rows(session_factory)
    assert len(rows) == 1
    assert rows[0].success is False
    assert rows[0].error_type == "TaskFailure"


async def test_cron_and_startup_catchup_in_one_second_write_two_rows(
    recording_env: _FakeCache,
    session_factory: sessionmaker[Session],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """2026-11-11 중복 행의 지문(같은 이름·같은 started_at)을 재현합니다.

    크론 경로와 기동 따라잡기 경로는 같은 데코레이터 함수를 각각 한 번씩
    부릅니다. 실행이 같은 초에 겹치면 MySQL 초 절단 때문에 두 행의 started_at
    이 같아 보이고, 한 실행이 두 행을 남긴 것처럼 읽힙니다.
    """
    invocations: list[dict[str, Any]] = []

    async def body(ctx: dict[str, Any]) -> dict[str, Any]:
        invocations.append(ctx)
        return {"status": "skipped", "reason": "already_running"}

    tracked = _record_schedule("drift_monitor")(body)
    monkeypatch.setattr(scheduled_tasks, "drift_monitor_task", tracked)
    monkeypatch.setattr(
        scheduled_tasks,
        "check_drift_monitor_catchup_needed",
        lambda: (True, "missed_slot", {"target_task": "drift_monitor"}),
    )
    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: FIXED_START)

    await tracked({})
    await scheduled_tasks.run_drift_monitor_catchup_task({})

    assert len(invocations) == 2
    rows = _rows(session_factory)
    assert [row.schedule_name for row in rows] == ["drift_monitor", "drift_monitor"]
    assert rows[0].id != rows[1].id
    assert rows[0].started_at == rows[1].started_at == FIXED_START
    assert rows[0].started_at.replace(microsecond=0) == rows[1].started_at.replace(microsecond=0)


def test_same_schedule_has_cron_and_catchup_dispatch_paths() -> None:
    """한 스케줄이 등록된 크론과 기동 따라잡기 두 경로에서 실행됨을 고정합니다."""
    cron_targets = {
        getattr(cron_job.coroutine, "__name__", "") for cron_job in worker.WorkerSettings.cron_jobs
    }
    function_targets = {
        getattr(getattr(entry, "coroutine", entry), "__name__", "")
        for entry in worker.WorkerSettings.functions
    }

    assert "drift_monitor_task" in cron_targets
    assert "run_drift_monitor_catchup_task" in function_targets
    assert scheduled_tasks.drift_monitor_task.__name__ == "drift_monitor_task"
