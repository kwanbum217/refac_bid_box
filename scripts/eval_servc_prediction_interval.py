"""
scripts/eval_servc_prediction_interval.py

용역 낙찰률 예측 구간(분위 회귀) 보정 검증.

설계서 6.3 은 큰 건일수록 산포가 커지는 이분산에 대해 구간 분할이 아니라
예측 구간 제공으로 대응한다고 정했습니다. 본 스크립트는 그 구간이 실제로
맞는지(피복률)와 얼마나 좁은지(구간 폭)를 2025년 홀드아웃으로 측정합니다.

명목 피복률과 실제 피복률이 어긋나면 구간은 쓸모가 없습니다. 90% 라고 적어
놓고 실제로 70% 만 들어맞으면 사용자를 오도합니다.

실행: .venv/bin/python scripts/eval_servc_prediction_interval.py
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import lightgbm as lgb  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.eval_servc_year_holdout import (  # noqa: E402
    ALL_FEATURES,
    EVAL_PARAMS,
    PRICE_BANDS,
    build_frame,
    report,
)
from src.ml.features import (  # noqa: E402
    CATEGORICAL_FEATURES,
    apply_categorical_dtypes,
    collect_category_levels,
)

DATASET = PROJECT_ROOT / "data" / "feature_store" / "dataset_Servc.parquet"
TRAIN_END_YEAR = 2024

# 설계서 6.3 이 지정한 분위입니다. 0.5 는 점 추정 비교용으로 함께 학습합니다.
QUANTILES = (0.1, 0.5, 0.9)

# 등각예측 보정에 쓸 연도. 학습에도 평가에도 쓰지 않은 구간이어야 합니다.
CALIB_YEAR = 2024
FIT_END_YEAR = 2023

# 분위 회귀는 objective 와 alpha 로 분위를 지정합니다. 나머지 용량 설정은
# 점 추정 모델과 같게 둬야 구간과 점 추정이 같은 복잡도에서 비교됩니다.
QUANTILE_PARAMS: dict[str, Any] = {
    key: value for key, value in EVAL_PARAMS.items() if key not in ("objective", "alpha")
}


def train_quantiles(X_train, y_train, X_valid) -> dict[float, np.ndarray]:
    preds: dict[float, np.ndarray] = {}
    for q in QUANTILES:
        model = lgb.LGBMRegressor(objective="quantile", alpha=q, **QUANTILE_PARAMS)
        model.fit(X_train, y_train, categorical_feature=list(CATEGORICAL_FEATURES))
        preds[q] = np.asarray(model.predict(X_valid))
        print(f"  분위 {q} 학습 완료", flush=True)
    return preds


def coverage_table(y: np.ndarray, lo: np.ndarray, hi: np.ndarray) -> pd.DataFrame:
    inside = (y >= lo) & (y <= hi)
    width = hi - lo
    return pd.DataFrame(
        [
            {
                "명목 피복률": 0.80,
                "실제 피복률": float(inside.mean()),
                "구간 폭 중앙값(%p)": float(np.median(width)),
                "구간 폭 평균(%p)": float(width.mean()),
                "하단 이탈": float((y < lo).mean()),
                "상단 이탈": float((y > hi).mean()),
            }
        ]
    )


def coverage_by_price(valid: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for label, low, high in PRICE_BANDS:
        band = valid[(valid["presmpt_prce"] >= low) & (valid["presmpt_prce"] < high)]
        if len(band) < 200:
            continue
        inside = (band["y"] >= band["lo"]) & (band["y"] <= band["hi"])
        rows.append(
            {
                "추정가격": label,
                "공고 건수": len(band),
                "실제 표준편차": float(band["y"].std()),
                "실제 피복률": float(inside.mean()),
                "구간 폭 중앙값(%p)": float((band["hi"] - band["lo"]).median()),
            }
        )
    return pd.DataFrame(rows)


def coverage_by_group(valid: pd.DataFrame, key: str, min_rows: int = 200) -> pd.DataFrame:
    rows = []
    for value, band in valid.groupby(key, observed=True):
        if len(band) < min_rows:
            continue
        inside = (band["y"] >= band["lo"]) & (band["y"] <= band["hi"])
        rows.append(
            {
                key: value,
                "공고 건수": len(band),
                "실제 피복률": float(inside.mean()),
                "구간 폭 중앙값(%p)": float((band["hi"] - band["lo"]).median()),
            }
        )
    return pd.DataFrame(rows).sort_values("공고 건수", ascending=False)


def conformal_scale(y_cal, lo_cal, hi_cal, target: float) -> float:
    """구간을 중앙 기준으로 몇 배 넓혀야 목표 피복률에 닿는지 구합니다.

    분위 회귀 예측은 그 자체로는 보정이 보장되지 않습니다. 실측에서 명목 80%
    구간의 실제 피복률이 75.5% 였습니다. 등각예측은 학습에도 평가에도 쓰지
    않은 구간에서 이탈 점수의 분위를 재어 배율을 정하므로, 분포 가정 없이
    목표 피복률을 맞출 수 있습니다.
    """
    center = (lo_cal + hi_cal) / 2
    half = np.maximum((hi_cal - lo_cal) / 2, 1e-9)
    # 각 건이 구간 안에 들어오려면 필요한 배율입니다.
    score = np.abs(y_cal - center) / half
    return float(np.quantile(score, target))


def main() -> int:
    df = build_frame(DATASET, TRAIN_END_YEAR)
    train = df[df["openg_dt"].dt.year <= TRAIN_END_YEAR]
    valid = df[df["openg_dt"].dt.year == TRAIN_END_YEAR + 1].copy()

    levels = collect_category_levels(train)
    train = apply_categorical_dtypes(train, levels)
    valid = apply_categorical_dtypes(valid, levels)

    X_train, y_train = train[ALL_FEATURES], train["winning_rate"].to_numpy()
    X_valid = valid[ALL_FEATURES]
    y = valid["winning_rate"].to_numpy()

    report("0. 분할", f"학습 {len(train):,}행 / 검증 {len(valid):,}행")
    preds = train_quantiles(X_train, y_train, X_valid)

    # 분위 회귀는 분위별로 독립 학습이라 예측이 뒤집힐 수 있습니다(교차 현상).
    # 하단이 상단보다 큰 행을 그대로 두면 구간 폭이 음수가 됩니다.
    lo = np.minimum(preds[0.1], preds[0.9])
    hi = np.maximum(preds[0.1], preds[0.9])
    crossed = int((preds[0.1] > preds[0.9]).sum())
    valid["y"], valid["lo"], valid["hi"] = y, lo, hi
    valid["하한율"] = np.where(valid["lwlt_rate_missing"] == 1, "결측", "보유")

    report("1. 분위 교차", f"하단 > 상단 인 건수: {crossed:,} ({crossed / len(valid):.4%})")
    report("2. 구간 보정 (명목 80%)", coverage_table(y, lo, hi))

    med = preds[0.5]
    point = pd.DataFrame(
        [
            {
                "추정": "분위 0.5 (중앙값)",
                "MAE": float(np.abs(med - y).mean()),
                "RMSE": float(np.sqrt(((med - y) ** 2).mean())),
                "편향": float((med - y).mean()),
                "0.5%p 이내": float((np.abs(med - y) <= 0.5).mean()),
                "1%p 이내": float((np.abs(med - y) <= 1.0).mean()),
            }
        ]
    )
    report("3. 분위 0.5 점 추정 성능", point)
    report("4. 추정가격 구간별 보정", coverage_by_price(valid))
    report("5. 계약방법별 보정", coverage_by_group(valid, "cntrct_mthd_nm"))
    report("6. 하한율 보유 여부별 보정", coverage_by_group(valid, "하한율"))

    # 등각예측 보정: 2023년까지 학습, 2024년으로 배율 산정, 2025년으로 검증.
    fit = df[df["openg_dt"].dt.year <= FIT_END_YEAR]
    cal = df[df["openg_dt"].dt.year == CALIB_YEAR]
    fit = apply_categorical_dtypes(fit, levels)
    cal = apply_categorical_dtypes(cal, levels)
    report("7. 등각예측 분할", f"학습 {len(fit):,} / 보정 {len(cal):,} / 검증 {len(valid):,}")

    cal_preds = train_quantiles(
        fit[ALL_FEATURES], fit["winning_rate"].to_numpy(), pd.concat([cal, valid])[ALL_FEATURES]
    )
    n_cal = len(cal)
    y_cal = cal["winning_rate"].to_numpy()
    rows = []
    for target in (0.80, 0.90):
        lo_c = np.minimum(cal_preds[0.1][:n_cal], cal_preds[0.9][:n_cal])
        hi_c = np.maximum(cal_preds[0.1][:n_cal], cal_preds[0.9][:n_cal])
        scale = conformal_scale(y_cal, lo_c, hi_c, target)

        lo_v = np.minimum(cal_preds[0.1][n_cal:], cal_preds[0.9][n_cal:])
        hi_v = np.maximum(cal_preds[0.1][n_cal:], cal_preds[0.9][n_cal:])
        center, half = (lo_v + hi_v) / 2, (hi_v - lo_v) / 2
        lo_s, hi_s = center - half * scale, center + half * scale
        inside = (y >= lo_s) & (y <= hi_s)
        rows.append(
            {
                "목표 피복률": target,
                "보정 배율": round(scale, 4),
                "실제 피복률": float(inside.mean()),
                "구간 폭 중앙값(%p)": float(np.median(hi_s - lo_s)),
            }
        )
    report("8. 등각예측 보정 결과", pd.DataFrame(rows))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
