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

# 점 추정 모델의 LightGBM 용량 설정입니다. 분위 모델은 아래
# QUANTILE_PARAM_OVERRIDES 로 따로 잡습니다.
#
# scripts/tune_servc_hyperparams.py 좌표 하강 17회 실측(2026-08-04, 학습
# 765,150행 / 검증 96,141행)에서 값어치가 있어 보인 축은 num_leaves 하나
# 뿐이었습니다.
#
# 그때 255 를 기각한 근거에는 사각지대가 있었습니다. 이 설정을 점 추정과 분위
# 모델이 함께 쓰고 있었기 때문에 리프를 올리면 **두 모델이 동시에** 바뀌었고,
# 관측된 "MAE 개선 + 구간 폭 11.2% 악화" 는 분리되지 않은 합계였습니다.
# 그래서 아래 QUANTILE_PARAM_OVERRIDES 로 두 축을 갈랐습니다. 분리 후에는 점
# 추정 용량을 키워도 구간 폭이 움직이지 않습니다(운영 실측 1.423%p 동일).
#
# 전량 재적합 결함 수정 전에는 리프를 올린 이득이 운영에서 나타나지 않았습니다.
# 같은 표본 1,000건의 당시 실측입니다.
#
#              홀드아웃 MAE   운영 MAE   운영 RMSE   운영 0.5%p 적중
#   리프  63       1.2838     0.9848      3.1195         75.2%
#   리프 127       1.2710     0.9863      3.1455         74.5%
#
# 이후 모델 선택 뒤 최신 20%를 버리던 결함을 고치고 동일 학습 상한으로 다시
# 평가하자 용역 리프 255 + EWM이 우세했습니다. 운영 3,999건에서도 MAE 3.42%
# 개선, 쌍대 절대오차 t=-7.50으로 재현됐습니다. 이 기본값 63은 물품과 미지정
# 카테고리에 유지하고, 용역만 CATEGORY_HYPERPARAMS에서 255로 재정의합니다.
# 근거는 docs/design/servc_unbiased_candidate_recheck_20260805.md 입니다.
#
# subsample 은 LightGBM 이 subsample_freq(기본 0)가 0 이면 통째로 무시합니다.
# 탐색에서 0.6/0.8/1.0 의 MAE 가 소수점 넷째 자리까지 같게 나온 것이 그
# 증거이며, 즉 이 설정은 지금까지 아무 일도 하지 않았습니다. 값을 지우면
# 과거 아티팩트와 파라미터 비교가 어긋나므로 남기되, 무효임을 여기 적습니다.
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

# 폴드 하나가 가져야 하는 최소 행 수. 트리 모델이 1행 입력에서 예외를 던집니다.
MIN_FOLD_SAMPLES = 2

# 카테고리별 모델 네임스페이스. 물품과 용역은 예정가격 산정과 낙찰자 결정이
# 서로 다른 제도라 한 이름을 공유하면 champion 비교가 뒤섞입니다.
#
# 공사는 아직 전용 모델을 학습하지 않았지만 이름은 미리 갈라 둡니다. 예전에는
# 미등록 카테고리가 DEFAULT_MODEL_NAME 으로 떨어져, 공사 재학습이 물품 디렉터리에
# 저장되고 물품 champion 과 비교됐을 것입니다. 학습을 돌리는 순간 물품 승격본을
# 덮어쓰는 경로였습니다.
#
# 서빙 매핑은 model_registry.CATEGORY_DEFAULT_MODELS 이며 지금은 공사를 v25 로
# 보냅니다. cnstwk_institution_v1 이 실제로 승격되기 전까지 두 매핑이 다른 것은
# 의도된 상태입니다. 승격 시점에 서빙 매핑도 함께 옮겨야 합니다.
DEFAULT_MODEL_NAME = "quantum_leap_v25_pro"
CATEGORY_MODEL_NAMES = {
    "Thng": "quantum_leap_v25_pro",
    "Servc": "servc_institution_v1",
    "Cnstwk": "cnstwk_institution_v1",
}

# 편향 없는 동일 학습 상한 재평가에서 용역은 리프 255와 기관 EWM 조합이
# 기준 대비 MAE 3.13%를 낮췄습니다. 물품에는 검증되지 않았으므로 적용하지 않습니다.
#
# objective 는 _train_lightgbm 의 기본값 huber(alpha=1.0)를 덮어씁니다. 용역 잔차는
# 0 에 몰린 비대칭 분포라 조건부 중앙값을 직접 겨냥하는 quantile(0.5)이 낫습니다.
# 2026년 out-of-sample 56,338건 실측에서 MAE 1.3554 -> 1.3312, 0.5%p 이내 적중
# 58.53% -> 59.65% 이고 7개 모집단 중 악화가 없었습니다. RMSE 는 2.7454 -> 2.7834
# 로 나빠지며 이는 L1 최적화의 대가로 수용한 값입니다.
#
# huber 의 alpha 를 줄여 L1 에 다가가는 방향은 기각됐습니다. alpha=0.2 는 gradient
# 가 +-alpha 로 고정돼 학습 신호가 평평해지고 MAE 1.7971 로 32% 나빴습니다. 두
# 목적함수는 연속적으로 이어지지 않습니다.
#
# 분위 모델(_train_quantile_models)은 hyperparams 를 받지 않으므로 이 재정의의
# 영향을 받지 않습니다. 점 추정만 바뀝니다.
# 근거: docs/design/servc_loss_function_20260807.md
#
# num_leaves 는 huber 아래에서 고른 255 가 quantile 에서도 최적이었습니다.
# 511 은 MAE 1.2560 으로 나쁘고 0.5%p 적중은 61.49% 로 더 떨어집니다. 용량은
# 손실함수가 아니라 범주 조합 구조가 정합니다. 목적함수를 바꿨다는 이유만으로
# 용량 축을 다시 훑을 필요가 없습니다.
#
# quantile 아래 좌표 하강이 찾은 min_child_samples 160 / learning_rate 0.03 /
# n_estimators 2000 / subsample_freq 5 조합은 기각했습니다. 홀드아웃에서 MAE
# 1.2562 -> 1.2525 였고 시드 3개 전부 일관이었는데도, 운영 8,995건 쌍대에서
# 1.4050 -> 1.4188 로 t=5.14 만큼 나빴습니다. 6개 집단 중 challenger 우세는
# 0개입니다. 원인은 조기 종료입니다. _train_lightgbm 은 early_stopping(10)을
# 걸지만 탐색 스크립트는 걸지 않아, 낮춘 학습률이 탐색에서는 2000 그루로
# 보상되고 운영에서는 조기 종료로 잘립니다.
# 근거: docs/design/servc_hyperparam_quantile_20260807.md
CATEGORY_HYPERPARAMS = {
    "Servc": {"lightgbm": {"num_leaves": 255, "objective": "quantile", "alpha": 0.5}}
}


def model_name_for_category(category_code: str | None) -> str:
    """카테고리 코드를 모델 네임스페이스로 옮깁니다.

    모르는 코드를 조용히 DEFAULT_MODEL_NAME 으로 떨어뜨리지 않습니다. 그 동작은
    다른 제도의 학습 산출물을 물품 이름으로 저장해 물품 champion 을 덮어씁니다.
    카테고리를 새로 학습하려면 CATEGORY_MODEL_NAMES 에 먼저 등록하십시오.
    """
    code = (category_code or "").strip()
    if not code:
        return DEFAULT_MODEL_NAME
    if code not in CATEGORY_MODEL_NAMES:
        raise ValueError(
            f"모델 네임스페이스가 없는 카테고리입니다: {code}. "
            f"CATEGORY_MODEL_NAMES 에 등록하십시오 (등록됨: {sorted(CATEGORY_MODEL_NAMES)})"
        )
    return CATEGORY_MODEL_NAMES[code]


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
SERVC_EXTRA_FEATURES = ["inst_ewm_rate"]


def training_features_for_category(category_code: str | None) -> list[str]:
    """검증된 카테고리에만 추가 특징을 적용합니다."""
    if (category_code or "").strip() == "Servc":
        return [*TRAINING_FEATURES, *SERVC_EXTRA_FEATURES]
    return list(TRAINING_FEATURES)


def hyperparams_for_category(
    category_code: str | None,
    overrides: dict[str, Any] | None = None,
) -> dict[str, dict[str, Any]]:
    """카테고리 기본값에 호출자 재정의를 모델별로 병합합니다."""
    effective = {
        name: dict(params)
        for name, params in CATEGORY_HYPERPARAMS.get((category_code or "").strip(), {}).items()
    }
    for name, params in (overrides or {}).items():
        effective[name] = {**effective.get(name, {}), **params}
    return effective


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
        return self.model.predict(frame)


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

    aggregated = {}
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

    params = {**LGB_BASE_PARAMS, **QUANTILE_PARAM_OVERRIDES}
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
        target_dir.mkdir(parents=True, exist_ok=True)

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

        # 가중치 저장
        model_file = target_dir / "model.bin"
        joblib.dump(best_model, model_file)

        # 예측 구간. 큰 건일수록 산포가 커지는 이분산에 대한 설계서 6.3 의 대응입니다.
        # 트리 모델을 못 쓸 만큼 표본이 적으면 구간도 만들지 않습니다.
        interval_meta: dict[str, Any] = {"available": False}
        if use_tree_models:
            # 분위 모델도 같은 이유로 전량을 씁니다. 등각 보정 배율은 이 함수가
            # 내부에서 뒷부분을 떼어 산정하므로 누수가 아닙니다.
            quantile_models, _, interval_meta = _train_quantile_models(X, y)
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
        with open(target_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata


trainer = ModelTrainer()
