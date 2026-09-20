"""tests/test_chatbot_api.py

챗봇 API 엔드포인트 비동기 쿼터 검사 오프로드 및 429 동작 검증 테스트.
- POST /api/v1/chatbot/chat 및 POST /api/v1/chatbot/chat/stream 비동기 핸들러에서
  동기 Redis 쿼터 검사(enforce_anonymous_api_quota)가 이벤트 루프를 막지 않고
  asyncio.to_thread 를 통해 작업 스레드로 오프로드되는지 검증합니다.
- 비인증 요청이 쿼터 초과 시 기존과 동일한 429 상태 코드와 에러 메시지로 거절되는지 검증합니다.
- SSE 스트리밍 경로(/chat/stream)의 경우 쿼터 초과 예외가 스트림 시작 전에 즉시 429 로 반환되며
  스트림 내부 에러 이벤트로 삼켜지지 않는지 검증합니다.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any

from src.app.api.v1 import chatbot as chatbot_mod
from src.app.core.security import (
    ANONYMOUS_API_RATE_LIMIT_EXCEEDED_DETAIL,
    anonymous_api_rate_limiter,
    enforce_anonymous_api_quota,
)
from src.app.schemas.chatbot import ChatResponse


class _FakeRedisExceeded:
    """쿼터 초과 상태를 시뮬레이션하는 Fake Redis."""

    def get(self, _key: str) -> str:
        return "999"

    def pipeline(self) -> Any:
        class Pipe:
            def incr(self, _key: str) -> Pipe:
                return self

            def expire(self, _key: str, _ttl: int) -> Pipe:
                return self

            def execute(self) -> bool:
                return True

        return Pipe()


def test_chat_api_quota_offloaded_to_thread(client, monkeypatch):
    """POST /chat 핸들러에서 쿼터 검사가 이벤트 루프 외부 스레드로 오프로드되는지 검증합니다."""
    recorded_executions: list[dict[str, Any]] = []
    real_enforce = enforce_anonymous_api_quota

    def spy_enforce(request, user):
        has_running_loop = False
        try:
            asyncio.get_running_loop()
            has_running_loop = True
        except RuntimeError:
            has_running_loop = False

        recorded_executions.append(
            {
                "thread_id": threading.get_ident(),
                "thread_name": threading.current_thread().name,
                "has_running_loop": has_running_loop,
            }
        )
        return real_enforce(request, user)

    monkeypatch.setattr(chatbot_mod, "enforce_anonymous_api_quota", spy_enforce)
    monkeypatch.setattr(
        chatbot_mod,
        "_run_chat",
        lambda payload, uid: ChatResponse(status="success", answer="테스트 응답"),
    )

    response = client.post("/api/v1/chatbot/chat", json={"message": "안녕하세요"})

    assert response.status_code == 200
    assert len(recorded_executions) == 1
    # asyncio.to_thread 로 오프로드되었으므로 실행 스레드에 running loop 가 없어야 합니다.
    assert recorded_executions[0]["has_running_loop"] is False


def test_chat_stream_api_quota_offloaded_to_thread(client, monkeypatch):
    """POST /chat/stream 핸들러에서 쿼터 검사가 이벤트 루프 외부 스레드로 오프로드되는지 검증합니다."""
    recorded_executions: list[dict[str, Any]] = []
    real_enforce = enforce_anonymous_api_quota

    def spy_enforce(request, user):
        has_running_loop = False
        try:
            asyncio.get_running_loop()
            has_running_loop = True
        except RuntimeError:
            has_running_loop = False

        recorded_executions.append(
            {
                "thread_id": threading.get_ident(),
                "thread_name": threading.current_thread().name,
                "has_running_loop": has_running_loop,
            }
        )
        return real_enforce(request, user)

    monkeypatch.setattr(chatbot_mod, "enforce_anonymous_api_quota", spy_enforce)
    # _prepare_chat_sync 가 바로 ChatResponse 를 반환하면 스트림이 final 이벤트 후 종료됩니다.
    monkeypatch.setattr(
        chatbot_mod,
        "_prepare_chat_sync",
        lambda payload, uid: ChatResponse(status="success", answer="스트림 테스트"),
    )

    response = client.post("/api/v1/chatbot/chat/stream", json={"message": "스트림 테스트"})

    assert response.status_code == 200
    assert len(recorded_executions) == 1
    # asyncio.to_thread 로 오프로드되었으므로 실행 스레드에 running loop 가 없어야 합니다.
    assert recorded_executions[0]["has_running_loop"] is False


def test_chat_api_quota_exceeded_returns_429(client, monkeypatch):
    """POST /chat 비인증 요청 시 쿼터가 초과되면 429 상태 코드와 에러 세부정보를 반환합니다."""
    fake_redis = _FakeRedisExceeded()
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake_redis)

    response = client.post("/api/v1/chatbot/chat", json={"message": "쿼터 초과 테스트"})

    assert response.status_code == 429
    assert response.json()["detail"] == ANONYMOUS_API_RATE_LIMIT_EXCEEDED_DETAIL


def test_chat_stream_api_quota_exceeded_returns_429_before_stream(client, monkeypatch):
    """POST /chat/stream 비인증 요청 시 쿼터가 초과되면 스트림 진입 전 즉시 429 로 거절됩니다."""
    fake_redis = _FakeRedisExceeded()
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake_redis)

    response = client.post("/api/v1/chatbot/chat/stream", json={"message": "쿼터 초과 스트림"})

    assert response.status_code == 429
    assert "application/json" in response.headers.get("content-type", "")
    assert response.json()["detail"] == ANONYMOUS_API_RATE_LIMIT_EXCEEDED_DETAIL


def test_both_handlers_call_to_thread_for_quota(client, monkeypatch):
    """chat_api 와 chat_stream_api 모두 asyncio.to_thread 로 쿼터 검사를 호출하는지 단언합니다."""
    called_targets: list[Any] = []
    real_to_thread = asyncio.to_thread

    async def spy_to_thread(func, /, *args, **kwargs):
        called_targets.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", spy_to_thread)
    monkeypatch.setattr(
        chatbot_mod,
        "_run_chat",
        lambda payload, uid: ChatResponse(status="success", answer="ok"),
    )
    monkeypatch.setattr(
        chatbot_mod,
        "_prepare_chat_sync",
        lambda payload, uid: ChatResponse(status="success", answer="ok"),
    )

    # 1. chat_api 호출 검증
    res_chat = client.post("/api/v1/chatbot/chat", json={"message": "chat"})
    assert res_chat.status_code == 200
    assert enforce_anonymous_api_quota in called_targets

    # 2. chat_stream_api 호출 검증
    called_targets.clear()
    res_stream = client.post("/api/v1/chatbot/chat/stream", json={"message": "stream"})
    assert res_stream.status_code == 200
    assert enforce_anonymous_api_quota in called_targets
