"""
src/app/core/cache.py

Redis 연결 수명 관리(RedisConnection)와 일반 조회 캐시(CacheLayer).

조회 캐시는 Redis 미가용 시 프로세스 내 메모리로 degrade 합니다. 조회 결과는
프로세스마다 달라도 정합성이 깨지지 않기 때문입니다. 인증 세션은 이 정책을
쓰면 안 되므로 src/app/core/security.py 의 SessionStore 가 별도의
RedisConnection 과 별도의 실패 정책(fail-closed)을 씁니다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.app.core.config import settings

logger = logging.getLogger(__name__)

# 연결 시도 자체의 상한입니다. Redis 가 응답하지 않는 동안 요청 스레드가
# 무한정 붙잡히지 않게 합니다.
CONNECT_TIMEOUT_SECONDS = 2

# 재연결 시도 간격입니다. 간격 없이 매 호출마다 붙으려 하면 Redis 가 내려간
# 동안 모든 요청이 CONNECT_TIMEOUT_SECONDS 만큼 정체되어 장애가 증폭됩니다.
# 5초면 한 프로세스가 내는 연결 시도가 5초에 한 번(최대 2초)으로 제한되므로
# 정체 비용이 요청 수에 비례하지 않고, Redis 가 복구된 뒤에는 늦어도 5초
# 안에 다시 붙습니다. 세션 TTL(14일)과 캐시 TTL 에 비하면 무시할 수 있는
# 지연이고, 반대로 값을 더 키우면 복구 감지가 그만큼 늦어집니다.
RECONNECT_BACKOFF_SECONDS = 5.0


class RedisConnection:
    """Redis 클라이언트의 수명과 재연결 백오프만 담당합니다.

    Redis 를 쓸 수 없을 때 무엇을 할지(degrade 할지 실패시킬지)는 이 클래스가
    정하지 않습니다. 사용하는 쪽이 정합니다.
    """

    def __init__(
        self,
        url: str | None = None,
        backoff_seconds: float = RECONNECT_BACKOFF_SECONDS,
        label: str = "redis",
    ):
        self._url = url
        self._backoff = backoff_seconds
        self._label = label
        self._client: Any = None
        self._next_attempt_at = 0.0

    @property
    def url(self) -> str:
        return self._url or settings.REDIS_URL

    def client(self) -> Any:
        """살아 있는 클라이언트, 또는 지금 Redis 를 쓸 수 없으면 None."""
        if self._client is not None:
            return self._client

        now = time.time()
        if now < self._next_attempt_at:
            return None
        self._next_attempt_at = now + self._backoff

        try:
            import redis

            client = redis.Redis.from_url(
                self.url,
                decode_responses=True,
                socket_connect_timeout=CONNECT_TIMEOUT_SECONDS,
            )
            client.ping()
        except Exception as exc:
            logger.warning(
                "[%s] Redis 연결 실패, %.0f초 뒤 재시도합니다: %s", self._label, self._backoff, exc
            )
            return None

        self._client = client
        logger.info("[%s] Redis 연결됨", self._label)
        return client

    def invalidate(self, exc: Exception) -> None:
        """운영 중 끊긴 클라이언트를 버려 백오프 이후 다시 붙게 합니다."""
        if self._client is not None:
            logger.warning("[%s] Redis 연결을 폐기합니다: %s", self._label, exc)
        self._client = None
        self._next_attempt_at = time.time() + self._backoff


class CacheLayer:
    def __init__(self, url: str | None = None, connection: RedisConnection | None = None):
        self._conn = connection or RedisConnection(url, label="cache")
        self._local: dict[str, tuple[float, Any]] = {}

    def client(self) -> Any:
        """Redis 클라이언트를 돌려줍니다. 사용할 수 없으면 None 입니다.

        분산 락처럼 캐시 get/set 으로 표현되지 않는 용도가 있어 공개합니다.
        호출부가 `_conn` 을 직접 뒤지지 않게 하는 것이 목적입니다.
        """
        return self._conn.client()

    def get(self, key: str) -> Any:
        client = self._conn.client()
        if client is not None:
            try:
                raw = client.get(key)
            except Exception as exc:
                logger.warning("캐시 조회 실패 (%s): %s", key, exc)
                self._conn.invalidate(exc)
                return None
            if not raw:
                return None
            try:
                return json.loads(raw)
            except ValueError:
                logger.warning("캐시 값 역직렬화 실패 (%s)", key)
                return None

        entry = self._local.get(key)
        if entry is None:
            return None
        expires_at, value = entry
        if expires_at < time.time():
            self._local.pop(key, None)
            return None
        return value

    def set(self, key: str, value: Any, ttl: int) -> None:
        client = self._conn.client()
        if client is not None:
            try:
                client.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
            except Exception as exc:
                logger.warning("캐시 저장 실패 (%s): %s", key, exc)
                self._conn.invalidate(exc)
            return
        self._local[key] = (time.time() + ttl, value)

    def delete(self, key: str) -> None:
        client = self._conn.client()
        if client is not None:
            try:
                client.delete(key)
            except Exception as exc:
                logger.warning("캐시 삭제 실패 (%s): %s", key, exc)
                self._conn.invalidate(exc)
            return
        self._local.pop(key, None)


cache = CacheLayer()
