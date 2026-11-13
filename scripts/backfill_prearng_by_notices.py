#!/usr/bin/env python3
"""
scripts/backfill_prearng_by_notices.py

용역 예비가격 상세를 공고번호 단건 조회(inqryDiv=2)로 소급 수집하는 수동 스크립트.

월 단위 구간 소급(scripts/backfill_prearng_prices.py)이 나라장터에서
'[07] 입력범위값 초과' 로 거부될 때 씁니다. 개찰일 범위에서 예비가격 행이 아직
없는 용역 공고만 골라 호출 상한(--limit) 안에서 수집하고, 적재가 있으면
수요기관명 연결과 기관별 사정률 재집계를 이어서 실행합니다.

기본은 dry-run 입니다. `--execute` 를 명시할 때만 실제 API 호출과 적재를 합니다.

실행:
    python3 scripts/backfill_prearng_by_notices.py --since 2026-10-12
    python3 scripts/backfill_prearng_by_notices.py \
        --since 2026-10-12 --until 2026-11-10 --limit 2000 --execute
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections import Counter
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.core.timeutil import kst_today, utcnow  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.app.services.api_collector import (  # noqa: E402
    RangeCollectionError,
    stream_servc_prearng_by_notices,
)
from src.tasks.scheduled_tasks import (  # noqa: E402
    _persist_prearng_rows,
    _run_sajeong_stats_followup,
    select_new_servc_notices,
)

DEFAULT_LIMIT = 2000
MAX_LIMIT = 5000
CANDIDATE_POOL_LIMIT = 50_000
SAMPLE_SIZE = 10


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="용역 예비가격 상세 공고 단건 소급 수집 (기본 dry-run)"
    )
    parser.add_argument("--since", required=True, help="개찰일 시작 (YYYY-MM-DD)")
    parser.add_argument(
        "--until",
        default=None,
        help="개찰일 종료 (YYYY-MM-DD). 기본은 어제입니다.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"호출 상한. 기본 {DEFAULT_LIMIT}, 최대 {MAX_LIMIT}",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제 API 호출과 적재를 수행합니다. 기본은 dry-run 입니다.",
    )
    return parser


def select_backfill_candidates(
    db: Session,
    *,
    since: date,
    until: date,
    limit: int,
    excluded_out: list[int] | None = None,
) -> list[tuple[str, datetime]]:
    """일일 증분과 같은 후보 조건에 개찰일 범위와 정렬을 더합니다.

    후보 조건(용역, 예비가격 없음)은 일일 증분 `select_new_servc_notices` 를
    그대로 import 해 씁니다. 그 함수는 하한만 받으므로 상한과 최근순 정렬은
    돌려받은 공고번호에 개찰일 범위를 걸어 좁힙니다. 자료 없음으로 기록된
    공고를 빼는 것도 그 함수 안에서 함께 적용됩니다.
    """
    until_dt = datetime.combine(until, time.max)
    since_dt = datetime.combine(since, time.min)
    pool = select_new_servc_notices(
        db,
        now=until_dt,
        lookback_days=(until - since).days + 1,
        limit=CANDIDATE_POOL_LIMIT,
        excluded_out=excluded_out,
    )
    if not pool:
        return []
    if len(pool) >= CANDIDATE_POOL_LIMIT:
        print(
            f"경고: 후보 조회가 상한 {CANDIDATE_POOL_LIMIT}건에 걸렸습니다. "
            "범위를 나눠 실행하십시오.",
            file=sys.stderr,
        )

    stmt = (
        select(BidAnnouncement.bid_ntce_no, func.max(BidAnnouncement.openg_dt))
        .where(
            BidAnnouncement.category == "Servc",
            BidAnnouncement.bid_ntce_no.in_(pool),
            BidAnnouncement.openg_dt >= since_dt,
            BidAnnouncement.openg_dt <= until_dt,
        )
        .group_by(BidAnnouncement.bid_ntce_no)
        .order_by(func.max(BidAnnouncement.openg_dt).desc(), BidAnnouncement.bid_ntce_no)
        .limit(limit)
    )
    return [(row[0], row[1]) for row in db.execute(stmt).all() if row[0]]


async def _collect(notices: list[str]) -> tuple[int, list[str], dict[str, Any]]:
    """공고번호 단건 수집을 수행하고 실패 목록과 후속 집계 결과를 돌려줍니다."""
    try:
        saved = await stream_servc_prearng_by_notices(notices, _persist_prearng_rows)
        failed: list[str] = []
    except RangeCollectionError as exc:
        saved = exc.saved
        failed = [notice for notice, _ in exc.failed_ranges]

    followup = await _run_sajeong_stats_followup(saved) if saved >= 1 else {}
    return saved, failed, followup


def _print_distribution(candidates: list[tuple[str, datetime]]) -> None:
    counts = Counter(openg_dt.date() for _, openg_dt in candidates)
    print("개찰일별 분포:")
    for day in sorted(counts, reverse=True):
        print(f"  {day}: {counts[day]}건")


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise ValueError(f"{value} 는 YYYY-MM-DD 형식이 아닙니다.") from None


def run(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    try:
        since = _parse_date(args.since)
        until = _parse_date(args.until) if args.until else kst_today(utcnow()) - timedelta(days=1)
    except ValueError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2

    if since > until:
        print("입력 오류: --since 는 --until 보다 늦을 수 없습니다.", file=sys.stderr)
        return 2
    if not 1 <= args.limit <= MAX_LIMIT:
        print(f"입력 오류: --limit 은 1 이상 {MAX_LIMIT} 이하여야 합니다.", file=sys.stderr)
        return 2

    session = SessionLocal()
    excluded: list[int] = []
    try:
        candidates = select_backfill_candidates(
            session, since=since, until=until, limit=args.limit, excluded_out=excluded
        )
    finally:
        session.close()

    print(
        f"후보 공고 {len(candidates)}건 (개찰일 {since} ~ {until}, 상한 {args.limit}건), "
        f"자료 없음 제외 {excluded[0] if excluded else 0}건"
    )
    if not candidates:
        print("수집할 공고가 없습니다.")
        return 0

    _print_distribution(candidates)
    print(f"표본 {min(SAMPLE_SIZE, len(candidates))}건:")
    for notice, openg_dt in candidates[:SAMPLE_SIZE]:
        print(f"  {notice}  {openg_dt:%Y-%m-%d %H:%M}")

    if not args.execute:
        print("dry-run 입니다. 실제 호출·적재는 --execute 를 명시해야 수행합니다.")
        return 0

    notices = [notice for notice, _ in candidates]
    saved, failed, followup = asyncio.run(_collect(notices))
    print(f"적재 완료: {saved}건 (조회 {len(notices)}건)")
    if saved >= 1:
        print(
            "사정률 후속 단계: "
            f"수요기관명 연결 {followup.get('linked')}건, "
            f"기관별 사정률 재집계 {followup.get('stats_rebuilt')}"
        )
    if failed:
        print(f"실패 공고 {len(failed)}건:", file=sys.stderr)
        for notice in failed:
            print(f"  {notice}", file=sys.stderr)
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
