#!/usr/bin/env python3
"""
parquet 복원으로 메워지지 않은 구간을 G2B API 로 재수집합니다.

parquet 덤프는 카테고리별로 절단 시점이 달라 공백이 남아 있습니다.
본 스크립트는 카테고리별 최신 적재일 이후부터 오늘까지를 15일 단위로 수집합니다.

사용법:
    python scripts/backfill_from_g2b.py
    python scripts/backfill_from_g2b.py --category Cnstwk --category Servc
    python scripts/backfill_from_g2b.py --since 20260301 --dry-run
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import func, select  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement, BidResult  # noqa: E402
from src.app.services.api_collector import BID_CATEGORIES, get_service_key  # noqa: E402
from src.app.services.collector_service import collect_bids  # noqa: E402

CHUNK_DAYS = 15


def _latest(session, model, column, category: str) -> date | None:
    value = session.scalar(select(func.max(column)).where(model.category == category))
    return value.date() if value else None


def _chunks(start: date, end: date):
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


async def _backfill(categories: list[str], since: str | None, dry_run: bool) -> int:
    today = datetime.utcnow().date()
    session = SessionLocal()
    total_announcements = 0
    total_results = 0
    try:
        for category in categories:
            for fetch_type, model, column in (
                ("announce", BidAnnouncement, BidAnnouncement.bid_ntce_dt),
                ("result", BidResult, BidResult.rl_openg_dt),
            ):
                if since:
                    start = datetime.strptime(since, "%Y%m%d").date()
                else:
                    latest = _latest(session, model, column, category)
                    start = (latest + timedelta(days=1)) if latest else today - timedelta(days=30)

                if start > today:
                    print(f"[{category}/{fetch_type}] 공백 없음 (최신 {start - timedelta(days=1)})")
                    continue

                span = (today - start).days + 1
                print(f"[{category}/{fetch_type}] {start} ~ {today} ({span}일) 수집 시작")
                if dry_run:
                    continue

                for chunk_start, chunk_end in _chunks(start, today):
                    metrics = await collect_bids(
                        session,
                        start_date=chunk_start.strftime("%Y%m%d"),
                        end_date=chunk_end.strftime("%Y%m%d"),
                        fetch_type=fetch_type,
                        categories=(category,),
                    )
                    if metrics.get("status") == "error":
                        print(f"  중단: {metrics.get('message')}")
                        return 1
                    total_announcements += metrics["announcement_count"]
                    total_results += metrics["result_count"]
                    print(
                        f"  {chunk_start}~{chunk_end}: "
                        f"공고 {metrics['announcement_count']:,} / 낙찰 {metrics['result_count']:,}"
                        f"  (누적 공고 {total_announcements:,} / 낙찰 {total_results:,})",
                        flush=True,
                    )
    finally:
        session.close()

    print("-" * 60)
    print(f"백필 완료: 공고 {total_announcements:,}건, 낙찰 {total_results:,}건 신규 적재")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="G2B API 로 데이터 공백 백필")
    parser.add_argument("--category", action="append", choices=list(BID_CATEGORIES))
    parser.add_argument("--since", help="시작일 강제 지정 (YYYYMMDD)")
    parser.add_argument("--dry-run", action="store_true", help="수집 구간만 출력")
    args = parser.parse_args()

    if not get_service_key():
        print("FAIL: G2B serviceKey 가 설정되지 않았습니다 (.env 확인)")
        return 1

    categories = args.category or list(BID_CATEGORIES)
    return asyncio.run(_backfill(categories, args.since, args.dry_run))


if __name__ == "__main__":
    sys.exit(main())
