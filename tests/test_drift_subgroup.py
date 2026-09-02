"""
tests/test_drift_subgroup.py

PSI 드리프트 모니터링 lwlt 결측 집단(subgroup) 분리 검증 테스트.
- baseline 분리 저장: lwlt_rate_missing (0.0 / 1.0) 값별 by_lwlt_missing 구조 저장
- 집단별 임계값 적용: with_lwlt 0.2, missing_lwlt 0.25 (완화)
- 종합 판정: 두 집단 중 하나라도 TRIGGER_RETRAIN 시 전체 DRIFT_DETECTED / TRIGGER_RETRAIN
- 차별화 알림: missing_lwlt 단독 미달 시 결측 집단 드리프트 라벨 구분
- 독립 표본 검증: 100건 최소 표본 기준이 집단별로 독립 적용
- 하위 호환성: by_lwlt_missing 키가 없는 옛 baseline 도 예외 없이 기존 경로로 정상 판정
- 모델 일반화: lwlt_rate_missing 특징 유무로 동작하며 모델명 하드코딩 없음
- 자동화 안전: 자동 재학습이나 자동 승격으로 이어지지 않고 DB 스키마 변경 없음
"""

from unittest.mock import AsyncMock

import numpy as np
import pandas as pd
import pytest

from src.app.core.config import settings
from src.app.models.predictions import RetrainLog
from src.ml.monitoring import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_PSI_THRESHOLD_MISSING_LWLT,
    DEFAULT_PSI_THRESHOLD_WITH_LWLT,
    SUBGROUP_KEY_MISSING_LWLT,
    SUBGROUP_KEY_WITH_LWLT,
    check_dataset_drift,
    load_baseline_distributions,
    save_baseline_distributions,
)
from src.tasks.notifier import notify_drift_detected
from src.tasks.scheduled_tasks import drift_monitor_task


def test_baseline_saved_with_by_lwlt_missing_subgroups(tmp_path):
    """lwlt_rate_missing 특징이 있는 데이터 학습 시 by_lwlt_missing 에 0.0, 1.0 집단별 분포가 분리 저장됩니다."""
    np.random.seed(42)
    sample_size = 200

    df_train = pd.DataFrame(
        {
            "log_price": np.random.normal(14.0, 1.0, sample_size),
            "inst_hist_rate": np.random.normal(0.92, 0.02, sample_size),
            "lwlt_rate": [88.0] * 120 + [0.0] * 80,
            "lwlt_rate_missing": [0.0] * 120 + [1.0] * 80,
            "srvce_div_nm": ["일반용역"] * 140 + ["기술용역"] * 60,
        }
    )

    feature_cols = ["log_price", "inst_hist_rate", "lwlt_rate_missing", "srvce_div_nm"]
    target_dir = tmp_path / "servc_model" / "baseline"

    baseline_payload = save_baseline_distributions(
        df_feat=df_train,
        feature_columns=feature_cols,
        target_dir=target_dir,
        model_name="servc_model",
        model_version="v_20260902_001",
    )

    assert "by_lwlt_missing" in baseline_payload
    by_sub = baseline_payload["by_lwlt_missing"]
    assert SUBGROUP_KEY_WITH_LWLT in by_sub
    assert SUBGROUP_KEY_MISSING_LWLT in by_sub

    # with_lwlt (0.0) 집단
    assert by_sub[SUBGROUP_KEY_WITH_LWLT]["training_samples"] == 120
    assert "log_price" in by_sub[SUBGROUP_KEY_WITH_LWLT]["features"]
    assert by_sub[SUBGROUP_KEY_WITH_LWLT]["features"]["log_price"]["type"] == "numeric"

    # missing_lwlt (1.0) 집단
    assert by_sub[SUBGROUP_KEY_MISSING_LWLT]["training_samples"] == 80
    assert "log_price" in by_sub[SUBGROUP_KEY_MISSING_LWLT]["features"]
    assert by_sub[SUBGROUP_KEY_MISSING_LWLT]["features"]["log_price"]["type"] == "numeric"

    # 저장된 파일 확인
    loaded = load_baseline_distributions(target_dir)
    assert loaded is not None
    assert "by_lwlt_missing" in loaded
    assert loaded["by_lwlt_missing"]["0.0"]["training_samples"] == 120
    assert loaded["by_lwlt_missing"]["1.0"]["training_samples"] == 80
    assert loaded["psi_config"]["subgroup_thresholds"]["0.0"] == DEFAULT_PSI_THRESHOLD_WITH_LWLT
    assert loaded["psi_config"]["subgroup_thresholds"]["1.0"] == DEFAULT_PSI_THRESHOLD_MISSING_LWLT


def test_baseline_without_lwlt_missing_does_not_have_subgroups(tmp_path):
    """lwlt_rate_missing 특징이 없는 모델은 by_lwlt_missing 을 생성하지 않으며 모델명 하드코딩이 없습니다."""
    np.random.seed(42)
    sample_size = 150

    df_train = pd.DataFrame(
        {
            "log_price": np.random.normal(14.0, 1.0, sample_size),
            "inst_hist_rate": np.random.normal(0.92, 0.02, sample_size),
            "srvce_div_nm": ["일반물품"] * 100 + ["기타물품"] * 50,
        }
    )

    feature_cols = ["log_price", "inst_hist_rate", "srvce_div_nm"]
    target_dir = tmp_path / "thng_model" / "baseline"

    baseline_payload = save_baseline_distributions(
        df_feat=df_train,
        feature_columns=feature_cols,
        target_dir=target_dir,
        model_name="thng_model",
        model_version="v_20260902_002",
    )

    assert "by_lwlt_missing" not in baseline_payload

    # 단일 집단 평가 정상 동작
    df_recent = df_train.copy()
    result = check_dataset_drift(baseline_payload, df_recent)
    assert result["status"] == "STABLE"
    assert "by_subgroup" not in result or result.get("by_subgroup") is None


def test_backward_compatibility_old_baseline_without_by_lwlt_missing(tmp_path, caplog):
    """by_lwlt_missing 키가 없는 옛 baseline JSON 에서도 죽지 않고 기존 단일 방식으로 판정하며 로그를 남깁니다."""
    np.random.seed(42)
    sample_size = 200

    df_base = pd.DataFrame(
        {
            "log_price": np.random.normal(15.0, 0.5, sample_size),
            "lwlt_rate_missing": [0.0] * 100 + [1.0] * 100,
        }
    )

    baseline_payload = save_baseline_distributions(
        df_feat=df_base,
        feature_columns=["log_price", "lwlt_rate_missing"],
        target_dir=tmp_path / "baseline",
        model_name="legacy_model",
        model_version="v_legacy_001",
    )

    # 옛 baseline 형식 시뮬레이션: by_lwlt_missing 키 제거
    baseline_payload.pop("by_lwlt_missing", None)

    df_recent = df_base.copy()

    with caplog.at_level("INFO"):
        result = check_dataset_drift(baseline_payload, df_recent)

    assert result["status"] == "STABLE"
    assert result["overall_action"] == "STABLE"
    assert "by_subgroup" not in result
    # 로그 기록 확인
    assert any("by_lwlt_missing" in record.message for record in caplog.records)


def test_subgroup_drift_thresholds_and_relaxation(tmp_path):
    """with_lwlt 에는 0.2 임계가, missing_lwlt 에는 0.25 완화 임계가 적용됩니다."""
    np.random.seed(42)
    n_samples = 200

    # baseline 준비
    df_base = pd.DataFrame(
        {
            "log_price": np.random.normal(14.0, 1.0, n_samples),
            "lwlt_rate_missing": [0.0] * 100 + [1.0] * 100,
        }
    )

    baseline_dist = save_baseline_distributions(
        df_feat=df_base,
        feature_columns=["log_price", "lwlt_rate_missing"],
        target_dir=tmp_path / "baseline",
        model_name="servc_test",
        model_version="v_001",
    )

    # 1. missing_lwlt 집단에 완화된 변동 부여 (0.20 <= PSI < 0.25 사이: 기존 0.2 기준이면 드리프트이나 0.25 기준이라 STABLE)
    # log_price 평균을 14.0 -> 14.65 정도로 미세 이동
    df_recent_mild = pd.DataFrame(
        {
            "log_price": np.concatenate(
                [
                    np.random.normal(14.0, 1.0, 100),  # with_lwlt: 안정
                    np.random.normal(14.65, 1.0, 100),  # missing_lwlt: 약간 변동
                ]
            ),
            "lwlt_rate_missing": [0.0] * 100 + [1.0] * 100,
        }
    )

    result_mild = check_dataset_drift(baseline_dist, df_recent_mild)
    sub_0 = result_mild["by_subgroup"][SUBGROUP_KEY_WITH_LWLT]
    sub_1 = result_mild["by_subgroup"][SUBGROUP_KEY_MISSING_LWLT]

    assert sub_0["threshold"] == DEFAULT_PSI_THRESHOLD_WITH_LWLT  # 0.2
    assert sub_1["threshold"] == DEFAULT_PSI_THRESHOLD_MISSING_LWLT  # 0.25

    # missing_lwlt PSI 가 0.25 미만이면 STABLE 유지
    if (
        sub_1["drift_results"].get("log_price")
        and sub_1["drift_results"]["log_price"]["psi"] is not None
    ):
        psi_val = sub_1["drift_results"]["log_price"]["psi"]
        if 0.15 <= psi_val < 0.25:
            assert sub_1["status"] == "STABLE"

    # 2. missing_lwlt 집단에 큰 변동 부여 (PSI >= 0.25)
    df_recent_severe = pd.DataFrame(
        {
            "log_price": np.concatenate(
                [
                    np.random.normal(14.0, 1.0, 100),  # with_lwlt: 안정
                    np.random.normal(18.0, 2.0, 100),  # missing_lwlt: 심한 드리프트 (PSI > 0.5)
                ]
            ),
            "lwlt_rate_missing": [0.0] * 100 + [1.0] * 100,
        }
    )

    result_severe = check_dataset_drift(baseline_dist, df_recent_severe)
    sub_0_sev = result_severe["by_subgroup"][SUBGROUP_KEY_WITH_LWLT]
    sub_1_sev = result_severe["by_subgroup"][SUBGROUP_KEY_MISSING_LWLT]

    assert sub_0_sev["status"] == "STABLE"
    assert sub_1_sev["status"] == "DRIFT_DETECTED"
    assert result_severe["status"] == "DRIFT_DETECTED"
    assert result_severe["overall_action"] == "TRIGGER_RETRAIN"
    assert result_severe["drift_subgroup_type"] == "missing_lwlt_only"


def test_subgroup_either_group_triggers_overall_retrain(tmp_path):
    """두 집단 중 하나라도 임계를 넘으면 전체 모델이 TRIGGER_RETRAIN 이 됩니다."""
    np.random.seed(42)
    n_samples = 200

    df_base = pd.DataFrame(
        {
            "log_price": np.random.normal(14.0, 1.0, n_samples),
            "inst_hist_rate": np.random.normal(0.92, 0.02, n_samples),
            "lwlt_rate_missing": [0.0] * 100 + [1.0] * 100,
        }
    )

    baseline_dist = save_baseline_distributions(
        df_feat=df_base,
        feature_columns=["log_price", "inst_hist_rate", "lwlt_rate_missing"],
        target_dir=tmp_path / "baseline",
        model_name="servc_test",
        model_version="v_001",
    )

    # with_lwlt 만 드리프트 발생
    df_with_drift = pd.DataFrame(
        {
            "log_price": np.concatenate(
                [
                    np.random.normal(20.0, 3.0, 100),  # with_lwlt 드리프트
                    np.random.normal(14.0, 1.0, 100),  # missing_lwlt 안정
                ]
            ),
            "inst_hist_rate": np.random.normal(0.92, 0.02, n_samples),
            "lwlt_rate_missing": [0.0] * 100 + [1.0] * 100,
        }
    )

    res_with = check_dataset_drift(baseline_dist, df_with_drift)
    assert res_with["status"] == "DRIFT_DETECTED"
    assert res_with["overall_action"] == "TRIGGER_RETRAIN"
    assert res_with["drift_subgroup_type"] == "with_lwlt_only"

    # 양쪽 모두 드리프트 발생
    df_both_drift = pd.DataFrame(
        {
            "log_price": np.concatenate(
                [
                    np.random.normal(20.0, 3.0, 100),  # with_lwlt 드리프트
                    np.random.normal(22.0, 3.0, 100),  # missing_lwlt 드리프트
                ]
            ),
            "inst_hist_rate": np.random.normal(0.92, 0.02, n_samples),
            "lwlt_rate_missing": [0.0] * 100 + [1.0] * 100,
        }
    )

    res_both = check_dataset_drift(baseline_dist, df_both_drift)
    assert res_both["status"] == "DRIFT_DETECTED"
    assert res_both["overall_action"] == "TRIGGER_RETRAIN"
    assert res_both["drift_subgroup_type"] == "both"


def test_subgroup_independent_sample_size_check(tmp_path):
    """표본 부족 100건 기준은 집단별로 각각 독립 적용됩니다."""
    np.random.seed(42)
    df_base = pd.DataFrame(
        {
            "log_price": np.random.normal(14.0, 1.0, 200),
            "lwlt_rate_missing": [0.0] * 100 + [1.0] * 100,
        }
    )

    baseline_dist = save_baseline_distributions(
        df_feat=df_base,
        feature_columns=["log_price", "lwlt_rate_missing"],
        target_dir=tmp_path / "baseline",
        model_name="servc_test",
        model_version="v_001",
    )

    # with_lwlt 는 150건(>= 100), missing_lwlt 는 40건(< 100)
    df_skewed_samples = pd.DataFrame(
        {
            "log_price": np.random.normal(14.0, 1.0, 190),
            "lwlt_rate_missing": [0.0] * 150 + [1.0] * 40,
        }
    )

    res = check_dataset_drift(baseline_dist, df_skewed_samples, min_samples=DEFAULT_MIN_SAMPLES)
    sub_0 = res["by_subgroup"][SUBGROUP_KEY_WITH_LWLT]
    sub_1 = res["by_subgroup"][SUBGROUP_KEY_MISSING_LWLT]

    assert sub_0["status"] == "STABLE"
    assert sub_0["recent_samples"] == 150

    assert sub_1["status"] == "INSUFFICIENT_DATA"
    assert sub_1["recent_samples"] == 40
    assert "표본 부족" in sub_1["reason"]

    # 한 집단이라도 INSUFFICIENT_DATA 이고 드리프트가 없으면 전체 판정은 INSUFFICIENT_DATA
    assert res["status"] == "INSUFFICIENT_DATA"
    assert res["overall_action"] == "INSUFFICIENT_DATA"


@pytest.mark.asyncio
async def test_missing_lwlt_only_drift_notification_label(monkeypatch):
    """missing_lwlt 단독 미달 시 notify_drift_detected 에서 '결측 집단 드리프트' 라벨로 알림이 구분됩니다."""
    mock_notify = AsyncMock()
    monkeypatch.setattr("src.tasks.notifier.notify", mock_notify)

    drift_features = [
        {"feature": "log_price", "psi": 0.32, "sample_size": 120, "subgroup": "missing_lwlt"}
    ]
    drift_by_subgroup = {
        "0.0": {
            "status": "STABLE",
            "samples": 150,
            "threshold": 0.2,
            "drift_feature_count": 0,
        },
        "1.0": {
            "status": "DRIFT_DETECTED",
            "samples": 120,
            "threshold": 0.25,
            "drift_feature_count": 1,
        },
    }

    await notify_drift_detected(
        model_name="servc_institution_v1",
        model_version="v_20260902_001",
        drift_features=drift_features,
        total_features_checked=28,
        evaluation_window_days=7,
        baseline_version="v_20260902_001",
        recent_samples=270,
        drift_by_subgroup=drift_by_subgroup,
        drift_subgroup_type="missing_lwlt_only",
    )

    assert mock_notify.await_count == 1
    call_args = mock_notify.await_args
    title = call_args[0][0]
    body_lines = call_args[0][1]

    # 알림 제목에 결측 집단 명시
    assert "결측 집단 드리프트 감지" in title
    assert "missing_lwlt" in title

    # 알림 본문에 집단별 상태 및 라벨 포함
    body_text = "\n".join(body_lines)
    assert "missing_lwlt" in body_text
    assert "with_lwlt" in body_text
    assert "0.25" in body_text


@pytest.mark.asyncio
async def test_drift_monitor_task_end_to_end_subgroup(isolated_db, tmp_path, monkeypatch):
    """drift_monitor_task 정기 실행에서 Servc 모델의 집단 분리 평가 및 retrain_logs 기록, 자동 재학습 미발생 검증."""
    monkeypatch.setattr(settings, "ML_DRIFT_MONITOR_ENABLED", True)
    monkeypatch.setattr("src.tasks.scheduled_tasks.SessionLocal", lambda: isolated_db)

    np.random.seed(42)
    n_samples = 240

    price_stable = float(np.exp(10.0) - 1.0)
    price_drift = float(np.exp(25.0) - 1.0)

    # baseline 생성 (Servc 및 Thng 모델)
    df_train_servc = pd.DataFrame(
        {
            "presumed_price": [price_stable] * n_samples,
            "base_price": [price_stable * 0.99] * n_samples,
            "winning_rate": [88.0] * n_samples,
            "openg_dt": ["2024-01-01"] * n_samples,
            "srvce_div_nm": ["일반용역"] * n_samples,
            "log_price": [10.0] * n_samples,
            "lwlt_rate_missing": [0.0] * 120 + [1.0] * 120,
            "lwlt_rate": [88.0] * 120 + [0.0] * 120,
        }
    )

    from src.ml.training_config import CATEGORY_MODEL_NAMES

    for category, model_name in CATEGORY_MODEL_NAMES.items():
        base_dir = tmp_path / model_name / "baseline"
        feature_cols = (
            ["log_price", "srvce_div_nm", "lwlt_rate_missing"]
            if category == "Servc"
            else ["log_price", "srvce_div_nm"]
        )
        save_baseline_distributions(
            df_feat=df_train_servc,
            feature_columns=feature_cols,
            target_dir=base_dir,
            model_name=model_name,
            model_version="v_20260902_001",
        )

    # 최근 데이터: missing_lwlt 집단만 log_price 25.0 (price_drift) 으로 드리프트 유도
    df_recent = pd.DataFrame(
        [
            {
                "presumed_price": price_stable if i < 120 else price_drift,
                "base_price": (price_stable if i < 120 else price_drift) * 0.99,
                "winning_rate": 88.0,
                "openg_dt": "2026-08-01",
                "srvce_div_nm": "일반용역",
                "lwlt_rate": 88.0 if i < 120 else None,
            }
            for i in range(n_samples)
        ]
    )

    def _mock_build_dataset(db, category_code, **kwargs):
        return df_recent

    monkeypatch.setattr("src.tasks.scheduled_tasks.build_training_dataset", _mock_build_dataset)

    mock_notify = AsyncMock()
    monkeypatch.setattr("src.tasks.scheduled_tasks.notify_drift_detected", mock_notify)

    mock_retrain = AsyncMock()
    monkeypatch.setattr("src.tasks.scheduled_tasks.run_retrain_pipeline_task", mock_retrain)

    outcome = await drift_monitor_task({}, evaluation_window_days=7, registry_dir=str(tmp_path))

    assert outcome["status"] in ("success", "partial_failure")
    servc_res = outcome["categories"]["Servc"]
    assert servc_res["status"] == "DRIFT_DETECTED"
    assert servc_res["drift_subgroup_type"] == "missing_lwlt_only"

    # 알림 호출 확인 (missing_lwlt_only 로 발신)
    assert mock_notify.await_count >= 1
    servc_notify_calls = [
        c
        for c in mock_notify.await_args_list
        if c.kwargs.get("model_name") == CATEGORY_MODEL_NAMES["Servc"]
    ]
    assert len(servc_notify_calls) == 1
    assert servc_notify_calls[0].kwargs.get("drift_subgroup_type") == "missing_lwlt_only"
    assert servc_notify_calls[0].kwargs.get("drift_by_subgroup") is not None

    # 자동 재학습·승격 절대 미발생 검증
    assert mock_retrain.await_count == 0

    # retrain_logs DB 저장 검증
    logs = isolated_db.query(RetrainLog).filter(RetrainLog.trigger_source == "drift_monitor").all()
    assert len(logs) > 0
    servc_logs = [
        log_item for log_item in logs if log_item.champion_version == CATEGORY_MODEL_NAMES["Servc"]
    ]
    assert len(servc_logs) > 0
    servc_log = servc_logs[0]
    assert servc_log.status == "DRIFT_DETECTED"
    assert "by_subgroup" in servc_log.metrics_summary
    assert servc_log.metrics_summary["drift_subgroup_type"] == "missing_lwlt_only"
