"""POST /api/v1/chatbot/query 익명 쿼터 회귀 검증."""

from __future__ import annotations

from types import SimpleNamespace

from src.app.api.v1.accounts import get_current_user
from src.app.core.security import anonymous_api_rate_limiter
from src.app.main import app
from src.app.models.accounts import CustomUser


class FakeRedis:
    """익명 쿼터 검증용 인메모리 Redis 시뮬레이터."""

    def __init__(self, count: int = 0):
        self.count = count

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


def _fake_bundle() -> SimpleNamespace:
    return SimpleNamespace(
        answer="테스트 답변",
        retrieved_docs=[],
        latency_ms=1.0,
        route_reason="rag",
        citations=[],
        segment_metrics=None,
        provenance=SimpleNamespace(trace_id="t123"),
    )


def _patch_get_answer(monkeypatch, calls: list | None = None):
    async def fake_get_answer(query, db=None, **_kwargs):
        if calls is not None:
            calls.append(query)
        return _fake_bundle()

    monkeypatch.setattr("src.app.api.v1.chatbot.rag_engine.get_answer", fake_get_answer)


def _shrink_quota(monkeypatch, count: int = 0):
    fake = FakeRedis(count=count)
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake)
    monkeypatch.setattr(
        type(anonymous_api_rate_limiter),
        "max_requests",
        property(lambda _self: 2),
    )


def test_anonymous_query_over_quota_returns_429(client, monkeypatch):
    """익명 요청이 쿼터를 넘으면 /query 가 429 를 반환하고 LLM 을 부르지 않는다."""
    calls: list = []
    _shrink_quota(monkeypatch, count=2)
    _patch_get_answer(monkeypatch, calls)

    response = client.post("/api/v1/chatbot/query", json={"query": "적격심사", "stream": False})

    assert response.status_code == 429
    assert calls == []


def test_authenticated_query_skips_anonymous_quota(client, monkeypatch):
    """인증 사용자는 쿼터 한도 초과 상태에서도 /query 가 200 으로 통과한다."""
    _shrink_quota(monkeypatch, count=100)
    _patch_get_answer(monkeypatch)

    mock_user = CustomUser(
        id=42,
        username="auth_user",
        email="auth_user@example.com",
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: mock_user
    try:
        response = client.post("/api/v1/chatbot/query", json={"query": "적격심사", "stream": False})
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    assert response.status_code == 200
    assert response.json()["response"] == "테스트 답변"


def test_anonymous_query_within_quota_returns_200(client, monkeypatch):
    """쿼터 안의 익명 요청은 기존 계약과 같은 응답 필드를 받는다."""
    calls: list = []
    _shrink_quota(monkeypatch, count=0)
    _patch_get_answer(monkeypatch, calls)

    response = client.post(
        "/api/v1/chatbot/query",
        json={"query": "적격심사 감점 요인이 무엇인가요?", "stream": False},
    )

    assert response.status_code == 200
    data = response.json()
    assert data["query"] == "적격심사 감점 요인이 무엇인가요?"
    assert data["response"] == "테스트 답변"
    assert "latency_ms" in data
    assert "x-rag-trace-id" in response.headers
    assert calls == ["적격심사 감점 요인이 무엇인가요?"]
