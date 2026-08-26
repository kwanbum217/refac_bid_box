#!/usr/bin/env python3
"""홀드아웃 분할을 바꿔 가며 같은 후보를 재고 **분할 간 산포**를 봅니다.

2026-08-10 까지 세 건이 같은 패턴으로 기각됐습니다. 홀드아웃에서 시드 3개
일관으로 개선인데 운영 쌍대에서 사라집니다.

    quantile alpha 0.45            홀드아웃 -0.0083  운영 t=-0.44
    quantile 아래 하이퍼파라미터    홀드아웃 -0.0037  운영 +0.0139 t=5.14
    num_leaves 127                 게이트 4개 통과   운영 t=2.13 악화

`servc_paired_asof_gap_20260810.md` 에서 특징 시점 차이 가설을 기각했으므로
남은 가장 단순한 설명은 **홀드아웃 이득 자체가 실체가 없다**는 것입니다.

시드 산포는 이미 재고 있습니다(0.0010). 그러나 시드를 바꿔도 **같은 분할**을
쓰므로, 분할이 만들어 내는 변동은 시드 일관성으로 배제되지 않습니다. 검증
연도를 바꿔 그 산포를 직접 잽니다.

    분할 산포 <= 시드 산포    단일 분할 결과를 믿어도 됩니다
    분할 산포 >  후보 차이    그 크기의 홀드아웃 이득은 읽을 수 없습니다

사용법:
    .venv/bin/python scripts/measure_servc_split_variance.py
    .venv/bin/python scripts/measure_servc_split_variance.py --years 2023,2024,2025
"""

from __future__ import annotations

import argparse
import sys
import time
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
    training_features_for_category,
)

CATEGORY = "Servc"
HIT_TOLERANCE = 0.5
BASELINE_ALPHA = float(cast(float, CATEGORY_HYPERPARAMS[CATEGORY]["lightgbm"]["alpha"]))


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


def build_frame(path: Path) -> pd.DataFrame:
    """이력 특징은 전량에 붙인 뒤 잘라냅니다. 연도로 먼저 자르면 기관별 연초
    건이 최소 표본에 걸려 기본값 폴백이 폭증합니다."""
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
    return frame.sort_values("openg_dt").reset_index(drop=True)


def fit_operational(
    train: pd.DataFrame, features: list[str], alpha: float, seed: int
) -> lgb.LGBMRegressor:
    """운영 3단계를 재현합니다. 시간순 분할 -> 조기 종료 -> 전량 재적합."""
    params = {
        **LGB_BASE_PARAMS,
        **CATEGORY_HYPERPARAMS[CATEGORY]["lightgbm"],
        "alpha": alpha,
        "random_state": seed,
    }
    categoricals = [column for column in CATEGORICAL_FEATURES if column in features]
    y = train["winning_rate"].to_numpy(dtype=float)

    cut = int(len(train) * (1 - DEFAULT_VALIDATION_SPLIT))
    lgb_params = cast(_LGBMKwargs, params)
    probe = lgb.LGBMRegressor(**lgb_params)
    probe.fit(
        train[features].iloc[:cut],
        y[:cut],
        eval_set=[(train[features].iloc[cut:], y[cut:])],
        categorical_feature=categoricals,
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )
    best = int(getattr(probe, "best_iteration_", 0) or cast(int, params["n_estimators"]))

    model = lgb.LGBMRegressor(**cast(_LGBMKwargs, {**params, "n_estimators": best}))
    model.fit(train[features], y, categorical_feature=categoricals)
    return model


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--years", default="2023,2024,2025", help="검증 연도들")
    parser.add_argument("--candidate-alpha", type=float, default=0.45)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1
    years = [int(value) for value in args.years.split(",")]

    started = time.perf_counter()
    frame = build_frame(path)
    print(f"특징 프레임 {len(frame):,}행 생성: {time.perf_counter() - started:.1f}초", flush=True)

    features = training_features_for_category(CATEGORY)
    year_series = frame["openg_dt"].dt.year
    alphas = [BASELINE_ALPHA, args.candidate_alpha]
    print(f"기준 alpha {BASELINE_ALPHA} / 후보 alpha {args.candidate_alpha} / 시드 {args.seed}")
    print(f"검증 연도: {years}\n")

    rows = []
    for year in years:
        train = frame[year_series < year].reset_index(drop=True)
        valid = frame[year_series == year].reset_index(drop=True)
        if train.empty or valid.empty:
            print(f"{year}년 구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
            continue
        actual = valid["winning_rate"].to_numpy(dtype=float)

        scores = {}
        for alpha in alphas:
            fit_started = time.perf_counter()
            model = fit_operational(train, features, alpha, args.seed)
            pred = np.asarray(model.predict(valid[features]), dtype=float)
            error = np.abs(pred - actual)
            scores[alpha] = {
                "MAE": float(error.mean()),
                "적중%": float((error <= HIT_TOLERANCE).mean() * 100),
            }
            print(
                f"  {year}년 alpha={alpha:<5} MAE={scores[alpha]['MAE']:.4f} "
                f"적중={scores[alpha]['적중%']:.2f}% "
                f"(학습 {len(train):,}행, {time.perf_counter() - fit_started:.1f}초)",
                flush=True,
            )

        rows.append(
            {
                "검증연도": year,
                "학습행": len(train),
                "검증행": len(valid),
                "기준 MAE": scores[BASELINE_ALPHA]["MAE"],
                "후보 MAE": scores[args.candidate_alpha]["MAE"],
                "MAE 차이": scores[args.candidate_alpha]["MAE"] - scores[BASELINE_ALPHA]["MAE"],
                "기준 적중%": scores[BASELINE_ALPHA]["적중%"],
                "후보 적중%": scores[args.candidate_alpha]["적중%"],
                "적중 차이": scores[args.candidate_alpha]["적중%"]
                - scores[BASELINE_ALPHA]["적중%"],
            }
        )

    if not rows:
        print("측정된 분할이 없습니다.")
        return 1

    table = pd.DataFrame(rows)
    print("\n== 분할별 결과 ==")
    print(table.round(4).to_string(index=False))

    diffs = table["MAE 차이"].to_numpy(dtype=float)
    hit_diffs = table["적중 차이"].to_numpy(dtype=float)
    base_maes = table["기준 MAE"].to_numpy(dtype=float)

    print("\n== 산포 ==")
    print(f"  기준 MAE 자체의 분할 간 표준편차 : {base_maes.std(ddof=1):.4f}")
    print(f"  후보-기준 MAE 차이의 표준편차    : {diffs.std(ddof=1):.4f}")
    print(f"  후보-기준 MAE 차이의 평균        : {diffs.mean():+.4f}")
    print(f"  적중 차이의 표준편차             : {hit_diffs.std(ddof=1):.4f}")
    print(
        f"  부호 일관                        : {'예' if (diffs < 0).all() or (diffs > 0).all() else '아니오'}"
    )

    print("\n== 판정 ==")
    seed_std = 0.0010  # eval_servc_quantile_alpha.py 실측
    print(f"  참고: 같은 분할에서 시드만 바꿨을 때의 표준편차는 {seed_std:.4f} 입니다.")
    if diffs.std(ddof=1) > abs(diffs.mean()):
        print("  분할 간 산포가 평균 차이보다 큽니다. 단일 분할의 이득은 읽을 수 없습니다.")
    elif diffs.std(ddof=1) > seed_std * 3:
        print(
            "  분할 간 산포가 시드 산포를 크게 넘습니다. 단일 분할 결과를 그대로 믿을 수 없습니다."
        )
    else:
        print("  분할 간 산포가 시드 산포와 비슷합니다. 단일 분할 결과가 안정적입니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
