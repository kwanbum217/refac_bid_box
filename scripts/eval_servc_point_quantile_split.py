#!/usr/bin/env python3
"""
점 추정 모델과 분위 모델의 `num_leaves` 를 분리했을 때를 잽니다.

`num_leaves` 255 를 기각했던 근거(`servc_hyperparam_search_20260804.md` 6장)에는
사각지대가 있었습니다. 학습기가 `LGB_BASE_PARAMS` 하나를 점 추정과 분위 모델에
함께 쓰기 때문에(`trainer.py::_train_quantile_models`), 255 로 올리면 **두 모델이
동시에** 바뀝니다. 그래서 그때 관측한 "MAE 는 좋아지고 구간 폭은 나빠짐" 은
분리 불가능한 합계였습니다.

두 모델의 목표는 다릅니다.

- 점 추정: MAE 와 0.5%p 적중
- 분위: 등각 보정 후 구간 폭 (피복률은 보정이 보장)

그러므로 점 추정만 255, 분위는 63 으로 두면 양쪽의 좋은 쪽만 취할 수 있는지가
쟁점입니다. 구간 폭은 분위 모델만 결정하므로 두 축은 독립이며, 여기서는 그
독립성을 실측으로 확인한 뒤 조합표로 제시합니다.

사용법:
    .venv/bin/python scripts/eval_servc_point_quantile_split.py
    .venv/bin/python scripts/eval_servc_point_quantile_split.py --point-leaves 63,255
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
from sklearn.metrics import mean_squared_error, r2_score  # noqa: E402

from scripts.eval_servc_year_holdout import ALL_FEATURES, build_frame  # noqa: E402
from src.ml.trainer import (  # noqa: E402
    CALIBRATION_SPLIT,
    INTERVAL_QUANTILES,
    INTERVAL_TARGET_COVERAGE,
    LGB_BASE_PARAMS,
    _conformal_scale,
)

# 학습 경로와 같은 목적함수여야 평가가 운영을 대변합니다.
POINT_OBJECTIVE = {"objective": "huber", "alpha": 1.0}


def _params(leaves: int, *, quantile: bool) -> dict:
    params = {**LGB_BASE_PARAMS, "num_leaves": leaves}
    params.pop("objective", None)
    params.pop("alpha", None)
    return params if quantile else {**params, **POINT_OBJECTIVE}


def measure_point(train: pd.DataFrame, valid: pd.DataFrame, leaves: int) -> dict:
    """점 추정 지표만 잽니다. 구간과 무관합니다."""
    started = time.perf_counter()
    model = lgb.LGBMRegressor(**_params(leaves, quantile=False))
    model.fit(train[ALL_FEATURES], train["winning_rate"])
    pred = model.predict(valid[ALL_FEATURES])
    actual = valid["winning_rate"].to_numpy(dtype=float)
    error = np.abs(pred - actual)
    return {
        "점추정 리프": leaves,
        "MAE": round(float(error.mean()), 4),
        "RMSE": round(float(np.sqrt(mean_squared_error(actual, pred))), 4),
        "R2": round(float(r2_score(actual, pred)), 4),
        "0.5%p 적중": round(float((error <= 0.5).mean()), 4),
        "1%p 적중": round(float((error <= 1.0).mean()), 4),
        "학습 초": round(time.perf_counter() - started, 1),
    }


def measure_interval(train: pd.DataFrame, valid: pd.DataFrame, leaves: int) -> dict:
    """분위 지표만 잽니다. `trainer._train_quantile_models` 와 순서를 맞춥니다."""
    cut = int(len(train) * (1 - CALIBRATION_SPLIT))
    fit_part, cal_part = train.iloc[:cut], train.iloc[cut:]
    params = _params(leaves, quantile=True)

    def _fit(frame: pd.DataFrame, q: float):
        model = lgb.LGBMRegressor(objective="quantile", alpha=q, **params)
        model.fit(frame[ALL_FEATURES], frame["winning_rate"])
        return model

    low_q, high_q = INTERVAL_QUANTILES
    cal_lo = _fit(fit_part, low_q).predict(cal_part[ALL_FEATURES])
    cal_hi = _fit(fit_part, high_q).predict(cal_part[ALL_FEATURES])
    scale = _conformal_scale(
        cal_part["winning_rate"].to_numpy(dtype=float), cal_lo, cal_hi, INTERVAL_TARGET_COVERAGE
    )

    lo = _fit(train, low_q).predict(valid[ALL_FEATURES])
    hi = _fit(train, high_q).predict(valid[ALL_FEATURES])
    center = (lo + hi) / 2
    half = np.maximum((hi - lo) / 2, 1e-9) * scale
    lo_c, hi_c = center - half, center + half
    actual = valid["winning_rate"].to_numpy(dtype=float)
    return {
        "분위 리프": leaves,
        "배율": round(scale, 4),
        "구간 폭": round(float(np.median(hi_c - lo_c)), 4),
        "피복률": round(float(((actual >= lo_c) & (actual <= hi_c)).mean()), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--point-leaves", default="63,127,255")
    parser.add_argument("--quantile-leaves", default="63,255")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df = build_frame(path, args.train_end)
    year = df["openg_dt"].dt.year
    train = df[year <= args.train_end]
    valid = df[year == args.valid_year].copy()
    print(f"학습 {len(train):,}행 / 검증 {len(valid):,}행")
    print(
        f"현행 공유 리프 {LGB_BASE_PARAMS['num_leaves']} / 명목 피복률 {INTERVAL_TARGET_COVERAGE:.0%}\n"
    )

    print("점 추정")
    point_rows = []
    for leaves in (int(v) for v in args.point_leaves.split(",")):
        row = measure_point(train, valid, leaves)
        point_rows.append(row)
        print(
            f"  리프 {leaves:>4}: MAE {row['MAE']:.4f} / RMSE {row['RMSE']:.4f} / "
            f"0.5%p {row['0.5%p 적중']:.2%} / {row['학습 초']}초",
            flush=True,
        )

    print("\n분위")
    interval_rows = []
    for leaves in (int(v) for v in args.quantile_leaves.split(",")):
        row = measure_interval(train, valid, leaves)
        interval_rows.append(row)
        print(
            f"  리프 {leaves:>4}: 배율 {row['배율']:.4f} / 폭 {row['구간 폭']:.4f}%p / "
            f"피복 {row['피복률']:.2%}",
            flush=True,
        )

    print(f"\n{'=' * 92}\n조합\n{'=' * 92}")
    combos = pd.DataFrame([{**p, **i} for p in point_rows for i in interval_rows])[
        ["점추정 리프", "분위 리프", "MAE", "0.5%p 적중", "구간 폭", "피복률"]
    ]
    print(combos.to_string(index=False))

    base = combos[
        (combos["점추정 리프"] == LGB_BASE_PARAMS["num_leaves"])
        & (combos["분위 리프"] == LGB_BASE_PARAMS["num_leaves"])
    ]
    if not base.empty:
        b = base.iloc[0]
        print(f"\n현행 기준 MAE {b['MAE']:.4f} / 폭 {b['구간 폭']:.4f}%p")
        better = combos[(combos["MAE"] < b["MAE"]) & (combos["구간 폭"] <= b["구간 폭"])]
        if better.empty:
            print("MAE 와 구간 폭을 동시에 개선하는 조합이 없습니다.")
        else:
            print("MAE 개선 + 폭 비악화 조합:")
            print(better.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
