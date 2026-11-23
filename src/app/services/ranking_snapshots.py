"""
src/app/services/ranking_snapshots.py

상위 N 집계 사전 계산.

`retrieve_structured_data` 가 질의마다 300만 행에 GROUP BY 를 걸어 33초를 쓰던
문제를 해결합니다 (docs/ops/latency_benchmark.md). `bid_dataset_summaries` 와 같은
스냅샷 방식이며, 원본 테이블의 스키마나 인덱스는 건드리지 않습니다.

**필터가 category 뿐인 질의만 대상입니다.** 날짜나 기관명이 걸린 질의는 조합이
사실상 무한하므로 기존 실시간 집계를 그대로 씁니다.

공고 차원(`dminstt_nm_v2`, `bid_ntce_nm_v2`)은 같은 공고번호·업무구분의 최신
차수 한 행만 세고 최신 차수가 취소공고인 공고를 뺍니다. 옛 차원 이름
(`dminstt_nm`, `bid_ntce_nm`)은 차수별 행을 모두 세어 같은 공고를 여러 번
반영했으므로 재집계·조회 대상에서 빼두었습니다.

집계 비용은 대부분 최신 차수 파생 테이블을 본문 행과 조인하는 단계에서 나옵니다.
그래서 카테고리 조합에서는 파생 테이블에도 같은 업무구분 조건을 걸고, 라벨
가짓수가 적은 차원은 전체 카테고리 순위를 카테고리별 결과의 합으로 만듭니다.
두 방법 모두 순위와 건수를 바꾸지 않는 실행 방식 개선입니다.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import and_, delete, func, select
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
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


@dataclass(frozen=True)
class DimensionSpec:
    """한 차원의 집계 대상과 범위입니다."""

    model: Any
    column: Any
    # True 면 같은 공고번호·업무구분의 최신 차수 한 행만 세고, 최신 차수가
    # 취소공고인 공고를 뺍니다.
    latest_ord_only: bool = False
    # True 면 전체 카테고리 순위를 카테고리별 결과의 합으로 만듭니다. 라벨
    # 가짓수가 적어 전체 결과를 메모리에 올릴 수 있는 차원만 켭니다. 켜면
    # 전체 카테고리를 위한 별도 집계가 사라집니다(2026-11-23 실측
    # dminstt_nm_v2 전체 카테고리 152초).
    derive_all_category: bool = False


# (dataset, dimension) -> 집계 대상 차원
#
# `latest_ord_only` 는 같은 공고번호·업무구분의 최신 차수 한 행만 세고, 최신
# 차수가 취소공고인 공고를 빼는 차원입니다. 공고는 차수마다 행이 하나씩 쌓이므로
# 그대로 세면 같은 공고가 여러 번 반영됩니다. 낙찰 결과는 결과 행 자체가 차수별
# 사건이라 그대로 셉니다.
#
# 옛 이름(`dminstt_nm`, `bid_ntce_nm`)은 이 정의가 아니므로 등록하지 않습니다.
# 등록하지 않은 차원은 재집계 대상이 아니고 조회도 실시간 경로로 넘어갑니다.
DIMENSIONS: dict[tuple[str, str], DimensionSpec] = {
    (DATASET_RESULT, "bidwinnr_nm"): DimensionSpec(BidResult, BidResult.bidwinnr_nm),
    (DATASET_ANNOUNCEMENT, "dminstt_nm_v2"): DimensionSpec(
        BidAnnouncement,
        BidAnnouncement.dminstt_nm,
        latest_ord_only=True,
        derive_all_category=True,
    ),
    (DATASET_ANNOUNCEMENT, "bid_ntce_nm_v2"): DimensionSpec(
        BidAnnouncement, BidAnnouncement.bid_ntce_nm, latest_ord_only=True
    ),
}

# 빈 문자열은 "전체" 를 뜻합니다. NULL 은 유니크 제약에서 중복을 허용해 쓰지 않습니다.
ALL_CATEGORIES = ""
SNAPSHOT_CATEGORIES = (ALL_CATEGORIES, *CATEGORY_LABELS)

# 매일 다시 집계하지 않는 차원입니다.
#
# `bid_ntce_nm` 은 varchar(500) 에 인덱스가 없어 전 기간을 전표 스캔한 뒤 임시
# 테이블과 파일소트를 씁니다. 2026-08-06 실측에서 전체 카테고리 한 조합이
# 167초로, 야간 재집계 506초의 3분의 1을 혼자 썼습니다. `_v2` 는 최신 차수
# 필터가 붙어 모수가 줄지만 집계 열 자체는 여전히 인덱스가 없습니다.
#
# 이 순위는 전 기간 누적이라 하루 만에 뒤집히지 않습니다. 주기를 늘려도 답변이
# 달라지지 않으므로 비용만 회수합니다. 자세한 근거는
# `docs/ops/snapshot_rebuild_cost_20260806.md`.
WEEKLY_DIMENSIONS = frozenset({(DATASET_ANNOUNCEMENT, "bid_ntce_nm_v2")})

# 주간 차원을 다시 집계하는 간격입니다. 요일로 판정하면 크론이 도는 시각의
# 시간대에 따라 건너뛰거나 두 번 도는 날이 생깁니다. 스냅샷 자체의 나이를
# 보면 시간대와 무관하게 자기교정됩니다.
WEEKLY_REBUILD_INTERVAL_DAYS = 7


def exclude_corrupted(column):
    """U+FFFD 를 포함한 값을 SQL 단계에서 제외합니다."""
    return column.is_not(None) & ~column.contains(REPLACEMENT_CHAR)


def _announcement_scope(stmt, category: str | None = None):
    """최신 차수 한 행만 남기고 최신 차수가 취소공고인 공고를 뺍니다.

    `bid_announcements` 는 (bid_ntce_no, bid_ntce_ord, category) 가 유니크이므로
    같은 공고번호·업무구분 안에서 같은 차수를 가진 행이 둘일 수 없습니다. 그래서
    최신 차수는 (bid_ntce_no, category) 별 MAX(bid_ntce_ord) 한 행과 같고,
    목록 필터의 정렬 tie-break(공고일시·수집일시·id)는 결과를 바꾸지 않습니다.
    파생 테이블의 GROUP BY 는 유니크 인덱스만 읽어 본문을 건드리지 않습니다.

    `category` 를 주면 파생 테이블도 그 업무구분만 남깁니다. 업무구분은 이미
    GROUP BY 키에 들어 있으므로 결과는 같고 조인 대상만 줄어듭니다
    (2026-11-23 실측 dminstt_nm_v2 Servc 55초 -> 31초). 그런데 `category = :c`
    로 그대로 쓰면 MySQL 이 category 인덱스를 골라 200만 행을 무작위로 읽습니다
    (같은 조합 150초). TRIM 은 공백 없는 고정 코드에서 값을 바꾸지 않으므로
    결과를 유지하면서 그 인덱스를 쓸 수 없게 만듭니다. 값에 공백이 섞여도
    바깥 조인의 `category` 조건이 정확히 걸러내 최종 결과는 달라지지 않습니다.
    """
    from src.app.services.bid_queries import not_cancelled_clause

    latest_stmt = select(
        BidAnnouncement.bid_ntce_no.label("bid_ntce_no"),
        BidAnnouncement.category.label("category"),
        func.max(BidAnnouncement.bid_ntce_ord).label("bid_ntce_ord"),
    ).group_by(BidAnnouncement.bid_ntce_no, BidAnnouncement.category)
    if category:
        latest_stmt = latest_stmt.where(func.trim(BidAnnouncement.category) == category)
    latest = latest_stmt.subquery("latest_ann_ord")
    return stmt.join(
        latest,
        and_(
            latest.c.bid_ntce_no == BidAnnouncement.bid_ntce_no,
            latest.c.category == BidAnnouncement.category,
            latest.c.bid_ntce_ord == BidAnnouncement.bid_ntce_ord,
        ),
    ).where(not_cancelled_clause())


def _scoped(stmt, spec: DimensionSpec, category: str | None = None):
    """차원이 정한 범위를 문장에 적용합니다."""
    return _announcement_scope(stmt, category) if spec.latest_ord_only else stmt


def _ranking_statement(dataset: str, dimension: str, category: str, *, complete: bool = False):
    """집계 후보를 뽑는 SELECT 문을 만듭니다. 실행과 분리해 계획을 검토할 수 있습니다."""
    spec = DIMENSIONS[(dataset, dimension)]
    model, column = spec.model, spec.column
    scope = [model.category == category] if category else []

    stmt = _scoped(
        select(column, func.count(model.id)).where(exclude_corrupted(column), *scope),
        spec,
        category,
    )
    stmt = stmt.group_by(column).order_by(func.count(model.id).desc())
    if not complete:
        stmt = stmt.limit(SNAPSHOT_DEPTH * OVERFETCH_FACTOR)
    return stmt


def _corruption_probe_statement(dataset: str, dimension: str, category: str):
    """집계 범위에 U+FFFD 값이 있는지 보는 SELECT 문을 만듭니다."""
    spec = DIMENSIONS[(dataset, dimension)]
    scope = [spec.model.category == category] if category else []
    return _scoped(
        select(spec.model.id).where(spec.column.contains(REPLACEMENT_CHAR), *scope).limit(1),
        spec,
        category,
    )


def _candidate_rows(
    db: Session, dataset: str, dimension: str, category: str, *, complete: bool = False
) -> list[tuple[str | None, int]]:
    """집계 후보를 건수 내림차순으로 돌려줍니다.

    `complete=True` 면 상위 N 자르지 않고 전 라벨을 돌려줍니다. 전체 카테고리
    순위를 카테고리별 결과의 합으로 만들 때 씁니다. 자르지 않아도 집계 자체는
    어차피 모든 그룹을 만들므로 비용은 늘지 않습니다.
    """
    stmt = _ranking_statement(dataset, dimension, category, complete=complete)
    return [(label, int(count or 0)) for label, count in db.execute(stmt).all()]


def _has_corrupted_label(db: Session, dataset: str, dimension: str, category: str) -> bool:
    """집계 범위에 U+FFFD 를 포함한 값이 있었는지 확인합니다.

    첫 건에서 멈추므로 저렴합니다. 손상 탐침도 집계와 같은 범위를 봅니다. 그래야
    "이 순위에서 제외했다" 는 표시가 실제 집계 모수와 일치합니다.
    """
    stmt = _corruption_probe_statement(dataset, dimension, category)
    return db.execute(stmt).first() is not None


def _rank(candidates: list[tuple[str | None, int]]) -> tuple[list, bool]:
    """후보에서 저장할 상위 N 을 고르고 인코딩이 깨진 값은 순위에서 제외합니다.

    복구 불가능한 손상값(전체의 41%)을 그대로 두면 순위 상위가 전부 깨진 문자열로
    채워져 답변이 쓸모없어집니다. 대시보드 업체 순위(`_is_readable_company_name`)도
    같은 방침입니다. 걸러낸 것이 있는지를 함께 돌려주어 호출부가 안내할 수 있게
    합니다.
    """
    kept: list = []
    dropped = False
    for label, count in candidates[: SNAPSHOT_DEPTH * OVERFETCH_FACTOR]:
        # SQL 이 U+FFFD 를 쳐냈어도 다른 형태로 깨진 값이 남을 수 있습니다.
        if is_corrupted_display_text(label):
            dropped = True
            continue
        kept.append((label, count))
        if len(kept) >= SNAPSHOT_DEPTH:
            break
    return kept, dropped


@dataclass(frozen=True)
class _Combination:
    """한 (차원, 카테고리) 조합의 집계 결과입니다."""

    # 스냅숏에 저장할 상위 N.
    rows: list[tuple[str | None, int]]
    # 손상값을 제외했는지(스냅숏 rank 0 마커).
    dropped: bool
    # 합산에 쓰는 후보. 전체 카테고리를 합으로 만들 때만 전 라벨입니다.
    candidates: list[tuple[str | None, int]]
    # SQL 단계에서 U+FFFD 를 쳐낸 것이 있었는지.
    corrupted: bool


def _compute_combination(
    db: Session, dataset: str, dimension: str, category: str, *, complete: bool = False
) -> _Combination:
    candidates = _candidate_rows(db, dataset, dimension, category, complete=complete)
    rows, heuristic_dropped = _rank(candidates)
    corrupted = _has_corrupted_label(db, dataset, dimension, category)
    return _Combination(
        rows=rows,
        dropped=heuristic_dropped or corrupted,
        candidates=candidates,
        corrupted=corrupted,
    )


def _merge_candidates(combinations: list[_Combination]) -> list[tuple[str | None, int]]:
    """카테고리별 후보를 라벨 기준으로 합산합니다.

    업무구분은 행마다 하나이므로 전체 카테고리의 건수는 카테고리별 건수의 합과
    정확히 같습니다. 동점은 라벨 오름차순으로 고정해 실행마다 같은 순위가
    나오게 합니다.
    """
    totals: dict[str | None, int] = {}
    for combination in combinations:
        for label, count in combination.candidates:
            totals[label] = totals.get(label, 0) + count
    return sorted(totals.items(), key=lambda item: (-item[1], item[0] or ""))


def _has_unregistered_category(db: Session, model: Any) -> bool:
    """스냅숏이 다루지 않는 업무구분이 있는지 봅니다.

    전체 카테고리를 카테고리별 합으로 만들면 이 값들이 빠집니다. 하나라도 있으면
    전체 집계를 직접 실행하는 쪽으로 돌아갑니다.
    """
    stmt = select(model.id).where(model.category.not_in(tuple(CATEGORY_LABELS))).limit(1)
    return db.execute(stmt).first() is not None


def _dimension_age_days(db: Session, dataset: str, dimension: str) -> float | None:
    """해당 차원 스냅샷의 나이(일). 아직 집계된 적이 없으면 None."""
    rebuilt_at = db.scalar(
        select(func.max(BidRankingSnapshot.rebuilt_at)).where(
            BidRankingSnapshot.dataset == dataset,
            BidRankingSnapshot.dimension == dimension,
        )
    )
    if rebuilt_at is None:
        return None
    # 이 저장소는 DateTime 컬럼을 UTC naive 로 통일합니다 (`core/timeutil`).
    # 어쩌다 aware 값이 들어와도 빼기가 깨지지 않도록 여기서 맞춥니다.
    if rebuilt_at.tzinfo is not None:
        rebuilt_at = rebuilt_at.astimezone(UTC).replace(tzinfo=None)
    return (utcnow() - rebuilt_at).total_seconds() / 86400.0


def _should_rebuild(db: Session, dataset: str, dimension: str, force_weekly: bool) -> bool:
    """주간 차원인지, 주간 차원이라면 다시 집계할 때가 됐는지 판정합니다."""
    if (dataset, dimension) not in WEEKLY_DIMENSIONS:
        return True
    if force_weekly:
        return True
    age = _dimension_age_days(db, dataset, dimension)
    # 한 번도 집계된 적이 없으면 반드시 만듭니다. 없는 채로 두면 조회가
    # 실시간 경로로 떨어져 오히려 느려집니다.
    return age is None or age >= WEEKLY_REBUILD_INTERVAL_DAYS


def rebuild_ranking_snapshots(db: Session, *, force_weekly: bool = False) -> dict[str, int]:
    """전체 조합을 다시 집계합니다. 무거우므로 정기 실행과 수집 직후에만 호출합니다.

    `WEEKLY_DIMENSIONS` 는 나이가 `WEEKLY_REBUILD_INTERVAL_DAYS` 를 넘었을 때만
    다시 집계합니다. 건너뛴 차원의 기존 스냅샷은 그대로 두므로 조회는 계속
    동작합니다. `force_weekly=True` 면 주기와 무관하게 전부 집계합니다.
    """
    started = utcnow()
    written = 0
    skipped = 0
    deferred: list[str] = []

    for dataset, dimension in DIMENSIONS:
        if not _should_rebuild(db, dataset, dimension, force_weekly):
            deferred.append(dimension)
            continue

        spec = DIMENSIONS[(dataset, dimension)]
        # 전체 카테고리를 카테고리별 합으로 만들 수 있는지 먼저 봅니다. 스냅숏이
        # 다루지 않는 업무구분이 있으면 합으로는 전체를 재현할 수 없으므로 직접
        # 집계하는 쪽으로 돌아갑니다.
        derive_all = spec.derive_all_category and not _has_unregistered_category(db, spec.model)
        combinations: dict[str, _Combination] = {}
        for category in SNAPSHOT_CATEGORIES:
            if category == ALL_CATEGORIES and derive_all:
                continue
            combinations[category] = _compute_combination(
                db,
                dataset,
                dimension,
                category,
                complete=derive_all and category != ALL_CATEGORIES,
            )

        if derive_all:
            per_category = [combinations[category] for category in CATEGORY_LABELS]
            candidates = _merge_candidates(per_category)
            rows, heuristic_dropped = _rank(candidates)
            corrupted = any(combination.corrupted for combination in per_category)
            combinations[ALL_CATEGORIES] = _Combination(
                rows=rows,
                dropped=heuristic_dropped or corrupted,
                candidates=candidates,
                corrupted=corrupted,
            )

        for category in SNAPSHOT_CATEGORIES:
            combination = combinations[category]
            skipped += int(combination.dropped)
            db.execute(
                delete(BidRankingSnapshot).where(
                    BidRankingSnapshot.dataset == dataset,
                    BidRankingSnapshot.dimension == dimension,
                    BidRankingSnapshot.category == category,
                )
            )
            # 손상 제외 마커는 손상 유무와 무관하게 항상 기록합니다. 마커가 없으면
            # "모른다" 와 "깨끗하다" 를 구분할 수 없어 실시간 경로가 매번
            # corrupted_probe 를 돕니다. 있으면 1, 없으면 0 을 남겨 존재 여부와
            # 값을 분리해 읽을 수 있게 합니다. rank 0 행은 조회에서 제외됩니다.
            db.add(
                BidRankingSnapshot(
                    dataset=dataset,
                    dimension=dimension,
                    category=category,
                    rank=SKIPPED_MARKER_RANK,
                    label=None,
                    metric_count=int(combination.dropped),
                    rebuilt_at=started,
                )
            )
            written += 1
            for rank, (label, count) in enumerate(combination.rows, start=1):
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

    elapsed = (utcnow() - started).total_seconds()
    logger.info(
        "상위 N 스냅샷 재집계 완료 (%d행, 손상 제외 조합 %d개, %.1fs, 주간 보류 %s)",
        written,
        skipped,
        elapsed,
        ",".join(deferred) or "없음",
    )
    summary: dict[str, Any] = {
        "rows": written,
        "scopes_with_corruption": skipped,
        "elapsed_seconds": elapsed,
        "deferred_dimensions": deferred,
    }
    return summary


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


def get_skipped_marker(db: Session, dataset: str, dimension: str, category: str) -> int | None:
    """손상 제외 마커의 존재 여부와 값을 분리해 돌려줍니다.

    마커 행이 없으면 None 을 돌려 "모른다" 를 뜻합니다. 있으면 metric_count 를
    int 로 돌려줍니다. 0 은 "확인했고 깨끗했다" 는 뜻이라 None 과 다릅니다.
    기존 get_skipped_count 의 시그니처와 반환 의미는 그대로 둡니다.
    """
    value = db.scalar(
        select(BidRankingSnapshot.metric_count).where(
            BidRankingSnapshot.dataset == dataset,
            BidRankingSnapshot.dimension == dimension,
            BidRankingSnapshot.category == (category or ALL_CATEGORIES),
            BidRankingSnapshot.rank == SKIPPED_MARKER_RANK,
        )
    )
    if value is None:
        return None
    return int(value)


def snapshot_age(db: Session) -> datetime | None:
    return db.scalar(select(func.max(BidRankingSnapshot.rebuilt_at)))
