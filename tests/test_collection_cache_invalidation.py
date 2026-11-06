"""정기 수집 종료 시 RAG 집계 캐시 무효화 검증."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from src.app.core.cache import cache
from src.rag.structured_data import invalidate_rag_aggregate_cache


class _FakeRedis:
    """scan_iter/delete 만 지원하는 Redis 대역입니다.

    keys() 를 두지 않아 무효화 경로가 KEYS 를 쓰면 즉시 실패합니다.
    """

    def __init__(self, keys: list[str]) -> None:
        self.data = dict.fromkeys(keys, "1")
        self.scan_patterns: list[str] = []

    def scan_iter(self, match=None, count=None):
        self.scan_patterns.append(match or "")
        prefix = (match or "").rstrip("*")
        for key in list(self.data):
            if key.startswith(prefix):
                yield key

    def delete(self, key: str) -> int:
        return 1 if self.data.pop(key, None) is not None else 0


def test_invalidate_deletes_only_aggregate_prefixes(monkeypatch):
    fake = _FakeRedis(
        [
            "rag:agg:aaa",
            "rag:rows:bbb",
            "rag:top:ccc",
            "rag:inst:ddd",
            "rag:inst_catalog:bid_announcements",
            "dashboard:stats",
        ]
    )
    monkeypatch.setattr(cache._conn, "client", lambda: fake)

    deleted = invalidate_rag_aggregate_cache()

    assert deleted == 3
    assert set(fake.data) == {
        "rag:inst:ddd",
        "rag:inst_catalog:bid_announcements",
        "dashboard:stats",
    }
    assert set(fake.scan_patterns) == {"rag:agg:*", "rag:rows:*", "rag:top:*"}


def test_invalidate_purges_local_memory_aggregate_keys(monkeypatch):
    monkeypatch.setattr(cache._conn, "client", lambda: None)
    monkeypatch.setattr(
        cache,
        "_local",
        {
            "rag:agg:aaa": (float("inf"), 1),
            "rag:rows:bbb": (float("inf"), 1),
            "rag:top:ccc": (float("inf"), 1),
            "rag:inst:ddd": (float("inf"), 1),
            "rag:inst_catalog:bid_announcements": (float("inf"), 1),
        },
    )

    deleted = invalidate_rag_aggregate_cache()

    assert deleted == 3
    assert set(cache._local) == {
        "rag:inst:ddd",
        "rag:inst_catalog:bid_announcements",
    }


def _patch_collection(monkeypatch, svc, announcement_count: int) -> None:
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=announcement_count))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))


@pytest.mark.asyncio
async def test_collect_bids_invalidates_once_when_rows_inserted(isolated_db, monkeypatch):
    import src.app.services.collector_service as svc
    import src.rag.structured_data as sd

    calls: list[str] = []
    monkeypatch.setattr(
        sd, "invalidate_rag_aggregate_cache", lambda: calls.append("invalidate") or 0
    )
    _patch_collection(monkeypatch, svc, announcement_count=3)

    result = await svc.collect_bids(
        isolated_db,
        start_date="20260810",
        end_date="20260812",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["announcement_count"] == 3
    assert calls == ["invalidate"]


@pytest.mark.asyncio
async def test_collect_bids_skips_invalidation_when_nothing_inserted(isolated_db, monkeypatch):
    import src.app.services.collector_service as svc
    import src.rag.structured_data as sd

    calls: list[str] = []
    monkeypatch.setattr(
        sd, "invalidate_rag_aggregate_cache", lambda: calls.append("invalidate") or 0
    )
    _patch_collection(monkeypatch, svc, announcement_count=0)

    result = await svc.collect_bids(
        isolated_db,
        start_date="20260810",
        end_date="20260812",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["total_records"] == 0
    assert calls == []


@pytest.mark.asyncio
async def test_invalidation_failure_does_not_change_collection_result(isolated_db, monkeypatch):
    import src.app.services.collector_service as svc
    import src.rag.structured_data as sd

    def _raise() -> int:
        raise RuntimeError("redis unavailable")

    monkeypatch.setattr(sd, "invalidate_rag_aggregate_cache", _raise)
    _patch_collection(monkeypatch, svc, announcement_count=2)

    result = await svc.collect_bids(
        isolated_db,
        start_date="20260810",
        end_date="20260812",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["announcement_count"] == 2
    assert result["status"] == "success"


@pytest.mark.asyncio
async def test_invalidation_runs_before_cache_warming(isolated_db, monkeypatch):
    import src.app.services.collector_service as svc
    import src.rag.structured_data as sd

    order: list[str] = []
    monkeypatch.setattr(
        sd, "invalidate_rag_aggregate_cache", lambda: order.append("invalidate") or 0
    )
    monkeypatch.setattr(
        svc,
        "_warm_aggregates_and_caches_sync",
        lambda _datasets, bind=None: order.append("warm"),
    )
    _patch_collection(monkeypatch, svc, announcement_count=1)

    await svc.collect_bids(
        isolated_db,
        start_date="20260810",
        end_date="20260812",
        categories=("Thng",),
        refresh_aggregates=True,
    )

    assert order == ["invalidate", "warm"]
