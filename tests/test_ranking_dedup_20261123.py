"""랭킹 스냅숏 공고 차원의 최신 차수 단일화·취소공고 제외 회귀 테스트.

2026-11-22 집계 중복 감사에서 랭킹 스냅숏의 기관명·공고명 순위가 같은 공고의
모든 차수를 각각 세어 부풀려진 사실이 드러났습니다(기관 1위 서울특별시 27,854건,
최신 차수만 세면 23,749건). 새 차원 `dminstt_nm_v2`, `bid_ntce_nm_v2` 가 같은
공고번호·업무구분의 최신 차수 한 행만 세고 최신 차수가 취소공고인 공고를 빼는지,
옛 차원이 재집계·조회 대상에서 빠졌는지 고정합니다. 낙찰 결과 차원
(`bidwinnr_nm`)은 결과 행이 차수별 별개 사건이라 그대로 둡니다.

시험은 SQLite 인메모리 픽스처(isolated_db)만 쓰며 로컬 .env, 운영 DB, Redis 에
기대지 않습니다.
"""

import importlib
from datetime import datetime, timedelta

import pytest

from src.app.models.bids import (
    BidAnnouncement,
    BidRankingSnapshot,
    BidResult,
)
from src.app.services.ranking_snapshots import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    DIMENSIONS,
    WEEKLY_DIMENSIONS,
    get_top_rankings,
    rebuild_ranking_snapshots,
)

BASE = datetime(2026, 5, 1, 9, 0, 0)
CANCELLED = "취소공고"

DIM_INSTITUTION = "dminstt_nm_v2"
DIM_ANNOUNCEMENT = "bid_ntce_nm_v2"
DIM_WINNER = "bidwinnr_nm"


def _add_announcement(
    db,
    bid_ntce_no: str,
    *,
    bid_ntce_ord: str = "000",
    dminstt_nm: str | None = "차수 검증 기관",
    bid_ntce_nm: str = "차수 검증 공고",
    ntce_kind_nm: str | None = None,
    category: str = "Servc",
    bid_ntce_dt: datetime | None = None,
) -> BidAnnouncement:
    row = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=bid_ntce_ord,
        bid_ntce_nm=bid_ntce_nm,
        dminstt_nm=dminstt_nm,
        ntce_kind_nm=ntce_kind_nm,
        category=category,
        bid_ntce_dt=bid_ntce_dt or BASE,
        collected_at=BASE,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def _rankings(db, dimension: str, category: str = "") -> list[tuple[str | None, int]] | None:
    return get_top_rankings(db, DATASET_ANNOUNCEMENT, dimension, category, 10)


def _counts(db, dimension: str, category: str = "") -> dict[str | None, int]:
    rows = _rankings(db, dimension, category)
    assert rows is not None, f"{dimension} 스냅숏이 없습니다."
    return dict(rows)


# --------------------------------------------------------------------------- #
# (a) 최신 차수 한 행만 센다
# --------------------------------------------------------------------------- #


def test_same_announcement_counts_once_across_ordinals(isolated_db):
    """000·001 차수를 가진 공고는 기관명 순위에 한 번만 반영됩니다."""
    for ordinal in ("000", "001", "002"):
        _add_announcement(
            isolated_db,
            "DEDUP-A",
            bid_ntce_ord=ordinal,
            dminstt_nm="중복 검증 기관",
            bid_ntce_nm="중복 검증 공고",
        )

    rebuild_ranking_snapshots(isolated_db)

    assert _counts(isolated_db, DIM_INSTITUTION) == {"중복 검증 기관": 1}
    assert _counts(isolated_db, DIM_ANNOUNCEMENT) == {"중복 검증 공고": 1}


def test_latest_ordinal_decides_the_agency_value(isolated_db):
    """차수 사이에 기관명이 바뀌면 최신 차수의 값만 남습니다."""
    _add_announcement(isolated_db, "DEDUP-B", bid_ntce_ord="000", dminstt_nm="이전 차수 기관")
    _add_announcement(isolated_db, "DEDUP-B", bid_ntce_ord="001", dminstt_nm="최신 차수 기관")

    rebuild_ranking_snapshots(isolated_db)

    assert _counts(isolated_db, DIM_INSTITUTION) == {"최신 차수 기관": 1}


def test_dedup_partition_includes_category(isolated_db):
    """같은 공고번호라도 업무구분이 다르면 서로 다른 공고로 셉니다."""
    _add_announcement(
        isolated_db, "DEDUP-C", bid_ntce_ord="000", dminstt_nm="공유 기관", category="Servc"
    )
    _add_announcement(
        isolated_db, "DEDUP-C", bid_ntce_ord="000", dminstt_nm="공유 기관", category="Thng"
    )

    rebuild_ranking_snapshots(isolated_db)

    assert _counts(isolated_db, DIM_INSTITUTION) == {"공유 기관": 2}


def test_category_scope_still_applies(isolated_db):
    """차원 범위를 바꿔도 category 필터는 그대로 동작합니다."""
    _add_announcement(isolated_db, "DEDUP-D", dminstt_nm="용역 기관", category="Servc")
    _add_announcement(isolated_db, "DEDUP-E", dminstt_nm="물품 기관", category="Thng")
    _add_announcement(isolated_db, "DEDUP-F", dminstt_nm="물품 기관", category="Thng")

    rebuild_ranking_snapshots(isolated_db)

    assert _counts(isolated_db, DIM_INSTITUTION, "Servc") == {"용역 기관": 1}
    assert _counts(isolated_db, DIM_INSTITUTION, "Thng") == {"물품 기관": 2}


# --------------------------------------------------------------------------- #
# (b) 최신 차수가 취소공고면 뺀다
# --------------------------------------------------------------------------- #


def test_announcement_whose_latest_ordinal_is_cancelled_is_excluded(isolated_db):
    """취소된 최신 차수는 물론, 이전 차수가 대신 세어지지도 않습니다."""
    _add_announcement(isolated_db, "CANCEL-A", bid_ntce_ord="000", dminstt_nm="이전 차수 기관")
    _add_announcement(
        isolated_db,
        "CANCEL-A",
        bid_ntce_ord="001",
        dminstt_nm="취소 기관",
        ntce_kind_nm=CANCELLED,
    )
    _add_announcement(isolated_db, "CANCEL-B", bid_ntce_ord="000", dminstt_nm="유지 기관")

    rebuild_ranking_snapshots(isolated_db)

    assert _counts(isolated_db, DIM_INSTITUTION) == {"유지 기관": 1}


@pytest.mark.parametrize("kind", ["재공고", "변경공고", None])
def test_cancelled_previous_ordinal_does_not_remove_reissued_announcement(isolated_db, kind):
    """최신 차수가 재공고·변경공고·NULL 이면 유효한 공고로 남습니다."""
    _add_announcement(
        isolated_db,
        "CANCEL-C",
        bid_ntce_ord="000",
        dminstt_nm="재공고 기관",
        ntce_kind_nm=CANCELLED,
    )
    _add_announcement(
        isolated_db,
        "CANCEL-C",
        bid_ntce_ord="001",
        dminstt_nm="재공고 기관",
        ntce_kind_nm=kind,
    )

    rebuild_ranking_snapshots(isolated_db)

    assert _counts(isolated_db, DIM_INSTITUTION) == {"재공고 기관": 1}


def test_excluded_announcement_is_absent_from_title_rankings_as_well(isolated_db):
    _add_announcement(
        isolated_db,
        "CANCEL-D",
        bid_ntce_ord="001",
        bid_ntce_nm="취소된 공고명",
        ntce_kind_nm=CANCELLED,
    )
    _add_announcement(isolated_db, "CANCEL-E", bid_ntce_ord="000", bid_ntce_nm="유지 공고명")

    rebuild_ranking_snapshots(isolated_db)

    assert _counts(isolated_db, DIM_ANNOUNCEMENT) == {"유지 공고명": 1}


# --------------------------------------------------------------------------- #
# (c) 옛 공고 차원은 더 이상 집계·조회 대상이 아니다
# --------------------------------------------------------------------------- #


def test_old_announcement_dimensions_are_unregistered(isolated_db):
    _add_announcement(isolated_db, "OLD-A", dminstt_nm="옛 차원 기관", bid_ntce_nm="옛 차원 공고")
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    for dimension in ("dminstt_nm", "bid_ntce_nm"):
        assert (DATASET_ANNOUNCEMENT, dimension) not in DIMENSIONS
        assert get_top_rankings(isolated_db, DATASET_ANNOUNCEMENT, dimension, "", 5) is None

    # 새 차원은 같은 데이터로 실제 순위를 남깁니다.
    assert _counts(isolated_db, DIM_INSTITUTION) == {"옛 차원 기관": 1}
    assert _counts(isolated_db, DIM_ANNOUNCEMENT) == {"옛 차원 공고": 1}


def test_rebuild_does_not_touch_old_dimension_rows(isolated_db):
    """옛 스냅숏 행은 지우지 않습니다. 되돌릴 때 코드만 되돌리면 됩니다."""
    isolated_db.add(
        BidRankingSnapshot(
            dataset=DATASET_ANNOUNCEMENT,
            dimension="dminstt_nm",
            category="",
            rank=1,
            label="옛 스냅숏 기관",
            metric_count=999,
            rebuilt_at=BASE,
        )
    )
    isolated_db.commit()

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    preserved = (
        isolated_db.query(BidRankingSnapshot)
        .filter(
            BidRankingSnapshot.dataset == DATASET_ANNOUNCEMENT,
            BidRankingSnapshot.dimension == "dminstt_nm",
        )
        .all()
    )
    assert [row.label for row in preserved] == ["옛 스냅숏 기관"]


# --------------------------------------------------------------------------- #
# (d) 새 주간 차원은 행이 없으면 주기와 무관하게 만든다
# --------------------------------------------------------------------------- #


def test_new_weekly_dimension_is_built_when_missing(isolated_db):
    _add_announcement(isolated_db, "WEEKLY-A", bid_ntce_nm="주간 차원 공고")
    assert (DATASET_ANNOUNCEMENT, DIM_ANNOUNCEMENT) in WEEKLY_DIMENSIONS

    outcome = rebuild_ranking_snapshots(isolated_db)

    assert outcome["deferred_dimensions"] == []
    assert _counts(isolated_db, DIM_ANNOUNCEMENT) == {"주간 차원 공고": 1}


def test_missing_weekly_rows_force_rebuild_even_when_other_dimension_is_fresh(isolated_db):
    """다른 차원이 방금 집계됐어도 새 주간 차원에 행이 없으면 즉시 만듭니다."""
    _add_announcement(isolated_db, "WEEKLY-B", bid_ntce_nm="주간 차원 공고")
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)
    # 새 차원만 사라진 상황을 만듭니다(운영에 _v2 스냅숏이 없는 첫 배포와 같습니다).
    isolated_db.query(BidRankingSnapshot).filter(
        BidRankingSnapshot.dimension == DIM_ANNOUNCEMENT
    ).delete()
    isolated_db.commit()

    outcome = rebuild_ranking_snapshots(isolated_db)

    assert outcome["deferred_dimensions"] == []
    assert _counts(isolated_db, DIM_ANNOUNCEMENT) == {"주간 차원 공고": 1}


# --------------------------------------------------------------------------- #
# (e) 낙찰 결과 차원은 그대로 둔다
# --------------------------------------------------------------------------- #


def test_winner_dimension_still_counts_every_result_row(isolated_db):
    for ordinal in ("000", "001"):
        isolated_db.add(
            BidResult(
                bid_ntce_no="RESULT-A",
                bid_ntce_ord=ordinal,
                category="Servc",
                bidwinnr_nm="결과 업체",
                dminstt_nm="결과 기관",
                rl_openg_dt=BASE,
                collected_at=BASE,
            )
        )
    isolated_db.commit()

    rebuild_ranking_snapshots(isolated_db)

    rows = get_top_rankings(isolated_db, DATASET_RESULT, DIM_WINNER, "", 5)
    assert rows == [("결과 업체", 2)]


# --------------------------------------------------------------------------- #
# (f) 재집계 스크립트 --force-weekly
# --------------------------------------------------------------------------- #


class _FakeSession:
    def close(self) -> None:
        pass


@pytest.fixture
def rebuild_script(monkeypatch):
    module = importlib.import_module("scripts.rebuild_ranking_snapshots")
    calls: list[dict] = []

    def fake_rebuild(db, **kwargs):
        calls.append(kwargs)
        return {"rows": 0, "deferred_dimensions": []}

    monkeypatch.setattr(module, "SessionLocal", _FakeSession)
    monkeypatch.setattr(module, "snapshot_age", lambda db: None)
    monkeypatch.setattr(module, "rebuild_ranking_snapshots", fake_rebuild)
    return module, calls


def test_script_passes_force_weekly_flag(rebuild_script):
    module, calls = rebuild_script

    assert module.main(["--force-weekly"]) == 0

    assert calls == [{"force_weekly": True}]


def test_script_default_keeps_weekly_interval(rebuild_script):
    module, calls = rebuild_script

    assert module.main([]) == 0

    assert calls == [{"force_weekly": False}]


# --------------------------------------------------------------------------- #
# 스냅숏 나이 기준(주기가 아니라 스냅숏 자체의 나이)은 기존 동작을 유지한다
# --------------------------------------------------------------------------- #


def test_stale_weekly_dimension_is_rebuilt(isolated_db):
    from src.app.core.timeutil import utcnow
    from src.app.services.ranking_snapshots import WEEKLY_REBUILD_INTERVAL_DAYS

    _add_announcement(isolated_db, "STALE-A", bid_ntce_nm="주간 차원 공고")
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)
    isolated_db.query(BidRankingSnapshot).filter(
        BidRankingSnapshot.dimension == DIM_ANNOUNCEMENT
    ).update(
        {BidRankingSnapshot.rebuilt_at: utcnow() - timedelta(days=WEEKLY_REBUILD_INTERVAL_DAYS + 1)}
    )
    isolated_db.commit()

    outcome = rebuild_ranking_snapshots(isolated_db)

    assert outcome["deferred_dimensions"] == []
