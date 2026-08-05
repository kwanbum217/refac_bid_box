#!/usr/bin/env python3
"""
홀드아웃 MAE 0.76 과 운영 MAE 0.96 의 격차가 **모델 때문인지 경로 때문인지**
가릅니다.

두 측정은 조건이 같습니다. 2025년, 하한율 보유 구간. 그런데 30% 차이납니다.
운영 쪽이 오히려 2025년을 학습에 포함하고도 나쁩니다.

가능한 원인은 둘입니다.

| 후보 | 내용 |
| --- | --- |
| 모델 | 홀드아웃은 2015~2024 로 그 자리에서 학습, 운영은 전량 학습 후 승격된 아티팩트 |
| 경로 | 홀드아웃은 parquet 프레임을 그대로, 운영은 DB 에서 특징을 재구성 |

가르는 방법은 **서빙 모델을 parquet 프레임에 직접 적용**하는 것입니다.

    서빙 모델 + parquet 특징  <- 이 스크립트가 재는 값
    서빙 모델 + API 경로      MAE 0.96 (기측정)
    홀드아웃 모델 + parquet   MAE 0.76 (기측정)

0.76 에 가까우면 경로가 원인이고, 0.96 에 가까우면 모델이 원인입니다.

사용법:
    .venv/bin/python scripts/diagnose_serving_vs_holdout_model.py
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

import joblib  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from scripts.eval_servc_year_holdout import build_frame  # noqa: E402
from src.ml.features import apply_categorical_dtypes  # noqa: E402

SERVING_DIR = PROJECT_ROOT / "data" / "model_files" / "servc_institution_v1"


def load_serving_model() -> tuple[object, list[str], dict]:
    """서빙 아티팩트와 그것이 요구하는 특징 목록·범주 수준을 함께 읽습니다."""
    import json

    metadata = json.loads((SERVING_DIR / "metadata.json").read_text(encoding="utf-8"))
    model = joblib.load(SERVING_DIR / "model.bin")
    features = metadata.get("required_features") or []
    levels = metadata.get("category_levels") or metadata.get("categorical_levels") or {}
    return model, list(features), levels if isinstance(levels, dict) else {}


def score(actual: np.ndarray, pred: np.ndarray, label: str, count: int) -> dict:
    error = np.abs(pred - actual)
    return {
        "구성": label,
        "건수": count,
        "MAE": round(float(error.mean()), 4),
        "RMSE": round(float(np.sqrt(((pred - actual) ** 2).mean())), 4),
        "0.5%p 적중": round(float((error <= 0.5).mean()), 4),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--train-end", type=int, default=2024)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1
    if not (SERVING_DIR / "model.bin").exists():
        print(f"서빙 모델이 없습니다: {SERVING_DIR}")
        return 1

    frame = build_frame(path, args.train_end)
    year = frame["openg_dt"].dt.year
    valid = frame[year == args.valid_year].copy()
    print(f"검증 {len(valid):,}행 ({args.valid_year}년)")

    model, features, levels = load_serving_model()
    print(f"서빙 모델 특징 {len(features)}개")

    # 요일 주기 특징은 `build_frame` 이 만들지 않습니다. `features.py` 와 같은
    # 정의로 채웁니다. 정의가 갈리면 비교 자체가 무의미해집니다.
    reference = pd.to_datetime(valid["openg_dt"], errors="coerce")
    weekday = reference.dt.weekday
    valid["weekday_sin"] = np.sin(2 * np.pi * weekday / 7)
    valid["weekday_cos"] = np.cos(2 * np.pi * weekday / 7)

    missing = [name for name in features if name not in valid.columns]
    if missing:
        print(f"\nparquet 프레임에 없는 특징 {len(missing)}개: {missing}")
        print("이 특징들은 학습기가 만드는 파생값입니다. 비교가 성립하지 않습니다.")
        return 1

    X = apply_categorical_dtypes(valid[features], levels)
    pred = np.asarray(model.predict(X), dtype=float)
    actual = valid["winning_rate"].to_numpy(dtype=float)

    has_lwlt = (valid["lwlt_rate_missing"] == 0).to_numpy()
    rows = [
        score(actual, pred, "서빙 모델 + parquet (전체)", len(valid)),
        score(actual[has_lwlt], pred[has_lwlt], "서빙 모델 + parquet (하한율 보유)", int(has_lwlt.sum())),
        score(actual[~has_lwlt], pred[~has_lwlt], "서빙 모델 + parquet (하한율 결측)", int((~has_lwlt).sum())),
    ]
    print(f"\n{'=' * 88}\n결과\n{'=' * 88}")
    print(pd.DataFrame(rows).to_string(index=False))

    served = float(rows[1]["MAE"])
    print(f"\n{'=' * 88}\n판정\n{'=' * 88}")
    print("기측정값과 대조합니다 (모두 2025년 하한율 보유 구간).")
    print("  홀드아웃 모델 + parquet : 0.7616")
    print(f"  서빙 모델 + parquet     : {served:.4f}  <- 이번 측정")
    print("  서빙 모델 + API 경로    : 0.9590")
    print()
    if abs(served - 0.7616) < abs(served - 0.9590):
        print("**경로가 원인입니다.** 같은 모델도 parquet 로 재면 홀드아웃에 가깝습니다.")
        print("API 경로가 만드는 특징이 학습 프레임과 다르다는 뜻입니다.")
    else:
        print("**모델이 원인입니다.** 서빙 아티팩트 자체가 홀드아웃 실험 모델보다")
        print("이 구간에서 나쁩니다. 전량 학습이 2025년 성능을 떨어뜨렸을 수 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
