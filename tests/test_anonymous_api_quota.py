"""익명 챗봇 API 요청 쿼터 검증."""

from __future__ import annotations

from unittest.mock import patch

from src.app.core.security import anonymous_api_rate_limiter, enforce_anonymous_api_quota


def test_anonymous_api_quota_returns_429_without_remaining_time(client, monkeypatch):
    """익명 세션 생성 API가 임계 초과를 429로 반환하고 시간을 노출하지 않는지 검증합니다."""

    class FakeRedis:
        def __init__(self):
            self.count = 0

        def get(self, _key):
            return str(self.count)

        def pipeline(self):
            outer = self

            class Pipe:
                def incr(self, _key):
                    outer.count += 1
                    return self

                def expire(self, _key, _ttl):
                    return self

                def execute(self):
                    return True

            return Pipe()

    fake = FakeRedis()
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake)
    monkeypatch.setattr(
        type(anonymous_api_rate_limiter),
        "max_requests",
        property(lambda _self: 2),
    )

    assert client.post("/api/v1/chatbot/session/new").status_code == 200
    assert client.post("/api/v1/chatbot/session/new").status_code == 200
    response = client.post("/api/v1/chatbot/session/new")

    assert response.status_code == 429
    assert "초" not in response.json()["detail"]
    assert "분" not in response.json()["detail"]


def test_authenticated_user_skips_anonymous_api_quota(monkeypatch):
    """인증 사용자는 익명 쿼터 검사 자체를 통과하는지 검증합니다."""
    with (
        patch.object(anonymous_api_rate_limiter, "check_rate_limit") as check,
        patch.object(anonymous_api_rate_limiter, "record_request") as record,
    ):
        enforce_anonymous_api_quota(None, object())

    check.assert_not_called()
    record.assert_not_called()


def test_anonymous_api_quota_uses_resolved_proxy_ip(monkeypatch):
    """라우터의 익명 쿼터가 신뢰 프록시 IP 해석기를 사용합니다."""
    with (
        patch("src.app.core.security.resolve_client_ip", return_value="198.51.100.7") as resolve,
        patch.object(anonymous_api_rate_limiter, "check_rate_limit") as check,
        patch.object(anonymous_api_rate_limiter, "record_request") as record,
    ):
        enforce_anonymous_api_quota(
            type(
                "Request",
                (),
                {
                    "client": type("Client", (), {"host": "10.0.0.2"})(),
                    "headers": {"x-forwarded-for": "198.51.100.7"},
                },
            )(),
            None,
        )

    resolve.assert_called_once_with("10.0.0.2", "198.51.100.7")
    check.assert_called_once_with("198.51.100.7")
    record.assert_called_once_with("198.51.100.7")


def test_anonymous_api_quota_fail_open_when_redis_unavailable(client, monkeypatch):
    """Redis를 사용할 수 없으면 익명 요청을 차단하지 않습니다."""
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: None)
    response = client.post("/api/v1/chatbot/session/new")
    assert response.status_code == 200
