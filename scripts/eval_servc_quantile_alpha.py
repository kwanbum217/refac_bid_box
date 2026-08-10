#!/usr/bin/env python3
"""용역 점 추정의 `quantile` alpha 를 훑어 적중률과 MAE 의 맞바꿈을 잽니다.

학습은 `quantile(0.5)` 로 조건부 중앙값을 겨냥하는데 승격 판정은 0.5%p 이내
적중률로 합니다. 두 목표가 다르다는 것을 초과분 타깃 실험이 수치로 보여
주었습니다(`servc_excess_target_20260810.md` 5장). 중앙부를 좁히자 적중률이
+0.2687%p 오르고 꼬리가 나빠져 RMSE 가 11% 악화됐습니다.

여기서는 타깃을 건드리지 않고 목적함수만 움직입니다. 현행 편향이
-0.0460 ~ -0.0499 로 계통적 과소예측이므로, alpha 를 0.5 보다 올리면 편향이
줄어들 여지가 있습니다.

`huber` 의 alpha 를 줄이는 방향은 시도하지 않습니다. `alpha=0.2` 가 MAE 1.7971
로 32% 나빴고 원인이 gradient 평탄화라는 실측이 이미 있습니다.

판정 기준 (결과를 보기 전에 고정합니다). 네 칸을 모두 적습니다:

    MAE 개선 x 적중 개선    운영 쌍대로 진행
    MAE 개선 x 적중 악화    기각. 서비스 지표가 우선입니다
    MAE 악화 x 적중 개선    맞바꿈. 적중 이득이 MAE 손실의 실용 가치를 넘는지
                            별도 판단이 필요하며 단독으로 승격하지 않습니다
    MAE 악화 x 적중 악화    기각

어느 경우든 차이가 시드 표준편차 이내면 선택 편향으로 기각합니다.

사용법:
    .venv/bin/python scripts/eval_servc_quantile_alpha.py
    .venv/bin/python scripts/eval_servc_quantile_alpha.py --alphas 0.5,0.52,0.55
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
    training_features_for_category,
)

CATEGORY = "Servc"
HIT_TOLERANCE = 0.5
BASELINE_ALPHA = float(CATEGORY_HYPERPARAMS[CATEGORY]["lightgbm"]["alpha"])


def build_frame(path: Path) -> pd.DataFrame:
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


def fit_operational(
    train: pd.DataFrame, features: list[str], alpha: float, seed: int
) -> lgb.LGBMRegressor:
    """운영 3단계를 재현합니다. alpha 만 바꾸고 나머지는 운영값 그대로입니다."""
    params = {
        **LGB_BASE_PARAMS,
        **CATEGORY_HYPERPARAMS[CATEGORY]["lightgbm"],
        "alpha": alpha,
        "random_state": seed,
    }
    categoricals = [column for column in CATEGORICAL_FEATURES if column in features]
    y = train["winning_rate"].to_numpy(dtype=float)

    cut = int(len(train) * (1 - DEFAULT_VALIDATION_SPLIT))
    probe = lgb.LGBMRegressor(**params)
    probe.fit(
        train[features].iloc[:cut],
        y[:cut],
        eval_set=[(train[features].iloc[cut:], y[cut:])],
        categorical_feature=categoricals,
        callbacks=[lgb.early_stopping(10, verbose=False)],
    )
    best = int(getattr(probe, "best_iteration_", 0) or params["n_estimators"])

    model = lgb.LGBMRegressor(**{**params, "n_estimators": best})
    model.fit(train[features], y, categorical_feature=categoricals)
    return model


def score(actual: np.ndarray, pred: np.ndarray, missing: np.ndarray) -> dict[str, float]:
    error = np.abs(pred - actual)
    return {
        "MAE": float(error.mean()),
        "RMSE": float(np.sqrt(np.mean((pred - actual) ** 2))),
        "0.5%p 적중%": float((error <= HIT_TOLERANCE).mean() * 100),
        "보유 MAE": float(error[~missing].mean()),
        "결측 MAE": float(error[missing].mean()),
        "편향": float((pred - actual).mean()),
    }


def paired_t(base_err: np.ndarray, cand_err: np.ndarray) -> tuple[float, float]:
    diff = cand_err - base_err
    se = float(diff.std(ddof=1) / np.sqrt(len(diff)))
    return float(diff.mean()), (float(diff.mean() / se) if se > 0 else 0.0)


def verdict(mae_gap: float, hit_gap: float, base_std: float) -> str:
    if abs(mae_gap) <= base_std:
        return "차이가 시드 산포 이내. 기각"
    if mae_gap < 0 and hit_gap > 0:
        return "양쪽 개선. 운영 쌍대로 진행"
    if mae_gap < 0 and hit_gap <= 0:
        return "MAE 만 개선. 기각(서비스 지표 우선)"
    if mae_gap > 0 and hit_gap > 0:
        return "맞바꿈. 단독 승격 불가, 별도 판단"
    return "양쪽 악화. 기각"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--alphas", default="0.5,0.52,0.55,0.58")
    parser.add_argument("--seeds", default="42,7,2024")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1
    alphas = [float(value) for value in args.alphas.split(",")]
    seeds = [int(value) for value in args.seeds.split(",")]
    if BASELINE_ALPHA not in alphas:
        alphas.insert(0, BASELINE_ALPHA)

    started = time.perf_counter()
    frame = build_frame(path)
    print(f"특징 프레임 {len(frame):,}행 생성: {time.perf_counter() - started:.1f}초", flush=True)

    year = frame["openg_dt"].dt.year
    train = frame[year <= args.train_end].reset_index(drop=True)
    valid = frame[year == args.valid_year].reset_index(drop=True)
    if train.empty or valid.empty:
        print(f"구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
        return 1

    features = training_features_for_category(CATEGORY)
    actual = valid["winning_rate"].to_numpy(dtype=float)
    missing = valid["raw_lwlt"].isna().to_numpy()
    print(
        f"학습 {len(train):,}행 (~{args.train_end}) / 검증 {len(valid):,}행 "
        f"({args.valid_year}) / 기준 alpha {BASELINE_ALPHA}"
    )
    print(f"훑을 alpha: {alphas} / 시드: {seeds}\n")

    rows = []
    errors: dict[float, dict[int, np.ndarray]] = {alpha: {} for alpha in alphas}
    for alpha in alphas:
        for seed in seeds:
            fit_started = time.perf_counter()
            model = fit_operational(train, features, alpha, seed)
            pred = np.asarray(model.predict(valid[features]), dtype=float)
            errors[alpha][seed] = np.abs(pred - actual)
            row = {"alpha": alpha, "시드": seed, **score(actual, pred, missing)}
            rows.append(row)
            print(
                f"  alpha={alpha:<5} seed={seed:<5} MAE={row['MAE']:.4f} "
                f"적중={row['0.5%p 적중%']:.2f}% 편향={row['편향']:+.4f} "
                f"({time.perf_counter() - fit_started:.1f}초)",
                flush=True,
            )

    table = pd.DataFrame(rows)
    print("\n== alpha별 평균과 시드 산포 ==")
    summary = table.groupby("alpha")[
        ["MAE", "RMSE", "0.5%p 적중%", "보유 MAE", "결측 MAE", "편향"]
    ].agg(["mean", "std"])
    print(summary.round(4).to_string())

    base_std = float(table[table["alpha"] == BASELINE_ALPHA]["MAE"].std())
    base_mae = float(table[table["alpha"] == BASELINE_ALPHA]["MAE"].mean())
    base_hit = float(table[table["alpha"] == BASELINE_ALPHA]["0.5%p 적중%"].mean())

    print(f"\n== 기준(alpha={BASELINE_ALPHA}) 대비 판정 / 시드 표준편차 {base_std:.4f} ==")
    for alpha in alphas:
        if alpha == BASELINE_ALPHA:
            continue
        mae_gap = float(table[table["alpha"] == alpha]["MAE"].mean()) - base_mae
        hit_gap = float(table[table["alpha"] == alpha]["0.5%p 적중%"].mean()) - base_hit
        signs = [paired_t(errors[BASELINE_ALPHA][seed], errors[alpha][seed])[0] for seed in seeds]
        consistent = all(value < 0 for value in signs) or all(value > 0 for value in signs)
        print(
            f"  alpha={alpha:<5} MAE {mae_gap:+.4f} / 적중 {hit_gap:+.4f}%p / "
            f"시드일관 {'예' if consistent else '아니오'} -> "
            f"{verdict(mae_gap, hit_gap, base_std) if consistent else '부호가 갈림. 기각'}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
