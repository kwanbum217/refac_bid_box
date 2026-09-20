"""
tests/test_scheduled_tasks.py

정기 실행 스케줄 검증.

원본은 Harness 야간 트리거(매일 02:00)와 Airflow 주간 재학습 DAG(월요일 03:00)로
나뉘어 있었습니다. 이식본은 둘 다 Arq 크론으로 옮겼으므로, 옮긴 시각이 원본과
같은지와 실행 이력이 남는지를 확인합니다.
"""

import asyncio
import threading
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, patch

import pandas as pd
import pytest
from arq.cron import next_cron
from sqlalchemy import select

from src.app.core.config import settings
from src.app.models.chatbot import PipelineExecution
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks import scheduled_tasks, worker
from src.tasks.run_mode_matrix import get_run_mode_steps
from src.tasks.worker import WorkerSettings
from tests.fake_redis import FakeRedisClient, FakeRedisConnection


@pytest.fixture(autouse=True)
def mock_schedule_claim(monkeypatch):
    """테스트 실행 환경에서 Redis 서버 없이도 스케줄 태스크가 정상 실행되도록 claim 모의 객체를 기본 제공합니다."""
    monkeypatch.setattr(
        scheduled_tasks,
        "acquire_schedule_claim",
        lambda owner, **kwargs: scheduled_tasks.ScheduleClaimResult(
            status=scheduled_tasks.ScheduleClaimStatus.ACQUIRED,
            key=scheduled_tasks.SCHEDULE_COLLECTION_CLAIM_KEY,
            owner=owner,
            ttl=21600,
            detail="test claim granted",
        ),
    )


def _cron_by_name(name: str):
    for job in WorkerSettings.cron_jobs:
        if job.name.endswith(name):
            return job
    raise AssertionError(f"크론 작업 {name} 이 등록되어 있지 않습니다.")


def _next_run_after(job, moment: datetime) -> datetime:
    return next_cron(
        moment,
        month=job.month,
        day=job.day,
        weekday=job.weekday,
        hour=job.hour,
        minute=job.minute,
        second=job.second,
        microsecond=job.microsecond,
    )


# --------------------------------------------------------------------------- #
# 크론 등록 시각 (원본 대조)
# --------------------------------------------------------------------------- #


def test_nightly_cron_runs_daily_at_two():
    """원본 Harness 트리거 expression "0 2 * * *" 와 같은 시각이어야 합니다."""
    job = _cron_by_name("nightly_schedule_task")
    assert job.hour == 2
    assert job.minute == 0
    assert job.weekday is None
    assert job.day is None

    next_run = _next_run_after(job, datetime(2026, 8, 5, 12, 0, 0))
    assert next_run == datetime(2026, 8, 6, 2, 0, 0, job.microsecond)


def test_development_refresh_cron_runs_daily_at_two():
    job = _cron_by_name("development_data_refresh_task")
    assert job.hour == 2
    assert job.minute == 0
    assert job.weekday is None
    assert scheduled_tasks.development_data_refresh_task in WorkerSettings.functions


def test_weekly_retrain_cron_runs_monday_at_three():
    """원본 Airflow schedule_interval "0 3 * * 1" 과 같은 시각이어야 합니다.

    weekday 필드는 "mon" 문자열로 저장되므로 값 비교 대신 실제 다음 실행 시각을
    계산해 월요일 03:00 에 떨어지는지 확인합니다.
    """
    job = _cron_by_name("weekly_retrain_task")
    assert job.hour == 3
    assert job.minute == 0

    # 수요일 정오 기준으로 다음 실행 시각을 계산합니다.
    next_run = _next_run_after(job, datetime(2026, 8, 5, 12, 0, 0))
    assert next_run.weekday() == 0
    assert (next_run.hour, next_run.minute) == (3, 0)
    assert next_run.date() == date(2026, 8, 10)


def test_cron_jobs_do_not_run_at_startup():
    """워커를 재기동할 때마다 야간 번들이 도는 사고를 막습니다."""
    for job in WorkerSettings.cron_jobs:
        assert job.run_at_startup is False


def test_cron_timeout_exceeds_default_job_timeout():
    """번들 전체 실행은 기본 job_timeout(30분)보다 오래 걸립니다."""
    for job in WorkerSettings.cron_jobs:
        assert job.timeout_s is not None
        assert job.timeout_s > WorkerSettings.job_timeout


# --------------------------------------------------------------------------- #
# 야간 스케줄
# --------------------------------------------------------------------------- #


def test_nightly_schedule_uses_original_run_mode():
    """원본 트리거의 RUN_MODE 값과 스텝 구성이 유지되어야 합니다."""
    assert get_run_mode_steps("nightly_schedule") == (
        "collect",
        "search",
        "rag",
        "predict",
        "inspect",
    )


@pytest.mark.asyncio
async def test_nightly_schedule_records_execution_and_runs_pipeline(monkeypatch, isolated_db):
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True, raising=False)
    session_factory = lambda: isolated_db  # noqa: E731
    with (
        patch.object(scheduled_tasks, "SessionLocal", session_factory),
        patch.object(
            scheduled_tasks,
            "run_automation_pipeline",
            new=AsyncMock(return_value={"status": "success"}),
        ) as run_pipeline,
    ):
        isolated_db.close = lambda: None
        result = await scheduled_tasks.nightly_schedule_task({})

    assert result["status"] == "success"
    kwargs = run_pipeline.await_args.kwargs
    assert kwargs["run_mode"] == "nightly_schedule"

    execution = isolated_db.execute(
        select(PipelineExecution).where(PipelineExecution.execution_id == kwargs["execution_id"])
    ).scalar_one()
    assert execution.run_mode == "nightly_schedule"
    # 원본 run_local_automation_bundle 의 기본 source 라벨입니다.
    assert execution.source == "local_scheduler"
    assert execution.raw_status_payload["scheduled"] is True


@pytest.mark.asyncio
async def test_nightly_schedule_skipped_when_disabled(monkeypatch, isolated_db):
    from src.app.core.config import settings

    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False, raising=False)
    with patch.object(scheduled_tasks, "run_automation_pipeline", new=AsyncMock()) as run_pipeline:
        result = await scheduled_tasks.nightly_schedule_task({})

    assert result == {"status": "skipped", "reason": "disabled"}
    run_pipeline.assert_not_awaited()
    # 실행하지 않았으므로 이력도 남지 않아야 합니다.
    assert isolated_db.execute(select(PipelineExecution)).scalars().all() == []


@pytest.mark.asyncio
async def test_development_refresh_records_lightweight_pipeline(isolated_db, monkeypatch):
    session_factory = lambda: isolated_db  # noqa: E731
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False, raising=False)
    with (
        patch.object(scheduled_tasks, "SessionLocal", session_factory),
        patch.object(
            scheduled_tasks,
            "run_automation_pipeline",
            new=AsyncMock(
                return_value={"status": "success", "completed_steps": ["collect", "rag", "inspect"]}
            ),
        ) as run_pipeline,
        patch.object(
            scheduled_tasks, "_rebuild_ranking_snapshots", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_rebuild_institution_stats", return_value={"status": "success"}
        ),
    ):
        isolated_db.close = lambda: None
        result = await scheduled_tasks.development_data_refresh_task({})

    assert result["status"] == "success"
    kwargs = run_pipeline.await_args.kwargs
    assert kwargs["run_mode"] == "refresh_data"
    execution = isolated_db.execute(
        select(PipelineExecution).where(PipelineExecution.execution_id == kwargs["execution_id"])
    ).scalar_one()
    assert execution.run_mode == "development_data_refresh"
    assert execution.source == "local_scheduler"


@pytest.mark.asyncio
async def test_development_refresh_skips_when_full_nightly_schedule_is_enabled(monkeypatch):
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True, raising=False)

    result = await scheduled_tasks.development_data_refresh_task({})

    assert result == {"status": "skipped", "reason": "nightly_schedule_enabled"}


@pytest.mark.asyncio
async def test_development_refresh_does_not_rebuild_aggregates_after_pipeline_failure(
    isolated_db, monkeypatch
):
    session_factory = lambda: isolated_db  # noqa: E731
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True, raising=False)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False, raising=False)
    with (
        patch.object(scheduled_tasks, "SessionLocal", session_factory),
        patch.object(
            scheduled_tasks,
            "run_automation_pipeline",
            new=AsyncMock(return_value={"status": "failed", "error": "KB 오류"}),
        ),
        patch.object(scheduled_tasks, "_rebuild_ranking_snapshots") as rebuild_ranking,
        patch.object(scheduled_tasks, "_rebuild_institution_stats") as rebuild_institution,
    ):
        isolated_db.close = lambda: None
        result = await scheduled_tasks.development_data_refresh_task({})

    assert result["status"] == "failed"
    rebuild_ranking.assert_not_called()
    rebuild_institution.assert_not_called()


# --------------------------------------------------------------------------- #
# 주간 재학습
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_weekly_retrain_marks_trigger_source():
    with patch.object(
        scheduled_tasks,
        "run_retrain_pipeline_task",
        new=AsyncMock(return_value={"status": "success", "version": "v1"}),
    ) as retrain:
        result = await scheduled_tasks.weekly_retrain_task({})

    assert result["status"] == "success"
    assert retrain.await_args.kwargs["trigger_source"] == "weekly_schedule"


@pytest.mark.asyncio
async def test_weekly_retrain_skipped_when_disabled(monkeypatch):
    from src.app.core.config import settings

    monkeypatch.setattr(settings, "ML_WEEKLY_RETRAIN_ENABLED", False, raising=False)
    with patch.object(scheduled_tasks, "run_retrain_pipeline_task", new=AsyncMock()) as retrain:
        result = await scheduled_tasks.weekly_retrain_task({})

    assert result == {"status": "skipped", "reason": "disabled"}
    retrain.assert_not_awaited()


@pytest.mark.asyncio
async def test_weekly_retrain_failure_does_not_propagate():
    """크론 안에서 예외가 새면 이후 스케줄까지 함께 멈춥니다."""
    with patch.object(
        scheduled_tasks,
        "run_retrain_pipeline_task",
        new=AsyncMock(side_effect=RuntimeError("학습 데이터 부족")),
    ):
        result = await scheduled_tasks.weekly_retrain_task({})

    assert result["status"] == "failed"
    assert "학습 데이터 부족" in result["error"]


# --------------------------------------------------------------------------- #
# 기동 따라잡기 동시성 제어 및 완결성 원장 (D-04)
# --------------------------------------------------------------------------- #


@pytest.fixture
def catchup_redis():
    fake_conn = FakeRedisConnection(FakeRedisClient())
    scheduled_tasks.set_schedule_redis_conn(fake_conn)
    yield fake_conn
    scheduled_tasks.set_schedule_redis_conn(None)


def _enable_needed_catchup(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", False)
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS", 24)
    now = datetime(2026, 9, 5, 12, 0, 0, tzinfo=UTC)
    old_collected = now - timedelta(hours=48)
    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: now)
    monkeypatch.setattr(
        scheduled_tasks, "get_latest_collection_time", lambda db=None: old_collected
    )


@pytest.mark.asyncio
async def test_catchup_ledger_distinguishes_target_executed_failed_skipped(
    monkeypatch, catchup_redis
):
    """원장이 대상, 실행, 실패, 건너뜀을 한 기록 경로에서 구분합니다."""
    _enable_needed_catchup(monkeypatch)
    monkeypatch.setattr(
        scheduled_tasks,
        "development_data_refresh_task",
        AsyncMock(return_value={"status": "success"}),
    )

    outcome = await scheduled_tasks.run_schedule_catchup_task({})
    assert outcome["status"] == "success"
    success_ledger = scheduled_tasks.load_catchup_ledger(conn=catchup_redis)
    assert success_ledger is not None
    assert success_ledger["targets"][0]["name"] == "development_data_refresh"
    assert success_ledger["executed"][0]["name"] == "development_data_refresh"
    assert success_ledger["failed"] == []
    assert success_ledger["skipped"] == []

    catchup_redis.client().delete(
        scheduled_tasks.SCHEDULE_CATCHUP_COOLDOWN_KEY,
        scheduled_tasks.CATCHUP_LEDGER_KEY,
    )
    monkeypatch.setattr(
        scheduled_tasks,
        "development_data_refresh_task",
        AsyncMock(side_effect=RuntimeError("수집 실패")),
    )

    failed = await scheduled_tasks.run_schedule_catchup_task({})
    assert failed["status"] == "failed"
    failed_ledger = scheduled_tasks.load_catchup_ledger(conn=catchup_redis)
    assert failed_ledger is not None
    assert failed_ledger["failed"][0]["name"] == "development_data_refresh"
    assert "수집 실패" in failed_ledger["failed"][0]["error"]
    assert failed_ledger["executed"] == []

    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", False)

    skipped = await scheduled_tasks.run_schedule_catchup_task({})
    assert skipped["status"] == "skipped"
    skipped_ledger = scheduled_tasks.load_catchup_ledger(conn=catchup_redis)
    assert skipped_ledger is not None
    assert skipped_ledger["skipped"][0]["reason"] == "disabled"
    assert skipped_ledger["executed"] == []
    assert skipped_ledger["failed"] == []


@pytest.mark.asyncio
async def test_catchup_cancelled_records_ledger_and_propagates(monkeypatch, catchup_redis):
    """취소 시 CancelledError가 전파되고 원장이 running이 아닌 cancelled 로 기록됩니다."""
    _enable_needed_catchup(monkeypatch)
    started = asyncio.Event()

    async def _blocking_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
        started.set()
        await asyncio.Event().wait()
        return {"status": "success"}

    monkeypatch.setattr(
        scheduled_tasks,
        "development_data_refresh_task",
        AsyncMock(side_effect=_blocking_refresh),
    )

    task = asyncio.create_task(scheduled_tasks.run_schedule_catchup_task({}))
    await started.wait()

    running_ledger = scheduled_tasks.load_catchup_ledger(conn=catchup_redis)
    assert running_ledger is not None
    assert running_ledger["status"] == "running"

    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await task

    assert task.cancelled() is True
    ledger = scheduled_tasks.load_catchup_ledger(conn=catchup_redis)
    assert ledger is not None
    assert ledger["status"] != "running"
    assert ledger["status"] == "cancelled"
    assert ledger["reason"] == "cancelled"
    assert ledger["failed"][0]["name"] == "development_data_refresh"
    assert ledger["failed"][0]["error"] == "cancelled"


@pytest.mark.asyncio
async def test_concurrent_catchup_does_not_run_twice(monkeypatch, catchup_redis):
    """SET NX 선점으로 동시 기동에서 대상 스케줄이 한 번만 실행됩니다."""
    _enable_needed_catchup(monkeypatch)
    monkeypatch.setattr(
        scheduled_tasks, "is_catchup_in_cooldown", lambda conn=None, key=None: (False, None)
    )
    started = asyncio.Event()
    release = asyncio.Event()

    async def _slow_refresh(ctx: dict[str, Any]) -> dict[str, Any]:
        started.set()
        await release.wait()
        return {"status": "success"}

    mock_refresh = AsyncMock(side_effect=_slow_refresh)
    monkeypatch.setattr(scheduled_tasks, "development_data_refresh_task", mock_refresh)

    first = asyncio.create_task(scheduled_tasks.run_schedule_catchup_task({"worker": "a"}))
    await started.wait()
    second = await scheduled_tasks.run_schedule_catchup_task({"worker": "b"})
    release.set()
    first_outcome = await first

    assert first_outcome["status"] == "success"
    assert second["status"] == "skipped"
    assert second["reason"] == "already_running"
    assert mock_refresh.await_count == 1


@pytest.mark.asyncio
async def test_startup_enqueues_catchup_without_blocking(monkeypatch):
    """기동은 큐 적재만 백그라운드로 띄우고 따라잡기 완료를 기다리지 않습니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "OTEL_ENABLED", False)
    enqueue_started = asyncio.Event()
    enqueue_finished = asyncio.Event()

    async def _slow_enqueue(*args: Any, **kwargs: Any) -> object:
        enqueue_started.set()
        await asyncio.sleep(30)
        enqueue_finished.set()
        return object()

    ctx: dict[str, Any] = {"redis": SimpleNamespace(enqueue_job=_slow_enqueue)}
    with patch.object(worker, "record_worker_heartbeat"):
        await worker._on_startup(ctx)
        await asyncio.sleep(0)
        assert enqueue_started.is_set()
        assert not enqueue_finished.is_set()
        assert not ctx["schedule_catchup_task"].done()
        await worker._on_shutdown(ctx)
    assert not enqueue_finished.is_set()


@pytest.mark.asyncio
async def test_startup_catchup_uses_arq_enqueue_not_direct_run(monkeypatch):
    """redis 가 있으면 따라잡기를 직접 실행하지 않고 Arq 큐에 넣습니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    monkeypatch.setattr(settings, "OTEL_ENABLED", False)
    enqueue = AsyncMock(return_value=object())
    direct = AsyncMock()
    ctx: dict[str, Any] = {"redis": SimpleNamespace(enqueue_job=enqueue)}
    with (
        patch.object(worker, "record_worker_heartbeat"),
        patch.object(worker, "run_schedule_catchup_task", direct),
    ):
        await worker._on_startup(ctx)
        await asyncio.sleep(0)
        await ctx["schedule_catchup_task"]
        await worker._on_shutdown(ctx)
    enqueue.assert_awaited()
    assert enqueue.await_args.args[0] == worker.SCHEDULE_CATCHUP_JOB_NAME
    assert enqueue.await_args.kwargs["_job_id"] == worker.SCHEDULE_CATCHUP_JOB_ID
    direct.assert_not_awaited()


@pytest.mark.asyncio
async def test_catchup_enqueue_failure_does_not_kill_worker(monkeypatch, catchup_redis):
    """큐 적재 예외는 워커를 종료시키지 않고 원장에 실패로 남깁니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)

    async def _boom(*args: Any, **kwargs: Any) -> None:
        raise RuntimeError("redis enqueue down")

    ctx: dict[str, Any] = {"redis": SimpleNamespace(enqueue_job=_boom)}
    await worker._run_catchup_background(ctx)
    ledger = scheduled_tasks.load_catchup_ledger(conn=catchup_redis)
    assert ledger is not None
    assert ledger["status"] == "failed"
    assert ledger["reason"] == "enqueue_failed"
    assert "redis enqueue down" in ledger["failed"][0]["error"]


def test_catchup_job_is_registered_with_nightly_timeout():
    """따라잡기 잡은 max_jobs 대상 함수이며 야간 크론과 같은 제한 시간을 가집니다."""
    catchup = None
    for fn in WorkerSettings.functions:
        target = getattr(fn, "coroutine", fn)
        if getattr(target, "__name__", "") == "run_schedule_catchup_task":
            catchup = fn
            break
    assert catchup is not None
    assert getattr(catchup, "timeout_s", None) == float(worker.SCHEDULE_CATCHUP_JOB_TIMEOUT_SECONDS)
    assert WorkerSettings.max_jobs == 4


# --------------------------------------------------------------------------- #
# 이벤트 루프 오프로드 증명 (스레드 식별자 대조)
# --------------------------------------------------------------------------- #


@pytest.mark.asyncio
async def test_schedule_claim_acquire_and_release_run_off_event_loop(monkeypatch, isolated_db):
    """claim 획득·해제가 이벤트 루프 스레드가 아닌 워커 스레드에서 실행됩니다."""
    monkeypatch.setattr(settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True, raising=False)
    loop_thread = threading.get_ident()
    acquire_threads: list[int] = []
    release_threads: list[int] = []

    def _acquire(owner, **kwargs):
        acquire_threads.append(threading.get_ident())
        return scheduled_tasks.ScheduleClaimResult(
            status=scheduled_tasks.ScheduleClaimStatus.ACQUIRED,
            key=scheduled_tasks.SCHEDULE_COLLECTION_CLAIM_KEY,
            owner=owner,
            ttl=21600,
            token="test-token",
            detail="test claim granted",
        )

    def _release(key, token=None, **kwargs):
        release_threads.append(threading.get_ident())
        return True

    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", _acquire)
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", _release)

    session_factory = lambda: isolated_db  # noqa: E731
    with (
        patch.object(scheduled_tasks, "SessionLocal", session_factory),
        patch.object(
            scheduled_tasks,
            "run_automation_pipeline",
            new=AsyncMock(return_value={"status": "success"}),
        ),
        patch.object(
            scheduled_tasks, "_rebuild_ranking_snapshots", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_rebuild_compare_stats_snapshots", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_rebuild_institution_stats", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_check_mysql_stats_freshness", return_value={"status": "success"}
        ),
        patch.object(
            scheduled_tasks, "_check_restore_drill_freshness", return_value={"status": "success"}
        ),
    ):
        isolated_db.close = lambda: None
        result = await scheduled_tasks.nightly_schedule_task({})

    assert result["status"] == "success"
    assert acquire_threads
    assert all(tid != loop_thread for tid in acquire_threads)
    assert release_threads
    assert all(tid != loop_thread for tid in release_threads)


@pytest.mark.asyncio
async def test_catchup_decision_and_ledger_run_off_event_loop(monkeypatch, catchup_redis):
    """따라잡기 판정과 선점·종결 원장 기록이 이벤트 루프 밖에서 실행됩니다."""
    loop_thread = threading.get_ident()
    check_threads: list[int] = []
    record_threads: list[int] = []

    def _check(db=None):
        check_threads.append(threading.get_ident())
        return (True, "threshold_exceeded", {"target_task": "development_data_refresh"})

    def _record(*args, **kwargs):
        record_threads.append(threading.get_ident())
        return True

    monkeypatch.setattr(scheduled_tasks, "check_schedule_catchup_needed", _check)
    monkeypatch.setattr(scheduled_tasks, "record_catchup_attempt", _record)
    monkeypatch.setattr(
        scheduled_tasks,
        "development_data_refresh_task",
        AsyncMock(return_value={"status": "success"}),
    )

    outcome = await scheduled_tasks.run_schedule_catchup_task({})

    assert outcome["status"] == "success"
    assert check_threads
    assert all(tid != loop_thread for tid in check_threads)
    # 선점(nx) 기록과 finally 종결 기록이 각각 오프로드됩니다.
    assert len(record_threads) >= 2
    assert all(tid != loop_thread for tid in record_threads)


@pytest.mark.asyncio
async def test_catchup_skip_ledger_write_runs_off_event_loop(monkeypatch, catchup_redis):
    """판정 스킵 경로의 원장 기록도 이벤트 루프 밖에서 실행됩니다."""
    loop_thread = threading.get_ident()
    record_threads: list[int] = []

    def _check(db=None):
        return (False, "threshold_not_exceeded", {"target_task": "development_data_refresh"})

    def _record(*args, **kwargs):
        record_threads.append(threading.get_ident())
        return True

    monkeypatch.setattr(scheduled_tasks, "check_schedule_catchup_needed", _check)
    monkeypatch.setattr(scheduled_tasks, "record_catchup_attempt", _record)

    outcome = await scheduled_tasks.run_schedule_catchup_task({})

    assert outcome["status"] == "skipped"
    assert record_threads
    assert all(tid != loop_thread for tid in record_threads)


@pytest.mark.asyncio
async def test_drift_feature_frame_and_psi_run_off_event_loop(monkeypatch):
    """드리프트 특징 프레임 생성과 PSI 판정이 같은 워커 스레드에서 한 번에 실행됩니다."""
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", True, raising=False)
    loop_thread = threading.get_ident()
    seen: list[tuple[str, int]] = []

    df_recent = pd.DataFrame(
        [
            {
                "presumed_price": 100_000_000.0,
                "base_price": 99_000_000.0,
                "winning_rate": 88.0,
                "openg_dt": "2026-08-01",
                "srvce_div_nm": "일반용역",
            }
            for _ in range(120)
        ]
    )

    def _build_dataset(db, category_code, **kwargs):
        seen.append(("build", threading.get_ident()))
        return df_recent

    def _compute_drift(baseline_dist, df_feat, **kwargs):
        seen.append(("drift", threading.get_ident()))
        return {
            "status": "STABLE",
            "recent_samples": len(df_feat),
            "drift_feature_count": 0,
            "drift_features": [],
            "total_features_checked": 2,
        }

    monkeypatch.setattr(scheduled_tasks, "build_training_dataset", _build_dataset)
    monkeypatch.setattr(scheduled_tasks, "check_dataset_drift", _compute_drift)
    monkeypatch.setattr(
        scheduled_tasks,
        "load_baseline_distributions",
        lambda baseline_dir: {"model_version": "v_thread_test"},
    )
    monkeypatch.setattr(scheduled_tasks, "_record_drift_log", lambda **kwargs: None)
    monkeypatch.setattr(scheduled_tasks, "notify_drift_detected", AsyncMock())
    monkeypatch.setattr(
        scheduled_tasks, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )

    outcome = await scheduled_tasks.drift_monitor_task({}, evaluation_window_days=7)

    assert outcome["status"] == "success"
    expected = 2 * len(CATEGORY_MODEL_NAMES)
    assert len(seen) == expected
    for index in range(0, expected, 2):
        build_kind, build_thread = seen[index]
        drift_kind, drift_thread = seen[index + 1]
        assert build_kind == "build"
        assert drift_kind == "drift"
        # 프레임 생성과 PSI 계산이 모두 이벤트 루프 밖에서 실행됩니다.
        assert build_thread != loop_thread
        assert drift_thread != loop_thread
        # 두 계산이 같은 워커 스레드에서 수행되어 프레임이 루프로 돌아오지 않습니다.
        assert build_thread == drift_thread
