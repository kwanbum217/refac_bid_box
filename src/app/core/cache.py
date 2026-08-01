"""
src/app/core/cache.py

Redis 캐시 계층 (원본 django.core.cache 대체).
Redis 미가용 시 프로세스 내 메모리 캐시로 자동 degrade 하여 조회 자체는 계속 동작합니다.
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from src.app.core.config import settings

logger = logging.getLogger(__name__)


class CacheLayer:
    def __init__(self, url: str | None = None):
        self._url = url or settings.REDIS_URL
        self._client: Any = None
        self._connected = False
        self._local: dict[str, tuple[float, Any]] = {}

    def _ensure_client(self) -> None:
        if self._connected:
            return
        self._connected = True
        try:
            import redis

            client = redis.Redis.from_url(self._url, decode_responses=True, socket_connect_timeout=2)
            client.ping()
            self._client = client
        except Exception as exc:
            logger.warning("Redis 연결 실패, 메모리 캐시로 대체합니다: %s", exc)
            self._client = None

    def get(self, key: str) -> Any:
        self._ensure_client()
        if self._client is not None:
            try:
                raw = self._client.get(key)
                return json.loads(raw) if raw else None
            except Exception as exc:
                logger.warning("캐시 조회 실패 (%s): %s", key, exc)
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
        self._ensure_client()
        if self._client is not None:
            try:
                self._client.setex(key, ttl, json.dumps(value, ensure_ascii=False, default=str))
                return
            except Exception as exc:
                logger.warning("캐시 저장 실패 (%s): %s", key, exc)
                return
        self._local[key] = (time.time() + ttl, value)

    def delete(self, key: str) -> None:
        self._ensure_client()
        if self._client is not None:
            try:
                self._client.delete(key)
                return
            except Exception as exc:
                logger.warning("캐시 삭제 실패 (%s): %s", key, exc)
                return
        self._local.pop(key, None)


cache = CacheLayer()
