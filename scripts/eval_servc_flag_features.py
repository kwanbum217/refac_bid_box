#!/usr/bin/env python3
"""제도 플래그 3종을 넣은 특징 집합을 검증 연도를 바꿔 가며 잽니다.

`measure_servc_split_variance.py` 와 같은 3단계 운영 학습 경로(시간순 분할 ->
조기 종료로 트리 수 결정 -> 전량 재적합)를 씁니다. 다른 것은 비교 축뿐입니다.
저기는 `alpha` 를 바꾸고 여기는 **특징 목록**을 바꿉니다.

    기준    training_features_for_category("Servc")
    후보    거기에 제도 플래그 3종을 더한 집합

2026-08-11 측정에서 **분할 변동으로 판정되어 특징 추가를 되돌렸습니다.** 그래서
플래그는 `features.py` 가 만들어 주지 않고 이 스크립트가 직접 붙입니다. 붙이는
방식은 `features._coerce_category` 와 `collect_category_levels` 의 동작을 그대로
따릅니다. 결측은 `MISSING_CATEGORY` 수준으로 접고, 범주 수준은 정렬해 고정합니다.

판정 기준은 `docs/servc_model_status.md` 5장 그대로입니다. 분할 산포 0.0074
이내면 분할 변동이고, 분할마다 부호가 갈리면 기각입니다.

사용법:
    uv run python scripts/eval_servc_flag_features.py --parquet <플래그 포함 parquet>
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

from scripts.build_servc_flag_dataset import FLAG_COLUMNS  # noqa: E402
from src.ml.features import (  # noqa: E402
    MISSING_CATEGORY,
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
SPLIT_NOISE = 0.0074  # servc_split_variance_20260810.md 실측


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


def _attach_flags(frame: pd.DataFrame, raw: pd.DataFrame) -> pd.DataFrame:
    """플래그를 범주형으로 붙입니다.

    features.py 가 범주를 다루는 방식과 같아야 비교가 성립합니다. 결측과 빈
    문자열은 MISSING_CATEGORY 로 접고, 수준 목록은 정렬해 고정합니다.
    """
    for column in FLAG_COLUMNS:
        if column not in raw.columns:
            raise KeyError(
                f"parquet 에 {column} 이 없습니다. build_servc_flag_dataset.py 를 먼저 돌리십시오."
            )
        values = raw[column].astype("string").fillna(MISSING_CATEGORY)
        values = values.where(values != "", MISSING_CATEGORY)
        frame[column] = values.to_numpy()
    levels = {
        column: sorted(set(frame[column].tolist()) | {MISSING_CATEGORY}) for column in FLAG_COLUMNS
    }
    return apply_categorical_dtypes(frame, levels)


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
    frame = _attach_flags(frame, raw.reset_index(drop=True))
    frame["openg_dt"] = raw["openg_dt"].to_numpy()
    frame["winning_rate"] = raw["winning_rate"].to_numpy(dtype=float)
    return frame.sort_values("openg_dt").reset_index(drop=True)


def fit_operational(train: pd.DataFrame, features: list[str], seed: int) -> lgb.LGBMRegressor:
    """운영 3단계를 재현합니다. 시간순 분할 -> 조기 종료 -> 전량 재적합."""
    params = {
        **LGB_BASE_PARAMS,
        **CATEGORY_HYPERPARAMS[CATEGORY]["lightgbm"],
        "random_state": seed,
    }
    known_categoricals = {*CATEGORICAL_FEATURES, *FLAG_COLUMNS}
    categoricals = [column for column in features if column in known_categoricals]
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


def score(model: lgb.LGBMRegressor, valid: pd.DataFrame, features: list[str]) -> dict[str, float]:
    actual = valid["winning_rate"].to_numpy(dtype=float)
    pred = np.asarray(model.predict(valid[features]), dtype=float)
    error = np.abs(pred - actual)
    return {
        "MAE": float(error.mean()),
        "적중%": float((error <= HIT_TOLERANCE).mean() * 100),
        "편향": float((pred - actual).mean()),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--parquet",
        default="data/feature_store_flag_experiment/dataset_Servc_flags.parquet",
    )
    parser.add_argument("--years", default="2023,2024,2025", help="검증 연도들")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    path = Path(args.parquet)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1
    years = [int(value) for value in args.years.split(",")]

    started = time.perf_counter()
    frame = build_frame(path)
    print(f"특징 프레임 {len(frame):,}행 생성: {time.perf_counter() - started:.1f}초", flush=True)

    baseline_features = training_features_for_category(CATEGORY)
    flags = list(FLAG_COLUMNS)
    candidate_features = [*baseline_features, *flags]

    print(f"기준 특징 {len(baseline_features)}종 / 후보 특징 {len(candidate_features)}종")
    print(f"추가 특징: {flags}")
    for column in flags:
        counts = frame[column].value_counts(dropna=False)
        print(f"  {column} 수준 {len(counts)}종, 상위: {counts.head(5).to_dict()}")
    print(f"검증 연도: {years}\n", flush=True)

    year_series = frame["openg_dt"].dt.year
    rows = []
    for year in years:
        train = frame[year_series < year].reset_index(drop=True)
        valid = frame[year_series == year].reset_index(drop=True)
        if train.empty or valid.empty:
            print(f"{year}년 구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
            continue

        scores = {}
        for label, features in (("기준", baseline_features), ("후보", candidate_features)):
            fit_started = time.perf_counter()
            model = fit_operational(train, features, args.seed)
            scores[label] = score(model, valid, features)
            print(
                f"  {year}년 {label} MAE={scores[label]['MAE']:.4f} "
                f"적중={scores[label]['적중%']:.2f}% 편향={scores[label]['편향']:+.4f} "
                f"(학습 {len(train):,}행, {time.perf_counter() - fit_started:.1f}초)",
                flush=True,
            )

        rows.append(
            {
                "검증연도": year,
                "학습행": len(train),
                "검증행": len(valid),
                "기준 MAE": scores["기준"]["MAE"],
                "후보 MAE": scores["후보"]["MAE"],
                "MAE 차이": scores["후보"]["MAE"] - scores["기준"]["MAE"],
                "기준 적중%": scores["기준"]["적중%"],
                "후보 적중%": scores["후보"]["적중%"],
                "적중 차이": scores["후보"]["적중%"] - scores["기준"]["적중%"],
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

    print("\n== 산포 ==")
    print(f"  MAE 차이 평균     : {diffs.mean():+.4f}")
    print(f"  MAE 차이 표준편차 : {diffs.std(ddof=1):.4f}")
    print(f"  적중 차이 평균    : {hit_diffs.mean():+.4f}%p")

    mae_consistent = bool((diffs < 0).all() or (diffs > 0).all())
    hit_consistent = bool((hit_diffs < 0).all() or (hit_diffs > 0).all())
    print(f"  MAE 부호 일관     : {'예' if mae_consistent else '아니오'}")
    print(f"  적중 부호 일관    : {'예' if hit_consistent else '아니오'}")

    # 판정 기준은 결과를 보기 전에 고정합니다. 네 칸을 모두 적습니다.
    print("\n== 판정 ==")
    if not mae_consistent:
        print("  기각. 분할마다 MAE 부호가 갈립니다.")
    elif abs(diffs.mean()) <= SPLIT_NOISE:
        print(f"  분할 변동. |평균 차이| {abs(diffs.mean()):.4f} <= 분할 산포 {SPLIT_NOISE}.")
        print("  개선이라 쓰지 않습니다.")
    elif diffs.mean() < 0:
        print(
            f"  MAE 개선 {diffs.mean():+.4f} 이 분할 산포 {SPLIT_NOISE} 를 넘고 부호가 일관입니다."
        )
        print(
            "  적중률은 "
            f"{'같은 방향' if hit_diffs.mean() > 0 else '반대 방향'}"
            f"({hit_diffs.mean():+.4f}%p) 입니다. 운영 쌍대 검정 대상입니다."
        )
    else:
        print(f"  기각. MAE 가 {diffs.mean():+.4f} 로 악화이고 부호가 일관입니다.")
        if hit_diffs.mean() > 0:
            print(
                f"  다만 적중률은 {hit_diffs.mean():+.4f}%p 개선입니다. 중앙부와 꼬리의 맞바꿈입니다."
            )
    if not hit_consistent:
        print("  승격 지표(0.5%p 적중률)의 부호가 분할마다 갈립니다. 기준 2 에 걸립니다.")
    print("\n  승격 판단은 이 결과만으로 하지 않습니다. 운영 쌍대 검정이 남아 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
