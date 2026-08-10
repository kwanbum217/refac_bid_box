#!/usr/bin/env python3
"""2026-05-26 낙찰하한율 인상이 만든 신규 하한율 수준의 예측 영향을 측정합니다.

기존 조사(lwlt_missing_investigation_20260806.md)는 개찰일 플래그로 신·구 제도를
갈랐고 편향 차이를 찾지 못했습니다. 이 스크립트는 다른 축으로 봅니다. 인상 이후
`lwlt_rate` 값 자체가 2%p 올라간 수준들이 나타나는데, 그중 다수는 학습 구간에
표본이 거의 없습니다. LightGBM 은 학습에서 본 분할점 사이로만 예측하므로 이런
수준에서 계통 오차가 날 수 있습니다.

학습 상한 이전만 학습하고 이후를 예측하며, 검증 행을 학습 표본 밀도로 갈라
비교합니다. 같은 절차를 1년 전 동기간에 적용한 대조군을 함께 냅니다.

사용법:
    .venv/bin/python scripts/eval_servc_regime_lwlt_levels.py
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

from src.ml.features import (  # noqa: E402
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.institution_history import attach_institution_history  # noqa: E402
from src.ml.repeat_history import attach_repeat_history  # noqa: E402
from src.ml.trainer import (  # noqa: E402
    CATEGORICAL_FEATURES,
    CATEGORY_HYPERPARAMS,
    DEFAULT_VALIDATION_SPLIT,
    LGB_BASE_PARAMS,
    TRAINING_FEATURES,
)

REGIME_DATE = "2026-05-26"
REGIME_STEP = 2.0
T_THRESHOLD = 2.0


def build_frame(path: Path) -> pd.DataFrame:
    """운영 trainer 와 같은 단일 특징 공급원으로 평가 프레임을 만듭니다."""
    raw = pd.read_parquet(path)
    raw = raw[raw["winning_rate"].notna()].copy()
    raw["openg_dt"] = pd.to_datetime(raw["openg_dt"], errors="coerce")
    raw = attach_institution_history(raw)
    raw = attach_repeat_history(raw)

    frame = pd.DataFrame(build_feature_frame(raw.to_dict(orient="records")))
    levels = collect_category_levels(frame)
    frame = apply_categorical_dtypes(frame, levels)
    frame["openg_dt"] = raw["openg_dt"].to_numpy()
    frame["winning_rate"] = raw["winning_rate"].to_numpy(dtype=float)
    frame["raw_lwlt"] = raw["lwlt_rate"].to_numpy(dtype=float)
    return frame.sort_values("openg_dt").reset_index(drop=True)


def fit_operational(train: pd.DataFrame, features: list[str]) -> lgb.LGBMRegressor:
    """운영 3단계를 재현합니다. 시간순 분할 -> 조기 종료 -> 전량 재적합."""
    params = {**LGB_BASE_PARAMS, **CATEGORY_HYPERPARAMS["Servc"]["lightgbm"]}
    categoricals = [column for column in CATEGORICAL_FEATURES if column in features]

    cut = int(len(train) * (1 - DEFAULT_VALIDATION_SPLIT))
    fit_part, valid_part = train.iloc[:cut], train.iloc[cut:]
    probe = lgb.LGBMRegressor(**params)
    probe.fit(
        fit_part[features],
        fit_part["winning_rate"],
        eval_set=[(valid_part[features], valid_part["winning_rate"])],
        categorical_feature=categoricals,
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )
    best = int(getattr(probe, "best_iteration_", 0) or params["n_estimators"])

    model = lgb.LGBMRegressor(**{**params, "n_estimators": best})
    model.fit(train[features], train["winning_rate"], categorical_feature=categoricals)
    return model


def classify(valid: pd.DataFrame, train: pd.DataFrame, thin: int) -> pd.Series:
    """검증 행을 학습 구간의 하한율 표본 밀도로 분류합니다."""
    density = train["raw_lwlt"].round(3).value_counts()
    level = valid["raw_lwlt"].round(3)

    seen = level.map(density).fillna(0)
    shifted_from = (level - REGIME_STEP).round(3).map(density).fillna(0)

    labels = pd.Series("하한율 결측", index=valid.index, dtype=object)
    has_value = level.notna()
    labels[has_value & (seen >= thin)] = "학습 충분 수준"
    labels[has_value & (seen < thin) & (shifted_from >= thin)] = "2%p 인상 희소 수준"
    labels[has_value & (seen < thin) & (shifted_from < thin)] = "기타 희소 수준"
    return labels


def summarize(valid: pd.DataFrame, pred: np.ndarray, labels: pd.Series) -> pd.DataFrame:
    actual = valid["winning_rate"].to_numpy(dtype=float)
    error = pred - actual
    rows = []
    for name in ["학습 충분 수준", "2%p 인상 희소 수준", "기타 희소 수준", "하한율 결측"]:
        mask = (labels == name).to_numpy()
        if not mask.any():
            continue
        bias = error[mask]
        se = float(bias.std(ddof=1) / np.sqrt(mask.sum())) if mask.sum() > 1 else float("inf")
        rows.append(
            {
                "집단": name,
                "건수": int(mask.sum()),
                "비중%": round(mask.mean() * 100, 2),
                "MAE": round(float(np.abs(bias).mean()), 4),
                "편향": round(float(bias.mean()), 4),
                "편향 t": round(float(bias.mean() / se) if se > 0 else 0.0, 2),
                "0.5%p 적중%": round(float((np.abs(bias) <= 0.5).mean()) * 100, 2),
            }
        )
    total_se = float(error.std(ddof=1) / np.sqrt(len(error)))
    rows.append(
        {
            "집단": "전체",
            "건수": len(error),
            "비중%": 100.0,
            "MAE": round(float(np.abs(error).mean()), 4),
            "편향": round(float(error.mean()), 4),
            "편향 t": round(float(error.mean() / total_se) if total_se > 0 else 0.0, 2),
            "0.5%p 적중%": round(float((np.abs(error) <= 0.5).mean()) * 100, 2),
        }
    )
    return pd.DataFrame(rows)


def run_split(frame: pd.DataFrame, cut: pd.Timestamp, end: pd.Timestamp, thin: int, title: str):
    train = frame[frame["openg_dt"] < cut].copy()
    valid = frame[(frame["openg_dt"] >= cut) & (frame["openg_dt"] <= end)].copy()
    if train.empty or valid.empty:
        print(f"[{title}] 구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
        return None

    features = list(TRAINING_FEATURES)
    started = time.perf_counter()
    model = fit_operational(train, features)
    pred = np.asarray(model.predict(valid[features]), dtype=float)
    labels = classify(valid, train, thin)

    print(f"\n=== {title} ===")
    print(
        f"학습 {len(train):,}행 (~{cut.date()}) / 검증 {len(valid):,}행 "
        f"({cut.date()}~{end.date()}) / 학습 {time.perf_counter() - started:.1f}초"
    )
    table = summarize(valid, pred, labels)
    print(table.to_string(index=False))
    return valid, pred, labels, table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--thin", type=int, default=300, help="희소 수준 판정 임계 표본 수")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    started = time.perf_counter()
    frame = build_frame(path)
    print(f"특징 프레임 {len(frame):,}행 생성: {time.perf_counter() - started:.1f}초", flush=True)

    cut = pd.Timestamp(REGIME_DATE)
    end = frame["openg_dt"].max()
    span = end - cut

    run_split(frame, cut, end, args.thin, f"신제도 구간 (컷 {cut.date()})")
    control_cut = cut - pd.DateOffset(years=1)
    run_split(
        frame,
        control_cut,
        control_cut + span,
        args.thin,
        f"대조군 1년 전 동기간 (컷 {control_cut.date()})",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
