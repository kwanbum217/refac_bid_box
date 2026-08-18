#!/usr/bin/env python3
"""운영 쌍대 표본에 **학습에서 잘라낸 구간**이 섞여 있는지 봅니다.

학습 데이터셋은 `build_training_dataset` 에서 낙찰률을
`[MIN_WINNING_RATE, MAX_WINNING_RATE]` 로 자릅니다. 그런데 운영 쌍대 표본은
`eval_servc_api_path.collect` 가 `sucsf_bid_rate > 0` 만 걸고 뽑습니다.

    학습    70 <= winning_rate <= 110
    평가    winning_rate > 0

**모델이 배우지 않은 구간에서 채점하고 있습니다.** MAE 는 이상치에 선형으로
반응하므로 소수의 행이 절대 수준과 쌍대 검정력을 함께 흔듭니다.

이 스크립트는 이미 저장된 쌍대 잔차 parquet 을 읽어 두 조건을 나란히 냅니다.
DB 접속도 모델 로드도 하지 않으므로 다른 작업과 자원을 다투지 않습니다.

사용법:
    .venv/bin/python scripts/audit_paired_sample_filter_gap.py
    .venv/bin/python scripts/audit_paired_sample_filter_gap.py --input-dir <경로>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.ml.dataset import MAX_WINNING_RATE, MIN_WINNING_RATE  # noqa: E402

# compare_servc_models_paired.py 와 같은 기준을 씁니다.
T_THRESHOLD = 2.0

DEFAULT_INPUT_DIR = PROJECT_ROOT / "data" / "analysis" / "servc_residuals"
REQUIRED_COLUMNS = ("actual", "base_err", "chal_err")


def paired_row(label: str, base: pd.Series, chal: pd.Series) -> dict:
    """쌍대 차이(challenger - base)의 평균, t, 최소 감지 차이를 냅니다."""
    diff = (chal - base).dropna()
    stderr = diff.std(ddof=1) / np.sqrt(len(diff))
    return {
        "조건": label,
        "n": len(diff),
        "base MAE": base.mean(),
        "chal MAE": chal.mean(),
        "평균차": diff.mean(),
        "t": diff.mean() / stderr if stderr else np.nan,
        "최소감지차": T_THRESHOLD * stderr,
    }


def audit(path: Path) -> pd.DataFrame | None:
    frame = pd.read_parquet(path)
    missing = [column for column in REQUIRED_COLUMNS if column not in frame.columns]
    if missing:
        print(f"  건너뜁니다. 쌍대 잔차 파일이 아닙니다 (없는 컬럼: {missing})")
        return None

    actual = pd.to_numeric(frame["actual"], errors="coerce")
    base = pd.to_numeric(frame["base_err"], errors="coerce")
    chal = pd.to_numeric(frame["chal_err"], errors="coerce")
    inside = actual.between(MIN_WINNING_RATE, MAX_WINNING_RATE)
    outside = ~inside

    count_out = int(outside.sum())
    print(
        f"  표본 {len(frame):,}건 / 학습 범위 밖 {count_out:,}건 ({count_out / len(frame) * 100:.3f}%)"
    )
    if count_out:
        print(f"    범위 밖 MAE       : {base[outside].mean():.4f}")
        print(f"    전체 MAE 기여     : {base[outside].sum() / len(base):.4f}")
        print(f"    범위 밖 실제값 예 : {sorted(actual[outside].round(2).tolist())[:8]}")

    rows = [
        paired_row("전량", base, chal),
        paired_row("범위 내", base[inside], chal[inside]),
    ]
    table = pd.DataFrame(rows)
    print(
        table.round({"base MAE": 4, "chal MAE": 4, "평균차": 5, "t": 2, "최소감지차": 5}).to_string(
            index=False
        )
    )

    verdicts = []
    for row in rows:
        if abs(row["t"]) < T_THRESHOLD:
            verdicts.append("판별 불가")
        else:
            verdicts.append("challenger 우세" if row["평균차"] < 0 else "base 우세")
    if verdicts[0] != verdicts[1]:
        print(f"    판정이 뒤집힙니다: 전량 '{verdicts[0]}' -> 범위 내 '{verdicts[1]}'")
    else:
        print(f"    판정 유지: {verdicts[0]}")
    return table


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", default=str(DEFAULT_INPUT_DIR))
    parser.add_argument("--pattern", default="paired_*.parquet")
    args = parser.parse_args()

    input_dir = Path(args.input_dir)
    if not input_dir.is_dir():
        print(f"입력 디렉터리가 없습니다: {input_dir}")
        return 1

    paths = sorted(input_dir.glob(args.pattern))
    if not paths:
        print(f"대상 파일이 없습니다: {input_dir}/{args.pattern}")
        return 1

    print(f"학습 낙찰률 범위: [{MIN_WINNING_RATE}, {MAX_WINNING_RATE}]")
    print(f"유의 판정 기준  : |t| >= {T_THRESHOLD}\n")
    for path in paths:
        print(f"== {path.name} ==")
        audit(path)
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
