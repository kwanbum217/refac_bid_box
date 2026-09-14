"""입찰공고 면허제한정보·참가가능지역 기간 백필.

야간 수집은 2026-09-14 부터 신규 공고의 제한정보만 적재합니다. 그 전에 게시돼 아직 입찰 중인
공고는 화면에 제한 업종명이 비어 있으므로, 공고 게시일 구간을 월 단위로 끊어 채웁니다.
적재는 INSERT IGNORE 라 같은 구간을 다시 돌려도 행이 늘지 않고, 중단 뒤 --start 로 이어 갈 수 있습니다.

사용법:

    uv run python scripts/backfill_bid_restrictions.py --start 20250701 --end 20260914
    uv run python scripts/backfill_bid_restrictions.py --open-bids-since 20250701

--open-bids-since 는 마감 전 공고 중 그 날짜 이후 게시분의 최소 게시일을 시작일로, 오늘을 종료일로 씁니다.
"""

from __future__ import annotations

import argparse
import asyncio
import calendar
import json
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import func, select  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.core.timeutil import utcnow  # noqa: E402
from src.app.models.bid_restrictions import (  # noqa: E402
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.app.services.api_collector import (  # noqa: E402
    RangeCollectionError,
    get_service_key,
    mask_credentials,
    stream_bid_license_limits,
    stream_bid_participation_regions,
)
from src.app.services.collector_service import _bulk_insert  # noqa: E402


def month_windows(start: date, end: date) -> list[tuple[str, str]]:
    """[start, end] 를 달력 월 경계로 자릅니다. API 기간 상한(32일) 안에 들도록 한 달을 넘기지 않습니다."""
    if start > end:
        raise ValueError("start 가 end 보다 늦습니다.")
    windows = []
    cursor = start
    while cursor <= end:
        last_day = calendar.monthrange(cursor.year, cursor.month)[1]
        window_end = min(date(cursor.year, cursor.month, last_day), end)
        windows.append((cursor.strftime("%Y%m%d"), window_end.strftime("%Y%m%d")))
        cursor = window_end + timedelta(days=1)
    return windows


def _parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def open_bids_start(db, since: date) -> date | None:
    first = db.scalar(
        select(func.min(BidAnnouncement.bid_ntce_dt)).where(
            BidAnnouncement.bid_clse_dt >= utcnow(),
            BidAnnouncement.bid_ntce_dt >= datetime.combine(since, datetime.min.time()),
        )
    )
    return first.date() if first else None


async def backfill(start: date, end: date) -> dict:
    db = SessionLocal()
    report: dict = {"start": start.isoformat(), "end": end.isoformat(), "windows": []}
    try:
        for window_start, window_end in month_windows(start, end):
            row: dict = {"start": window_start, "end": window_end}
            for kind, stream, model in (
                ("license_limit", stream_bid_license_limits, BidAnnouncementLicenseLimit),
                (
                    "participation_region",
                    stream_bid_participation_regions,
                    BidAnnouncementParticipationRegion,
                ),
            ):
                started = time.perf_counter()
                try:
                    row[kind] = await stream(
                        window_start, window_end, lambda rows, m=model: _bulk_insert(db, m, rows)
                    )
                except RangeCollectionError as exc:
                    row[kind] = exc.saved
                    row[f"{kind}_failed_ranges"] = exc.failed_ranges
                except Exception as exc:
                    db.rollback()
                    row[f"{kind}_error"] = mask_credentials(exc)
                row[f"{kind}_seconds"] = round(time.perf_counter() - started, 2)
            report["windows"].append(row)
            print(json.dumps(row, ensure_ascii=False), flush=True)
        report["license_limit_rows"] = db.scalar(
            select(func.count()).select_from(BidAnnouncementLicenseLimit)
        )
        report["participation_region_rows"] = db.scalar(
            select(func.count()).select_from(BidAnnouncementParticipationRegion)
        )
        return report
    finally:
        db.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--start", help="게시일 시작 YYYYMMDD")
    parser.add_argument("--end", help="게시일 종료 YYYYMMDD (기본: 오늘)")
    parser.add_argument(
        "--open-bids-since", help="마감 전 공고 중 이 날짜 이후 게시분부터 채웁니다"
    )
    args = parser.parse_args(argv)
    load_dotenv(PROJECT_ROOT / ".env")

    if not get_service_key():
        print("G2B serviceKey 가 없어 백필할 수 없습니다.", file=sys.stderr)
        return 2
    end = _parse_day(args.end) if args.end else date.today()
    if args.open_bids_since:
        db = SessionLocal()
        try:
            start = open_bids_start(db, _parse_day(args.open_bids_since))
        finally:
            db.close()
        if start is None:
            print("대상 공고가 없습니다.")
            return 0
    elif args.start:
        start = _parse_day(args.start)
    else:
        parser.error("--start 또는 --open-bids-since 가 필요합니다.")

    report = asyncio.run(backfill(start, end))
    failed = [
        w for w in report["windows"] if any(k.endswith(("_error", "_failed_ranges")) for k in w)
    ]
    print(json.dumps({k: v for k, v in report.items() if k != "windows"}, ensure_ascii=False))
    if failed:
        print(
            f"실패 구간 {len(failed)}개. 같은 명령을 --start 로 다시 실행하십시오.", file=sys.stderr
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
