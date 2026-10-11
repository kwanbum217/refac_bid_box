"""워커 콜백이 토큰 검증을 작업 조회보다 먼저 수행하는지 검증합니다.

토큰 검증 전에 job 을 조회하면 응답 코드(404 vs 403)로 job 존재 여부가
드러납니다. 토큰을 먼저 검증하면 잘못된 토큰은 job 존재 여부와 무관하게 항상
403 이고, 토큰이 유효할 때만 조회해 없으면 404 가 됩니다. 기존 job 에 대한
잘못된 토큰 403 은 tests/test_automation_status_api.py 가 함께 확인합니다.
"""

from __future__ import annotations

from src.app.services.automation_tokens import make_callback_token

MISSING_JOB = "job-that-does-not-exist"
CALLBACK_PATH = f"/api/v1/automation/job/{MISSING_JOB}/callback"
CALLBACK_REJECTION_DETAIL = "유효하지 않은 callback 토큰입니다."


def test_invalid_token_with_missing_job_is_403_not_404(client):
    response = client.post(
        CALLBACK_PATH,
        json={},
        headers={"X-BIDBOX-CALLBACK-TOKEN": "invalid"},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == CALLBACK_REJECTION_DETAIL


def test_missing_token_with_missing_job_is_403(client):
    response = client.post(CALLBACK_PATH, json={})
    assert response.status_code == 403
    assert response.json()["detail"] == CALLBACK_REJECTION_DETAIL


def test_token_signed_for_other_job_is_403(client):
    response = client.post(
        CALLBACK_PATH,
        json={},
        headers={"X-BIDBOX-CALLBACK-TOKEN": make_callback_token("some-other-job")},
    )
    assert response.status_code == 403
    assert response.json()["detail"] == CALLBACK_REJECTION_DETAIL


def test_valid_token_with_missing_job_reaches_lookup_and_is_404(client):
    response = client.post(
        CALLBACK_PATH,
        json={},
        headers={"X-BIDBOX-CALLBACK-TOKEN": make_callback_token(MISSING_JOB)},
    )
    assert response.status_code == 404
