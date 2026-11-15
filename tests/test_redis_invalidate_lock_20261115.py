"""
tests/test_redis_invalidate_lock_20261115.py

RedisConnection.invalidate() 가 client() 와 같은 잠금을 쓰는지 고정합니다.

invalidate 가 잠금 없이 _client 와 _next_attempt_at 을 쓰면, client() 가 잠금
안에서 새 클라이언트를 만드는 동안 폐기가 끼어들어 두 필드가 서로 다른 시점의
값을 갖습니다. 세 가지를 검사합니다.

1. 연결 시도 중에 들어온 invalidate 는 그 시도가 끝날 때까지 기다린다.
2. 연결된 상태의 invalidate 는 클라이언트를 버리고 백오프 안의 재연결을 막는다.
3. 연결이 없는 상태의 invalidate 는 경고 로그를 남기지 않는다.
"""

from __future__ import annotations

import logging
import sys
import threading
import time

from src.app.core.cache import RedisConnection

BACKOFF = 5.0


class SlowPingClient:
    """ping 이 이벤트로 대기하는 대역입니다. 연결 시도 구간을 붙잡습니다."""

    def __init__(self, entered: threading.Event, release: threading.Event):
        self._entered = entered
        self._release = release

    def ping(self):
        self._entered.set()
        assert self._release.wait(5)
        return True


class PingClient:
    def ping(self):
        return True


def _install_redis(monkeypatch, connector) -> None:
    class FakeRedisModule:
        class Redis:
            from_url = staticmethod(connector)

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule)


def test_invalidate_waits_for_inflight_connection(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    fake_client = SlowPingClient(entered, release)
    _install_redis(monkeypatch, lambda *_args, **_kwargs: fake_client)
    conn = RedisConnection(url="redis://unused/0", backoff_seconds=BACKOFF, label="test")

    connected: list[object] = []
    connector_thread = threading.Thread(target=lambda: connected.append(conn.client()))
    connector_thread.start()
    assert entered.wait(5)

    invalidated = threading.Event()
    started_at = time.time()

    def discard() -> None:
        conn.invalidate(ConnectionError("연결 끊김"))
        invalidated.set()

    invalidate_thread = threading.Thread(target=discard)
    invalidate_thread.start()
    # invalidate 는 연결 시도가 끝날 때까지 잠금에서 대기해야 합니다.
    assert not invalidated.wait(0.2)

    release.set()
    connector_thread.join(5)
    invalidate_thread.join(5)

    assert not connector_thread.is_alive()
    assert not invalidate_thread.is_alive()
    assert connected == [fake_client]
    assert conn._client is None
    assert conn._next_attempt_at >= started_at + BACKOFF


def test_invalidate_drops_client_and_blocks_reconnect(monkeypatch):
    fake_client = PingClient()
    attempts: list[int] = []

    def connector(*_args, **_kwargs):
        attempts.append(1)
        return fake_client

    _install_redis(monkeypatch, connector)
    conn = RedisConnection(url="redis://unused/0", backoff_seconds=60.0, label="test")

    assert conn.client() is fake_client
    conn.invalidate(ConnectionError("연결 끊김"))

    assert conn._client is None
    assert conn.client() is None
    assert attempts == [1]


def test_invalidate_without_client_does_not_warn(caplog):
    conn = RedisConnection(url="redis://unused/0", backoff_seconds=BACKOFF, label="test")

    with caplog.at_level(logging.WARNING, logger="src.app.core.cache"):
        conn.invalidate(ConnectionError("연결 없음"))

    assert caplog.records == []
    assert conn._client is None
