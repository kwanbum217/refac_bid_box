"""
tests/test_automation_rbac.py

자동화 API RBAC 및 확인 토큰 일회성 검증.
 - 비직원 사용자는 run 계열 5개 엔드포인트에 접근할 수 없다 (403).
 - 직원 사용자는 run 계열 엔드포인트에 접근할 수 있다.
 - 빈 토큰 또는 토큰 없이 confirm 을 호출하면 403 이며 상태가 전이되지 않는다.
 - 위조 토큰, 다른 job 의 토큰, 만료 토큰이 모두 거부된다.
 - 같은 확인 토큰을 두 번째로 제출하면 거부된다 (일회성).
 - 워커 콜백 경로는 RBAC 적용 전과 동일하게 동작한다.
"""

from unittest.mock import patch

import pytest

from src.app.services.automation_tokens import (
    _sign,
)
from tests.fake_redis import fake_confirmation_redis


@pytest.fixture(autouse=True)
def fake_redis_for_automation_tokens():
    """확인 토큰 소비 경로에 대역 Redis 연결을 주입합니다 (운영 코드는 fail-closed 유지)."""
    with fake_confirmation_redis():
        yield


VALID_SIGNUP = {
    "username": "rbac-user",
    "password1": "StrongPass123!!",
    "password2": "StrongPass123!!",
    "nickname": "RBAC테스터",
    "email": "rbac@example.com",
    "birth_date": "1990-01-01",
    "gender": "M",
    "agree_terms": True,
    "agree_privacy": True,
}

RUN_ENDPOINTS = [
    "/api/v1/automation/run/collect-bids",
    "/api/v1/automation/run/update-kb",
    "/api/v1/automation/run/predict",
    "/api/v1/automation/run/manual-full",
    "/api/v1/automation/run/retrain",
]


def _signup(client, **overrides):
    payload = {**VALID_SIGNUP, **overrides}
    return client.post("/api/v1/accounts/signup", json=payload)


def _login(client, username="rbac-user"):
    client.post(
        "/api/v1/accounts/login",
        json={"username": username, "password": "StrongPass123!!"},
    )


def _make_staff(client, isolated_db):
    """로그인한 사용자를 staff 로 승급시킨다."""
    from src.app.models.accounts import CustomUser

    user = isolated_db.execute(
        __import__("sqlalchemy").select(CustomUser).where(CustomUser.username == "rbac-user")
    ).scalar_one()
    user.is_staff = True
    isolated_db.commit()


# --------------------------------------------------------------------------- #
# RBAC: 비직원 사용자 403
# --------------------------------------------------------------------------- #


def test_non_staff_user_gets_403_on_all_run_endpoints(client, isolated_db):
    _signup(client)
    _login(client)
    for endpoint in RUN_ENDPOINTS:
        response = client.post(endpoint, json={"reason": "테스트"})
        assert response.status_code == 403, f"{endpoint} expected 403, got {response.status_code}"
        assert "관리자 권한" in response.json()["detail"]


# --------------------------------------------------------------------------- #
# RBAC: 직원 사용자 정상 접근
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_staff_user_can_access_run_endpoints(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)
    for endpoint in RUN_ENDPOINTS:
        response = client.post(endpoint, json={"reason": "테스트"})
        assert response.status_code == 200, f"{endpoint} expected 200, got {response.status_code}"


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_superuser_can_access_run_endpoints(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    import sqlalchemy

    from src.app.models.accounts import CustomUser

    user = isolated_db.execute(
        sqlalchemy.select(CustomUser).where(CustomUser.username == "rbac-user")
    ).scalar_one()
    user.is_superuser = True
    isolated_db.commit()

    response = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# 확인 토큰: 빈 토큰 거부
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_rejects_empty_token(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)

    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]

    confirm_resp = client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={"confirmation_token": ""},
    )
    assert confirm_resp.status_code == 403
    assert "확인 토큰이 필요합니다" in confirm_resp.json()["detail"]


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_rejects_missing_token(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)

    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]

    confirm_resp = client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={},
    )
    assert confirm_resp.status_code == 403


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_empty_token_does_not_transition_status(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)

    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]

    client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={"confirmation_token": ""},
    )

    status_resp = client.get(f"/api/v1/automation/job/{job_id}/status")
    assert status_resp.json()["data"]["status"] == "pending_confirmation"


# --------------------------------------------------------------------------- #
# 확인 토큰: 위조 토큰 거부
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_rejects_forged_token(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)

    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]

    confirm_resp = client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={"confirmation_token": "forged:token:value"},
    )
    assert confirm_resp.status_code == 403


# --------------------------------------------------------------------------- #
# 확인 토큰: 다른 job 의 토큰 거부
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_rejects_token_from_different_job(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)

    create_resp_a = client.post("/api/v1/automation/run/manual-full", json={"reason": "작업 A"})
    token_a = create_resp_a.json()["confirmation_token"]

    create_resp_b = client.post("/api/v1/automation/run/manual-full", json={"reason": "작업 B"})
    job_id_b = create_resp_b.json()["job"]["job_id"]

    confirm_resp = client.post(
        f"/api/v1/automation/job/{job_id_b}/confirm",
        json={"confirmation_token": token_a},
    )
    assert confirm_resp.status_code == 403
    assert "일치하지 않습니다" in confirm_resp.json()["detail"]


# --------------------------------------------------------------------------- #
# 확인 토큰: 만료 토큰 거부
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_rejects_expired_token(mock_enqueue, client, isolated_db):
    import time

    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)

    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]

    expired_token = _sign(job_id, "bidbox.automation.confirmation")
    parts = expired_token.rsplit(":", 2)
    old_timestamp = str(int(time.time()) - 60 * 60)
    expired_token = f"{parts[0]}:{old_timestamp}:{parts[2]}"

    confirm_resp = client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={"confirmation_token": expired_token},
    )
    assert confirm_resp.status_code == 403


# --------------------------------------------------------------------------- #
# 확인 토큰: 일회성 (재사용 거부)
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_confirm_rejects_reused_token(mock_enqueue, client, isolated_db):
    _signup(client)
    _login(client)
    _make_staff(client, isolated_db)

    create_resp = client.post("/api/v1/automation/run/manual-full", json={"reason": "전체 점검"})
    job_id = create_resp.json()["job"]["job_id"]
    token = create_resp.json()["confirmation_token"]

    first_resp = client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={"confirmation_token": token},
    )
    assert first_resp.status_code == 200

    replay_resp = client.post(
        f"/api/v1/automation/job/{job_id}/confirm",
        json={"confirmation_token": token},
    )
    assert replay_resp.status_code == 403
    assert "이미 사용된" in replay_resp.json()["detail"]


# --------------------------------------------------------------------------- #
# 워커 콜백 경로는 변경 없음
# --------------------------------------------------------------------------- #


@patch("src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True)
def test_callback_path_unchanged_by_rbac(mock_enqueue, client, isolated_db):
    from src.app.services.automation_orchestrator import make_callback_token

    _signup(client)
    _login(client)

    create_resp = client.post(
        "/api/v1/automation/run/collect-bids",
        json={"reason": "테스트"},
        headers={"Authorization": "ignored"},
    )
    assert create_resp.status_code == 403

    import sqlalchemy

    from src.app.models.accounts import CustomUser

    user = isolated_db.execute(
        sqlalchemy.select(CustomUser).where(CustomUser.username == "rbac-user")
    ).scalar_one()
    user.is_staff = True
    isolated_db.commit()

    create_resp = client.post("/api/v1/automation/run/collect-bids", json={"reason": "테스트"})
    job_id = create_resp.json()["job"]["job_id"]
    token = make_callback_token(job_id)

    callback_resp = client.post(
        f"/api/v1/automation/job/{job_id}/callback",
        json={"step": "collect", "status": "success", "summary": "완료", "final": True},
        headers={"X-BIDBOX-CALLBACK-TOKEN": token},
    )
    assert callback_resp.status_code == 200
    assert callback_resp.json()["status"] == "success"
