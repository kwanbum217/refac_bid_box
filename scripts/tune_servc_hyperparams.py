#!/usr/bin/env python3
"""
용역 낙찰률 모델의 하이퍼파라미터를 연도 홀드아웃으로 탐색합니다.

운영 학습기(`src/ml/trainer.py`)의 `LGB_BASE_PARAMS` 는 실험 스크립트 값에 맞춘
것일 뿐 탐색을 거친 값이 아닙니다. 남은 여지가 있는지 실측으로 확인합니다.

무작위 탐색 대신 **좌표 하강**을 씁니다. 학습 1회가 수십 초라 무작위로 뿌리면
같은 시간에 훨씬 적은 축만 보게 됩니다. 축 하나씩 최적값을 잡고 다음 축으로
넘어가면 같은 예산에서 모든 축을 최소 한 번씩 훑을 수 있습니다.

선택 기준은 **MAE** 입니다. R2 로 고르면 잔차 비대칭 때문에 중심을 위로 밀어
올린 모델이 뽑힙니다 (인수인계 3.1 참조). 0.5%p 적중률을 함께 출력해 기준이
서로 어긋나지 않는지 봅니다.

사용법:
    .venv/bin/python scripts/tune_servc_hyperparams.py
    .venv/bin/python scripts/tune_servc_hyperparams.py --rounds 2 --out data/tuning.json
"""

from __future__ import annotations

import argparse
import json
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
from sklearn.metrics import r2_score  # noqa: E402

from scripts.eval_servc_year_holdout import ALL_FEATURES, build_frame  # noqa: E402
from scripts.segment_servc_models import apply_lower_limit  # noqa: E402
from src.ml.trainer import LGB_BASE_PARAMS  # noqa: E402

# 운영 학습기와 같은 목적함수입니다. 여기서 갈리면 탐색 결과가 운영에 옮겨지지
# 않습니다.
FIXED_PARAMS = {"objective": "huber", "alpha": 1.0}

# 탐색 축과 후보. 기준값을 반드시 포함시켜 "기준이 이미 최적" 인 경우를 탐색이
# 스스로 확인하게 합니다.
SEARCH_SPACE: dict[str, list] = {
    "num_leaves": [31, 63, 127, 255, 511],
    "min_child_samples": [20, 40, 80, 160],
    "learning_rate": [0.03, 0.05, 0.08],
    "n_estimators": [600, 1200, 2000],
    "colsample_bytree": [0.6, 0.8, 1.0],
    # subsample 은 subsample_freq 가 0 이면 LightGBM 이 통째로 무시합니다.
    # 1차 탐색에서 0.6/0.8/1.0 의 MAE 가 소수점 넷째 자리까지 같게 나온 것이
    # 그 증거입니다. 빈도를 함께 흔들어야 이 축이 실제로 탐색됩니다.
    "subsample": [0.6, 0.8, 1.0],
    "subsample_freq": [0, 1, 5],
    "reg_lambda": [0.0, 1.0, 10.0],
}


def evaluate(train: pd.DataFrame, valid: pd.DataFrame, params: dict) -> dict[str, float]:
    started = time.perf_counter()
    model = lgb.LGBMRegressor(**{**LGB_BASE_PARAMS, **FIXED_PARAMS, **params})
    model.fit(train[ALL_FEATURES], train["winning_rate"])
    pred = apply_lower_limit(model.predict(valid[ALL_FEATURES]), valid)

    actual = valid["winning_rate"].to_numpy(dtype=float)
    abs_err = np.abs(pred - actual)
    return {
        "mae": round(float(abs_err.mean()), 4),
        "rmse": round(float(np.sqrt(np.mean((pred - actual) ** 2))), 4),
        "r2": round(float(r2_score(actual, pred)), 4),
        "hit_0_5": round(float((abs_err <= 0.5).mean()), 4),
        "hit_1_0": round(float((abs_err <= 1.0).mean()), 4),
        "bias": round(float((pred - actual).mean()), 4),
        "seconds": round(time.perf_counter() - started, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--rounds", type=int, default=1, help="좌표 하강 반복 횟수")
    parser.add_argument(
        "--base",
        default=None,
        help='시작점 JSON. 이전 탐색 결과에서 이어 갈 때 씁니다 (예: \'{"num_leaves": 255}\')',
    )
    parser.add_argument(
        "--axes",
        default=None,
        help="탐색할 축을 쉼표로 제한합니다. 이미 확인한 축을 건너뛸 때 씁니다",
    )
    parser.add_argument("--out", default="data/servc_hyperparam_search.json")
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

    print(f"학습 {len(train):,}행 / 검증 {len(valid):,}행 / 특징 {len(ALL_FEATURES)}개")

    best = {key: LGB_BASE_PARAMS[key] for key in SEARCH_SPACE if key in LGB_BASE_PARAMS}
    best.setdefault("reg_lambda", 0.0)
    best.setdefault("subsample_freq", 0)
    if args.base:
        best.update(json.loads(args.base))

    axes = SEARCH_SPACE
    if args.axes:
        axes = {name: SEARCH_SPACE[name] for name in args.axes.split(",")}

    baseline = evaluate(train, valid, best)
    print(f"\n기준선 {best}\n  -> MAE {baseline['mae']} / 0.5%p {baseline['hit_0_5']:.2%} "
          f"/ R2 {baseline['r2']} ({baseline['seconds']}초)")

    trials: list[dict] = [{"round": 0, "axis": "baseline", "params": dict(best), **baseline}]
    best_mae = baseline["mae"]

    for round_no in range(1, args.rounds + 1):
        improved_in_round = False
        for axis, candidates in axes.items():
            print(f"\n[{round_no}회차] {axis} (현재 {best[axis]})")
            for value in candidates:
                if value == best[axis]:
                    continue
                params = {**best, axis: value}
                result = evaluate(train, valid, params)
                trials.append({"round": round_no, "axis": axis, "params": dict(params), **result})
                mark = ""
                if result["mae"] < best_mae:
                    best_mae, best[axis], mark = result["mae"], value, "  <- 채택"
                    improved_in_round = True
                print(f"  {axis}={value}: MAE {result['mae']} / 0.5%p {result['hit_0_5']:.2%} "
                      f"/ R2 {result['r2']} ({result['seconds']}초){mark}")

        if not improved_in_round:
            print(f"\n{round_no}회차에서 개선이 없어 중단합니다.")
            break

    final = evaluate(train, valid, best)
    print(f"\n{'=' * 92}\n최종 파라미터\n{'=' * 92}")
    print(json.dumps(best, ensure_ascii=False, indent=2))

    comparison = pd.DataFrame(
        [
            {"구분": "기준선", **{k: baseline[k] for k in ("mae", "rmse", "r2", "hit_0_5", "hit_1_0", "bias")}},
            {"구분": "탐색 결과", **{k: final[k] for k in ("mae", "rmse", "r2", "hit_0_5", "hit_1_0", "bias")}},
        ]
    )
    print(f"\n{comparison.to_string(index=False)}")

    gain = baseline["mae"] - final["mae"]
    print(
        f"\nMAE {gain:+.4f}%p / 0.5%p 적중 {final['hit_0_5'] - baseline['hit_0_5']:+.2%} "
        f"(시행 {len(trials)}회)"
    )
    if gain <= 0:
        print("개선이 없습니다. 기준 파라미터를 유지하십시오.")

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "train_end": args.train_end,
                "valid_year": args.valid_year,
                "baseline": {"params": trials[0]["params"], "metrics": baseline},
                "best": {"params": best, "metrics": final},
                "trials": trials,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n전체 시행 기록: {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
