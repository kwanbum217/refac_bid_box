import numpy as np
import pandas as pd
from src.ml.predictor import predictor
from src.ml.trainer import ModelTrainer
from src.ml.validate_model import evaluate_model_performance, compare_champion_vs_challenger
from src.ml.monitoring import calculate_psi, check_feature_drift


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
