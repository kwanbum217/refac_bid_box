#!/usr/bin/env python3
"""
좌표 하강이 낸 개선폭이 학습 무작위성보다 큰지 확인합니다.

좌표 하강은 축마다 **가장 좋은 값을 고르는** 절차라, 축을 훑는 것만으로도
무작위 변동의 상단이 누적됩니다. 축 8개를 훑으면 실제 이득이 0 이어도 홀드아웃
MAE 는 조금 내려갑니다. 그래서 "탐색이 개선을 냈다" 는 그 개선폭이 같은 설정을
시드만 바꿔 돌렸을 때의 산포보다 클 때만 의미가 있습니다.

`tune_servc_hyperparams.py` 가 남긴 JSON 의 기준선·최종 파라미터를 읽어 두
설정을 여러 시드로 학습하고, 시드 간 표준편차와 두 설정의 차이를 함께 냅니다.

판정은 단순합니다.

    차이 <= 시드 산포     -> 탐색 결과는 노이즈. 기준 파라미터 유지
    차이 >  시드 산포     -> 실체가 있음. 운영 경로 쌍대 검정으로 진행

사용법:
    .venv/bin/python scripts/measure_servc_tuning_noise.py
    .venv/bin/python scripts/measure_servc_tuning_noise.py --seeds 42,1,7,13
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import pandas as pd  # noqa: E402

from scripts.eval_servc_year_holdout import build_frame  # noqa: E402
from scripts.tune_servc_hyperparams import evaluate  # noqa: E402


def summarize(runs: list[dict], key: str) -> dict[str, float]:
    values = [run[key] for run in runs]
    return {
        "mean": statistics.fmean(values),
        "std": statistics.stdev(values) if len(values) > 1 else 0.0,
        "min": min(values),
        "max": max(values),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--search-json", default="data/servc_hyperparam_search_quantile.json")
    parser.add_argument("--train-end", type=int, default=2024)
    parser.add_argument("--valid-year", type=int, default=2025)
    parser.add_argument("--seeds", default="42,1,7", help="쉼표로 구분한 random_state 목록")
    parser.add_argument("--out", default="data/servc_tuning_noise.json")
    args = parser.parse_args()

    search_path = PROJECT_ROOT / args.search_json
    if not search_path.exists():
        print(f"탐색 결과가 없습니다: {search_path}")
        return 1

    search = json.loads(search_path.read_text(encoding="utf-8"))
    settings = {
        "기준선": search["baseline"]["params"],
        "탐색 결과": search["best"]["params"],
    }

    path = PROJECT_ROOT / args.parquet
    df = build_frame(path, args.train_end)
    year = df["openg_dt"].dt.year
    train = df[year <= args.train_end]
    valid = df[year == args.valid_year].copy()
    if train.empty or valid.empty:
        print(f"구간이 비었습니다 (학습 {len(train)}, 검증 {len(valid)})")
        return 1

    seeds = [int(value) for value in args.seeds.split(",")]
    print(f"학습 {len(train):,}행 / 검증 {len(valid):,}행 / 시드 {seeds}")

    records: dict[str, list[dict]] = {}
    for name, params in settings.items():
        print(f"\n[{name}] {params}")
        runs = []
        for seed in seeds:
            result = evaluate(train, valid, {**params, "random_state": seed})
            runs.append({"seed": seed, **result})
            print(
                f"  seed={seed}: MAE {result['mae']} / 0.5%p {result['hit_0_5']:.2%} "
                f"({result['seconds']}초)"
            )
        records[name] = runs

    rows = []
    for name, runs in records.items():
        mae = summarize(runs, "mae")
        hit = summarize(runs, "hit_0_5")
        rows.append(
            {
                "구분": name,
                "MAE 평균": round(mae["mean"], 4),
                "MAE 표준편차": round(mae["std"], 4),
                "MAE 폭": round(mae["max"] - mae["min"], 4),
                "0.5%p 평균": round(hit["mean"], 4),
                "0.5%p 표준편차": round(hit["std"], 4),
            }
        )
    print(f"\n{pd.DataFrame(rows).to_string(index=False)}")

    base_mae = summarize(records["기준선"], "mae")
    best_mae = summarize(records["탐색 결과"], "mae")
    gain = base_mae["mean"] - best_mae["mean"]
    # 시드 산포는 두 설정 중 큰 쪽을 씁니다. 작은 쪽을 쓰면 판정이 관대해집니다.
    noise = max(base_mae["std"], best_mae["std"])

    print(f"\n{'=' * 76}")
    print(f"평균 MAE 차이 {gain:+.4f} / 시드 표준편차 {noise:.4f}")
    if gain <= noise:
        print("차이가 시드 산포 이내입니다. 탐색 결과를 채택할 근거가 없습니다.")
    else:
        print(
            f"차이가 시드 산포의 {gain / noise:.1f}배입니다. 운영 경로 쌍대 검정으로 진행하십시오."
        )

    base_hit = summarize(records["기준선"], "hit_0_5")
    best_hit = summarize(records["탐색 결과"], "hit_0_5")
    hit_gain = best_hit["mean"] - base_hit["mean"]
    hit_noise = max(base_hit["std"], best_hit["std"])
    print(f"0.5%p 적중 차이 {hit_gain:+.4f} / 시드 표준편차 {hit_noise:.4f}")

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(
            {
                "seeds": seeds,
                "settings": settings,
                "runs": records,
                "mae_gain": gain,
                "mae_seed_std": noise,
                "hit_0_5_gain": hit_gain,
                "hit_0_5_seed_std": hit_noise,
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
