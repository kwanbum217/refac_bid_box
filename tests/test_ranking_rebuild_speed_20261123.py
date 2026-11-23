"""랭킹 스냅숏 공고 차원 재집계 실행 방식 회귀 테스트.

2026-11-23 공고 차원을 최신 차수·취소 제외(`_v2`)로 바꾸면서 야간 재집계가
870.9초로 늘었습니다. 집계는 조합마다 최신 차수 파생 테이블을 본문과 조인하는
비용이 대부분이고, (공고번호, 업무구분) 별 최신 차수는 업무구분별로 서로 겹치지
않습니다. 그래서 실행 방식만 두 가지로 바꿨습니다.

1. 카테고리 조합은 파생 테이블에도 같은 업무구분 조건을 건다.
2. 라벨 가짓수가 적은 차원은 전체 카테고리 순위를 카테고리별 결과의 합으로 만든다.

이 파일은 두 변경이 순위·건수를 바꾸지 않았는지 고정합니다. 비교 대상은 개선
전 방식(파생 테이블에 업무구분 조건이 없고, 전체 카테고리를 직접 집계)을 그대로
옮긴 참조 구현입니다. 시험은 SQLite 인메모리 픽스처(`isolated_db`)만 쓰며 로컬
.env, 운영 DB, Redis 에 기대지 않습니다.
"""

from datetime import datetime

import pytest
from sqlalchemy import and_, func, or_, select

from src.app.models.bids import (
    BidAnnouncement,
    BidRankingSnapshot,
    is_corrupted_display_text,
)
from src.app.services.ranking_snapshots import (
    ALL_CATEGORIES,
    DATASET_ANNOUNCEMENT,
    DIMENSIONS,
    REPLACEMENT_CHAR,
    _compute_combination,
    _merge_candidates,
    get_skipped_marker,
    get_top_rankings,
    rebuild_ranking_snapshots,
)

BASE = datetime(2026, 5, 1, 9, 0, 0)
CANCELLED = "취소공고"

DIM_INSTITUTION = "dminstt_nm_v2"
DIM_ANNOUNCEMENT = "bid_ntce_nm_v2"
ANNOUNCEMENT_DIMENSIONS = (DIM_INSTITUTION, DIM_ANNOUNCEMENT)
REAL_CATEGORIES = ("Thng", "Cnstwk", "Servc", "Frgcpt")
SNAPSHOT_COMBINATIONS = tuple(
    (dimension, category)
    for dimension in ANNOUNCEMENT_DIMENSIONS
    for category in (ALL_CATEGORIES, *REAL_CATEGORIES)
)

# 업무구분마다 상위 10개 라벨의 건수를 서로 다르게 깔아, 상위 10 경계에 동점이
# 생기지 않게 합니다. 동점은 두 구현의 순서가 모두 임의라 비교가 흔들립니다.
GRADIENT_COUNTS = {
    "Thng": (40, 36, 32, 28, 24, 20, 16, 12, 8, 4),
    "Cnstwk": (39, 35, 31, 27, 23, 19, 15, 11, 7, 3),
    "Servc": (38, 34, 30, 26, 22, 18, 14, 10, 6, 2),
    "Frgcpt": (37, 33, 29, 25, 21, 17, 13, 9, 5, 1),
}


def _add_announcement(
    db,
    bid_ntce_no: str,
    *,
    bid_ntce_ord: str = "000",
    dminstt_nm: str | None = "차수 검증 기관",
    bid_ntce_nm: str = "차수 검증 공고",
    ntce_kind_nm: str | None = None,
    category: str = "Servc",
) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        bid_ntce_nm=bid_ntce_nm,
        dminstt_nm=dminstt_nm,
        ntce_kind_nm=ntce_kind_nm,
        category=category,
        bid_ntce_dt=BASE,
        collected_at=BASE,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _reference_ranking(db, dimension: str, category: str, limit: int = 10):
    """개선 전 방식으로 상위 라벨을 셉니다.

    파생 테이블에 업무구분 조건을 걸지 않고, 전체 카테고리는 카테고리별 결과를
    합치지 않고 직접 집계합니다. 파이썬 손상값 필터와 오버페치 상한까지 개선 전
    `_compute_rows` 와 같게 맞춥니다.
    """
    spec = DIMENSIONS[(DATASET_ANNOUNCEMENT, dimension)]
    column = spec.column
    latest = (
        select(
            BidAnnouncement.bid_ntce_no.label("bid_ntce_no"),
            BidAnnouncement.category.label("category"),
            func.max(BidAnnouncement.bid_ntce_ord).label("bid_ntce_ord"),
        )
        .group_by(BidAnnouncement.bid_ntce_no, BidAnnouncement.category)
        .subquery("reference_latest")
    )
    stmt = (
        select(column, func.count(BidAnnouncement.id))
        .join(
            latest,
            and_(
                latest.c.bid_ntce_no == BidAnnouncement.bid_ntce_no,
                latest.c.category == BidAnnouncement.category,
                latest.c.bid_ntce_ord == BidAnnouncement.bid_ntce_ord,
            ),
        )
        .where(
            column.is_not(None),
            ~column.contains(REPLACEMENT_CHAR),
            or_(
                BidAnnouncement.ntce_kind_nm.is_(None),
                BidAnnouncement.ntce_kind_nm != CANCELLED,
            ),
        )
    )
    if category:
        stmt = stmt.where(BidAnnouncement.category == category)
    stmt = stmt.group_by(column).order_by(func.count(BidAnnouncement.id).desc()).limit(limit * 3)

    kept: list[tuple[str | None, int]] = []
    for label, count in db.execute(stmt).all():
        if is_corrupted_display_text(label):
            continue
        kept.append((label, int(count or 0)))
        if len(kept) >= limit:
            break
    return kept


def _snapshot(db, dimension: str, category: str) -> list[tuple[str | None, int]]:
    rows = get_top_rankings(db, DATASET_ANNOUNCEMENT, dimension, category, 10)
    return rows or []


def _seed_mixed_announcements(db) -> None:
    """차수·취소·재공고·업무구분·손상값이 섞인 표본을 만듭니다."""
    # 업무구분별 건수 사다리. 두 차원 모두 상위 10 경계가 동점 없이 갈립니다.
    for category, counts in GRADIENT_COUNTS.items():
        for index, repeats in enumerate(counts, start=1):
            for repeat in range(repeats):
                _add_announcement(
                    db,
                    f"GRAD-{category}-{index:02d}-{repeat:02d}",
                    dminstt_nm=f"{category} 기관 {index:02d}",
                    bid_ntce_nm=f"{category} 공고 {index:02d}",
                    category=category,
                )

    # 같은 공고의 차수 3개: 최신 차수의 기관·공고명만 남아야 합니다.
    for ordinal, agency in (
        ("000", "이전 차수 기관"),
        ("001", "중간 차수 기관"),
        ("002", "최신 차수 기관"),
    ):
        _add_announcement(
            db,
            "MIX-A",
            bid_ntce_ord=ordinal,
            dminstt_nm=agency,
            bid_ntce_nm=f"혼합 공고 {ordinal}",
        )
    # 최신 차수가 취소공고면 이전 차수도 세지 않습니다.
    _add_announcement(db, "MIX-B", bid_ntce_ord="000", dminstt_nm="취소 이전 기관")
    _add_announcement(
        db, "MIX-B", bid_ntce_ord="001", dminstt_nm="취소 최신 기관", ntce_kind_nm=CANCELLED
    )
    # 최신 차수가 재공고·변경공고·NULL 이면 유효합니다.
    for kind in ("재공고", "변경공고", None):
        key = f"MIX-C-{kind}"
        _add_announcement(
            db, key, bid_ntce_ord="000", dminstt_nm="이전 취소 기관", ntce_kind_nm=CANCELLED
        )
        _add_announcement(
            db,
            key,
            bid_ntce_ord="001",
            dminstt_nm="유효 기관",
            bid_ntce_nm="유효 공고",
            ntce_kind_nm=kind,
        )
    # 같은 공고번호가 업무구분마다 다른 차수를 가집니다.
    _add_announcement(db, "MIX-D", bid_ntce_ord="000", dminstt_nm="물품 공유 기관", category="Thng")
    _add_announcement(
        db, "MIX-D", bid_ntce_ord="001", dminstt_nm="용역 공유 기관", category="Servc"
    )
    _add_announcement(
        db, "MIX-D", bid_ntce_ord="002", dminstt_nm="건설 공유 기관", category="Cnstwk"
    )
    # 여러 업무구분에 걸친 공통 라벨: 전체 건수는 업무구분별 건수의 합입니다.
    for category, repeats in (("Thng", 6), ("Cnstwk", 2), ("Servc", 7)):
        for index in range(repeats):
            _add_announcement(
                db,
                f"MIX-E-{category}-{index}",
                dminstt_nm="공통 기관",
                bid_ntce_nm="공통 공고",
                category=category,
            )
    # 손상값은 순위에서 빠지고 마커만 남습니다.
    _add_announcement(
        db,
        "MIX-F",
        dminstt_nm=f"손상{REPLACEMENT_CHAR}기관",
        bid_ntce_nm=f"손상{REPLACEMENT_CHAR}공고",
    )
    # 라벨이 NULL 인 행은 어느 순위에도 들어가지 않습니다.
    _add_announcement(db, "MIX-G", dminstt_nm=None, bid_ntce_nm="NULL 기관 공고")


# --------------------------------------------------------------------------- #
# (a) 개선 방식과 개선 전 방식의 순위·건수가 같다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("dimension", "category"), SNAPSHOT_COMBINATIONS)
def test_optimized_rebuild_matches_previous_ranking(isolated_db, dimension, category):
    _seed_mixed_announcements(isolated_db)

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    expected = _reference_ranking(isolated_db, dimension, category)
    assert _snapshot(isolated_db, dimension, category) == expected


def test_all_category_ranking_is_sorted_across_categories(isolated_db):
    _seed_mixed_announcements(isolated_db)
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    for dimension in ANNOUNCEMENT_DIMENSIONS:
        rows = _snapshot(isolated_db, dimension, ALL_CATEGORIES)
        counts = [count for _, count in rows]
        assert counts == sorted(counts, reverse=True)
        assert rows[0] == ("Thng 기관 01" if dimension == DIM_INSTITUTION else "Thng 공고 01", 40)
        assert len(rows) == 10


def test_all_category_counts_are_summed_across_categories(isolated_db):
    """공통 라벨의 전체 건수는 업무구분별 건수의 합과 정확히 같습니다."""
    for category, repeats in (("Thng", 6), ("Cnstwk", 2), ("Servc", 7)):
        for index in range(repeats):
            _add_announcement(
                isolated_db,
                f"SUM-{category}-{index}",
                dminstt_nm="합산 기관",
                bid_ntce_nm="합산 공고",
                category=category,
            )

    combinations = [
        _compute_combination(
            isolated_db, DATASET_ANNOUNCEMENT, DIM_INSTITUTION, category, complete=True
        )
        for category in REAL_CATEGORIES
    ]
    merged = dict(_merge_candidates(combinations))

    assert merged["합산 기관"] == 15
    assert dict(combinations[0].candidates)["합산 기관"] == 6


# --------------------------------------------------------------------------- #
# (b) 최신 차수·취소 제외 의미는 그대로다
# --------------------------------------------------------------------------- #


def test_latest_ordinal_wins_and_cancelled_latest_is_excluded(isolated_db):
    for ordinal, agency in (("000", "옛 기관"), ("001", "새 기관")):
        _add_announcement(isolated_db, "SCOPE-A", bid_ntce_ord=ordinal, dminstt_nm=agency)
    _add_announcement(isolated_db, "SCOPE-B", bid_ntce_ord="000", dminstt_nm="취소 이전 기관")
    _add_announcement(
        isolated_db,
        "SCOPE-B",
        bid_ntce_ord="001",
        dminstt_nm="취소 최신 기관",
        ntce_kind_nm=CANCELLED,
    )

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    assert dict(_snapshot(isolated_db, DIM_INSTITUTION, ALL_CATEGORIES)) == {"새 기관": 1}


@pytest.mark.parametrize("kind", ["재공고", "변경공고", None])
def test_reissued_announcement_stays_after_cancelled_previous_ordinal(isolated_db, kind):
    _add_announcement(
        isolated_db,
        "SCOPE-C",
        bid_ntce_ord="000",
        dminstt_nm="이전 취소 기관",
        ntce_kind_nm=CANCELLED,
    )
    _add_announcement(
        isolated_db,
        "SCOPE-C",
        bid_ntce_ord="001",
        dminstt_nm="유효 기관",
        ntce_kind_nm=kind,
    )

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    assert dict(_snapshot(isolated_db, DIM_INSTITUTION, ALL_CATEGORIES)) == {"유효 기관": 1}


def test_dedup_partition_keeps_category(isolated_db):
    """같은 공고번호라도 업무구분이 다르면 각자의 최신 차수를 셉니다."""
    _add_announcement(
        isolated_db, "SCOPE-D", bid_ntce_ord="000", dminstt_nm="물품 기관", category="Thng"
    )
    _add_announcement(
        isolated_db, "SCOPE-D", bid_ntce_ord="005", dminstt_nm="용역 기관", category="Servc"
    )

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    assert dict(_snapshot(isolated_db, DIM_INSTITUTION, "Thng")) == {"물품 기관": 1}
    assert dict(_snapshot(isolated_db, DIM_INSTITUTION, "Servc")) == {"용역 기관": 1}
    assert dict(_snapshot(isolated_db, DIM_INSTITUTION, ALL_CATEGORIES)) == {
        "물품 기관": 1,
        "용역 기관": 1,
    }


# --------------------------------------------------------------------------- #
# (c) 전체 카테고리를 합으로 만들 수 없으면 직접 집계로 돌아간다
# --------------------------------------------------------------------------- #


def test_unregistered_category_falls_back_to_direct_aggregation(isolated_db):
    _add_announcement(isolated_db, "FALL-A", dminstt_nm="등록 기관", category="Servc")
    _add_announcement(isolated_db, "FALL-B", dminstt_nm="미등록 기관", category="Etc")

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    # 등록된 업무구분 스냅숏은 그대로이고, 전체만 직접 집계로 미등록 업무구분을 포함합니다.
    assert dict(_snapshot(isolated_db, DIM_INSTITUTION, ALL_CATEGORIES)) == {
        "등록 기관": 1,
        "미등록 기관": 1,
    }
    assert dict(_snapshot(isolated_db, DIM_INSTITUTION, "Servc")) == {"등록 기관": 1}


def test_missing_category_values_are_still_counted_in_all_category(isolated_db):
    _add_announcement(isolated_db, "EMPTY-A", dminstt_nm="빈 업무구분 기관", category="")

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    assert dict(_snapshot(isolated_db, DIM_INSTITUTION, ALL_CATEGORIES)) == {"빈 업무구분 기관": 1}


# --------------------------------------------------------------------------- #
# (d) 손상 제외 마커는 조합마다 그대로 남는다
# --------------------------------------------------------------------------- #


def test_corruption_marker_matches_previous_behaviour(isolated_db):
    _add_announcement(isolated_db, "MARK-A", dminstt_nm="정상 기관", category="Thng")
    _add_announcement(
        isolated_db,
        "MARK-B",
        dminstt_nm=f"손상{REPLACEMENT_CHAR}기관",
        category="Thng",
    )
    _add_announcement(isolated_db, "MARK-C", dminstt_nm="용역 기관", category="Servc")

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    for category in ("Thng", ALL_CATEGORIES):
        assert get_skipped_marker(isolated_db, DATASET_ANNOUNCEMENT, DIM_INSTITUTION, category) == 1
    for category in ("Servc", "Cnstwk", "Frgcpt"):
        assert get_skipped_marker(isolated_db, DATASET_ANNOUNCEMENT, DIM_INSTITUTION, category) == 0


# --------------------------------------------------------------------------- #
# (e) 스냅숏 기록 자체는 달라지지 않는다
# --------------------------------------------------------------------------- #


def test_rebuild_writes_same_number_of_snapshot_rows(isolated_db):
    _seed_mixed_announcements(isolated_db)
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)
    first = (
        isolated_db.query(BidRankingSnapshot)
        .filter(BidRankingSnapshot.dataset == DATASET_ANNOUNCEMENT)
        .count()
    )

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)
    second = (
        isolated_db.query(BidRankingSnapshot)
        .filter(BidRankingSnapshot.dataset == DATASET_ANNOUNCEMENT)
        .count()
    )

    assert first == second
    assert first <= len(SNAPSHOT_COMBINATIONS) * 11
