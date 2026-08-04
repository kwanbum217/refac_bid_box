#!/usr/bin/env python3
"""
캐싱된 parquet 으로 용역 모델을 재학습합니다.

`src/tasks/retrain_task.py` 는 `build_training_dataset` 이 DB 를 읽어야 하므로
컨테이너가 필요합니다. 데이터셋 재생성 없이 학습기만 다시 돌리고 싶을 때 —
하이퍼파라미터 변경 검증이 대표적입니다 — 이 스크립트가 그 구간만 떼어 냅니다.

**parquet 이 최신인지는 호출자가 책임집니다.** 새 공고를 반영하려면 DB 경로로
`build_training_dataset` 을 먼저 돌려야 합니다.

승격은 하지 않습니다. `ml_registry` 에만 남기고 지표를 출력하므로, 채택 여부를
보고 `src.ml.promotion.promote` 를 따로 부르십시오.

사용법:
    .venv/bin/python scripts/retrain_servc_from_parquet.py
    .venv/bin/python scripts/retrain_servc_from_parquet.py --category Thng
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

import pandas as pd  # noqa: E402

from src.ml.trainer import ModelTrainer  # noqa: E402

# 이 값들 아래로 떨어지면 승격 후보로 볼 수 없습니다. 현행 champion 실측치이며
# 근거는 docs/handoff/2026-08-04_servc_serving_handoff.md 2장입니다.
CHAMPION_REFERENCE = {"servc_institution_v1": {"r2": 0.6881, "rmse": 2.6757, "mae": 1.3176}}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="Servc")
    parser.add_argument("--parquet", default=None, help="기본값은 dataset_{category}.parquet")
    parser.add_argument("--min-rows", type=int, default=100_000, help="이보다 적으면 중단")
    args = parser.parse_args()

    parquet = Path(
        args.parquet or f"data/feature_store/dataset_{args.category}.parquet"
    )
    path = PROJECT_ROOT / parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    df = pd.read_parquet(path)
    print(f"데이터셋 {path.name}: {len(df):,}행 x {len(df.columns)}컬럼")
    # 과거에 테스트 픽스처가 운영 parquet 을 80행으로 덮어쓴 적이 있습니다.
    # 그대로 학습하면 지표만 좋은 빈 모델이 레지스트리에 들어갑니다.
    if len(df) < args.min_rows:
        print(f"행 수가 {args.min_rows:,} 미만입니다. 픽스처가 덮어썼는지 확인하십시오.")
        return 1

    trainer = ModelTrainer.for_category(args.category)
    print(f"학습기: {trainer.model_name}")

    started = time.perf_counter()
    metadata = trainer.train_and_register(df)
    elapsed = time.perf_counter() - started

    metrics = metadata["metrics"]
    print(f"\n버전 {metadata['version']} / {elapsed:.0f}초 / 모델 {metadata.get('model_type')}")
    print(json.dumps(metrics, ensure_ascii=False, indent=2))

    folds = (metadata.get("cv_metrics") or {}).get("folds") or []
    if folds:
        print(f"\n폴드별 R2: {[round(float(f.get('r2', 0)), 4) for f in folds]}")

    reference = CHAMPION_REFERENCE.get(trainer.model_name)
    if reference:
        rows = [
            {"구분": "현행 champion", **reference},
            {"구분": "이번 학습", **{k: metrics.get(k) for k in reference}},
        ]
        print(f"\n{pd.DataFrame(rows).to_string(index=False)}")

    print(
        f"\n승격은 하지 않았습니다. 채택하려면:\n"
        f'  from src.ml.promotion import promote\n'
        f'  promote("{trainer.model_name}", category_code="{args.category}")'
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
