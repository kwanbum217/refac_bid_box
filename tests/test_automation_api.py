"""
tests/test_automation_api.py

원본 apps/chatbot/tests.py ChatAutomationApiTests 중 automation API 핵심 검증 이식.
 - 데이터 갱신 실행 → 자동화 요청 생성
 - 전체 점검 → 확인 필요 (high_cost)
 - 실행 취소
 - 상태 조회
 - 미인증 차단
"""

from unittest.mock import patch

VALID_SIGNUP = {
    "username": "automation-user",
    "password1": "StrongPass123!!",
    "password2": "StrongPass123!!",
    "nickname": "테스터",
    "email": "auto@example.com",
    "birth_date": "1999-05-17",
    "gender": "F",
    "agree_terms": True,
    "agree_privacy": True,
}


def _login(client):
    client.post("/api/v1/accounts/signup", json=VALID_SIGNUP)
    client.post(
        "/api/v1/accounts/login",
        json={"username": "automation-user", "password": "StrongPass123!!"},
    )


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_collect_bids_creates_automation_request(mock_enqueue, client, isolated_db):
    _login(client)
    response = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["job"]["action_key"] == "collect_refresh"
    assert payload["job"]["run_mode"] == "collect_only"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_manual_full_requires_confirmation(mock_enqueue, client, isolated_db):
    _login(client)
    response = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    assert response.status_code == 200
    payload = response.json()
    assert payload["mode"] == "confirmation"
    assert payload["confirmation_token"]


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_cancel_pending_confirmation(mock_enqueue, client, isolated_db):
    _login(client)
    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]

    cancel_resp = client.post(f"/api/v1/automation/job/{job_id}/cancel")
    assert cancel_resp.status_code == 200
    assert cancel_resp.json()["job"]["status"] == "canceled"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_status_query_returns_job_details(mock_enqueue, client, isolated_db):
    _login(client)
    create_resp = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    job_id = create_resp.json()["job"]["job_id"]

    status_resp = client.get(f"/api/v1/automation/job/{job_id}/status")
    assert status_resp.status_code == 200
    data = status_resp.json()["data"]
    assert data["job_id"] == job_id
    assert data["action_key"] == "collect_refresh"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_executes_pending_request(mock_enqueue, client, isolated_db):
    _login(client)
    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]
    token = create_resp.json()["confirmation_token"]

    confirm_resp = client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={"confirmation_token": token},
    )
    assert confirm_resp.status_code == 200
    assert confirm_resp.json()["job"]["status"] in ("running", "queued", "success")


def test_automation_requires_authentication(client, isolated_db):
    response = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    assert response.status_code == 401


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_callback_updates_step_status(mock_enqueue, client, isolated_db):
    from src.app.services.automation_orchestrator import make_callback_token

    _login(client)
    create_resp = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    job_id = create_resp.json()["job"]["job_id"]
    token = make_callback_token(job_id)

    callback_resp = client.post(
        f"/api/v1/automation/job/{job_id}/callback",
        json={"step": "collect", "status": "success", "summary": "수집 완료", "final": True},
        headers={"X-BIDBOX-CALLBACK-TOKEN": token},
    )
    assert callback_resp.status_code == 200
    assert callback_resp.json()["status"] == "success"
