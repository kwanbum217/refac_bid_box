"""tests/test_weekly_retrain_catchup.py

기동 시 주간 재학습(월요일 03:00) 따라잡기 판정과 적재 검증.

검증 항목:
1. 주간 슬롯 계산(월요일 03:00, Asia/Seoul)
2. 주간 재학습 이력 없음/슬롯 이전/슬롯 이후 판정
3. 두 설정(AUTOMATION_SCHEDULE_CATCHUP_ENABLED, ML_WEEKLY_RETRAIN_ENABLED) 비활성 시 건너뜀
4. Redis NX 선점 실패 시 already_running
5. 데이터 따라잡기 종료 시(건너뜀/예외) 주간 재학습 태스크 적재 및 적재 실패 격리
6. worker 등록 타임아웃(10800초) 확인
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pytest

from src.app.core.config import settings
from src.app.models.predictions import RetrainLog
from src.tasks import scheduled_tasks, worker
from src.tasks.scheduled_tasks import (
    WEEKLY_RETRAIN_CATCHUP_CLAIM_KEY,
    WEEKLY_RETRAIN_CATCHUP_JOB_ID,
    WEEKLY_RETRAIN_CATCHUP_JOB_NAME,
    check_weekly_retrain_catchup_needed,
    get_latest_weekly_retrain_time,
    previous_cron_slot,
    run_schedule_catchup_task,
    run_weekly_retrain_catchup_task,
    set_schedule_redis_conn,
)
from tests.fake_redis import FakeRedisClient, FakeRedisConnection

SEOUL = ZoneInfo("Asia/Seoul")


class FakeArqRedis:
    """arq ctx['redis'] 대역. enqueue_job 호출만 기록합니다."""

    def __init__(self, side_effect: Exception | None = None) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._side_effect = side_effect

    async def enqueue_job(self, name: str, **kwargs: Any) -> Any:
        self.calls.append((name, kwargs))
        if self._side_effect is not None:
            raise self._side_effect
        return object()


@pytest.fixture(autouse=True)
def isolate_schedule_redis():
    """모든 테스트에 격리된 FakeRedisConnection 을 제공하여 실제 Redis 와의 결합을 방지합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)
    yield fake_conn
    set_schedule_redis_conn(None)


def _enable_weekly_catchup(monkeypatch) -> None:
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", True)


# --------------------------------------------------------------------------- #
# 슬롯 계산
# --------------------------------------------------------------------------- #


def test_previous_cron_slot_weekly_returns_last_monday_0300_kst():
    """월요일 09:20 KST 기준 직전 주간 슬롯은 그날 03:00 KST(전날 18:00 UTC)입니다."""
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    slot = previous_cron_slot(now, 3, 0, weekday=0, tz=SEOUL)
    assert slot == datetime(2026, 9, 27, 18, 0, 0, tzinfo=UTC)


def test_previous_cron_slot_weekly_before_slot_returns_previous_week():
    """월요일 02:00 KST(슬롯 이전) 기준이면 전주 월요일 03:00 KST 를 돌려줍니다."""
    now = datetime(2026, 9, 28, 2, 0, 0, tzinfo=SEOUL)
    slot = previous_cron_slot(now, 3, 0, weekday=0, tz=SEOUL)
    assert slot == datetime(2026, 9, 20, 18, 0, 0, tzinfo=UTC)


# --------------------------------------------------------------------------- #
# 판정
# --------------------------------------------------------------------------- #


def test_weekly_catchup_needed_when_no_history(monkeypatch):
    _enable_weekly_catchup(monkeypatch)
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=None):
        needed, reason, details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is True
    assert reason == "no_previous_weekly_retrain"
    assert details["last_weekly_slot"] == "2026-09-27T18:00:00+00:00"
    assert details["latest_weekly_retrain_at"] is None


def test_weekly_catchup_needed_when_last_run_before_slot(monkeypatch):
    _enable_weekly_catchup(monkeypatch)
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    last_run = datetime(2026, 9, 27, 3, 11, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run):
        needed, reason, details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is True
    assert reason == "missed_weekly_retrain"
    assert details["latest_weekly_retrain_at"] == last_run.isoformat()


def test_weekly_catchup_skipped_when_last_run_after_slot(monkeypatch):
    _enable_weekly_catchup(monkeypatch)
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    last_run = datetime(2026, 9, 28, 0, 0, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run):
        needed, reason, _details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is False
    assert reason == "weekly_retrain_up_to_date"


@pytest.mark.parametrize(
    ("catchup_enabled", "weekly_enabled"),
    [(False, True), (True, False)],
)
def test_weekly_catchup_skipped_when_disabled(monkeypatch, catchup_enabled, weekly_enabled):
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", catchup_enabled)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", weekly_enabled)
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=None):
        needed, reason, details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is False
    assert reason == "disabled"
    assert details["enabled"] is False


def test_get_latest_weekly_retrain_time_filters_trigger_source(isolated_db):
    """trigger_source='weekly_schedule' 행만 주간 이력으로 집계합니다."""
    isolated_db.add_all(
        [
            RetrainLog(
                trigger_source="weekly_schedule",
                champion_version="champ",
                challenger_version="weekly-1",
                status="success",
                created_at=datetime(2026, 9, 21, 0, 0, 0),
            ),
            RetrainLog(
                trigger_source="manual",
                champion_version="champ",
                challenger_version="manual-1",
                status="success",
                created_at=datetime(2026, 9, 27, 0, 0, 0),
            ),
        ]
    )
    isolated_db.commit()

    latest = get_latest_weekly_retrain_time(isolated_db)
    assert latest == datetime(2026, 9, 21, 0, 0, 0)


# --------------------------------------------------------------------------- #
# 실행 태스크 (선점)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_weekly_catchup_skips_when_claim_already_held(monkeypatch):
    monkeypatch.setattr(
        scheduled_tasks,
        "check_weekly_retrain_catchup_needed",
        lambda db=None, now=None, tz=None: (
            True,
            "missed_weekly_retrain",
            {"enabled": True, "last_weekly_slot": "2026-09-27T18:00:00+00:00"},
        ),
    )
    fake_conn = FakeRedisConnection(FakeRedisClient())
    fake_conn.client().set(WEEKLY_RETRAIN_CATCHUP_CLAIM_KEY, "held", nx=True)
    set_schedule_redis_conn(fake_conn)

    mock_retrain = AsyncMock(return_value={"status": "success"})
    with patch.object(scheduled_tasks, "weekly_retrain_task", mock_retrain):
        result = await run_weekly_retrain_catchup_task({})

    assert result["status"] == "skipped"
    assert result["reason"] == "already_running"
    mock_retrain.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_catchup_runs_retrain_when_claim_acquired(monkeypatch):
    monkeypatch.setattr(
        scheduled_tasks,
        "check_weekly_retrain_catchup_needed",
        lambda db=None, now=None, tz=None: (True, "missed_weekly_retrain", {"enabled": True}),
    )
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    mock_retrain = AsyncMock(
        return_value={"status": "success", "trigger_source": "weekly_schedule"}
    )
    with patch.object(scheduled_tasks, "weekly_retrain_task", mock_retrain):
        result = await run_weekly_retrain_catchup_task({})

    assert result["status"] == "success"
    assert result["catchup_details"] == {"enabled": True}
    mock_retrain.assert_awaited_once()
    assert fake_conn.client().get(WEEKLY_RETRAIN_CATCHUP_CLAIM_KEY) is not None


# --------------------------------------------------------------------------- #
# 데이터 따라잡기 종료 시 주간 재학습 적재
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_schedule_catchup_enqueues_weekly_retrain_when_skipped(monkeypatch):
    monkeypatch.setattr(
        scheduled_tasks,
        "check_schedule_catchup_needed",
        lambda db=None, tz=None: (False, "threshold_not_exceeded", {"enabled": True}),
    )
    fake_arq = FakeArqRedis()

    result = await run_schedule_catchup_task({"redis": fake_arq})

    assert result["status"] == "skipped"
    assert fake_arq.calls == [
        (WEEKLY_RETRAIN_CATCHUP_JOB_NAME, {"_job_id": WEEKLY_RETRAIN_CATCHUP_JOB_ID})
    ]


@pytest.mark.asyncio
async def test_schedule_catchup_enqueues_weekly_retrain_on_failure(monkeypatch):
    monkeypatch.setattr(
        scheduled_tasks,
        "check_schedule_catchup_needed",
        lambda db=None, tz=None: (
            True,
            "missed_schedule",
            {"target_task": "development_data_refresh", "elapsed_hours": 30.0},
        ),
    )
    mock_refresh = AsyncMock(side_effect=RuntimeError("G2B 통신 장애"))
    fake_arq = FakeArqRedis()

    with patch.object(scheduled_tasks, "development_data_refresh_task", mock_refresh):
        result = await run_schedule_catchup_task({"redis": fake_arq})

    assert result["status"] == "failed"
    assert fake_arq.calls == [
        (WEEKLY_RETRAIN_CATCHUP_JOB_NAME, {"_job_id": WEEKLY_RETRAIN_CATCHUP_JOB_ID})
    ]


@pytest.mark.asyncio
async def test_schedule_catchup_enqueue_failure_does_not_change_result(monkeypatch):
    monkeypatch.setattr(
        scheduled_tasks,
        "check_schedule_catchup_needed",
        lambda db=None, tz=None: (False, "threshold_not_exceeded", {"enabled": True}),
    )
    fake_arq = FakeArqRedis(side_effect=RuntimeError("redis down"))

    result = await run_schedule_catchup_task({"redis": fake_arq})

    assert result["status"] == "skipped"
    assert result["reason"] == "threshold_not_exceeded"
    assert len(fake_arq.calls) == 1


@pytest.mark.asyncio
async def test_schedule_catchup_without_redis_skips_enqueue(monkeypatch):
    monkeypatch.setattr(
        scheduled_tasks,
        "check_schedule_catchup_needed",
        lambda db=None, tz=None: (False, "threshold_not_exceeded", {"enabled": True}),
    )

    result = await run_schedule_catchup_task({})

    assert result["status"] == "skipped"


def test_weekly_catchup_registered_with_three_hour_timeout():
    entries: dict[str, Any] = {}
    for fn in worker.WorkerSettings.functions:
        target = getattr(fn, "coroutine", fn)
        entries[getattr(target, "__name__", "")] = fn

    entry = entries["run_weekly_retrain_catchup_task"]
    assert getattr(entry, "timeout_s", None) == worker.SCHEDULE_CATCHUP_JOB_TIMEOUT_SECONDS
