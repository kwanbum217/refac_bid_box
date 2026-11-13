"""
tests/test_prearng_empty_skip_20261113.py

예비가격 자료 없음 공고 제외(2026-11-13) 검증.

막으려는 사고:
  - 정상 응답 0건과 실패 응답(429·401·네트워크)을 구분하지 않아 실패한 공고를
    자료 없음으로 굳히는 것
  - 자료 없음 기록이 TTL 없이 영구 제외가 되는 것
  - Redis 장애가 수집이나 후보 선택을 멈추게 하는 것
  - 제외 뒤 후보 수가 limit 보다 적어지거나 SQL 정렬 순서가 흐트러지는 것

나라장터 API 와 운영 DB·Redis 는 대역(double)으로 대체하며 실호출과 쓰기를
하지 않습니다.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

import scripts.backfill_prearng_by_notices as bf
from src.app.core.db import Base
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.models.prearng_prices import BidPrearngPrice
from src.app.services import api_collector
from src.app.services.api_collector import (
    PREARNG_EMPTY_SKIP_PREFIX,
    PREARNG_EMPTY_SKIP_TTL_SECONDS,
    stream_servc_prearng_by_notices,
)
from src.tasks.scheduled_tasks import select_new_servc_notices


class _FakeCache:
    """CacheLayer 대역. set/get 만 흉내 냅니다."""

    def __init__(self, *, write_error: bool = False, read_error: bool = False) -> None:
        self.values: dict[str, Any] = {}
        self.ttls: dict[str, int] = {}
        self.write_error = write_error
        self.read_error = read_error

    def set(self, key: str, value: Any, ttl: int) -> None:
        if self.write_error:
            raise RuntimeError("redis down")
        self.values[key] = value
        self.ttls[key] = ttl

    def get(self, key: str) -> Any:
        if self.read_error:
            raise RuntimeError("redis down")
        return self.values.get(key)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[BidAnnouncement.__table__, BidPrearngPrice.__table__],
    )
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _add_announcement(session: Any, notice_no: str, openg_dt: datetime) -> None:
    session.add(BidAnnouncement(bid_ntce_no=notice_no, category="Servc", openg_dt=openg_dt))


# ============================================================================
# 1. 정상 응답 0건만 기록하고 TTL 을 건다
# ============================================================================


async def test_empty_response_is_recorded_with_ttl(monkeypatch) -> None:
    cache = _FakeCache()
    monkeypatch.setattr(api_collector, "_prearng_empty_cache", cache)

    async def _empty(client, sem, bid_ntce_no, num_of_rows):
        return []

    monkeypatch.setattr(api_collector, "_fetch_prearng_notice", _empty)

    saved = await stream_servc_prearng_by_notices(["R-EMPTY"], lambda rows: len(rows))

    assert saved == 0
    assert cache.values == {f"{PREARNG_EMPTY_SKIP_PREFIX}R-EMPTY": 1}
    assert cache.ttls[f"{PREARNG_EMPTY_SKIP_PREFIX}R-EMPTY"] == 3 * 24 * 3600
    assert PREARNG_EMPTY_SKIP_TTL_SECONDS == 3 * 24 * 3600


# ============================================================================
# 2. 실패 응답은 기록하지 않는다
# ============================================================================


async def test_failed_response_is_not_recorded(monkeypatch) -> None:
    cache = _FakeCache()
    monkeypatch.setattr(api_collector, "_prearng_empty_cache", cache)

    async def _fail(client, sem, bid_ntce_no, num_of_rows):
        raise RuntimeError("429 Too Many Requests")

    monkeypatch.setattr(api_collector, "_fetch_prearng_notice", _fail)

    with pytest.raises(api_collector.RangeCollectionError):
        await stream_servc_prearng_by_notices(["R-FAIL"], lambda rows: len(rows))

    assert cache.values == {}


# ============================================================================
# 3. 기록된 공고는 후보에서 빠지고 limit 은 유지된다
# ============================================================================


def test_recorded_notice_is_excluded_and_limit_kept(db_session, monkeypatch) -> None:
    cache = _FakeCache()
    monkeypatch.setattr(api_collector, "_prearng_empty_cache", cache)

    now = utcnow()
    for index in range(5):
        _add_announcement(db_session, f"R-{index:03d}", now - timedelta(days=1))
    db_session.commit()
    cache.values[f"{PREARNG_EMPTY_SKIP_PREFIX}R-000"] = 1

    excluded: list[int] = []
    result = select_new_servc_notices(db_session, now=now, limit=2, excluded_out=excluded)

    assert result == ["R-001", "R-002"]
    assert len(result) == 2
    assert result == sorted(result)
    assert excluded == [1]


def test_candidates_stay_sorted_after_exclusion(db_session, monkeypatch) -> None:
    cache = _FakeCache()
    monkeypatch.setattr(api_collector, "_prearng_empty_cache", cache)

    now = utcnow()
    for notice in ["R-A", "R-B", "R-C", "R-D"]:
        _add_announcement(db_session, notice, now - timedelta(days=1))
    db_session.commit()
    cache.values[f"{PREARNG_EMPTY_SKIP_PREFIX}R-B"] = 1

    result = select_new_servc_notices(db_session, now=now, limit=3)

    assert result == ["R-A", "R-C", "R-D"]


def test_backfill_candidates_use_same_exclusion(db_session, monkeypatch) -> None:
    cache = _FakeCache()
    monkeypatch.setattr(api_collector, "_prearng_empty_cache", cache)

    _add_announcement(db_session, "R-EMPTY", datetime(2026, 11, 1, 10, 0))
    _add_announcement(db_session, "R-KEEP", datetime(2026, 11, 1, 11, 0))
    db_session.commit()
    cache.values[f"{PREARNG_EMPTY_SKIP_PREFIX}R-EMPTY"] = 1

    excluded: list[int] = []
    candidates = bf.select_backfill_candidates(
        db_session,
        since=date(2026, 10, 12),
        until=date(2026, 11, 10),
        limit=10,
        excluded_out=excluded,
    )

    assert [notice for notice, _ in candidates] == ["R-KEEP"]
    assert excluded == [1]


def test_dry_run_prints_excluded_count(db_session, monkeypatch, capsys) -> None:
    cache = _FakeCache()
    monkeypatch.setattr(api_collector, "_prearng_empty_cache", cache)

    _add_announcement(db_session, "R-EMPTY", datetime(2026, 11, 1, 10, 0))
    _add_announcement(db_session, "R-KEEP", datetime(2026, 11, 1, 11, 0))
    db_session.commit()
    cache.values[f"{PREARNG_EMPTY_SKIP_PREFIX}R-EMPTY"] = 1

    monkeypatch.setattr(bf, "SessionLocal", lambda: db_session)

    code = bf.run(["--since", "2026-10-12", "--until", "2026-11-10"])

    assert code == 0
    assert "자료 없음 제외 1건" in capsys.readouterr().out


# ============================================================================
# 4. 캐시 오류는 fail-open 이다
# ============================================================================


def test_cache_read_failure_keeps_candidates(db_session, monkeypatch) -> None:
    monkeypatch.setattr(api_collector, "_prearng_empty_cache", _FakeCache(read_error=True))

    now = utcnow()
    _add_announcement(db_session, "R-A", now - timedelta(days=1))
    _add_announcement(db_session, "R-B", now - timedelta(days=1))
    db_session.commit()

    assert select_new_servc_notices(db_session, now=now, limit=5) == ["R-A", "R-B"]


async def test_cache_write_failure_does_not_stop_collection(monkeypatch) -> None:
    monkeypatch.setattr(api_collector, "_prearng_empty_cache", _FakeCache(write_error=True))

    async def _empty(client, sem, bid_ntce_no, num_of_rows):
        return []

    monkeypatch.setattr(api_collector, "_fetch_prearng_notice", _empty)

    assert await stream_servc_prearng_by_notices(["R-EMPTY"], lambda rows: len(rows)) == 0
