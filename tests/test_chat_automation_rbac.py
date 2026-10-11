"""
tests/test_chat_automation_rbac.py

챗봇 자동화 경로 RBAC 회귀 시험.

 - 일반 회원은 챗봇 action 요청으로 automation_requests 행을 만들 수 없다.
 - 일반 회원은 확인 토큰과 '실행' 문구 경로로도 요청을 실행할 수 없다.
 - staff 는 기존과 같이 action 요청을 만들고 확인할 수 있다.
"""

from __future__ import annotations

from unittest.mock import patch

from src.app.models.chatbot import AutomationRequest
from tests.test_automation_rbac import (
    _login,
    _make_staff,
    _seed_pending_request,
    _signup,
)

STAFF_REQUIRED_MESSAGE = "자동화 실행은 관리자만 이용할 수 있습니다."


def _chat(client, message: str, **extra):
    return client.post("/api/v1/chatbot/chat", json={"message": message, **extra})


# --------------------------------------------------------------------------- #
# action 요청
# --------------------------------------------------------------------------- #


def test_non_staff_chat_action_blocked(client, isolated_db):
    _signup(client)
    _login(client)

    payload = _chat(client, "공고 수집해줘").json()

    assert payload["status"] == "error"
    assert payload["mode"] == "error"
    assert STAFF_REQUIRED_MESSAGE in payload["answer"]
    assert isolated_db.query(AutomationRequest).count() == 0


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_staff_chat_action_allowed(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)

    payload = _chat(client, "공고 수집해줘").json()

    assert payload["mode"] == "action"
    assert payload["job"]["action_key"] == "collect_refresh"
    assert isolated_db.query(AutomationRequest).count() == 1


# --------------------------------------------------------------------------- #
# 확인 경로 (토큰 / 문구)
# --------------------------------------------------------------------------- #


def test_non_staff_confirmation_token_blocked(client, isolated_db):
    signup = _signup(client)
    _login(client)
    _seed_pending_request(isolated_db, signup.json()["id"], "job-chat-token-001")

    payload = _chat(client, "승인", confirmation_token="whatever-token").json()

    assert payload["status"] == "error"
    assert STAFF_REQUIRED_MESSAGE in payload["answer"]
    stored = isolated_db.query(AutomationRequest).filter_by(request_id="job-chat-token-001").one()
    assert stored.status == "pending_confirmation"


def test_non_staff_text_confirmation_blocked(client, isolated_db):
    signup = _signup(client)
    _login(client)
    _seed_pending_request(isolated_db, signup.json()["id"], "job-chat-text-001")

    payload = _chat(client, "승인 후 실행해줘").json()

    assert payload["status"] == "error"
    assert STAFF_REQUIRED_MESSAGE in payload["answer"]
    stored = isolated_db.query(AutomationRequest).filter_by(request_id="job-chat-text-001").one()
    assert stored.status == "pending_confirmation"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_staff_text_confirmation_allowed(mock_enqueue, client, isolated_db):
    signup = _signup(client)
    _login(client)
    _make_staff(client, isolated_db)
    _seed_pending_request(isolated_db, signup.json()["id"], "job-chat-staff-001")

    payload = _chat(client, "승인 후 실행해줘").json()

    assert payload["mode"] == "action"
    stored = isolated_db.query(AutomationRequest).filter_by(request_id="job-chat-staff-001").one()
    assert stored.confirmed_at is not None
    assert stored.status in ("queued", "running")
