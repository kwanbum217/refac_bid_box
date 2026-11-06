"""ML 운영 감사 A2·A3·A4 회귀 시험.

A2: 주간 재학습·드리프트 크론 본문이 heavy_task_guard 안에서 실행되고,
    run_retrain_pipeline_task 가 직접 디스패치 때도 무거운 작업 타임아웃을 받는다.
A3: 드리프트 감시의 카테고리 단위 실패가 알림으로 올라가고 나머지는 계속 처리된다.
A4: 야간 파생 집계 후속 단계 실패가 알림으로 올라간다.

실제 학습·드리프트·DB·Redis 는 호출하지 않고 경계만 monkeypatch 로 대체한다.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks import scheduled_tasks, worker
from src.tasks.scheduled_tasks import ScheduleClaimResult, ScheduleClaimStatus


class GuardLog:
    """가드 진입과 본문 실행 순서를 기록하는 대체 가드입니다."""

    def __init__(self) -> None:
        self.events: list[str] = []

    @asynccontextmanager
    async def __call__(self, task_name: str):
        self.events.append(f"guard:{task_name}")
        yield


def _acquired_claim(*args: Any, **kwargs: Any) -> ScheduleClaimResult:
    return ScheduleClaimResult(
        status=ScheduleClaimStatus.ACQUIRED,
        key="test:claim",
        owner="test",
        ttl=3600,
        token="test-token",
    )


def _stable_verdict() -> dict[str, Any]:
    return {
        "status": "STABLE",
        "recent_samples": 10,
        "drift_feature_count": 0,
        "drift_features": [],
        "total_features_checked": 5,
        "window_drift": False,
    }


def _isolate_schedule_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "record_schedule_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", lambda *args, **kwargs: True)


# --------------------------------------------------------------------------- #
# A2: 무거운 작업 가드
# --------------------------------------------------------------------------- #


async def test_weekly_retrain_runs_body_inside_heavy_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = GuardLog()
    monkeypatch.setattr(worker, "heavy_task_guard", guard)
    monkeypatch.setattr(scheduled_tasks, "_acquire_weekly_retrain_claim", _acquired_claim)
    monkeypatch.setattr(scheduled_tasks.settings, "ML_WEEKLY_RETRAIN_ENABLED", True)
    _isolate_schedule_io(monkeypatch)

    async def fake_retrain(ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        guard.events.append(f"body:{kwargs['category_code']}")
        return {"status": "success"}

    monkeypatch.setattr(scheduled_tasks, "run_retrain_pipeline_task", fake_retrain)

    outcome = await scheduled_tasks.weekly_retrain_task({})

    assert outcome["status"] == "success"
    assert guard.events[0] == "guard:weekly_retrain_task"
    bodies = [event for event in guard.events if event.startswith("body:")]
    assert len(bodies) == len(CATEGORY_MODEL_NAMES)
    assert guard.events.index("guard:weekly_retrain_task") < guard.events.index(bodies[0])


async def test_drift_monitor_runs_body_inside_heavy_guard(monkeypatch: pytest.MonkeyPatch) -> None:
    guard = GuardLog()
    monkeypatch.setattr(worker, "heavy_task_guard", guard)
    monkeypatch.setattr(scheduled_tasks, "_acquire_drift_monitor_claim", _acquired_claim)
    monkeypatch.setattr(scheduled_tasks.settings, "ML_DRIFT_MONITOR_ENABLED", True)
    _isolate_schedule_io(monkeypatch)

    async def fake_body(
        ctx: dict[str, Any], evaluation_window_days: int, registry_dir: str
    ) -> dict[str, Any]:
        guard.events.append("body:drift")
        return {"status": "success", "categories": {}}

    monkeypatch.setattr(scheduled_tasks, "_run_drift_monitor", fake_body)

    outcome = await scheduled_tasks.drift_monitor_task({})

    assert outcome["status"] == "success"
    assert guard.events == ["guard:drift_monitor_task", "body:drift"]


def test_run_retrain_pipeline_task_is_heavy_task() -> None:
    assert "run_retrain_pipeline_task" in worker.HEAVY_TASK_NAMES


# --------------------------------------------------------------------------- #
# A3: 드리프트 카테고리 단위 실패 알림
# --------------------------------------------------------------------------- #


def _patch_drift_body(monkeypatch: pytest.MonkeyPatch, failing: str) -> None:
    monkeypatch.setattr(
        scheduled_tasks, "load_baseline_distributions", lambda _dir: {"model_version": "v1"}
    )
    monkeypatch.setattr(scheduled_tasks, "_record_drift_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scheduled_tasks, "apply_drift_persistence", lambda verdict, previous: verdict
    )

    def fake_assessment(
        category: str,
        start_at: Any,
        end_at: Any,
        baseline_dist: dict[str, Any],
        evaluation_window_days: int,
    ) -> dict[str, Any]:
        if category == failing:
            raise RuntimeError("드리프트 계산 실패")
        return _stable_verdict()

    monkeypatch.setattr(scheduled_tasks, "_compute_drift_assessment_thread", fake_assessment)
    monkeypatch.setattr(scheduled_tasks, "notify_drift_detected", AsyncMock())


async def _run_drift_with_patches(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[str, dict[str, Any], AsyncMock]:
    monkeypatch.setattr(worker, "heavy_task_guard", GuardLog())
    monkeypatch.setattr(scheduled_tasks, "_acquire_drift_monitor_claim", _acquired_claim)
    monkeypatch.setattr(scheduled_tasks.settings, "ML_DRIFT_MONITOR_ENABLED", True)
    _isolate_schedule_io(monkeypatch)
    failing = sorted(CATEGORY_MODEL_NAMES)[0]
    _patch_drift_body(monkeypatch, failing)
    notify = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "notify_task_failure", notify)
    outcome = await scheduled_tasks.drift_monitor_task({})
    return failing, outcome, notify


async def test_drift_category_failure_notifies_once_and_continues(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing, outcome, notify = await _run_drift_with_patches(monkeypatch)

    assert set(outcome["categories"]) == set(CATEGORY_MODEL_NAMES)
    assert outcome["categories"][failing]["status"] == "failed"
    assert outcome["status"] == "partial_failure"
    assert notify.await_count == 1
    assert notify.await_args.args[0] == "drift_monitor_task"
    assert failing in str(notify.await_args.kwargs["detail"])


async def test_drift_category_failure_alert_raises_but_task_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failing = sorted(CATEGORY_MODEL_NAMES)[0]
    monkeypatch.setattr(worker, "heavy_task_guard", GuardLog())
    monkeypatch.setattr(scheduled_tasks, "_acquire_drift_monitor_claim", _acquired_claim)
    monkeypatch.setattr(scheduled_tasks.settings, "ML_DRIFT_MONITOR_ENABLED", True)
    _isolate_schedule_io(monkeypatch)
    _patch_drift_body(monkeypatch, failing)
    monkeypatch.setattr(
        scheduled_tasks,
        "notify_task_failure",
        AsyncMock(side_effect=RuntimeError("웹훅 장애")),
    )

    outcome = await scheduled_tasks.drift_monitor_task({})

    assert outcome["categories"][failing]["status"] == "failed"
    assert set(outcome["categories"]) == set(CATEGORY_MODEL_NAMES)


# --------------------------------------------------------------------------- #
# A4: 야간 파생 집계 후속 단계 실패 알림
# --------------------------------------------------------------------------- #


def _patch_nightly(monkeypatch: pytest.MonkeyPatch, failing_followups: dict[str, str]) -> AsyncMock:
    monkeypatch.setattr(worker, "record_schedule_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduled_tasks.settings, "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED", True)
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", _acquired_claim)
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", lambda *args, **kwargs: True)
    monkeypatch.setattr(
        scheduled_tasks, "_create_scheduled_execution", lambda *args, **kwargs: "exec-1"
    )

    async def fake_pipeline(ctx: dict[str, Any], **kwargs: Any) -> dict[str, Any]:
        return {"status": "success"}

    monkeypatch.setattr(scheduled_tasks, "run_automation_pipeline", fake_pipeline)

    def followup(name: str):
        status = failing_followups.get(name, "success")
        return lambda: {"status": status, "error": "집계 실패" if status == "failed" else None}

    monkeypatch.setattr(
        scheduled_tasks, "_rebuild_ranking_snapshots", followup("ranking_snapshots")
    )
    monkeypatch.setattr(
        scheduled_tasks, "_rebuild_compare_stats_snapshots", followup("compare_stats_snapshots")
    )
    monkeypatch.setattr(
        scheduled_tasks, "_rebuild_institution_stats", followup("institution_stats")
    )
    monkeypatch.setattr(scheduled_tasks, "_check_mysql_stats_freshness", lambda: {"status": "ok"})
    monkeypatch.setattr(scheduled_tasks, "_check_restore_drill_freshness", lambda: {"status": "ok"})
    monkeypatch.setattr(scheduled_tasks, "_check_search_index_parity", lambda: {"status": "ok"})

    notify = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "notify_followup_failures", notify)
    return notify


async def test_nightly_followup_failure_notifies_once(monkeypatch: pytest.MonkeyPatch) -> None:
    notify = _patch_nightly(monkeypatch, {"institution_stats": "failed"})

    outcome = await scheduled_tasks.nightly_schedule_task({})

    assert outcome["status"] == "partial_success"
    assert outcome["failed_followups"] == ["institution_stats"]
    assert notify.await_count == 1
    assert notify.await_args.args[0] == ["institution_stats"]


async def test_nightly_success_sends_no_followup_alert(monkeypatch: pytest.MonkeyPatch) -> None:
    notify = _patch_nightly(monkeypatch, {})

    outcome = await scheduled_tasks.nightly_schedule_task({})

    assert outcome["status"] == "success"
    assert "failed_followups" not in outcome
    assert notify.await_count == 0


async def test_nightly_followup_alert_raises_but_task_returns(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    notify = _patch_nightly(monkeypatch, {"ranking_snapshots": "failed"})
    notify.side_effect = RuntimeError("웹훅 장애")

    outcome = await scheduled_tasks.nightly_schedule_task({})

    assert outcome["status"] == "partial_success"
    assert outcome["failed_followups"] == ["ranking_snapshots"]
