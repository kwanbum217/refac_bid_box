"""tests/test_conc_chat_limit_20261122.py

챗봇 API 동시 실행 상한·사용자당 1요청·SSE DB 세션 조기 반납 시험.

- 상한(기본 2)을 넘으면 LLM·DB 를 건드리기 전에 503 과 Retry-After 로 거절합니다.
- 같은 사용자의 두 번째 동시 요청은 429 로 거절하고 다른 사용자는 통과합니다.
- 스트림이 정상 종료·예외·클라이언트 연결 끊김으로 끝나도 슬롯과 사용자 키를 반납합니다.
- 첫 token 또는 docs(근거 준비 완료) 뒤에 DB 세션을 반납하고 이중 close 가 없습니다.
- 상한 설정값을 바꾸면 다음 요청부터 반영됩니다.

LLM 백엔드와 rag_engine 은 가짜로 대체하며 운영 DB·Redis·Ollama 에 기대지 않습니다.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from starlette.requests import ClientDisconnect, Request

from src.app.api.v1 import chatbot as chatbot_mod
from src.app.api.v1.accounts import get_current_user
from src.app.core.config import settings
from src.app.main import app
from src.app.schemas.chatbot import ChatRequest, ChatResponse
from src.app.services import chat_concurrency as chat_limit
from src.app.services.planner import plan_chat_request

CHAT_URL = "/api/v1/chatbot/chat"
STREAM_URL = "/api/v1/chatbot/chat/stream"
QUESTION = "한국농어촌공사 공고 알려줘"


@pytest.fixture(autouse=True)
def _pin_chat_limit(monkeypatch):
    """로컬 .env 값과 무관하게 시험 상한을 기본값 2 로 고정합니다."""
    monkeypatch.setattr(settings, "CHATBOT_MAX_CONCURRENT_REQUESTS", 2)


@pytest.fixture
def limiter(monkeypatch) -> chat_limit.ChatConcurrencyLimiter:
    """시험마다 빈 동시성 제한기를 꽂아 이전 시험 상태가 새지 않게 합니다."""
    fresh = chat_limit.ChatConcurrencyLimiter()
    monkeypatch.setattr(chatbot_mod, "chat_limiter", fresh)
    return fresh


@pytest.fixture
def login_as():
    """get_current_user 를 대체해 사용자 id 를 시험 안에서 바꿉니다."""
    state: dict[str, Any] = {"user": None}

    def override() -> Any:
        return state["user"]

    app.dependency_overrides[get_current_user] = override

    def set_user(user_id: int | None) -> None:
        state["user"] = None if user_id is None else SimpleNamespace(id=user_id)

    try:
        yield set_user
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def _pending_answer() -> chatbot_mod._PendingRagAnswer:
    return chatbot_mod._PendingRagAnswer(
        message=QUESTION,
        session_key="conc-chat-limit",
        history=[],
        kb_status=None,
        plan=plan_chat_request(QUESTION),
        tool_context={},
        user_id=None,
    )


def _final_response() -> ChatResponse:
    return ChatResponse(status="success", answer="완료")


def _patch_fast_pipeline(monkeypatch) -> None:
    """플래너·도구·RAG 정리 단계를 건너뛰고 스트리밍 배선만 남깁니다."""
    monkeypatch.setattr(chatbot_mod, "_prepare_chat_sync", lambda payload, uid: _pending_answer())
    monkeypatch.setattr(
        chatbot_mod, "_finalize_rag_answer_sync", lambda *args, **kwargs: _final_response()
    )


def _http_request(ip: str = "203.0.113.9") -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": STREAM_URL,
            "headers": [(b"content-type", b"application/json")],
            "client": (ip, 50000),
            "query_string": b"",
            "scheme": "http",
            "server": ("testserver", 80),
        }
    )


# --------------------------------------------------------------------------- #
# (a) 상한 초과 -> LLM 호출 없이 503 + Retry-After
# --------------------------------------------------------------------------- #


def test_third_concurrent_chat_is_rejected_without_llm(client, limiter, monkeypatch):
    backend_calls: list[int] = []
    monkeypatch.setattr(
        chatbot_mod,
        "_run_chat",
        lambda *args, **kwargs: backend_calls.append(1) or _final_response(),
    )
    limiter.acquire("user:101", chat_limit.max_concurrent_requests())
    limiter.acquire("user:102", chat_limit.max_concurrent_requests())

    response = client.post(CHAT_URL, json={"message": QUESTION})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(chat_limit.CHAT_RETRY_AFTER_SECONDS)
    assert chat_limit.CHAT_BUSY_DETAIL in response.json()["detail"]
    assert backend_calls == []
    # 거절된 요청은 전역 슬롯도 사용자 키도 새로 잡지 않습니다.
    assert limiter._active_total == 2
    assert "ip:testclient" not in limiter._active_users


def test_third_concurrent_stream_is_rejected_before_stream(client, limiter, monkeypatch):
    stream_calls: list[int] = []

    async def fake_stream_tokens(*args, **kwargs):
        stream_calls.append(1)
        yield {"type": "done", "final_answer": "완료", "trace_id": "test-trace"}

    _patch_fast_pipeline(monkeypatch)
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)
    limiter.acquire("user:201", chat_limit.max_concurrent_requests())
    limiter.acquire("user:202", chat_limit.max_concurrent_requests())

    response = client.post(STREAM_URL, json={"message": QUESTION})

    assert response.status_code == 503
    assert response.headers["Retry-After"] == str(chat_limit.CHAT_RETRY_AFTER_SECONDS)
    assert "event:" not in response.text
    assert stream_calls == []


# --------------------------------------------------------------------------- #
# (b) 사용자당 동시 1요청 -> 429, 다른 사용자는 통과
# --------------------------------------------------------------------------- #


def test_same_user_second_request_is_rejected_and_other_user_passes(
    client, limiter, login_as, monkeypatch
):
    backend_calls: list[int] = []
    monkeypatch.setattr(
        chatbot_mod,
        "_run_chat",
        lambda *args, **kwargs: backend_calls.append(1) or _final_response(),
    )
    login_as(7)
    limiter.acquire("user:7", chat_limit.max_concurrent_requests())

    rejected = client.post(CHAT_URL, json={"message": QUESTION})

    assert rejected.status_code == 429
    assert rejected.headers["Retry-After"] == str(chat_limit.CHAT_RETRY_AFTER_SECONDS)
    assert chat_limit.CHAT_DUPLICATE_DETAIL in rejected.json()["detail"]
    assert backend_calls == []

    login_as(8)
    assert client.post(CHAT_URL, json={"message": QUESTION}).status_code == 200
    assert backend_calls == [1]


def test_anonymous_requests_share_the_client_ip_key(client, limiter, monkeypatch):
    backend_calls: list[int] = []
    monkeypatch.setattr(
        chatbot_mod,
        "_run_chat",
        lambda *args, **kwargs: backend_calls.append(1) or _final_response(),
    )
    limiter.acquire("ip:testclient", chat_limit.max_concurrent_requests())

    response = client.post(CHAT_URL, json={"message": QUESTION})

    assert response.status_code == 429
    assert backend_calls == []


# --------------------------------------------------------------------------- #
# (c) 모든 종료 경로에서 슬롯과 사용자 키 반납
# --------------------------------------------------------------------------- #


def test_stream_releases_slot_after_normal_end(client, limiter, monkeypatch):
    async def fake_stream_tokens(*args, **kwargs):
        yield {"type": "docs", "docs": []}
        yield {"type": "token", "text": "답변"}
        yield {"type": "done", "final_answer": "답변", "trace_id": "test-trace"}

    _patch_fast_pipeline(monkeypatch)
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)
    monkeypatch.setattr(chatbot_mod, "open_thread_session", lambda: (MagicMock(), True))

    response = client.post(STREAM_URL, json={"message": QUESTION})

    assert response.status_code == 200
    assert "event: final" in response.text
    assert limiter._active_total == 0
    assert limiter._active_users == set()


def test_stream_releases_slot_on_engine_error(client, limiter, monkeypatch):
    async def failing_stream_tokens(*args, **kwargs):
        yield {"type": "token", "text": "일부"}
        raise RuntimeError("engine failure")

    _patch_fast_pipeline(monkeypatch)
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", failing_stream_tokens)
    monkeypatch.setattr(chatbot_mod, "open_thread_session", lambda: (MagicMock(), True))

    response = client.post(STREAM_URL, json={"message": QUESTION})

    assert response.status_code == 200
    assert "event: error" in response.text
    assert limiter._active_total == 0
    assert limiter._active_users == set()


def test_chat_releases_slot_when_pipeline_raises(client, limiter, monkeypatch):
    def boom(*args, **kwargs):
        raise RuntimeError("pipeline failure")

    monkeypatch.setattr(chatbot_mod, "_run_chat", boom)

    with pytest.raises(RuntimeError):
        client.post(CHAT_URL, json={"message": QUESTION})

    assert limiter._active_total == 0
    assert limiter._active_users == set()


def test_stream_releases_slot_on_client_disconnect(limiter, monkeypatch):
    session = MagicMock()

    async def fake_stream_tokens(*args, **kwargs):
        yield {"type": "docs", "docs": []}
        yield {"type": "token", "text": "첫토큰"}
        yield {"type": "token", "text": "끝까지가지않음"}

    _patch_fast_pipeline(monkeypatch)
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)
    monkeypatch.setattr(chatbot_mod, "open_thread_session", lambda: (session, True))

    async def drive() -> None:
        response = await chatbot_mod.chat_stream_api(
            ChatRequest(message=QUESTION), _http_request(), None
        )
        iterator = response.body_iterator
        for _ in range(4):  # planning, plan, answering, docs
            await iterator.__anext__()
        await iterator.aclose()

    asyncio.run(drive())

    assert limiter._active_total == 0
    assert limiter._active_users == set()
    session.close.assert_called_once()


# --------------------------------------------------------------------------- #
# (d) 첫 token 또는 docs 뒤 DB 세션 반납, 스트림 끝 이중 close 없음
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("evidence_kind", ["token", "docs"])
def test_stream_releases_db_session_when_evidence_is_ready(
    client, limiter, evidence_kind, monkeypatch
):
    session = MagicMock()
    close_spy = session.close
    markers: dict[str, int] = {}

    async def fake_stream_tokens(*args, **kwargs):
        if evidence_kind == "docs":
            yield {"type": "docs", "docs": []}
        else:
            yield {"type": "token", "text": "첫토큰"}
        markers["close_count_when_evidence_resumed"] = close_spy.call_count
        yield {"type": "done", "final_answer": "첫토큰", "trace_id": "test-trace"}

    _patch_fast_pipeline(monkeypatch)
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)

    opened: list[Any] = []

    def fake_open_thread_session():
        opened.append(session)
        return session, True

    monkeypatch.setattr(chatbot_mod, "open_thread_session", fake_open_thread_session)

    response = client.post(STREAM_URL, json={"message": QUESTION})

    assert response.status_code == 200
    assert markers["close_count_when_evidence_resumed"] == 1
    close_spy.assert_called_once()


def test_stream_does_not_close_borrowed_session(client, limiter, monkeypatch):
    session = MagicMock()

    async def fake_stream_tokens(*args, **kwargs):
        yield {"type": "token", "text": "답변"}
        yield {"type": "done", "final_answer": "답변", "trace_id": "test-trace"}

    _patch_fast_pipeline(monkeypatch)
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)
    monkeypatch.setattr(chatbot_mod, "open_thread_session", lambda: (session, False))

    response = client.post(STREAM_URL, json={"message": QUESTION})

    assert response.status_code == 200
    session.close.assert_not_called()


# --------------------------------------------------------------------------- #
# (e) 상한 설정값 반영
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("limit", "expected_status"), [(1, 503), (3, 200)])
def test_chat_limit_setting_is_read_per_request(
    client, limiter, monkeypatch, limit, expected_status
):
    monkeypatch.setattr(settings, "CHATBOT_MAX_CONCURRENT_REQUESTS", limit)
    monkeypatch.setattr(chatbot_mod, "_run_chat", lambda *args, **kwargs: _final_response())
    assert chat_limit.max_concurrent_requests() == limit
    limiter.acquire("user:900", chat_limit.max_concurrent_requests())

    response = client.post(CHAT_URL, json={"message": QUESTION})

    assert response.status_code == expected_status


# --------------------------------------------------------------------------- #
# (f) Starlette 이 본문 생성자를 시작하지 않고 끝나는 두 경로에서도 반납
# --------------------------------------------------------------------------- #

CLIENT_KEY = "ip:203.0.113.9"


def _asgi_scope(spec_version: str) -> dict[str, Any]:
    return {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": spec_version},
        "http_version": "1.1",
        "method": "POST",
        "path": STREAM_URL,
        "raw_path": STREAM_URL.encode(),
        "query_string": b"",
        "headers": [],
    }


def _new_body(record: list[int]):
    async def body():
        record.append(1)
        yield "event: token\ndata: {}\n\n"

    return body()


def _acquire(limiter: chat_limit.ChatConcurrencyLimiter):
    return limiter.acquire(CLIENT_KEY, chat_limit.max_concurrent_requests())


def _assert_released(limiter: chat_limit.ChatConcurrencyLimiter) -> None:
    assert limiter._active_total == 0
    assert limiter._active_users == set()


def test_response_releases_slot_when_start_send_fails(limiter):
    """(가) spec_version >= 2.4: 응답 시작 send 의 OSError -> ClientDisconnect."""
    started: list[int] = []
    release = _acquire(limiter)
    response = chat_limit.ChatStreamingResponse(_new_body(started), release=release)

    async def send(message: dict[str, Any]) -> None:
        raise OSError("client disconnected")

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    with pytest.raises(ClientDisconnect):
        asyncio.run(response(_asgi_scope("2.4"), receive, send))

    assert started == []
    _assert_released(limiter)


def test_response_releases_slot_when_disconnect_wins(limiter):
    """(나) spec_version < 2.4: listen_for_disconnect 가 먼저 끝나 본문이 취소됨."""
    started: list[int] = []
    sent: list[dict[str, Any]] = []
    release = _acquire(limiter)
    response = chat_limit.ChatStreamingResponse(_new_body(started), release=release)
    start_sent = asyncio.Event()

    async def send(message: dict[str, Any]) -> None:
        sent.append(message)
        start_sent.set()
        # 응답 시작 전송이 끝나지 않은 채 연결 끊김이 먼저 도착하는 상황입니다.
        await asyncio.Event().wait()

    async def receive() -> dict[str, Any]:
        await start_sent.wait()
        return {"type": "http.disconnect"}

    asyncio.run(response(_asgi_scope("2.3"), receive, send))

    assert [message["type"] for message in sent] == ["http.response.start"]
    assert started == []
    _assert_released(limiter)


def test_response_release_is_idempotent_after_normal_call(limiter):
    """정상 종료에서 wrapper 와 생성기 finally 가 겹쳐도 한 번만 반납합니다."""
    started: list[int] = []
    release = _acquire(limiter)
    response = chat_limit.ChatStreamingResponse(_new_body(started), release=release)

    async def send(message: dict[str, Any]) -> None:
        return None

    async def receive() -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}

    asyncio.run(response(_asgi_scope("2.4"), receive, send))
    release()

    assert started == [1]
    _assert_released(limiter)


def test_stream_endpoint_releases_slot_when_response_build_fails(limiter, monkeypatch):
    """슬롯을 잡은 뒤 응답 객체를 만들기 전 예외가 나도 반납합니다."""

    def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("response build failure")

    monkeypatch.setattr(chatbot_mod, "ChatStreamingResponse", boom)

    async def call() -> None:
        with pytest.raises(RuntimeError):
            await chatbot_mod.chat_stream_api(ChatRequest(message=QUESTION), _http_request(), None)

    asyncio.run(call())

    _assert_released(limiter)
