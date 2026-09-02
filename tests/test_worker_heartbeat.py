import asyncio

import pytest

from src.app.api.v1 import health
from src.app.core import cache as cache_module
from src.tasks import worker


class FakeCache:
    def __init__(self):
        self.values = {}

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ttl):
        self.values[key] = value


class FakeRedis:
    def llen(self, key):
        assert key == worker.ARQ_QUEUE_KEY
        return 3


def test_record_worker_heartbeat_records_identity_and_queue(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(worker, "_worker_cache", fake)
    monkeypatch.setattr(worker, "_redis_queue_length", lambda: 3)
    monkeypatch.setattr(worker, "_now_iso", lambda: "2026-09-02T00:00:00+00:00")

    worker.record_worker_heartbeat()

    assert fake.values[worker.WORKER_HEARTBEAT_KEY] == {
        "worker_id": worker._worker_id,
        "last_seen_at": "2026-09-02T00:00:00+00:00",
    }
    assert fake.values[worker.QUEUE_BACKLOG_KEY] == {
        "pending": 3,
        "observed_at": "2026-09-02T00:00:00+00:00",
    }


def test_schedule_wrapper_records_success_and_failure(monkeypatch):
    fake = FakeCache()
    monkeypatch.setattr(worker, "_worker_cache", fake)
    monkeypatch.setattr(worker, "_now_iso", lambda: "2026-09-02T00:00:00+00:00")

    async def task(_ctx):
        return {"status": "success"}

    from src.tasks.scheduled_tasks import _record_schedule

    tracked = _record_schedule("nightly")(task)
    assert asyncio.run(tracked({})) == {"status": "success"}
    assert fake.values[worker.SCHEDULE_STATUS_KEY]["nightly"] == {
        "last_run_at": "2026-09-02T00:00:00+00:00",
        "success": True,
    }

    async def failing_task(_ctx):
        raise RuntimeError("expected")

    tracked_failure = _record_schedule("weekly")(failing_task)
    with pytest.raises(RuntimeError, match=r"^expected$"):
        asyncio.run(tracked_failure({}))
    assert fake.values[worker.SCHEDULE_STATUS_KEY]["weekly"]["success"] is False


def test_worker_observation_returns_unknown_when_redis_unavailable(monkeypatch):
    class UnavailableCache:
        def get(self, _key):
            raise ConnectionError("redis unavailable")

    monkeypatch.setattr(cache_module, "CacheLayer", UnavailableCache)

    assert health.worker_observation() == {
        "worker": None,
        "queue": None,
        "schedules": None,
    }
