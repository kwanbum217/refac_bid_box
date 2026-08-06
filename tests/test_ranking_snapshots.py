"""
tests/test_ranking_snapshots.py

상위 N 사전 집계 검증.

`retrieve_structured_data` 가 질의마다 300만 행에 GROUP BY 를 걸어 33초를 쓰던
문제를 스냅샷으로 해결했습니다 (docs/ops/latency_benchmark.md). 이 파일이 지키는
것은 두 가지입니다.

1. 스냅샷 결과가 실시간 집계와 같은 값을 낸다 (빨라졌지만 답이 달라지면 안 됩니다)
2. 스냅샷을 쓸 수 없는 질의는 실시간 경로로 정확히 넘어간다
"""

from datetime import datetime, timedelta

import pytest

from src.app.models.bids import (
    CORRUPTED_TEXT_FALLBACKS,
    BidAnnouncement,
    BidRankingSnapshot,
    BidResult,
)
from src.app.services.ranking_snapshots import (
    ALL_CATEGORIES,
    DATASET_RESULT,
    SNAPSHOT_DEPTH,
    get_skipped_count,
    get_top_rankings,
    rebuild_ranking_snapshots,
    snapshot_age,
)
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import _snapshot_scope, retrieve_structured_data


def _seed(db):
    """물품 3건, 건설 2건. 낙찰업체/수요기관 순위가 명확히 갈리도록 구성합니다."""
    base = datetime(2026, 5, 1, 9, 0, 0)
    rows = [
        ("Thng", "가나기업", "서울시"),
        ("Thng", "가나기업", "서울시"),
        ("Thng", "다라상사", "부산시"),
        ("Cnstwk", "마바건설", "대전시"),
        ("Cnstwk", "마바건설", "대전시"),
    ]
    for index, (category, winner, agency) in enumerate(rows):
        db.add(
            BidResult(
                bid_ntce_no=f"R{index:04d}",
                bid_ntce_ord="00",
                category=category,
                bidwinnr_nm=winner,
                dminstt_nm=agency,
                rl_openg_dt=base + timedelta(days=index),
                collected_at=base,
            )
        )
        db.add(
            BidAnnouncement(
                bid_ntce_no=f"A{index:04d}",
                bid_ntce_ord="000",
                category=category,
                bid_ntce_nm=f"{agency} 물품 구매",
                dminstt_nm=agency,
                bid_ntce_dt=base + timedelta(days=index),
                collected_at=base,
            )
        )
    db.commit()


@pytest.fixture
def seeded_db(isolated_db):
    _seed(isolated_db)
    return isolated_db


# --------------------------------------------------------------------------- #
# 집계
# --------------------------------------------------------------------------- #


def test_rebuild_writes_rows_for_every_combination(seeded_db):
    outcome = rebuild_ranking_snapshots(seeded_db)
    assert outcome["rows"] > 0
    assert snapshot_age(seeded_db) is not None


def test_rebuild_ranks_by_count_descending(seeded_db):
    rebuild_ranking_snapshots(seeded_db)
    rows = get_top_rankings(seeded_db, DATASET_RESULT, "bidwinnr_nm", "Thng", 5)
    assert rows == [("가나기업", 2), ("다라상사", 1)]


def test_rebuild_scopes_by_category(seeded_db):
    rebuild_ranking_snapshots(seeded_db)
    construction = get_top_rankings(seeded_db, DATASET_RESULT, "bidwinnr_nm", "Cnstwk", 5)
    assert construction == [("마바건설", 2)]


def test_all_categories_scope_aggregates_everything(seeded_db):
    rebuild_ranking_snapshots(seeded_db)
    rows = get_top_rankings(seeded_db, DATASET_RESULT, "bidwinnr_nm", ALL_CATEGORIES, 5)
    assert dict(rows) == {"가나기업": 2, "마바건설": 2, "다라상사": 1}


def test_rebuild_is_idempotent(seeded_db):
    first = rebuild_ranking_snapshots(seeded_db, force_weekly=True)["rows"]
    second = rebuild_ranking_snapshots(seeded_db, force_weekly=True)["rows"]
    assert first == second
    # 갱신할 때마다 행이 쌓이면 순위가 뒤섞입니다.
    total = seeded_db.query(BidRankingSnapshot).count()
    assert total == second


# --------------------------------------------------------------------------- #
# 주간 차원
# --------------------------------------------------------------------------- #
#
# bid_ntce_nm 은 varchar(500) 에 인덱스가 없어 6,645,162 행을 전표 스캔합니다.
# 2026-08-06 실측에서 한 조합이 167초로 야간 재집계 506초의 3분의 1을 씁니다.
# 전 기간 누적 순위라 하루 만에 뒤집히지 않으므로 주기를 늘립니다.


def test_weekly_dimension_is_skipped_on_the_next_night(seeded_db):
    from src.app.services.ranking_snapshots import WEEKLY_DIMENSIONS

    rebuild_ranking_snapshots(seeded_db)
    result = rebuild_ranking_snapshots(seeded_db)

    deferred = set(result["deferred_dimensions"])
    assert deferred == {dimension for _, dimension in WEEKLY_DIMENSIONS}


def test_deferred_dimension_keeps_its_snapshot(seeded_db):
    """건너뛴 차원의 기존 순위를 지우면 조회가 실시간 경로로 떨어집니다."""
    from src.app.services.ranking_snapshots import DATASET_ANNOUNCEMENT, get_top_rankings

    rebuild_ranking_snapshots(seeded_db)
    before = get_top_rankings(seeded_db, DATASET_ANNOUNCEMENT, "bid_ntce_nm", "", 5)
    rebuild_ranking_snapshots(seeded_db)
    after = get_top_rankings(seeded_db, DATASET_ANNOUNCEMENT, "bid_ntce_nm", "", 5)

    assert before
    assert after == before


def test_weekly_dimension_rebuilds_once_stale(seeded_db):
    from datetime import timedelta

    from src.app.core.timeutil import utcnow
    from src.app.services.ranking_snapshots import (
        DATASET_ANNOUNCEMENT,
        WEEKLY_REBUILD_INTERVAL_DAYS,
    )

    rebuild_ranking_snapshots(seeded_db)
    stale = utcnow() - timedelta(days=WEEKLY_REBUILD_INTERVAL_DAYS + 1)
    seeded_db.query(BidRankingSnapshot).filter(
        BidRankingSnapshot.dataset == DATASET_ANNOUNCEMENT,
        BidRankingSnapshot.dimension == "bid_ntce_nm",
    ).update({BidRankingSnapshot.rebuilt_at: stale})
    seeded_db.commit()

    result = rebuild_ranking_snapshots(seeded_db)

    assert result["deferred_dimensions"] == []


def test_weekly_dimension_is_built_when_missing(seeded_db):
    """한 번도 집계된 적이 없으면 주기와 무관하게 만들어야 합니다."""
    from src.app.services.ranking_snapshots import DATASET_ANNOUNCEMENT, get_top_rankings

    result = rebuild_ranking_snapshots(seeded_db)

    assert result["deferred_dimensions"] == []
    assert get_top_rankings(seeded_db, DATASET_ANNOUNCEMENT, "bid_ntce_nm", "", 5)


def test_rebuild_reflects_new_data(seeded_db):
    rebuild_ranking_snapshots(seeded_db)
    for index in range(3):
        seeded_db.add(
            BidResult(
                bid_ntce_no=f"NEW{index}",
                bid_ntce_ord="00",
                category="Thng",
                bidwinnr_nm="신규업체",
                dminstt_nm="인천시",
                rl_openg_dt=datetime(2026, 6, 1),
                collected_at=datetime(2026, 6, 1),
            )
        )
    seeded_db.commit()
    rebuild_ranking_snapshots(seeded_db)

    rows = get_top_rankings(seeded_db, DATASET_RESULT, "bidwinnr_nm", "Thng", 5)
    assert rows[0] == ("신규업체", 3)


def test_snapshot_depth_caps_stored_rows(seeded_db):
    rebuild_ranking_snapshots(seeded_db)
    ranks = [
        row.rank
        for row in seeded_db.query(BidRankingSnapshot)
        .filter(BidRankingSnapshot.dimension == "bidwinnr_nm")
        .all()
    ]
    assert max(ranks) <= SNAPSHOT_DEPTH


# --------------------------------------------------------------------------- #
# 조회 경로 선택
# --------------------------------------------------------------------------- #


def test_missing_snapshot_returns_none(isolated_db):
    """집계 전에는 None 을 돌려 실시간 경로로 넘어가야 합니다."""
    assert get_top_rankings(isolated_db, DATASET_RESULT, "bidwinnr_nm", "Thng", 5) is None


def test_unknown_dimension_returns_none(seeded_db):
    rebuild_ranking_snapshots(seeded_db)
    assert get_top_rankings(seeded_db, DATASET_RESULT, "없는컬럼", "Thng", 5) is None


@pytest.mark.parametrize(
    ("filters", "expected"),
    [
        ({}, ""),
        ({"category": "Thng"}, "Thng"),
        ({"date_from": "2025-01-01"}, None),
        ({"date_to": "2025-12-31"}, None),
        ({"relative_years": 1}, None),
        ({"institution_name": "서울시"}, None),
        ({"category": "Thng", "date_from": "2025-01-01"}, None),
    ],
)
def test_snapshot_scope_rejects_unsupported_filters(filters, expected):
    """날짜와 기관명은 조합이 무한하므로 스냅샷 대상이 아닙니다."""
    plan = RetrievalPlan(use_sql=True, filters=filters)
    assert _snapshot_scope(plan) == expected


# --------------------------------------------------------------------------- #
# 값 일치 (핵심)
# --------------------------------------------------------------------------- #


def test_snapshot_result_matches_live_aggregation(seeded_db):
    """빨라졌지만 답이 달라지면 의미가 없습니다."""
    plan = RetrievalPlan(use_sql=True, filters={"category": "Thng"})

    live = retrieve_structured_data(seeded_db, plan)["summary"]
    rebuild_ranking_snapshots(seeded_db)
    cached = retrieve_structured_data(seeded_db, plan)["summary"]

    for key in ("top_winners", "top_institutions", "top_announcements"):
        assert cached[key] == live[key], f"{key} 가 실시간 집계와 다릅니다."


def test_filtered_query_still_uses_live_path(seeded_db):
    """날짜 필터가 걸리면 스냅샷을 무시하고 실제 기간으로 집계해야 합니다."""
    rebuild_ranking_snapshots(seeded_db)

    plan = RetrievalPlan(
        use_sql=True, filters={"category": "Thng", "date_from": "2026-05-03"}
    )
    summary = retrieve_structured_data(seeded_db, plan)["summary"]

    # 2026-05-03 이후 물품 낙찰은 다라상사 1건뿐입니다.
    assert [row["bidwinnr_nm"] for row in summary["top_winners"]] == ["다라상사"]


def test_snapshot_scope_survives_empty_category(seeded_db):
    rebuild_ranking_snapshots(seeded_db)
    plan = RetrievalPlan(use_sql=True, filters={})
    summary = retrieve_structured_data(seeded_db, plan)["summary"]
    winners = {row["bidwinnr_nm"] for row in summary["top_winners"]}
    assert {"가나기업", "마바건설", "다라상사"} <= winners


# --------------------------------------------------------------------------- #
# 인코딩 손상값 제외
# --------------------------------------------------------------------------- #

CORRUPTED_WINNER = "���� ����"


@pytest.fixture
def corrupted_db(isolated_db):
    """손상값이 정상값보다 건수가 많은 상황. 실제 DB(건설 99.2% 손상)와 같습니다."""
    base = datetime(2026, 5, 1, 9, 0, 0)
    rows = [(CORRUPTED_WINNER, 5), ("정상건설", 2)]
    index = 0
    for winner, count in rows:
        for _ in range(count):
            isolated_db.add(
                BidResult(
                    bid_ntce_no=f"C{index:04d}",
                    bid_ntce_ord="00",
                    category="Cnstwk",
                    bidwinnr_nm=winner,
                    dminstt_nm="대전시",
                    rl_openg_dt=base,
                    collected_at=base,
                )
            )
            index += 1
    isolated_db.commit()
    return isolated_db


def test_corrupted_labels_excluded_from_snapshot(corrupted_db):
    """손상값이 1위여도 순위에서 빠져야 합니다."""
    rebuild_ranking_snapshots(corrupted_db)
    rows = get_top_rankings(corrupted_db, DATASET_RESULT, "bidwinnr_nm", "Cnstwk", 5)
    assert rows == [("정상건설", 2)]


def test_exclusion_is_recorded_for_the_answer(corrupted_db):
    """제외 사실을 숨기면 집계 모수가 달라진 것을 알 수 없습니다."""
    rebuild_ranking_snapshots(corrupted_db)
    assert get_skipped_count(corrupted_db, DATASET_RESULT, "bidwinnr_nm", "Cnstwk") == 1


def test_answer_carries_exclusion_hint(corrupted_db):
    rebuild_ranking_snapshots(corrupted_db)
    plan = RetrievalPlan(use_sql=True, filters={"category": "Cnstwk"})
    outcome = retrieve_structured_data(corrupted_db, plan)

    assert [row["bidwinnr_nm"] for row in outcome["summary"]["top_winners"]] == ["정상건설"]
    assert any("인코딩" in hint for hint in outcome["insufficiency_hints"])


def test_live_path_also_excludes_corrupted(corrupted_db):
    """스냅샷 없이 실시간 집계로 가는 질의도 같은 기준이어야 합니다."""
    plan = RetrievalPlan(use_sql=True, filters={"category": "Cnstwk", "date_from": "2026-04-01"})
    outcome = retrieve_structured_data(corrupted_db, plan)

    assert [row["bidwinnr_nm"] for row in outcome["summary"]["top_winners"]] == ["정상건설"]
    assert any("인코딩" in hint for hint in outcome["insufficiency_hints"])


def test_no_hint_when_nothing_was_excluded(seeded_db):
    """멀쩡한 데이터에까지 안내를 붙이면 신뢰를 잃습니다."""
    rebuild_ranking_snapshots(seeded_db)
    plan = RetrievalPlan(use_sql=True, filters={"category": "Thng"})
    outcome = retrieve_structured_data(seeded_db, plan)
    assert not any("인코딩" in hint for hint in outcome["insufficiency_hints"])


def test_sample_announcements_use_display_fallback(isolated_db):
    """표본 공고는 건너뛸 수 없으므로 화면과 같은 안내 문구로 대체합니다."""
    isolated_db.add(
        BidAnnouncement(
            bid_ntce_no="A9999",
            bid_ntce_ord="000",
            category="Cnstwk",
            bid_ntce_nm=CORRUPTED_WINNER,
            dminstt_nm=CORRUPTED_WINNER,
            bid_ntce_dt=datetime(2026, 5, 1),
            collected_at=datetime(2026, 5, 1),
        )
    )
    isolated_db.commit()

    plan = RetrievalPlan(use_sql=True, filters={"category": "Cnstwk"})
    samples = retrieve_structured_data(isolated_db, plan)["summary"]["sample_announcements"]
    assert samples[0]["bid_ntce_nm"] == CORRUPTED_TEXT_FALLBACKS["title"]
    assert samples[0]["dminstt_nm"] == CORRUPTED_TEXT_FALLBACKS["agency"]
