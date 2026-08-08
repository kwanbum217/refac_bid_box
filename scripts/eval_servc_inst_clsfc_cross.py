#!/usr/bin/env python3
"""
기관 x 소분류 교차가 잔차를 가르는지 잽니다.

현행 기관 이력(`inst_hist_rate`, `inst_ewm_rate`)은 기관 전체 평균이고 소분류는
범주 특징으로 따로 들어갑니다. **둘의 교차는 없습니다.** 같은 기관이라도
소분류가 다르면 낙찰률 수준이 다를 수 있다는 것이 이 축의 가설입니다.

특징을 만들어 재학습하면 한 번에 40분이 넘습니다. 잔차 parquet 은 이미 기관
이력을 반영한 모델의 것이므로, 그 잔차가 기관 x 소분류로 갈린다면 그것이
**증분 신호**입니다. 재학습 전에 여기서 판정합니다.

측정 순서는 스킬의 원칙을 따릅니다. **재현성보다 오라클을 먼저** 잽니다.
소분류 단독 오프셋은 연도 간 상관 0.803, 부호 일치 85.7% 로 재현성이 매우
높았는데도 오라클 오프셋이 MAE 를 0.1525 악화시켰습니다. 재현성은 이용
가능성이 아닙니다.

    1. 셀 크기 분포        기관 x 소분류가 쓸 만한 표본을 남기는가
    2. 오라클 (상한)       그 해 셀 오프셋을 그 해에서 빼면 MAE 가 개선되는가
    3. 재현성              오라클이 이득일 때만. 연도 간 상관과 부호 일치
    4. 실용                전년 셀 오프셋을 다음 해에 적용

**오프셋은 평균과 중앙값을 함께 잽니다.** 운영 지표는 MAE 이고 점 추정
목적함수는 `quantile(0.5)` 이므로 MAE 를 최소화하는 상수 오프셋은 셀 잔차의
**중앙값**입니다. 소분류 단독 기각 때 쓴 평균 오프셋은 이 점에서 불리했고,
그 문서도 왜도와 편향의 부호가 반대였다는 것을 실패 원인으로 적었습니다.

**최소 셀 크기 없이는 오라클이 무의미합니다.** 표본 1건짜리 셀은 오프셋이
잔차 그 자체라 MAE 가 0 이 됩니다. 오프셋은 임계값을 넘긴 셀에만 적용하고
임계값을 여러 개로 훑습니다.

사용법:
    .venv/bin/python scripts/eval_servc_inst_clsfc_cross.py
    .venv/bin/python scripts/eval_servc_inst_clsfc_cross.py --years 2024 2025 2026
"""

from __future__ import annotations

import argparse
import json
import sys
from itertools import pairwise
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

RESIDUAL_DIR = PROJECT_ROOT / "data" / "analysis" / "servc_residuals"
DEFAULT_YEARS = [2023, 2024, 2025, 2026]

# 오프셋을 적용할 셀의 최소 표본 수. 작을수록 오라클이 낙관적이며 1 이면
# 정의상 MAE 가 0 이 됩니다. 실용 단계에서 쓸 수 있는 값까지 함께 훑습니다.
MIN_CELL_ROWS = [10, 20, 50, 100]

# 이 축의 정본 키입니다. 기관은 수요기관을 씁니다. features.py 의 기관 이력이
# dminstt_nm 을 우선 해석하므로 교차도 같은 기준이어야 증분 신호가 됩니다.
CELL_KEYS = ["dminstt_nm", "clsfc_nm"]

# 교차가 단독보다 나은지 확인하는 대조군입니다. 교차가 단독을 이기지 못하면
# 교차라는 형태 자체에 근거가 없습니다. 소분류 단독은 이미 평균 오프셋으로
# 기각됐지만 중앙값 오프셋에서는 다시 재야 합니다.
VARIANTS = {
    "기관 단독": ["dminstt_nm"],
    "소분류 단독": ["clsfc_nm"],
    "기관 x 소분류": CELL_KEYS,
}


def set_cell(df: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    df = df.copy()
    df["cell"] = df[keys[0]].astype(str)
    for key in keys[1:]:
        df["cell"] = df["cell"] + " | " + df[key].astype(str)
    return df


def load_year(year: int) -> pd.DataFrame:
    path = RESIDUAL_DIR / f"servc_residuals_{year}.parquet"
    if not path.exists():
        raise SystemExit(f"잔차 parquet 이 없습니다: {path}")
    df = pd.read_parquet(path)
    missing = [c for c in CELL_KEYS if c not in df.columns]
    if missing:
        raise SystemExit(
            f"{path.name} 에 {missing} 이 없습니다. "
            "diagnose_servc_lwlt_residuals.py --dump-dir 로 재생성하십시오."
        )
    return set_cell(df, CELL_KEYS)


def cell_size_table(df: pd.DataFrame) -> pd.DataFrame:
    sizes = df.groupby("cell", observed=True).size()
    rows = []
    for threshold in [1, 5, 10, 20, 50, 100]:
        kept = sizes[sizes >= threshold]
        rows.append(
            {
                "최소 표본": threshold,
                "셀 수": len(kept),
                "포함 행": int(kept.sum()),
                "행 비중": round(float(kept.sum()) / len(df), 4),
            }
        )
    return pd.DataFrame(rows)


def offsets(df: pd.DataFrame, min_rows: int, stat: str) -> pd.Series:
    """임계값을 넘긴 셀의 잔차 대표값입니다. err = pred - actual 이므로 빼면 보정입니다."""
    grouped = df.groupby("cell", observed=True)["err"]
    table = grouped.median() if stat == "median" else grouped.mean()
    counts = grouped.size()
    return table[counts >= min_rows]


def apply_offsets(df: pd.DataFrame, table: pd.Series) -> np.ndarray:
    shift = df["cell"].map(table).fillna(0.0).to_numpy(dtype=float)
    return np.abs(df["err"].to_numpy(dtype=float) - shift)


def oracle_table(by_year: dict[int, pd.DataFrame]) -> pd.DataFrame:
    """그 해 오프셋을 그 해에 적용한 상한입니다. 실제로는 도달할 수 없습니다."""
    rows = []
    for year, df in by_year.items():
        base = float(df["abs_err"].mean())
        for min_rows in MIN_CELL_ROWS:
            for stat in ("median", "mean"):
                table = offsets(df, min_rows, stat)
                covered = df["cell"].isin(table.index)
                after = float(apply_offsets(df, table).mean())
                rows.append(
                    {
                        "연도": year,
                        "최소 표본": min_rows,
                        "오프셋": stat,
                        "적용 셀": len(table),
                        "적용 행 비중": round(float(covered.mean()), 4),
                        "MAE 전": round(base, 4),
                        "MAE 후": round(after, 4),
                        "개선": round(base - after, 4),
                    }
                )
    return pd.DataFrame(rows)


def reproducibility_table(
    by_year: dict[int, pd.DataFrame], min_rows: int, stat: str
) -> pd.DataFrame:
    years = sorted(by_year)
    rows = []
    for prev, curr in pairwise(years):
        a = offsets(by_year[prev], min_rows, stat)
        b = offsets(by_year[curr], min_rows, stat)
        common = a.index.intersection(b.index)
        if len(common) < 10:
            rows.append(
                {
                    "연도쌍": f"{prev}->{curr}",
                    "공통 셀": len(common),
                    "상관": None,
                    "부호 일치": None,
                }
            )
            continue
        x, y = a[common], b[common]
        rows.append(
            {
                "연도쌍": f"{prev}->{curr}",
                "공통 셀": len(common),
                "상관": round(float(np.corrcoef(x, y)[0, 1]), 4),
                "부호 일치": round(float((np.sign(x) == np.sign(y)).mean()), 4),
            }
        )
    return pd.DataFrame(rows)


def practical_table(by_year: dict[int, pd.DataFrame], stat: str) -> pd.DataFrame:
    """전년 오프셋을 다음 해에 적용합니다. 이것만이 실제로 쓸 수 있는 형태입니다."""
    years = sorted(by_year)
    rows = []
    for prev, curr in pairwise(years):
        df = by_year[curr]
        base = float(df["abs_err"].mean())
        for min_rows in MIN_CELL_ROWS:
            table = offsets(by_year[prev], min_rows, stat)
            covered = df["cell"].isin(table.index)
            after = float(apply_offsets(df, table).mean())
            rows.append(
                {
                    "연도쌍": f"{prev}->{curr}",
                    "최소 표본": min_rows,
                    "적용 행 비중": round(float(covered.mean()), 4),
                    "MAE 전": round(base, 4),
                    "MAE 후": round(after, 4),
                    "개선": round(base - after, 4),
                }
            )
    return pd.DataFrame(rows)


def variant_table(by_year: dict[int, pd.DataFrame], min_rows: int, stat: str) -> pd.DataFrame:
    """세 가지 키 정의를 같은 조건으로 비교합니다. 오라클과 실용을 함께 봅니다."""
    rows = []
    for label, keys in VARIANTS.items():
        scoped = {year: set_cell(df, keys) for year, df in by_year.items()}
        oracle = oracle_table(scoped)
        picked = oracle[(oracle["최소 표본"] == min_rows) & (oracle["오프셋"] == stat)]
        practical = practical_table(scoped, stat)
        practical = practical[practical["최소 표본"] == min_rows]
        rows.append(
            {
                "키": label,
                "셀 수 (최신)": int(scoped[max(scoped)]["cell"].nunique()),
                "오라클 최소": round(float(picked["개선"].min()), 4),
                "오라클 평균": round(float(picked["개선"].mean()), 4),
                "실용 최소": round(float(practical["개선"].min()), 4),
                "실용 평균": round(float(practical["개선"].mean()), 4),
            }
        )
    return pd.DataFrame(rows)


def report(title: str, frame: pd.DataFrame) -> None:
    print(f"\n### {title}")
    print(frame.to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, nargs="+", default=DEFAULT_YEARS)
    parser.add_argument("--stat", choices=["median", "mean"], default="median")
    parser.add_argument("--min-rows", type=int, default=20)
    parser.add_argument("--output", type=str, default="data/servc_inst_clsfc_cross.json")
    args = parser.parse_args()

    by_year = {year: load_year(year) for year in args.years}

    for year, df in by_year.items():
        print(
            f"{year}: {len(df):,}행, 셀 {df['cell'].nunique():,}개, MAE {df['abs_err'].mean():.4f}"
        )

    report("1. 셀 크기 분포 (최신 연도)", cell_size_table(by_year[max(by_year)]))

    oracle = oracle_table(by_year)
    report("2. 오라클 상한 (같은 해 오프셋을 같은 해에)", oracle)

    picked = oracle[(oracle["최소 표본"] == args.min_rows) & (oracle["오프셋"] == args.stat)]
    best = float(picked["개선"].min())
    print(
        f"\n판정 기준: 최소 표본 {args.min_rows}, {args.stat} 오프셋에서 "
        f"모든 연도의 오라클 개선이 양수여야 다음 단계로 갑니다. 최소 개선 {best:+.4f}"
    )

    payload: dict[str, object] = {
        "years": args.years,
        "stat": args.stat,
        "min_rows": args.min_rows,
        "cell_sizes": cell_size_table(by_year[max(by_year)]).to_dict(orient="records"),
        "oracle": oracle.to_dict(orient="records"),
        "oracle_min_gain": best,
    }

    if best <= 0:
        print("\n오라클이 이득을 내지 못했습니다. 재현성과 실용 단계는 의미가 없어 건너뜁니다.")
        payload["verdict"] = "closed_at_oracle"
    else:
        repro = reproducibility_table(by_year, args.min_rows, args.stat)
        report("3. 재현성 (연도 간 오프셋 상관)", repro)
        practical = practical_table(by_year, args.stat)
        report("4. 실용 (전년 오프셋을 다음 해에)", practical)
        payload["reproducibility"] = repro.to_dict(orient="records")
        payload["practical"] = practical.to_dict(orient="records")
        payload["practical_min_gain"] = float(
            practical[practical["최소 표본"] == args.min_rows]["개선"].min()
        )
        payload["verdict"] = "open" if payload["practical_min_gain"] > 0 else "closed_at_practical"

    variants = variant_table(by_year, args.min_rows, args.stat)
    report("5. 키 정의 대조 (교차가 단독을 이기는가)", variants)
    payload["variants"] = variants.to_dict(orient="records")

    out = PROJECT_ROOT / args.output
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n저장: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
