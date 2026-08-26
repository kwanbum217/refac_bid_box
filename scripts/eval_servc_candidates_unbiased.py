#!/usr/bin/env python3
"""용역 점 추정 후보를 같은 학습 상한에서 편향 없이 쌍대 비교합니다.

모든 후보는 2024년까지의 데이터만 보고 2025년을 예측합니다. 각 후보는 내부
시간순 80/20 분할에서 조기 종료 트리 수를 고른 뒤 2024년 전량으로 재적합하므로
현재 운영 학습기의 ``refit_on_full`` 동작과 같습니다.

사용법:
    .venv/bin/python scripts/eval_servc_candidates_unbiased.py
"""

from __future__ import annotations

import argparse
import sys
import time
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.ml.features import (  # noqa: E402
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.institution_history import EWM_HALFLIFE, attach_institution_history  # noqa: E402
from src.ml.repeat_history import attach_repeat_history  # noqa: E402
from src.ml.trainer import (  # noqa: E402
    CATEGORICAL_FEATURES,
    DEFAULT_VALIDATION_SPLIT,
    LGB_BASE_PARAMS,
    TRAINING_FEATURES,
)

T_THRESHOLD = 2.0


def _huber_regressor(*, num_leaves: int, n_estimators: int | None = None) -> lgb.LGBMRegressor:
    return lgb.LGBMRegressor(
        n_estimators=n_estimators or int(LGB_BASE_PARAMS["n_estimators"]),
        learning_rate=float(LGB_BASE_PARAMS["learning_rate"]),
        num_leaves=num_leaves,
        min_child_samples=int(LGB_BASE_PARAMS["min_child_samples"]),
        subsample=float(LGB_BASE_PARAMS["subsample"]),
        colsample_bytree=float(LGB_BASE_PARAMS["colsample_bytree"]),
        random_state=int(LGB_BASE_PARAMS["random_state"]),
        verbose=int(LGB_BASE_PARAMS["verbose"]),
        n_jobs=int(LGB_BASE_PARAMS["n_jobs"]),
        objective="huber",
        alpha=1.0,
    )


def attach_ewm_history(raw: pd.DataFrame, halflife: int) -> str:
    """누수 없이 0~1 비율의 기관별 지수감쇠 이력을 붙입니다."""
    raw.sort_values("openg_dt", inplace=True)
    column = f"inst_ewm_{halflife}"
    rate = raw["winning_rate"] / 100.0
    shifted = rate.groupby(raw["dminstt_nm"], observed=True).transform(
        lambda values: values.shift(1).ewm(halflife=halflife, ignore_na=True).mean()
    )
    raw[column] = shifted.groupby([raw["dminstt_nm"], raw["openg_dt"]], observed=True).transform(
        lambda values: values.iloc[0]
    )
    raw[column] = raw[column].fillna(raw["inst_hist_rate"])
    return column


def build_training_frame(path: Path, halflife: int) -> tuple[pd.DataFrame, str]:
    """운영 trainer와 같은 단일 특징 공급원으로 평가 프레임을 만듭니다."""
    if halflife != EWM_HALFLIFE:
        raise ValueError(f"운영 EWM 반감기는 {EWM_HALFLIFE}건입니다: {halflife}")
    raw = pd.read_parquet(path)
    raw = raw[raw["winning_rate"].notna()].copy()
    raw["openg_dt"] = pd.to_datetime(raw["openg_dt"], errors="coerce")
    raw = attach_institution_history(raw)
    raw = attach_repeat_history(raw)
    ewm_feature = "inst_ewm_rate"

    feature_frame = pd.DataFrame(build_feature_frame(raw.to_dict(orient="records")))
    levels = collect_category_levels(feature_frame)
    feature_frame = apply_categorical_dtypes(feature_frame, levels)
    feature_frame["openg_dt"] = raw["openg_dt"].to_numpy()
    feature_frame["winning_rate"] = raw["winning_rate"].to_numpy(dtype=float)
    feature_frame[ewm_feature] = raw[ewm_feature].to_numpy(dtype=float)
    return feature_frame.sort_values("openg_dt").reset_index(drop=True), ewm_feature


def fit_refit_full(
    train: pd.DataFrame,
    features: list[str],
    leaves: int,
) -> tuple[lgb.LGBMRegressor, int]:
    """내부 검증으로 트리 수를 고른 뒤 같은 학습 상한 전량에 재적합합니다."""
    cut = int(len(train) * (1 - DEFAULT_VALIDATION_SPLIT))
    fit_part, valid_part = train.iloc[:cut], train.iloc[cut:]
    categoricals = [column for column in CATEGORICAL_FEATURES if column in features]

    selected = _huber_regressor(num_leaves=leaves)
    selected.fit(
        fit_part[features],
        fit_part["winning_rate"],
        eval_set=[(valid_part[features], valid_part["winning_rate"])],
        categorical_feature=categoricals,
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )
    best_iteration = int(getattr(selected, "best_iteration_", 0) or LGB_BASE_PARAMS["n_estimators"])

    refit = _huber_regressor(num_leaves=leaves, n_estimators=best_iteration)
    refit.fit(
        train[features],
        train["winning_rate"],
        categorical_feature=categoricals,
    )
    return refit, best_iteration


def score(actual: np.ndarray, pred: np.ndarray, missing: np.ndarray) -> dict[str, float]:
    error = np.abs(pred - actual)
    return {
        "MAE": float(error.mean()),
        "RMSE": float(np.sqrt(np.mean((pred - actual) ** 2))),
        "0.5%p 적중": float((error <= 0.5).mean()),
        "하한율 보유 MAE": float(error[~missing].mean()),
        "하한율 결측 MAE": float(error[missing].mean()),
    }


def paired(diff: np.ndarray, metric: str) -> dict[str, object]:
    n = len(diff)
    mean = float(diff.mean())
    se = float(diff.std(ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    t_value = mean / se if se > 0 else 0.0
    verdict = (
        "판별 불가" if abs(t_value) < T_THRESHOLD else ("후보 우세" if mean < 0 else "기준 우세")
    )
    return {
        "지표": metric,
        "평균 차이": mean,
        "표준오차": se,
        "최소 감지 차이": T_THRESHOLD * se,
        "t": t_value,
        "판정": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--leaves", default="127,255")
    parser.add_argument("--halflife", type=int, default=20)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    started = time.perf_counter()
    frame, ewm_feature = build_training_frame(path, args.halflife)
    print(f"특징 프레임 생성: {time.perf_counter() - started:.1f}초", flush=True)

    base_features = list(TRAINING_FEATURES)
    missing_features = [column for column in base_features if column not in frame]
    if missing_features:
        print(f"운영 특징이 평가 프레임에 없습니다: {missing_features}")
        return 1

    year = frame["openg_dt"].dt.year
    train = frame[year <= args.train_end].copy()
    valid = frame[year == args.valid_year].copy()
    if train.empty or valid.empty:
        print(f"구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
        return 1

    print(
        f"학습 {len(train):,}행 (~{args.train_end}년) / 검증 {len(valid):,}행 ({args.valid_year}년)"
    )
    print(f"운영과 같은 기준 특징 {len(base_features)}개를 사용합니다.\n")

    candidates = [("기준 리프 63", 63, base_features)]
    candidates.extend(
        (f"리프 {leaves}", leaves, base_features)
        for leaves in (int(value) for value in args.leaves.split(","))
    )
    candidates.append((f"지수감쇠 반감기 {args.halflife}건", 63, [*base_features, ewm_feature]))
    largest_leaves = max(int(value) for value in args.leaves.split(","))
    candidates.append(
        (
            f"리프 {largest_leaves} + 지수감쇠",
            largest_leaves,
            [*base_features, ewm_feature],
        )
    )

    actual = valid["winning_rate"].to_numpy(dtype=float)
    missing = valid["lwlt_rate_missing"].to_numpy(dtype=bool)
    predictions: dict[str, np.ndarray] = {}
    rows = []
    for label, leaves, features in candidates:
        fit_started = time.perf_counter()
        model, best_iteration = fit_refit_full(train, features, leaves)
        pred = np.asarray(model.predict(valid[features]), dtype=np.float64)
        predictions[label] = pred
        rows.append(
            {
                "후보": label,
                "특징 수": len(features),
                "트리 수": best_iteration,
                **score(actual, pred, missing),
                "학습 초": time.perf_counter() - fit_started,
            }
        )
        print(f"  {label}: 완료 ({rows[-1]['학습 초']:.1f}초)", flush=True)

    result = pd.DataFrame(rows)
    numeric_columns = [
        "MAE",
        "RMSE",
        "0.5%p 적중",
        "하한율 보유 MAE",
        "하한율 결측 MAE",
        "학습 초",
    ]
    result[numeric_columns] = result[numeric_columns].round(5)
    print(f"\n{'=' * 112}\n성능\n{'=' * 112}")
    print(result.to_string(index=False))

    base_pred = predictions["기준 리프 63"]
    base_error = np.abs(base_pred - actual)
    comparisons = []
    for label, pred in predictions.items():
        if label == "기준 리프 63":
            continue
        candidate_error = np.abs(pred - actual)
        for row in (
            paired(candidate_error - base_error, "절대오차"),
            paired(candidate_error**2 - base_error**2, "제곱오차"),
        ):
            comparisons.append({"후보": label, **row})

    comparison = pd.DataFrame(comparisons)
    for column in ("평균 차이", "표준오차", "최소 감지 차이", "t"):
        comparison[column] = comparison[column].round(5 if column != "t" else 2)
    print(f"\n{'=' * 112}\n쌍대 비교 (후보 - 기준)\n{'=' * 112}")
    print(comparison.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
