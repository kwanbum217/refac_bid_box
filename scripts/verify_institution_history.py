"""
scripts/verify_institution_history.py

운영 DB 에서 기관별 낙찰률 이력 계산 결과를 샘플링해 검증합니다.
"""

from __future__ import annotations

import statistics
from datetime import datetime
from typing import Any

from sqlalchemy import text

from src.app.core.db import SessionLocal
from src.ml.institution_history import calculate_institution_win_rate


def sample_institutions(
    session: Any, category: str, reference_date: datetime, lookback_days: int = 365, limit: int = 10
):
    start_date = reference_date - __import__("datetime").timedelta(days=lookback_days)
    query = text("""
        SELECT dminstt_nm, COUNT(*) AS cnt
        FROM bid_results
        WHERE category = :category
          AND dminstt_nm IS NOT NULL
          AND dminstt_nm != ''
          AND rl_openg_dt < :ref_date
          AND rl_openg_dt >= :start_date
          AND sucsf_bid_rate > 0
          AND sucsf_bid_rate < 100
        GROUP BY dminstt_nm
        ORDER BY cnt DESC
        LIMIT :limit
    """)
    return (
        session.execute(
            query,
            {
                "category": category,
                "ref_date": reference_date,
                "start_date": start_date,
                "limit": limit,
            },
        )
        .mappings()
        .all()
    )


def category_distribution(
    session: Any,
    category: str,
    reference_date: datetime,
    lookback_days: int = 365,
    sample_size: int = 100,
):
    start_date = reference_date - __import__("datetime").timedelta(days=lookback_days)
    query = text("""
        SELECT dminstt_nm
        FROM bid_results
        WHERE category = :category
          AND dminstt_nm IS NOT NULL
          AND dminstt_nm != ''
          AND rl_openg_dt < :ref_date
          AND rl_openg_dt >= :start_date
          AND sucsf_bid_rate > 0
          AND sucsf_bid_rate < 100
        GROUP BY dminstt_nm
        HAVING COUNT(*) >= 5
        ORDER BY RAND()
        LIMIT :limit
    """)
    rows = (
        session.execute(
            query,
            {
                "category": category,
                "ref_date": reference_date,
                "start_date": start_date,
                "limit": sample_size,
            },
        )
        .mappings()
        .all()
    )

    rates = []
    for row in rows:
        rate = calculate_institution_win_rate(
            session,
            institution_name=row["dminstt_nm"],
            reference_date=reference_date,
            category=category,
            lookback_days=lookback_days,
            min_samples=5,
        )
        rates.append(rate)
    return rates


def main():
    reference_date = datetime(2025, 6, 1, 0, 0, 0)
    session = SessionLocal()

    print(f"Reference date: {reference_date}")
    print("=" * 60)

    for category in ("Thng", "Servc", "Cnstwk"):
        print(f"\n[Top 10 {category} institutions]")
        for row in sample_institutions(session, category, reference_date):
            inst = row["dminstt_nm"]
            rate = calculate_institution_win_rate(
                session,
                institution_name=inst,
                reference_date=reference_date,
                category=category,
                lookback_days=365,
                min_samples=5,
            )
            print(f"  {inst}: count={row['cnt']}, rate={rate:.4f}")

        rates = category_distribution(session, category, reference_date)
        if rates:
            print(f"\n[{category} rate distribution (n={len(rates)})]")
            print(f"  min={min(rates):.4f}, max={max(rates):.4f}")
            print(f"  mean={statistics.mean(rates):.4f}, median={statistics.median(rates):.4f}")
            print(f"  stdev={statistics.stdev(rates):.4f}")
        else:
            print(f"\n[{category}] no samples")

    session.close()


if __name__ == "__main__":
    main()
