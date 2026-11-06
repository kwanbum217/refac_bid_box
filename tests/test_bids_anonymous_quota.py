"""공고 JSON API 익명 쿼터 적용 검증."""

from __future__ import annotations

from unittest.mock import MagicMock

from src.app.api.v1 import bids as bids_mod
from src.app.core.security import anonymous_api_rate_limiter


class _FakeRedis:
    """쿼터 카운터만 흉내 내는 Redis 대역."""

    def __init__(self) -> None:
        self.count = 0

    def get(self, _key):
        return str(self.count)

    def pipeline(self):
        outer = self

        class Pipe:
            def incr(self, _key, _amount=1):
                outer.count += 1
                return self

            def expire(self, _key, _ttl):
                return self

            def execute(self):
                return True

        return Pipe()


def test_bids_route_returns_429_over_anonymous_quota(client, monkeypatch):
    fake = _FakeRedis()
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake)
    monkeypatch.setattr(
        type(anonymous_api_rate_limiter),
        "max_requests",
        property(lambda _self: 2),
    )

    assert client.get("/api/v1/bids").status_code == 200
    assert client.get("/api/v1/bids").status_code == 200
    response = client.get("/api/v1/bids")

    assert response.status_code == 429
    assert "초" not in response.json()["detail"]
    assert "분" not in response.json()["detail"]


def test_all_unauthenticated_bids_routes_enforce_quota(client, monkeypatch):
    recorder = MagicMock()
    monkeypatch.setattr(bids_mod, "enforce_anonymous_api_quota", recorder)

    for path in (
        "/api/v1/bids",
        "/api/v1/bids/results",
        "/api/v1/bids/stats",
        "/api/v1/bids/compare-stats",
        "/api/v1/bids/home",
        "/api/v1/bids/results/1",
        "/api/v1/bids/1",
    ):
        client.get(path)

    assert recorder.call_count == 7
