#!/usr/bin/env python3
"""
홀드아웃 개선이 운영에서 재현되지 않는 이유를 찾습니다.

`num_leaves` 를 올리면 2025년 홀드아웃 MAE 가 1.0~1.4% 좋아지는데, 운영 API
경로에서는 255 도 127 도 이득이 나타나지 않았습니다(127 은 전 지표 악화).
두 번 연속 같은 방향이라 우연으로 보기 어렵습니다.

가장 유력한 원인은 **두 표본의 구성이 다르다**는 것입니다. 운영 측정은
`--require-lwlt` 로 하한율 보유 건만 뽑는 반면, 홀드아웃은 결측 건을 22% 포함
합니다. 결측 건은 낙찰률 표준편차가 2.3배라 오차가 크고, 리프를 늘리면 바로
그 어려운 구간에서 이득이 나기 쉽습니다. 그렇다면 홀드아웃 전체 평균은
좋아지는데 운영이 보는 구간은 나빠질 수 있습니다.

이 가설은 **홀드아웃을 하한율 보유 건으로 한정해 다시 재면** 판정됩니다.
한정한 구간에서도 리프가 클수록 좋다면 가설은 틀린 것이고, 뒤집힌다면
홀드아웃 지표 자체를 운영 구성에 맞춰 재정의해야 합니다.

사용법:
    .venv/bin/python scripts/diagnose_holdout_serving_gap.py
    .venv/bin/python scripts/diagnose_holdout_serving_gap.py --leaves 63,127,255
"""

from __future__ import annotations

import argparse
import sys
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
from sklearn.metrics import mean_squared_error  # noqa: E402

from scripts.eval_servc_year_holdout import ALL_FEATURES, build_frame  # noqa: E402
from src.ml.trainer import LGB_BASE_PARAMS  # noqa: E402

POINT_OBJECTIVE = {"objective": "huber", "alpha": 1.0}


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


# 운영 측정(`eval_servc_api_path.py --require-lwlt`)이 보는 구간입니다.
SERVING_SEGMENT = "하한율 보유"

PRICE_BANDS = [
    ("1천만 미만", 0, 10_000_000),
    ("1천만~5천만", 10_000_000, 50_000_000),
    ("5천만~2.3억", 50_000_000, 230_000_000),
    ("2.3억 이상", 230_000_000, float("inf")),
]


def describe_composition(valid: pd.DataFrame) -> None:
    """홀드아웃이 무엇으로 이루어져 있는지 봅니다."""
    has_lwlt = valid["lwlt_rate_missing"] == 0
    print(f"\n{'=' * 88}\n홀드아웃 구성\n{'=' * 88}")
    print(f"전체 {len(valid):,}건")
    rows = []
    for label, mask in (("하한율 보유", has_lwlt), ("하한율 결측", ~has_lwlt)):
        part = valid[mask]
        rows.append(
            {
                "구간": label,
                "건수": len(part),
                "비중": f"{len(part) / len(valid):.1%}",
                "낙찰률 평균": round(float(part["winning_rate"].mean()), 3),
                "표준편차": round(float(part["winning_rate"].std()), 3),
            }
        )
    print(pd.DataFrame(rows).to_string(index=False))
    print(
        f"\n운영 측정은 '{SERVING_SEGMENT}' 만 봅니다(보유율 100%). "
        f"홀드아웃은 {rows[0]['비중']} 입니다."
    )


def fit(train: pd.DataFrame, leaves: int):
    model = lgb.LGBMRegressor(
        **cast(_LGBMKwargs, {**LGB_BASE_PARAMS, **POINT_OBJECTIVE, "num_leaves": leaves})
    )
    model.fit(train[ALL_FEATURES], train["winning_rate"])
    return model


def score(model, part: pd.DataFrame) -> dict:
    if part.empty:
        return {}
    pred = model.predict(part[ALL_FEATURES])
    actual = part["winning_rate"].to_numpy(dtype=float)
    error = np.abs(pred - actual)
    return {
        "건수": len(part),
        "MAE": round(float(error.mean()), 4),
        "RMSE": round(float(np.sqrt(mean_squared_error(actual, pred))), 4),
        "0.5%p 적중": round(float((error <= 0.5).mean()), 4),
    }


def compare(models: dict[int, object], valid: pd.DataFrame, label: str) -> pd.DataFrame:
    rows = []
    for leaves, model in models.items():
        result = score(model, valid)
        if result:
            rows.append({"구간": label, "리프": leaves, **result})
    return pd.DataFrame(rows)


def verdict(table: pd.DataFrame, base_leaves: int) -> None:
    """구간마다 리프를 늘리는 것이 이득인지 손해인지 방향을 찍습니다."""
    print(f"\n{'=' * 88}\n판정\n{'=' * 88}")
    for segment, part in table.groupby("구간", sort=False):
        base = part[part["리프"] == base_leaves]
        if base.empty:
            continue
        base_mae = float(base.iloc[0]["MAE"])
        best = part.loc[part["MAE"].idxmin()]
        direction = "리프 상향이 이득" if int(best["리프"]) > base_leaves else "기준 리프가 최선"
        gain = base_mae - float(best["MAE"])
        print(
            f"  {segment:<12} {direction:<16} "
            f"최소 MAE 리프 {int(best['리프']):>3} / {gain:+.4f} ({gain / base_mae:+.2%})"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--leaves", default="63,127")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df = build_frame(path, args.train_end)
    year = df["openg_dt"].dt.year
    train = df[year <= args.train_end]
    valid = df[year == args.valid_year].copy()
    print(f"학습 {len(train):,}행 / 검증 {len(valid):,}행")

    describe_composition(valid)

    leaves_list = [int(v) for v in args.leaves.split(",")]
    models = {}
    for leaves in leaves_list:
        print(f"\n리프 {leaves} 학습 중", flush=True)
        models[leaves] = fit(train, leaves)

    has_lwlt = valid["lwlt_rate_missing"] == 0
    tables = [
        compare(models, valid, "홀드아웃 전체"),
        compare(models, valid[has_lwlt], SERVING_SEGMENT),
        compare(models, valid[~has_lwlt], "하한율 결측"),
    ]
    table = pd.concat(tables, ignore_index=True)
    print(f"\n{'=' * 88}\n구간별 성능\n{'=' * 88}")
    print(table.to_string(index=False))

    verdict(table, leaves_list[0])

    print(f"\n{'=' * 88}\n금액대별 ({SERVING_SEGMENT} 한정)\n{'=' * 88}")
    serving = valid[has_lwlt]
    band_rows = []
    for label, low, high in PRICE_BANDS:
        part = serving[(serving["presmpt_prce"] >= low) & (serving["presmpt_prce"] < high)]
        band_rows.append(compare(models, part, label))
    band_table = pd.concat([t for t in band_rows if not t.empty], ignore_index=True)
    print(band_table.to_string(index=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
