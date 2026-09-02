import threading
import time
from unittest.mock import MagicMock

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from src.app.api.v1 import health
from src.app.api.v1.health import warmup_state
from src.app.core.cache import cache
from src.app.core.config import settings
from src.app.main import app
from src.app.models.bids import BidResult
from src.rag.structured_data import _cached_aggregate, _stmt_cache_key, _top_rows

client = TestClient(app)


def _patch_dependencies_healthy(monkeypatch):
    for name in (
        "_check_mysql",
        "_check_redis",
        "_check_meilisearch",
        "_check_model_registry",
        "_check_chromadb",
    ):
        monkeypatch.setattr(health, name, lambda: None)


def test_concurrent_cold_aggregate_single_flight():
    stmt = select(func.count(BidResult.id)).where(BidResult.id == 11111)
    key = _stmt_cache_key("rag:agg:", stmt)
    cache.delete(key)

    calls = 0
    start_event = threading.Event()
    finish_event = threading.Event()

    class MockResult:
        def one(self):
            return (100, 87.5, 5000000)

    def slow_execute(statement):
        nonlocal calls
        calls += 1
        start_event.set()
        assert finish_event.wait(timeout=2)
        return MockResult()

    mock_db = MagicMock()
    mock_db.execute.side_effect = slow_execute

    results = []
    errors = []

    def run_query():
        try:
            res = _cached_aggregate(mock_db, stmt)
            results.append(res)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=run_query)
    t2 = threading.Thread(target=run_query)
    t3 = threading.Thread(target=run_query)

    t1.start()
    assert start_event.wait(timeout=2)

    t2.start()
    t3.start()

    time.sleep(0.05)
    finish_event.set()

    t1.join(timeout=2)
    t2.join(timeout=2)
    t3.join(timeout=2)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert not t3.is_alive()
    assert not errors
    assert len(results) == 3
    assert calls == 1
    assert results[0] == [100.0, 87.5, 5000000.0]
    assert results[1] == [100.0, 87.5, 5000000.0]
    assert results[2] == [100.0, 87.5, 5000000.0]


def test_concurrent_cold_top_rows_single_flight():
    stmt = select(BidResult.bidwinnr_nm, func.count(BidResult.id)).where(BidResult.id == 22222)
    key = _stmt_cache_key("rag:top:", stmt.limit(15))
    cache.delete(key)

    calls = 0
    start_event = threading.Event()
    finish_event = threading.Event()

    def slow_execute(statement):
        nonlocal calls
        calls += 1
        start_event.set()
        assert finish_event.wait(timeout=2)
        mock_res = MagicMock()
        mock_res.all.return_value = [("업체A", 10), ("업체B", 5)]
        return mock_res

    mock_db = MagicMock()
    mock_db.execute.side_effect = slow_execute

    results = []
    errors = []

    def run_query():
        try:
            res = _top_rows(
                mock_db,
                scope=None,
                dataset="result",
                dimension="bidwinnr_nm",
                live_stmt=stmt,
                limit=5,
            )
            results.append(res)
        except Exception as e:
            errors.append(e)

    t1 = threading.Thread(target=run_query)
    t2 = threading.Thread(target=run_query)

    t1.start()
    assert start_event.wait(timeout=2)
    t2.start()

    time.sleep(0.05)
    finish_event.set()

    t1.join(timeout=2)
    t2.join(timeout=2)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert not errors
    assert len(results) == 2
    assert calls == 1
    assert results[0] == results[1]
    assert results[0][0] == [("업체A", 10), ("업체B", 5)]


def test_single_flight_error_does_not_deadlock_subsequent_callers():
    stmt = select(func.count(BidResult.id)).where(BidResult.id == 33333)
    key = _stmt_cache_key("rag:agg:", stmt)
    cache.delete(key)

    calls = 0
    t1_started = threading.Event()
    t1_allow_fail = threading.Event()

    def failing_then_succeeding_execute(statement):
        nonlocal calls
        calls += 1
        if calls == 1:
            t1_started.set()
            assert t1_allow_fail.wait(timeout=2)
            raise RuntimeError("DB connection dropped")
        mock_res = MagicMock()
        mock_res.one.return_value = (42, 90.0, 1000)
        return mock_res

    mock_db = MagicMock()
    mock_db.execute.side_effect = failing_then_succeeding_execute

    t1_error = []
    t2_result = []
    t2_error = []

    def run_t1():
        try:
            _cached_aggregate(mock_db, stmt)
        except Exception as e:
            t1_error.append(e)

    def run_t2():
        try:
            res = _cached_aggregate(mock_db, stmt)
            t2_result.append(res)
        except Exception as e:
            t2_error.append(e)

    t1 = threading.Thread(target=run_t1)
    t2 = threading.Thread(target=run_t2)

    t1.start()
    assert t1_started.wait(timeout=2)
    t2.start()

    time.sleep(0.05)
    t1_allow_fail.set()

    t1.join(timeout=2)
    t2.join(timeout=2)

    assert not t1.is_alive()
    assert not t2.is_alive()
    assert len(t1_error) == 1
    assert isinstance(t1_error[0], RuntimeError)
    assert t2_result == [[42.0, 90.0, 1000.0]]
    assert calls == 2


def test_readiness_includes_warmup_and_llm_status(monkeypatch):
    _patch_dependencies_healthy(monkeypatch)
    warmup_state.reset()
    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {"ok": True, "provider": "ollama", "detail": None, "latency_ms": 1.5},
    )

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert "warmup" in data
    assert data["warmup"]["completed"] is True
    assert "llm" in data
    assert data["llm"]["ok"] is True
    assert data["llm"]["provider"] == "ollama"


def test_readiness_is_degraded_when_warmup_incomplete(monkeypatch):
    _patch_dependencies_healthy(monkeypatch)
    warmup_state.start()
    # predictor and vector are still incomplete
    warmup_state.mark_llm_done(success=True)
    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {"ok": True, "provider": "ollama", "detail": None, "latency_ms": 1.0},
    )

    response = client.get("/api/v1/health/ready")
    # By default, warmup incomplete is degraded, not 503
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["warmup"]["completed"] is False
    assert data["warmup"]["details"]["llm"]["ok"] is True
    assert data["warmup"]["details"]["predictor"]["ok"] is False


def test_readiness_is_degraded_when_llm_unavailable(monkeypatch):
    _patch_dependencies_healthy(monkeypatch)
    warmup_state.reset()
    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {
            "ok": False,
            "provider": "ollama",
            "detail": "llm_service_unavailable",
            "latency_ms": 2.0,
        },
    )

    response = client.get("/api/v1/health/ready")
    # By default, LLM unavailable is degraded, not 503
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["llm"]["ok"] is False


def test_readiness_promotes_warmup_to_not_ready_with_settings(monkeypatch):
    _patch_dependencies_healthy(monkeypatch)
    warmup_state.start()
    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {"ok": True, "provider": "ollama", "detail": None, "latency_ms": 1.0},
    )
    monkeypatch.setattr(settings, "READINESS_REQUIRE_WARMUP", True)

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["warmup"]["completed"] is False


def test_readiness_promotes_llm_to_not_ready_with_settings(monkeypatch):
    _patch_dependencies_healthy(monkeypatch)
    warmup_state.reset()
    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {
            "ok": False,
            "provider": "ollama",
            "detail": "llm_service_unavailable",
            "latency_ms": 2.0,
        },
    )
    monkeypatch.setattr(settings, "READINESS_REQUIRE_LLM", True)

    response = client.get("/api/v1/health/ready")
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["llm"]["ok"] is False


def test_flight_locks_dictionary_does_not_leak_memory():
    from src.rag.structured_data import _flight_locks

    mock_db = MagicMock()
    mock_db.execute.return_value.one.return_value = (1, 80.0, 1000)

    for i in range(100):
        stmt = select(func.count(BidResult.id)).where(BidResult.id == 900000 + i)
        _cached_aggregate(mock_db, stmt)

    assert len(_flight_locks) == 0

    stmt_concurrent = select(func.count(BidResult.id)).where(BidResult.id == 999999)
    key_concurrent = _stmt_cache_key("rag:agg:", stmt_concurrent)
    cache.delete(key_concurrent)

    start_event = threading.Event()
    finish_event = threading.Event()

    def slow_exec(st):
        start_event.set()
        assert finish_event.wait(timeout=2)
        mock_res = MagicMock()
        mock_res.one.return_value = (2, 85.0, 2000)
        return mock_res

    mock_db.execute.side_effect = slow_exec

    threads = [
        threading.Thread(target=lambda: _cached_aggregate(mock_db, stmt_concurrent))
        for _ in range(5)
    ]
    for t in threads:
        t.start()

    assert start_event.wait(timeout=2)
    assert key_concurrent in _flight_locks
    assert _flight_locks[key_concurrent].ref_count >= 1

    finish_event.set()
    for t in threads:
        t.join(timeout=2)

    assert key_concurrent not in _flight_locks
    assert len(_flight_locks) == 0
