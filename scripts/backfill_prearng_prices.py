#!/usr/bin/env python3
"""
scripts/backfill_prearng_prices.py

나라장터 개찰결과 예비가격 상세(용역) 소급 수집 스크립트.

기본은 dry-run 입니다. `--execute` 를 명시할 때만 실제 API 호출과 적재를 합니다.
API 창 상한이 약 1개월이라 --start/--end(YYYY-MM) 구간을 달력 월 단위로 쪼개
공고당 1행으로 집약해 `bid_prearng_prices` 에 `INSERT IGNORE` 로 멱등 적재합니다.

서비스 키 값은 로그·표준출력에 기록하지 않습니다.

실행:
    uv run python scripts/backfill_prearng_prices.py --start 2026-01 --end 2026-03
    uv run python scripts/backfill_prearng_prices.py --start 2026-01 --end 2026-03 --execute
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Sequence
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.prearng_prices import BidPrearngPrice  # noqa: E402
from src.app.services.api_collector import (  # noqa: E402
    RangeCollectionError,
    stream_servc_prearng_range,
)
from src.app.services.collector_service import _bulk_insert  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="개찰결과 예비가격 상세(용역) 소급 수집 (기본 dry-run)"
    )
    parser.add_argument("--start", required=True, help="시작 월 (YYYY-MM)")
    parser.add_argument("--end", required=True, help="종료 월 (YYYY-MM)")
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 API 호출과 적재를 수행합니다. 기본은 dry-run 입니다.",
    )
    return parser


async def _execute_range(start_month: str, end_month: str) -> int:
    session = SessionLocal()
    try:
        return await stream_servc_prearng_range(
            start_month,
            end_month,
            lambda rows: _bulk_insert(session, BidPrearngPrice, rows),
        )
    finally:
        session.close()


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    from src.app.services.api_collector import split_prearng_month_windows

    try:
        windows = split_prearng_month_windows(args.start, args.end)
    except ValueError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2

    print(f"대상 월 창 {len(windows)}개: {args.start} ~ {args.end}")
    for window_bgn, window_end in windows:
        print(f"  - {window_bgn} ~ {window_end}")

    if not args.execute:
        print("dry-run 입니다. 실제 호출·적재는 --execute 를 명시해야 수행합니다.")
        return 0

    try:
        saved = asyncio.run(_execute_range(args.start, args.end))
    except RangeCollectionError as exc:
        failed = ", ".join(f"{bgn}~{end}" for bgn, end in exc.failed_ranges)
        print(
            f"부분 실패: 적재 {exc.saved}건, 실패 창 {len(exc.failed_ranges)}개 ({failed})",
            file=sys.stderr,
        )
        return 1
    print(f"적재 완료: {saved}건")
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
