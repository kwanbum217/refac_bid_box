"""
tests/test_schedule_catchup.py

기동 시 스케줄 따라잡기(catch-up) 및 공통 Redis 원자 claim 검증 테스트.

검증 항목:
1. 설정 기본값 일치성 (비활성 기본값, 데이터 최신화 활성, 야간 비활성)
2. 비활성화 시 정상 스킵
3. 임계 시간(24시간) 미경과 시 정상 스킵
4. 임계 시간 초과 시 따라잡기 실행 및 기존 스케줄 경로 재사용
5. 쿨다운(6시간) 내 재시작 루프 방어
6. 워커 startup 비차단(non-blocking) 및 예외 격리
7. Redis SET NX EX 기반 공통 원자 claim 획득 (ACQUIRED)
8. 이미 claim된 경우 단일 실행 보장 (ALREADY_CLAIMED) 및 파이프라인/집계 미호출
9. Redis 미가용 시 fail-closed 정책 (REDIS_UNAVAILABLE) 및 파이프라인 미호출
10. Redis 명령 오류 시 fail-closed 정책 (COMMAND_ERROR) 및 파이프라인 미호출
11. 정규 cron 2종(nightly, refresh)과 catch-up의 동일 claim 키 공유 및 상호 배타성
12. catch-up의 기존 경로 재사용 시 자기 충돌(self-collision) 방지
"""

from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.cache import RedisConnection
from src.app.core.config import settings
from src.tasks import scheduled_tasks, worker
from src.tasks.scheduled_tasks import (
    SCHEDULE_COLLECTION_CLAIM_KEY,
    ScheduleClaimStatus,
    acquire_schedule_claim,
    check_schedule_catchup_needed,
    development_data_refresh_task,
    is_catchup_in_cooldown,
    nightly_schedule_task,
    record_catchup_attempt,
    release_schedule_claim,
    run_schedule_catchup_task,
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


class ErrorRedisClient:
    """Redis 명령 실행 중 예외(네트워크 순단 등)를 발생시키는 모의 클라이언트입니다."""

    def set(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Redis I/O error")

    def get(self, *args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("Redis I/O error")

    def delete(self, *args: Any, **kwargs: Any) -> int:
        raise RuntimeError("Redis I/O error")


@pytest.fixture(autouse=True)
def isolate_schedule_redis():
    """모든 테스트에 격리된 FakeRedisConnection 을 기본 제공하여 실제 Redis 와의 결합 및 테스트 순서 의존성을 방지합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)
    yield fake_conn
    set_schedule_redis_conn(None)


def test_catchup_defaults_and_env_consistency():
    """설정 기본값이 .env.example 및 docker-compose.yml 사양과 일치하는지 확인합니다."""
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
    """따라잡기는 새 수집 로직이나 중복 claim을 만들지 않고 development_data_refresh_task 를 재사용합니다."""
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
        patch.object(scheduled_tasks, "development_data_refresh_task", mock_refresh),
        patch.object(scheduled_tasks, "nightly_schedule_task", mock_nightly),
    ):
        ctx: dict[str, Any] = {}
        outcome = await run_schedule_catchup_task(ctx)

    assert outcome["status"] == "success"
    mock_refresh.assert_awaited_once_with(ctx)
    mock_nightly.assert_not_awaited()
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
        patch.object(scheduled_tasks, "nightly_schedule_task", mock_nightly),
        patch.object(scheduled_tasks, "development_data_refresh_task", mock_refresh),
    ):
        ctx: dict[str, Any] = {}
        outcome = await run_schedule_catchup_task(ctx)

    assert outcome["status"] == "success"
    mock_nightly.assert_awaited_once_with(ctx)
    mock_refresh.assert_not_awaited()
    assert outcome["catchup_details"]["target_task"] == "nightly_schedule"


@pytest.mark.asyncio
async def test_catchup_handles_failure_and_prevents_restart_loop(monkeypatch):
    """따라잡기 실행 중 예외가 발생해도 상태를 failed 로 반환합니다."""
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
        patch.object(scheduled_tasks, "development_data_refresh_task", mock_refresh),
    ):
        outcome = await run_schedule_catchup_task({})

    assert outcome["status"] == "failed"
    assert outcome["reason"] == "execution_failed"
    assert "G2B 통신 장애" in outcome["error"]


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


# --------------------------------------------------------------------------- #
# 원자적 Redis claim 핵심 사양 검증 (SET NX EX, fail-closed, 공유 락, 충돌 방지)
# --------------------------------------------------------------------------- #


def test_acquire_schedule_claim_atomic_set_nx_ex():
    """claim 획득이 Redis SET NX EX 한 번으로 원자적으로 수행되는지 검증합니다."""
    fake_client = FakeRedisClient()
    fake_conn = FakeRedisConnection(fake_client)

    claim = acquire_schedule_claim("test_worker", ttl_seconds=3600, conn=fake_conn)
    assert claim.status == ScheduleClaimStatus.ACQUIRED
    assert claim.acquired is True
    assert claim.key == SCHEDULE_COLLECTION_CLAIM_KEY
    assert SCHEDULE_COLLECTION_CLAIM_KEY in fake_client._store

    # 동일 키 재시도 시 원자적으로 거부됨 (ALREADY_CLAIMED)
    second_claim = acquire_schedule_claim("test_worker_2", ttl_seconds=3600, conn=fake_conn)
    assert second_claim.status == ScheduleClaimStatus.ALREADY_CLAIMED
    assert second_claim.acquired is False


def test_acquire_schedule_claim_redis_unavailable_fails_closed():
    """Redis 연결 불가 시 fail-closed 로 처리하여 작업을 불허함을 검증합니다."""
    unreachable_conn = UnreachableRedisConnection()

    claim = acquire_schedule_claim("test_worker", conn=unreachable_conn)
    assert claim.status == ScheduleClaimStatus.REDIS_UNAVAILABLE
    assert claim.acquired is False
    assert "Redis 연결이 불가능하여" in claim.detail


def test_acquire_schedule_claim_command_error_fails_closed():
    """Redis 명령 실행 중 예외 발생 시 fail-closed 로 거부하고 연결을 폐기함을 검증합니다."""
    fake_conn = FakeRedisConnection(ErrorRedisClient())

    with patch.object(fake_conn, "invalidate") as mock_invalidate:
        claim = acquire_schedule_claim("test_worker", conn=fake_conn)
        assert claim.status == ScheduleClaimStatus.COMMAND_ERROR
        assert claim.acquired is False
        assert "Redis claim 명령 실행 중 오류" in claim.detail
        mock_invalidate.assert_called_once()


@pytest.mark.asyncio
async def test_nightly_and_refresh_share_same_claim_key(isolated_db, monkeypatch):
    """정규 수집 cron 2종이 동일한 claim 키를 공유하여 상호 배타적으로 실행됨을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    session_factory = lambda: isolated_db  # noqa: E731
    isolated_db.close = lambda: None

    mock_pipeline = AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]})

    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)

    with (
        patch.object(scheduled_tasks, "SessionLocal", session_factory),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
        patch.object(
            scheduled_tasks, "_rebuild_ranking_snapshots", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_rebuild_institution_stats", return_value={"status": "success"}
        ),
    ):
        # 1. 수동으로 claim 키를 선점 (다른 프로세스 또는 선행 스케줄이 실행 중임을 모의)
        pre_claim = acquire_schedule_claim("pre_existing_runner", conn=fake_conn)
        assert pre_claim.acquired is True

        # 2. nightly_schedule_task 실행 시 claim 획득 실패로 즉시 건너뜀 (파이프라인 미호출)
        nightly_res = await nightly_schedule_task({})
        assert nightly_res["status"] == "skipped"
        assert nightly_res["reason"] == "already_claimed"
        mock_pipeline.assert_not_awaited()

        # 3. development_data_refresh_task 실행 시도 역시 동일한 키 충돌로 즉시 건너뜀
        # (nightly 설정과 무관하게 claim 단계 검증을 위해 bypass monkeypatch)
        monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)
        refresh_res = await development_data_refresh_task({})
        assert refresh_res["status"] == "skipped"
        assert refresh_res["reason"] == "already_claimed"
        mock_pipeline.assert_not_awaited()


@pytest.mark.asyncio
async def test_nightly_aborts_pipeline_when_redis_unavailable(isolated_db, monkeypatch):
    """Redis 장애 시 nightly_schedule_task 가 fail-closed 로 종료되고 최상위 error 계약을 유지하며 파이프라인을 실행하지 않음을 검증합니다."""
    unreachable_conn = UnreachableRedisConnection()
    set_schedule_redis_conn(unreachable_conn)

    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True)
    mock_pipeline = AsyncMock()

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
    ):
        isolated_db.close = lambda: None
        result = await nightly_schedule_task({})

    assert result["status"] == "failed"
    assert result["reason"] == "redis_unavailable"
    assert result["error"] == result["claim"]["detail"]
    assert "Redis 연결이 불가능하여" in result["error"]
    assert isinstance(result["claim"], dict)
    assert result["claim"]["acquired"] is False
    mock_pipeline.assert_not_awaited()


@pytest.mark.asyncio
async def test_nightly_aborts_pipeline_on_command_error(isolated_db, monkeypatch):
    """Redis 명령 예외 시 nightly_schedule_task 가 fail-closed 로 종료되고 최상위 error 계약을 유지하며 파이프라인을 실행하지 않음을 검증합니다."""
    fake_conn = FakeRedisConnection(ErrorRedisClient())
    set_schedule_redis_conn(fake_conn)

    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True)
    mock_pipeline = AsyncMock()

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
    ):
        isolated_db.close = lambda: None
        result = await nightly_schedule_task({})

    assert result["status"] == "failed"
    assert result["reason"] == "command_error"
    assert result["error"] == result["claim"]["detail"]
    assert "Redis claim 명령 실행 중 오류" in result["error"]
    assert isinstance(result["claim"], dict)
    assert result["claim"]["acquired"] is False
    mock_pipeline.assert_not_awaited()


@pytest.mark.asyncio
async def test_development_refresh_aborts_pipeline_when_redis_unavailable(isolated_db, monkeypatch):
    """Redis 장애 시 development_data_refresh_task 가 fail-closed 로 종료되고 최상위 error 계약을 유지하며 파이프라인을 실행하지 않음을 검증합니다."""
    unreachable_conn = UnreachableRedisConnection()
    set_schedule_redis_conn(unreachable_conn)

    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)
    mock_pipeline = AsyncMock()

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
    ):
        isolated_db.close = lambda: None
        result = await development_data_refresh_task({})

    assert result["status"] == "failed"
    assert result["reason"] == "redis_unavailable"
    assert result["error"] == result["claim"]["detail"]
    assert "Redis 연결이 불가능하여" in result["error"]
    assert isinstance(result["claim"], dict)
    assert result["claim"]["acquired"] is False
    mock_pipeline.assert_not_awaited()


@pytest.mark.asyncio
async def test_development_refresh_aborts_pipeline_on_command_error(isolated_db, monkeypatch):
    """Redis 명령 예외 시 development_data_refresh_task 가 fail-closed 로 종료되고 최상위 error 계약을 유지하며 파이프라인을 실행하지 않음을 검증합니다."""
    fake_conn = FakeRedisConnection(ErrorRedisClient())
    set_schedule_redis_conn(fake_conn)

    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)
    mock_pipeline = AsyncMock()

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
    ):
        isolated_db.close = lambda: None
        result = await development_data_refresh_task({})

    assert result["status"] == "failed"
    assert result["reason"] == "command_error"
    assert result["error"] == result["claim"]["detail"]
    assert "Redis claim 명령 실행 중 오류" in result["error"]
    assert isinstance(result["claim"], dict)
    assert result["claim"]["acquired"] is False
    mock_pipeline.assert_not_awaited()


def test_acquire_schedule_claim_log_does_not_expose_token(caplog):
    """claim 성공 시 INFO 로그에 소유 토큰 원문이 노출되지 않고 owner, key, ttl 만 기록됨을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    with caplog.at_level(logging.INFO, logger="src.tasks.scheduled_tasks"):
        claim = acquire_schedule_claim("secure_test_owner", ttl_seconds=180, conn=fake_conn)

    assert claim.acquired is True
    assert claim.token is not None
    # 1. 반환된 토큰 원문이 로그 전체에 전혀 나타나지 않음을 확인
    assert claim.token not in caplog.text
    # 2. owner, key, ttl 은 정상 기록됨을 확인
    assert "secure_test_owner" in caplog.text
    assert SCHEDULE_COLLECTION_CLAIM_KEY in caplog.text
    assert "180초" in caplog.text


@pytest.mark.asyncio
async def test_catchup_does_not_self_collide_with_target_task(isolated_db, monkeypatch):
    """따라잡기가 타겟 태스크를 호출할 때 외부에서 중복 claim을 걸어 자기 충돌(self-collision)을 일으키지 않음을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)

    now = datetime(2026, 9, 3, 12, 0, 0, tzinfo=UTC)
    old_collected = now - timedelta(hours=48)

    mock_pipeline = AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]})

    with (
        patch.object(scheduled_tasks, "utcnow", return_value=now),
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "get_latest_collection_time", return_value=old_collected),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
        patch.object(
            scheduled_tasks, "_rebuild_ranking_snapshots", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_rebuild_institution_stats", return_value={"status": "success"}
        ),
    ):
        isolated_db.close = lambda: None
        outcome = await run_schedule_catchup_task({})

    assert outcome["status"] == "success"
    mock_pipeline.assert_awaited_once()


def test_cooldown_via_claim_roundtrip():
    """RedisConnection 기반에서 is_catchup_in_cooldown 및 record_catchup_attempt 가 정상 동작함을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    now = datetime(2026, 9, 3, 15, 0, 0, tzinfo=UTC)

    with patch.object(scheduled_tasks, "utcnow", return_value=now):
        # 1. 초기 상태: claim 없음 -> 쿨다운 아님
        in_cd, attempt = is_catchup_in_cooldown(conn=fake_conn)
        assert in_cd is False
        assert attempt is None

        # 2. claim 시도 및 성공
        claim = record_catchup_attempt(now, conn=fake_conn)
        assert claim.status == ScheduleClaimStatus.ACQUIRED

        # 3. 쿨다운 확인: claim 존재 -> 쿨다운 상태
        in_cd, attempt = is_catchup_in_cooldown(conn=fake_conn)
        assert in_cd is True
        assert attempt == now.isoformat()

        # 4. 해제 시 정상적으로 쿨다운 해제됨
        assert claim.token is not None
        released = release_schedule_claim(token=claim.token, conn=fake_conn)
        assert released is True
        in_cd, attempt = is_catchup_in_cooldown(conn=fake_conn)
        assert in_cd is False


def test_release_schedule_claim_atomic_ownership():
    """소유 토큰 일치 여부에 따른 원자적 해제 및 불일치 시 보존을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    # 1. claim 획득
    claim = acquire_schedule_claim("runner_1", conn=fake_conn)
    assert claim.acquired is True
    assert claim.token is not None

    # 2. 토큰 없이 해제 시도 -> 실패 및 키 유지
    assert release_schedule_claim(token=None, conn=fake_conn) is False
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is True

    # 3. 잘못된 토큰으로 해제 시도 -> 실패 및 키 유지
    assert release_schedule_claim(token="wrong_token_hex", conn=fake_conn) is False
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is True

    # 4. 올바른 토큰으로 해제 시도 -> 성공 및 키 삭제
    assert release_schedule_claim(token=claim.token, conn=fake_conn) is True
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is False

    # 5. 이미 삭제된 키에 대해 재해제 시도 -> False
    assert release_schedule_claim(token=claim.token, conn=fake_conn) is False


def test_stale_owner_cannot_release_subsequent_claim():
    """이전 실행(stale owner)이 TTL 경과 후 생성된 후속 실행의 새 claim을 삭제하지 못함을 검증합니다."""
    fake_client = FakeRedisClient()
    fake_conn = FakeRedisConnection(fake_client)
    set_schedule_redis_conn(fake_conn)

    # 1. 첫 번째 실행 A 가 claim 획득
    claim_a = acquire_schedule_claim("stale_runner_a", conn=fake_conn)
    assert claim_a.acquired is True
    token_a = claim_a.token
    assert token_a is not None

    # 2. TTL 만료로 키가 삭제되고 새 실행 B 가 claim 획득한 상황 모의
    fake_client.delete(SCHEDULE_COLLECTION_CLAIM_KEY)
    claim_b = acquire_schedule_claim("fresh_runner_b", conn=fake_conn)
    assert claim_b.acquired is True
    token_b = claim_b.token
    assert token_b is not None
    assert token_a != token_b

    # 3. 뒤늦게 종료된 실행 A 가 이전 token_a 로 해제를 시도
    released_a = release_schedule_claim(token=token_a, conn=fake_conn)
    assert released_a is False

    # 4. 실행 B 의 claim 이 삭제되지 않고 온전히 보존되어 있음을 확인
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is True
    raw_data = fake_client.get(SCHEDULE_COLLECTION_CLAIM_KEY)
    import json

    data = json.loads(raw_data)
    assert data["token"] == token_b
    assert data["owner"] == "fresh_runner_b"

    # 5. 오직 실행 B 만이 자기 토큰으로 해제 가능
    released_b = release_schedule_claim(token=token_b, conn=fake_conn)
    assert released_b is True
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is False


@pytest.mark.asyncio
async def test_nightly_retains_claim_on_pipeline_failure_dict(isolated_db, monkeypatch):
    """nightly_schedule_task 가 예외 없는 failure dict 반환 시 claim을 유지하여 후속 실행을 차단함을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True)
    mock_pipeline = AsyncMock(
        return_value={"status": "failed", "error": "External API timeout", "step": "collect"}
    )

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
    ):
        isolated_db.close = lambda: None
        result = await nightly_schedule_task({})

    # 1. 실패 dict 반환 확인
    assert result["status"] == "failed"
    assert result["error"] == "External API timeout"

    # 2. claim 이 해제되지 않고 쿨다운이 유지되는지 확인
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is True

    # 3. 직후 재실행 시 already_claimed 로 실행 차단됨을 확인
    second_result = await nightly_schedule_task({})
    assert second_result["status"] == "skipped"
    assert second_result["reason"] == "already_claimed"
    # 파이프라인이 두 번째 호출에서는 실행되지 않았어야 함
    mock_pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_development_refresh_retains_claim_on_pipeline_failure_dict(isolated_db, monkeypatch):
    """development_data_refresh_task 가 예외 없는 failure dict 반환 시 claim을 유지하여 후속 실행을 차단함을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)
    mock_pipeline = AsyncMock(
        return_value={"status": "failed", "error": "DB connection dropped", "step": "collect"}
    )

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
    ):
        isolated_db.close = lambda: None
        result = await development_data_refresh_task({})

    assert result["status"] == "failed"
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is True

    # 후속 재실행 차단
    second_result = await development_data_refresh_task({})
    assert second_result["status"] == "skipped"
    assert second_result["reason"] == "already_claimed"
    mock_pipeline.assert_awaited_once()


@pytest.mark.asyncio
async def test_nightly_retains_claim_on_partial_failure(isolated_db, monkeypatch):
    """후속 집계 실패로 partial_success 가 된 경우에도 claim을 유지함을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True)
    mock_pipeline = AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]})

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
        patch.object(
            scheduled_tasks, "_rebuild_ranking_snapshots", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks,
            "_rebuild_institution_stats",
            return_value={"status": "failed", "error": "calc error"},
        ),
    ):
        isolated_db.close = lambda: None
        result = await nightly_schedule_task({})

    assert result["status"] == "partial_success"
    assert "institution_stats" in result["failed_followups"]

    # claim 이 해제되지 않고 유지됨
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is True

    # 후속 실행 시 already_claimed 로 차단
    second_result = await nightly_schedule_task({})
    assert second_result["status"] == "skipped"
    assert second_result["reason"] == "already_claimed"


@pytest.mark.asyncio
async def test_nightly_releases_claim_on_success(isolated_db, monkeypatch):
    """nightly_schedule_task 가 성공(success)한 경우 자기 토큰으로 정상 해제되어 후속 실행이 가능함을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True)
    mock_pipeline = AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]})

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
        patch.object(
            scheduled_tasks, "_rebuild_ranking_snapshots", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_rebuild_institution_stats", return_value={"status": "success"}
        ),
    ):
        isolated_db.close = lambda: None
        result = await nightly_schedule_task({})

    assert result["status"] == "success"
    # claim 이 정상 해제되어 쿨다운이 아님
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is False


@pytest.mark.asyncio
async def test_development_refresh_releases_claim_on_success(isolated_db, monkeypatch):
    """development_data_refresh_task 가 성공(success)한 경우 자기 토큰으로 정상 해제되어 후속 실행이 가능함을 검증합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)
    mock_pipeline = AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]})

    with (
        patch.object(scheduled_tasks, "SessionLocal", lambda: isolated_db),
        patch.object(scheduled_tasks, "run_automation_pipeline", mock_pipeline),
        patch.object(
            scheduled_tasks, "_rebuild_ranking_snapshots", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_rebuild_institution_stats", return_value={"status": "success"}
        ),
    ):
        isolated_db.close = lambda: None
        result = await development_data_refresh_task({})

    assert result["status"] == "success"
    in_cd, _ = is_catchup_in_cooldown(conn=fake_conn)
    assert in_cd is False
