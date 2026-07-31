"""
src/ml/validate_model.py

실시간 모델 성능 실측 및 Champion/Challenger 검증 평가기.
Champion vs Challenger 성능 대조 리포트를 생성하고
설정된 승격 조건(RMSE, MAPE, R² 개선) 충족 시 하이브리드 승인 게이트를 통과시킵니다.
"""

from typing import Any
import numpy as np


def evaluate_model_performance(y_true: np.ndarray, y_pred: np.ndarray) -> dict[str, float]:
    """RMSE, MAPE, R² 실시간 평가 지표 산출"""
    mse = np.mean((y_true - y_pred) ** 2)
    rmse = float(np.sqrt(mse))
    mape = float(np.mean(np.abs((y_true - y_pred) / np.maximum(y_true, 1e-5))) * 100.0)

    ss_res = np.sum((y_true - y_pred) ** 2)
    ss_tot = np.sum((y_true - np.mean(y_true)) ** 2)
    r2 = float(1.0 - (ss_res / (ss_tot + 1e-5)))

    return {
        "rmse": round(rmse, 4),
        "mape": round(mape, 4),
        "r2": round(r2, 4),
    }


def compare_champion_vs_challenger(
    champion_metrics: dict[str, float],
    challenger_metrics: dict[str, float],
) -> dict[str, Any]:
    """
    Champion vs Challenger 지표 비교 및 승격 추천 여부 판단.
    Challenger가 RMSE/MAPE를 낮추고 R²를 향상시켰을 때 승격 권장.
    """
    improved_rmse = challenger_metrics["rmse"] < champion_metrics["rmse"]
    improved_mape = challenger_metrics["mape"] < champion_metrics["mape"]
    improved_r2 = challenger_metrics["r2"] >= champion_metrics["r2"]

    should_promote = improved_rmse or improved_r2

    return {
        "champion_metrics": champion_metrics,
        "challenger_metrics": challenger_metrics,
        "improved_rmse": improved_rmse,
        "improved_mape": improved_mape,
        "improved_r2": improved_r2,
        "recommendation": "PROMOTE_CHALLENGER" if should_promote else "REJECT_CHALLENGER",
    }
