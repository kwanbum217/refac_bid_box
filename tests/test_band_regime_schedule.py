"""
tests/test_band_regime_schedule.py

`2억미만 1억이상` 띠 용역 공고 첨부 판별 일일 크론 검증.

막으려는 사고:
  - 기본값이 켜져 있거나 플래그와 무관하게 크론이 등록되어 매일 외부 호출이 도는 것
  - 판별 범위가 14일을 벗어나 과거 공고를 다시 훑는 것
  - 외부 호출 상한(max_calls)과 대기(sleep) 없이 무제한으로 내려받는 것
  - 태스크 예외가 워커나 다른 크론을 멈추게 하는 것

판별 본문은 대역으로 대체하며 실제 네트워크·운영 DB·Redis 를 쓰지 않습니다.
"""

from __future__ import annotations

import importlib
from datetime import timedelta
from typing import Any

import pytest

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.tasks import scheduled_tasks, worker

LOOKBACK_DAYS = 14
MAX_CALLS = 60
SLEEP_SECONDS = 1.0
CRON_HOUR = 6
CRON_MINUTE = 10


class _FakeSession:
    """close 만 있는 DB 세션 대역."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def _cron_job_for(module: Any, name: str):
    for job in module.WorkerSettings.cron_jobs:
        target = getattr(job, "coroutine", job)
        if getattr(target, "__name__", "") == name:
            return job
    return None


@pytest.fixture
def fake_env(monkeypatch: pytest.MonkeyPatch):
    """세션과 스케줄 기록을 대역으로 바꾸고 플래그를 켠 환경을 돌려줍니다."""
    session = _FakeSession()
    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: session)
    monkeypatch.setattr(settings, "BAND_REGIME_SCHEDULE_ENABLED", True)
    recorded: dict[str, Any] = {"records": []}

    def _record(schedule_name: str, outcome: Any, success: bool) -> None:
        recorded["records"].append((schedule_name, outcome, success))

    monkeypatch.setattr("src.tasks.worker.record_schedule_result", _record)
    return session, recorded


@pytest.fixture
def reload_worker_with_flag():
    """플래그 값을 바꿔 worker 모듈을 다시 로드하고, 끝나면 원래 값으로 되돌립니다."""
    original = settings.BAND_REGIME_SCHEDULE_ENABLED

    def _reload(enabled: bool) -> Any:
        settings.BAND_REGIME_SCHEDULE_ENABLED = enabled
        return importlib.reload(worker)

    yield _reload
    settings.BAND_REGIME_SCHEDULE_ENABLED = original
    importlib.reload(worker)


# ============================================================================
# 1. 크론 등록 (플래그 조건)
# ============================================================================


def test_cron_not_registered_when_flag_disabled(reload_worker_with_flag) -> None:
    module = reload_worker_with_flag(False)

    assert _cron_job_for(module, "band_regime_daily_task") is None


def test_cron_registered_at_0610_when_flag_enabled(reload_worker_with_flag) -> None:
    module = reload_worker_with_flag(True)
    job = _cron_job_for(module, "band_regime_daily_task")

    assert job is not None
    assert job.hour == CRON_HOUR
    assert job.minute == CRON_MINUTE
    assert job.run_at_startup is False
    assert job.timeout_s == scheduled_tasks.BAND_REGIME_DAILY_JOB_TIMEOUT_SECONDS


# ============================================================================
# 2. 일일 판별 태스크
# ============================================================================


@pytest.mark.asyncio
async def test_daily_task_runs_recent_14_days_with_call_cap(monkeypatch, fake_env) -> None:
    session, recorded = fake_env
    captured: dict[str, Any] = {}

    def _fake_classify(db, *, start, end, max_calls, sleep, execute):
        captured.update(
            db=db,
            start=start,
            end=end,
            max_calls=max_calls,
            sleep=sleep,
            execute=execute,
        )
        return {
            "status": "success",
            "start": f"{start:%Y%m%d}",
            "end": f"{end:%Y%m%d}",
            "targets": 3,
            "calls_used": 2,
            "classified": 2,
            "no_attachment": 0,
            "failed": 1,
            "skipped": 0,
        }

    import scripts.classify_band_regime as classify

    monkeypatch.setattr(classify, "run_band_regime_classification", _fake_classify)

    outcome = await scheduled_tasks.band_regime_daily_task({})

    today = utcnow().date()
    assert captured["db"] is session
    assert captured["end"] == today
    assert captured["start"] == today - timedelta(days=LOOKBACK_DAYS - 1)
    assert captured["max_calls"] == MAX_CALLS
    assert captured["sleep"] == SLEEP_SECONDS
    assert captured["execute"] is True
    assert session.closed is True

    assert outcome == {
        "status": "success",
        "start": f"{today - timedelta(days=LOOKBACK_DAYS - 1):%Y%m%d}",
        "end": f"{today:%Y%m%d}",
        "targets": 3,
        "calls_used": 2,
        "classified": 2,
        "no_attachment": 0,
        "failed": 1,
        "skipped": 0,
        "truncated": False,
    }
    assert recorded["records"][0][0] == scheduled_tasks.BAND_REGIME_DAILY_SCHEDULE_NAME
    assert recorded["records"][0][2] is True


@pytest.mark.asyncio
async def test_daily_task_skips_when_flag_disabled(monkeypatch) -> None:
    monkeypatch.setattr(settings, "BAND_REGIME_SCHEDULE_ENABLED", False)
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *args: None)
    called: list[Any] = []

    import scripts.classify_band_regime as classify

    monkeypatch.setattr(
        classify,
        "run_band_regime_classification",
        lambda *args, **kwargs: called.append((args, kwargs)),
    )

    outcome = await scheduled_tasks.band_regime_daily_task({})

    assert outcome == {"status": "skipped", "reason": "disabled"}
    assert called == []


@pytest.mark.asyncio
async def test_daily_task_notifies_once_and_returns_failure(monkeypatch, fake_env) -> None:
    _session, recorded = fake_env
    notifications: list[tuple[str, str]] = []

    def _boom(*args, **kwargs):
        raise RuntimeError("첨부 다운로드 실패")

    async def _record_failure(task_name: str, error: str, *, detail: str = "") -> None:
        notifications.append((task_name, error))

    import scripts.classify_band_regime as classify

    monkeypatch.setattr(classify, "run_band_regime_classification", _boom)
    monkeypatch.setattr(scheduled_tasks, "notify_task_failure", _record_failure)

    outcome = await scheduled_tasks.band_regime_daily_task({})

    assert len(notifications) == 1
    assert outcome["status"] == "failed"
    assert outcome["error_type"] == "RuntimeError"
    assert recorded["records"][0][0] == scheduled_tasks.BAND_REGIME_DAILY_SCHEDULE_NAME
    assert recorded["records"][0][2] is False
