#!/usr/bin/env python3
"""용역 모델의 학습 타깃을 낙찰하한율 대비 초과분으로 바꿔 비교합니다.

현행은 절대 낙찰률(88.1 같은 값)을 예측합니다. 하한율이 있는 공고에서 실제
낙찰가는 하한율 바로 위에 몰리므로, 타깃을 `winning_rate - offset` 으로 바꾸면
문제가 좁아집니다. parquet 실측에서 보유 집단 IQR 이 1.1300 에서 0.5470 으로
줄고, 결측까지 포함한 전체도 2.4250 에서 0.8020 이 됩니다.

`lwlt_rate` 는 이미 입력 특징이지만 트리는 축에 정렬된 분할만 만들 수 있어
뺄셈 관계를 직접 표현하지 못합니다. 타깃에서 미리 빼 주면 그 일에 쓰던 용량이
남습니다. 이것이 기대 이득의 메커니즘입니다.

offset 정의 (결측 39% 처리):

    보유 행    offset = lwlt_rate
    결측 행    offset = 학습 구간 결측 집단 낙찰률 중앙값 (상수)

결측 행에 0 을 쓰면 타깃이 0.16 과 96.59 두 모드로 쪼개져 전체 SD 가 39.11 이
됩니다. 상수를 쓰면 두 집단 중앙값이 0.162 와 -0.082 로 정렬됩니다. 상수는
학습 구간에서만 계산해 미래 정보 누수를 막고, 서빙이 같은 값을 쓰도록
metadata 에 실어야 합니다.

판정 기준 (결과를 보기 전에 고정합니다):

    1. 시드 전부에서 MAE 개선이 일관해야 실체가 있다고 봅니다
    2. 차이가 시드 표준편차 이내면 선택 편향으로 보고 기각합니다
    3. 0.5%p 적중률이 나빠지면 MAE 가 좋아져도 승격 후보로 올리지 않습니다
    4. 홀드아웃을 통과해도 운영 경로 쌍대 검정 전에는 결론을 내지 않습니다

사용법:
    .venv/bin/python scripts/eval_servc_excess_target.py
    .venv/bin/python scripts/eval_servc_excess_target.py --seeds 42,7,2024
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


def make_offset(frame: pd.DataFrame, constant: float) -> np.ndarray:
    """행별 타깃 오프셋. 결측 행은 학습 구간에서 정한 상수를 씁니다."""
    return frame["raw_lwlt"].fillna(constant).to_numpy(dtype=float)


def fit_operational(
    train: pd.DataFrame, y: np.ndarray, features: list[str], seed: int
) -> lgb.LGBMRegressor:
    """운영 3단계를 재현합니다. 시간순 분할 -> 조기 종료 -> 전량 재적합."""
    params = {
        **LGB_BASE_PARAMS,
        **CATEGORY_HYPERPARAMS[CATEGORY]["lightgbm"],
        "random_state": seed,
    }
    categoricals = [column for column in CATEGORICAL_FEATURES if column in features]

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
    """모든 지표는 낙찰률 공간에서 계산합니다. 두 후보를 같은 자로 잽니다."""
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
    """같은 공고에 대한 대응표본 검정. 음수면 후보가 우세합니다."""
    diff = cand_err - base_err
    se = float(diff.std(ddof=1) / np.sqrt(len(diff)))
    return float(diff.mean()), (float(diff.mean() / se) if se > 0 else 0.0)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--seeds", default="42,7,2024")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1
    seeds = [int(value) for value in args.seeds.split(",")]

    started = time.perf_counter()
    frame = build_frame(path)
    print(f"특징 프레임 {len(frame):,}행 생성: {time.perf_counter() - started:.1f}초", flush=True)

    year = frame["openg_dt"].dt.year
    train = frame[year <= args.train_end].reset_index(drop=True)
    valid = frame[year == args.valid_year].reset_index(drop=True)
    if train.empty or valid.empty:
        print(f"구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
        return 1

    # 상수는 학습 구간에서만 정합니다. 검증 구간을 보면 누수입니다.
    constant = float(train.loc[train["raw_lwlt"].isna(), "winning_rate"].median())
    print(
        f"학습 {len(train):,}행 (~{args.train_end}) / 검증 {len(valid):,}행 "
        f"({args.valid_year}) / 결측 오프셋 상수 {constant:.4f}"
    )

    features = training_features_for_category(CATEGORY)
    actual = valid["winning_rate"].to_numpy(dtype=float)
    missing = valid["raw_lwlt"].isna().to_numpy()
    train_offset = make_offset(train, constant)
    valid_offset = make_offset(valid, constant)
    print(f"운영 특징 {len(features)}개 / 검증 결측 비중 {missing.mean() * 100:.2f}%\n")

    rows = []
    errors: dict[str, dict[int, np.ndarray]] = {"현행": {}, "초과분": {}}
    for seed in seeds:
        for label in ("현행", "초과분"):
            fit_started = time.perf_counter()
            if label == "현행":
                y_train = train["winning_rate"].to_numpy(dtype=float)
                model = fit_operational(train, y_train, features, seed)
                pred = np.asarray(model.predict(valid[features]), dtype=float)
            else:
                y_train = train["winning_rate"].to_numpy(dtype=float) - train_offset
                model = fit_operational(train, y_train, features, seed)
                # 예측을 낙찰률 공간으로 되돌립니다. 서빙도 같은 식을 씁니다.
                pred = np.asarray(model.predict(valid[features]), dtype=float) + valid_offset

            errors[label][seed] = np.abs(pred - actual)
            row = {"타깃": label, "시드": seed, **score(actual, pred, missing)}
            row["학습초"] = round(time.perf_counter() - fit_started, 1)
            rows.append(row)
            print(
                f"  {label:5} seed={seed:<5} MAE={row['MAE']:.4f} "
                f"적중={row['0.5%p 적중%']:.2f}% ({row['학습초']}초)",
                flush=True,
            )

    table = pd.DataFrame(rows)
    print("\n== 시드별 결과 ==")
    print(table.round(4).to_string(index=False))

    print("\n== 타깃별 평균과 시드 산포 ==")
    summary = table.groupby("타깃")[["MAE", "RMSE", "0.5%p 적중%", "보유 MAE", "결측 MAE"]].agg(
        ["mean", "std"]
    )
    print(summary.round(4).to_string())

    print("\n== 시드별 쌍대 검정 (음수 = 초과분 우세) ==")
    diffs = []
    for seed in seeds:
        mean_diff, t_value = paired_t(errors["현행"][seed], errors["초과분"][seed])
        diffs.append(mean_diff)
        print(f"  seed={seed:<5} 평균차={mean_diff:+.4f} t={t_value:+.2f}")

    candidate_wins_all = all(diff < 0 for diff in diffs)
    baseline_wins_all = all(diff > 0 for diff in diffs)

    base_std = float(table[table["타깃"] == "현행"]["MAE"].std())
    gap = float(
        table[table["타깃"] == "초과분"]["MAE"].mean()
        - table[table["타깃"] == "현행"]["MAE"].mean()
    )
    hit_gap = float(
        table[table["타깃"] == "초과분"]["0.5%p 적중%"].mean()
        - table[table["타깃"] == "현행"]["0.5%p 적중%"].mean()
    )
    print(f"\n평균 MAE 차이 {gap:+.4f} / 현행 시드 표준편차 {base_std:.4f}")
    print(f"0.5%p 적중률 차이 {hit_gap:+.4f}%p")

    if baseline_wins_all:
        print("판정: 전 시드에서 현행이 우세합니다. 기각.")
    elif not candidate_wins_all:
        print("판정: 시드마다 부호가 갈립니다. 기각.")
    elif abs(gap) <= base_std:
        print("판정: 차이가 시드 산포 이내입니다. 기각.")
    elif hit_gap < 0:
        print("판정: MAE 는 좋아졌으나 0.5%p 적중률이 나빠집니다. 기각(기준 3).")
    else:
        print("판정: 홀드아웃 통과. 운영 경로 쌍대 검정으로 진행하십시오.")

    if gap > 0 and hit_gap > 0:
        print(
            "\n주의: MAE 와 적중률이 반대 방향입니다. 중앙부는 좁아지고 꼬리가 "
            "나빠지는 맞바꿈이며, 이 관찰은 목적함수 축의 출발점입니다."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
