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

# 폴드 하나가 가져야 하는 최소 행 수. 트리 모델이 1행 입력에서 예외를 던집니다.
MIN_FOLD_SAMPLES = 2

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


def has_time_column(df: pd.DataFrame) -> bool:
    """시계열 정렬 기준 컬럼이 실재하는지 확인합니다."""
    return TIME_SORT_COLUMN in df.columns


def _sorted_positions(df: pd.DataFrame) -> np.ndarray:
    """시계열 오름차순 위치 배열을 반환합니다.

    라벨이 아니라 위치를 돌려줍니다. 호출부가 numpy 배열에 위치 색인을 쓰므로
    라벨을 섞어 쓰면 인덱스가 기본 RangeIndex 가 아닐 때 조용히 어긋납니다.

    기준 컬럼이 없거나 값이 비면 프레임 순서를 그대로 씁니다. 파싱 실패(NaT)는
    맨 앞으로 보내 학습 구간에 넣습니다. 검증 구간은 개찰일이 확실한 최신
    구간이어야 의미가 있습니다.
    """
    if not has_time_column(df):
        return np.arange(len(df))
    parsed = pd.to_datetime(df[TIME_SORT_COLUMN], errors="coerce")
    if parsed.isna().all():
        return np.arange(len(df))
    return parsed.reset_index(drop=True).sort_values(na_position="first").index.to_numpy()


def _time_based_split(
    df: pd.DataFrame,
    y: np.ndarray,
    validation_split: float,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """개찰일 기준으로 정렬한 뒤 뒤에서 validation_split 만큼을 검증에 사용합니다.

    표본이 적어 홀드아웃을 뗄 수 없으면 전체를 학습과 검증에 함께 씁니다.
    빈 검증 구간을 돌려주면 predict 단계에서 0행 입력으로 예외가 납니다.
    이 경우 지표는 과적합된 값이므로 승격 판단에 쓰면 안 됩니다.
    """
    sorted_order = _sorted_positions(df)

    split_at = int(len(sorted_order) * (1.0 - validation_split))
    if split_at <= 0 or split_at >= len(sorted_order):
        return sorted_order, sorted_order, y[sorted_order], y[sorted_order]

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
    sorted_order = _sorted_positions(df)

    fold_size = max(1, len(sorted_order) // n_folds)
    splits = []
    for fold_idx in range(1, n_folds):
        valid_start = fold_idx * fold_size
        valid_end = (fold_idx + 1) * fold_size if fold_idx < n_folds - 1 else len(sorted_order)
        train_idx = sorted_order[:valid_start]
        valid_idx = sorted_order[valid_start:valid_end]
        # 표본이 적으면 fold_size 가 1 이 되어 1행짜리 폴드가 생깁니다.
        # LightGBM/CatBoost 는 1행 입력에서 예외를 던지므로 건너뜁니다.
        if len(train_idx) < MIN_FOLD_SAMPLES or len(valid_idx) < MIN_FOLD_SAMPLES:
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


def _train_ridge_cv(
    X_train: np.ndarray,
    y_train: np.ndarray,
    X_valid: np.ndarray,
    y_valid: np.ndarray,
    hyperparams: dict[str, Any] | None = None,
) -> Any:
    """트리 모델과 시그니처를 맞춘 Ridge 어댑터. Ridge 는 조기 종료가 없어 검증 구간을 쓰지 않습니다."""
    return _train_ridge(X_train, y_train, hyperparams)


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

        # build_feature_frame 은 새 dict 를 만들어 반환하므로 개찰일이 사라집니다.
        # 시계열 분할이 프레임 순서로 조용히 폴백하지 않도록 여기서 다시 싣습니다.
        # 학습 특징이 아니라 정렬 기준이므로 TRAINING_FEATURES 에는 넣지 않습니다.
        if TIME_SORT_COLUMN in df_raw.columns:
            df_feat[TIME_SORT_COLUMN] = df_raw[TIME_SORT_COLUMN].to_numpy()

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

        # 홀드아웃을 뗄 수 없어 학습 구간을 그대로 검증에 쓴 경우입니다.
        # 이때 지표는 과적합된 값이라 승격 판단 근거가 될 수 없습니다.
        holdout_is_overfit = len(train_idx) == len(valid_idx) and np.array_equal(
            train_idx, valid_idx
        )

        model_fns: dict[str, Any] = {"ridge": _train_ridge_cv}
        if use_tree_models:
            model_fns["lightgbm"] = _train_lightgbm
            model_fns["catboost"] = _train_catboost

        df_train = df_feat.iloc[train_idx].reset_index(drop=True)

        candidates = []
        cv_by_model: dict[str, dict[str, Any]] = {}
        holdout_by_model: dict[str, dict[str, float]] = {}
        for name, model_fn in model_fns.items():
            params = hyperparams.get(name) if hyperparams else None
            # 모델 선택은 학습 구간 내부의 K-Fold 로만 합니다. 홀드아웃 점수로
            # 고르면 그 점수가 선택 편향으로 부풀려져 승격 판단이 낙관적이 됩니다.
            cv = _cross_validate_model(df_train, y_train, model_fn, params, n_folds)
            model = model_fn(X_train, y_train, X_valid, y_valid, params)
            holdout = evaluate_model_performance(
                np.asarray(y_valid), np.asarray(model.predict(X_valid))
            )
            cv_by_model[name] = cv
            holdout_by_model[name] = holdout
            # K-Fold 를 만들 수 없을 만큼 표본이 적으면 홀드아웃으로 내려갑니다.
            selection_score = cv.get("avg_r2", holdout["r2"])
            candidates.append((selection_score, name, model, cv, holdout))

        _, model_type, best_model, cv_metrics, valid_metrics = max(
            candidates, key=lambda item: item[0]
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
            "candidate_cv_metrics": cv_by_model,
            "candidate_holdout_metrics": holdout_by_model,
            # 아래 두 값이 참이면 metrics 를 승격 판단에 쓰면 안 됩니다.
            "holdout_is_overfit": holdout_is_overfit,
            "time_sorted_split": bool(has_time_column(df_feat)),
            "hyperparams": hyperparams or {},
            "status": "challenger",
        }
        with open(target_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata


trainer = ModelTrainer()
