"""
tests/test_retrain_category_guard.py

재학습 파이프라인의 카테고리 필수 가드, 주간 재학습 fan-out 장애 격리,
아티팩트 staging 원자적 저장 및 부분 아티팩트 배제 검증.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.ml.dataset import build_training_dataset
from src.ml.promotion import latest_version
from src.ml.trainer import ModelTrainer
from src.ml.training_config import (
    CATEGORY_MODEL_NAMES,
    model_name_for_category,
)
from src.tasks.retrain_task import run_retrain_pipeline_task
from src.tasks.scheduled_tasks import weekly_retrain_task

# ---------------------------------------------------------------------------
# 1. 카테고리 가드 검증: None / 빈값 / 미등록 코드 명시적 거부
# ---------------------------------------------------------------------------


def test_model_name_for_category_rejects_none_and_empty():
    """category_code 가 None 또는 빈값이면 ValueError 를 내고 등록 목록을 안내합니다."""
    for invalid_code in (None, "", "   "):
        with pytest.raises(ValueError) as exc_info:
            model_name_for_category(invalid_code)
        err_msg = str(exc_info.value)
        assert "CATEGORY_MODEL_NAMES" in err_msg or "등록" in err_msg
        for cat in CATEGORY_MODEL_NAMES:
            assert cat in err_msg


def test_model_name_for_category_rejects_unregistered_code():
    """등록되지 않은 카테고리 코드는 ValueError 를 발생시킵니다."""
    with pytest.raises(ValueError) as exc_info:
        model_name_for_category("UnknownCategory")
    err_msg = str(exc_info.value)
    for cat in CATEGORY_MODEL_NAMES:
        assert cat in err_msg


def test_model_name_for_category_maps_valid_codes():
    """등록된 카테고리 코드는 올바른 모델 네임스페이스로 매핑됩니다."""
    for cat, expected_model in CATEGORY_MODEL_NAMES.items():
        assert model_name_for_category(cat) == expected_model


def test_build_training_dataset_rejects_none_and_invalid_category(isolated_db):
    """build_training_dataset 에서 category_code 가 None 이거나 미등록이면 거부합니다."""
    for invalid in (None, "", "UnknownCategory"):
        with pytest.raises(ValueError) as exc_info:
            build_training_dataset(isolated_db, category_code=invalid)
        err_msg = str(exc_info.value)
        for cat in CATEGORY_MODEL_NAMES:
            assert cat in err_msg


@pytest.mark.asyncio
async def test_run_retrain_pipeline_task_rejects_none_category():
    """run_retrain_pipeline_task 에서 category_code 가 None 이면 명시적으로 거부합니다."""
    for invalid in (None, "", "UnknownCategory"):
        with pytest.raises(ValueError) as exc_info:
            await run_retrain_pipeline_task({}, category_code=invalid)
        err_msg = str(exc_info.value)
        for cat in CATEGORY_MODEL_NAMES:
            assert cat in err_msg


# ---------------------------------------------------------------------------
# 2. 주간 재학습 fan-out 및 장애 격리 검증
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_weekly_retrain_fans_out_to_all_categories():
    """주간 재학습이 CATEGORY_MODEL_NAMES 의 모든 카테고리에 대해 독립 실행합니다."""
    executed_categories: list[str] = []

    async def fake_run_retrain(ctx, trigger_source="weekly_schedule", category_code=None, **kwargs):
        executed_categories.append(category_code)
        return {
            "status": "success",
            "category": category_code,
            "version": f"v_test_{category_code}",
        }

    with patch("src.tasks.scheduled_tasks.run_retrain_pipeline_task", side_effect=fake_run_retrain):
        outcome = await weekly_retrain_task({})

    assert outcome["status"] == "success"
    assert sorted(executed_categories) == sorted(CATEGORY_MODEL_NAMES.keys())
    assert len(outcome["categories"]) == len(CATEGORY_MODEL_NAMES)
    for cat in CATEGORY_MODEL_NAMES:
        assert outcome["categories"][cat]["status"] == "success"


@pytest.mark.asyncio
async def test_weekly_retrain_isolates_category_failure():
    """한 카테고리가 실패해도 나머지 카테고리는 중단 없이 계속 실행됩니다."""
    executed_categories: list[str] = []

    async def fake_run_retrain(ctx, trigger_source="weekly_schedule", category_code=None, **kwargs):
        executed_categories.append(category_code)
        if category_code == "Servc":
            raise RuntimeError("Servc 재학습 모의 실패")
        return {
            "status": "success",
            "category": category_code,
            "version": f"v_test_{category_code}",
        }

    with patch("src.tasks.scheduled_tasks.run_retrain_pipeline_task", side_effect=fake_run_retrain):
        outcome = await weekly_retrain_task({})

    # Servc 가 실패했더라도 Thng, Cnstwk 는 실행 완료
    assert sorted(executed_categories) == sorted(CATEGORY_MODEL_NAMES.keys())
    assert outcome["status"] == "partial_failure"
    assert outcome["categories"]["Servc"]["status"] == "failed"
    assert "Servc 재학습 모의 실패" in outcome["categories"]["Servc"]["error"]
    assert outcome["categories"]["Thng"]["status"] == "success"
    assert outcome["categories"]["Cnstwk"]["status"] == "success"


@pytest.mark.asyncio
async def test_weekly_retrain_disabled():
    """settings.ML_WEEKLY_RETRAIN_ENABLED=False 면 스케줄이 건너뜁니다."""
    with patch("src.tasks.scheduled_tasks.settings.ML_WEEKLY_RETRAIN_ENABLED", False):
        outcome = await weekly_retrain_task({})
    assert outcome["status"] == "skipped"
    assert outcome["reason"] == "disabled"


# ---------------------------------------------------------------------------
# 3. 원자적 아티팩트 저장 및 부분 아티팩트 배제 검증 (staging -> rename)
# ---------------------------------------------------------------------------


def test_atomic_artifact_saving_success(tmp_path):
    """정상 학습 시 아티팩트가 원자적으로 target_dir 에 저장되고 latest_version 에 잡힙니다."""
    df_raw = pd.DataFrame(
        [
            {
                "presumed_price": 1000.0 + i,
                "base_price": 990.0 + i,
                "winning_rate": 88.0 + (i % 3) * 0.1,
                "openg_dt": f"2024-{i + 1:02d}-01",
            }
            for i in range(10)
        ]
    )

    trainer_inst = ModelTrainer(
        model_name="quantum_leap_v25_pro",
        registry_dir=str(tmp_path),
        category_code="Thng",
    )
    meta = trainer_inst.train_and_register(df_raw)

    version = meta["version"]
    target_dir = tmp_path / "quantum_leap_v25_pro" / version
    assert target_dir.exists()
    assert (target_dir / "model.bin").exists()
    assert (target_dir / "metadata.json").exists()

    # staging 디렉터리가 남아있지 않아야 함
    staging_dirs = list((tmp_path / "quantum_leap_v25_pro").glob(".train_staging_*"))
    assert len(staging_dirs) == 0

    # latest_version 으로 정상 조회됨
    lv = latest_version("quantum_leap_v25_pro", registry_dir=tmp_path)
    assert lv == version


def test_atomic_artifact_saving_aborts_on_failure_leaves_no_partial_artifact(tmp_path):
    """학습/저장 중 오류 발생 시 불완전한 버전 디렉터리가 남지 않아 latest_version 으로 선택되지 않습니다."""
    df_raw = pd.DataFrame(
        [
            {
                "presumed_price": 1000.0 + i,
                "base_price": 990.0 + i,
                "winning_rate": 88.0 + (i % 3) * 0.1,
                "openg_dt": f"2024-{i + 1:02d}-01",
            }
            for i in range(10)
        ]
    )

    trainer_inst = ModelTrainer(
        model_name="quantum_leap_v25_pro",
        registry_dir=str(tmp_path),
        category_code="Thng",
    )

    # 1. 우선 기준 버전 v1 정상 학습
    meta1 = trainer_inst.train_and_register(df_raw)
    v1 = meta1["version"]
    assert latest_version("quantum_leap_v25_pro", registry_dir=tmp_path) == v1

    # 2. 두 번째 학습 시 중간에 예외 발생 모의 (예: metadata.json 저장 직전 실패)
    with (
        patch("src.ml.trainer.json.dump", side_effect=OSError("디스크 쓰기 모의 실패")),
        pytest.raises(OSError, match="디스크 쓰기 모의 실패"),
    ):
        trainer_inst.train_and_register(df_raw)

    # 3. 실패 후 검증:
    # staging 디렉터리 및 불완전한 버전 디렉터리가 남지 않아야 함
    model_dir = tmp_path / "quantum_leap_v25_pro"
    staging_dirs = list(model_dir.glob(".train_staging_*"))
    assert len(staging_dirs) == 0

    # 버전 디렉터리는 v1 하나만 존재해야 하며, 깨진 버전이 latest_version 이 되지 않아야 함
    version_dirs = [
        p.name for p in model_dir.iterdir() if p.is_dir() and not p.name.startswith(".")
    ]
    assert version_dirs == [v1]
    assert latest_version("quantum_leap_v25_pro", registry_dir=tmp_path) == v1
