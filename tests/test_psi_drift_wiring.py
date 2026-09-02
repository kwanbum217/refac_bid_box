"""
tests/test_psi_drift_wiring.py

PSI 드리프트 모니터링 운영 배선 검증 테스트.
- 학습 시 baseline 아티팩트 원자적 저장 및 실패 시 불변 검증
- Arq Worker 크론 및 함수 등록 검증
- 표본 부족(100건 미만) 시 판정 보류(INSUFFICIENT_DATA) 검증
- 드리프트 감지(PSI >= 0.2) 시 알림 발신 및 retrain_logs 기록 검증
- 자동 재학습·자동 승격 미발생(인간 판단 위임) 검증
- Single Source of Truth features.py 활용 검증
"""

from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from src.app.models.predictions import RetrainLog
from src.ml.monitoring import (
    InsufficientSampleError,
    calculate_categorical_psi,
    calculate_psi,
    check_dataset_drift,
    check_feature_drift,
    load_baseline_distributions,
    save_baseline_distributions,
)
from src.ml.trainer import ModelTrainer
from src.tasks.scheduled_tasks import drift_monitor_task
from src.tasks.worker import WorkerSettings


def test_baseline_saved_on_training_success(tmp_path):
    """학습 성공 시 ml_registry/{model_name}/baseline/ 에 분포 아티팩트와 메타데이터가 저장됩니다."""
    np.random.seed(42)
    sample_size = 120
    df_raw = pd.DataFrame(
        [
            {
                "presumed_price": 1000.0 + i * 10,
                "base_price": 990.0 + i * 10,
                "winning_rate": 88.0 + (i % 5) * 0.2,
                "openg_dt": f"2024-{(i % 12) + 1:02d}-01",
                "srvce_div_nm": "일반용역" if i % 2 == 0 else "기술용역",
            }
            for i in range(sample_size)
        ]
    )

    trainer = ModelTrainer(model_name="test_model", registry_dir=str(tmp_path))
    metadata = trainer.train_and_register(df_raw)

    assert metadata["status"] == "challenger"
    version = metadata["version"]

    version_baseline = tmp_path / "test_model" / version / "baseline"
    assert (version_baseline / "feature_distributions_v1.json").exists()

    latest_baseline = tmp_path / "test_model" / "baseline"
    assert (latest_baseline / "feature_distributions_v1.json").exists()
    assert (latest_baseline / "metadata.json").exists()

    dist = load_baseline_distributions(latest_baseline)
    assert dist is not None
    assert dist["schema_version"] == 1
    assert dist["model_name"] == "test_model"
    assert dist["model_version"] == version
    assert dist["training_samples"] == sample_size
    assert "log_price" in dist["features"]
    assert dist["features"]["log_price"]["type"] == "numeric"
    assert "histogram" in dist["features"]["log_price"]
    assert "quantiles" in dist["features"]["log_price"]
    assert dist["psi_config"]["min_samples_per_feature"] == 100


def test_baseline_not_saved_on_training_failure(tmp_path, monkeypatch):
    """학습 실패 시 baseline 디렉터리가 생성되거나 갱신되지 않습니다."""
    df_raw = pd.DataFrame(
        [
            {"presumed_price": 1000.0, "base_price": 990.0, "winning_rate": 88.5},
            {"presumed_price": 2000.0, "base_price": 1980.0, "winning_rate": 87.9},
        ]
    )

    trainer = ModelTrainer(model_name="fail_model", registry_dir=str(tmp_path))

    def _mock_refit_fail(*args, **kwargs):
        raise RuntimeError("학습 재적합 강제 실패")

    monkeypatch.setattr("src.ml.trainer._refit_on_full", _mock_refit_fail)

    with pytest.raises(RuntimeError, match="학습 재적합 강제 실패"):
        trainer.train_and_register(df_raw)

    baseline_dir = tmp_path / "fail_model" / "baseline"
    assert not baseline_dir.exists()

    staging_dirs = list((tmp_path / "fail_model").glob(".train_staging_*"))
    assert len(staging_dirs) == 0


def test_baseline_atomic_update_preserves_integrity(tmp_path):
    """두 번째 학습 성공 시 baseline 디렉터리가 임시 staging 잔재 없이 원자적으로 갱신됩니다."""
    np.random.seed(42)
    df_raw = pd.DataFrame(
        [
            {
                "presumed_price": 1000.0 + i,
                "base_price": 990.0 + i,
                "winning_rate": 88.0 + (i % 5) * 0.2,
                "openg_dt": f"2024-{(i % 12) + 1:02d}-01",
            }
            for i in range(120)
        ]
    )

    trainer = ModelTrainer(model_name="atomic_model", registry_dir=str(tmp_path))
    meta1 = trainer.train_and_register(df_raw)
    dist1 = load_baseline_distributions(tmp_path / "atomic_model" / "baseline")
    assert dist1["model_version"] == meta1["version"]

    meta2 = trainer.train_and_register(df_raw)
    dist2 = load_baseline_distributions(tmp_path / "atomic_model" / "baseline")
    assert dist2["model_version"] == meta2["version"]
    assert meta2["version"] != meta1["version"]

    staging_files = list((tmp_path / "atomic_model").glob(".*staging*"))
    assert len(staging_files) == 0


def test_insufficient_samples_raises_and_stops_false_stable():
    """표본이 100건 미만이면 STABLE 로 승격하지 않고 INSUFFICIENT_DATA 로 보류합니다."""
    small_exp = np.random.normal(0, 1, 50)
    small_act = np.random.normal(0, 1, 50)

    with pytest.raises(InsufficientSampleError, match="PSI 계산 표본 부족"):
        calculate_psi(small_exp, small_act, min_samples=100)

    res = check_feature_drift(small_exp, small_act, min_samples=100)
    assert res["action"] == "INSUFFICIENT_DATA"
    assert res["drift_detected"] is None
    assert res["psi_value"] is None


def test_categorical_psi_calculation():
    """범주형 특징 PSI 가 올바르게 계산됩니다."""
    exp_counts = {"일반용역": 600, "기술용역": 400}
    act_counts_stable = {"일반용역": 610, "기술용역": 390}
    psi_stable = calculate_categorical_psi(exp_counts, act_counts_stable, min_samples=100)
    assert psi_stable < 0.1

    act_counts_drift = {"일반용역": 100, "기술용역": 900}
    psi_drift = calculate_categorical_psi(exp_counts, act_counts_drift, min_samples=100)
    assert psi_drift >= 0.2


def test_check_dataset_drift_multi_feature(tmp_path):
    """다차원 데이터셋 드리프트 검사에서 한 특징이라도 0.2 초과 시 TRIGGER_RETRAIN 을 반환합니다."""
    np.random.seed(42)
    n_samples = 150

    df_train = pd.DataFrame(
        {
            "log_price": np.random.normal(14.0, 1.0, n_samples),
            "inst_hist_rate": np.random.normal(0.92, 0.02, n_samples),
            "srvce_div_nm": ["일반용역"] * 100 + ["기술용역"] * 50,
        }
    )

    baseline_dist = save_baseline_distributions(
        df_feat=df_train,
        feature_columns=["log_price", "inst_hist_rate", "srvce_div_nm"],
        target_dir=tmp_path / "baseline",
        model_name="test_model",
        model_version="v_20260901_001",
    )

    # 1. 안정 데이터셋
    df_stable = pd.DataFrame(
        {
            "log_price": np.random.normal(14.0, 1.0, n_samples),
            "inst_hist_rate": np.random.normal(0.92, 0.02, n_samples),
            "srvce_div_nm": ["일반용역"] * 95 + ["기술용역"] * 55,
        }
    )
    result_stable = check_dataset_drift(baseline_dist, df_stable)
    assert result_stable["status"] == "STABLE"
    assert result_stable["overall_action"] == "STABLE"
    assert result_stable["drift_feature_count"] == 0

    # 2. 드리프트 데이터셋 (log_price 급변)
    df_drift = pd.DataFrame(
        {
            "log_price": np.random.normal(20.0, 3.0, n_samples),
            "inst_hist_rate": np.random.normal(0.92, 0.02, n_samples),
            "srvce_div_nm": ["일반용역"] * 95 + ["기술용역"] * 55,
        }
    )
    result_drift = check_dataset_drift(baseline_dist, df_drift)
    assert result_drift["status"] == "DRIFT_DETECTED"
    assert result_drift["overall_action"] == "TRIGGER_RETRAIN"
    assert result_drift["drift_feature_count"] >= 1
    assert any(f["feature"] == "log_price" for f in result_drift["drift_features"])


def test_worker_settings_cron_jobs_wired():
    """WorkerSettings 에 drift_monitor_task 가 04:00 크론 및 함수로 등록되어 있습니다."""
    assert drift_monitor_task in WorkerSettings.functions

    drift_crons = [
        job
        for job in WorkerSettings.cron_jobs
        if getattr(job, "coroutine", None) == drift_monitor_task
    ]
    assert len(drift_crons) == 1
    cron_job = drift_crons[0]
    assert getattr(cron_job, "hour", None) == {4} or getattr(cron_job, "hour", None) == 4
    assert getattr(cron_job, "minute", None) == {0} or getattr(cron_job, "minute", None) == 0


@pytest.mark.asyncio
async def test_drift_monitor_task_disabled_by_default(isolated_db, monkeypatch):
    """기본값에서 ML_DRIFT_MONITOR_ENABLED 가 False 이면 스킵됩니다."""
    monkeypatch.setenv("ML_DRIFT_MONITOR_ENABLED", "0")

    outcome = await drift_monitor_task({})
    assert outcome["status"] == "skipped"
    assert outcome["reason"] == "disabled"


@pytest.mark.asyncio
async def test_drift_monitor_task_records_and_notifies(isolated_db, tmp_path, monkeypatch):
    """드리프트 감지 시 retrain_logs 에 기록되고 notify_drift_detected 가 호출되며 자동 재학습은 발화하지 않습니다."""
    monkeypatch.setenv("ML_DRIFT_MONITOR_ENABLED", "1")
    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", lambda: isolated_db)

    np.random.seed(42)
    n_samples = 150

    # mock baseline
    df_train = pd.DataFrame(
        {
            "presumed_price": [1000.0] * n_samples,
            "base_price": [990.0] * n_samples,
            "winning_rate": [88.0] * n_samples,
            "openg_dt": ["2024-01-01"] * n_samples,
            "srvce_div_nm": ["일반용역"] * n_samples,
            "log_price": np.random.normal(10.0, 0.5, n_samples),
        }
    )

    from src.ml.training_config import CATEGORY_MODEL_NAMES

    for _category, model_name in CATEGORY_MODEL_NAMES.items():
        base_dir = tmp_path / model_name / "baseline"
        save_baseline_distributions(
            df_feat=df_train,
            feature_columns=["log_price", "srvce_div_nm"],
            target_dir=base_dir,
            model_name=model_name,
            model_version="v_20260901_001",
        )

    # 최근 평가 데이터 (드리프트 유도: log_price 25.0)
    df_recent_drift = pd.DataFrame(
        [
            {
                "presumed_price": 100_000_000.0,
                "base_price": 99_000_000.0,
                "winning_rate": 88.0,
                "openg_dt": "2026-08-01",
                "srvce_div_nm": "기술용역",
                "log_price": 25.0,
            }
            for _ in range(n_samples)
        ]
    )

    def _mock_build_dataset(db, category_code, **kwargs):
        return df_recent_drift

    monkeypatch.setattr("src.tasks.scheduled_tasks.build_training_dataset", _mock_build_dataset)

    mock_notify = AsyncMock()
    monkeypatch.setattr("src.tasks.scheduled_tasks.notify_drift_detected", mock_notify)

    mock_retrain = AsyncMock()
    monkeypatch.setattr("src.tasks.scheduled_tasks.run_retrain_pipeline_task", mock_retrain)

    outcome = await drift_monitor_task({}, evaluation_window_days=7, registry_dir=str(tmp_path))

    assert outcome["status"] == "success"
    # 알림 발신 확인
    assert mock_notify.await_count >= 1

    # 자동 재학습이나 승격은 절대 호출되지 않아야 함 (계약 준수)
    assert mock_retrain.await_count == 0

    # retrain_logs DB 확인
    logs = isolated_db.query(RetrainLog).filter(RetrainLog.trigger_source == "drift_monitor").all()
    assert len(logs) > 0
    drift_logs = [log_item for log_item in logs if log_item.status == "DRIFT_DETECTED"]
    assert len(drift_logs) > 0
    sample_log = drift_logs[0]
    assert sample_log.challenger_version == "v_20260901_001"  # baseline_version 으로 해석
    assert "drift_results" in sample_log.metrics_summary
