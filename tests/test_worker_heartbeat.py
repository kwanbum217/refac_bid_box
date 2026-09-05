import asyncio

import pytest

from src.app.api.v1 import health
from src.app.core import cache as cache_module
from src.tasks import worker


class FakeCache:
    def __init__(self, redis_client=None):
        self.values = {}
        self._redis_client = redis_client

    def client(self):
        return self._redis_client

    def get(self, key):
        return self.values.get(key)

    def set(self, key, value, ttl):
        self.values[key] = value


class FakeRedis:
    def __init__(self):
        self.zsets: dict[str, dict[str, float]] = {}

    def zadd(self, name: str, mapping: dict[str, float]) -> int:
        if name not in self.zsets:
            self.zsets[name] = {}
        added = 0
        for member, score in mapping.items():
            if member not in self.zsets[name]:
                added += 1
            self.zsets[name][member] = float(score)
        return added

    def zcard(self, name: str) -> int:
        return len(self.zsets.get(name, {}))

    def zcount(self, name: str, min_score: str | float, max_score: str | float) -> int:
        members = self.zsets.get(name, {})
        low = float("-inf") if str(min_score) == "-inf" else float(min_score)
        high = float("+inf") if str(max_score) in ("+inf", "inf") else float(max_score)
        return sum(1 for score in members.values() if low <= score <= high)

    def llen(self, _key: str) -> int:
        raise RuntimeError("WRONGTYPE Operation against a key holding the wrong kind of value")


def test_fake_redis_raises_wrongtype_on_llen():
    fake_redis = FakeRedis()
    with pytest.raises(RuntimeError, match="WRONGTYPE"):
        fake_redis.llen(worker.ARQ_QUEUE_KEY)


def test_record_worker_heartbeat_case1_ready_jobs(monkeypatch):
    """대기 작업이 있는 경우: pending > 0, status='ok'."""
    now_ms = 1_700_000_000_000
    now_iso = "2026-09-02T00:00:00+00:00"

    fake_redis = FakeRedis()
    fake_redis.zadd(
        worker.ARQ_QUEUE_KEY,
        {
            "job_past": float(now_ms - 5000),
            "job_now": float(now_ms),
            "job_future": float(now_ms + 10000),
        },
    )

    fake_cache = FakeCache()
    monkeypatch.setattr(fake_cache, "client", lambda: fake_redis)
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)
    monkeypatch.setattr(worker, "_now_iso", lambda: now_iso)
    monkeypatch.setattr(worker.time, "time", lambda: now_ms / 1000.0)

    worker.record_worker_heartbeat()

    assert fake_cache.values[worker.WORKER_HEARTBEAT_KEY] == {
        "worker_id": worker._worker_id,
        "last_seen_at": now_iso,
    }
    assert fake_cache.values[worker.QUEUE_BACKLOG_KEY] == {
        "status": "ok",
        "pending": 2,
        "total": 3,
        "deferred": 1,
        "observed_at": now_iso,
    }
    assert worker._redis_queue_length() == 2


def test_record_worker_heartbeat_case2_future_scheduled_only(monkeypatch):
    """미래 예약만 있는 경우: pending = 0, total > 0, deferred > 0, status='ok'."""
    now_ms = 1_700_000_000_000
    now_iso = "2026-09-02T00:00:00+00:00"

    fake_redis = FakeRedis()
    fake_redis.zadd(
        worker.ARQ_QUEUE_KEY,
        {
            "job_future_1": float(now_ms + 3000),
            "job_future_2": float(now_ms + 6000),
        },
    )

    fake_cache = FakeCache()
    monkeypatch.setattr(fake_cache, "client", lambda: fake_redis)
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)
    monkeypatch.setattr(worker, "_now_iso", lambda: now_iso)
    monkeypatch.setattr(worker.time, "time", lambda: now_ms / 1000.0)

    worker.record_worker_heartbeat()

    assert fake_cache.values[worker.WORKER_HEARTBEAT_KEY] == {
        "worker_id": worker._worker_id,
        "last_seen_at": now_iso,
    }
    assert fake_cache.values[worker.QUEUE_BACKLOG_KEY] == {
        "status": "ok",
        "pending": 0,
        "total": 2,
        "deferred": 2,
        "observed_at": now_iso,
    }
    # 단순 ZCARD와 달리 대기 작업 수(0)를 정확히 반영
    assert worker._redis_queue_length() == 0


def test_record_worker_heartbeat_case3_empty_queue(monkeypatch):
    """빈 큐인 경우: pending = 0, total = 0, deferred = 0, status='ok'."""
    now_ms = 1_700_000_000_000
    now_iso = "2026-09-02T00:00:00+00:00"

    fake_redis = FakeRedis()
    fake_cache = FakeCache()
    monkeypatch.setattr(fake_cache, "client", lambda: fake_redis)
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)
    monkeypatch.setattr(worker, "_now_iso", lambda: now_iso)
    monkeypatch.setattr(worker.time, "time", lambda: now_ms / 1000.0)

    worker.record_worker_heartbeat()

    assert fake_cache.values[worker.WORKER_HEARTBEAT_KEY] == {
        "worker_id": worker._worker_id,
        "last_seen_at": now_iso,
    }
    assert fake_cache.values[worker.QUEUE_BACKLOG_KEY] == {
        "status": "ok",
        "pending": 0,
        "total": 0,
        "deferred": 0,
        "observed_at": now_iso,
    }
    assert worker._redis_queue_length() == 0


def test_record_worker_heartbeat_case4_connection_failure(monkeypatch):
    """연결 실패/관측 불가인 경우: status='unavailable', pending=None, heartbeat는 정상 기록."""
    now_iso = "2026-09-02T00:00:00+00:00"

    fake_cache = FakeCache()
    monkeypatch.setattr(fake_cache, "client", lambda: None)
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)
    monkeypatch.setattr(worker, "_now_iso", lambda: now_iso)

    worker.record_worker_heartbeat()

    # heartbeat_not_blocked: 관측 실패여도 워커 생존 시각은 정상 기록
    assert fake_cache.values[worker.WORKER_HEARTBEAT_KEY] == {
        "worker_id": worker._worker_id,
        "last_seen_at": now_iso,
    }
    # failure_vs_zero: 적체 0(status='ok', pending=0)과 관측 실패(status='unavailable', pending=None) 구분
    assert fake_cache.values[worker.QUEUE_BACKLOG_KEY] == {
        "status": "unavailable",
        "pending": None,
        "total": None,
        "deferred": None,
        "observed_at": now_iso,
    }
    assert worker._redis_queue_length() is None


def test_record_worker_heartbeat_queue_exception_does_not_block_heartbeat(monkeypatch):
    """적체 조회 중 예외 발생 시에도 워커 생존 시각 기록은 차단되지 않음."""
    now_iso = "2026-09-02T00:00:00+00:00"

    fake_cache = FakeCache()
    monkeypatch.setattr(fake_cache, "client", lambda: None)
    monkeypatch.setattr(worker, "_worker_cache", fake_cache)
    monkeypatch.setattr(worker, "_now_iso", lambda: now_iso)
    monkeypatch.setattr(
        worker,
        "_redis_queue_metrics",
        lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError("redis crash")),
    )

    worker.record_worker_heartbeat()

    assert fake_cache.values[worker.WORKER_HEARTBEAT_KEY] == {
        "worker_id": worker._worker_id,
        "last_seen_at": now_iso,
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
