"""
tests/test_schedule_run_log_dup_20261113.py

`schedule_run_log` 의 불변식 고정: 한 실행은 한 행만 기록합니다.

성공·예외 어느 경로로 끝나든 `_record_schedule` 로 감싼 태스크 하나는
`_record_schedule_run` 을 정확히 한 번 부르고, 그 결과로 한 행만 남습니다.

2026-11-13 확인 결과, 2026-11-11 에 관측된 같은 이름·같은 started_at 다중 행의
원인은 두 실행 경로의 겹침이 아니라 호스트에서 돈 pytest 실행이 운영 DB 에 남긴
시험 행이었습니다. 한 회차가 0~8ms 안에 여러 행을 썼고, MySQL `DateTime`(fsp 없음)
초 절단 때문에 started_at 이 같아 보였습니다. 기본 격리는 tests/conftest.py 의
`_isolate_schedule_run_log_db` 가 담당합니다.

SQLite 인메모리와 대역 캐시만 쓰며 Redis·MySQL·Docker 에 연결하지 않습니다.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.db import Base
from src.app.models.schedule_run_log import ScheduleRunLog
from src.tasks import worker
from src.tasks.scheduled_tasks import _record_schedule


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
