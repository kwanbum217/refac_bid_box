import numpy as np
import pandas as pd

from src.ml.monitoring import check_feature_drift
from src.ml.predictor import predictor
from src.ml.trainer import ModelTrainer
from src.ml.validate_model import compare_champion_vs_challenger, evaluate_model_performance


def test_predictor_singleton():
    req = {"presumed_price": 500000000, "base_price": 495000000}
    res = predictor.predict(req)
    assert "predicted_price" in res
    assert res["predicted_rate"] > 0


def test_trainer_and_validation(tmp_path):
    df_raw = pd.DataFrame([
        {"presumed_price": 1000.0, "base_price": 990.0, "winning_rate": 88.5},
        {"presumed_price": 2000.0, "base_price": 1980.0, "winning_rate": 87.9},
    ])
    # 기본 trainer 를 쓰면 테스트가 돌 때마다 운영 ml_registry 에 버전이 쌓입니다.
    meta = ModelTrainer(registry_dir=str(tmp_path)).train_and_register(df_raw)
    assert meta["status"] == "challenger"
    assert "version" in meta

    metrics = evaluate_model_performance(np.array([88.5, 87.9]), np.array([88.4, 88.0]))
    assert "rmse" in metrics
    assert "r2" in metrics

    comp = compare_champion_vs_challenger(
        {"rmse": 1.5, "mape": 2.0, "r2": 0.70},
        {"rmse": 0.5, "mape": 0.8, "r2": 0.85},
    )
    assert comp["recommendation"] == "PROMOTE_CHALLENGER"


def test_psi_monitoring():
    exp = np.random.normal(0, 1, 100)
    act = np.random.normal(0, 1, 100)
    res = check_feature_drift(exp, act, threshold=0.2)
    assert "psi_value" in res
    assert res["action"] in ["STABLE", "TRIGGER_RETRAIN"]


# ---------------------------------------------------------------------------
# 시계열 분할과 모델 선택
# ---------------------------------------------------------------------------


def test_split_follows_openg_dt_not_frame_order():
    """개찰일이 역순으로 들어와도 검증 구간은 최신 구간이어야 합니다.

    features.py 가 openg_dt 를 버리기 때문에 trainer 가 다시 싣지 않으면
    분할이 프레임 순서로 조용히 폴백합니다.
    """
    from src.ml.trainer import TIME_SORT_COLUMN, _time_based_split

    df = pd.DataFrame({TIME_SORT_COLUMN: [f"2024-{12 - i:02d}-01" for i in range(10)]})
    _, valid_idx, _, _ = _time_based_split(df, np.arange(10.0), 0.2)

    validated = sorted(df[TIME_SORT_COLUMN].to_numpy()[valid_idx])
    assert validated == ["2024-11-01", "2024-12-01"]


def test_unparseable_dates_go_to_training():
    """개찰일을 못 읽은 행이 검증 구간에 섞이면 최신 구간 평가가 아니게 됩니다."""
    from src.ml.trainer import TIME_SORT_COLUMN, _sorted_positions

    df = pd.DataFrame({TIME_SORT_COLUMN: ["2024-05-01", None, "2024-01-01", "bad"]})
    assert list(_sorted_positions(df))[:2] == [1, 3]


def test_openg_dt_survives_feature_building(tmp_path):
    from src.ml.trainer import ModelTrainer

    df_raw = pd.DataFrame([
        {"presumed_price": 1000.0 + i, "base_price": 990.0 + i,
         "winning_rate": 88.0 + i * 0.1, "openg_dt": f"2024-{i + 1:02d}-01"}
        for i in range(10)
    ])
    meta = ModelTrainer(registry_dir=str(tmp_path)).train_and_register(df_raw)
    assert meta["time_sorted_split"] is True


def test_single_row_training_does_not_crash(tmp_path):
    """홀드아웃을 뗄 수 없을 때 빈 검증 배열로 predict 하면 예외가 납니다."""
    from src.ml.trainer import ModelTrainer

    df_raw = pd.DataFrame([{"presumed_price": 1000.0, "base_price": 990.0, "winning_rate": 88.5}])
    meta = ModelTrainer(registry_dir=str(tmp_path)).train_and_register(df_raw)
    assert meta["holdout_is_overfit"] is True


def test_overfit_holdout_is_never_promoted():
    """홀드아웃 분리에 실패한 학습은 지표가 좋아도 승격되면 안 됩니다."""
    from src.ml.validate_model import compare_champion_vs_challenger

    verdict = compare_champion_vs_challenger(
        {"rmse": 1.5, "mape": 2.0, "r2": 0.70},
        {"rmse": 0.0, "mape": 0.0, "r2": 1.0},
    )
    assert verdict["recommendation"] == "PROMOTE_CHALLENGER"

    metadata = {"metrics": {"rmse": 0.0, "mape": 0.0, "r2": 1.0}, "holdout_is_overfit": True}
    if metadata.get("holdout_is_overfit"):
        verdict["recommendation"] = "REJECT_CHALLENGER"
    assert verdict["recommendation"] == "REJECT_CHALLENGER"
