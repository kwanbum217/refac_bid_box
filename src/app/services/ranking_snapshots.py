"""
src/app/services/ranking_snapshots.py

상위 N 집계 사전 계산.

`retrieve_structured_data` 가 질의마다 300만 행에 GROUP BY 를 걸어 33초를 쓰던
문제를 해결합니다 (docs/ops/latency_benchmark.md). `bid_dataset_summaries` 와 같은
스냅샷 방식이며, 원본 테이블의 스키마나 인덱스는 건드리지 않습니다.

**필터가 category 뿐인 질의만 대상입니다.** 날짜나 기관명이 걸린 질의는 조합이
사실상 무한하므로 기존 실시간 집계를 그대로 씁니다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.app.models.bids import (
    CATEGORY_LABELS,
    BidAnnouncement,
    BidRankingSnapshot,
    BidResult,
)

logger = logging.getLogger(__name__)

DATASET_ANNOUNCEMENT = "announcement"
DATASET_RESULT = "result"

# 호출부는 상위 5개를 쓰지만 여유를 두고 저장합니다.
SNAPSHOT_DEPTH = 10

# (dataset, dimension) -> (모델, 집계 컬럼)
DIMENSIONS: dict[tuple[str, str], tuple[Any, Any]] = {
    (DATASET_RESULT, "bidwinnr_nm"): (BidResult, BidResult.bidwinnr_nm),
    (DATASET_ANNOUNCEMENT, "dminstt_nm"): (BidAnnouncement, BidAnnouncement.dminstt_nm),
    (DATASET_ANNOUNCEMENT, "bid_ntce_nm"): (BidAnnouncement, BidAnnouncement.bid_ntce_nm),
}

# 빈 문자열은 "전체" 를 뜻합니다. NULL 은 유니크 제약에서 중복을 허용해 쓰지 않습니다.
ALL_CATEGORIES = ""
SNAPSHOT_CATEGORIES = (ALL_CATEGORIES, *CATEGORY_LABELS)


def _compute_rows(db: Session, dataset: str, dimension: str, category: str) -> list[tuple]:
    model, column = DIMENSIONS[(dataset, dimension)]
    stmt = select(column, func.count(model.id)).group_by(column)
    if category:
        stmt = stmt.where(model.category == category)
    stmt = stmt.order_by(func.count(model.id).desc()).limit(SNAPSHOT_DEPTH)
    return db.execute(stmt).all()


def rebuild_ranking_snapshots(db: Session) -> dict[str, int]:
    """전체 조합을 다시 집계합니다. 무거우므로 정기 실행과 수집 직후에만 호출합니다."""
    started = datetime.utcnow()
    written = 0

    for (dataset, dimension) in DIMENSIONS:
        for category in SNAPSHOT_CATEGORIES:
            rows = _compute_rows(db, dataset, dimension, category)
            db.execute(
                delete(BidRankingSnapshot).where(
                    BidRankingSnapshot.dataset == dataset,
                    BidRankingSnapshot.dimension == dimension,
                    BidRankingSnapshot.category == category,
                )
            )
            for rank, (label, count) in enumerate(rows, start=1):
                db.add(
                    BidRankingSnapshot(
                        dataset=dataset,
                        dimension=dimension,
                        category=category,
                        rank=rank,
                        # 표기 정규화는 읽는 쪽(structured_data)에 그대로 둡니다.
                        # 여기서 손대면 정규화 규칙이 두 군데로 갈라집니다.
                        label=label,
                        metric_count=int(count or 0),
                        rebuilt_at=started,
                    )
                )
                written += 1
            db.commit()

    elapsed = (datetime.utcnow() - started).total_seconds()
    logger.info("상위 N 스냅샷 재집계 완료 (%d행, %.1fs)", written, elapsed)
    return {"rows": written, "elapsed_seconds": elapsed}


def get_top_rankings(
    db: Session, dataset: str, dimension: str, category: str, limit: int
) -> list[tuple[str | None, int]] | None:
    """스냅샷을 읽습니다. 아직 집계되지 않았으면 None 을 돌려 실시간 경로로 넘깁니다."""
    if (dataset, dimension) not in DIMENSIONS:
        return None

    rows = db.execute(
        select(BidRankingSnapshot.label, BidRankingSnapshot.metric_count)
        .where(
            BidRankingSnapshot.dataset == dataset,
            BidRankingSnapshot.dimension == dimension,
            BidRankingSnapshot.category == (category or ALL_CATEGORIES),
        )
        .order_by(BidRankingSnapshot.rank)
        .limit(limit)
    ).all()

    if not rows:
        return None
    return [(row[0], int(row[1] or 0)) for row in rows]


def snapshot_age(db: Session) -> datetime | None:
    return db.scalar(select(func.max(BidRankingSnapshot.rebuilt_at)))
