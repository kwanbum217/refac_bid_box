#!/usr/bin/env python3
"""
전량 재적합의 이득을 **낙관 편향 없이** 잽니다.

운영 쌍대 비교에서 재적합본이 MAE -6.3%, 구간 폭 -18.5% 로 크게 앞섰습니다.
그러나 그 모델은 2025년을 학습에 포함하므로 2025년 공고 평가가 낙관적입니다.

편향을 없애려면 **두 모델 모두 2024년까지만** 학습시키고 2025년으로 재면
됩니다. 그러면 차이는 오직 "학습 구간을 다 쓰는가" 에서만 옵니다.

    구 방식  2015~2024 중 앞 80% 로 학습   (재적합 전 trainer 와 같음)
    신 방식  2015~2024 전량으로 학습        (재적합 후 trainer 와 같음)

조기 종료 처리도 운영과 맞춥니다. 구 방식은 뒤 20% 를 검증으로 쓰고, 신 방식은
그 조기 종료가 고른 트리 수를 고정해 전량으로 다시 적합합니다.

사용법:
    .venv/bin/python scripts/eval_servc_refit_unbiased.py
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

from scripts.eval_servc_year_holdout import ALL_FEATURES, build_frame  # noqa: E402
from src.ml.trainer import DEFAULT_VALIDATION_SPLIT, LGB_BASE_PARAMS  # noqa: E402

POINT_OBJECTIVE = {"objective": "huber", "alpha": 1.0}
T_THRESHOLD = 2.0


def fit_split_only(train: pd.DataFrame) -> tuple[object, int]:
    """구 방식. 앞 80% 로만 학습하고 그 모델을 그대로 씁니다."""
    cut = int(len(train) * (1 - DEFAULT_VALIDATION_SPLIT))
    fit_part, valid_part = train.iloc[:cut], train.iloc[cut:]
    model = lgb.LGBMRegressor(**{**LGB_BASE_PARAMS, **POINT_OBJECTIVE})
    model.fit(
        fit_part[ALL_FEATURES],
        fit_part["winning_rate"],
        eval_set=[(valid_part[ALL_FEATURES], valid_part["winning_rate"])],
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )
    return model, int(getattr(model, "best_iteration_", 0) or LGB_BASE_PARAMS["n_estimators"])


def fit_refit_full(train: pd.DataFrame, best_iteration: int) -> object:
    """신 방식. 조기 종료가 고른 트리 수를 고정해 전량으로 다시 적합합니다."""
    params = {**LGB_BASE_PARAMS, **POINT_OBJECTIVE, "n_estimators": best_iteration}
    model = lgb.LGBMRegressor(**params)
    model.fit(train[ALL_FEATURES], train["winning_rate"])
    return model


def paired(diff: np.ndarray, label: str) -> dict:
    n = len(diff)
    mean = float(diff.mean())
    se = float(diff.std(ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    t = mean / se if se > 0 else 0.0
    verdict = "판별 불가" if abs(t) < T_THRESHOLD else ("전량 우세" if mean < 0 else "80% 우세")
    return {
        "지표": label,
        "평균 차이": round(mean, 5),
        "표준오차": round(se, 5),
        "t": round(t, 2),
        "판정": verdict,
    }


def score(actual: np.ndarray, pred: np.ndarray, label: str) -> dict:
    error = np.abs(pred - actual)
    return {
        "방식": label,
        "MAE": round(float(error.mean()), 4),
        "RMSE": round(float(np.sqrt(((pred - actual) ** 2).mean())), 4),
        "R2": round(
            1 - float(((pred - actual) ** 2).sum() / ((actual - actual.mean()) ** 2).sum()), 4
        ),
        "0.5%p 적중": round(float((error <= 0.5).mean()), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    frame = build_frame(path, args.train_end)
    year = frame["openg_dt"].dt.year
    train = frame[year <= args.train_end]
    valid = frame[year == args.valid_year].copy()
    print(
        f"학습 {len(train):,}행 (~{args.train_end}년) / 검증 {len(valid):,}행 ({args.valid_year}년)"
    )
    print("두 모델 모두 검증 연도를 학습하지 않습니다. 낙관 편향이 없습니다.\n")

    started = time.perf_counter()
    old_model, best_iteration = fit_split_only(train)
    cut = int(len(train) * (1 - DEFAULT_VALIDATION_SPLIT))
    print(
        f"  구 방식: {cut:,}행 학습 / 조기 종료 트리 {best_iteration} ({time.perf_counter() - started:.0f}초)"
    )

    started = time.perf_counter()
    new_model = fit_refit_full(train, best_iteration)
    print(
        f"  신 방식: {len(train):,}행 학습 / 트리 {best_iteration} 고정 ({time.perf_counter() - started:.0f}초)\n"
    )

    actual = valid["winning_rate"].to_numpy(dtype=float)
    old_pred = np.asarray(old_model.predict(valid[ALL_FEATURES]), dtype=float)
    new_pred = np.asarray(new_model.predict(valid[ALL_FEATURES]), dtype=float)

    rows = [
        score(actual, old_pred, "구 방식 (앞 80%)"),
        score(actual, new_pred, "신 방식 (전량 재적합)"),
    ]
    print(f"{'=' * 88}\n결과\n{'=' * 88}")
    print(pd.DataFrame(rows).to_string(index=False))

    old_err, new_err = np.abs(old_pred - actual), np.abs(new_pred - actual)
    stats = pd.DataFrame(
        [
            paired(new_err - old_err, "절대오차"),
            paired(new_err**2 - old_err**2, "제곱오차"),
        ]
    )
    print(f"\n{'=' * 88}\n쌍대 비교 (전량 - 80%)\n{'=' * 88}")
    print(stats.to_string(index=False))

    gain = float(rows[0]["MAE"]) - float(rows[1]["MAE"])
    print(f"\nMAE {gain:+.4f} ({gain / float(rows[0]['MAE']):+.2%})")
    print(f"전량 쪽이 더 정확한 공고 비율: {float((new_err < old_err).mean()):.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
