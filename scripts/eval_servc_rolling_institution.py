#!/usr/bin/env python3
"""
기관 이력을 시간 창 기반으로 다시 만들었을 때의 이득을 잽니다.

현행 `inst_hist_rate` 는 `expanding().mean()` 입니다(`segment_servc_models.py:129`).
`shift(1)` 을 거치므로 누수는 없지만 **10년 전 낙찰률과 지난달 낙찰률의 가중치가
같습니다.** 2026-05-26 낙찰하한율 일괄 인상 같은 제도 전환이 있는 시장에서는
오래된 표본이 최근 신호를 희석합니다.

`features.py:229` 의 `inst_rate_mean_30d` 는 이름만 30일입니다. 값이 없으면
`inst_hist_rate` 로 폴백하므로 실질적으로 기관 전체 평균과 같습니다.

여기서는 30/90/365일 창과 지수감쇠를 실제로 계산해 현행 대비 이득을 봅니다.
누수 방지는 `closed="left"` 로 합니다. 기준 시각 이전만 포함하므로 자기 자신과
동시각 공고가 모두 빠집니다.

사용법:
    .venv/bin/python scripts/eval_servc_rolling_institution.py
    .venv/bin/python scripts/eval_servc_rolling_institution.py --windows 90,365
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
from src.ml.trainer import LGB_BASE_PARAMS  # noqa: E402

POINT_OBJECTIVE = {"objective": "huber", "alpha": 1.0}
GROUP_KEY = "dminstt_nm"


def attach_rolling_history(df: pd.DataFrame, windows: list[int], halflife: int) -> list[str]:
    """기관별 시간 창 평균과 지수감쇠 평균을 붙이고 추가된 컬럼명을 돌려줍니다.

    `closed="left"` 가 누수 차단의 전부입니다. 창이 기준 시각 미만만 담으므로
    자기 자신은 물론 같은 시각에 열린 다른 공고도 들어오지 않습니다.
    """
    df.sort_values("openg_dt", inplace=True)
    added: list[str] = []

    for window in windows:
        mean_col, cnt_col, std_col = (
            f"inst_roll_{window}d_mean",
            f"inst_roll_{window}d_cnt",
            f"inst_roll_{window}d_std",
        )
        rolled = (
            df.groupby(GROUP_KEY, observed=True)
            .rolling(f"{window}D", on="openg_dt", closed="left")["winning_rate"]
            .agg(["mean", "count", "std"])
            .reset_index(level=0, drop=True)
            .sort_index()
        )
        df[mean_col] = rolled["mean"].to_numpy()
        df[cnt_col] = rolled["count"].to_numpy()
        df[std_col] = rolled["std"].to_numpy()
        added.extend([mean_col, cnt_col, std_col])

    # 지수감쇠는 건수 기준이라 `closed="left"` 같은 장치가 없습니다. `shift(1)` 은
    # 자기 자신만 뺄 뿐이어서, 같은 시각에 열린 다른 공고가 정렬 순서상 앞에 있으면
    # 그 결과를 봅니다. 운영에서는 알 수 없는 값이므로 누수입니다.
    #
    # (기관, 개찰시각) 그룹의 **첫 행 값**을 그룹 전체에 뿌려 시각 경계를 만듭니다.
    # 첫 행의 shift 값은 그 시각 이전까지만 반영하므로 동시각 공고가 빠집니다.
    ewm_col = f"inst_ewm_{halflife}"
    shifted = df.groupby(GROUP_KEY, observed=True)["winning_rate"].transform(
        lambda s: s.shift(1).ewm(halflife=halflife, ignore_na=True).mean()
    )
    df[ewm_col] = shifted.groupby([df[GROUP_KEY], df["openg_dt"]], observed=True).transform("first")
    added.append(ewm_col)

    # 표본이 없는 신규 기관은 현행 특징과 같은 값으로 채워 비교를 공정하게 합니다.
    for col in added:
        if col.endswith(("_cnt", "_std")):
            df[col] = df[col].fillna(0.0)
        else:
            df[col] = df[col].fillna(df["inst_hist_rate"])
    return added


def evaluate(train: pd.DataFrame, valid: pd.DataFrame, features: list[str], label: str) -> dict:
    started = time.perf_counter()
    model = lgb.LGBMRegressor(**{**LGB_BASE_PARAMS, **POINT_OBJECTIVE})
    model.fit(train[features], train["winning_rate"])
    pred = model.predict(valid[features])
    actual = valid["winning_rate"].to_numpy(dtype=float)
    error = np.abs(pred - actual)

    # 운영 API 측정은 하한율 보유 건만 봅니다. 전체 평균만 보면 운영이 겪지 않는
    # 결측 구간의 개선까지 섞여 판단이 흐려집니다.
    has_lwlt = (valid["lwlt_rate_missing"] == 0).to_numpy()
    return {
        "구성": label,
        "특징 수": len(features),
        "MAE": round(float(error.mean()), 4),
        "RMSE": round(float(np.sqrt(mean_squared_error(actual, pred))), 4),
        "R2": round(float(r2_score(actual, pred)), 4),
        "0.5%p 적중": round(float((error <= 0.5).mean()), 4),
        "보유구간 MAE": round(float(error[has_lwlt].mean()), 4),
        "보유구간 적중": round(float((error[has_lwlt] <= 0.5).mean()), 4),
        "학습 초": round(time.perf_counter() - started, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--windows", default="30,90,365")
    parser.add_argument("--halflife", type=int, default=20)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df = build_frame(path, args.train_end)
    windows = [int(v) for v in args.windows.split(",")]
    print(f"시간 창 {windows}일 / 지수감쇠 반감기 {args.halflife}건 계산 중")
    started = time.perf_counter()
    added = attach_rolling_history(df, windows, args.halflife)
    print(f"  {len(added)}개 특징, {time.perf_counter() - started:.1f}초\n")

    year = df["openg_dt"].dt.year
    train = df[year <= args.train_end]
    valid = df[year == args.valid_year].copy()
    print(f"학습 {len(train):,}행 / 검증 {len(valid):,}행\n")

    rows = [evaluate(train, valid, list(ALL_FEATURES), "현행 (expanding 평균)")]
    print(
        f"  {rows[0]['구성']}: MAE {rows[0]['MAE']:.4f} / 0.5%p {rows[0]['0.5%p 적중']:.2%}",
        flush=True,
    )

    for window in windows:
        cols = [c for c in added if c.startswith(f"inst_roll_{window}d")]
        row = evaluate(train, valid, [*ALL_FEATURES, *cols], f"+ {window}일 창")
        rows.append(row)
        print(f"  {row['구성']}: MAE {row['MAE']:.4f} / 0.5%p {row['0.5%p 적중']:.2%}", flush=True)

    # 창 단독은 이득이 없는데 조합만 좋다면 지수감쇠가 주역입니다. 갈라서 봅니다.
    ewm_cols = [c for c in added if c.startswith("inst_ewm_")]
    for label, cols in (
        ("+ 지수감쇠만", ewm_cols),
        ("+ 전체 창", [c for c in added if c not in ewm_cols]),
        ("+ 전체 창 + 지수감쇠", added),
    ):
        row = evaluate(train, valid, [*ALL_FEATURES, *cols], label)
        rows.append(row)
        print(f"  {row['구성']}: MAE {row['MAE']:.4f} / 0.5%p {row['0.5%p 적중']:.2%}", flush=True)

    table = pd.DataFrame(rows)
    print(f"\n{'=' * 100}\n결과\n{'=' * 100}")
    print(table.to_string(index=False))

    base = table.iloc[0]
    best = table.loc[table["MAE"].idxmin()]
    gain = float(base["MAE"]) - float(best["MAE"])
    print(f"\n최소 MAE: {best['구성']} / {best['MAE']:.4f}")
    print(f"현행 대비 {-gain:+.4f} ({-gain / float(base['MAE']):+.2%})")
    print(f"0.5%p 적중 {float(base['0.5%p 적중']):.2%} -> {float(best['0.5%p 적중']):.2%}")

    seg_gain = float(base["보유구간 MAE"]) - float(best["보유구간 MAE"])
    print(
        f"\n운영이 보는 구간(하한율 보유): {float(base['보유구간 MAE']):.4f} -> "
        f"{float(best['보유구간 MAE']):.4f} ({-seg_gain / float(base['보유구간 MAE']):+.2%})"
    )
    print(f"  적중 {float(base['보유구간 적중']):.2%} -> {float(best['보유구간 적중']):.2%}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
