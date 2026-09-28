"""
tests/test_monitor_catchup.py

기동 따라잡기의 PSI 드리프트 감시(매일 04:00)와 낙찰결과 커버리지 감시(월요일 05:00)
판정·실행·적재 검증.

검증 항목:
1. 드리프트 슬롯 이후 이력 유무에 따른 판정(이후/이전/이력 없음)
2. 다음 04:00 슬롯 1시간 이내 양보 및 설정 비활성 건너뜀
3. 커버리지 Redis 스케줄 기록 이후/이전/없음/읽기 실패 판정
4. 다음 월요일 05:00 슬롯 1시간 이내 양보
5. 두 원 태스크의 공통 선점: already_running 본문 미실행, 자기 토큰만 해제
6. 따라잡기 실행 태스크가 판정 True 일 때만 원 태스크 호출
7. run_schedule_catchup_task 가 세 따라잡기를 적재하고 하나가 실패해도 나머지를 적재
8. 커버리지 태스크 실행 후 Redis 스케줄 상태 기록
9. worker 등록 및 1시간 타임아웃 확인
10. 타임존 명시 주입으로 TZ=UTC 에서도 결정적
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.app.core.cache import CacheLayer
from src.app.core.config import settings
from src.app.models.predictions import RetrainLog
from src.tasks import coverage_tasks, scheduled_tasks, worker
from src.tasks.scheduled_tasks import (
    DRIFT_MONITOR_CATCHUP_JOB_ID,
    DRIFT_MONITOR_CATCHUP_JOB_NAME,
    DRIFT_MONITOR_CLAIM_KEY,
    RESULT_COVERAGE_CATCHUP_JOB_ID,
    RESULT_COVERAGE_CATCHUP_JOB_NAME,
    RESULT_COVERAGE_CLAIM_KEY,
    WEEKLY_RETRAIN_CATCHUP_JOB_ID,
    WEEKLY_RETRAIN_CATCHUP_JOB_NAME,
    ScheduleClaimResult,
    ScheduleClaimStatus,
    check_drift_monitor_catchup_needed,
    check_result_coverage_catchup_needed,
    get_latest_drift_monitor_time,
    run_drift_monitor_catchup_task,
    run_result_coverage_catchup_task,
    run_schedule_catchup_task,
    set_schedule_redis_conn,
)
from tests.fake_redis import FakeRedisClient, FakeRedisConnection

SEOUL = ZoneInfo("Asia/Seoul")

# 2026-09-28 09:20 KST. 직전 매일 04:00 슬롯은 2026-09-27 19:00 UTC,
# 직전 월요일 05:00 슬롯은 2026-09-27 20:00 UTC 다.
MONDAY_0920_KST = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)


class FakeArqRedis:
    """arq ctx['redis'] 대역. enqueue_job 호출만 기록합니다."""

    def __init__(self, side_effect: Exception | None = None, return_value: Any = "job") -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._side_effect = side_effect
        self._return_value = return_value

    async def enqueue_job(self, name: str, **kwargs: Any) -> Any:
        self.calls.append((name, kwargs))
        if self._side_effect is not None:
            raise self._side_effect
        return self._return_value


class StatusStoreClient:
    """CacheLayer 가 쓰는 setex/get 만 지원하는 스케줄 상태 기록 대역입니다."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    def setex(self, key: str, ttl: int, value: str) -> bool:
        self.store[key] = value
        return True

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, *keys: str) -> int:
        return sum(1 for key in keys if self.store.pop(key, None) is not None)

    def ping(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def isolate_schedule_redis():
    """모든 테스트에 격리된 FakeRedisConnection 을 제공하여 실제 Redis 결합을 방지합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)
    yield fake_conn
    set_schedule_redis_conn(None)


def _enable_drift_catchup(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", True)


# --------------------------------------------------------------------------- #
# 드리프트 감시 판정
# --------------------------------------------------------------------------- #


def test_drift_needed_when_missed_slot(monkeypatch):
    """마지막 04:00 슬롯 이전에만 이력이 있으면 놓친 슬롯을 보충합니다."""
    _enable_drift_catchup(monkeypatch)
    last_run = datetime(2026, 9, 27, 3, 11, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_drift_monitor_time", return_value=last_run):
        needed, reason, details = check_drift_monitor_catchup_needed(now=MONDAY_0920_KST, tz=SEOUL)

    assert needed is True
    assert reason == "missed_drift_monitor"
    assert details["last_drift_slot"] == "2026-09-27T19:00:00+00:00"
    assert details["latest_drift_monitor_at"] == last_run.isoformat()


def test_drift_up_to_date_when_after_slot(monkeypatch):
    """마지막 04:00 슬롯 이후 이력이 있으면 건너뜁니다."""
    _enable_drift_catchup(monkeypatch)
    last_run = datetime(2026, 9, 27, 20, 0, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_drift_monitor_time", return_value=last_run):
        needed, reason, _details = check_drift_monitor_catchup_needed(now=MONDAY_0920_KST, tz=SEOUL)

    assert needed is False
    assert reason == "drift_monitor_up_to_date"


def test_drift_needed_when_no_history(monkeypatch):
    """이력이 전혀 없으면 따라잡기를 실행합니다."""
    _enable_drift_catchup(monkeypatch)
    with patch.object(scheduled_tasks, "get_latest_drift_monitor_time", return_value=None):
        needed, reason, details = check_drift_monitor_catchup_needed(now=MONDAY_0920_KST, tz=SEOUL)

    assert needed is True
    assert reason == "no_previous_drift_monitor"
    assert details["latest_drift_monitor_at"] is None


def test_drift_yields_when_next_slot_imminent(monkeypatch):
    """2026-09-28 03:30 KST 기동은 다음 04:00 슬롯이 30분 뒤라 크론에 양보합니다."""
    _enable_drift_catchup(monkeypatch)
    now = datetime(2026, 9, 27, 18, 30, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_drift_monitor_time", return_value=None):
        needed, reason, details = check_drift_monitor_catchup_needed(now=now, tz=SEOUL)

    assert needed is False
    assert reason == "next_drift_slot_imminent"
    assert details["next_slot"] == "2026-09-27T19:00:00+00:00"


@pytest.mark.parametrize(
    ("catchup_enabled", "drift_enabled"),
    [(False, True), (True, False)],
)
def test_drift_skipped_when_disabled(monkeypatch, catchup_enabled, drift_enabled):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", catchup_enabled)
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", drift_enabled)
    with patch.object(scheduled_tasks, "get_latest_drift_monitor_time", return_value=None):
        needed, reason, details = check_drift_monitor_catchup_needed(now=MONDAY_0920_KST, tz=SEOUL)

    assert needed is False
    assert reason == "disabled"
    assert details["enabled"] is False


def test_get_latest_drift_monitor_time_filters_trigger_source(isolated_db):
    """trigger_source='drift_monitor' 행만 드리프트 이력으로 집계합니다."""
    isolated_db.add_all(
        [
            RetrainLog(
                trigger_source="drift_monitor",
                champion_version="champ",
                challenger_version="baseline-1",
                status="STABLE",
                created_at=datetime(2026, 9, 21, 0, 0, 0),
            ),
            RetrainLog(
                trigger_source="weekly_schedule",
                champion_version="champ",
                challenger_version="weekly-1",
                status="success",
                created_at=datetime(2026, 9, 27, 0, 0, 0),
            ),
        ]
    )
    isolated_db.commit()

    assert get_latest_drift_monitor_time(isolated_db) == datetime(2026, 9, 21, 0, 0, 0)


# --------------------------------------------------------------------------- #
# 커버리지 감시 판정 (Redis 스케줄 상태)
# --------------------------------------------------------------------------- #


def test_coverage_needed_when_record_before_slot(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)

    def _reader() -> dict[str, Any]:
        return {
            "result_coverage_monitor": {
                "last_run_at": "2026-09-27T00:00:00+00:00",
                "success": True,
            }
        }

    needed, reason, details = check_result_coverage_catchup_needed(
        now=MONDAY_0920_KST, tz=SEOUL, status_reader=_reader
    )

    assert needed is True
    assert reason == "missed_result_coverage"
    assert details["last_coverage_slot"] == "2026-09-27T20:00:00+00:00"


def test_coverage_up_to_date_when_record_after_slot(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)

    def _reader() -> dict[str, Any]:
        return {
            "result_coverage_monitor": {
                "last_run_at": "2026-09-28T00:00:00+00:00",
                "success": True,
            }
        }

    needed, reason, _details = check_result_coverage_catchup_needed(
        now=MONDAY_0920_KST, tz=SEOUL, status_reader=_reader
    )

    assert needed is False
    assert reason == "result_coverage_up_to_date"


def test_coverage_needed_when_last_run_failed(monkeypatch):
    """슬롯 이후 실행이 success False 로 기록되면 실패로 보고 다시 실행합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)

    def _reader() -> dict[str, Any]:
        return {
            "result_coverage_monitor": {
                "last_run_at": "2026-09-28T00:00:00+00:00",
                "success": False,
            }
        }

    needed, reason, details = check_result_coverage_catchup_needed(
        now=MONDAY_0920_KST, tz=SEOUL, status_reader=_reader
    )

    assert needed is True
    assert reason == "last_result_coverage_failed"
    assert details["latest_result_coverage_at"] == "2026-09-28T00:00:00+00:00"
    assert details["latest_result_coverage_success"] is False


def test_coverage_treats_entry_without_success_as_no_record(monkeypatch):
    """success 키가 없는 항목은 기록 없음과 같게 취급합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)

    def _reader() -> dict[str, Any]:
        return {"result_coverage_monitor": {"last_run_at": "2026-09-28T00:00:00+00:00"}}

    needed, reason, _details = check_result_coverage_catchup_needed(
        now=MONDAY_0920_KST, tz=SEOUL, status_reader=_reader
    )

    assert needed is True
    assert reason == "no_previous_result_coverage"


def test_coverage_yields_before_slot_even_when_last_run_failed(monkeypatch):
    """양보 규칙은 실패 기록보다 먼저 적용되어 다음 슬롯 직전에는 실행하지 않습니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    now = datetime(2026, 9, 27, 19, 30, 0, tzinfo=UTC)

    def _reader() -> dict[str, Any]:
        return {
            "result_coverage_monitor": {
                "last_run_at": "2026-09-20T00:00:00+00:00",
                "success": False,
            }
        }

    needed, reason, details = check_result_coverage_catchup_needed(
        now=now, tz=SEOUL, status_reader=_reader
    )

    assert needed is False
    assert reason == "next_coverage_slot_imminent"
    assert details["next_slot"] == "2026-09-27T20:00:00+00:00"


def test_coverage_needed_when_no_record(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)

    def _reader() -> dict[str, Any]:
        return {}

    needed, reason, details = check_result_coverage_catchup_needed(
        now=MONDAY_0920_KST, tz=SEOUL, status_reader=_reader
    )

    assert needed is True
    assert reason == "no_previous_result_coverage"
    assert details["latest_result_coverage_at"] is None


def test_coverage_treats_read_failure_as_no_record(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)

    def _reader() -> dict[str, Any]:
        raise RuntimeError("redis read failed")

    needed, reason, details = check_result_coverage_catchup_needed(
        now=MONDAY_0920_KST, tz=SEOUL, status_reader=_reader
    )

    assert needed is True
    assert reason == "no_previous_result_coverage"
    assert details["latest_result_coverage_at"] is None


def test_coverage_yields_when_next_slot_imminent(monkeypatch):
    """2026-09-28 04:30 KST 기동은 다음 05:00 슬롯이 30분 뒤라 크론에 양보합니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    now = datetime(2026, 9, 27, 19, 30, 0, tzinfo=UTC)

    def _reader() -> dict[str, Any]:
        return {}

    needed, reason, details = check_result_coverage_catchup_needed(
        now=now, tz=SEOUL, status_reader=_reader
    )

    assert needed is False
    assert reason == "next_coverage_slot_imminent"
    assert details["next_slot"] == "2026-09-27T20:00:00+00:00"


def test_coverage_skipped_when_disabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", False)

    needed, reason, details = check_result_coverage_catchup_needed(now=MONDAY_0920_KST, tz=SEOUL)

    assert needed is False
    assert reason == "disabled"
    assert details["enabled"] is False


# --------------------------------------------------------------------------- #
# 원 태스크 공통 선점
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_drift_task_skips_when_claim_held(monkeypatch):
    """같은 선점 키가 이미 잡혀 있으면 본문 없이 already_running 을 반환합니다."""
    _enable_drift_catchup(monkeypatch)
    fake_conn = FakeRedisConnection(FakeRedisClient())
    fake_conn.client().set(DRIFT_MONITOR_CLAIM_KEY, "held", nx=True)
    set_schedule_redis_conn(fake_conn)

    mock_body = AsyncMock(return_value={"status": "success"})
    with patch.object(scheduled_tasks, "_run_drift_monitor", mock_body):
        result = await scheduled_tasks.drift_monitor_task({})

    assert result == {"status": "skipped", "reason": "already_running"}
    mock_body.assert_not_awaited()
    assert fake_conn.client().get(DRIFT_MONITOR_CLAIM_KEY) == "held"


@pytest.mark.asyncio
async def test_drift_task_releases_own_claim(monkeypatch):
    _enable_drift_catchup(monkeypatch)
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    mock_body = AsyncMock(return_value={"status": "success", "trigger_source": "drift_monitor"})
    with patch.object(scheduled_tasks, "_run_drift_monitor", mock_body):
        result = await scheduled_tasks.drift_monitor_task({})

    assert result["status"] == "success"
    assert fake_conn.client().get(DRIFT_MONITOR_CLAIM_KEY) is None


@pytest.mark.asyncio
async def test_drift_task_does_not_release_foreign_claim(monkeypatch):
    _enable_drift_catchup(monkeypatch)
    fake_client = FakeRedisClient()
    fake_conn = FakeRedisConnection(fake_client)
    set_schedule_redis_conn(fake_conn)

    foreign_payload = json.dumps({"owner": "other", "token": "foreign-token"})
    fake_client.set(DRIFT_MONITOR_CLAIM_KEY, foreign_payload, nx=True)
    own_claim = ScheduleClaimResult(
        status=ScheduleClaimStatus.ACQUIRED,
        key=DRIFT_MONITOR_CLAIM_KEY,
        owner="drift_monitor",
        ttl=10800,
        token="own-token",
    )

    mock_body = AsyncMock(return_value={"status": "success"})
    with (
        patch.object(scheduled_tasks, "_acquire_drift_monitor_claim", return_value=own_claim),
        patch.object(scheduled_tasks, "_run_drift_monitor", mock_body),
    ):
        result = await scheduled_tasks.drift_monitor_task({})

    assert result["status"] == "success"
    assert fake_client.get(DRIFT_MONITOR_CLAIM_KEY) == foreign_payload


@pytest.mark.asyncio
async def test_coverage_task_skips_when_claim_held():
    fake_conn = FakeRedisConnection(FakeRedisClient())
    fake_conn.client().set(RESULT_COVERAGE_CLAIM_KEY, "held", nx=True)
    set_schedule_redis_conn(fake_conn)

    mock_body = AsyncMock(return_value={"status": "ok"})
    with patch.object(coverage_tasks, "_run_result_coverage_monitor", mock_body):
        result = await coverage_tasks.result_coverage_monitor_task({})

    assert result == {"status": "skipped", "reason": "already_running"}
    mock_body.assert_not_awaited()
    assert fake_conn.client().get(RESULT_COVERAGE_CLAIM_KEY) == "held"


@pytest.mark.asyncio
async def test_coverage_task_releases_own_claim():
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    mock_body = AsyncMock(return_value={"status": "ok", "alerts": [], "rows": 0})
    with patch.object(coverage_tasks, "_run_result_coverage_monitor", mock_body):
        result = await coverage_tasks.result_coverage_monitor_task({})

    assert result["status"] == "ok"
    assert fake_conn.client().get(RESULT_COVERAGE_CLAIM_KEY) is None


# --------------------------------------------------------------------------- #
# 따라잡기 실행 태스크
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_drift_catchup_skips_without_calling_task(monkeypatch):
    monkeypatch.setattr(
        scheduled_tasks,
        "check_drift_monitor_catchup_needed",
        lambda db=None, now=None, tz=None: (False, "drift_monitor_up_to_date", {"enabled": True}),
    )
    mock_task = AsyncMock()
    with patch.object(scheduled_tasks, "drift_monitor_task", mock_task):
        result = await run_drift_monitor_catchup_task({})

    assert result["status"] == "skipped"
    assert result["reason"] == "drift_monitor_up_to_date"
    mock_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_drift_catchup_delegates_already_running(monkeypatch):
    """따라잡기는 별도 선점 없이 원 태스크의 already_running 을 그대로 전달합니다."""
    _enable_drift_catchup(monkeypatch)
    monkeypatch.setattr(
        scheduled_tasks,
        "check_drift_monitor_catchup_needed",
        lambda db=None, now=None, tz=None: (True, "missed_drift_monitor", {"enabled": True}),
    )
    fake_conn = FakeRedisConnection(FakeRedisClient())
    fake_conn.client().set(DRIFT_MONITOR_CLAIM_KEY, "held", nx=True)
    set_schedule_redis_conn(fake_conn)

    mock_body = AsyncMock(return_value={"status": "success"})
    with patch.object(scheduled_tasks, "_run_drift_monitor", mock_body):
        result = await run_drift_monitor_catchup_task({})

    assert result["status"] == "skipped"
    assert result["reason"] == "already_running"
    assert result["catchup_details"] == {"enabled": True}
    mock_body.assert_not_awaited()


@pytest.mark.asyncio
async def test_coverage_catchup_delegates_already_running(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(
        scheduled_tasks,
        "check_result_coverage_catchup_needed",
        lambda now=None, tz=None, status_reader=None: (
            True,
            "missed_result_coverage",
            {"enabled": True},
        ),
    )
    fake_conn = FakeRedisConnection(FakeRedisClient())
    fake_conn.client().set(RESULT_COVERAGE_CLAIM_KEY, "held", nx=True)
    set_schedule_redis_conn(fake_conn)

    mock_body = AsyncMock(return_value={"status": "ok"})
    with patch.object(coverage_tasks, "_run_result_coverage_monitor", mock_body):
        result = await run_result_coverage_catchup_task({})

    assert result["status"] == "skipped"
    assert result["reason"] == "already_running"
    assert result["catchup_details"] == {"enabled": True}
    mock_body.assert_not_awaited()


# --------------------------------------------------------------------------- #
# 데이터 따라잡기 종료 시 적재
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_schedule_catchup_enqueues_three_catchups(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(
        scheduled_tasks,
        "check_schedule_catchup_needed",
        lambda db=None, tz=None: (False, "threshold_not_exceeded", {"enabled": True}),
    )
    fake_arq = FakeArqRedis()

    result = await run_schedule_catchup_task({"redis": fake_arq})

    assert result["status"] == "skipped"
    assert fake_arq.calls == [
        (WEEKLY_RETRAIN_CATCHUP_JOB_NAME, {"_job_id": WEEKLY_RETRAIN_CATCHUP_JOB_ID}),
        (DRIFT_MONITOR_CATCHUP_JOB_NAME, {"_job_id": DRIFT_MONITOR_CATCHUP_JOB_ID}),
        (RESULT_COVERAGE_CATCHUP_JOB_NAME, {"_job_id": RESULT_COVERAGE_CATCHUP_JOB_ID}),
    ]


@pytest.mark.asyncio
async def test_enqueue_one_failure_does_not_block_others(monkeypatch):
    """한 적재의 예외가 나머지 적재를 막지 않습니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(
        scheduled_tasks,
        "check_schedule_catchup_needed",
        lambda db=None, tz=None: (False, "threshold_not_exceeded", {"enabled": True}),
    )
    calls: list[str] = []

    async def fake_weekly(ctx: dict[str, Any]) -> None:
        calls.append("weekly")

    async def fake_drift(ctx: dict[str, Any]) -> None:
        calls.append("drift")
        raise RuntimeError("enqueue failure")

    async def fake_coverage(ctx: dict[str, Any]) -> None:
        calls.append("coverage")

    monkeypatch.setattr(scheduled_tasks, "_enqueue_weekly_retrain_catchup", fake_weekly)
    monkeypatch.setattr(scheduled_tasks, "_enqueue_drift_monitor_catchup", fake_drift)
    monkeypatch.setattr(scheduled_tasks, "_enqueue_result_coverage_catchup", fake_coverage)

    result = await run_schedule_catchup_task({})

    assert result["status"] == "skipped"
    assert calls == ["weekly", "drift", "coverage"]


@pytest.mark.asyncio
async def test_schedule_catchup_without_redis_skips_monitor_enqueue(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(
        scheduled_tasks,
        "check_schedule_catchup_needed",
        lambda db=None, tz=None: (False, "threshold_not_exceeded", {"enabled": True}),
    )

    result = await run_schedule_catchup_task({})

    assert result["status"] == "skipped"


# --------------------------------------------------------------------------- #
# 커버리지 태스크의 Redis 스케줄 상태 기록
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_coverage_task_records_schedule_status(monkeypatch):
    """커버리지 태스크의 정상 실행(status ok)은 success True 로 기록됩니다."""
    store_client = StatusStoreClient()
    fake_cache = CacheLayer(connection=FakeRedisConnection(store_client, label="status_store"))
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)

    async def fake_body() -> dict[str, Any]:
        return {"status": "ok", "as_of": "2026-09-28", "alerts": [], "rows": 0}

    with patch.object(coverage_tasks, "_run_result_coverage_monitor", fake_body):
        result = await coverage_tasks.result_coverage_monitor_task({})

    assert result["status"] == "ok"
    status = worker.read_schedule_status()
    assert status["result_coverage_monitor"]["last_run_at"]
    assert status["result_coverage_monitor"]["success"] is True


@pytest.mark.asyncio
async def test_coverage_task_records_failed_schedule_status(monkeypatch):
    """커버리지 태스크의 실패 실행(status error)은 success False 로 기록됩니다."""
    store_client = StatusStoreClient()
    fake_cache = CacheLayer(connection=FakeRedisConnection(store_client, label="status_store"))
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)

    async def fake_body() -> dict[str, Any]:
        return {"status": "error", "as_of": "2026-09-28", "alerts": [], "rows": 0, "error": "boom"}

    with patch.object(coverage_tasks, "_run_result_coverage_monitor", fake_body):
        result = await coverage_tasks.result_coverage_monitor_task({})

    assert result["status"] == "error"
    status = worker.read_schedule_status()
    assert status["result_coverage_monitor"]["last_run_at"]
    assert status["result_coverage_monitor"]["success"] is False


@pytest.mark.asyncio
async def test_coverage_alert_message_includes_calibrated_rates(monkeypatch):
    """커버리지 경고 문구에 보정률·다주 기저·2주 연속 표시가 들어갑니다."""
    alert = {
        "category": "Thng",
        "week_start": "2026-08-24",
        "rate": 0.535,
        "baseline_rate": 0.65,
        "announcements": 454,
        "baseline_announcements": 409,
        "adjusted_rate": 0.577,
        "baseline_multi_rate": 0.623,
        "previous_week_start": "2026-08-17",
        "previous_adjusted_rate": 0.58,
        "previous_baseline_multi_rate": 0.64,
    }
    monkeypatch.setattr(
        coverage_tasks,
        "_collect_snapshot",
        lambda: {"status": "ok", "as_of": "2026-08-24", "alerts": [alert], "rows": 1},
    )
    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    monkeypatch.setattr(coverage_tasks, "notify", fake_notify)

    result = await coverage_tasks._run_result_coverage_monitor()

    assert result["status"] == "ok"
    _title, lines, level = sent[0]
    assert level == "warning"
    body = "\n".join(lines)
    assert "보정 57.7%" in body
    assert "다주 기저 62.3%" in body
    assert "2주 연속" in body


@pytest.mark.asyncio
async def test_drift_schedule_success_statuses_unchanged(monkeypatch):
    """기본 success_statuses 를 쓰는 드리프트 감시는 정상 실행을 success True 로 기록합니다."""
    store_client = StatusStoreClient()
    fake_cache = CacheLayer(connection=FakeRedisConnection(store_client, label="status_store"))
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)
    _enable_drift_catchup(monkeypatch)

    mock_body = AsyncMock(return_value={"status": "success", "trigger_source": "drift_monitor"})
    with patch.object(scheduled_tasks, "_run_drift_monitor", mock_body):
        result = await scheduled_tasks.drift_monitor_task({})

    assert result["status"] == "success"
    assert worker.read_schedule_status()["drift_monitor"]["success"] is True


@pytest.mark.asyncio
async def test_record_schedule_default_success_statuses(monkeypatch):
    """기본 success_statuses 는 success/skipped 만 성공으로 봅니다."""
    store_client = StatusStoreClient()
    fake_cache = CacheLayer(connection=FakeRedisConnection(store_client, label="status_store"))
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)

    @scheduled_tasks._record_schedule("probe_schedule")
    async def probe(status: str) -> dict[str, str]:
        return {"status": status}

    await probe("ok")
    assert worker.read_schedule_status()["probe_schedule"]["success"] is False
    await probe("success")
    assert worker.read_schedule_status()["probe_schedule"]["success"] is True
    await probe("skipped")
    assert worker.read_schedule_status()["probe_schedule"]["success"] is True


# --------------------------------------------------------------------------- #
# worker 등록
# --------------------------------------------------------------------------- #


def test_monitor_catchup_registered_with_one_hour_timeout():
    entries: dict[str, Any] = {}
    for fn in worker.WorkerSettings.functions:
        target = getattr(fn, "coroutine", fn)
        entries[getattr(target, "__name__", "")] = fn

    for name in ("run_drift_monitor_catchup_task", "run_result_coverage_catchup_task"):
        entry = entries[name]
        assert getattr(entry, "timeout_s", None) == worker.MONITOR_CATCHUP_JOB_TIMEOUT_SECONDS


# --------------------------------------------------------------------------- #
# 상수 단일 정의 (cron 타임아웃과 TTL·양보 파생)
# --------------------------------------------------------------------------- #


def _cron_entry(name: str) -> Any:
    for job in worker.WorkerSettings.cron_jobs:
        target = getattr(job, "coroutine", job)
        if getattr(target, "__name__", "") == name:
            return job
    raise AssertionError(f"cron 등록을 찾지 못했습니다: {name}")


def test_monitor_claim_ttl_at_least_job_timeout():
    """선점 TTL 은 잡 타임아웃 이상이어야 잡이 도는 동안 선점이 만료되지 않습니다."""
    assert (
        scheduled_tasks.DRIFT_MONITOR_CLAIM_TTL_SECONDS
        >= scheduled_tasks.DRIFT_MONITOR_JOB_TIMEOUT_SECONDS
    )
    assert (
        scheduled_tasks.RESULT_COVERAGE_CLAIM_TTL_SECONDS
        >= scheduled_tasks.RESULT_COVERAGE_JOB_TIMEOUT_SECONDS
    )


def test_monitor_yield_equals_job_timeout():
    assert (
        scheduled_tasks.DRIFT_MONITOR_YIELD_BEFORE_SLOT_SECONDS
        == scheduled_tasks.DRIFT_MONITOR_JOB_TIMEOUT_SECONDS
    )
    assert (
        scheduled_tasks.RESULT_COVERAGE_YIELD_BEFORE_SLOT_SECONDS
        == scheduled_tasks.RESULT_COVERAGE_JOB_TIMEOUT_SECONDS
    )


def test_monitor_timeout_ttl_yield_values_unchanged():
    """단일 정의로 묶어도 timeout, TTL, 양보 값은 바뀌지 않습니다."""
    assert scheduled_tasks.DRIFT_MONITOR_JOB_TIMEOUT_SECONDS == 3600
    assert scheduled_tasks.RESULT_COVERAGE_JOB_TIMEOUT_SECONDS == 3600
    assert scheduled_tasks.DRIFT_MONITOR_CLAIM_TTL_SECONDS == 10800
    assert scheduled_tasks.RESULT_COVERAGE_CLAIM_TTL_SECONDS == 10800
    assert scheduled_tasks.DRIFT_MONITOR_YIELD_BEFORE_SLOT_SECONDS == 3600
    assert scheduled_tasks.RESULT_COVERAGE_YIELD_BEFORE_SLOT_SECONDS == 3600


def test_monitor_cron_timeouts_use_job_timeout_constants():
    drift_entry = _cron_entry("drift_monitor_task")
    assert (
        getattr(drift_entry, "timeout_s", None) == scheduled_tasks.DRIFT_MONITOR_JOB_TIMEOUT_SECONDS
    )
    coverage_entry = _cron_entry("result_coverage_monitor_task")
    assert (
        getattr(coverage_entry, "timeout_s", None)
        == scheduled_tasks.RESULT_COVERAGE_JOB_TIMEOUT_SECONDS
    )
