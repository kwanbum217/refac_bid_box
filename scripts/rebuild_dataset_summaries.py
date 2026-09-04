#!/usr/bin/env python3
"""scripts/rebuild_dataset_summaries.py

bid_dataset_summaries 를 요청 경로 밖에서 통제된 시점에 재집계합니다.

`get_bid_dataset_summary` 는 stale 을 발견하면 그 자리에서 전체 재집계를 수행하고,
announcement 재집계는 실측 477초가 걸립니다. 마이그레이션으로 기대 버전이 올라간
직후 첫 HTTP 요청이 그 작업을 잡으면 사용자가 그 시간을 기다립니다. 집계 알고리즘을
바꾸거나 마이그레이션을 적용한 뒤에는 이 실행기로 먼저 채워 두십시오.

읽기 전용 조회가 아니라 요약 테이블에 쓰기를 수행하므로, 자동 승인 화이트리스트에
넣지 마십시오. 운영자가 직접 실행하는 것을 전제로 합니다.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.app.core.db import SessionLocal
from src.app.models.bids import BidDatasetSummary
from src.app.services.dashboard import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    SUMMARY_ALGORITHM_VERSIONS,
    rebuild_bid_dataset_summary,
)

DATASETS = (DATASET_ANNOUNCEMENT, DATASET_RESULT)


def _describe(summary: BidDatasetSummary) -> str:
    return (
        f"count={summary.total_count} amount={summary.total_amount} "
        f"avg_rate={summary.avg_rate} version={summary.aggregation_version} "
        f"source_latest={summary.source_latest_collected_at}"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="데이터셋 요약 통제 재집계")
    parser.add_argument(
        "--dataset",
        action="append",
        choices=list(DATASETS),
        help="재집계 대상. 반복 지정 가능하며 미지정 시 전부",
    )
    parser.add_argument(
        "--only-stale",
        action="store_true",
        help="저장된 집계 버전이 기대 버전과 다른 것만 재집계합니다",
    )
    args = parser.parse_args(argv)

    targets = args.dataset or list(DATASETS)
    session = SessionLocal()
    try:
        for dataset in targets:
            expected = SUMMARY_ALGORITHM_VERSIONS.get(dataset, 1)
            before = session.get(BidDatasetSummary, dataset)
            if before is not None:
                print(f"[{dataset}] 이전: {_describe(before)}", flush=True)
                if args.only_stale and before.aggregation_version == expected:
                    print(f"[{dataset}] 기대 버전 {expected} 과 같아 건너뜁니다", flush=True)
                    continue
            else:
                print(f"[{dataset}] 이전 요약 없음", flush=True)

            started = time.monotonic()
            summary = rebuild_bid_dataset_summary(session, dataset)
            elapsed = time.monotonic() - started
            print(f"[{dataset}] 이후: {_describe(summary)}", flush=True)
            print(f"[{dataset}] 소요 {elapsed:.1f}초", flush=True)
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
