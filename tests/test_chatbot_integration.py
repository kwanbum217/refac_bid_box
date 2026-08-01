"""
tests/test_chatbot_integration.py

원본 apps/chatbot/tests.py ChatAutomationApiTests 이식.

이 파일은 자동화 API 를 직접 호출하는 대신 반드시 챗봇 대화 API(/chatbot/chat)를
거칩니다. 원본 테스트의 목적이 "자연어 요청이 계획 수립을 거쳐 자동화 요청으로
연결되는가" 이기 때문이며, 엔드포인트 단독 동작은 tests/test_automation_api.py 가
이미 담당합니다.

나머지 잔존 항목은 docs/handoff/2026-08-01_session_todo.md 에 기록되어 있습니다.
"""

from unittest.mock import patch

from src.app.models.chatbot import AutomationRequest

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


def _chat(client, message: str, **extra):
    return client.post("/api/v1/chatbot/chat", json={"message": message, **extra})


def test_new_chat_session_returns_fresh_key(client, isolated_db):
    """원본 test_new_chat_session_api_cycles_only_chat_session 대응.

    원본은 Django 세션을 갈아끼우므로 로그인 유지까지 확인했습니다. 이식본은
    세션 키를 응답으로만 돌려주는 무상태 방식이라, 직전 키와 달라지는지와
    이전 대화 상태가 보존되는지를 확인합니다.
    """
    _login(client)
    first = _chat(client, "최근 공고 보여줘")
    old_key = first.json()["session_key"]

    response = client.post("/api/v1/chatbot/session/new")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["session_key"] != old_key

    # 새 세션을 만들어도 이전 세션 상태는 남아 있어야 합니다.
    switched = _chat(client, "", session_key=old_key)
    assert switched.json()["session_key"] == old_key


def test_chat_switches_to_persisted_session_history(client, isolated_db):
    """원본 test_chat_api_switches_to_persisted_session_history 대응.

    메시지 없이 session_key 만 보내면 전환 모드로 직전 결과를 되돌려 줍니다.
    """
    _login(client)
    first = _chat(client, "최근 공고 보여줘")
    session_key = first.json()["session_key"]

    response = _chat(client, "", session_key=session_key)
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "switch"
    assert payload["session_key"] == session_key


def test_chat_without_message_and_without_session_returns_error(client, isolated_db):
    """빈 요청은 전환이 아니라 오류로 처리되어야 합니다 (원본 동일)."""
    _login(client)
    payload = _chat(client, "").json()
    assert payload["status"] == "error"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_chat_creates_automation_request_for_data_refresh(mock_enqueue, client, isolated_db):
    """원본 test_chat_api_creates_running_automation_request_for_data_refresh 대응.

    자연어 요청이 action 모드로 분류되어 AutomationRequest 레코드까지 생성되는지
    확인합니다. 원본의 Harness 관련 단언(plan_execution_id, callback_mode)은
    Harness 를 제거한 이식본에 대응 개념이 없어 제외했습니다.
    """
    _login(client)
    response = _chat(client, "오늘 데이터 갱신해서 그래프 보여줘")
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "action"
    assert payload["intent"] == "data_refresh"
    assert payload["job"]["run_mode"] == "refresh_data"

    request_obj = isolated_db.query(AutomationRequest).one()
    assert request_obj.action_key == "data_refresh"
    assert request_obj.payload["source"] == "chat_api"


def test_chat_requires_login_for_automation(client, isolated_db):
    """원본은 로그인 사용자만 자동화를 실행합니다. 비로그인은 오류여야 합니다."""
    response = _chat(client, "오늘 데이터 갱신해줘")
    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["intent"] == "data_refresh"


def test_chat_requires_confirmation_for_full_validation(client, isolated_db):
    """원본 test_chat_api_requires_confirmation_for_full_validation 대응."""
    _login(client)
    payload = _chat(client, "전체 점검해줘").json()
    assert payload["mode"] == "confirmation"
    assert payload["confirmation_token"]


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_chat_cancel_pending_confirmation_marks_canceled(mock_enqueue, client, isolated_db):
    """원본 test_cancel_pending_confirmation_request_marks_canceled 대응.

    확인 대기 상태의 요청은 워커에 넣지 않은 채 취소되어야 합니다.
    """
    _login(client)
    job_id = _chat(client, "전체 점검해줘").json()["job"]["job_id"]

    cancel_resp = client.post(f"/api/v1/automation/job/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["job"]["status"] == "canceled"
    # 확인 전 취소이므로 실제 실행은 한 번도 예약되지 않아야 합니다.
    mock_enqueue.assert_not_called()
