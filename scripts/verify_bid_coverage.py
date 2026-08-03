#!/usr/bin/env python3
"""
입찰공고/낙찰정보의 연도별 적재 현황과 조인율을 보고합니다.

백필이 실제로 결손을 메웠는지 확인하는 용도입니다. 학습 특징의 가격 항목
(예정가격, 기초금액)은 공고에만 있으므로, 낙찰 행이 공고와 조인되지 않으면
가격 특징 없이 학습하게 됩니다. 조인율이 이 파이프라인의 실질 상한입니다.

사용법:
    python scripts/verify_bid_coverage.py
    python scripts/verify_bid_coverage.py --category Cnstwk --since 2015
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import text  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.services.api_collector import BID_CATEGORIES  # noqa: E402

YEARLY_SQL = text(
    """
    SELECT y, SUM(ann) AS ann, SUM(res) AS res FROM (
        SELECT YEAR(bid_ntce_dt) AS y, COUNT(*) AS ann, 0 AS res
        FROM bid_announcements
        WHERE category = :cat AND bid_ntce_dt IS NOT NULL
        GROUP BY YEAR(bid_ntce_dt)
        UNION ALL
        SELECT YEAR(rl_openg_dt) AS y, 0 AS ann, COUNT(*) AS res
        FROM bid_results
        WHERE category = :cat AND rl_openg_dt IS NOT NULL
        GROUP BY YEAR(rl_openg_dt)
    ) t
    WHERE y >= :since
    GROUP BY y ORDER BY y
    """
)

# 낙찰 행이 같은 공고와 이어지는 비율입니다. 학습 파이프라인의 실질 상한입니다.
# 차수는 공고가 3자리(000), 낙찰이 2자리(00) 로 내려오므로 반드시 맞춰야 합니다.
# src/ml/dataset.py 의 _normalized_ord 와 동일한 방식입니다.
JOIN_SQL = text(
    """
    SELECT COUNT(*) AS total,
           SUM(CASE WHEN a.id IS NOT NULL THEN 1 ELSE 0 END) AS joined,
           SUM(CASE WHEN a.presmpt_prce IS NOT NULL THEN 1 ELSE 0 END) AS with_price
    FROM bid_results r
    LEFT JOIN bid_announcements a
           ON a.bid_ntce_no = r.bid_ntce_no
          AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
          AND a.category = r.category
    WHERE r.category = :cat
    """
)

CONTRACT_SQL = text(
    """
    SELECT COUNT(*), SUM(CASE WHEN cntrct_mthd_nm IS NOT NULL THEN 1 ELSE 0 END)
    FROM bid_announcements WHERE category = :cat
    """
)


def _pct(part: int, whole: int) -> str:
    return f"{part / whole * 100:6.2f}%" if whole else "     -"


def main() -> int:
    parser = argparse.ArgumentParser(description="입찰 데이터 적재 현황 검증")
    parser.add_argument("--category", action="append", choices=list(BID_CATEGORIES))
    parser.add_argument("--since", type=int, default=2015, help="시작 연도")
    args = parser.parse_args()

    categories = args.category or list(BID_CATEGORIES)
    session = SessionLocal()
    try:
        for cat in categories:
            name = BID_CATEGORIES[cat]["name"]
            print(f"\n{'=' * 62}\n{cat} ({name})\n{'=' * 62}")

            print(f"{'연도':>6} {'공고':>12} {'낙찰':>12}")
            for year, raw_ann, raw_res in session.execute(
                YEARLY_SQL, {"cat": cat, "since": args.since}
            ):
                ann, res = int(raw_ann or 0), int(raw_res or 0)
                mark = "  <- 공고 결손" if res and ann * 2 < res else ""
                print(f"{year:>6} {ann:>12,} {res:>12,}{mark}")

            total, joined, with_price = session.execute(JOIN_SQL, {"cat": cat}).one()
            total, joined, with_price = int(total), int(joined or 0), int(with_price or 0)
            print(f"\n  낙찰 {total:,}건 중 공고 조인 {joined:,}건 ({_pct(joined, total)})")
            print(f"  그중 예정가격 보유 {with_price:,}건 ({_pct(with_price, total)})")

            ann_total, ann_contract = session.execute(CONTRACT_SQL, {"cat": cat}).one()
            ann_total, ann_contract = int(ann_total), int(ann_contract or 0)
            print(
                f"  공고 {ann_total:,}건 중 계약체결방법 보유 "
                f"{ann_contract:,}건 ({_pct(ann_contract, ann_total)})"
            )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
