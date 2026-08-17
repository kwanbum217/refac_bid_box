"""
src/ml/conformal.py

등각예측(Conformal Prediction) 및 분위 회귀 모델 학습기.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from src.ml.features import CATEGORICAL_FEATURES
from src.ml.training_config import LGB_BASE_PARAMS

# 분위 모델만의 재정의입니다. 지금은 점 추정과 값이 같아 동작이 바뀌지 않지만,
# 두 모델의 용량을 따로 정할 수 있게 하는 것이 이 상수의 존재 이유입니다. 예전에는
# 점 추정 리프를 건드리면 구간 폭이 11.2% 딸려 움직여 정확도와 폭을 맞바꾸는 것처럼
# 보였습니다. 분리 후 실측에서는 점 추정을 127 로 올려도 폭이 1.423%p 로 동일합니다.
#
# 점 추정과 목표가 다릅니다.
#
#   점 추정: MAE 와 0.5%p 적중을 낮춘다 -> 용량이 클수록 좋다
#   분위:    등각 보정 후 구간 폭을 줄인다 -> 폭이 리프에 대해 U자를 그린다
#
# 분위 모델이 정교해지면 원 구간은 좁아지지만 검증 구간 오차가 상대적으로 커져
# 등각 배율이 그만큼 오릅니다. 실측에서 두 효과가 63 에서 교차합니다.
#
#   분위 63  -> 배율 1.1485 / 폭 1.7728%p / 피복 89.88%
#   분위 255 -> 배율 1.2595 / 폭 1.8891%p / 피복 89.90%
#
# 근거는 docs/design/servc_hyperparam_search_20260804.md 7장과 9장입니다.
QUANTILE_PARAM_OVERRIDES = {"num_leaves": 63}

# 분위 모델 설정을 카테고리별로 잡을 때 쓰는 하이퍼파라미터 키입니다. 점 추정
# 키("lightgbm")와 반드시 갈라야 합니다. 용역 점 추정은 objective quantile
# alpha 0.5 / 리프 255 인데, 그 값이 분위 모델로 흘러들면 10·90분위가 전부
# 중앙값으로 바뀌어 구간이 붕괴합니다.
#
# objective 와 alpha 는 분위별로 정해지므로 이 통로로 받아도 무시합니다.
QUANTILE_HYPERPARAM_KEY = "lightgbm_quantile"

# 예측 구간 설정. 설계서 6.3 은 이분산 대응을 구간 분할이 아니라 예측 구간
# 제공으로 정했습니다. 소박한 분위 회귀 구간은 보정에 실패하므로(명목 80%
# 대비 실제 75.52%, 10억 이상 66.85%) 등각예측 배율을 함께 산정합니다.
# 목표를 90% 로 두는 이유는 80% 가 보정 후에도 76.77% 로 표기와 어긋나기
# 때문입니다. 근거: docs/design/servc_prediction_interval_20260804.md
INTERVAL_QUANTILES = (0.1, 0.9)
INTERVAL_TARGET_COVERAGE = 0.90

# 등각예측 보정에 쓸 학습 구간 뒷부분 비율. 분위 모델 적합에는 쓰지 않습니다.
# 같은 데이터로 적합과 보정을 하면 배율이 낙관적으로 나옵니다.
CALIBRATION_SPLIT = 0.15


def _present_categoricals(X: pd.DataFrame) -> list[str]:
    return [column for column in CATEGORICAL_FEATURES if column in X.columns]


def _conformal_scale(
    y_cal: np.ndarray,
    lo_cal: np.ndarray,
    hi_cal: np.ndarray,
    target: float,
) -> float:
    """구간을 중앙 기준으로 몇 배 넓혀야 목표 피복률에 닿는지 구합니다."""
    center = (lo_cal + hi_cal) / 2
    half = np.maximum((hi_cal - lo_cal) / 2, 1e-9)
    score = np.abs(y_cal - center) / half
    return float(np.quantile(score, target))


def _train_quantile_models(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    hyperparams: dict[str, Any] | None = None,
) -> tuple[dict[float, Any], float, dict[str, Any]]:
    """분위 모델 2종과 등각예측 배율을 만듭니다.

    학습 구간 뒷부분을 보정용으로 떼어 배율을 산정한 뒤, 분위 모델 자체는
    전체 학습 구간으로 다시 적합합니다. 보정 표본까지 써야 분위 추정이
    가장 좋아지고, 배율은 이미 확보했으므로 누수가 아닙니다.

    hyperparams 는 QUANTILE_HYPERPARAM_KEY 로 전달된 카테고리별 재정의입니다.
    이 인자가 없던 동안 분위 모델은 카테고리와 무관하게 리프 63 에 고정돼
    있었고, 점 추정만 카테고리별 설정을 받았습니다.
    """
    import lightgbm as lgb

    params = {**LGB_BASE_PARAMS, **QUANTILE_PARAM_OVERRIDES, **(hyperparams or {})}
    # 분위별로 정해지는 축이라 외부 재정의를 받지 않습니다.
    params.pop("objective", None)
    params.pop("alpha", None)
    categorical = _present_categoricals(X_train)

    split_at = int(len(X_train) * (1.0 - CALIBRATION_SPLIT))
    scale = 1.0
    calibration: dict[str, Any] = {"calibrated": False, "calibration_samples": 0}
    if split_at > 0 and split_at < len(X_train):
        X_fit, X_cal = X_train.iloc[:split_at], X_train.iloc[split_at:]
        y_fit, y_cal = y_train[:split_at], y_train[split_at:]
        bounds = []
        for q in INTERVAL_QUANTILES:
            model = lgb.LGBMRegressor(objective="quantile", alpha=q, **params)
            model.fit(X_fit, y_fit, categorical_feature=categorical)
            bounds.append(model.predict(X_cal))
        # 분위별 독립 학습이라 예측이 뒤집힐 수 있습니다(교차 현상).
        lo_cal = np.minimum(bounds[0], bounds[1])
        hi_cal = np.maximum(bounds[0], bounds[1])
        scale = _conformal_scale(y_cal, lo_cal, hi_cal, INTERVAL_TARGET_COVERAGE)
        calibration = {"calibrated": True, "calibration_samples": len(X_cal)}

    models: dict[float, Any] = {}
    for q in INTERVAL_QUANTILES:
        model = lgb.LGBMRegressor(objective="quantile", alpha=q, **params)
        model.fit(X_train, y_train, categorical_feature=categorical)
        models[q] = model

    calibration.update(
        {
            "quantiles": list(INTERVAL_QUANTILES),
            "target_coverage": INTERVAL_TARGET_COVERAGE,
            "conformal_scale": round(scale, 6),
            # 어떤 용량으로 적합했는지 아티팩트에 남깁니다. 이 값이 없던 동안
            # 세 버전의 metadata.json 이 서로 다른 hyperparams 를 기록하면서도
            # conformal_scale 이 1.151263 으로 같았고, 그 이유가 분위 모델이
            # 통로 없이 고정돼 있어서였다는 사실이 드러나지 않았습니다.
            "num_leaves": params.get("num_leaves"),
        }
    )
    return models, scale, calibration
