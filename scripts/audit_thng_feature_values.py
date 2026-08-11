#!/usr/bin/env python3
"""
물품(Thng) 학습 특징이 실제 값으로 채워지는지 특징별로 잽니다.

`scripts/audit_feature_parity_values.py` 는 학습과 서빙이 같은 값을 만드는지
봅니다. 이 스크립트는 그 앞 단계를 봅니다. 학습 프레임 자체에서 각 특징이
상수인지, 항상 기본값인지, 원본 컬럼 부재로 대체값만 받는지 판정합니다.

용역에서 `inst_sample_cnt` 가 서빙에서 항상 0 이던 결함과 같은 형태를 찾는
것이 목적입니다. 그 결함은 값이 존재하는 것처럼 보였지만 실제로는 정보가
전혀 없는 상수였습니다.

학습기와 동일한 순서로 이력을 붙인 뒤 `build_feature_frame` 을 통과시켜야
합니다. 파생 경로를 우회해 원본 컬럼만 보면 `features.py` 가 채우는 기본값
폴백을 놓칩니다.

사용법:
    uv run python scripts/audit_thng_feature_values.py
    uv run python scripts/audit_thng_feature_values.py --category Servc --rows 200000
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

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.ml.features import (  # noqa: E402
    CATEGORICAL_FEATURES,
    MISSING_CATEGORY,
    build_feature_frame,
)
from src.ml.institution_history import attach_institution_history  # noqa: E402
from src.ml.repeat_history import attach_repeat_history  # noqa: E402
from src.ml.trainer import training_features_for_category  # noqa: E402

# 고유값이 이 수 이하이면 모델이 쓸 수 있는 분해능이 사실상 없다고 봅니다.
DEGENERATE_UNIQUE_MAX = 1

# 한 값이 이 비율 이상을 차지하면 나머지가 잡음 수준이라 봅니다.
DOMINANT_SHARE_FLOOR = 0.999


def load_frame(parquet: Path, category: str, rows: int | None) -> pd.DataFrame:
    """학습기와 같은 순서로 이력을 붙인 학습 프레임을 만듭니다."""
    df = pd.read_parquet(parquet)
    if rows is not None and rows < len(df):
        # 앞에서 자르면 연도가 치우치므로 시간순 균등 추출을 씁니다.
        step = len(df) // rows
        df = df.iloc[::step].head(rows).copy()
    df["category"] = category
    df = attach_institution_history(df)
    df = attach_repeat_history(df)
    return df


def audit(df: pd.DataFrame, features: list[str]) -> pd.DataFrame:
    """특징별 결측률, 고유값 수, 최빈값 점유율과 판정을 표로 냅니다."""
    records = df.to_dict(orient="records")
    frame = pd.DataFrame(build_feature_frame(records))

    rows = []
    for name in features:
        if name not in frame.columns:
            rows.append(
                {
                    "특징": name,
                    "종류": "누락",
                    "결측률": np.nan,
                    "고유값수": 0,
                    "최빈값": "",
                    "최빈점유율": np.nan,
                    "판정": "특징 미생성",
                }
            )
            continue

        column = frame[name]
        kind = "범주" if name in CATEGORICAL_FEATURES else "수치"

        if kind == "범주":
            text = column.astype("string")
            missing = float((text.isna() | (text == MISSING_CATEGORY)).mean())
            counts = text.value_counts(dropna=False)
        else:
            numeric = pd.to_numeric(column, errors="coerce")
            missing = float(numeric.isna().mean())
            counts = numeric.value_counts(dropna=False)

        unique = len(counts)
        top_value = counts.index[0] if unique else ""
        top_share = float(counts.iloc[0] / len(frame)) if unique else np.nan

        if unique <= DEGENERATE_UNIQUE_MAX:
            verdict = "상수"
        elif kind == "범주" and missing >= DOMINANT_SHARE_FLOOR:
            verdict = "항상 미상"
        elif top_share >= DOMINANT_SHARE_FLOOR:
            verdict = "사실상 상수"
        elif missing >= DOMINANT_SHARE_FLOOR:
            verdict = "항상 결측"
        else:
            verdict = "유효"

        rows.append(
            {
                "특징": name,
                "종류": kind,
                "결측률": round(missing, 4),
                "고유값수": unique,
                "최빈값": str(top_value)[:18],
                "최빈점유율": round(top_share, 4) if pd.notna(top_share) else np.nan,
                "판정": verdict,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--category", default="Thng")
    parser.add_argument("--parquet", default=None)
    parser.add_argument("--rows", type=int, default=None, help="표본 수. 미지정 시 전량")
    args = parser.parse_args()

    default_parquet = f"data/feature_store/dataset_{args.category}.parquet"
    path = Path(args.parquet or (PROJECT_ROOT / default_parquet))
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    print(f"{args.category} 학습 프레임 구성 중: {path}")
    df = load_frame(path, args.category, args.rows)
    print(f"  {len(df):,}행 x {len(df.columns)}컬럼 (이력 부착 후)")

    features = training_features_for_category(args.category)
    print(f"  학습 특징 {len(features)}개\n")

    table = audit(df, features)
    print(f"{'=' * 92}\n특징별 값 감사\n{'=' * 92}")
    print(table.to_string(index=False))

    dead = table[table["판정"] != "유효"]
    print(f"\n{'=' * 92}\n판정\n{'=' * 92}")
    if dead.empty:
        print("모든 학습 특징이 유효한 분산을 가집니다.")
        return 0

    print(f"정보가 없는 특징 {len(dead)}/{len(table)}개:")
    print(dead[["특징", "종류", "판정", "최빈값"]].to_string(index=False))
    print(
        "\n이 특징들은 트리 분기에 쓰일 수 없습니다. 학습 특징 수를 세면 포함되지만"
        " 모델이 실제로 읽는 신호는 그만큼 적습니다."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
