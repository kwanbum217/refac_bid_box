"""
tests/test_skipped_marker_always_recorded.py

손상 제외 마커 상시 기록 계약 검증.

배경: 스냅샷 재구축이 손상이 있을 때만 rank=0 마커 행을 썼다. 손상이 없는
차원은 확인했다는 사실 자체를 버렸고, get_skipped_count 가 돌려주는 0 이
"모른다" 와 "깨끗하다" 를 구분하지 못해 실시간 경로가 매번 40 초짜리
corrupted_probe 를 돌렸다. 이 파일은 다음을 고정한다.

1. 재구축 후 마커 행이 손상 유무와 무관하게 항상 생긴다 (있으면 1, 없으면 0).
2. 마커 존재 여부를 값과 분리해 읽는 함수가 None 과 int 를 구분한다.
3. 마커가 존재하면 탐침을 호출하지 않고, 없을 때만 종전대로 호출한다.
4. 마커 0 일 때 dropped 는 0, 마커 1 일 때 dropped 는 1 이다.

탐침 호출 여부는 실제 호출 횟수로 검증하고 시간으로 검증하지 않는다.
"""

from datetime import datetime

import pytest
from sqlalchemy import func, select

from src.app.core.cache import cache
from src.app.models.bids import BidAnnouncement, BidRankingSnapshot, BidResult
from src.app.services.ranking_snapshots import (
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    SKIPPED_MARKER_RANK,
    get_skipped_count,
    get_skipped_marker,
    rebuild_ranking_snapshots,
)
from src.rag import structured_data


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


def _seed_clean(db):
    """손상값이 하나도 없는 물품 2건."""
    base = datetime(2026, 5, 1, 9, 0, 0)
    for index, winner in enumerate(["가나기업", "가나기업"]):
        db.add(
            BidResult(
                bid_ntce_no=f"CL{index:04d}",
                bid_ntce_ord="00",
                category="Thng",
                bidwinnr_nm=winner,
                dminstt_nm="서울시",
                rl_openg_dt=base,
                collected_at=base,
            )
        )
    db.commit()


def _seed_corrupted(db):
    """손상값이 정상값보다 많은 건설 데이터."""
    base = datetime(2026, 5, 1, 9, 0, 0)
    corrupted = "깨진 업체명 \ufffd"
    for index in range(3):
        db.add(
            BidResult(
                bid_ntce_no=f"CR{index:04d}",
                bid_ntce_ord="00",
                category="Cnstwk",
                bidwinnr_nm=corrupted,
                dminstt_nm="대전시",
                rl_openg_dt=base,
                collected_at=base,
            )
        )
    db.add(
        BidResult(
            bid_ntce_no="CR0009",
            bid_ntce_ord="00",
            category="Cnstwk",
            bidwinnr_nm="정상건설",
            dminstt_nm="대전시",
            rl_openg_dt=base,
            collected_at=base,
        )
    )
    db.commit()


def _marker_row(db, dataset, dimension, category):
    return (
        db.query(BidRankingSnapshot)
        .filter(
            BidRankingSnapshot.dataset == dataset,
            BidRankingSnapshot.dimension == dimension,
            BidRankingSnapshot.category == category,
            BidRankingSnapshot.rank == SKIPPED_MARKER_RANK,
        )
        .one_or_none()
    )


# --------------------------------------------------------------------------- #
# 재구축은 마커를 항상 기록한다
# --------------------------------------------------------------------------- #


def test_clean_dimension_still_gets_zero_marker(isolated_db):
    """손상이 없어도 확인했다는 사실을 마커 0 으로 남긴다."""
    _seed_clean(isolated_db)
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    row = _marker_row(isolated_db, DATASET_RESULT, "bidwinnr_nm", "Thng")
    assert row is not None
    assert int(row.metric_count) == 0


def test_corrupted_dimension_gets_one_marker(isolated_db):
    """손상이 있으면 마커 1 을 남긴다."""
    _seed_corrupted(isolated_db)
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    row = _marker_row(isolated_db, DATASET_RESULT, "bidwinnr_nm", "Cnstwk")
    assert row is not None
    assert int(row.metric_count) == 1


def test_marker_presence_is_separated_from_value(isolated_db):
    """마커 없음(None)과 마커 0 을 구분한다."""
    _seed_clean(isolated_db)

    assert get_skipped_marker(isolated_db, DATASET_RESULT, "bidwinnr_nm", "Thng") is None

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    assert get_skipped_marker(isolated_db, DATASET_RESULT, "bidwinnr_nm", "Thng") == 0


def test_get_skipped_count_signature_and_meaning_unchanged(isolated_db):
    """기존 함수는 그대로 둔다. 없음도 0, 마커 0 도 0 을 돌려준다."""
    _seed_clean(isolated_db)

    assert get_skipped_count(isolated_db, DATASET_RESULT, "bidwinnr_nm", "Thng") == 0

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    assert get_skipped_count(isolated_db, DATASET_RESULT, "bidwinnr_nm", "Thng") == 0


def test_zero_marker_does_not_leak_into_rankings(isolated_db):
    """metric_count 0 마커 행이 순위 결과에 섞이지 않는다."""
    from src.app.services.ranking_snapshots import get_top_rankings

    _seed_clean(isolated_db)
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    rows = get_top_rankings(isolated_db, DATASET_RESULT, "bidwinnr_nm", "Thng", 5)
    assert rows == [("가나기업", 2)]
    assert all(count > 0 for _, count in rows)


# --------------------------------------------------------------------------- #
# 마커 존재 시 탐침을 돌지 않는다 (호출 횟수로 검증)
# --------------------------------------------------------------------------- #


class _LiveResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _ProbeResult:
    def __init__(self, hit):
        self._hit = hit

    def first(self):
        return (1,) if self._hit else None


class _CountingSession:
    """순위 질의와 탐침 질의를 구분해 세고, 마커는 scalar 로 돌려준다.

    marker 가 None 이면 마커 행이 없는 것이고, int 면 존재하는 것이다.
    """

    def __init__(self, rows, *, marker=None, probe_hit=False):
        self._rows = rows
        self._marker = marker
        self._probe_hit = probe_hit
        self.live_executions = 0
        self.probe_executions = 0

    def execute(self, stmt):
        if self.live_executions == 0:
            self.live_executions += 1
            return _LiveResult(self._rows)
        self.probe_executions += 1
        return _ProbeResult(self._probe_hit)

    def scalar(self, stmt=None):
        return self._marker


def _live_stmt():
    return (
        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .group_by(BidResult.bidwinnr_nm)
        .order_by(func.count(BidResult.id).desc())
    )


def _probe_stmt():
    return select(BidResult.id)


def _top(db, **kwargs):
    return structured_data._top_rows(
        db,
        scope=None,
        dataset=DATASET_RESULT,
        dimension="bidwinnr_nm",
        category="",
        live_stmt=_live_stmt(),
        corrupted_probe=_probe_stmt(),
        **kwargs,
    )


def test_probe_skipped_when_zero_marker_present():
    """마커 0 은 깨끗하다는 확정이라 탐침을 돌지 않는다."""
    db = _CountingSession([("정상건설", 50)], marker=0, probe_hit=True)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50)]
    assert dropped == 0
    assert db.live_executions == 1
    assert db.probe_executions == 0


def test_probe_skipped_when_one_marker_present():
    """마커 1 은 제외가 있었다는 확정이라 탐침을 돌지 않는다."""
    db = _CountingSession([("정상건설", 50)], marker=1, probe_hit=False)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50)]
    assert dropped == 1
    assert db.live_executions == 1
    assert db.probe_executions == 0


def test_probe_runs_when_marker_absent():
    """마커가 아예 없을 때만 종전대로 탐침을 실행한다."""
    db = _CountingSession([("정상건설", 50)], marker=None, probe_hit=True)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50)]
    assert dropped == 1
    assert db.live_executions == 1
    assert db.probe_executions == 1


def test_probe_confirms_zero_when_marker_absent_and_clean():
    """마커가 없고 탐침도 빗나가면 dropped 는 0 이다."""
    db = _CountingSession([("정상건설", 50)], marker=None, probe_hit=False)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50)]
    assert dropped == 0
    assert db.live_executions == 1
    assert db.probe_executions == 1


def test_window_corruption_still_skips_probe_without_marker():
    """가져온 창에 손상값이 있으면 마커 없이도 탐침을 돌지 않는다."""
    db = _CountingSession([("손상업체\ufffd", 100), ("정상건설", 50)], marker=None)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50)]
    assert dropped == 1
    assert db.live_executions == 1
    assert db.probe_executions == 0


def test_rebuilt_zero_marker_suppresses_probe_end_to_end(isolated_db, monkeypatch):
    """재구축으로 생긴 마커 0 이 실제 _top_rows 에서 탐침을 막는다."""
    _seed_clean(isolated_db)
    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    probe_calls = []
    real_execute = isolated_db.execute

    def counting_execute(stmt, *args, **kwargs):
        result = real_execute(stmt, *args, **kwargs)
        compiled = str(stmt.compile(compile_kwargs={"literal_binds": True}))
        if "bidwinnr_nm" in compiled and "LIKE" in compiled:
            probe_calls.append(compiled)
        return result

    monkeypatch.setattr(isolated_db, "execute", counting_execute)

    live_stmt = (
        select(BidResult.bidwinnr_nm, func.count(BidResult.id))
        .where(BidResult.category == "Thng")
        .group_by(BidResult.bidwinnr_nm)
        .order_by(func.count(BidResult.id).desc())
    )
    probe_stmt = select(BidResult.id).where(BidResult.bidwinnr_nm.contains("\ufffd"))

    kept, dropped = structured_data._top_rows(
        isolated_db,
        scope=None,
        dataset=DATASET_RESULT,
        dimension="bidwinnr_nm",
        category="Thng",
        live_stmt=live_stmt,
        corrupted_probe=probe_stmt,
    )

    assert dropped == 0
    assert kept
    assert probe_calls == []


def test_announcement_marker_always_recorded(isolated_db):
    """공고 차원도 손상 유무와 무관하게 마커가 생긴다."""
    base = datetime(2026, 5, 1, 9, 0, 0)
    isolated_db.add(
        BidAnnouncement(
            bid_ntce_no="AM0001",
            bid_ntce_ord="000",
            category="Thng",
            bid_ntce_nm="서울시 물품 구매",
            dminstt_nm="서울시",
            bid_ntce_dt=base,
            collected_at=base,
        )
    )
    isolated_db.commit()

    rebuild_ranking_snapshots(isolated_db, force_weekly=True)

    row = _marker_row(isolated_db, DATASET_ANNOUNCEMENT, "dminstt_nm", "Thng")
    assert row is not None
    assert int(row.metric_count) == 0
