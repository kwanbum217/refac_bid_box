"""tests/fake_redis.py

확인 토큰 단일 소비는 Redis 를 요구하며 연결이 없으면 fail-closed 로 거부합니다.
테스트 환경에는 Redis 서버가 없으므로 운영 코드를 완화하지 않고 대역 연결을
주입합니다. 운영 코드에 개발용 우회 경로를 두면 단일 소비 보장 자체가
무의미해지므로, 대역은 반드시 테스트 쪽에만 둡니다.
"""

from __future__ import annotations

import contextlib
from typing import Any
from unittest.mock import patch

from src.app.core.cache import RedisConnection


class FakeRedisClient:
    """SET NX 와 SET XX 의미론만 재현하는 최소 대역입니다."""

    def __init__(self, store: dict[str, Any] | None = None) -> None:
        self._store: dict[str, Any] = {} if store is None else store

    def set(
        self,
        key: str,
        value: Any,
        ex: int | None = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool | None:
        exists = key in self._store
        if nx and exists:
            return None
        if xx and not exists:
            return None
        self._store[key] = value
        return True

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def delete(self, *keys: str) -> int:
        return sum(1 for k in keys if self._store.pop(k, None) is not None)

    def ping(self) -> bool:
        return True


class FakeRedisConnection(RedisConnection):
    def __init__(self, client: Any = None, label: str = "fake_automation_tokens") -> None:
        super().__init__(label=label)
        self._fake = client or FakeRedisClient()

    def client(self) -> Any:
        return self._fake

    def invalidate(self, exc: Exception) -> None:
        return None


@contextlib.contextmanager
def fake_confirmation_redis(conn: FakeRedisConnection | None = None):
    """확인 토큰 소비 경로에 대역 Redis 연결을 주입합니다."""
    target = conn or FakeRedisConnection()
    with patch("src.app.services.automation_tokens._confirmation_redis_conn", target):
        yield target
