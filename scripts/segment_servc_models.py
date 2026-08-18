#!/usr/bin/env python3
"""
용역 낙찰률 예측의 분리 모델 실험과 축별 분해 평가.

`docs/design/g2b_procurement_institution_analysis.md` 8장의 설계를 실측으로
검증합니다. 세 가지를 답합니다.

1. 제도 특징(낙찰하한율, 용역구분, 낙찰방법 등)이 실제로 성능을 올리는가
2. 계약방법 x 낙찰방식 분리 모델이 단일 모델보다 나은가
3. 구간별 성능이 얼마나 다른가 (전체 평균 R2 가 의미 있는 지표인가)

분할은 시간순입니다. 입찰은 시계열이므로 무작위 분할은 미래 정보로 과거를
맞히게 되어 운영보다 좋은 수치를 냅니다.

사용법:
    .venv/bin/python scripts/segment_servc_models.py
    .venv/bin/python scripts/segment_servc_models.py --parquet data/feature_store/dataset_Servc.parquet
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

# 낙찰하한율 2%p 일괄 인상 시행일 (조달청공고 제2026-260호)
REGIME_SHIFT_DATE = pd.Timestamp("2026-05-26")

# 홀드아웃 비율. 시간순 정렬 후 뒤에서 이만큼을 검증에 씁니다.
HOLDOUT_RATIO = 0.2

# 세그먼트가 이보다 작으면 학습·평가가 무의미해 폴백 모델로 넘깁니다.
MIN_SEGMENT_ROWS = 2000

NUMERIC_BASE = [
    "log_price",
    "month_sin",
    "month_cos",
    "notice_duration",
    "inst_hist_rate",
    "inst_sample_cnt",
]

NUMERIC_INSTITUTION = [
    "lwlt_rate",
    "lwlt_rate_missing",
    "is_post_regime_shift",
    "notice_amt_ratio",
    "is_over_notice_amt",
    "tech_ablt_evl_rt",
    "bid_prce_evl_rt",
    "tot_prdprc_num",
    "drwt_prdprc_num",
]

CATEGORICAL_INSTITUTION = [
    "srvce_div_nm",
    "lrg_clsfc_nm",
    "cntrct_mthd_nm",
    "prearng_mthd",
    "sucsfbid_mthd_nm",
]

LGB_PARAMS = {
    "objective": "regression",
    "n_estimators": 400,
    "learning_rate": 0.05,
    "num_leaves": 63,
    "min_child_samples": 50,
    "random_state": 42,
    "verbose": -1,
}


def build_frame(parquet_path: Path) -> pd.DataFrame:
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

    # 하한율 결측을 0 으로 채우면 "하한율 0" 과 구분되지 않습니다.
    # 지시자를 따로 내고 값은 중앙값으로 채웁니다.
    df["lwlt_rate_missing"] = df["lwlt_rate"].isna().astype(float)
    df["lwlt_rate"] = df["lwlt_rate"].fillna(df["lwlt_rate"].median())

    df["is_post_regime_shift"] = (df["bid_ntce_dt"] >= REGIME_SHIFT_DATE).astype(float)
    notice_amount = np.where(df["bid_ntce_dt"].dt.year >= 2025, 230_000_000, 220_000_000)
    df["notice_amt_ratio"] = df["presmpt_prce"] / notice_amount
    df["is_over_notice_amt"] = (df["presmpt_prce"] >= notice_amount).astype(float)

    for column in ("tech_ablt_evl_rt", "bid_prce_evl_rt", "tot_prdprc_num", "drwt_prdprc_num"):
        df[column] = pd.to_numeric(df[column], errors="coerce").fillna(0.0)

    for column in CATEGORICAL_INSTITUTION:
        df[column] = df[column].fillna("미상").astype("category")

    df = _attach_institution_history(df)
    return df.sort_values("openg_dt").reset_index(drop=True)


def _attach_institution_history(df: pd.DataFrame) -> pd.DataFrame:
    """기준 시점 이전 같은 기관의 낙찰률 평균과 표본 수입니다.

    shift(1) 로 자기 자신을 제외해야 타깃 누수가 나지 않습니다.
    """
    df = df.sort_values("openg_dt")
    grouped = df.groupby("dminstt_nm", observed=True)["winning_rate"]
    df["inst_hist_rate"] = grouped.transform(lambda s: s.shift(1).expanding().mean())
    df["inst_sample_cnt"] = grouped.transform(lambda s: s.shift(1).expanding().count())
    df["inst_hist_rate"] = df["inst_hist_rate"].fillna(df["winning_rate"].median())
    df["inst_sample_cnt"] = df["inst_sample_cnt"].fillna(0.0)
    return df


def split_by_time(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    cut = int(len(df) * (1.0 - HOLDOUT_RATIO))
    return df.iloc[:cut], df.iloc[cut:]


def fit_predict(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    columns: list[str],
) -> np.ndarray:
    model = lgb.LGBMRegressor(**LGB_PARAMS)
    model.fit(train[columns], train["winning_rate"])
    return model.predict(valid[columns])


def score(y_true, y_pred) -> dict[str, float]:
    return {
        "r2": round(float(r2_score(y_true, y_pred)), 4),
        "rmse": round(float(np.sqrt(mean_squared_error(y_true, y_pred))), 4),
        "mae": round(float(np.mean(np.abs(np.asarray(y_true) - np.asarray(y_pred)))), 4),
    }


def apply_lower_limit(preds: np.ndarray, valid: pd.DataFrame) -> np.ndarray:
    """낙찰률은 하한율 이상입니다 (실측 99.95%). 하한율 결측 건은 절단하지 않습니다.

    협상에 의한 계약은 제도상 하한율 개념이 없으므로 제외합니다.
    """
    clipped = preds.copy()
    has_limit = (valid["lwlt_rate_missing"] == 0).to_numpy()
    is_negotiation = (valid["tech_ablt_evl_rt"] > 0).to_numpy()
    mask = has_limit & ~is_negotiation
    clipped[mask] = np.maximum(clipped[mask], valid["lwlt_rate"].to_numpy()[mask])
    return clipped


def segment_of(row) -> str:
    if row["tech_ablt_evl_rt"] > 0:
        return "협상에의한계약"
    if str(row["cntrct_mthd_nm"]) == "수의계약":
        return "수의계약"
    if str(row["sucsfbid_mthd_nm"]).startswith("적격심사제"):
        return "적격심사_명시"
    return "경쟁_공고서참조"


def report(title: str, rows: list[dict]) -> None:
    print(f"\n{'=' * 82}\n{title}\n{'=' * 82}")
    print(pd.DataFrame(rows).to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parquet", default="data/feature_store/dataset_Servc.parquet", help="데이터셋 경로"
    )
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        print("먼저 build_training_dataset 으로 생성하십시오.")
        return 1

    df = build_frame(path)
    print(f"표본 {len(df):,}행 (개찰일 {df['openg_dt'].min()} ~ {df['openg_dt'].max()})")

    train, valid = split_by_time(df)
    print(f"학습 {len(train):,} / 홀드아웃 {len(valid):,}")

    y_valid = valid["winning_rate"].to_numpy()

    # 1. 특징군 증분
    feature_sets = {
        "base (기존 6종)": NUMERIC_BASE,
        "+ 제도 수치": NUMERIC_BASE + NUMERIC_INSTITUTION,
        "+ 제도 범주": NUMERIC_BASE + NUMERIC_INSTITUTION + CATEGORICAL_INSTITUTION,
    }
    rows = []
    preds_by_set = {}
    for name, columns in feature_sets.items():
        preds = fit_predict(train, valid, columns)
        preds_by_set[name] = preds
        rows.append({"특징군": name, "특징수": len(columns), **score(y_valid, preds)})
    report("1. 특징군별 홀드아웃 성능 (단일 모델)", rows)

    full_columns = feature_sets["+ 제도 범주"]
    single_preds = preds_by_set["+ 제도 범주"]

    # 2. 하한율 절단 후처리 효과
    clipped = apply_lower_limit(single_preds, valid)
    report(
        "2. 하한율 절단 후처리 효과",
        [
            {"처리": "절단 없음", **score(y_valid, single_preds)},
            {"처리": "하한율 절단", **score(y_valid, clipped)},
        ],
    )

    # 3. 분리 모델
    train_seg = train.assign(segment=train.apply(segment_of, axis=1))
    valid_seg = valid.assign(segment=valid.apply(segment_of, axis=1))

    segmented = np.array(single_preds, dtype=float)
    seg_rows = []
    for segment in sorted(valid_seg["segment"].unique()):
        tr = train_seg[train_seg["segment"] == segment]
        va_mask = (valid_seg["segment"] == segment).to_numpy()
        va = valid_seg[va_mask]
        if len(tr) < MIN_SEGMENT_ROWS or len(va) < 100:
            seg_rows.append(
                {"세그먼트": segment, "학습": len(tr), "검증": len(va), "판정": "표본부족_폴백"}
            )
            continue
        seg_pred = fit_predict(tr, va, full_columns)
        segmented[va_mask] = seg_pred
        single_slice = score(va["winning_rate"], single_preds[va_mask])
        seg_slice = score(va["winning_rate"], seg_pred)
        seg_rows.append(
            {
                "세그먼트": segment,
                "학습": len(tr),
                "검증": len(va),
                "타깃표준편차": round(float(va["winning_rate"].std()), 3),
                "단일R2": single_slice["r2"],
                "분리R2": seg_slice["r2"],
                "단일RMSE": single_slice["rmse"],
                "분리RMSE": seg_slice["rmse"],
            }
        )
    report("3. 세그먼트별 단일 모델 대 분리 모델", seg_rows)

    segmented_clipped = apply_lower_limit(segmented, valid)
    report(
        "4. 최종 비교 (전체 홀드아웃)",
        [
            {"구성": "단일 모델", **score(y_valid, single_preds)},
            {"구성": "단일 + 절단", **score(y_valid, clipped)},
            {"구성": "분리 모델", **score(y_valid, segmented)},
            {"구성": "분리 + 절단", **score(y_valid, segmented_clipped)},
        ],
    )

    # 5. 설계서 8.4 절의 분해 축
    best = segmented_clipped
    axes = {
        "예가결정방법": valid["prearng_mthd"].astype(str),
        "용역구분": valid["srvce_div_nm"].astype(str),
        "제도레짐": np.where(valid["is_post_regime_shift"] > 0, "post_20260526", "pre"),
        "하한율가용성": np.where(valid["lwlt_rate_missing"] > 0, "결측", "보유"),
    }
    for axis_name, values in axes.items():
        rows = []
        series = pd.Series(values, index=valid.index)
        for level in series.value_counts().head(6).index:
            mask = (series == level).to_numpy()
            if mask.sum() < 50:
                continue
            rows.append(
                {
                    axis_name: level,
                    "건수": int(mask.sum()),
                    "타깃표준편차": round(float(valid["winning_rate"][mask].std()), 3),
                    **score(y_valid[mask], best[mask]),
                }
            )
        report(f"5. 분해 평가 — {axis_name}", rows)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
