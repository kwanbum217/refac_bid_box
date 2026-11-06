"""챗봇 메시지·질의 길이 상한(4,000자) 검증."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.api.v1 import chatbot as chatbot_mod
from src.app.schemas.chatbot import (
    CHAT_MESSAGE_MAX_LENGTH,
    ChatbotQueryRequest,
    ChatRequest,
    ChatResponse,
)


def test_message_max_length_is_4000():
    assert CHAT_MESSAGE_MAX_LENGTH == 4000


def test_chat_request_accepts_message_at_limit():
    payload = ChatRequest(message="가" * CHAT_MESSAGE_MAX_LENGTH)

    assert len(payload.message) == CHAT_MESSAGE_MAX_LENGTH


def test_chat_request_rejects_message_over_limit():
    with pytest.raises(ValidationError):
        ChatRequest(message="가" * (CHAT_MESSAGE_MAX_LENGTH + 1))


def test_chatbot_query_request_accepts_query_at_limit():
    payload = ChatbotQueryRequest(query="가" * CHAT_MESSAGE_MAX_LENGTH)

    assert len(payload.query) == CHAT_MESSAGE_MAX_LENGTH


def test_chatbot_query_request_rejects_query_over_limit():
    with pytest.raises(ValidationError):
        ChatbotQueryRequest(query="가" * (CHAT_MESSAGE_MAX_LENGTH + 1))


def test_chat_api_accepts_message_at_limit(client, monkeypatch):
    monkeypatch.setattr(chatbot_mod, "enforce_anonymous_api_quota", lambda _request, _user: None)
    monkeypatch.setattr(
        chatbot_mod, "_run_chat", lambda _payload, _uid: ChatResponse(status="success")
    )

    response = client.post(
        "/api/v1/chatbot/chat",
        json={"message": "가" * CHAT_MESSAGE_MAX_LENGTH},
    )

    assert response.status_code == 200


def test_chat_api_rejects_message_over_limit(client, monkeypatch):
    monkeypatch.setattr(chatbot_mod, "enforce_anonymous_api_quota", lambda _request, _user: None)

    response = client.post(
        "/api/v1/chatbot/chat",
        json={"message": "가" * (CHAT_MESSAGE_MAX_LENGTH + 1)},
    )

    assert response.status_code == 422
