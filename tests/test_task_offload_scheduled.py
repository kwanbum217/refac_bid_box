"""tests/test_task_offload_scheduled.py

정기 태스크(nightly_schedule_task, development_data_refresh_task)의
동기 DB/집계 함수 오프로드 검증 테스트.

asyncio.to_thread 로 오프로드된 스레드에서는 실행 중인 이벤트 루프가 없어
asyncio.get_running_loop() 호출 시 RuntimeError 가 발생하는 성질을 이용해
이벤트 루프 스레드 블로킹 여부를 판정합니다.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.cache import RedisConnection
from src.app.core.config import settings
from src.tasks.scheduled_tasks import (
    development_data_refresh_task,
    nightly_schedule_task,
    set_schedule_redis_conn,
)
from tests.fake_redis import FakeRedisClient, FakeRedisConnection


class UnreachableRedisConnection(RedisConnection):
    """Redis 서버 미기동/연결 불가를 모의하는 대역 연결입니다."""

    def __init__(self, label: str = "test_unreachable") -> None:
        super().__init__(label=label)

    def client(self) -> Any:
        return None

    def invalidate(self, exc: Exception) -> None:
        pass


@pytest.fixture(autouse=True)
def isolate_schedule_redis():
    """모든 테스트에 격리된 FakeRedisConnection을 기본 제공하여 실제 Redis 부재 환경(CI 등)에서도 claim을 정상 획득하게 합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)
    yield fake_conn
    set_schedule_redis_conn(None)


def _assert_no_running_event_loop(func_name: str) -> None:
    """오프로드된 스레드에서 실행 중인지 검증합니다.

    이벤트 루프 스레드에서 직접 동기 호출되면 get_running_loop() 이 루프를 반환하여
    AssertionError 가 발생하고, asyncio.to_thread 로 오프로드된 스레드에서는
    RuntimeError 가 발생하여 통과합니다.
    """
    try:
        asyncio.get_running_loop()
        in_event_loop = True
    except RuntimeError:
        in_event_loop = False

    assert not in_event_loop, (
        f"{func_name} 함수가 이벤트 루프 스레드에서 직접 동기 실행되었습니다. "
        "asyncio.to_thread 로 오프로드되어야 합니다."
    )


@pytest.mark.asyncio
async def test_nightly_schedule_task_offloads_sync_functions():
    """nightly_schedule_task 에서 동기 함수 3종이 이벤트 루프 밖 스레드에서 실행되는지 검증."""
    call_log: list[str] = []

    def fake_create_execution(db, run_mode: str, trigger_name: str) -> str:
        _assert_no_running_event_loop("_create_scheduled_execution")
        call_log.append("_create_scheduled_execution")
        return "test-nightly-exec-123"

    def fake_rebuild_ranking() -> dict[str, int]:
        _assert_no_running_event_loop("_rebuild_ranking_snapshots")
        call_log.append("_rebuild_ranking_snapshots")
        return {"rows": 42, "scopes_with_corruption": 0}

    def fake_rebuild_institution() -> dict[str, int]:
        _assert_no_running_event_loop("_rebuild_institution_stats")
        call_log.append("_rebuild_institution_stats")
        return {"institutions": 15}

    async def fake_pipeline(ctx, **kwargs):
        return {"status": "success", "execution_id": kwargs.get("execution_id")}

    with (
        patch("src.tasks.scheduled_tasks.SessionLocal", return_value=MagicMock()),
        patch(
            "src.tasks.scheduled_tasks._create_scheduled_execution",
            side_effect=fake_create_execution,
        ),
        patch("src.tasks.scheduled_tasks.run_automation_pipeline", side_effect=fake_pipeline),
        patch(
            "src.tasks.scheduled_tasks._rebuild_ranking_snapshots", side_effect=fake_rebuild_ranking
        ),
        patch(
            "src.tasks.scheduled_tasks._rebuild_institution_stats",
            side_effect=fake_rebuild_institution,
        ),
        patch.object(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True),
    ):
        result = await nightly_schedule_task({})

    assert result["status"] == "success"
    assert result["execution_id"] == "test-nightly-exec-123"
    assert result["ranking_snapshots"] == {"rows": 42, "scopes_with_corruption": 0}
    assert result["institution_stats"] == {"institutions": 15}
    assert call_log == [
        "_create_scheduled_execution",
        "_rebuild_ranking_snapshots",
        "_rebuild_institution_stats",
    ]


@pytest.mark.asyncio
async def test_development_data_refresh_task_offloads_sync_functions():
    """development_data_refresh_task 에서 동기 함수 3종이 이벤트 루프 밖 스레드에서 실행되는지 검증."""
    call_log: list[str] = []

    def fake_create_execution(db, run_mode: str, trigger_name: str) -> str:
        _assert_no_running_event_loop("_create_scheduled_execution")
        call_log.append("_create_scheduled_execution")
        return "test-refresh-exec-456"

    def fake_rebuild_ranking() -> dict[str, int]:
        _assert_no_running_event_loop("_rebuild_ranking_snapshots")
        call_log.append("_rebuild_ranking_snapshots")
        return {"rows": 100, "scopes_with_corruption": 1}

    def fake_rebuild_institution() -> dict[str, int]:
        _assert_no_running_event_loop("_rebuild_institution_stats")
        call_log.append("_rebuild_institution_stats")
        return {"institutions": 20}

    async def fake_pipeline(ctx, **kwargs):
        return {"status": "success", "execution_id": kwargs.get("execution_id")}

    with (
        patch("src.tasks.scheduled_tasks.SessionLocal", return_value=MagicMock()),
        patch(
            "src.tasks.scheduled_tasks._create_scheduled_execution",
            side_effect=fake_create_execution,
        ),
        patch("src.tasks.scheduled_tasks.run_automation_pipeline", side_effect=fake_pipeline),
        patch(
            "src.tasks.scheduled_tasks._rebuild_ranking_snapshots", side_effect=fake_rebuild_ranking
        ),
        patch(
            "src.tasks.scheduled_tasks._rebuild_institution_stats",
            side_effect=fake_rebuild_institution,
        ),
        patch.object(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True),
        patch.object(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False),
    ):
        result = await development_data_refresh_task({})

    assert result["status"] == "success"
    assert result["execution_id"] == "test-refresh-exec-456"
    assert result["ranking_snapshots"] == {"rows": 100, "scopes_with_corruption": 1}
    assert result["institution_stats"] == {"institutions": 20}
    assert call_log == [
        "_create_scheduled_execution",
        "_rebuild_ranking_snapshots",
        "_rebuild_institution_stats",
    ]


@pytest.mark.asyncio
async def test_nightly_schedule_task_fails_closed_when_redis_unavailable():
    """Redis 부재 시 nightly_schedule_task 가 fail-closed 로 status='failed' 를 반환하고 오프로드 동기 함수를 호출하지 않는지 검증."""
    unreachable_conn = UnreachableRedisConnection()
    set_schedule_redis_conn(unreachable_conn)

    mock_create = MagicMock()
    mock_pipeline = AsyncMock()
    mock_ranking = MagicMock()
    mock_inst = MagicMock()

    with (
        patch("src.tasks.scheduled_tasks.SessionLocal", return_value=MagicMock()),
        patch("src.tasks.scheduled_tasks._create_scheduled_execution", mock_create),
        patch("src.tasks.scheduled_tasks.run_automation_pipeline", mock_pipeline),
        patch("src.tasks.scheduled_tasks._rebuild_ranking_snapshots", mock_ranking),
        patch("src.tasks.scheduled_tasks._rebuild_institution_stats", mock_inst),
        patch.object(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True),
    ):
        result = await nightly_schedule_task({})

    assert result["status"] == "failed"
    assert result["reason"] == "redis_unavailable"
    assert "claim" in result
    assert result["claim"]["acquired"] is False
    mock_create.assert_not_called()
    mock_pipeline.assert_not_called()
    mock_ranking.assert_not_called()
    mock_inst.assert_not_called()


@pytest.mark.asyncio
async def test_development_data_refresh_task_fails_closed_when_redis_unavailable():
    """Redis 부재 시 development_data_refresh_task 가 fail-closed 로 status='failed' 를 반환하고 오프로드 동기 함수를 호출하지 않는지 검증."""
    unreachable_conn = UnreachableRedisConnection()
    set_schedule_redis_conn(unreachable_conn)

    mock_create = MagicMock()
    mock_pipeline = AsyncMock()
    mock_ranking = MagicMock()
    mock_inst = MagicMock()

    with (
        patch("src.tasks.scheduled_tasks.SessionLocal", return_value=MagicMock()),
        patch("src.tasks.scheduled_tasks._create_scheduled_execution", mock_create),
        patch("src.tasks.scheduled_tasks.run_automation_pipeline", mock_pipeline),
        patch("src.tasks.scheduled_tasks._rebuild_ranking_snapshots", mock_ranking),
        patch("src.tasks.scheduled_tasks._rebuild_institution_stats", mock_inst),
        patch.object(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True),
        patch.object(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False),
    ):
        result = await development_data_refresh_task({})

    assert result["status"] == "failed"
    assert result["reason"] == "redis_unavailable"
    assert "claim" in result
    assert result["claim"]["acquired"] is False
    mock_create.assert_not_called()
    mock_pipeline.assert_not_called()
    mock_ranking.assert_not_called()
    mock_inst.assert_not_called()
