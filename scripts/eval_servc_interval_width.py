#!/usr/bin/env python3
"""
분위 모델의 복잡도가 최종 예측 구간 폭에 어떻게 작용하는지 잽니다.

`num_leaves` 255 를 기각한 근거가 여기서 나왔습니다. 리프를 늘리자 분위 모델이
학습 구간에 더 잘 맞아 원래 구간은 좁아졌는데, 그만큼 등각예측 배율이 커져
**최종 폭은 오히려 넓어졌습니다** (1.423 -> 1.583%p).

그렇다면 반대 방향은 어떤가 — 분위 모델을 일부러 덜 적합시키면 배율이 작아져
최종 폭이 줄어드는가? 피복률은 등각예측이 보장하므로 **폭만 비교하면 우열이
결정됩니다.**

점 추정 모델은 건드리지 않습니다. 분위 아티팩트만 바꿔 끼우면 되므로 운영
반영 비용이 낮습니다.

사용법:
    .venv/bin/python scripts/eval_servc_interval_width.py
    .venv/bin/python scripts/eval_servc_interval_width.py --leaves 15,31,63,127
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path
from typing import TypedDict, cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.eval_servc_year_holdout import ALL_FEATURES, build_frame  # noqa: E402
from src.ml.trainer import (  # noqa: E402
    CALIBRATION_SPLIT,
    INTERVAL_QUANTILES,
    INTERVAL_TARGET_COVERAGE,
    LGB_BASE_PARAMS,
    QUANTILE_PARAM_OVERRIDES,
    _conformal_scale,
)

# 이 스크립트가 흔드는 축은 분위 모델의 리프입니다. 점 추정 설정과는 무관합니다.
CURRENT_QUANTILE_LEAVES = QUANTILE_PARAM_OVERRIDES["num_leaves"]


class _LGBMQuantileParams(TypedDict, total=False):
    n_estimators: int
    learning_rate: float
    num_leaves: int
    min_child_samples: int
    subsample: float
    colsample_bytree: float
    random_state: int
    verbose: int
    n_jobs: int


def evaluate(train: pd.DataFrame, valid: pd.DataFrame, leaves: int) -> dict:
    """학습기와 같은 절차로 분위 모델을 만들고 보정한 뒤 폭을 잽니다.

    `trainer._train_quantile_models` 와 순서를 맞춥니다. 보정 구간으로 배율을
    산정한 뒤 분위 모델은 전량으로 재적합합니다.
    """
    cut = int(len(train) * (1 - CALIBRATION_SPLIT))
    fit_part, cal_part = train.iloc[:cut], train.iloc[cut:]

    params = {**LGB_BASE_PARAMS, **QUANTILE_PARAM_OVERRIDES, "num_leaves": leaves}
    params.pop("objective", None)
    params.pop("alpha", None)

    def _fit(frame: pd.DataFrame, q: float):
        model = lgb.LGBMRegressor(
            objective="quantile", alpha=q, **cast(_LGBMQuantileParams, params)
        )
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
    inside = (actual >= lo_c) & (actual <= hi_c)
    return {
        "num_leaves": leaves,
        "배율": round(scale, 4),
        "보정 전 폭": round(float(np.median(hi - lo)), 4),
        "보정 후 폭": round(float(np.median(hi_c - lo_c)), 4),
        "피복률": round(float(inside.mean()), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--leaves", default="15,31,63,127")
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
    print(f"명목 피복률 {INTERVAL_TARGET_COVERAGE:.0%} / 분위 {INTERVAL_QUANTILES}")

    rows = []
    for leaves in (int(v) for v in args.leaves.split(",")):
        result = evaluate(train, valid, leaves)
        rows.append(result)
        print(
            f"  리프 {leaves:>4}: 배율 {result['배율']:.4f} / "
            f"폭 {result['보정 전 폭']:.3f} -> {result['보정 후 폭']:.3f}%p / "
            f"피복 {result['피복률']:.2%}",
            flush=True,
        )

    table = pd.DataFrame(rows)
    print(f"\n{'=' * 92}\n결과\n{'=' * 92}")
    print(table.to_string(index=False))

    best = table.loc[table["보정 후 폭"].idxmin()]
    current = table[table["num_leaves"] == CURRENT_QUANTILE_LEAVES]
    print(f"\n최소 폭: 리프 {int(best['num_leaves'])} / {best['보정 후 폭']}%p")
    if not current.empty:
        base_width = float(current.iloc[0]["보정 후 폭"])
        gain = base_width - float(best["보정 후 폭"])
        print(
            f"현행 분위(리프 {CURRENT_QUANTILE_LEAVES}) 대비 {gain:+.4f}%p ({gain / base_width:+.2%})"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
