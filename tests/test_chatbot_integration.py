"""
tests/test_chatbot_integration.py

원본 apps/chatbot/tests.py ChatAutomationApiTests 핵심 이식.
나머지 13개는 docs/handoff/2026-08-01_session_todo.md에 기록됨.
"""

from unittest.mock import patch


VALID_SIGNUP = {
    "username": "chat-int-user",
    "password1": "StrongPass123!!",
    "password2": "StrongPass123!!",
    "nickname": "테스터",
    "email": "chat-int@example.com",
    "birth_date": "1999-05-17",
    "gender": "F",
    "agree_terms": True,
    "agree_privacy": True,
}


def _login(client):
    client.post("/api/v1/accounts/signup", json=VALID_SIGNUP)
    client.post(
        "/api/v1/accounts/login",
        json={"username": "chat-int-user", "password": "StrongPass123!!"},
    )


def test_new_chat_session_creates_session(client, isolated_db):
    _login(client)
    response = client.post("/api/v1/chatbot/session/new")
    assert response.status_code == 200
    assert response.json()["status"] == "success"
    assert "session_key" in response.json()


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_chat_creates_running_automation_request_for_data_refresh(mock_enqueue, client, isolated_db):
    _login(client)
    response = client.post("/api/v1/automation/run/collect-bids", json={"reason": "데이터 갱신해줘"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["action_key"] == "collect_refresh"
    assert payload["job"]["status"] in ("queued", "running")


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_cancel_pending_confirmation_marks_canceled(mock_enqueue, client, isolated_db):
    _login(client)
    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검해줘"})
    job_id = create_resp.json()["job"]["job_id"]

    cancel_resp = client.post(f"/api/v1/automation/job/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["job"]["status"] == "canceled"
