#!/usr/bin/env python3
"""
용역 낙찰률 예측을 연도 경계로 평가합니다.

`segment_servc_models.py` 는 8:2 비율 분할이라 학습·검증 경계가 데이터 양에
따라 움직입니다. 운영에서는 "작년까지 배워서 올해를 맞힌다" 가 실제 상황이므로
연도 경계로 자르고, 공고 한 건당 오차가 얼마나 벌어지는지를 봅니다.

기본값은 학습 2024년까지, 검증 2025년입니다.

사용법:
    .venv/bin/python scripts/eval_servc_year_holdout.py
    .venv/bin/python scripts/eval_servc_year_holdout.py --train-end 2023 --valid-year 2024
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
from sklearn.metrics import mean_squared_error, r2_score  # noqa: E402

from scripts.segment_servc_models import (  # noqa: E402
    LGB_PARAMS,
    NUMERIC_BASE,
    NUMERIC_INSTITUTION,
    REGIME_SHIFT_DATE,
    _attach_institution_history,
    apply_lower_limit,
)
from src.ml.features import CATEGORICAL_FEATURES  # noqa: E402

# 범주형 목록은 features.py 가 단일 공급원입니다. 여기에 따로 적으면 학습 경로와
# 어긋나 평가가 운영과 다른 특징을 재게 됩니다 (AGENTS.md 6항).
CATEGORICAL = list(CATEGORICAL_FEATURES)
ALL_FEATURES = [*NUMERIC_BASE, *NUMERIC_INSTITUTION, *CATEGORICAL]

# 오차 구간. 낙찰률 %p 단위이며 발주 담당자가 체감하는 단위와 같습니다.
ERROR_BANDS = [0.5, 1.0, 2.0, 3.0, 5.0, 10.0]

PRICE_BANDS = [
    ("1천만 미만", 0, 10_000_000),
    ("1천만~5천만", 10_000_000, 50_000_000),
    ("5천만~1억", 50_000_000, 100_000_000),
    ("1억~2.3억", 100_000_000, 230_000_000),
    ("2.3억~10억", 230_000_000, 1_000_000_000),
    ("10억 이상", 1_000_000_000, np.inf),
]


def build_frame(parquet_path: Path, train_end_year: int) -> pd.DataFrame:
    """특징을 만듭니다.

    `segment_servc_models.build_frame` 과 달리 결측 대체값을 학습 구간에서만
    계산합니다. 전체 중앙값으로 채우면 검증 구간 정보가 학습에 새어 듭니다.
    """
    df = pd.read_parquet(parquet_path)
    df = df[df["winning_rate"].notna()].copy()

    for column in ("openg_dt", "bid_ntce_dt", "bid_clse_dt"):
        df[column] = pd.to_datetime(df[column], errors="coerce")

    df["log_price"] = np.log1p(df["presmpt_prce"].clip(lower=0))
    month = df["openg_dt"].dt.month.fillna(1)
    df["month_sin"] = np.sin(2 * np.pi * month / 12)
    df["month_cos"] = np.cos(2 * np.pi * month / 12)
    df["notice_duration"] = (
        ((df["bid_clse_dt"] - df["bid_ntce_dt"]).dt.total_seconds() / 86400)
        .clip(lower=0)
        .fillna(14.0)
    )

    in_train = df["openg_dt"].dt.year <= train_end_year
    lwlt_median = df.loc[in_train, "lwlt_rate"].median()
    rate_median = df.loc[in_train, "winning_rate"].median()

    df["lwlt_rate_missing"] = df["lwlt_rate"].isna().astype(float)
    df["lwlt_rate"] = df["lwlt_rate"].fillna(lwlt_median)

    df["is_post_regime_shift"] = (df["bid_ntce_dt"] >= REGIME_SHIFT_DATE).astype(float)
    notice_amount = np.where(df["bid_ntce_dt"].dt.year >= 2025, 230_000_000, 220_000_000)
    df["notice_amt_ratio"] = df["presmpt_prce"] / notice_amount
    df["is_over_notice_amt"] = (df["presmpt_prce"] >= notice_amount).astype(float)

    for column in ("tech_ablt_evl_rt", "bid_prce_evl_rt", "tot_prdprc_num", "drwt_prdprc_num"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)

    for column in CATEGORICAL:
        df[column] = df[column].fillna("미상").astype(str).astype("category")

    df = _attach_institution_history(df)
    df["inst_hist_rate"] = df["inst_hist_rate"].fillna(rate_median)
    return df.sort_values("openg_dt").reset_index(drop=True)


def score(y_true, y_pred) -> dict[str, float]:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    return {
        "r2": round(float(r2_score(y_true, y_pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "mae": round(float(np.mean(np.abs(y_true - y_pred))), 4),
    }


def error_band_table(abs_err: np.ndarray) -> pd.DataFrame:
    rows = []
    total = len(abs_err)
    for band in ERROR_BANDS:
        n = int((abs_err <= band).sum())
        rows.append({"오차": f"{band}%p 이내", "공고 건수": n, "비율": round(n / total, 4)})
    n_over = int((abs_err > ERROR_BANDS[-1]).sum())
    rows.append(
        {"오차": f"{ERROR_BANDS[-1]}%p 초과", "공고 건수": n_over, "비율": round(n_over / total, 4)}
    )
    return pd.DataFrame(rows)


def group_table(valid: pd.DataFrame, key: str, min_rows: int = 200) -> pd.DataFrame:
    rows = []
    for name, part in valid.groupby(key, observed=True):
        if len(part) < min_rows:
            continue
        stats = score(part["winning_rate"], part["pred"])
        rows.append(
            {
                key: str(name),
                "공고 건수": len(part),
                "실제 표준편차": round(float(part["winning_rate"].std()), 3),
                "MAE": stats["mae"],
                "RMSE": stats["rmse"],
                "R2": stats["r2"],
                "1%p 이내": round(float((part["abs_err"] <= 1.0).mean()), 4),
                "3%p 이내": round(float((part["abs_err"] <= 3.0).mean()), 4),
            }
        )
    return pd.DataFrame(rows).sort_values("공고 건수", ascending=False)


def price_band_table(valid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, low, high in PRICE_BANDS:
        part = valid[(valid["presmpt_prce"] >= low) & (valid["presmpt_prce"] < high)]
        if part.empty:
            continue
        stats = score(part["winning_rate"], part["pred"])
        rows.append(
            {
                "추정가격": label,
                "공고 건수": len(part),
                "MAE": stats["mae"],
                "RMSE": stats["rmse"],
                "1%p 이내": round(float((part["abs_err"] <= 1.0).mean()), 4),
                "3%p 이내": round(float((part["abs_err"] <= 3.0).mean()), 4),
                "금액 오차 중앙값(원)": int(part["amt_err"].median()),
            }
        )
    return pd.DataFrame(rows)


def report(title: str, frame: pd.DataFrame | str, index: bool = False) -> None:
    """분위수 표는 행 이름이 곧 분위수라 index=True 로 출력해야 읽힙니다."""
    print(f"\n{'=' * 92}\n{title}\n{'=' * 92}")
    if isinstance(frame, str):
        print(frame)
    else:
        print(frame.to_string(index=index))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024, help="학습 마지막 연도 (포함)")
    parser.add_argument("--valid-year", type=int, default=2025, help="검증 연도")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df = build_frame(path, args.train_end)
    year = df["openg_dt"].dt.year
    train = df[year <= args.train_end]
    valid = df[year == args.valid_year].copy()

    if train.empty or valid.empty:
        print(f"구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
        return 1

    report(
        "0. 분할",
        f"학습  ~{args.train_end}년: {len(train):,}행 "
        f"({train['openg_dt'].min():%Y-%m-%d} ~ {train['openg_dt'].max():%Y-%m-%d})\n"
        f"검증  {args.valid_year}년   : {len(valid):,}행 "
        f"({valid['openg_dt'].min():%Y-%m-%d} ~ {valid['openg_dt'].max():%Y-%m-%d})\n"
        f"검증 구간 실제 낙찰률: 평균 {valid['winning_rate'].mean():.3f} "
        f"표준편차 {valid['winning_rate'].std():.3f}",
    )

    model = lgb.LGBMRegressor(**LGB_PARAMS)
    model.fit(train[ALL_FEATURES], train["winning_rate"])
    preds = apply_lower_limit(model.predict(valid[ALL_FEATURES]), valid)

    valid["pred"] = preds
    valid["err"] = valid["pred"] - valid["winning_rate"]
    valid["abs_err"] = valid["err"].abs()
    # 낙찰금액 환산 오차입니다. 낙찰률이 %p 단위이므로 낙찰금액에 대한 상대오차와
    # 같은 비율이 됩니다. 담당자가 보는 단위로 바꾸기 위한 참고값입니다.
    valid["amt_err"] = (valid["abs_err"] / 100.0 * valid["sucsf_bid_amt"]).round()

    overall = score(valid["winning_rate"], valid["pred"])
    report(
        f"1. {args.valid_year}년 전체 성능 (공고 {len(valid):,}건)",
        pd.DataFrame([overall]),
    )

    report(
        "2. 공고 한 건당 오차 분포 (예측 - 실제, %p)",
        valid["err"]
        .describe(percentiles=[0.01, 0.05, 0.25, 0.5, 0.75, 0.95, 0.99])
        .round(3)
        .to_frame("낙찰률 오차(%p)"),
        index=True,
    )

    report("3. 오차 구간별 공고 건수", error_band_table(valid["abs_err"].to_numpy()))

    report(
        "4. 낙찰금액 환산 절대오차",
        valid["amt_err"]
        .describe(percentiles=[0.25, 0.5, 0.75, 0.95])
        .round(0)
        .to_frame("금액 오차(원)"),
        index=True,
    )

    valid["month"] = valid["openg_dt"].dt.month
    report(f"5. {args.valid_year}년 월별", group_table(valid, "month", min_rows=0))
    report("6. 추정가격 구간별", price_band_table(valid))
    report("7. 계약방법별", group_table(valid, "cntrct_mthd_nm"))
    report("8. 예가결정방법별", group_table(valid, "prearng_mthd"))
    report("9. 용역구분별", group_table(valid, "srvce_div_nm"))

    valid["하한율"] = np.where(valid["lwlt_rate_missing"] == 1, "결측", "보유")
    report("10. 낙찰하한율 보유 여부별", group_table(valid, "하한율"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
