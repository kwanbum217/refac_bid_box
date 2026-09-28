"""tests/test_weekly_retrain_catchup.py

기동 시 주간 재학습(월요일 03:00) 따라잡기 판정과 적재 검증.

검증 항목:
1. 주간 슬롯 계산(월요일 03:00, Asia/Seoul, 이전/다음 슬롯)
2. 주간 재학습 이력 없음/슬롯 이전/슬롯 이후 판정
3. 두 설정(AUTOMATION_SCHEDULE_CATCHUP_ENABLED, ML_WEEKLY_RETRAIN_ENABLED) 비활성 시 건너뜀
4. 다음 주간 슬롯 3시간 이내 양보(next_weekly_slot_imminent) 및 3시간 초과 시 기존 판정
5. weekly_retrain_task 공통 선점: already_running, 자기 토큰만 해제, Redis 불가 시 경고 후 진행
6. 따라잡기가 별도 선점 없이 weekly_retrain_task 의 already_running 을 그대로 전달
7. 데이터 따라잡기 종료 시 주간 재학습 태스크 적재, 중복 job_id 적재 시 info 로그
8. worker 등록 타임아웃(10800초) 확인
9. resolve_schedule_timezone 기본값이 프로세스 로컬 타임존을 따름
"""

from __future__ import annotations

import json
import logging
import os
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from zoneinfo import ZoneInfo

import pandas as pd
import pytest

from src.app.core.cache import RedisConnection
from src.app.core.config import settings
from src.app.models.predictions import RetrainLog
from src.tasks import retrain_task, scheduled_tasks, worker
from src.tasks.scheduled_tasks import (
    WEEKLY_RETRAIN_CATCHUP_JOB_ID,
    WEEKLY_RETRAIN_CATCHUP_JOB_NAME,
    WEEKLY_RETRAIN_CLAIM_KEY,
    ScheduleClaimResult,
    ScheduleClaimStatus,
    _enqueue_weekly_retrain_catchup,
    check_weekly_retrain_catchup_needed,
    get_latest_weekly_retrain_time,
    get_weekly_retrain_records_since,
    next_cron_slot,
    previous_cron_slot,
    run_schedule_catchup_task,
    run_weekly_retrain_catchup_task,
    set_schedule_redis_conn,
    weekly_retrain_task,
)
from tests.fake_redis import FakeRedisClient, FakeRedisConnection

SEOUL = ZoneInfo("Asia/Seoul")


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


class UnreachableScheduleRedisConnection(RedisConnection):
    """Redis 서버 미기동/연결 불가를 모의하는 대역 연결입니다."""

    def __init__(self, label: str = "test_weekly_unreachable") -> None:
        super().__init__(label=label)

    def client(self) -> Any:
        return None

    def invalidate(self, exc: Exception) -> None:
        return None


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


def test_next_cron_slot_weekly_returns_upcoming_monday_0300_kst():
    """월요일 01:00 KST(슬롯 이전) 기준 다음 주간 슬롯은 같은 날 03:00 KST 입니다."""
    now = datetime(2026, 9, 27, 16, 0, 0, tzinfo=UTC)
    slot = next_cron_slot(now, 3, 0, weekday=0, tz=SEOUL)
    assert slot == datetime(2026, 9, 27, 18, 0, 0, tzinfo=UTC)


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
    with (
        patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run),
        patch.object(scheduled_tasks, "get_weekly_retrain_records_since", return_value=[]),
    ):
        needed, reason, details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is True
    assert reason == "missed_weekly_retrain"
    assert details["latest_weekly_retrain_at"] == last_run.isoformat()


def test_weekly_catchup_skipped_when_last_run_after_slot(monkeypatch):
    _enable_weekly_catchup(monkeypatch)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc")
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    last_run = datetime(2026, 9, 28, 0, 0, 0, tzinfo=UTC)
    with (
        patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run),
        patch.object(
            scheduled_tasks,
            "get_weekly_retrain_records_since",
            return_value=[(last_run, {"category": "Servc"})],
        ),
    ):
        needed, reason, _details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is False
    assert reason == "weekly_retrain_up_to_date"


def test_weekly_catchup_yields_when_next_slot_imminent(monkeypatch):
    """월요일 01:00 KST 기동(직전 슬롯 놓침)은 다음 03:00 슬롯이 3시간 이내라 크론에 양보합니다."""
    _enable_weekly_catchup(monkeypatch)
    now = datetime(2026, 9, 27, 16, 0, 0, tzinfo=UTC)
    last_run = datetime(2026, 9, 21, 3, 11, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run):
        needed, reason, details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is False
    assert reason == "next_weekly_slot_imminent"
    assert details["next_slot"] == "2026-09-27T18:00:00+00:00"


def test_weekly_catchup_needed_when_next_slot_beyond_yield_window(monkeypatch):
    """다음 슬롯까지 3시간을 넘게 남으면 양보하지 않고 기존 판정을 유지합니다."""
    _enable_weekly_catchup(monkeypatch)
    now = datetime(2026, 9, 27, 14, 0, 0, tzinfo=UTC)
    with patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=None):
        needed, reason, _details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is True
    assert reason == "no_previous_weekly_retrain"


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
# 카테고리별 따라잡기 판정
# --------------------------------------------------------------------------- #


def _weekly_record(created_at: datetime, category: str | None) -> tuple[datetime, dict[str, Any]]:
    summary: dict[str, Any] = {} if category is None else {"category": category}
    return created_at, summary


def test_weekly_catchup_needed_when_one_of_two_categories_missing(monkeypatch):
    """두 카테고리 중 하나만 슬롯 이후 기록이 있으면 needed=True 와 missing_categories 를 남깁니다."""
    _enable_weekly_catchup(monkeypatch)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc,Thng")
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    last_run = datetime(2026, 9, 28, 0, 0, 0, tzinfo=UTC)
    records = [_weekly_record(last_run, "Servc")]
    with (
        patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run),
        patch.object(scheduled_tasks, "get_weekly_retrain_records_since", return_value=records),
    ):
        needed, reason, details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is True
    assert reason == "missed_weekly_retrain"
    assert details["missing_categories"] == ["Thng"]


def test_weekly_catchup_up_to_date_when_all_categories_recorded(monkeypatch):
    """설정된 두 카테고리 모두 슬롯 이후 기록이 있으면 처리됨으로 판정합니다."""
    _enable_weekly_catchup(monkeypatch)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc,Thng")
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    last_run = datetime(2026, 9, 28, 0, 0, 0, tzinfo=UTC)
    records = [_weekly_record(last_run, "Servc"), _weekly_record(last_run, "Thng")]
    with (
        patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run),
        patch.object(scheduled_tasks, "get_weekly_retrain_records_since", return_value=records),
    ):
        needed, reason, _details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is False
    assert reason == "weekly_retrain_up_to_date"


def test_weekly_catchup_accepts_category_less_row_for_single_category(monkeypatch):
    """카테고리 하나만 설정되면 category 없는 과거 행을 그 카테고리 기록으로 인정합니다."""
    _enable_weekly_catchup(monkeypatch)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc")
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    last_run = datetime(2026, 9, 28, 0, 0, 0, tzinfo=UTC)
    records = [_weekly_record(last_run, None)]
    with (
        patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run),
        patch.object(scheduled_tasks, "get_weekly_retrain_records_since", return_value=records),
    ):
        needed, reason, _details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is False
    assert reason == "weekly_retrain_up_to_date"


def test_weekly_catchup_rejects_category_less_row_for_two_categories(monkeypatch):
    """두 카테고리가 설정되면 category 없는 행은 어느 카테고리 기록으로도 인정하지 않습니다."""
    _enable_weekly_catchup(monkeypatch)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc,Thng")
    now = datetime(2026, 9, 28, 0, 20, 0, tzinfo=UTC)
    last_run = datetime(2026, 9, 28, 0, 0, 0, tzinfo=UTC)
    records = [_weekly_record(last_run, None)]
    with (
        patch.object(scheduled_tasks, "get_latest_weekly_retrain_time", return_value=last_run),
        patch.object(scheduled_tasks, "get_weekly_retrain_records_since", return_value=records),
    ):
        needed, reason, details = check_weekly_retrain_catchup_needed(now=now, tz=SEOUL)

    assert needed is True
    assert reason == "missed_weekly_retrain"
    assert details["missing_categories"] == ["Servc", "Thng"]


def test_get_weekly_retrain_records_since_filters_by_time_and_source(isolated_db):
    """슬롯 이후 weekly_schedule 행만 돌려주고 manual 행과 슬롯 이전 행은 제외합니다."""
    isolated_db.add_all(
        [
            RetrainLog(
                trigger_source="weekly_schedule",
                champion_version="champ",
                challenger_version="weekly-before",
                status="success",
                metrics_summary={"category": "Servc"},
                created_at=datetime(2026, 9, 26, 0, 0, 0),
            ),
            RetrainLog(
                trigger_source="weekly_schedule",
                champion_version="champ",
                challenger_version="weekly-after",
                status="success",
                metrics_summary={"category": "Thng"},
                created_at=datetime(2026, 9, 28, 0, 0, 0),
            ),
            RetrainLog(
                trigger_source="manual",
                champion_version="champ",
                challenger_version="manual-after",
                status="success",
                metrics_summary={"category": "Servc"},
                created_at=datetime(2026, 9, 28, 0, 0, 0),
            ),
        ]
    )
    isolated_db.commit()

    records = get_weekly_retrain_records_since(isolated_db, since=datetime(2026, 9, 27, 18, 0, 0))
    assert [summary for _created_at, summary in records] == [{"category": "Thng"}]


# --------------------------------------------------------------------------- #
# 실행 태스크 (공통 선점)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_weekly_retrain_task_skips_when_claim_already_held(monkeypatch):
    """같은 선점 키가 이미 잡혀 있으면 학습 본문 없이 already_running 을 반환합니다."""
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", True)
    fake_conn = FakeRedisConnection(FakeRedisClient())
    fake_conn.client().set(WEEKLY_RETRAIN_CLAIM_KEY, "held", nx=True)
    set_schedule_redis_conn(fake_conn)

    mock_retrain = AsyncMock(return_value={"status": "success"})
    with patch.object(scheduled_tasks, "run_retrain_pipeline_task", mock_retrain):
        result = await weekly_retrain_task({})

    assert result == {"status": "skipped", "reason": "already_running"}
    mock_retrain.assert_not_awaited()
    assert fake_conn.client().get(WEEKLY_RETRAIN_CLAIM_KEY) == "held"


@pytest.mark.asyncio
async def test_weekly_retrain_task_releases_own_claim_on_success(monkeypatch):
    """성공 시 자기 토큰으로 선점을 해제해 다음 실행이 가능하게 합니다."""
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", True)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc")
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    mock_retrain = AsyncMock(return_value={"status": "success", "category": "Servc"})
    with patch.object(scheduled_tasks, "run_retrain_pipeline_task", mock_retrain):
        result = await weekly_retrain_task({})

    assert result["status"] == "success"
    mock_retrain.assert_awaited_once()
    assert fake_conn.client().get(WEEKLY_RETRAIN_CLAIM_KEY) is None


@pytest.mark.asyncio
async def test_weekly_retrain_task_releases_claim_on_category_failure(monkeypatch):
    """카테고리 실패로 끝나도 자기 토큰으로 선점을 해제합니다."""
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", True)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc")
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    mock_retrain = AsyncMock(side_effect=RuntimeError("재학습 실패"))
    with patch.object(scheduled_tasks, "run_retrain_pipeline_task", mock_retrain):
        result = await weekly_retrain_task({})

    assert result["status"] == "failed"
    assert fake_conn.client().get(WEEKLY_RETRAIN_CLAIM_KEY) is None


@pytest.mark.asyncio
async def test_weekly_retrain_task_releases_claim_on_unhandled_exception(monkeypatch):
    """미처리 예외가 전파되어도 finally 에서 자기 토큰 선점을 해제합니다."""
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", True)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Srvc")
    fake_conn = FakeRedisConnection(FakeRedisClient())
    set_schedule_redis_conn(fake_conn)

    mock_notify = AsyncMock(side_effect=RuntimeError("알림 실패"))
    with (
        patch.object(scheduled_tasks, "notify_task_failure", mock_notify),
        pytest.raises(RuntimeError, match="알림 실패"),
    ):
        await weekly_retrain_task({})

    assert fake_conn.client().get(WEEKLY_RETRAIN_CLAIM_KEY) is None


@pytest.mark.asyncio
async def test_weekly_retrain_task_does_not_release_foreign_claim(monkeypatch):
    """다른 실행이 잡은 선점은 자기 토큰이 아니면 해제하지 않습니다."""
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", True)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc")
    fake_client = FakeRedisClient()
    fake_conn = FakeRedisConnection(fake_client)
    set_schedule_redis_conn(fake_conn)

    foreign_payload = json.dumps({"owner": "other", "token": "foreign-token"})
    fake_client.set(WEEKLY_RETRAIN_CLAIM_KEY, foreign_payload, nx=True)
    own_claim = ScheduleClaimResult(
        status=ScheduleClaimStatus.ACQUIRED,
        key=WEEKLY_RETRAIN_CLAIM_KEY,
        owner="weekly_retrain",
        ttl=10800,
        token="own-token",
    )

    mock_retrain = AsyncMock(return_value={"status": "success", "category": "Servc"})
    with (
        patch.object(scheduled_tasks, "_acquire_weekly_retrain_claim", return_value=own_claim),
        patch.object(scheduled_tasks, "run_retrain_pipeline_task", mock_retrain),
    ):
        result = await weekly_retrain_task({})

    assert result["status"] == "success"
    assert fake_client.get(WEEKLY_RETRAIN_CLAIM_KEY) == foreign_payload


@pytest.mark.asyncio
async def test_weekly_retrain_task_proceeds_without_claim_when_redis_unavailable(
    monkeypatch, caplog
):
    """Redis 에 접근할 수 없으면 경고를 남기고 선점 없이 학습을 진행합니다."""
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", True)
    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_CATEGORIES", "Servc")
    set_schedule_redis_conn(UnreachableScheduleRedisConnection())

    mock_retrain = AsyncMock(return_value={"status": "success", "category": "Servc"})
    with (
        caplog.at_level(logging.WARNING, logger="src.tasks.scheduled_tasks"),
        patch.object(scheduled_tasks, "run_retrain_pipeline_task", mock_retrain),
    ):
        result = await weekly_retrain_task({})

    assert result["status"] == "success"
    mock_retrain.assert_awaited_once()
    assert "선점 없이 진행" in caplog.text


@pytest.mark.asyncio
async def test_weekly_catchup_delegates_already_running_without_own_claim(monkeypatch):
    """따라잡기는 별도 선점 없이 공통 선점의 already_running 을 그대로 전달합니다."""
    _enable_weekly_catchup(monkeypatch)
    monkeypatch.setattr(
        scheduled_tasks,
        "check_weekly_retrain_catchup_needed",
        lambda db=None, now=None, tz=None: (True, "missed_weekly_retrain", {"enabled": True}),
    )
    fake_conn = FakeRedisConnection(FakeRedisClient())
    fake_conn.client().set(WEEKLY_RETRAIN_CLAIM_KEY, "held", nx=True)
    set_schedule_redis_conn(fake_conn)

    mock_retrain = AsyncMock(return_value={"status": "success"})
    with patch.object(scheduled_tasks, "run_retrain_pipeline_task", mock_retrain):
        result = await run_weekly_retrain_catchup_task({})

    assert result["status"] == "skipped"
    assert result["reason"] == "already_running"
    assert result["catchup_details"] == {"enabled": True}
    mock_retrain.assert_not_awaited()


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


@pytest.mark.asyncio
async def test_enqueue_weekly_retrain_logs_when_job_id_duplicate(caplog):
    """enqueue_job 이 None(같은 job_id 존재)이면 조용히 사라지지 않고 info 로그를 남깁니다."""
    fake_arq = FakeArqRedis(return_value=None)

    with caplog.at_level(logging.INFO, logger="src.tasks.scheduled_tasks"):
        await _enqueue_weekly_retrain_catchup({"redis": fake_arq})

    assert fake_arq.calls == [
        (WEEKLY_RETRAIN_CATCHUP_JOB_NAME, {"_job_id": WEEKLY_RETRAIN_CATCHUP_JOB_ID})
    ]
    assert "중복 적재를 건너뜁니다" in caplog.text


def test_weekly_catchup_registered_with_three_hour_timeout():
    entries: dict[str, Any] = {}
    for fn in worker.WorkerSettings.functions:
        target = getattr(fn, "coroutine", fn)
        entries[getattr(target, "__name__", "")] = fn

    entry = entries["run_weekly_retrain_catchup_task"]
    assert getattr(entry, "timeout_s", None) == worker.SCHEDULE_CATCHUP_JOB_TIMEOUT_SECONDS


# --------------------------------------------------------------------------- #
# 상수 단일 정의 (cron 타임아웃과 TTL·양보 파생)
# --------------------------------------------------------------------------- #


def _cron_entry(name: str) -> Any:
    for job in worker.WorkerSettings.cron_jobs:
        target = getattr(job, "coroutine", job)
        if getattr(target, "__name__", "") == name:
            return job
    raise AssertionError(f"cron 등록을 찾지 못했습니다: {name}")


def test_weekly_retrain_claim_ttl_at_least_job_timeout():
    """선점 TTL 은 잡 타임아웃 이상이어야 잡이 도는 동안 선점이 만료되지 않습니다."""
    assert (
        scheduled_tasks.WEEKLY_RETRAIN_CLAIM_TTL_SECONDS
        >= scheduled_tasks.WEEKLY_RETRAIN_JOB_TIMEOUT_SECONDS
    )


def test_weekly_retrain_yield_equals_job_timeout():
    assert (
        scheduled_tasks.WEEKLY_RETRAIN_YIELD_BEFORE_SLOT_SECONDS
        == scheduled_tasks.WEEKLY_RETRAIN_JOB_TIMEOUT_SECONDS
    )


def test_weekly_retrain_timeout_ttl_yield_values_unchanged():
    """단일 정의로 묶어도 timeout, TTL, 양보 값은 바뀌지 않습니다."""
    assert scheduled_tasks.WEEKLY_RETRAIN_JOB_TIMEOUT_SECONDS == 10800
    assert scheduled_tasks.WEEKLY_RETRAIN_CLAIM_TTL_SECONDS == 10800
    assert scheduled_tasks.WEEKLY_RETRAIN_YIELD_BEFORE_SLOT_SECONDS == 10800
    assert scheduled_tasks.SCHEDULE_CLAIM_MIN_TTL_SECONDS == 10800


def test_weekly_retrain_cron_timeout_uses_job_timeout_constant():
    entry = _cron_entry("weekly_retrain_task")
    assert getattr(entry, "timeout_s", None) == scheduled_tasks.WEEKLY_RETRAIN_JOB_TIMEOUT_SECONDS


@pytest.mark.asyncio
async def test_retrain_success_record_summary_includes_category(monkeypatch):
    """성공 기록의 metrics_summary 에 category 를 담고 원 verdict 는 바꾸지 않습니다."""
    captured: dict[str, Any] = {}
    verdict = {"recommendation": "REJECT_CHALLENGER", "champion_comparable": True}

    def fake_build(*_args: Any, **_kwargs: Any) -> Any:
        return pd.DataFrame({"x": [1, 2, 3]})

    class FakeTrainer:
        model_name = "servc_institution_v1"
        registry_dir = "ml_registry"

        def train_and_register(self, _df: Any) -> dict[str, Any]:
            return {
                "version": "servc-v1",
                "samples_count": 3,
                "metrics": {"rmse": 1.0},
                "holdout_is_overfit": False,
            }

    def fake_record(*_args: Any, **kwargs: Any) -> None:
        captured.update(kwargs)

    monkeypatch.setattr(retrain_task, "_build_training_dataset_thread", fake_build)
    monkeypatch.setattr(
        retrain_task, "_load_champion_metrics", lambda *_a, **_k: ("champ", {"rmse": 2.0})
    )
    monkeypatch.setattr(retrain_task.ModelTrainer, "for_category", lambda *_a, **_k: FakeTrainer())
    monkeypatch.setattr(retrain_task, "compare_champion_vs_challenger", lambda *_a, **_k: verdict)
    monkeypatch.setattr(retrain_task, "_record", fake_record)
    monkeypatch.setattr(retrain_task, "notify_retrain_result", AsyncMock())
    monkeypatch.setattr(retrain_task, "notify_task_failure", AsyncMock())

    result = await retrain_task.run_retrain_pipeline_task(
        {}, trigger_source="weekly_schedule", category_code="Servc"
    )

    assert result["status"] == "success"
    assert captured["summary"]["category"] == "Servc"
    assert captured["summary"]["recommendation"] == "REJECT_CHALLENGER"
    assert "category" not in verdict


# --------------------------------------------------------------------------- #
# 기본 타임존
# --------------------------------------------------------------------------- #


@pytest.mark.skipif(not hasattr(time, "tzset"), reason="time.tzset 미지원 플랫폼")
def test_resolve_schedule_timezone_default_follows_process_local():
    """tz 미지정 시 resolve_schedule_timezone 이 프로세스 로컬 타임존을 따릅니다."""
    original_tz = os.environ.get("TZ")
    try:
        os.environ["TZ"] = "Asia/Seoul"
        time.tzset()
        seoul_offset = scheduled_tasks.resolve_schedule_timezone().utcoffset(datetime.now(UTC))

        os.environ["TZ"] = "UTC"
        time.tzset()
        utc_offset = scheduled_tasks.resolve_schedule_timezone().utcoffset(datetime.now(UTC))
    finally:
        if original_tz is None:
            os.environ.pop("TZ", None)
        else:
            os.environ["TZ"] = original_tz
        time.tzset()

    assert seoul_offset == timedelta(hours=9)
    assert utc_offset == timedelta(0)
