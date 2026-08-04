#!/usr/bin/env python3
"""
참가자 수가 용역 낙찰률을 얼마나 설명하는지 잽니다.

설계 문서는 참가자 수를 "제한경쟁 잔차의 지배 요인" 으로 지목했지만 값이 없어
확인하지 못했습니다. `collect_servc_participant_count.py` 로 2025년분을 받았으므로
이제 실측할 수 있습니다.

**참가자 수는 개찰 후에야 알 수 있습니다.** 공고 시점 예측에 그대로 넣으면
미래 정보 누수입니다. 그래서 두 가지를 나눠 잽니다.

| 실험 | 의미 | 운영 적용 |
| --- | --- | --- |
| 오라클 | 실제 참가자 수를 특징으로 투입 | 불가. 개선 폭의 **상한**만 알려 줍니다 |
| 이력 | 기관·분류의 과거 참가자 수 평균 | 가능. 공고 시점에 계산됩니다 |

오라클 개선이 작으면 이력 특징은 볼 것도 없습니다. 크면 이력이 그 중 얼마를
회수하는지가 실제 판단 재료입니다.

사용법:
    .venv/bin/python scripts/eval_servc_participant_effect.py
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
from sklearn.metrics import r2_score  # noqa: E402

from scripts.eval_servc_year_holdout import ALL_FEATURES, build_frame  # noqa: E402
from scripts.segment_servc_models import apply_lower_limit  # noqa: E402
from src.ml.trainer import LGB_BASE_PARAMS  # noqa: E402

EVAL_PARAMS = {**LGB_BASE_PARAMS, "objective": "huber", "alpha": 1.0}

# 이력 특징을 붙이는 키. 좁은 키일수록 신호가 선명하나 결측이 늘어납니다.
HISTORY_KEYS = [
    ("prtcpt_hist_instt", ["dminstt_nm"]),
    ("prtcpt_hist_clsfc", ["mid_clsfc_nm"]),
    ("prtcpt_hist_instt_mthd", ["dminstt_nm", "cntrct_mthd_nm"]),
]


def attach_participant_count(df: pd.DataFrame, counts: pd.DataFrame) -> pd.DataFrame:
    counts = counts.dropna(subset=["prtcpt_cnum"]).copy()
    counts["bid_ntce_no"] = counts["bid_ntce_no"].astype(str)
    lookup = counts.groupby("bid_ntce_no")["prtcpt_cnum"].max()

    out = df.copy()
    out["bid_ntce_no"] = out["bid_ntce_no"].astype(str)
    out["prtcpt_cnum"] = out["bid_ntce_no"].map(lookup)
    return out


def attach_participant_history(df: pd.DataFrame, split_dt: pd.Timestamp) -> pd.DataFrame:
    """학습 구간의 참가자 수 평균만으로 이력을 만듭니다.

    검증 구간 값을 섞으면 이력 자체가 정답을 실어 나릅니다. 평균은 반드시
    분할 이전 구간에서만 계산합니다.
    """
    out = df.copy()
    source = out[(out["openg_dt"] < split_dt) & out["prtcpt_cnum"].notna()]
    global_mean = float(source["prtcpt_cnum"].mean())

    for name, keys in HISTORY_KEYS:
        stats = source.groupby(keys, observed=True)["prtcpt_cnum"].agg(["mean", "count"])
        # 표본이 적은 키는 전체 평균 쪽으로 당깁니다. 1건짜리 키를 그대로 믿으면
        # 이력이 잡음을 특징으로 승격시킵니다.
        shrunk = (stats["mean"] * stats["count"] + global_mean * 10) / (stats["count"] + 10)
        merged = out[keys].merge(
            shrunk.rename(name), how="left", left_on=keys, right_index=True
        )
        out[name] = merged[name].fillna(global_mean).to_numpy()
    return out


def run(train: pd.DataFrame, valid: pd.DataFrame, features: list[str], label: str) -> dict:
    model = lgb.LGBMRegressor(**EVAL_PARAMS)
    model.fit(train[features], train["winning_rate"])
    pred = apply_lower_limit(model.predict(valid[features]), valid)
    actual = valid["winning_rate"].to_numpy(dtype=float)
    abs_err = np.abs(pred - actual)
    return {
        "구분": label,
        "특징 수": len(features),
        "R2": round(float(r2_score(actual, pred)), 4),
        "RMSE": round(float(np.sqrt(np.mean((pred - actual) ** 2))), 4),
        "MAE": round(float(abs_err.mean()), 4),
        "0.5%p": round(float((abs_err <= 0.5).mean()), 4),
        "1%p": round(float((abs_err <= 1.0).mean()), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--counts", default="data/feature_store/servc_participant_count.parquet")
    parser.add_argument("--split", default="2025-09-01", help="학습/검증 경계 개찰일")
    args = parser.parse_args()

    dataset_path = PROJECT_ROOT / args.parquet
    counts_path = PROJECT_ROOT / args.counts
    for path in (dataset_path, counts_path):
        if not path.exists():
            print(f"파일이 없습니다: {path}")
            return 1

    # 참가자 수가 2025년분만 있으므로 학습·검증 모두 2025년 안에서 자릅니다.
    df = build_frame(dataset_path, train_end_year=2024)
    df = attach_participant_count(df, pd.read_parquet(counts_path))
    df = df[df["openg_dt"].dt.year == 2025]

    covered = df["prtcpt_cnum"].notna()
    print(f"2025년 {len(df):,}행 중 참가자 수 보유 {covered.sum():,}행 ({covered.mean():.1%})")
    df = df[covered].copy()
    if df.empty:
        print("조인 결과가 비었습니다. 공고번호 형식을 확인하십시오.")
        return 1

    split_dt = pd.Timestamp(args.split)
    df = attach_participant_history(df, split_dt)
    train = df[df["openg_dt"] < split_dt]
    valid = df[df["openg_dt"] >= split_dt].copy()
    print(f"학습 {len(train):,}행 / 검증 {len(valid):,}행 (경계 {args.split})")
    if train.empty or valid.empty:
        print("구간이 비었습니다.")
        return 1

    print(
        "\n참가자 수 분포\n"
        + df["prtcpt_cnum"].describe(percentiles=[0.25, 0.5, 0.75, 0.95]).round(2).to_string()
    )

    # 참가자 수와 하한율 대비 초과폭의 관계. 경쟁이 셀수록 하한에 붙습니다.
    df["gap"] = df["winning_rate"] - df["lwlt_rate"]
    bands = pd.cut(df["prtcpt_cnum"], [0, 1, 2, 5, 10, 30, 100, np.inf])
    table = df.groupby(bands, observed=True).agg(
        건수=("gap", "size"),
        gap_중앙값=("gap", "median"),
        gap_표준편차=("gap", "std"),
        낙찰률_표준편차=("winning_rate", "std"),
    ).round(3)
    print(f"\n참가자 수 구간별 하한율 초과폭\n{table.to_string()}")

    history_features = [name for name, _ in HISTORY_KEYS]
    results = [
        run(train, valid, ALL_FEATURES, "기준 (참가자 수 없음)"),
        run(train, valid, [*ALL_FEATURES, *history_features], "이력 (운영 가능)"),
        run(train, valid, [*ALL_FEATURES, "prtcpt_cnum"], "오라클 (상한, 운영 불가)"),
    ]
    print(f"\n{'=' * 92}\n결과\n{'=' * 92}")
    print(pd.DataFrame(results).to_string(index=False))

    base, hist, oracle = results
    print(
        f"\n오라클 상한  RMSE {base['RMSE'] - oracle['RMSE']:+.4f} / "
        f"0.5%p {oracle['0.5%p'] - base['0.5%p']:+.2%}"
    )
    print(
        f"이력 회수분  RMSE {base['RMSE'] - hist['RMSE']:+.4f} / "
        f"0.5%p {hist['0.5%p'] - base['0.5%p']:+.2%}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
