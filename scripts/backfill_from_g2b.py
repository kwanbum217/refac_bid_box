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

from src.app.core.timeutil import utcnow

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

# 한 번의 collect_bids 호출이 담당하는 기간입니다.
# api_collector 가 이 기간을 15일 구간으로 쪼개 MAX_CONCURRENT(16) 개씩 병렬 요청하므로,
# 15일로 두면 구간이 1개뿐이라 동시성이 전혀 쓰이지 않습니다. 16배로 잡아
# 매 호출마다 16개 구간이 동시에 나가게 합니다. 수신 즉시 적재하고 버려
# 메모리는 구간 수에 비례한 상한 안에서 유지됩니다.
CHUNK_DAYS = 15 * 16


def _latest(session, model, column, category: str) -> date | None:
    value = session.scalar(select(func.max(column)).where(model.category == category))
    return value.date() if value else None


def _chunks(start: date, end: date):
    current = start
    while current <= end:
        chunk_end = min(current + timedelta(days=CHUNK_DAYS - 1), end)
        yield current, chunk_end
        current = chunk_end + timedelta(days=1)


async def _backfill(
    categories: list[str],
    since: str | None,
    dry_run: bool,
    *,
    until: str | None = None,
    fetch_types: tuple[str, ...] = ("announce", "result"),
) -> int:
    today = utcnow().date()
    session = SessionLocal()
    total_announcements = 0
    total_results = 0
    try:
        for category in categories:
            for fetch_type, model, column in (
                ("announce", BidAnnouncement, BidAnnouncement.bid_ntce_dt),
                ("result", BidResult, BidResult.rl_openg_dt),
            ):
                if fetch_type not in fetch_types:
                    continue

                if since:
                    start = datetime.strptime(since, "%Y%m%d").date()
                else:
                    latest = _latest(session, model, column, category)
                    start = (latest + timedelta(days=1)) if latest else today - timedelta(days=30)

                # 과거 결손 구간을 메우려면 종료일을 직접 지정합니다.
                # 지정이 없으면 기존처럼 오늘까지 채웁니다.
                finish = datetime.strptime(until, "%Y%m%d").date() if until else today

                if start > finish:
                    print(f"[{category}/{fetch_type}] 공백 없음 (최신 {start - timedelta(days=1)})")
                    continue

                span = (finish - start).days + 1
                print(f"[{category}/{fetch_type}] {start} ~ {finish} ({span}일) 수집 시작")
                if dry_run:
                    continue

                for chunk_start, chunk_end in _chunks(start, finish):
                    metrics = await collect_bids(
                        session,
                        start_date=chunk_start.strftime("%Y%m%d"),
                        end_date=chunk_end.strftime("%Y%m%d"),
                        fetch_type=fetch_type,
                        categories=(category,),
                        # 덩어리마다 집계를 다시 만들면 수집보다 집계가 오래 걸립니다.
                        # 아래에서 전체가 끝난 뒤 한 번만 수행합니다.
                        refresh_aggregates=False,
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
        if not dry_run and (total_announcements or total_results):
            print("대시보드 집계 재생성 중...", flush=True)
            _refresh_aggregates(session, fetch_types)
    finally:
        session.close()

    print("-" * 60)
    print(f"백필 완료: 공고 {total_announcements:,}건, 낙찰 {total_results:,}건 신규 적재")

    if total_announcements or total_results:
        # 이 스크립트는 DB 적재와 대시보드 집계까지만 합니다. 야간 파이프라인이
        # 이어서 하는 KB 색인, 검색 색인, 파생 집계는 하지 않습니다. 2026-08-27 에
        # 이를 빠뜨려 낙찰 결과 9,798건이 DB 에만 있고 KB 에 없는 상태가 됐고,
        # 챗봇이 해당 공고의 낙찰 정보를 답하지 못했습니다.
        # docs/analysis/llm_generalization_judgment_20260827.md 6장.
        print("")
        print("주의: 이 스크립트는 KB·검색 색인과 파생 집계를 갱신하지 않습니다.")
        print("      아래를 이어서 수행하지 않으면 챗봇과 검색이 신규분을 보지 못합니다.")
        print(
            "      - ChromaDB KB 색인: rebuild_knowledge_base(db, collected_since=<백필 시작 시각>)"
        )
        print("      - Meilisearch 색인: 검색 색인 갱신 경로")
        print("      - 파생 집계: _rebuild_institution_stats(), _rebuild_ranking_snapshots()")
    return 0


def _refresh_aggregates(session, fetch_types: tuple[str, ...]) -> None:
    """수집이 전부 끝난 뒤 한 번만 집계를 다시 만듭니다."""
    from src.app.models.bids import DATASET_ANNOUNCEMENT, DATASET_RESULT
    from src.app.services.dashboard import (
        rebuild_bid_dataset_summaries,
        warm_dashboard_stats_cache,
    )
    from src.app.services.home_context import warm_home_page_cache

    datasets = []
    if "announce" in fetch_types:
        datasets.append(DATASET_ANNOUNCEMENT)
    if "result" in fetch_types:
        datasets.append(DATASET_RESULT)
    try:
        rebuild_bid_dataset_summaries(session, datasets)
        warm_dashboard_stats_cache(session)
        warm_home_page_cache(session)
    except Exception as exc:
        print(f"  집계 재생성 실패 (적재 자체는 완료됨): {exc}")


def main() -> int:
    parser = argparse.ArgumentParser(description="G2B API 로 데이터 공백 백필")
    parser.add_argument("--category", action="append", choices=list(BID_CATEGORIES))
    parser.add_argument("--since", help="시작일 강제 지정 (YYYYMMDD)")
    parser.add_argument("--until", help="종료일 지정 (YYYYMMDD). 과거 결손 구간 복구용")
    parser.add_argument(
        "--fetch-type",
        action="append",
        choices=["announce", "result"],
        help="수집 대상. 지정하지 않으면 둘 다",
    )
    parser.add_argument("--dry-run", action="store_true", help="수집 구간만 출력")
    args = parser.parse_args()

    if not get_service_key():
        print("FAIL: G2B serviceKey 가 설정되지 않았습니다 (.env 확인)")
        return 1

    categories = args.category or list(BID_CATEGORIES)
    fetch_types = tuple(args.fetch_type or ("announce", "result"))
    return asyncio.run(
        _backfill(
            categories,
            args.since,
            args.dry_run,
            until=args.until,
            fetch_types=fetch_types,
        )
    )


if __name__ == "__main__":
    sys.exit(main())
