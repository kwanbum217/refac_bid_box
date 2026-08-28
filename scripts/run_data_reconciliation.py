#!/usr/bin/env python3
"""
scripts/run_data_reconciliation.py

DB 적재 이후 하류 동기화(파생 집계, ChromaDB KB 색인, Meilisearch 색인, 정합성 검사)를
정해진 순서로 실행하고, DB와 KB 및 검색 색인의 정합성 차집합을 검사하는 상위 오케스트레이션 진입점입니다.

실행 순서:
    1. 파생 집계 (rebuild_institution_stats, rebuild_ranking_snapshots)
    2. ChromaDB KB 색인 (rebuild_knowledge_base)
    3. Meilisearch 색인 (sync_search_index)
    4. 정합성 검사 (verify_reconciliation: DB vs ChromaDB vs Meilisearch)

실패 시 즉시 중단(fail-closed)하고 종료 코드 1로 끝납니다.
정합성 검사에서 차집합이 0이 아니면 누락 건수와 예시 식별자를 출력하고 종료 코드 1로 끝납니다.
전 단계와 정합성 검사가 모두 통과했을 때만 종료 코드 0으로 끝납니다.

사용법:
    python scripts/run_data_reconciliation.py --since 20260827
    python scripts/run_data_reconciliation.py --since-hours 24
    python scripts/run_data_reconciliation.py --since 20260827 --dry-run
"""

from __future__ import annotations

import argparse
import re
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.app.core.config import settings  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.core.timeutil import utcnow  # noqa: E402
from src.app.models.bids import BidResult  # noqa: E402
from src.app.services.kb_builder import rebuild_knowledge_base  # noqa: E402
from src.app.services.ranking_snapshots import rebuild_ranking_snapshots  # noqa: E402
from src.app.services.search_index import (  # noqa: E402
    INDEX_UID,
    MeiliSearchClient,
    sync_search_index,
)
from src.ml.institution_history import rebuild_institution_stats  # noqa: E402

STAGE_DERIVED_AGGREGATES = "derived_aggregates"
STAGE_CHROMADB_KB = "chromadb_kb"
STAGE_MEILISEARCH_INDEX = "meilisearch_index"
STAGE_CONSISTENCY_CHECK = "consistency_check"

STAGE_ORDER = [
    STAGE_DERIVED_AGGREGATES,
    STAGE_CHROMADB_KB,
    STAGE_MEILISEARCH_INDEX,
    STAGE_CONSISTENCY_CHECK,
]

STAGE_DESCRIPTIONS = {
    STAGE_DERIVED_AGGREGATES: "파생 집계 (기관별 통계 및 순위 스냅샷)",
    STAGE_CHROMADB_KB: "ChromaDB KB 색인",
    STAGE_MEILISEARCH_INDEX: "Meilisearch 검색 색인 동기화",
    STAGE_CONSISTENCY_CHECK: "정합성 검사 (DB vs KB vs 검색색인)",
}


def parse_date_or_datetime(value: str | None) -> datetime | None:
    """YYYYMMDD, YYYY-MM-DD, 또는 ISO datetime 문자열을 파싱합니다."""
    if not value:
        return None
    val_str = str(value).strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(val_str, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(val_str)
    except ValueError as exc:
        raise ValueError(f"유효하지 않은 날짜/시각 형식입니다: {value}") from exc


def get_db_result_notice_numbers(
    session: Session,
    *,
    collected_since: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> set[str]:
    """대상 구간 DB 낙찰결과 식별자(공고번호) 집합을 조회합니다."""
    stmt = select(BidResult.bid_ntce_no)
    if collected_since is not None:
        stmt = stmt.where(BidResult.collected_at >= collected_since)
    elif start_date is not None:
        stmt = stmt.where(
            BidResult.rl_openg_dt >= datetime.combine(start_date, datetime.min.time())
        )
        if end_date is not None:
            stmt = stmt.where(
                BidResult.rl_openg_dt <= datetime.combine(end_date, datetime.max.time())
            )
    rows = session.execute(stmt).scalars().all()
    return {str(r).strip() for r in rows if r}


def get_chroma_indexed_notice_numbers(
    client: Any | None = None,
    collection_name: str = "bidding_kb",
) -> set[str]:
    """ChromaDB bidding_kb 컬렉션에 색인된 공고번호 식별자 집합을 추출합니다."""
    try:
        import chromadb

        from src.rag.embeddings import get_collection

        if client is None:
            client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
        collection = get_collection(client, collection_name)
        stored_count = collection.count()
        if not stored_count:
            return set()

        notice_numbers: set[str] = set()
        batch_size = 10_000
        notice_pattern = re.compile(r"\[(?:공고번호|낙찰공고번호)\]\s*([0-9A-Za-z]+)")

        for offset in range(0, stored_count, batch_size):
            data = collection.get(
                include=["metadatas", "documents"], limit=batch_size, offset=offset
            )
            docs = data.get("documents") or []
            for doc in docs:
                match = notice_pattern.search(str(doc))
                if match:
                    notice_numbers.add(match.group(1).strip())
        return notice_numbers
    except Exception as exc:
        raise RuntimeError(f"ChromaDB 식별자 조회 실패: {exc}") from exc


def get_meilisearch_result_notice_numbers(client: Any | None = None) -> set[str]:
    """Meilisearch bid_records 인덱스에서 dataset='result'인 공고번호 식별자 집합을 추출합니다."""
    try:
        if client is None:
            client = MeiliSearchClient()
        offset = 0
        limit = 1_000
        notice_numbers: set[str] = set()
        while True:
            res = client._request(
                "POST",
                f"/indexes/{INDEX_UID}/search",
                json={
                    "q": "",
                    "filter": 'dataset = "result"',
                    "offset": offset,
                    "limit": limit,
                    "attributesToRetrieve": ["bid_ntce_no", "source_id"],
                },
            )
            hits = res.get("hits") or []
            for hit in hits:
                if hit.get("bid_ntce_no"):
                    notice_numbers.add(str(hit["bid_ntce_no"]).strip())
            if len(hits) < limit:
                break
            offset += len(hits)
        return notice_numbers
    except Exception as exc:
        raise RuntimeError(f"Meilisearch 식별자 조회 실패: {exc}") from exc


def verify_reconciliation(
    db: Session,
    *,
    collected_since: datetime | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    chroma_fetcher: Callable[[], set[str]] | None = None,
    meili_fetcher: Callable[[], set[str]] | None = None,
    db_fetcher: Callable[..., set[str]] | None = None,
) -> dict[str, Any]:
    """DB 낙찰결과 식별자 집합과 ChromaDB, Meilisearch 색인 식별자 집합의 차집합을 계산합니다."""
    if db_fetcher is not None:
        db_notice_nos = db_fetcher(
            db,
            collected_since=collected_since,
            start_date=start_date,
            end_date=end_date,
        )
    else:
        db_notice_nos = get_db_result_notice_numbers(
            db,
            collected_since=collected_since,
            start_date=start_date,
            end_date=end_date,
        )

    chroma_notice_nos = (
        chroma_fetcher() if chroma_fetcher is not None else get_chroma_indexed_notice_numbers()
    )
    meili_notice_nos = (
        meili_fetcher() if meili_fetcher is not None else get_meilisearch_result_notice_numbers()
    )

    diff_chroma = db_notice_nos - chroma_notice_nos
    diff_meili = db_notice_nos - meili_notice_nos

    passed = (len(diff_chroma) == 0) and (len(diff_meili) == 0)
    return {
        "passed": passed,
        "db_count": len(db_notice_nos),
        "chroma_count": len(chroma_notice_nos),
        "meili_count": len(meili_notice_nos),
        "missing_in_chroma": diff_chroma,
        "missing_in_meili": diff_meili,
    }


def execute_derived_aggregates(session: Session) -> dict[str, Any]:
    """1단계: 파생 집계 (기관별 통계 및 순위 스냅샷) 갱신."""
    inst_result = rebuild_institution_stats(session)
    session.commit()
    rank_result = rebuild_ranking_snapshots(session)
    session.commit()
    return {"institution_stats": inst_result, "ranking_snapshots": rank_result}


def execute_kb_indexing(db: Session, collected_since: datetime | None) -> dict[str, Any]:
    """2단계: ChromaDB KB 색인 갱신."""
    result = rebuild_knowledge_base(db, collected_since=collected_since)
    if result.get("status") != "success":
        raise RuntimeError(f"ChromaDB KB 색인 실패: {result.get('summary', '알 수 없는 오류')}")
    return result


def execute_meilisearch_indexing(db: Session, collected_since: datetime | None) -> dict[str, Any]:
    """3단계: Meilisearch 검색 색인 동기화."""
    return sync_search_index(db, collected_since=collected_since)


def execute_consistency_check(
    db: Session,
    collected_since: datetime | None,
    start_date: date | None = None,
    end_date: date | None = None,
    chroma_fetcher: Callable[[], set[str]] | None = None,
    meili_fetcher: Callable[[], set[str]] | None = None,
    db_fetcher: Callable[..., set[str]] | None = None,
) -> dict[str, Any]:
    """4단계: 정합성 차집합 검사."""
    result = verify_reconciliation(
        db,
        collected_since=collected_since,
        start_date=start_date,
        end_date=end_date,
        chroma_fetcher=chroma_fetcher,
        meili_fetcher=meili_fetcher,
        db_fetcher=db_fetcher,
    )
    if not result["passed"]:
        missing_chroma = result.get("missing_in_chroma", set())
        missing_meili = result.get("missing_in_meili", set())
        errors = []
        if missing_chroma:
            sample = sorted(missing_chroma)[:5]
            errors.append(f"ChromaDB 누락 {len(missing_chroma):,}건 (예시: {sample})")
        if missing_meili:
            sample = sorted(missing_meili)[:5]
            errors.append(f"Meilisearch 누락 {len(missing_meili):,}건 (예시: {sample})")
        raise RuntimeError("정합성 차집합 불일치 발견:\n  - " + "\n  - ".join(errors))
    return result


def run_reconciliation(
    *,
    since: str | None = None,
    until: str | None = None,
    since_hours: int | None = None,
    collected_since: datetime | None = None,
    dry_run: bool = False,
    session: Session | None = None,
    step_handlers: dict[str, Callable] | None = None,
    chroma_fetcher: Callable[[], set[str]] | None = None,
    meili_fetcher: Callable[[], set[str]] | None = None,
    db_fetcher: Callable[..., set[str]] | None = None,
) -> int:
    """하류 동기화 및 정합성 검사 오케스트레이션을 실행합니다.

    반환값:
        0: 전 단계 및 정합성 검사 통과
        1: 어느 한 단계라도 실패하거나 정합성 차집합이 비어 있지 않음
    """
    # 대상 구간 해석
    target_since: datetime | None = collected_since
    start_d: date | None = None
    end_d: date | None = None

    if since_hours is not None:
        target_since = utcnow() - timedelta(hours=since_hours)
    elif since is not None:
        try:
            target_since = parse_date_or_datetime(since)
            if target_since:
                start_d = target_since.date()
        except ValueError as exc:
            print(f"[FAIL] 시작 시각 파싱 실패: {exc}", file=sys.stderr)
            return 1

    if until is not None:
        try:
            until_dt = parse_date_or_datetime(until)
            if until_dt:
                end_d = until_dt.date()
        except ValueError as exc:
            print(f"[FAIL] 종료 시각 파싱 실패: {exc}", file=sys.stderr)
            return 1

    if target_since is None and start_d is None:
        print(
            "[FAIL] 대상 구간 지정이 필요합니다 (--since 또는 --since-hours). 전체 재색인은 기본 동작이 아닙니다.",
            file=sys.stderr,
        )
        return 1

    print("=" * 60)
    print("하류 데이터 동기화 및 정합성 검사 파이프라인")
    print(f"  기준 구간: collected_since={target_since}, start={start_d}, end={end_d}")
    print(f"  실행 모드: {'DRY-RUN' if dry_run else 'RUN'}")
    print("=" * 60)

    if dry_run:
        print("[DRY-RUN] 실행 계획:")
        for idx, stage in enumerate(STAGE_ORDER, 1):
            print(f"  {idx}. [{stage}] {STAGE_DESCRIPTIONS[stage]}")
        print("[DRY-RUN] 실제 단계를 실행하지 않고 정상 종료합니다.")
        return 0

    handlers = {
        STAGE_DERIVED_AGGREGATES: lambda db: execute_derived_aggregates(db),
        STAGE_CHROMADB_KB: lambda db: execute_kb_indexing(db, target_since),
        STAGE_MEILISEARCH_INDEX: lambda db: execute_meilisearch_indexing(db, target_since),
        STAGE_CONSISTENCY_CHECK: lambda db: execute_consistency_check(
            db,
            target_since,
            start_date=start_d,
            end_date=end_d,
            chroma_fetcher=chroma_fetcher,
            meili_fetcher=meili_fetcher,
            db_fetcher=db_fetcher,
        ),
    }
    if step_handlers:
        handlers.update(step_handlers)

    db_session = session or SessionLocal()
    try:
        for idx, stage_name in enumerate(STAGE_ORDER, 1):
            desc = STAGE_DESCRIPTIONS.get(stage_name, stage_name)
            print(f"\n[{idx}/4] {desc} 실행 중...")
            handler = handlers.get(stage_name)
            if handler is None:
                print(f"[FAIL] 단계 '{stage_name}'에 대한 핸들러가 없습니다.", file=sys.stderr)
                return 1
            try:
                outcome = handler(db_session)
                print(f"[{idx}/4] {stage_name} 완료: {outcome}")
            except Exception as exc:
                print(f"\n[FAIL] 단계 '{stage_name}' 실행 중 오류 발생: {exc}", file=sys.stderr)
                print(
                    "하류 동기화가 실패하여 이후 단계를 중단합니다 (fail-closed).", file=sys.stderr
                )
                return 1

        print("\n" + "=" * 60)
        print("[SUCCESS] 전 단계 및 정합성 검사 통과 (차집합 0건)")
        print("=" * 60)
        return 0
    finally:
        if session is None:
            db_session.close()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DB 적재 후 하류 동기화(파생 집계, KB 색인, 검색 색인, 정합성 검사) 오케스트레이션"
    )
    parser.add_argument(
        "--since",
        help="동기화 대상 시작일시 (YYYYMMDD, YYYY-MM-DD, 또는 ISO datetime)",
    )
    parser.add_argument(
        "--until",
        help="동기화 대상 종료일시 (YYYYMMDD, YYYY-MM-DD, 또는 ISO datetime)",
    )
    parser.add_argument(
        "--since-hours",
        type=int,
        help="최근 N시간 적재분만 동기화",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="실제 실행 없이 실행 계획만 출력",
    )
    args = parser.parse_args()

    return run_reconciliation(
        since=args.since,
        until=args.until,
        since_hours=args.since_hours,
        dry_run=args.dry_run,
    )


if __name__ == "__main__":
    sys.exit(main())
