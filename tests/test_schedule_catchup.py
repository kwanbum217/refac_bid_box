"""
tests/test_schedule_catchup.py

기동 시 스케줄 따라잡기(catch-up) 검증 테스트.

검증 항목:
1. 설정 기본값 일치성 (비활성 기본값, 데이터 최신화 활성, 야간 비활성)
2. 비활성화 시 정상 스킵
3. 임계 시간(24시간) 미경과 시 정상 스킵
4. 임계 시간 초과 시 따라잡기 실행 및 기존 스케줄 경로 재사용
5. 쿨다운(6시간) 내 재시작 루프 방어
6. 워커 startup 비차단(non-blocking) 및 예외 격리
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.config import settings
from src.tasks import scheduled_tasks, worker
from src.tasks.scheduled_tasks import (
    check_schedule_catchup_needed,
    is_catchup_in_cooldown,
    record_catchup_attempt,
    run_schedule_catchup_task,
)


def test_catchup_defaults_and_env_consistency():
    """설정 기본값이 .env.example 및 docker-compose.yml 사양과 일치하는지 확인합니다."""
    # 따라잡기는 기본적으로 꺼져 있어야 합니다 (기동 시 과부하 방지).
    assert settings.AUTOMATION_SCHEDULE_CATCHUP_ENABLED is False
    assert settings.AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS == 24
    assert settings.AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS == 6

    # 개발 스택 기본 스케줄 정합성
    assert settings.AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED is True
    assert settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED is False


def test_catchup_skipped_when_disabled(monkeypatch):
    """AUTOMATION_SCHEDULE_CATCHUP_ENABLED 가 False 면 즉시 건너뜁니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", False)

    needed, reason, details = check_schedule_catchup_needed()
    assert needed is False
    assert reason == "disabled"
    assert details["enabled"] is False


@pytest.mark.asyncio
async def test_catchup_task_returns_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", False)

    result = await run_schedule_catchup_task({})
    assert result["status"] == "skipped"
    assert result["reason"] == "disabled"


def test_catchup_skipped_when_threshold_not_exceeded(monkeypatch):
    """마지막 수집 후 경과 시간이 임계(24시간) 미만이면 실행하지 않습니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS", 24)

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    # 5시간 전 수집
    recent_collected = now - timedelta(hours=5)

    with (
        patch.object(scheduled_tasks, "utcnow", return_value=now),
        patch.object(scheduled_tasks, "get_latest_collection_time", return_value=recent_collected),
        patch.object(scheduled_tasks, "is_catchup_in_cooldown", return_value=(False, None)),
    ):
        needed, reason, details = check_schedule_catchup_needed()
        assert needed is False
        assert reason == "threshold_not_exceeded"
        assert details["elapsed_hours"] == 5.0
        assert details["threshold_hours"] == 24


def test_catchup_needed_when_threshold_exceeded(monkeypatch):
    """마지막 수집 후 경과 시간이 임계(24시간) 이상이면 따라잡기를 발화합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS", 24)
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    # 30시간 전 수집 (임계 초과)
    old_collected = now - timedelta(hours=30)

    with (
        patch.object(scheduled_tasks, "utcnow", return_value=now),
        patch.object(scheduled_tasks, "get_latest_collection_time", return_value=old_collected),
        patch.object(scheduled_tasks, "is_catchup_in_cooldown", return_value=(False, None)),
    ):
        needed, reason, details = check_schedule_catchup_needed()
        assert needed is True
        assert reason == "threshold_exceeded"
        assert details["elapsed_hours"] == 30.0
        assert details["target_task"] == "development_data_refresh"


def test_catchup_needed_when_no_previous_collection(monkeypatch):
    """공고 수집 이력이 전혀 없는 경우 즉시 따라잡기를 발화합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS", 24)

    with (
        patch.object(scheduled_tasks, "get_latest_collection_time", return_value=None),
        patch.object(scheduled_tasks, "is_catchup_in_cooldown", return_value=(False, None)),
    ):
        needed, reason, details = check_schedule_catchup_needed()
        assert needed is True
        assert reason == "no_previous_collection"
        assert details["latest_collected_at"] is None


def test_catchup_skipped_when_in_cooldown(monkeypatch):
    """임계를 초과했더라도 최근 쿨다운(6시간) 내에 시도한 기록이 있으면 반복을 방지합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS", 24)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS", 6)

    last_attempt_iso = "2026-09-03T11:00:00+00:00"

    with patch.object(
        scheduled_tasks, "is_catchup_in_cooldown", return_value=(True, last_attempt_iso)
    ):
        needed, reason, details = check_schedule_catchup_needed()
        assert needed is False
        assert reason == "in_cooldown"
        assert details["last_attempt"] == last_attempt_iso
        assert details["cooldown_hours"] == 6


@pytest.mark.asyncio
async def test_catchup_uses_existing_development_refresh_path(monkeypatch):
    """따라잡기는 새 수집 로직을 만들지 않고 development_data_refresh_task 를 재사용합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    old_collected = now - timedelta(hours=48)

    mock_refresh = AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]})
    mock_nightly = AsyncMock()

    with (
        patch.object(scheduled_tasks, "utcnow", return_value=now),
        patch.object(scheduled_tasks, "get_latest_collection_time", return_value=old_collected),
        patch.object(scheduled_tasks, "is_catchup_in_cooldown", return_value=(False, None)),
        patch.object(scheduled_tasks, "record_catchup_attempt") as mock_record_attempt,
        patch.object(scheduled_tasks, "development_data_refresh_task", mock_refresh),
        patch.object(scheduled_tasks, "nightly_schedule_task", mock_nightly),
    ):
        ctx: dict[str, Any] = {}
        outcome = await run_schedule_catchup_task(ctx)

    assert outcome["status"] == "success"
    mock_refresh.assert_awaited_once_with(ctx)
    mock_nightly.assert_not_awaited()
    mock_record_attempt.assert_called_once()
    assert outcome["catchup_details"]["target_task"] == "development_data_refresh"


@pytest.mark.asyncio
async def test_catchup_uses_existing_nightly_path_when_nightly_enabled(monkeypatch):
    """운영 야간 스케줄이 활성화된 경우 nightly_schedule_task 를 재사용합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", False)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True)

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    old_collected = now - timedelta(hours=48)

    mock_nightly = AsyncMock(return_value={"status": "success", "steps": ["all"]})
    mock_refresh = AsyncMock()

    with (
        patch.object(scheduled_tasks, "utcnow", return_value=now),
        patch.object(scheduled_tasks, "get_latest_collection_time", return_value=old_collected),
        patch.object(scheduled_tasks, "is_catchup_in_cooldown", return_value=(False, None)),
        patch.object(scheduled_tasks, "record_catchup_attempt") as mock_record_attempt,
        patch.object(scheduled_tasks, "nightly_schedule_task", mock_nightly),
        patch.object(scheduled_tasks, "development_data_refresh_task", mock_refresh),
    ):
        ctx: dict[str, Any] = {}
        outcome = await run_schedule_catchup_task(ctx)

    assert outcome["status"] == "success"
    mock_nightly.assert_awaited_once_with(ctx)
    mock_refresh.assert_not_awaited()
    mock_record_attempt.assert_called_once()
    assert outcome["catchup_details"]["target_task"] == "nightly_schedule"


@pytest.mark.asyncio
async def test_catchup_handles_failure_and_prevents_restart_loop(monkeypatch):
    """따라잡기 실행 중 예외가 발생해도 상태를 failed 로 반환하고, 시도 기록은 유지됩니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)

    mock_refresh = AsyncMock(side_effect=RuntimeError("G2B 통신 장애"))

    with (
        patch.object(
            scheduled_tasks,
            "check_schedule_catchup_needed",
            return_value=(
                True,
                "threshold_exceeded",
                {"target_task": "development_data_refresh", "elapsed_hours": 30.0},
            ),
        ),
        patch.object(scheduled_tasks, "record_catchup_attempt") as mock_record_attempt,
        patch.object(scheduled_tasks, "development_data_refresh_task", mock_refresh),
    ):
        outcome = await run_schedule_catchup_task({})

    assert outcome["status"] == "failed"
    assert outcome["reason"] == "execution_failed"
    assert "G2B 통신 장애" in outcome["error"]
    # 실패했더라도 시도 기록이 선제 저장되어 즉시 재시작 루프에 걸리지 않음
    mock_record_attempt.assert_called_once()


@pytest.mark.asyncio
async def test_worker_startup_spawns_catchup_in_background(monkeypatch):
    """워커 기동 시 따라잡기를 동기로 블로킹하지 않고 백그라운드 태스크로 띄웁니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "OTEL_ENABLED", False)

    mock_catchup_run = AsyncMock()
    ctx: dict[str, Any] = {}

    with (
        patch.object(worker, "run_schedule_catchup_task", mock_catchup_run),
        patch.object(worker, "record_worker_heartbeat"),
    ):
        await worker._on_startup(ctx)

        # 백그라운드 태스크가 등록되었는지 확인
        assert "schedule_catchup_task" in ctx
        assert isinstance(ctx["schedule_catchup_task"], asyncio.Task)
        assert not ctx["schedule_catchup_task"].done()

        # shutdown 시 정상 취소/회수되는지 확인
        await worker._on_shutdown(ctx)
        assert "schedule_catchup_task" not in ctx

    # 테스트 루프 정리
    await asyncio.sleep(0.01)


def test_cooldown_cache_roundtrip(monkeypatch):
    """CacheLayer 모의 환경에서 쿨다운 판정이 정상 동작하는지 확인합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS", 6)

    fake_cache_storage: dict[str, Any] = {}

    class FakeCache:
        def get(self, key: str):
            return fake_cache_storage.get(key)

        def set(self, key: str, value: Any, ttl: int):
            fake_cache_storage[key] = value

    now = datetime(2026, 9, 3, 15, 0, 0, tzinfo=UTC)

    with (
        patch("src.app.core.cache.CacheLayer", return_value=FakeCache()),
        patch.object(scheduled_tasks, "utcnow", return_value=now),
    ):
        # 1. 초기 상태: 쿨다운 아님
        in_cd, attempt = is_catchup_in_cooldown()
        assert in_cd is False
        assert attempt is None

        # 2. 1시간 전 시도 기록
        record_catchup_attempt(now - timedelta(hours=1))
        in_cd, attempt = is_catchup_in_cooldown()
        assert in_cd is True
        assert attempt == (now - timedelta(hours=1)).isoformat()

        # 3. 7시간 전 시도 기록 (쿨다운 6시간 경과)
        record_catchup_attempt(now - timedelta(hours=7))
        in_cd, attempt = is_catchup_in_cooldown()
        assert in_cd is False
