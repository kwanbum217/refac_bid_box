#!/usr/bin/env python3
"""
분위 모델 리프별 구간 폭을 **집단별 피복률과 함께** 잽니다.

`eval_servc_interval_width.py` 는 전체 폭만 봅니다. 그런데 등각 배율은 전역
하나라, 리프를 바꾸면 전체 피복률은 유지되면서 **집단 간 배분만 옮겨갈 수**
있습니다. 하한율 결측 집단은 구간 폭이 보유 집단의 7배라 이 이동을 가장 크게
받습니다(`servc_interval_by_group_20260806.md`).

폭만 보고 고르면 그 이동을 못 봅니다. 그래서 리프마다 전체 폭·피복률과
하한율 보유/결측 집단의 폭·피복률을 같이 냅니다.

검증 연도를 인자로 받습니다. 홀드아웃 이득은 분할 변동 안에 있을 수 있으므로
(`servc_split_variance_20260810.md`) 한 해로 판정하지 마십시오.

사용법:
    .venv/bin/python scripts/eval_servc_interval_width_by_group.py
    .venv/bin/python scripts/eval_servc_interval_width_by_group.py --train-end 2023 --valid-year 2024
"""

from __future__ import annotations

import argparse
import sys
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
from src.ml.trainer import (  # noqa: E402
    CALIBRATION_SPLIT,
    INTERVAL_QUANTILES,
    INTERVAL_TARGET_COVERAGE,
    LGB_BASE_PARAMS,
    QUANTILE_PARAM_OVERRIDES,
    _conformal_scale,
)

CURRENT_QUANTILE_LEAVES = QUANTILE_PARAM_OVERRIDES["num_leaves"]

# build_frame 이 lwlt_rate 를 중앙값으로 채우면서 원래 결측 여부를 이 컬럼에
# 남겨 둡니다. 원본 parquet 를 다시 읽어 위치로 붙이면 어긋납니다. build_frame 이
# 마지막에 openg_dt 로 정렬하고 인덱스를 다시 매기기 때문입니다.
LWLT_MISSING_COLUMN = "lwlt_rate_missing"


def _bounds(
    train: pd.DataFrame, valid: pd.DataFrame, leaves: int
) -> tuple[np.ndarray, np.ndarray, float]:
    """학습기와 같은 순서로 보정 배율을 산정하고 검증 구간 구간을 냅니다."""
    cut = int(len(train) * (1 - CALIBRATION_SPLIT))
    fit_part, cal_part = train.iloc[:cut], train.iloc[cut:]

    params = {**LGB_BASE_PARAMS, **QUANTILE_PARAM_OVERRIDES, "num_leaves": leaves}
    params.pop("objective", None)
    params.pop("alpha", None)

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
    return center - half, center + half, scale


def _summarize(actual: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> dict:
    inside = (actual >= lo) & (actual <= hi)
    coverage = float(inside.mean())
    n = len(actual)
    # 피복률의 표준오차. 리프 간 차이를 표본 잡음과 구분하는 데 씁니다.
    stderr = float(np.sqrt(coverage * (1 - coverage) / n)) if n else float("nan")
    return {
        "건수": n,
        "폭": round(float(np.median(hi - lo)), 4),
        "피복률": round(coverage, 4),
        "피복 표준오차": round(stderr, 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--leaves", default="31,63,127,255")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df = build_frame(path, args.train_end)
    df["하한율"] = np.where(df[LWLT_MISSING_COLUMN] > 0, "결측", "보유")

    year = df["openg_dt"].dt.year
    train = df[year <= args.train_end]
    valid = df[year == args.valid_year].copy()
    print(f"학습 {len(train):,}행 / 검증 {len(valid):,}행 (검증 {args.valid_year}년)")
    print(f"명목 피복률 {INTERVAL_TARGET_COVERAGE:.0%} / 분위 {INTERVAL_QUANTILES}")
    print(
        f"검증 집단: 보유 {(valid['하한율'] == '보유').sum():,} / 결측 {(valid['하한율'] == '결측').sum():,}"
    )

    actual = valid["winning_rate"].to_numpy(dtype=float)
    rows = []
    for leaves in (int(v) for v in args.leaves.split(",")):
        lo, hi, scale = _bounds(train, valid, leaves)
        row = {"num_leaves": leaves, "배율": round(scale, 4)}
        row.update({f"전체 {k}": v for k, v in _summarize(actual, lo, hi).items()})
        for group in ("보유", "결측"):
            mask = (valid["하한율"] == group).to_numpy()
            row.update(
                {f"{group} {k}": v for k, v in _summarize(actual[mask], lo[mask], hi[mask]).items()}
            )
        rows.append(row)
        print(
            f"  리프 {leaves:>4}: 배율 {scale:.4f} / 전체 폭 {row['전체 폭']:.4f} 피복 {row['전체 피복률']:.2%}"
            f" / 보유 폭 {row['보유 폭']:.4f} 피복 {row['보유 피복률']:.2%}"
            f" / 결측 폭 {row['결측 폭']:.4f} 피복 {row['결측 피복률']:.2%}",
            flush=True,
        )

    table = pd.DataFrame(rows)
    print(f"\n{'=' * 100}\n결과 (검증 {args.valid_year}년)\n{'=' * 100}")
    print(table.to_string(index=False))

    best = table.loc[table["전체 폭"].idxmin()]
    print(
        f"\n최소 폭: 리프 {int(best['num_leaves'])} / {best['전체 폭']}%p (현행 {CURRENT_QUANTILE_LEAVES})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
