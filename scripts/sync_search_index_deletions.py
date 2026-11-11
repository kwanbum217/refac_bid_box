#!/usr/bin/env python3
"""
scripts/sync_search_index_deletions.py

Meilisearch 색인에는 남아 있지만 MySQL 원본에서 사라진 공고·낙찰 문서를 찾아 지웁니다.

색인은 upsert 만 하므로 원본에서 삭제된 행의 문서가 그대로 남습니다. 남은 문서는
목록·검색에 계속 노출되며, 야간 건수 대조는 이 차이를 불일치로만 보고합니다
(건수 대조는 scripts/sync_search_index.py 로 다시 채우는 누락도 함께 감지합니다).
색인은 MySQL 에서 다시 만들 수 있는 파생 읽기 모델이지만, 삭제를 되돌리려면 전체
재색인(약 45분)이 필요하므로 자동 삭제 경로는 두지 않습니다. 이 스크립트는 사람이
직접 실행하는 수동 도구이며 기본값은 dry-run 입니다.

사용법:
    python3 scripts/sync_search_index_deletions.py
    python3 scripts/sync_search_index_deletions.py --execute
    python3 scripts/sync_search_index_deletions.py --execute --max-ratio 0.05

종료 코드:
    0  정상 (dry-run 포함)
    1  오류
    2  삭제 후보가 상한(--max-ratio, 기본 1%)을 넘어 거부
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import select, tuple_  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement, BidResult  # noqa: E402
from src.app.services.search_index import (  # noqa: E402
    DOCUMENT_ID_BATCH_SIZE,
    SYNC_BATCH_SIZE,
    MeiliSearchClient,
)

DATASET_ANNOUNCEMENT = "announcement"
DATASET_RESULT = "result"
DATASETS = (DATASET_ANNOUNCEMENT, DATASET_RESULT)

DEFAULT_MAX_DELETE_RATIO = 0.01
SAMPLE_SIZE = 20

EXIT_OK = 0
EXIT_ERROR = 1
EXIT_RATIO_EXCEEDED = 2


def parse_announcement_document_id(document_id: str) -> tuple[str, str] | None:
    """`announcement_{category}_{bid_ntce_no}` 를 (bid_ntce_no, category) 로 읽습니다.

    공고 문서의 안정 ID 는 원본 PK 가 아니라 업무구분+공고번호이므로, 존재 판정도
    같은 조합으로 해야 차수가 늘어난 공고를 삭제 후보로 잘못 넣지 않습니다.
    """
    parts = document_id.split("_", 2)
    if len(parts) != 3 or parts[0] != DATASET_ANNOUNCEMENT:
        return None
    _, category, bid_ntce_no = parts
    if not category or not bid_ntce_no:
        return None
    return bid_ntce_no, category


def parse_result_document_id(document_id: str) -> int | None:
    """`result_{row.id}` 를 원본 PK 로 읽습니다."""
    prefix, separator, remainder = document_id.partition("_")
    if prefix != DATASET_RESULT or not separator or not remainder.isdigit():
        return None
    return int(remainder)


def _existing_announcement_pairs(db: Session, pairs: list[tuple[str, str]]) -> set[tuple[str, str]]:
    """(bid_ntce_no, category) 조합이 원본에 있는지 배치 IN 질의로 확인합니다."""
    found: set[tuple[str, str]] = set()
    for start in range(0, len(pairs), SYNC_BATCH_SIZE):
        chunk = pairs[start : start + SYNC_BATCH_SIZE]
        rows = db.execute(
            select(BidAnnouncement.bid_ntce_no, BidAnnouncement.category).where(
                tuple_(BidAnnouncement.bid_ntce_no, BidAnnouncement.category).in_(chunk)
            )
        ).all()
        found.update((bid_ntce_no, category) for bid_ntce_no, category in rows)
    return found


def _existing_result_ids(db: Session, ids: list[int]) -> set[int]:
    found: set[int] = set()
    for start in range(0, len(ids), SYNC_BATCH_SIZE):
        chunk = ids[start : start + SYNC_BATCH_SIZE]
        rows = db.execute(select(BidResult.id).where(BidResult.id.in_(chunk))).scalars().all()
        found.update(int(row) for row in rows)
    return found


def stale_ids_in_batch(db: Session, dataset: str, document_ids: list[str]) -> list[str]:
    """색인 문서 id 중 원본에 대응 행이 없는 것만 남깁니다."""
    if dataset == DATASET_ANNOUNCEMENT:
        parsed = {
            document_id: parse_announcement_document_id(document_id) for document_id in document_ids
        }
        known = [key for key in parsed.values() if key is not None]
        existing = _existing_announcement_pairs(db, known)
        return [
            document_id for document_id, key in parsed.items() if key is None or key not in existing
        ]

    parsed_ids = {
        document_id: parse_result_document_id(document_id) for document_id in document_ids
    }
    known_ids = [value for value in parsed_ids.values() if value is not None]
    existing_ids = _existing_result_ids(db, known_ids)
    return [
        document_id
        for document_id, value in parsed_ids.items()
        if value is None or value not in existing_ids
    ]


def collect_stale_document_ids(
    db: Session,
    client: MeiliSearchClient,
    dataset: str,
    *,
    index_batch_size: int = DOCUMENT_ID_BATCH_SIZE,
    db_batch_size: int = SYNC_BATCH_SIZE,
) -> tuple[list[str], int]:
    """색인 id 를 끝까지 순회하며 원본에 없는 문서 id 와 색인 총 건수를 돌려줍니다.

    색인 문서를 모두 메모리에 들고 있지 않도록 DB 확인은 배치 단위로 끊어서 합니다.
    """
    stale: list[str] = []
    total = 0
    pending: list[str] = []
    for document_id in client.iter_document_ids(dataset, batch_size=index_batch_size):
        total += 1
        pending.append(document_id)
        if len(pending) >= db_batch_size:
            stale.extend(stale_ids_in_batch(db, dataset, pending))
            pending = []
    if pending:
        stale.extend(stale_ids_in_batch(db, dataset, pending))
    return stale, total


def _format_ratio(value: float) -> str:
    return f"{value * 100:.2f}%"


def _exceeds_ratio(total: int, candidate_count: int, max_ratio: float) -> bool:
    """후보 수가 색인 건수 대비 상한을 넘는지 판정합니다.

    상한에 정확히 걸린 경우는 허용합니다. 부동소수 오차로 경계가 뒤집히지 않도록
    아주 작은 여유를 둡니다.
    """
    return candidate_count > total * max_ratio + 1e-9


def _report(dataset: str, total: int, stale: list[str], max_ratio: float) -> None:
    limit = int(total * max_ratio + 1e-9)
    print(
        f"[{dataset}] 색인 {total:,}건, 원본에 없음 {len(stale):,}건 "
        f"(상한 {_format_ratio(max_ratio)} = {limit:,}건)"
    )
    if stale:
        sample = ", ".join(stale[:SAMPLE_SIZE])
        suffix = "" if len(stale) <= SAMPLE_SIZE else f" 외 {len(stale) - SAMPLE_SIZE:,}건"
        print(f"  표본: {sample}{suffix}")


def _delete_stale_documents(client: MeiliSearchClient, stale: list[str]) -> None:
    for start in range(0, len(stale), DOCUMENT_ID_BATCH_SIZE):
        chunk = stale[start : start + DOCUMENT_ID_BATCH_SIZE]
        task_uid = client.delete_documents(chunk)
        print(f"  삭제 요청 {len(chunk):,}건, taskUid={task_uid}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="원본 MySQL 에 없는 Meilisearch 색인 문서를 찾아 지웁니다. 기본은 dry-run 입니다."
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="실제로 삭제합니다. 미지정 시 후보만 출력하는 dry-run 입니다.",
    )
    parser.add_argument(
        "--max-ratio",
        type=float,
        default=DEFAULT_MAX_DELETE_RATIO,
        help=(
            "데이터셋 색인 건수 대비 삭제 후보 허용 비율입니다. 기본 0.01(1%%). "
            "이 값을 넘으면 아무것도 지우지 않고 종료 코드 2 로 끝납니다."
        ),
    )
    args = parser.parse_args(argv)
    if not 0 <= args.max_ratio <= 1:
        print("오류: --max-ratio 는 0 이상 1 이하여야 합니다.", file=sys.stderr)
        return EXIT_ERROR

    db = SessionLocal()
    try:
        client = MeiliSearchClient()
        results: dict[str, tuple[int, list[str]]] = {}
        for dataset in DATASETS:
            stale, total = collect_stale_document_ids(db, client, dataset)
            results[dataset] = (total, stale)
            _report(dataset, total, stale, args.max_ratio)

        exceeded = [
            dataset
            for dataset, (total, stale) in results.items()
            if _exceeds_ratio(total, len(stale), args.max_ratio)
        ]
        if exceeded:
            print(
                "거부: 삭제 후보가 상한을 넘었습니다 "
                f"({', '.join(exceeded)}). 원본 데이터나 색인 상태를 먼저 확인하고, "
                "의도한 규모라면 --max-ratio 로 명시 상향하십시오.",
                file=sys.stderr,
            )
            return EXIT_RATIO_EXCEEDED

        total_stale = sum(len(stale) for _, stale in results.values())
        if not args.execute:
            print(f"dry-run: 삭제 후보 {total_stale:,}건. 실제 삭제는 --execute 로 실행하십시오.")
            return EXIT_OK

        if not total_stale:
            print("삭제할 문서가 없습니다.")
            return EXIT_OK

        for dataset in DATASETS:
            _, stale = results[dataset]
            if stale:
                print(f"[{dataset}] 삭제")
                _delete_stale_documents(client, stale)
        print(
            f"삭제 요청 완료: {total_stale:,}건. 색인 반영은 Meilisearch 작업 상태로 확인하십시오."
        )
        return EXIT_OK
    except Exception as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return EXIT_ERROR
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main())
