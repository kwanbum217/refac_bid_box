#!/usr/bin/env python3
"""
LightGBM 과 CatBoost 를 섞을 여지가 있는지 잽니다.

`train_and_register` 는 MAPE 가 가장 낮은 **하나만** 고릅니다. CatBoost 가 R2
0.6994 로 LightGBM 0.6967 을 이겼는데 MAPE 로만 순서가 뒤집힌 적이 있어(1.431
대 1.5025) 강점이 다르다는 신호로 읽혔고, 앙상블이 다음 축으로 남았습니다.

앙상블을 구현하려면 선택 로직 자체를 손봐야 해서 범위가 큽니다. **구현 전에
여지가 있는지부터 재는 것이 순서입니다.** 판정은 두 값으로 합니다.

    잔차 상관        두 모델이 같은 곳에서 틀리면 섞어도 달라지지 않습니다
    단순 평균 MAE    가중치를 최적화하기 전, 반반 평균이 둘 다를 이기는가

반반 평균조차 이기지 못하면 가중치를 찾아도 이득은 작습니다. 상관이 0.95 를
넘으면 그 계열은 볼 필요가 없습니다.

사용법:
    .venv/bin/python scripts/eval_servc_ensemble_headroom.py
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import warnings
from pathlib import Path
from typing import cast

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import r2_score  # noqa: E402

from scripts.eval_servc_year_holdout import ALL_FEATURES, build_frame  # noqa: E402
from src.ml.trainer import (  # noqa: E402
    DEFAULT_VALIDATION_SPLIT,
    TIME_SORT_COLUMN,
    _train_catboost,
    _train_lightgbm,
    hyperparams_for_category,
)

CATEGORY = "Servc"

# 상관이 이 값을 넘으면 두 모델이 같은 곳에서 틀린다고 봅니다. 섞어도 오차가
# 상쇄되지 않습니다.
CORRELATION_CEILING = 0.95


def metrics(pred: np.ndarray, actual: np.ndarray) -> dict[str, float]:
    abs_err = np.abs(pred - actual)
    return {
        "mae": round(float(abs_err.mean()), 4),
        "rmse": round(float(np.sqrt(np.mean((pred - actual) ** 2))), 4),
        "r2": round(float(r2_score(actual, pred)), 4),
        "hit_0_5": round(float((abs_err <= 0.5).mean()), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--out", default="data/servc_ensemble_headroom.json")
    parser.add_argument(
        "--catboost-loss",
        default=None,
        help="CatBoost loss_function 재정의 (예: MAE, Quantile:alpha=0.5). 미지정이면 운영 설정",
    )
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df = build_frame(path, args.train_end)
    year = df["openg_dt"].dt.year
    train = df[year <= args.train_end].sort_values(TIME_SORT_COLUMN, kind="stable")
    valid = df[year == args.valid_year].copy()
    if train.empty or valid.empty:
        print(f"구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
        return 1

    # 조기 종료용 분할입니다. 검증 연도를 쓰면 트리 수를 검증 연도로 정하고 같은
    # 연도에서 점수를 내게 되어 누수입니다.
    split_at = int(len(train) * (1 - DEFAULT_VALIDATION_SPLIT))
    inner_train, inner_valid = train.iloc[:split_at], train.iloc[split_at:]
    X_in, y_in = inner_train[ALL_FEATURES], inner_train["winning_rate"].to_numpy(dtype=float)
    X_ev, y_ev = inner_valid[ALL_FEATURES], inner_valid["winning_rate"].to_numpy(dtype=float)

    actual = valid["winning_rate"].to_numpy(dtype=float)
    print(f"학습 {len(train):,}행 / 검증 {len(valid):,}행 / 특징 {len(ALL_FEATURES)}개")

    # 운영과 같은 카테고리 설정을 씁니다. 여기서 갈리면 비교가 운영을 대변하지
    # 못합니다.
    overrides = hyperparams_for_category(CATEGORY)
    if args.catboost_loss:
        # CatBoost 기본 목적함수는 RMSE 라 조건부 평균을 겨냥합니다. LightGBM 은
        # quantile(0.5) 로 중앙값을 겨냥하므로 평균을 내면 겨냥이 희석됩니다.
        # 목적함수를 맞추면 그 희석이 사라지는지 재기 위한 갈래입니다.
        overrides["catboost"] = {
            **overrides.get("catboost", {}),
            "loss_function": args.catboost_loss,
        }
        print(f"CatBoost 목적함수 재정의: {args.catboost_loss}")

    preds: dict[str, np.ndarray] = {}
    for name, trainer_fn in (("lightgbm", _train_lightgbm), ("catboost", _train_catboost)):
        started = time.perf_counter()
        model = trainer_fn(X_in, y_in, X_ev, y_ev, overrides.get(name))
        preds[name] = np.asarray(model.predict(valid[ALL_FEATURES]), dtype=float)
        print(f"  {name} 학습 {time.perf_counter() - started:.0f}초")

    rows = [{"모델": name, **metrics(pred, actual)} for name, pred in preds.items()]

    blend = 0.5 * preds["lightgbm"] + 0.5 * preds["catboost"]
    rows.append({"모델": "반반 평균", **metrics(blend, actual)})
    print(f"\n{pd.DataFrame(rows).to_string(index=False)}")

    resid = {name: pred - actual for name, pred in preds.items()}
    correlation = float(np.corrcoef(resid["lightgbm"], resid["catboost"])[0, 1])

    best_single = min(cast(float, rows[0]["mae"]), cast(float, rows[1]["mae"]))
    blend_mae = cast(float, rows[2]["mae"])
    gain = best_single - blend_mae

    # 가중치를 검증 연도에서 고르는 것은 오라클입니다. 실제로는 이 가중치를
    # 미리 알 수 없으므로 이 값은 상한이며, 상한조차 이득이 없으면 가중치
    # 탐색을 구현할 이유가 없습니다.
    sweep = []
    for weight in np.round(np.arange(0.0, 1.01, 0.05), 2):
        mixed = weight * preds["lightgbm"] + (1 - weight) * preds["catboost"]
        sweep.append({"lgbm 가중": float(weight), **metrics(mixed, actual)})
    sweep_frame = pd.DataFrame(sweep)
    best_row = sweep_frame.loc[sweep_frame["mae"].idxmin()]
    oracle_gain = best_single - float(best_row["mae"])

    print(f"\n### 가중치 스윕 (검증 연도에서 고른 오라클)\n{sweep_frame.to_string(index=False)}")
    print(
        f"\n오라클 최적 가중치 {best_row['lgbm 가중']:.2f} 에서 MAE {best_row['mae']:.4f}, "
        f"단일 최고 대비 {oracle_gain:+.4f}"
    )

    print(f"\n{'=' * 76}")
    print(f"잔차 상관 {correlation:.4f} (한계 {CORRELATION_CEILING})")
    print(f"반반 평균이 단일 최고 대비 MAE {gain:+.4f}")

    if correlation >= CORRELATION_CEILING:
        print("두 모델이 같은 곳에서 틀립니다. 앙상블 여지가 없습니다.")
    elif gain <= 0:
        print("상관은 낮으나 반반 평균이 단일 최고를 이기지 못합니다. 여지가 작습니다.")
    else:
        print("여지가 있습니다. 가중치 탐색과 운영 쌍대 검정으로 진행하십시오.")

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "train_end": args.train_end,
                "valid_year": args.valid_year,
                "metrics": rows,
                "catboost_loss": args.catboost_loss,
                "residual_correlation": correlation,
                "blend_gain_over_best_single": gain,
                "weight_sweep": sweep,
                "oracle_best_weight": float(best_row["lgbm 가중"]),
                "oracle_gain_over_best_single": oracle_gain,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n측정 기록: {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
