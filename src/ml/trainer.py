"""
src/ml/trainer.py

일반화 ML 모델 학습기.
K-Fold 교차 검증 및 LightGBM/CatBoost 기반 사투가 예측 모델을 재학습하고
모델 레지스트리에 버저닝하여 아티팩트를 저장합니다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.app.core.timeutil import utcnow
from src.ml.features import (
    CATEGORICAL_FEATURES,
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.institution_history import attach_institution_history
from src.ml.repeat_history import REPEAT_FEATURES, attach_repeat_history
from src.ml.validate_model import evaluate_model_performance

# 홀드아웃 비율. 학습에 쓰지 않은 구간에서 지표를 내야 의미가 있습니다.
# 시계열 데이터이므로 개찰일(rl_openg_dt / openg_dt) 기준으로 정렬한 뒤
# 뒤에서 20%를 최종 검증에 사용합니다.
DEFAULT_VALIDATION_SPLIT = 0.2

# K-Fold 폴드 수. 시간 순서를 존중하는 블록 K-Fold 를 사용합니다.
DEFAULT_N_FOLDS = 5

# LightGBM 용량 설정. 점 추정과 분위 모델이 같은 복잡도를 써야 구간과 점
# 추정이 어긋나지 않습니다. 값은 scripts/ablation_servc_features.py 실측 기준입니다.
LGB_BASE_PARAMS = {
    "n_estimators": 600,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 40,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "random_state": 42,
    "verbose": -1,
    "n_jobs": -1,
}

# 폴드 하나가 가져야 하는 최소 행 수. 트리 모델이 1행 입력에서 예외를 던집니다.
MIN_FOLD_SAMPLES = 2

# 카테고리별 모델 네임스페이스. 물품과 용역은 예정가격 산정과 낙찰자 결정이
# 서로 다른 제도라 한 이름을 공유하면 champion 비교가 뒤섞입니다.
DEFAULT_MODEL_NAME = "quantum_leap_v25_pro"
CATEGORY_MODEL_NAMES = {
    "Thng": "quantum_leap_v25_pro",
    "Servc": "servc_institution_v1",
}


def model_name_for_category(category_code: str | None) -> str:
    return CATEGORY_MODEL_NAMES.get((category_code or "").strip(), DEFAULT_MODEL_NAME)

# 시계열 기준 컬럼. 없으면 프레임 순서를 그대로 사용합니다.
TIME_SORT_COLUMN = "openg_dt"

# 학습에 쓰는 특징. features.py 산출물 중 실측으로 선정했습니다 (2026-08-02).
#
# inst_hist_rate 가 사실상 유일한 신호입니다. 이 값 하나만으로 R2 0.33 이고,
# 빼면 전체 R2 가 0.36 에서 0.03 으로 떨어집니다.
#
# 제외한 것들과 근거입니다.
#   inst_rate_mean_30d  inst_hist_rate 를 그대로 복사한 값이라 중복입니다
#   inst_rate_std_90d   입력이 없어 항상 상수 0.015 입니다
#   price_ratio         기초금액은 제도상 예정가격의 1.1 배라 표준편차 0.017,
#                       목표 상관 0.05 로 신호가 없습니다
#
# 2026-08-03 에 제도 특징을 추가했습니다. 용역 917,629행 시간순 홀드아웃 실측입니다.
#
#   기존 6종            R2 0.5600  RMSE 3.1780
#   + 제도 수치         R2 0.6433  RMSE 2.8615
#   + 제도 범주         R2 0.6683  RMSE 2.7591
#
# 근거: docs/design/servc_segment_experiment_20260803.md
#
# 같은 날 세부분류(중/소)와 공고속성을 더했습니다. 학습 2024년까지, 검증 2025년
# 96,141건 실측입니다.
#
#   범주 5종            R2 0.6767  RMSE 2.7312
#   범주 11종           R2 0.6910  RMSE 2.6701
#
# 근거: docs/design/servc_restricted_competition_20260803.md
NUMERIC_FEATURES = [
    "log_price",
    "month_sin",
    "month_cos",
    "weekday_sin",
    "weekday_cos",
    "notice_duration",
    "inst_hist_rate",
    "inst_sample_cnt",
    "lwlt_rate",
    "lwlt_rate_missing",
    "is_post_regime_shift",
    "notice_amt_ratio",
    "is_over_notice_amt",
    "tech_ablt_evl_rt",
    "bid_prce_evl_rt",
    "tot_prdprc_num",
    "drwt_prdprc_num",
    *REPEAT_FEATURES,
]

TRAINING_FEATURES = [*NUMERIC_FEATURES, *CATEGORICAL_FEATURES]


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


def _present_categoricals(X: pd.DataFrame) -> list[str]:
    return [column for column in CATEGORICAL_FEATURES if column in X.columns]


def _to_numeric_matrix(X: pd.DataFrame) -> np.ndarray:
    """범주형을 정수 코드로 바꾼 수치 행렬입니다.

    Ridge 는 범주형을 다루지 못합니다. 코드는 순서에 의미가 없어 선형모형에
    적합하지 않지만, Ridge 는 트리 모델이 실패할 때의 폴백 기준선이므로
    비교 가능한 값만 내면 충분합니다.
    """
    numeric = X.copy()
    for column in _present_categoricals(numeric):
        numeric[column] = numeric[column].cat.codes.astype(float)
    return numeric.to_numpy(dtype=float)


def _train_ridge_cv(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_valid: pd.DataFrame,
    y_valid: np.ndarray,
    hyperparams: dict[str, Any] | None = None,
) -> Any:
    """트리 모델과 시그니처를 맞춘 Ridge 어댑터.

    Ridge 는 조기 종료가 없어 검증 구간을 쓰지 않습니다. predict 도 DataFrame 을
    받아야 하므로 얇은 래퍼로 감싸 호출부의 인터페이스를 통일합니다.
    """
    from sklearn.linear_model import Ridge

    params = {"alpha": 1.0, "random_state": 42}
    params.update(hyperparams or {})
    model = Ridge(**params).fit(_to_numeric_matrix(X_train), y_train)
    return _RidgeFrameAdapter(model)


class _RidgeFrameAdapter:
    """DataFrame 을 받아 정수 코드 행렬로 바꿔 예측합니다."""

    def __init__(self, model: Any):
        self.model = model

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return self.model.predict(_to_numeric_matrix(X))


def _train_lightgbm(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_valid: pd.DataFrame,
    y_valid: np.ndarray,
    hyperparams: dict[str, Any] | None = None,
) -> Any:
    import lightgbm as lgb

    # 낙찰률에서 하한율을 뺀 잔차는 0 에 몰린 비대칭 분포입니다(중앙값 0.159%p,
    # 72.7% 가 0.5%p 이내). L2 로 학습하면 긴 오른쪽 꼬리를 줄이려고 중심 예측을
    # 위로 밀어 올려, 대다수 건에서 조금씩 빗나갑니다. Huber 로 바꾸면 0.5%p 이내
    # 적중이 45.69% 에서 59.91% 로 오릅니다. 대가는 10%p 초과 오차 1.11% -> 1.56%.
    # 근거: docs/design/servc_repeat_procurement_20260803.md 1장
    # 용량은 실험 스크립트(scripts/ablation_servc_features.py)에서 실측으로
    # 검증된 값에 맞춥니다. 종전 200트리/31리프는 실험본(600/63)보다 작아
    # 같은 데이터에서 2025년 홀드아웃 R2 0.6688 대 0.6967,
    # 0.5%p 이내 적중 54.77% 대 60.49% 로 뒤졌습니다.
    params = {**LGB_BASE_PARAMS, "objective": "huber", "alpha": 1.0}
    params.update(hyperparams or {})

    model = lgb.LGBMRegressor(**params)
    model.fit(
        X_train,
        y_train,
        eval_set=[(X_valid, y_valid)],
        categorical_feature=_present_categoricals(X_train),
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )
    return model


def _train_catboost(
    X_train: pd.DataFrame,
    y_train: np.ndarray,
    X_valid: pd.DataFrame,
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

    # CatBoost 는 범주형 컬럼에 결측을 허용하지 않습니다. features.py 가
    # MISSING_CATEGORY 로 채워 주지만 문자열로 넘겨야 코드 해석이 어긋나지 않습니다.
    cat_features = _present_categoricals(X_train)
    train_frame = X_train.copy()
    valid_frame = X_valid.copy()
    for column in cat_features:
        train_frame[column] = train_frame[column].astype(str)
        valid_frame[column] = valid_frame[column].astype(str)

    model = CatBoostRegressor(**params)
    model.fit(
        train_frame,
        y_train,
        eval_set=(valid_frame, y_valid),
        cat_features=cat_features,
        verbose=False,
    )
    return _CatBoostFrameAdapter(model, cat_features)


class _CatBoostFrameAdapter:
    """범주형을 문자열로 되돌려 예측합니다. 학습 때와 표현을 맞춰야 합니다."""

    def __init__(self, model: Any, cat_features: list[str]):
        self.model = model
        self.cat_features = cat_features

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        frame = X.copy()
        for column in self.cat_features:
            frame[column] = frame[column].astype(str)
        return self.model.predict(frame)


def _cross_validate_model(
    df: pd.DataFrame,
    y: np.ndarray,
    model_fn,
    hyperparams: dict[str, Any] | None,
    n_folds: int,
) -> dict[str, Any]:
    """K-Fold 교차 검증을 수행하고 평균 지표를 반환합니다."""
    X = df[TRAINING_FEATURES]
    fold_metrics = []

    for _fold_idx, (train_idx, valid_idx) in enumerate(_time_based_kfold_splits(df, n_folds)):
        model = model_fn(
            X.iloc[train_idx],
            y[train_idx],
            X.iloc[valid_idx],
            y[valid_idx],
            hyperparams,
        )
        preds = model.predict(X.iloc[valid_idx])
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
    # 폴드별 원지표를 남깁니다. 평균만 저장하면 설계서 7장 필수 4
    # (어느 폴드도 R2 > 0.99 아닐 것)를 판정할 근거가 사라집니다.
    # ssh_hist_premium 은 5폴드 중 3개가 R2 0.9999999999999998 이었는데
    # 평균만 보면 그 사실이 드러나지 않습니다.
    aggregated["folds"] = fold_metrics
    return aggregated


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
) -> tuple[dict[float, Any], float, dict[str, Any]]:
    """분위 모델 2종과 등각예측 배율을 만듭니다.

    학습 구간 뒷부분을 보정용으로 떼어 배율을 산정한 뒤, 분위 모델 자체는
    전체 학습 구간으로 다시 적합합니다. 보정 표본까지 써야 분위 추정이
    가장 좋아지고, 배율은 이미 확보했으므로 누수가 아닙니다.
    """
    import lightgbm as lgb

    params = dict(LGB_BASE_PARAMS)
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
        }
    )
    return models, scale, calibration


class ModelTrainer:
    def __init__(self, model_name: str = DEFAULT_MODEL_NAME, registry_dir: str = "ml_registry"):
        self.model_name = model_name
        self.registry_dir = Path(registry_dir)

    @classmethod
    def for_category(cls, category_code: str | None, registry_dir: str = "ml_registry"):
        """카테고리 전용 학습기를 만듭니다.

        분기가 없으면 용역 재학습이 물품 디렉터리에 저장되고 물품 champion 과
        비교됩니다. 서로 다른 제도를 쓰는 두 모델이 한 이름을 공유하게 됩니다.
        """
        return cls(model_name_for_category(category_code), registry_dir)

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
        version = f"v_{utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
        target_dir = self.registry_dir / self.model_name / version
        suffix = 1
        while target_dir.exists():
            version = f"v_{utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]}_{suffix}"
            target_dir = self.registry_dir / self.model_name / version
            suffix += 1
        target_dir.mkdir(parents=True, exist_ok=True)

        # 기관 이력을 프레임 단위로 먼저 붙입니다. features.py 는 입력에 있는
        # inst_hist_rate 를 그대로 쓰므로, 여기서 채우면 단일 공급원이 유지됩니다.
        # 행당 DB 조회로는 32시간이 걸려 배치 계산을 씁니다.
        df_raw = attach_institution_history(df_raw)
        df_raw = attach_repeat_history(df_raw)

        # 단일 특징 공급원 적용
        records = df_raw.to_dict(orient="records")
        features_list = build_feature_frame(records)
        df_feat = pd.DataFrame(features_list)

        # 범주 수준을 여기서 확정해 모델과 함께 저장합니다. 추론 시점에 같은
        # 수준으로 복원하지 않으면 범주 코드가 어긋나 조용히 다른 값을 읽습니다.
        category_levels = collect_category_levels(df_feat)
        df_feat = apply_categorical_dtypes(df_feat, category_levels)

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
        X = df_feat[TRAINING_FEATURES]
        X_train, X_valid = X.iloc[train_idx], X.iloc[valid_idx]

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
            # 선택은 MAPE(낮을수록 좋음)로 합니다. R2/RMSE 는 조건부 평균을
            # 겨냥하는데 낙찰률 잔차는 0 에 몰린 비대칭 분포라, 그 기준으로 고르면
            # 중심을 위로 밀어 올린 모델이 이깁니다. 2025년 홀드아웃 실측에서
            # CatBoost 가 R2 0.6994 로 LightGBM(Huber) 0.6967 을 이겼지만
            # 0.5%p 이내 적중은 46.80% 대 60.49% 로 크게 졌습니다.
            # MAPE 로 고르면 LightGBM 1.431, CatBoost 1.5025 로 순서가 뒤집힙니다.
            # 근거: docs/design/servc_repeat_procurement_20260803.md 1장
            # K-Fold 를 만들 수 없을 만큼 표본이 적으면 홀드아웃으로 내려갑니다.
            selection_score = cv.get("avg_mape", holdout["mape"])
            candidates.append((selection_score, name, model, cv, holdout))

        _, model_type, best_model, cv_metrics, valid_metrics = min(
            candidates, key=lambda item: item[0]
        )

        # 가중치 저장
        model_file = target_dir / "model.bin"
        joblib.dump(best_model, model_file)

        # 예측 구간. 큰 건일수록 산포가 커지는 이분산에 대한 설계서 6.3 의 대응입니다.
        # 트리 모델을 못 쓸 만큼 표본이 적으면 구간도 만들지 않습니다.
        interval_meta: dict[str, Any] = {"available": False}
        if use_tree_models:
            quantile_models, _, interval_meta = _train_quantile_models(X_train, y_train)
            for q, model in quantile_models.items():
                joblib.dump(model, target_dir / f"model_q{int(q * 100):02d}.bin")
            interval_meta["available"] = True

        # 메타데이터 저장
        metadata = {
            "model_name": self.model_name,
            "version": version,
            "trained_at": utcnow().isoformat(),
            "samples_count": len(df_raw),
            "train_samples": len(train_idx),
            "validation_samples": len(valid_idx),
            "features": list(TRAINING_FEATURES),
            "categorical_features": list(CATEGORICAL_FEATURES),
            "category_levels": category_levels,
            "model_type": model_type,
            "metrics": valid_metrics,
            "cv_metrics": cv_metrics,
            "candidate_cv_metrics": cv_by_model,
            "candidate_holdout_metrics": holdout_by_model,
            # 아래 두 값이 참이면 metrics 를 승격 판단에 쓰면 안 됩니다.
            "holdout_is_overfit": holdout_is_overfit,
            "time_sorted_split": bool(has_time_column(df_feat)),
            "hyperparams": hyperparams or {},
            "interval": interval_meta,
            "status": "challenger",
        }
        with open(target_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata


trainer = ModelTrainer()
