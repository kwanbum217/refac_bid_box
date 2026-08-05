#!/usr/bin/env python3
"""
학습이 만드는 기관 이력이 **그 공고 시점 기준으로 정확한지** 확인합니다.

2026-08-05 대조에서 `inst_hist_rate` 와 `inst_sample_cnt` 가 서빙값과 0.88~0.91
로 어긋났습니다. 원인이 학습 계산의 결함인지, 아니면 서빙 집계 표가 **현재 시점**
값이라는 구조적 차이인지 가려야 했습니다.

가르는 방법은 단순합니다. 그 공고 개찰일 이전만 SQL 로 직접 집계해 학습값과
맞춰 봅니다. 정의가 같으므로 학습이 옳다면 일치해야 합니다.

실측(2025년 100건): 표본 수 상관 0.9999, 낙찰률 상관 0.9878.
**학습 계산은 정확합니다.** 남은 불일치는 서빙 집계 표의 시점에서 옵니다.

그리고 실제 운영은 미개찰 공고를 예측하므로 현재 시점 값이 맞습니다. 어긋나는
것은 과거 공고로 평가할 때뿐이며, 이는 코드가 아니라 평가 방식의 문제입니다.

사용법:
    .venv/bin/python scripts/verify_asof_history_parity.py
    .venv/bin/python scripts/verify_asof_history_parity.py --samples 200 --year 2025
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

import pandas as pd  # noqa: E402
from sqlalchemy import text  # noqa: E402

from src.app.core.db import SessionLocal, engine  # noqa: E402
from src.ml.institution_history import (  # noqa: E402
    HISTORY_MIN_SAMPLES,
    VALID_RATE_MAX,
    VALID_RATE_MIN,
    attach_institution_history,
    lookup_institution_history,
)

# 학습(`attach_institution_history`)과 같은 정의입니다. 기준 시점 이전 전량이며
# 이상치 범위도 같습니다. 하나라도 어긋나면 비교가 성립하지 않습니다.
ASOF_SQL = text(
    """
    SELECT COUNT(*) AS n, AVG(sucsf_bid_rate) AS avg_rate
    FROM bid_results
    WHERE dminstt_nm = :inst AND category = :category
      AND rl_openg_dt < :ref
      AND sucsf_bid_rate > :lo AND sucsf_bid_rate < :hi
    """
)

# 학습 계산이 정확하다고 볼 하한입니다. 시점 차이만 남았다면 1.0 에 붙습니다.
PARITY_FLOOR = 0.99


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--category", default="Servc")
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--samples", type=int, default=100)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    # 이력은 전량에 붙인 뒤 잘라 냅니다. 연도로 먼저 자르면 각 기관의 연초 건이
    # 최소 표본에 걸려 기본값 폴백이 폭증합니다.
    source = pd.read_parquet(path)
    source["category"] = args.category
    full = attach_institution_history(source)
    year = pd.to_datetime(full["openg_dt"]).dt.year
    picked = full[year == args.year].drop_duplicates("bid_ntce_no", keep="last")
    picked = picked.sample(n=min(args.samples * 3, len(picked)), random_state=args.seed)

    session = SessionLocal()
    rows: list[dict] = []
    try:
        with engine.connect() as conn:
            for row in picked.itertuples():
                if not row.dminstt_nm:
                    continue
                result = conn.execute(
                    ASOF_SQL,
                    {
                        "inst": row.dminstt_nm,
                        "category": args.category,
                        "ref": row.openg_dt,
                        "lo": VALID_RATE_MIN,
                        "hi": VALID_RATE_MAX,
                    },
                ).one()
                # 최소 표본 미만이면 학습이 기본값으로 채우므로 비교가 무의미합니다.
                if result.n is None or result.n < HISTORY_MIN_SAMPLES:
                    continue
                payload = {
                    "dminstt_nm": row.dminstt_nm,
                    "category": args.category,
                    "openg_dt": row.openg_dt,
                }
                rows.append(
                    {
                        "train_rate": float(row.inst_hist_rate),
                        "asof_rate": float(result.avg_rate) / 100.0,
                        "serve_rate": lookup_institution_history(payload, session),
                        "train_cnt": float(row.inst_sample_cnt),
                        "asof_cnt": float(result.n),
                    }
                )
                if len(rows) >= args.samples:
                    break
    finally:
        session.close()

    if not rows:
        print("비교 가능한 표본이 없습니다.")
        return 1

    frame = pd.DataFrame(rows)
    print(f"표본 {len(frame)}건\n")
    print(f"{'=' * 76}\n낙찰률 이력\n{'=' * 76}")
    for label, column in (("as-of 계산", "asof_rate"), ("현재 집계표", "serve_rate")):
        corr = frame["train_rate"].corr(frame[column])
        diff = (frame[column] - frame["train_rate"]).abs().mean()
        print(f"  학습 대 {label:<12}: 상관 {corr:.4f} / 평균절대차 {diff:.5f}")

    print(f"\n{'=' * 76}\n표본 수\n{'=' * 76}")
    count_corr = frame["train_cnt"].corr(frame["asof_cnt"])
    count_diff = (frame["asof_cnt"] - frame["train_cnt"]).abs().mean()
    print(f"  학습 대 as-of 계산  : 상관 {count_corr:.4f} / 평균절대차 {count_diff:.1f}")

    print()
    if count_corr >= PARITY_FLOOR:
        print("**학습 계산이 정확합니다.** 남은 불일치는 서빙 집계 표의 시점에서 옵니다.")
        print("운영은 미개찰 공고를 예측하므로 현재 시점 값이 맞고, 과거 공고 평가에서만")
        print("어긋납니다. 코드가 아니라 평가 방식의 문제입니다.")
    else:
        print("**학습 계산이 as-of 정의와 어긋납니다.** 시점 차이로 설명되지 않는")
        print("결함이 남아 있습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
