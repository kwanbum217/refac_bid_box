"""tests/test_chatbot_stream_db_parity.py

SSE-01 회귀 시험.

POST /api/v1/chatbot/chat/stream 이 RAG 엔진에 DB 세션을 넘기지 않아
비스트리밍 POST /chat 과 다른 근거로 답하던 결함을 고정합니다. 스트리밍 경로가
get_answer_sync 와 같은 종류의 세션을 받는지, 그리고 스트림 종료·예외 때
세션을 닫는지 확인합니다. 운영 DB 는 쓰지 않고 SQLite 픽스처를 씁니다.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

from sqlalchemy.orm import Session

from src.app.api.v1 import chatbot as chatbot_mod
from src.app.schemas.chatbot import ChatResponse
from src.app.services.planner import plan_chat_request

STREAM_URL = "/api/v1/chatbot/chat/stream"
CHAT_URL = "/api/v1/chatbot/chat"
QUESTION = "한국농어촌공사 공고 알려줘"


def _pending_answer() -> chatbot_mod._PendingRagAnswer:
    """RAG 직전 상태를 흉내 내 DB·LLM 없이 스트림 경로만 검증합니다."""
    return chatbot_mod._PendingRagAnswer(
        message=QUESTION,
        session_key="stream-db-parity",
        history=[],
        kb_status=None,
        plan=plan_chat_request(QUESTION),
        tool_context={},
        user_id=None,
    )


def _final_response() -> ChatResponse:
    return ChatResponse(status="success", answer="완료")


def test_stream_passes_db_session_to_engine(client, monkeypatch):
    """스트리밍 경로가 stream_tokens 에 None 이 아닌 세션을 넘겨야 합니다."""
    captured: dict[str, Any] = {}

    async def fake_stream_tokens(
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ):
        captured["db"] = db
        yield {"type": "docs", "docs": []}
        yield {"type": "token", "text": "근거 기반 답변"}
        yield {
            "type": "done",
            "citations": [],
            "trace_id": "test-trace",
            "final_answer": "근거 기반 답변",
        }

    monkeypatch.setattr(chatbot_mod, "_prepare_chat_sync", lambda payload, uid: _pending_answer())
    monkeypatch.setattr(
        chatbot_mod, "_finalize_rag_answer_sync", lambda *args, **kwargs: _final_response()
    )
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)

    response = client.post(STREAM_URL, json={"message": QUESTION})

    assert response.status_code == 200
    assert isinstance(captured["db"], Session)


def test_stream_and_non_stream_receive_same_session_kind(client, monkeypatch):
    """/chat 과 /chat/stream 이 같은 종류의 DB 세션을 RAG 엔진에 넘겨야 합니다."""
    sync_capture: dict[str, Any] = {}
    stream_capture: dict[str, Any] = {}

    def fake_get_answer_sync(
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ):
        sync_capture["db"] = db
        return SimpleNamespace(
            answer="동일 근거",
            provenance=SimpleNamespace(model_dump=lambda: {}),
            latency_ms=0.0,
        )

    async def fake_stream_tokens(
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ):
        stream_capture["db"] = db
        yield {
            "type": "done",
            "citations": [],
            "trace_id": "test-trace",
            "final_answer": "동일 근거",
        }

    pending = _pending_answer()
    monkeypatch.setattr(chatbot_mod, "_prepare_chat", lambda db, payload, user_id=None: pending)
    monkeypatch.setattr(chatbot_mod, "_prepare_chat_sync", lambda payload, uid: pending)
    monkeypatch.setattr(
        chatbot_mod, "_finalize_rag_answer", lambda *args, **kwargs: _final_response()
    )
    monkeypatch.setattr(
        chatbot_mod, "_finalize_rag_answer_sync", lambda *args, **kwargs: _final_response()
    )
    monkeypatch.setattr(chatbot_mod.rag_engine, "get_answer_sync", fake_get_answer_sync)
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)

    assert client.post(CHAT_URL, json={"message": QUESTION}).status_code == 200
    assert client.post(STREAM_URL, json={"message": QUESTION}).status_code == 200

    assert isinstance(sync_capture["db"], Session)
    assert isinstance(stream_capture["db"], Session)


def test_stream_closes_session_after_success(client, monkeypatch):
    """스트림이 정상 종료되면 확보한 세션을 닫아야 합니다."""
    session = MagicMock()
    close_spy = session.close

    async def fake_stream_tokens(
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ):
        yield {
            "type": "done",
            "citations": [],
            "trace_id": "test-trace",
            "final_answer": "완료",
        }

    monkeypatch.setattr(chatbot_mod, "open_thread_session", lambda: (session, True))
    monkeypatch.setattr(chatbot_mod, "_prepare_chat_sync", lambda payload, uid: _pending_answer())
    monkeypatch.setattr(
        chatbot_mod, "_finalize_rag_answer_sync", lambda *args, **kwargs: _final_response()
    )
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", fake_stream_tokens)

    response = client.post(STREAM_URL, json={"message": QUESTION})

    assert response.status_code == 200
    close_spy.assert_called_once()


def test_stream_closes_session_on_engine_error(client, monkeypatch):
    """엔진 예외로 스트림이 중단되어도 세션을 닫아야 합니다."""
    session = MagicMock()
    close_spy = session.close

    async def failing_stream_tokens(
        user_query: str,
        db: Session | None = None,
        history: list[dict] | None = None,
        tool_context: dict | None = None,
    ):
        yield {"type": "token", "text": "일부"}
        raise RuntimeError("engine failure")

    monkeypatch.setattr(chatbot_mod, "open_thread_session", lambda: (session, True))
    monkeypatch.setattr(chatbot_mod, "_prepare_chat_sync", lambda payload, uid: _pending_answer())
    monkeypatch.setattr(
        chatbot_mod, "_finalize_rag_answer_sync", lambda *args, **kwargs: _final_response()
    )
    monkeypatch.setattr(chatbot_mod.rag_engine, "stream_tokens", failing_stream_tokens)

    response = client.post(STREAM_URL, json={"message": QUESTION})

    assert response.status_code == 200
    assert "event: error" in response.text
    close_spy.assert_called_once()
