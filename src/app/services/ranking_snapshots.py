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
    is_corrupted_display_text,
)

logger = logging.getLogger(__name__)

DATASET_ANNOUNCEMENT = "announcement"
DATASET_RESULT = "result"

# 호출부는 상위 5개를 쓰지만 여유를 두고 저장합니다.
SNAPSHOT_DEPTH = 10

# U+FFFD 를 SQL 에서 먼저 쳐내도 파이썬 휴리스틱에 걸리는 값이 남습니다.
# 그만큼만 여유를 두면 충분합니다.
OVERFETCH_FACTOR = 3

# 복구 불가능한 손상값은 U+FFFD(치환 문자)를 포함합니다. 상위권 대부분이 손상값이라
# 파이썬에서만 거르면 오버페치를 아무리 늘려도 순위가 다 차지 않습니다.
REPLACEMENT_CHAR = "\ufffd"

# 순위는 1위부터입니다. rank 0 은 "손상값을 제외했는가" 표시 자리로 씁니다
# (metric_count 1 = 제외 있었음). 조회 시점에 다시 판정하면 300만 행 스캔이
# 필요하므로 집계할 때 함께 남깁니다.
SKIPPED_MARKER_RANK = 0

# (dataset, dimension) -> (모델, 집계 컬럼)
DIMENSIONS: dict[tuple[str, str], tuple[Any, Any]] = {
    (DATASET_RESULT, "bidwinnr_nm"): (BidResult, BidResult.bidwinnr_nm),
    (DATASET_ANNOUNCEMENT, "dminstt_nm"): (BidAnnouncement, BidAnnouncement.dminstt_nm),
    (DATASET_ANNOUNCEMENT, "bid_ntce_nm"): (BidAnnouncement, BidAnnouncement.bid_ntce_nm),
}

# 빈 문자열은 "전체" 를 뜻합니다. NULL 은 유니크 제약에서 중복을 허용해 쓰지 않습니다.
ALL_CATEGORIES = ""
SNAPSHOT_CATEGORIES = (ALL_CATEGORIES, *CATEGORY_LABELS)


def exclude_corrupted(column):
    """U+FFFD 를 포함한 값을 SQL 단계에서 제외합니다."""
    return column.is_not(None) & ~column.contains(REPLACEMENT_CHAR)


def _compute_rows(db: Session, dataset: str, dimension: str, category: str) -> tuple[list, int]:
    """상위 N 을 집계하되 인코딩이 깨진 값은 순위에서 제외합니다.

    복구 불가능한 손상값(전체의 41%)을 그대로 두면 순위 상위가 전부 깨진 문자열로
    채워져 답변이 쓸모없어집니다. 대시보드 업체 순위(`_is_readable_company_name`)도
    같은 방침입니다. 제외한 그룹 수를 함께 돌려주어 호출부가 안내할 수 있게 합니다.
    """
    model, column = DIMENSIONS[(dataset, dimension)]
    scope = [model.category == category] if category else []

    stmt = (
        select(column, func.count(model.id))
        .where(exclude_corrupted(column), *scope)
        .group_by(column)
        .order_by(func.count(model.id).desc())
        .limit(SNAPSHOT_DEPTH * OVERFETCH_FACTOR)
    )

    kept: list = []
    dropped = False
    for label, count in db.execute(stmt).all():
        # SQL 이 U+FFFD 를 쳐냈어도 다른 형태로 깨진 값이 남을 수 있습니다.
        if is_corrupted_display_text(label):
            dropped = True
            continue
        kept.append((label, count))
        if len(kept) >= SNAPSHOT_DEPTH:
            break

    if not dropped:
        # SQL 단계에서 제외된 것이 있었는지 확인합니다. 첫 건에서 멈추므로 저렴합니다.
        dropped = (
            db.execute(
                select(model.id)
                .where(column.contains(REPLACEMENT_CHAR), *scope)
                .limit(1)
            ).first()
            is not None
        )

    return kept, dropped


def rebuild_ranking_snapshots(db: Session) -> dict[str, int]:
    """전체 조합을 다시 집계합니다. 무거우므로 정기 실행과 수집 직후에만 호출합니다."""
    started = datetime.utcnow()
    written = 0
    skipped = 0

    for (dataset, dimension) in DIMENSIONS:
        for category in SNAPSHOT_CATEGORIES:
            rows, dropped = _compute_rows(db, dataset, dimension, category)
            skipped += int(dropped)
            db.execute(
                delete(BidRankingSnapshot).where(
                    BidRankingSnapshot.dataset == dataset,
                    BidRankingSnapshot.dimension == dimension,
                    BidRankingSnapshot.category == category,
                )
            )
            if dropped:
                db.add(
                    BidRankingSnapshot(
                        dataset=dataset,
                        dimension=dimension,
                        category=category,
                        rank=SKIPPED_MARKER_RANK,
                        label=None,
                        metric_count=1,
                        rebuilt_at=started,
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
    logger.info(
        "상위 N 스냅샷 재집계 완료 (%d행, 손상 제외 조합 %d개, %.1fs)", written, skipped, elapsed
    )
    return {"rows": written, "scopes_with_corruption": skipped, "elapsed_seconds": elapsed}


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
            BidRankingSnapshot.rank > SKIPPED_MARKER_RANK,
        )
        .order_by(BidRankingSnapshot.rank)
        .limit(limit)
    ).all()

    if not rows:
        return None
    return [(row[0], int(row[1] or 0)) for row in rows]


def get_skipped_count(db: Session, dataset: str, dimension: str, category: str) -> int:
    """집계 시점에 손상값을 제외했는지 여부(1/0). 답변 안내 문구용입니다."""
    value = db.scalar(
        select(BidRankingSnapshot.metric_count).where(
            BidRankingSnapshot.dataset == dataset,
            BidRankingSnapshot.dimension == dimension,
            BidRankingSnapshot.category == (category or ALL_CATEGORIES),
            BidRankingSnapshot.rank == SKIPPED_MARKER_RANK,
        )
    )
    return int(value or 0)


def snapshot_age(db: Session) -> datetime | None:
    return db.scalar(select(func.max(BidRankingSnapshot.rebuilt_at)))
