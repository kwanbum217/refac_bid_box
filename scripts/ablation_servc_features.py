#!/usr/bin/env python3
"""
용역 낙찰률 예측 모델의 특징 절제 실험.

`docs/design/servc_prediction_model_design.md` 의 수치를 재현합니다.
특징군을 하나씩 더하며 홀드아웃 R2 증분을 재고, 낙찰률의 기준 금액이
예정가격인지 기초금액인지 판별합니다.

분할은 시간순입니다. 입찰은 시계열이므로 무작위 분할은 미래 정보로 과거를
맞히게 되어 운영보다 좋은 수치를 냅니다.

사용법:
    python scripts/ablation_servc_features.py
    python scripts/ablation_servc_features.py --category Cnstwk
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

import lightgbm as lgb  # noqa: E402
from sklearn.metrics import (  # noqa: E402
    mean_absolute_percentage_error,
    mean_squared_error,
    r2_score,
)
from sqlalchemy import text  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402

# 차수는 공고가 3자리(000), 낙찰이 2자리(00) 로 내려옵니다. 맞추지 않으면
# 조인율이 3.4% 로 떨어집니다. src/ml/dataset.py 의 _normalized_ord 와 동일합니다.
QUERY = text(
    """
    SELECT r.sucsf_bid_rate AS y, r.sucsf_bid_amt AS amt, r.rl_openg_dt AS openg_dt,
           r.dminstt_nm AS inst,
           a.presmpt_prce AS presmpt, a.base_amount AS base,
           a.cntrct_mthd_nm AS cntrct, a.bid_methd_nm AS bidm, a.ntce_kind_nm AS kind,
           a.bid_ntce_dt AS ntce_dt, a.bid_clse_dt AS clse_dt
    FROM bid_results r
    JOIN bid_announcements a
      ON a.bid_ntce_no = r.bid_ntce_no
     AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
     AND a.category = r.category
    WHERE r.category = :cat
      AND r.sucsf_bid_rate IS NOT NULL
      AND r.rl_openg_dt IS NOT NULL
    """
)

RATE_MIN, RATE_MAX = 50.0, 120.0
HOLDOUT_FRACTION = 0.2

LGB_PARAMS = {
    "n_estimators": 600,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 40,
    "subsample": 0.8,
    "colsample_bytree": 0.8,
    "verbose": -1,
    "n_jobs": -1,
}


class _LGBMKwargs(TypedDict, total=False):
    n_estimators: int
    learning_rate: float
    num_leaves: int
    min_child_samples: int
    subsample: float
    colsample_bytree: float
    random_state: int
    verbose: int
    n_jobs: int
    objective: str
    alpha: float


BASE_FEATURES = [
    "log_price",
    "month_sin",
    "month_cos",
    "wd_sin",
    "wd_cos",
    "duration",
    "inst_hist",
    "inst_cnt",
]
CATEGORICAL = ["cntrct", "bidm", "kind"]
PRICE_SHAPE = ["price_rank", "price_q", "base_ratio"]
PAIR_HISTORY = ["ic_hist", "ic_cnt"]

FEATURE_SETS = {
    "A. 현행 8특징": BASE_FEATURES,
    "B. A + 범주형 3종": BASE_FEATURES + CATEGORICAL,
    "C. B + 금액 순위·분위": BASE_FEATURES + CATEGORICAL + PRICE_SHAPE,
    "D. C + 기관x계약방법 이력": BASE_FEATURES + CATEGORICAL + PRICE_SHAPE + PAIR_HISTORY,
    "E. D - log_price": [f for f in BASE_FEATURES if f != "log_price"]
    + CATEGORICAL
    + PRICE_SHAPE
    + PAIR_HISTORY,
}


def load_frame(category: str) -> pd.DataFrame:
    session = SessionLocal()
    try:
        df = pd.read_sql(QUERY, session.bind, params={"cat": category})
    finally:
        session.close()
    print(f"원표본 {len(df):,}")
    df = df[(df.y > RATE_MIN) & (df.y < RATE_MAX)]
    df = df.sort_values("openg_dt").reset_index(drop=True)
    print(f"정제 후 {len(df):,}  기간 {df.openg_dt.min().date()} ~ {df.openg_dt.max().date()}")
    return df


def report_rate_basis(df: pd.DataFrame) -> None:
    """낙찰률이 어느 금액을 기준으로 산정되는지 판별합니다."""
    print("\n=== 낙찰률 기준 금액 판별 ===")
    for column in ("presmpt", "base"):
        subset = df[(df[column] > 0) & df.amt.notna()]
        implied = subset.amt / subset[column] * 100
        error = (implied - subset.y).abs()
        print(
            f"  기준={column:8} 오차 0.5%p 이내 {(error < 0.5).mean() * 100:5.2f}%  "
            f"중앙오차 {error.median():.3f}%p"
        )


def build_features(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    opened = df.openg_dt
    df["month_sin"] = np.sin(2 * np.pi * opened.dt.month / 12)
    df["month_cos"] = np.cos(2 * np.pi * opened.dt.month / 12)
    df["wd_sin"] = np.sin(2 * np.pi * opened.dt.weekday / 7)
    df["wd_cos"] = np.cos(2 * np.pi * opened.dt.weekday / 7)
    df["duration"] = (df.clse_dt - df.ntce_dt).dt.total_seconds().div(86400).clip(0, 365).fillna(-1)
    df["log_price"] = np.log1p(df.presmpt.clip(lower=0)).fillna(-1)

    # 이력은 자기 자신과 미래를 제외해야 합니다. shift(1) 이 자기 자신을,
    # expanding() 이 미래를 배제합니다. 빠뜨리면 홀드아웃이 비현실적으로 좋아집니다.
    by_institution = df.groupby("inst", sort=False)["y"]
    df["inst_hist"] = by_institution.transform(lambda s: s.shift(1).expanding().mean())
    df["inst_cnt"] = by_institution.transform(lambda s: s.shift(1).expanding().count()).fillna(0)
    df["inst_hist"] = df.inst_hist.fillna(df.y.mean())

    # 금액은 선형이 아니라 순위 관계입니다 (Pearson -0.018, Spearman -0.259).
    df["price_rank"] = df.presmpt.rank(pct=True).fillna(0.5)
    df["price_q"] = pd.qcut(df.presmpt.rank(method="first"), 20, labels=False, duplicates="drop")
    # 기초/예정 비율은 중앙값 1.10 이나 표준편차가 174만입니다. 절단이 필요합니다.
    df["base_ratio"] = (
        (df.base / df.presmpt).replace([np.inf, -np.inf], np.nan).clip(0.5, 2.0).fillna(1.1)
    )

    for column in CATEGORICAL:
        df[column] = df[column].astype("category")

    pair_key = df.inst.astype(str) + "|" + df.cntrct.astype(str)
    by_pair = df.groupby(pair_key, sort=False)["y"]
    df["ic_hist"] = by_pair.transform(lambda s: s.shift(1).expanding().mean()).fillna(df.inst_hist)
    df["ic_cnt"] = by_pair.transform(lambda s: s.shift(1).expanding().count()).fillna(0)
    return df


def evaluate(df: pd.DataFrame, columns: list[str], cut: int):
    features = df[columns]
    model = lgb.LGBMRegressor(**cast(_LGBMKwargs, LGB_PARAMS))
    model.fit(
        features[:cut],
        df.y[:cut],
        categorical_feature=[c for c in columns if str(features[c].dtype) == "category"],
    )
    predicted = model.predict(features[cut:])
    actual = df.y[cut:]
    return (
        model,
        r2_score(actual, predicted),
        mean_squared_error(actual, predicted) ** 0.5,
        mean_absolute_percentage_error(actual, predicted) * 100,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="특징 절제 실험")
    parser.add_argument("--category", default="Servc")
    args = parser.parse_args()

    df = load_frame(args.category)
    report_rate_basis(df)
    df = build_features(df)

    cut = int(len(df) * (1 - HOLDOUT_FRACTION))
    print(f"\n학습 {cut:,} / 홀드아웃 {len(df) - cut:,} (시간순 분할)")
    print(f"{'특징군':30} {'R2':>8} {'RMSE':>8} {'MAPE':>8}")

    results = {}
    for name, columns in FEATURE_SETS.items():
        model, r2, rmse, mape = evaluate(df, columns, cut)
        results[name] = (r2, model, columns)
        print(f"{name:30} {r2:8.4f} {rmse:8.4f} {mape:8.4f}")

    best_name = max(results, key=lambda k: results[k][0])
    _, best_model, best_columns = results[best_name]
    importance = pd.Series(best_model.feature_importances_, index=best_columns)
    print(f"\n최고 특징군: {best_name}\n특징 기여도:")
    for name, value in importance.sort_values(ascending=False).items():
        print(f"  {name:14} {value:>7}")

    print("\n=== 금액 구간별 오차 (최고 모델) ===")
    holdout = df[cut:].copy()
    holdout["err"] = (best_model.predict(df[best_columns][cut:]) - holdout.y).abs()
    holdout["seg"] = pd.qcut(
        holdout.presmpt.rank(method="first"), 5, labels=["최소", "소", "중", "대", "최대"]
    )
    summary = holdout.groupby("seg", observed=True).agg(
        건수=("y", "size"), 실제평균=("y", "mean"), MAE=("err", "mean"), 실제표준편차=("y", "std")
    )
    print(summary.round(3).to_string())
    return 0


if __name__ == "__main__":
    sys.exit(main())
