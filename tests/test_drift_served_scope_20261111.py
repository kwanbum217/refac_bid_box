"""드리프트 감시 범위를 서빙 매핑에 맞춘 회귀 시험 (I-ai F-05).

감시 대상은 서빙 매핑(CATEGORY_DEFAULT_MODELS)이고, 학습 매핑(CATEGORY_MODEL_NAMES)
에만 있는 미서빙 분야는 baseline 을 읽지 않고 not_served 로 남습니다. 실패 집계에도
영향을 주지 않습니다. 서빙·학습 모델 이름이 어긋나면 경고를 남기고 서빙 이름을 씁니다.
"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import Any
from unittest.mock import AsyncMock

import pytest

from src.ml.model_registry import CATEGORY_DEFAULT_MODELS
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks import scheduled_tasks, worker
from src.tasks.scheduled_tasks import ScheduleClaimResult, ScheduleClaimStatus

UNSERVED_CATEGORY = "Cnstwk"
UNSERVED_MODEL_NAME = "cnstwk_institution_v1"


class GuardLog:
    """가드 진입만 기록하고 잠금은 잡지 않는 대체 가드입니다."""

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


def _isolate_schedule_io(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(worker, "heavy_task_guard", GuardLog())
    monkeypatch.setattr(scheduled_tasks, "_acquire_drift_monitor_claim", _acquired_claim)
    monkeypatch.setattr(scheduled_tasks.settings, "ML_DRIFT_MONITOR_ENABLED", True)
    monkeypatch.setattr(worker, "record_schedule_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", lambda *args, **kwargs: True)
    monkeypatch.setattr(scheduled_tasks, "notify_task_failure", AsyncMock())
    monkeypatch.setattr(scheduled_tasks, "notify_drift_detected", AsyncMock())


def _spy_baseline_loader(monkeypatch: pytest.MonkeyPatch, *, found: bool) -> list[str]:
    """baseline 조회 경로를 기록하고 존재 여부를 흉내 냅니다."""
    calls: list[str] = []

    def _load(baseline_dir: Any) -> dict[str, Any]:
        calls.append(str(baseline_dir))
        return {"model_version": "v_20261111"} if found else {}

    monkeypatch.setattr(scheduled_tasks, "load_baseline_distributions", _load)
    return calls


def test_served_mapping_has_no_construction_category() -> None:
    """공사는 여전히 학습 매핑에만 있고 서빙 매핑에는 없는 상태입니다."""
    assert UNSERVED_CATEGORY in CATEGORY_MODEL_NAMES
    assert CATEGORY_MODEL_NAMES[UNSERVED_CATEGORY] == UNSERVED_MODEL_NAME
    assert UNSERVED_CATEGORY not in CATEGORY_DEFAULT_MODELS


@pytest.mark.asyncio
async def test_drift_reads_baseline_only_for_served_categories(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """드리프트 감시가 서빙 분야의 baseline 만 읽고 공사 baseline 은 읽지 않습니다."""
    _isolate_schedule_io(monkeypatch)
    monkeypatch.setattr(scheduled_tasks, "_record_drift_log", lambda *args, **kwargs: None)
    calls = _spy_baseline_loader(monkeypatch, found=False)

    outcome = await scheduled_tasks.drift_monitor_task({}, registry_dir="/registry")

    read_model_names = {path.split("/")[-2] for path in calls}
    assert read_model_names == set(CATEGORY_DEFAULT_MODELS.values())
    assert UNSERVED_MODEL_NAME not in read_model_names
    assert set(outcome["categories"]) >= set(CATEGORY_DEFAULT_MODELS)


@pytest.mark.asyncio
async def test_served_categories_are_monitored_by_serving_model_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """감시 경로와 결과 모델 이름이 서빙 매핑 값을 그대로 따릅니다."""
    _isolate_schedule_io(monkeypatch)
    monkeypatch.setattr(scheduled_tasks, "_record_drift_log", lambda *args, **kwargs: None)
    calls = _spy_baseline_loader(monkeypatch, found=False)

    outcome = await scheduled_tasks.drift_monitor_task({}, registry_dir="/registry")

    for category, model_name in CATEGORY_DEFAULT_MODELS.items():
        assert f"/registry/{model_name}/baseline" in calls
        assert outcome["categories"][category]["model_name"] == model_name


@pytest.mark.asyncio
async def test_unserved_category_is_not_served_and_not_counted_as_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """공사는 not_served 로 남고 실패 집계에 영향을 주지 않습니다."""
    _isolate_schedule_io(monkeypatch)
    recorded: list[dict[str, Any]] = []

    def _record(**kwargs: Any) -> None:
        recorded.append(kwargs)

    monkeypatch.setattr(scheduled_tasks, "_record_drift_log", _record)
    _spy_baseline_loader(monkeypatch, found=False)

    outcome = await scheduled_tasks.drift_monitor_task({}, registry_dir="/registry")

    unserved = outcome["categories"][UNSERVED_CATEGORY]
    assert unserved["status"] == "not_served"
    assert unserved["reason"]
    assert outcome["status"] == "success"
    assert all(item.get("status") != "failed" for item in outcome["categories"].values())
    assert UNSERVED_MODEL_NAME not in {entry.get("champion_version") for entry in recorded}


@pytest.mark.asyncio
async def test_served_failure_keeps_unserved_out_of_failure_verdict(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """서빙 분야가 실패해도 미서빙 분야는 실패로 집계되지 않습니다."""
    _isolate_schedule_io(monkeypatch)
    monkeypatch.setattr(scheduled_tasks, "_record_drift_log", lambda *args, **kwargs: None)
    _spy_baseline_loader(monkeypatch, found=True)
    monkeypatch.setattr(
        scheduled_tasks, "apply_drift_persistence", lambda verdict, previous: verdict
    )

    failing = sorted(CATEGORY_DEFAULT_MODELS)[0]

    def _assess(category: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        if category == failing:
            raise RuntimeError("드리프트 계산 실패")
        return {
            "status": "STABLE",
            "recent_samples": 10,
            "drift_feature_count": 0,
            "drift_features": [],
            "total_features_checked": 5,
            "window_drift": False,
        }

    monkeypatch.setattr(scheduled_tasks, "_compute_drift_assessment_thread", _assess)

    outcome = await scheduled_tasks.drift_monitor_task({}, registry_dir="/registry")

    assert outcome["categories"][UNSERVED_CATEGORY]["status"] == "not_served"
    assert outcome["status"] == "partial_failure"
    assert outcome["categories"][failing]["status"] == "failed"
    failed = {name for name, res in outcome["categories"].items() if res["status"] == "failed"}
    assert failed == {failing}


@pytest.mark.asyncio
async def test_name_mismatch_warns_and_uses_serving_name(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """서빙·학습 모델 이름이 어긋나면 경고를 남기고 서빙 이름으로 감시합니다."""
    _isolate_schedule_io(monkeypatch)
    monkeypatch.setattr(scheduled_tasks, "_record_drift_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scheduled_tasks,
        "CATEGORY_DEFAULT_MODELS",
        {"Thng": "quantum_leap_v25_pro", "Servc": "servc_served_next"},
    )
    monkeypatch.setattr(
        scheduled_tasks,
        "CATEGORY_MODEL_NAMES",
        {
            "Thng": "quantum_leap_v25_pro",
            "Servc": "servc_institution_v1",
            UNSERVED_CATEGORY: UNSERVED_MODEL_NAME,
        },
    )
    calls = _spy_baseline_loader(monkeypatch, found=False)

    with caplog.at_level(logging.WARNING, logger=scheduled_tasks.__name__):
        outcome = await scheduled_tasks.drift_monitor_task({}, registry_dir="/registry")

    assert "/registry/servc_served_next/baseline" in calls
    assert "/registry/servc_institution_v1/baseline" not in calls
    assert outcome["categories"]["Servc"]["model_name"] == "servc_served_next"

    warnings = [
        record.getMessage() for record in caplog.records if record.levelno >= logging.WARNING
    ]
    assert any(
        "servc_served_next" in message and "servc_institution_v1" in message for message in warnings
    )
