"""
tests/test_authenticated_api_quota.py

로그인 사용자 API 요청 쿼터 검증.

 - 로그인 사용자가 상수 한도를 넘으면 429 를 반환하고 남은 시간을 노출하지 않는다.
 - 제한 키는 user.id 이며 접두사는 api:ratelimit:user: 이다.
 - Redis 를 사용할 수 없으면 익명 제한기와 같이 요청을 차단하지 않는다.
"""

from __future__ import annotations

from unittest.mock import patch

from src.app.core.security import (
    AUTHENTICATED_API_RATE_LIMIT_EXCEEDED_DETAIL,
    AUTHENTICATED_API_RATE_LIMIT_PREFIX,
    authenticated_api_rate_limiter,
    enforce_anonymous_api_quota,
)
from tests.test_automation_rbac import _login, _signup

_QUOTA_PATH = "/api/v1/chatbot/session/new"


class _FakeRedisOverLimit:
    """한도 초과 상태를 흉내내는 최소 대역 (get/pipeline)."""

    def get(self, _key: str) -> str:
        return "999"

    def pipeline(self):
        outer = self

        class Pipe:
            def incr(self, _key: str):
                return self

            def expire(self, _key: str, _ttl: int):
                return self

            def execute(self):
                return outer.get("")

        return Pipe()


def test_authenticated_api_quota_returns_429(client, isolated_db, monkeypatch):
    _signup(client)
    _login(client)
    monkeypatch.setattr(
        authenticated_api_rate_limiter._conn, "client", lambda: _FakeRedisOverLimit()
    )
    monkeypatch.setattr(
        type(authenticated_api_rate_limiter),
        "max_requests",
        property(lambda _self: 2),
    )

    response = client.post(_QUOTA_PATH)

    assert response.status_code == 429
    assert response.json()["detail"] == AUTHENTICATED_API_RATE_LIMIT_EXCEEDED_DETAIL
    assert "초" not in response.json()["detail"]


def test_authenticated_quota_is_keyed_by_user_id(monkeypatch):
    user = type("User", (), {"id": 7})()

    with (
        patch.object(authenticated_api_rate_limiter, "check_rate_limit") as check,
        patch.object(authenticated_api_rate_limiter, "record_request") as record,
    ):
        enforce_anonymous_api_quota(None, user)

    check.assert_called_once_with(7)
    record.assert_called_once_with(7)
    assert authenticated_api_rate_limiter._key(7) == f"{AUTHENTICATED_API_RATE_LIMIT_PREFIX}7"


def test_authenticated_api_quota_fail_open_when_redis_unavailable(client, isolated_db, monkeypatch):
    _signup(client)
    _login(client)
    monkeypatch.setattr(authenticated_api_rate_limiter._conn, "client", lambda: None)

    response = client.post(_QUOTA_PATH)

    assert response.status_code == 200
