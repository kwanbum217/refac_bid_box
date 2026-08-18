"""
tests/test_task_offload_retrain.py

재학습 태스크의 동기 I/O 및 CPU 바운드 연산(데이터셋 빌드, 모델 학습, DB/디스크 접근)이
이벤트 루프 스레드가 아닌 worker thread(to_thread)로 오프로드되는지 검증합니다.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pandas as pd
import pytest

from src.tasks import retrain_task
from src.tasks.retrain_task import run_retrain_pipeline_task


def _assert_no_running_loop() -> None:
    """오프로드된 스레드에서는 asyncio.get_running_loop() 가 RuntimeError 를 발생시켜야 합니다."""
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    assert not in_loop, "동기 작업이 이벤트 루프 스레드에서 직접 실행되었습니다 (to_thread 미적용)."


@pytest.mark.asyncio
async def test_retrain_pipeline_task_offloaded_to_thread(monkeypatch: pytest.MonkeyPatch) -> None:
    """build_training_dataset, train_and_register, _load_champion_metrics, _record 가 모두 이벤트 루프 밖에서 실행되는지 검증."""
    call_log: list[str] = []

    def mock_build_training_dataset(*args, **kwargs):
        _assert_no_running_loop()
        call_log.append("build_training_dataset")
        return pd.DataFrame({"sample": [1, 2, 3]})

    def mock_load_champion_metrics(*args, **kwargs):
        _assert_no_running_loop()
        call_log.append("_load_champion_metrics")
        return "1.0.0", {"rmse": 0.05}

    mock_trainer = MagicMock()
    mock_trainer.model_name = "thng_model"
    mock_trainer.registry_dir = "ml_registry"

    def mock_train_and_register(df):
        _assert_no_running_loop()
        call_log.append("train_and_register")
        return {
            "version": "1.0.1",
            "samples_count": 3,
            "metrics": {"rmse": 0.04},
            "holdout_is_overfit": False,
        }

    mock_trainer.train_and_register.side_effect = mock_train_and_register

    def mock_record(*args, **kwargs):
        _assert_no_running_loop()
        call_log.append("_record")

    mock_db = MagicMock()

    monkeypatch.setattr(retrain_task, "SessionLocal", lambda: mock_db)
    monkeypatch.setattr(retrain_task, "build_training_dataset", mock_build_training_dataset)
    monkeypatch.setattr(retrain_task, "_load_champion_metrics", mock_load_champion_metrics)
    monkeypatch.setattr(
        retrain_task.ModelTrainer, "for_category", lambda cat, registry_dir: mock_trainer
    )
    monkeypatch.setattr(retrain_task, "_record", mock_record)
    monkeypatch.setattr(
        retrain_task,
        "compare_champion_vs_challenger",
        lambda c, ch: {"recommendation": "PROMOTE_CHALLENGER"},
    )
    monkeypatch.setattr(retrain_task, "notify_retrain_result", AsyncMock())
    monkeypatch.setattr(retrain_task, "notify_empty_training_data", AsyncMock())
    monkeypatch.setattr(retrain_task, "notify_task_failure", AsyncMock())

    result = await run_retrain_pipeline_task(
        ctx={},
        trigger_source="manual",
        category_code="Thng",
        require_announcement=True,
    )

    assert result["status"] == "success"
    assert result["version"] == "1.0.1"

    # 순서 검증: champion 지표를 학습 전에 읽는지 검증
    assert "build_training_dataset" in call_log
    assert "_load_champion_metrics" in call_log
    assert "train_and_register" in call_log
    assert "_record" in call_log

    idx_load_champ = call_log.index("_load_champion_metrics")
    idx_train = call_log.index("train_and_register")
    assert idx_load_champ < idx_train, (
        "champion 지표는 학습(train_and_register) 전에 읽어야 합니다."
    )


@pytest.mark.asyncio
async def test_retrain_pipeline_empty_dataset_offloaded(monkeypatch: pytest.MonkeyPatch) -> None:
    """데이터셋이 비었을 때도 _record 가 이벤트 루프 밖에서 실행되는지 검증."""
    call_log: list[str] = []

    def mock_build_training_dataset(*args, **kwargs):
        _assert_no_running_loop()
        call_log.append("build_training_dataset")
        return pd.DataFrame()

    def mock_record(*args, **kwargs):
        _assert_no_running_loop()
        call_log.append("_record")

    mock_db = MagicMock()

    monkeypatch.setattr(retrain_task, "SessionLocal", lambda: mock_db)
    monkeypatch.setattr(retrain_task, "build_training_dataset", mock_build_training_dataset)
    monkeypatch.setattr(retrain_task, "_record", mock_record)
    monkeypatch.setattr(retrain_task, "notify_empty_training_data", AsyncMock())

    result = await run_retrain_pipeline_task(
        ctx={},
        trigger_source="manual",
        category_code="Thng",
    )

    assert result["status"] == "skipped"
    assert call_log == ["build_training_dataset", "_record"]
