"""
src/ml/trainer.py

일반화 ML 모델 학습기.
K-Fold 교차 검증 및 LightGBM/CatBoost 기반 사투가 예측 모델을 재학습하고
모델 레지스트리에 버저닝하여 아티팩트를 저장합니다.
"""

from __future__ import annotations

import json
import shutil
import tempfile
from pathlib import Path
from typing import Any

import joblib
import numpy as np
import pandas as pd

from src.app.core.timeutil import utcnow
from src.ml.conformal import (
    CALIBRATION_SPLIT,
    INTERVAL_QUANTILES,
    INTERVAL_TARGET_COVERAGE,
    QUANTILE_HYPERPARAM_KEY,
    QUANTILE_PARAM_OVERRIDES,
    _conformal_scale,
    _train_quantile_models,
)
from src.ml.features import (
    CATEGORICAL_FEATURES,
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.institution_history import attach_institution_history
from src.ml.repeat_history import attach_repeat_history
from src.ml.splitters import (
    DEFAULT_N_FOLDS,
    DEFAULT_VALIDATION_SPLIT,
    MIN_FOLD_SAMPLES,
    TIME_SORT_COLUMN,
    _sorted_positions,
    _time_based_kfold_splits,
    _time_based_split,
    has_time_column,
)
from src.ml.training_config import (
    CATEGORY_HYPERPARAMS,
    CATEGORY_MODEL_NAMES,
    DEFAULT_MODEL_NAME,
    LGB_BASE_PARAMS,
    NUMERIC_FEATURES,
    SERVC_EXTRA_FEATURES,
    TRAINING_FEATURES,
    hyperparams_for_category,
    model_name_for_category,
    training_features_for_category,
)
from src.ml.validate_model import evaluate_model_performance

__all__ = [
    "CALIBRATION_SPLIT",
    "CATEGORY_HYPERPARAMS",
    "CATEGORY_MODEL_NAMES",
    "DEFAULT_MODEL_NAME",
    "DEFAULT_N_FOLDS",
    "DEFAULT_VALIDATION_SPLIT",
    "INTERVAL_QUANTILES",
    "INTERVAL_TARGET_COVERAGE",
    "LGB_BASE_PARAMS",
    "MIN_FOLD_SAMPLES",
    "NUMERIC_FEATURES",
    "QUANTILE_HYPERPARAM_KEY",
    "QUANTILE_PARAM_OVERRIDES",
    "SERVC_EXTRA_FEATURES",
    "TIME_SORT_COLUMN",
    "TRAINING_FEATURES",
    "ModelTrainer",
    "_conformal_scale",
    "_sorted_positions",
    "_time_based_kfold_splits",
    "_time_based_split",
    "_train_quantile_models",
    "has_time_column",
    "hyperparams_for_category",
    "model_name_for_category",
    "trainer",
    "training_features_for_category",
]


def _best_iteration_of(model: Any, model_type: str) -> int | None:
    """조기 종료가 고른 트리 수를 꺼냅니다. 없으면 None."""
    if model_type == "lightgbm":
        value = getattr(model, "best_iteration_", None)
        return int(value) if value else None
    if model_type == "catboost":
        inner = getattr(model, "model", model)
        getter = getattr(inner, "get_best_iteration", None)
        value = getter() if callable(getter) else None
        return int(value) + 1 if value else None
    return None


def _refit_on_full(
    model_fn: Any,
    model_type: str,
    selected: Any,
    X: pd.DataFrame,
    y: np.ndarray,
    hyperparams: dict[str, Any] | None,
) -> Any:
    """선택된 모델을 전량 데이터로 다시 적합합니다.

    트리 수는 **선택 단계에서 조기 종료가 고른 값으로 고정**합니다. 그대로
    재적합하면 검증 구간이 학습에 포함돼 조기 종료가 판단 근거를 잃고, 설정된
    n_estimators 를 끝까지 써 과적합합니다.

    Ridge 처럼 반복 수 개념이 없는 모델은 그대로 재적합합니다.
    """
    fixed = dict(hyperparams or {})
    best_iteration = _best_iteration_of(selected, model_type)
    if best_iteration:
        fixed["n_estimators" if model_type == "lightgbm" else "iterations"] = best_iteration
    # 검증 인자에 전량을 넘깁니다. 조기 종료 콜백이 살아 있어도 학습 데이터를
    # 보므로 멈추지 않으며, 트리 수는 위에서 이미 고정했습니다.
    return model_fn(X, y, X, y, fixed or None)


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
    return np.asarray(numeric.to_numpy(dtype=float))


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
        return np.asarray(self.model.predict(_to_numeric_matrix(X)))


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
    #
    # 용역은 CATEGORY_HYPERPARAMS 에서 quantile(0.5)로 덮어씁니다. 여기 huber 는
    # 물품과 미지정 카테고리의 기본값입니다.
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
        return np.asarray(self.model.predict(frame))


def _cross_validate_model(
    df: pd.DataFrame,
    y: np.ndarray,
    model_fn,
    hyperparams: dict[str, Any] | None,
    n_folds: int,
    feature_columns: list[str] | None = None,
) -> dict[str, Any]:
    """K-Fold 교차 검증을 수행하고 평균 지표를 반환합니다."""
    X = df[feature_columns or TRAINING_FEATURES]
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

    aggregated: dict[str, object] = {}
    for key in fold_metrics[0]:
        aggregated[f"avg_{key}"] = round(float(np.mean([m[key] for m in fold_metrics])), 4)
        aggregated[f"std_{key}"] = round(float(np.std([m[key] for m in fold_metrics])), 4)
    aggregated["fold_count"] = len(fold_metrics)
    # 폴드별 원지표를 남깁니다. 평균만 저장하면 설계서 7장 필수 4
    # (어느 폴드도 R2 > 0.99 아닐 것)를 판정할 근거가 사라집니다.
    # ssh_hist_premium 은 5폴드 중 3개가 R2 0.9999999999999998 이었는데
    # 평균만 보면 그 사실이 드러나지 않습니다.
    aggregated["folds"] = fold_metrics
    return aggregated


class ModelTrainer:
    def __init__(
        self,
        model_name: str = DEFAULT_MODEL_NAME,
        registry_dir: str = "ml_registry",
        category_code: str | None = None,
    ):
        self.model_name = model_name
        self.registry_dir = Path(registry_dir)
        self.category_code = (category_code or "").strip() or None

    @classmethod
    def for_category(cls, category_code: str | None, registry_dir: str = "ml_registry"):
        """카테고리 전용 학습기를 만듭니다.

        분기가 없으면 용역 재학습이 물품 디렉터리에 저장되고 물품 champion 과
        비교됩니다. 서로 다른 제도를 쓰는 두 모델이 한 이름을 공유하게 됩니다.
        """
        return cls(model_name_for_category(category_code), registry_dir, category_code)

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

        # 기관 이력을 프레임 단위로 먼저 붙입니다. features.py 는 입력에 있는
        # inst_hist_rate 를 그대로 쓰므로, 여기서 채우면 단일 공급원이 유지됩니다.
        # 행당 DB 조회로는 32시간이 걸려 배치 계산을 씁니다.
        df_raw = attach_institution_history(df_raw)
        df_raw = attach_repeat_history(df_raw)
        feature_columns = training_features_for_category(self.category_code)
        effective_hyperparams = hyperparams_for_category(self.category_code, hyperparams)

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
        train_idx, valid_idx, y_train, y_valid = _time_based_split(df_feat, y, validation_split)
        X = df_feat[feature_columns]
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
            params = effective_hyperparams.get(name)
            # 모델 선택은 학습 구간 내부의 K-Fold 로만 합니다. 홀드아웃 점수로
            # 고르면 그 점수가 선택 편향으로 부풀려져 승격 판단이 낙관적이 됩니다.
            cv = _cross_validate_model(
                df_train, y_train, model_fn, params, n_folds, feature_columns
            )
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

        # **선택이 끝나면 전량으로 다시 적합합니다.**
        #
        # 위 후보들은 앞 80% 로만 학습했습니다. 홀드아웃 지표를 내려면 그래야
        # 하지만, 그 모델을 그대로 저장하면 **가장 최근 20% 를 영영 못 배운
        # 모델이 서빙됩니다.** 시계열 분할이라 그 20% 는 최신 구간입니다.
        #
        # 2026-08-05 실측이 그 대가를 보여 줍니다. 같은 2025년 하한율 보유
        # 구간에서 서빙 아티팩트가 MAE 0.9500, 2024년까지 전량으로 학습한
        # 실험 모델이 0.7616 이었습니다. 25% 차이가 전부 여기서 옵니다.
        # (측정: scripts/diagnose_serving_vs_holdout_model.py)
        #
        # metrics 는 재적합 전 홀드아웃 값을 그대로 둡니다. 저장 모델과 지표의
        # 학습 범위가 다르다는 뜻이므로 metadata 에 refit_on_full 로 명시합니다.
        # 승격 판정은 계속 홀드아웃 지표로 합니다. 전량 학습본의 지표를 내려면
        # 검증 구간이 학습에 포함돼 무의미해집니다.
        best_model = _refit_on_full(
            model_fns[model_type],
            model_type,
            best_model,
            X,
            y,
            effective_hyperparams.get(model_type),
        )

        # 아티팩트 원자적 저장: staging 에서 저장을 완료한 뒤 target_dir 로 이동합니다.
        # 중단 시 불완전한 아티팩트가 남아 latest_version 으로 선택되는 것을 방지합니다.
        model_dir = self.registry_dir / self.model_name
        model_dir.mkdir(parents=True, exist_ok=True)
        staging = Path(tempfile.mkdtemp(dir=str(model_dir), prefix=".train_staging_"))

        try:
            # 가중치 저장
            model_file = staging / "model.bin"
            joblib.dump(best_model, model_file)

            # 예측 구간. 큰 건일수록 산포가 커지는 이분산에 대한 설계서 6.3 의 대응입니다.
            # 트리 모델을 못 쓸 만큼 표본이 적으면 구간도 만들지 않습니다.
            interval_meta: dict[str, Any] = {"available": False}
            if use_tree_models:
                # 분위 모델도 같은 이유로 전량을 씁니다. 등각 보정 배율은 이 함수가
                # 내부에서 뒷부분을 떼어 산정하므로 누수가 아닙니다.
                quantile_models, _, interval_meta = _train_quantile_models(
                    X, y, effective_hyperparams.get(QUANTILE_HYPERPARAM_KEY)
                )
                for q, model in quantile_models.items():
                    joblib.dump(model, staging / f"model_q{int(q * 100):02d}.bin")
                interval_meta["available"] = True

            # 메타데이터 저장
            metadata = {
                "model_name": self.model_name,
                "version": version,
                "trained_at": utcnow().isoformat(),
                "samples_count": len(df_raw),
                "train_samples": len(train_idx),
                "validation_samples": len(valid_idx),
                # metrics 는 앞 80% 로 학습한 모델의 홀드아웃 값이고, 저장된 가중치는
                # 전량으로 재적합한 것입니다. 두 학습 범위가 다르다는 표시입니다.
                "refit_on_full": True,
                "features": list(feature_columns),
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
                "hyperparams": effective_hyperparams,
                "interval": interval_meta,
                "status": "challenger",
            }
            with open(staging / "metadata.json", "w", encoding="utf-8") as f:
                json.dump(metadata, f, indent=2, ensure_ascii=False)

            shutil.move(str(staging), str(target_dir))
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

        return metadata


trainer = ModelTrainer()
