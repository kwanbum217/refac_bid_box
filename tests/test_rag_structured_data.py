"""
tests/test_rag_structured_data.py

손상 탐침(corrupted_probe) 실행 계약 검증.

탐침은 선행 와일드카드(`LIKE concat('%', U+FFFD, '%')`)라 인덱스를 쓰지
못합니다. 날짜 필터가 없으면 3,118,641행을 훑고(2026-09-06 EXPLAIN),
날짜 필터가 있어도 범위 내 약 50만 행을 훑습니다.

비용에도 불구하고 탐침을 없앨 수 없습니다. SQL 이 `exclude_corrupted` 로
손상값을 먼저 걸러 보내므로, 가져온 창이 깨끗한 것과 전체 결과에 손상이
없는 것은 다릅니다. 창이 깨끗하다고 탐침을 생략하면 실제로 제외했는데도
안내가 사라집니다(Wave E1 회귀). 아래 테스트는 그 계약을 고정합니다.
"""

import pytest
from sqlalchemy import func, select

from src.app.core.cache import cache
from src.app.models.bids import BidResult
from src.rag import structured_data


@pytest.fixture(autouse=True)
def isolated_cache(monkeypatch):
    """프로세스 공용 캐시를 테스트마다 비웁니다."""
    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})
    return cache


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


class _TopRowsSession:
    """순위 질의와 탐침 질의를 구분해 세는 세션 대역입니다.

    스냅샷 마커 조회는 `db.scalar` 단일 호출이므로 실행 횟수에 섞이지
    않습니다. 순위 질의가 항상 첫 번째 `execute` 이고 탐침이 두 번째입니다.
    """

    def __init__(self, rows, *, marker=0, probe_hit=False):
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
        dataset="bid_results",
        dimension="bidwinnr_nm",
        category="",
        live_stmt=_live_stmt(),
        corrupted_probe=_probe_stmt(),
        **kwargs,
    )


def test_probe_runs_even_when_ranking_is_filled():
    """창이 깨끗해도 탐침을 생략하지 않습니다. Wave E1 회귀 방지입니다.

    SQL 이 손상값을 먼저 걸러 보내므로 파이썬 계층은 창밖 제외를 셀 수
    없고, 탐침 없이 0을 확정하면 안내가 사라집니다.
    """
    db = _TopRowsSession([("정상건설", 50), ("대한건설", 40)], marker=0, probe_hit=True)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50), ("대한건설", 40)]
    assert dropped == 1
    assert db.live_executions == 1
    assert db.probe_executions == 1


def test_probe_confirms_zero_when_no_corruption():
    """손상이 없으면 탐침이 0을 확정합니다."""
    db = _TopRowsSession([("정상건설", 50)], marker=0, probe_hit=False)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50)]
    assert dropped == 0
    assert db.live_executions == 1
    assert db.probe_executions == 1


def test_snapshot_marker_short_circuits_probe():
    """스냅샷 마커가 있으면 탐침을 돌지 않습니다."""
    db = _TopRowsSession([("정상건설", 50)], marker=1, probe_hit=True)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50)]
    assert dropped == 1
    assert db.live_executions == 1
    assert db.probe_executions == 0


def test_filtered_corruption_skips_probe():
    """가져온 창에 손상값이 있으면 파이썬 계층이 세므로 탐침을 돌지 않습니다."""
    db = _TopRowsSession([("손상업체\ufffd", 100), ("정상건설", 50)], marker=0)

    kept, dropped = _top(db)

    assert kept == [("정상건설", 50)]
    assert dropped == 1
    assert db.live_executions == 1
    assert db.probe_executions == 0


def test_probe_outcome_is_cached():
    """탐침 결과까지 함께 캐시돼 다음 적중 때 DB 를 치지 않습니다."""
    db = _TopRowsSession([("정상건설", 50)], marker=0, probe_hit=True)

    first = _top(db)
    executions_after_first = db.live_executions + db.probe_executions
    second = _top(db)

    assert first == second
    assert db.live_executions + db.probe_executions == executions_after_first
