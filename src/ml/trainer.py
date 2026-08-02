"""
src/ml/trainer.py

일반화 ML 모델 학습기.
K-Fold 교차 검증 및 LightGBM/CatBoost 기반 사투가 예측 모델을 재학습하고
모델 레지스트리에 버저닝하여 아티팩트를 저장합니다.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.ml.features import build_feature_frame
from src.ml.validate_model import evaluate_model_performance

# 홀드아웃 비율. 학습에 쓰지 않은 구간에서 지표를 내야 의미가 있습니다.
# 시계열 데이터이므로 개찰일(rl_openg_dt / openg_dt) 기준으로 정렬한 뒤
# 뒤에서 20%를 최종 검증에 사용합니다.
DEFAULT_VALIDATION_SPLIT = 0.2

# K-Fold 폴드 수. 시간 순서를 존중하는 블록 K-Fold 를 사용합니다.
DEFAULT_N_FOLDS = 5

# 시계열 기준 컬럼. 없으면 프레임 순서를 그대로 사용합니다.
TIME_SORT_COLUMN = "openg_dt"

# 학습에 쓰는 특징. features.py 가 산출하는 컬럼 중 선정합니다.
TRAINING_FEATURES = [
    "log_price",
    "month_sin",
    "month_cos",
    "weekday_sin",
    "weekday_cos",
    "notice_duration",
    "inst_hist_rate",
    "inst_rate_mean_30d",
    "inst_rate_std_90d",
    "price_ratio",
]


def _resolve_time_index(df_feat: pd.DataFrame) -> pd.Series:
    """시계열 분할을 위한 기준 시계열을 반환합니다."""
    if TIME_SORT_COLUMN in df_feat.columns:
        return pd.to_datetime(df_feat[TIME_SORT_COLUMN], errors="coerce")
    return pd.Series(range(len(df_feat)))


def _time_based_split(
    df: pd.DataFrame,
    y: np.ndarray,
    validation_split: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """개찰일 기준으로 정렬한 뒤 뒤에서 validation_split 만큼을 검증에 사용합니다."""
    time_index = _resolve_time_index(df)
    sorted_order = time_index.sort_values().index.to_numpy()

    split_at = int(len(sorted_order) * (1.0 - validation_split))
    if split_at <= 0 or split_at >= len(sorted_order):
        return np.arange(len(df)), np.array([], dtype=int), y, np.array([], dtype=float)

    train_idx = sorted_order[:split_at]
    valid_idx = sorted_order[split_at:]
    return train_idx, valid_idx, y[train_idx], y[valid_idx]


def _time_based_kfold_splits(
    df: pd.DataFrame,
    n_folds: int,
) -> list[tuple[np.ndarray, np.ndarray]]:
    """시계열 순서를 존중하는 K-Fold 인덱스 쌍을 반환합니다.

    각 폴드는 이전 폴드들을 훈련, 현재 폴드를 검증으로 사용합니다.
    """
    time_index = _resolve_time_index(df)
    sorted_order = time_index.sort_values().index.to_numpy()

    fold_size = max(1, len(sorted_order) // n_folds)
    splits = []
    for fold_idx in range(1, n_folds):
        valid_start = fold_idx * fold_size
        valid_end = (fold_idx + 1) * fold_size if fold_idx < n_folds - 1 else len(sorted_order)
        train_idx = sorted_order[:valid_start]
        valid_idx = sorted_order[valid_start:valid_end]
        if len(train_idx) == 0 or len(valid_idx) == 0:
            continue
        splits.append((train_idx, valid_idx))
    return splits


def _train_ridge(
    X_train: np.ndarray,
    y_train: np.ndarray,
    hyperparams: dict[str, Any] | None = None,
) -> Any:
    from sklearn.linear_model import Ridge

    params = {"alpha": 1.0, "random_state": 42}
    params.update(hyperparams or {})
    return Ridge(**params).fit(X_train, y_train)


def _train_lightgbm(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    hyperparams: dict[str, Any] | None = None,
) -> Any:
    import lightgbm as lgb

    params = {
        "objective": "regression",
        "n_estimators": 200,
        "learning_rate": 0.05,
        "num_leaves": 31,
        "random_state": 42,
        "verbose": -1,
    }
    params.update(hyperparams or {})

    model = lgb.LGBMRegressor(**params)
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_valid, y_valid)],
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )
    return model


def _train_catboost(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    hyperparams: dict[str, Any] | None = None,
) -> Any:
    from catboost import CatBoostRegressor

    params = {
        "iterations": 200,
        "learning_rate": 0.05,
        "depth": 6,
        "random_seed": 42,
        "verbose": False,
    }
    params.update(hyperparams or {})

    model = CatBoostRegressor(**params)
    model.fit(X_train, y_train, eval_set=(X_valid, y_valid), verbose=False)
    return model


def _cross_validate_model(
    df: pd.DataFrame,
    y: np.ndarray,
    model_fn,
    hyperparams: dict[str, Any] | None,
    n_folds: int,
) -> dict[str, Any]:
    """K-Fold 교차 검증을 수행하고 평균 지표를 반환합니다."""
    X = df[TRAINING_FEATURES].values
    fold_metrics = []

    for _fold_idx, (train_idx, valid_idx) in enumerate(_time_based_kfold_splits(df, n_folds)):
        model = model_fn(
            X[train_idx],
            y[train_idx],
            X[valid_idx],
            y[valid_idx],
            hyperparams,
        )
        preds = model.predict(X[valid_idx])
        metrics = evaluate_model_performance(np.asarray(y[valid_idx]), np.asarray(preds))
        fold_metrics.append(metrics)

    if not fold_metrics:
        return {}

    aggregated = {}
    for key in fold_metrics[0]:
        aggregated[f"avg_{key}"] = round(
            float(np.mean([m[key] for m in fold_metrics])), 4
        )
        aggregated[f"std_{key}"] = round(
            float(np.std([m[key] for m in fold_metrics])), 4
        )
    aggregated["fold_count"] = len(fold_metrics)
    return aggregated


class ModelTrainer:
    def __init__(self, model_name: str = "quantum_leap_v25_pro", registry_dir: str = "ml_registry"):
        self.model_name = model_name
        self.registry_dir = Path(registry_dir)

    def train_and_register(
        self,
        df_raw: pd.DataFrame,
        hyperparams: dict[str, Any] | None = None,
        validation_split: float = DEFAULT_VALIDATION_SPLIT,
        n_folds: int = DEFAULT_N_FOLDS,
    ) -> dict[str, Any]:
        """
        Single Source of Truth features.py로 특징을 산출한 뒤 모델을 학습하고
        ml_registry/{model_name}/{version}/ 에 버저닝 저장합니다.
        """
        # 초 단위 버전명은 같은 초에 두 번 학습하면 충돌해 이전 아티팩트를 덮어씁니다.
        # 밀리초까지 넣고, 그래도 겹치면 접미사를 붙여 회피합니다.
        version = f"v_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
        target_dir = self.registry_dir / self.model_name / version
        suffix = 1
        while target_dir.exists():
            version = f"v_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]}_{suffix}"
            target_dir = self.registry_dir / self.model_name / version
            suffix += 1
        target_dir.mkdir(parents=True, exist_ok=True)

        # 단일 특징 공급원 적용
        records = df_raw.to_dict(orient="records")
        features_list = build_feature_frame(records)
        df_feat = pd.DataFrame(features_list)

        # Target (winning_rate)
        if "winning_rate" in df_raw.columns:
            y = df_raw["winning_rate"].values
        else:
            y = np.full(len(df_feat), 88.0)

        # 시계열 분할: 과거를 학습, 미래를 검증
        train_idx, valid_idx, y_train, y_valid = _time_based_split(
            df_feat, y, validation_split
        )
        X = df_feat[TRAINING_FEATURES].values
        X_train, X_valid = X[train_idx], X[valid_idx]

        # 데이터가 너무 적으면 트리 모델이 실패하므로 Ridge 로 폴백합니다.
        # 정기 실행이 멈추지 않도록 최소 2건 이상 확보 시에만 트리 모델을 시도합니다.
        use_tree_models = len(X_train) >= 2 and len(X_valid) >= 2

        lgbm_cv: dict[str, Any] = {}
        catboost_cv: dict[str, Any] = {}
        lgbm_valid_metrics: dict[str, float] = {}
        catboost_valid_metrics: dict[str, float] = {}

        if use_tree_models:
            # K-Fold 교차 검증으로 LightGBM/CatBoost 성능을 비교합니다.
            lgbm_cv = _cross_validate_model(
                df_feat.iloc[train_idx].reset_index(drop=True),
                y_train,
                _train_lightgbm,
                hyperparams.get("lightgbm") if hyperparams else None,
                n_folds,
            )
            catboost_cv = _cross_validate_model(
                df_feat.iloc[train_idx].reset_index(drop=True),
                y_train,
                _train_catboost,
                hyperparams.get("catboost") if hyperparams else None,
                n_folds,
            )

            lgbm_model = _train_lightgbm(X_train, y_train, X_valid, y_valid, hyperparams.get("lightgbm") if hyperparams else None)
            catboost_model = _train_catboost(X_train, y_train, X_valid, y_valid, hyperparams.get("catboost") if hyperparams else None)

            lgbm_valid_metrics = evaluate_model_performance(
                np.asarray(y_valid),
                np.asarray(lgbm_model.predict(X_valid)),
            )
            catboost_valid_metrics = evaluate_model_performance(
                np.asarray(y_valid),
                np.asarray(catboost_model.predict(X_valid)),
            )

        # Ridge 폴백은 항상 가능하며, 트리 모델이 없거나 실패하면 사용합니다.
        ridge_model = _train_ridge(X_train, y_train, hyperparams.get("ridge") if hyperparams else None)
        ridge_valid_metrics = evaluate_model_performance(
            np.asarray(y_valid),
            np.asarray(ridge_model.predict(X_valid)),
        )

        # R² 기준으로 더 나은 모델을 선택합니다.
        candidates = [(ridge_model, "ridge", ridge_valid_metrics, {})]
        if use_tree_models:
            candidates.append((lgbm_model, "lightgbm", lgbm_valid_metrics, lgbm_cv))
            candidates.append((catboost_model, "catboost", catboost_valid_metrics, catboost_cv))

        best_model, model_type, valid_metrics, cv_metrics = max(
            candidates, key=lambda item: item[2]["r2"]
        )

        # 가중치 저장
        model_file = target_dir / "model.bin"
        joblib.dump(best_model, model_file)

        # 메타데이터 저장
        metadata = {
            "model_name": self.model_name,
            "version": version,
            "trained_at": datetime.utcnow().isoformat(),
            "samples_count": len(df_raw),
            "train_samples": len(train_idx),
            "validation_samples": len(valid_idx),
            "features": list(TRAINING_FEATURES),
            "model_type": model_type,
            "metrics": valid_metrics,
            "cv_metrics": cv_metrics,
            "candidate_metrics": {
                "lightgbm": lgbm_valid_metrics,
                "catboost": catboost_valid_metrics,
            },
            "hyperparams": hyperparams or {},
            "status": "challenger",
        }
        with open(target_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata


trainer = ModelTrainer()
