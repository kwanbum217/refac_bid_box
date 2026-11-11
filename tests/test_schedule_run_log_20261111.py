"""
tests/test_schedule_run_log_20261111.py

`schedule_run_log` 테이블과 스케줄 실행 영구 기록 경로 검증.

SQLite 인메모리에서만 돌며 운영 DB·MySQL·Redis·Docker 를 쓰지 않습니다. Redis
최근 상태는 대역 캐시로 확인하고, 성공·status 실패·예외 세 경로가 각각 한 행을
남기는지, DB 기록 실패가 태스크 결과와 예외 전파를 바꾸지 않는지 봅니다.
"""

from __future__ import annotations

import importlib.util
import inspect as stdlib_inspect
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.db import Base
from src.app.models.schedule_run_log import ScheduleRunLog
from src.tasks import worker
from src.tasks.scheduled_tasks import _record_schedule

PROJECT_ROOT = Path(__file__).resolve().parents[1]
REVISION = "c5d6e7f8a9b0"
PREVIOUS_REVISION = "b4e5f6a7c8d9"
TABLE_NAME = "schedule_run_log"
INDEX_NAME = "ix_schedule_run_log_name_started"
MIGRATION_PATH = PROJECT_ROOT / "migrations" / "versions" / f"{REVISION}_add_schedule_run_log.py"

COLUMN_LENGTHS = {
    "schedule_name": 64,
    "status": 32,
    "error_type": 128,
    "error_message": 1000,
    "worker_id": 128,
}
COLUMN_NAMES = (
    "id",
    "schedule_name",
    "started_at",
    "finished_at",
    "duration_ms",
    "success",
    "status",
    "error_type",
    "error_message",
    "worker_id",
)


class _FakeCache:
    """get·set 만 있는 Redis 대역."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> Any:
        return self.data.get(key)

    def set(self, key: str, value: Any, ttl: int | None = None) -> None:
        self.data[key] = value
        if ttl is not None:
            self.ttls[key] = ttl


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


# --------------------------------------------------------------------------- #
# 모델·마이그레이션 계약
# --------------------------------------------------------------------------- #


def _load_migration() -> Any:
    spec = importlib.util.spec_from_file_location("schedule_run_log_migration", MIGRATION_PATH)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_model_columns_and_table_options() -> None:
    table = ScheduleRunLog.__table__

    assert tuple(column.name for column in table.columns) == COLUMN_NAMES
    for name, length in COLUMN_LENGTHS.items():
        assert table.c[name].type.length == length
    assert table.c["id"].primary_key is True
    for required in ("schedule_name", "started_at", "finished_at", "success"):
        assert table.c[required].nullable is False
    for optional in ("duration_ms", "status", "error_type", "error_message", "worker_id"):
        assert table.c[optional].nullable is True

    assert table.kwargs["mysql_charset"] == "utf8mb4"
    assert table.kwargs["mysql_collate"] == "utf8mb4_unicode_ci"
    indexes = {index.name: index for index in table.indexes}
    assert tuple(column.name for column in indexes[INDEX_NAME].columns) == (
        "schedule_name",
        "started_at",
    )


def test_migration_revision_follows_current_head() -> None:
    migration = _load_migration()

    assert migration.revision == REVISION
    assert migration.down_revision == PREVIOUS_REVISION

    script = ScriptDirectory.from_config(Config(str(PROJECT_ROOT / "alembic.ini")))
    heads = script.get_heads()
    assert len(heads) == 1
    chain = {rev.revision for rev in script.walk_revisions("base", heads[0])}
    assert REVISION in chain


def test_migration_declares_utf8mb4_unicode_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    migration = _load_migration()
    captured: dict[str, Any] = {}
    created_indexes: list[tuple[str, str, list[str]]] = []

    def fake_create_table(name: str, *columns: Any, **options: Any) -> None:
        captured["name"] = name
        captured["options"] = options

    def fake_create_index(
        name: str, table_name: str, columns: list[str], unique: bool = False
    ) -> None:
        created_indexes.append((name, table_name, list(columns)))

    monkeypatch.setattr(
        migration,
        "op",
        SimpleNamespace(create_table=fake_create_table, create_index=fake_create_index),
    )
    monkeypatch.setattr(migration, "_existing_tables", lambda: set())

    migration.upgrade()

    assert captured["name"] == TABLE_NAME
    assert captured["options"]["mysql_charset"] == "utf8mb4"
    assert captured["options"]["mysql_collate"] == "utf8mb4_unicode_ci"
    assert created_indexes == [(INDEX_NAME, TABLE_NAME, ["schedule_name", "started_at"])]


def test_upgrade_and_downgrade_are_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    engine = create_engine("sqlite:///:memory:")
    migration = _load_migration()
    try:
        with engine.begin() as connection:
            operations = Operations(MigrationContext.configure(connection))
            monkeypatch.setattr(migration, "op", operations)

            migration.upgrade()
            migration.upgrade()
            assert TABLE_NAME in set(inspect(connection).get_table_names())
            index_names = {index["name"] for index in inspect(connection).get_indexes(TABLE_NAME)}
            assert INDEX_NAME in index_names

            migration.downgrade()
            assert TABLE_NAME not in set(inspect(connection).get_table_names())
    finally:
        engine.dispose()


# --------------------------------------------------------------------------- #
# 기록 경로
# --------------------------------------------------------------------------- #


async def test_success_path_records_one_row(
    recording_env: _FakeCache, session_factory: sessionmaker[Session]
) -> None:
    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"status": "success"}

    tracked = _record_schedule("nightly")(task)
    assert await tracked({}) == {"status": "success"}

    rows = _rows(session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.schedule_name == "nightly"
    assert row.success is True
    assert row.status == "success"
    assert row.error_type is None
    assert row.error_message is None
    assert row.started_at <= row.finished_at
    assert row.duration_ms is not None
    assert row.duration_ms >= 0
    assert row.worker_id


async def test_status_failure_path_records_one_row(
    recording_env: _FakeCache, session_factory: sessionmaker[Session]
) -> None:
    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"status": "failed"}

    tracked = _record_schedule("coverage", success_statuses=frozenset({"ok"}))(task)
    assert await tracked({}) == {"status": "failed"}

    rows = _rows(session_factory)
    assert len(rows) == 1
    assert rows[0].success is False
    assert rows[0].status == "failed"
    assert rows[0].error_type is None


async def test_exception_path_records_one_row_and_reraises(
    recording_env: _FakeCache, session_factory: sessionmaker[Session]
) -> None:
    class TaskFailure(RuntimeError):
        pass

    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        raise TaskFailure("expected")

    tracked = _record_schedule("weekly")(task)
    with pytest.raises(TaskFailure, match=r"^expected$"):
        await tracked({})

    rows = _rows(session_factory)
    assert len(rows) == 1
    row = rows[0]
    assert row.schedule_name == "weekly"
    assert row.success is False
    assert row.status is None
    assert row.error_type == "TaskFailure"
    assert row.error_message == "expected"


async def test_error_message_is_truncated(
    recording_env: _FakeCache, session_factory: sessionmaker[Session]
) -> None:
    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        raise RuntimeError("x" * 1200)

    tracked = _record_schedule("chatty")(task)
    with pytest.raises(RuntimeError):
        await tracked({})

    rows = _rows(session_factory)
    assert len(rows[0].error_message or "") == worker.SCHEDULE_ERROR_MESSAGE_LIMIT


async def test_redis_recent_status_is_unchanged(
    recording_env: _FakeCache, session_factory: sessionmaker[Session]
) -> None:
    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"status": "success"}

    tracked = _record_schedule("nightly")(task)
    await tracked({})

    status = worker.read_schedule_status()
    assert status["nightly"]["success"] is True
    assert status["nightly"]["last_run_at"]
    assert recording_env.ttls[worker.SCHEDULE_STATUS_KEY] == worker.OBSERVATION_TTL_SECONDS
    assert len(_rows(session_factory)) == 1


async def test_db_failure_does_not_change_success_result(
    recording_env: _FakeCache,
    monkeypatch: pytest.MonkeyPatch,
    session_factory: sessionmaker[Session],
) -> None:
    def unavailable() -> Session:
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "SessionLocal", unavailable)

    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"status": "success"}

    tracked = _record_schedule("nightly")(task)
    assert await tracked({}) == {"status": "success"}
    assert worker.read_schedule_status()["nightly"]["success"] is True


async def test_db_failure_does_not_change_propagated_exception(
    recording_env: _FakeCache, monkeypatch: pytest.MonkeyPatch
) -> None:
    class TaskFailure(RuntimeError):
        pass

    def unavailable() -> Session:
        raise RuntimeError("db down")

    monkeypatch.setattr(worker, "SessionLocal", unavailable)

    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        raise TaskFailure("expected")

    tracked = _record_schedule("weekly")(task)
    with pytest.raises(TaskFailure, match=r"^expected$"):
        await tracked({})


def test_record_schedule_result_keeps_three_argument_signature() -> None:
    """기존 호출부(시험 대역 포함)가 세 인자로 부를 수 있어야 합니다."""
    assert list(stdlib_inspect.signature(worker.record_schedule_result).parameters) == [
        "schedule_name",
        "outcome",
        "success",
    ]


async def test_schedule_run_timing_is_cleared_after_record(
    recording_env: _FakeCache, session_factory: sessionmaker[Session]
) -> None:
    async def task(_ctx: dict[str, Any]) -> dict[str, Any]:
        return {"status": "success"}

    await _record_schedule("nightly")(task)({})

    assert worker.schedule_run_timing.get() is None
