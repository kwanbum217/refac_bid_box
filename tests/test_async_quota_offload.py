"""
tests/test_async_quota_offload.py

문서 추출·SSR 로그인·SSR 회원가입 핸들러가 Redis 쿼터/제한기 검사를 이벤트 루프
스레드에서 실행하지 않음을 검증합니다. 세 경로는 인증 없이(또는 저비용 인증만으로)
반복 호출할 수 있어, Redis 가 연결만 받고 응답하지 않으면 루프가 그대로 점유되어
서비스 전체 API 가 멈춥니다.

판정 방법: 오프로드된 스레드에는 실행 중인 이벤트 루프가 없으므로
asyncio.get_running_loop() 이 RuntimeError 를 냅니다. 또한 asyncio.to_thread 를
기록해 쿼터 함수가 실제로 그 경로로 넘어갔는지 함께 확인합니다.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

import src.app.api.ui as ui
import src.app.api.v1.documents as documents
from src.app.api.v1.accounts import require_current_user
from src.app.core.security import login_rate_limiter, signup_rate_limiter
from src.app.main import app
from tests.test_csrf import csrf_form

SIGNUP_FORM = {
    "username": "quota_offload_new",
    "password1": "offload-pass-1234",
    "password2": "offload-pass-1234",
    "nickname": "쿼터 오프로드",
    "email": "quota_offload_new@example.com",
    "birth_date": "1990-01-01",
    "gender": "M",
    "agree_terms": "on",
    "agree_privacy": "on",
}


def _on_loop_thread() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def _spy(observed: list[bool]):
    def _record(*_args, **_kwargs) -> None:
        observed.append(_on_loop_thread())

    return _record


@pytest.fixture
def offload_calls(monkeypatch) -> list[object]:
    """asyncio.to_thread 로 넘어간 호출 대상을 기록합니다."""
    calls: list[object] = []
    real_to_thread = asyncio.to_thread

    async def _spy_to_thread(func, /, *args, **kwargs):
        calls.append(func)
        return await real_to_thread(func, *args, **kwargs)

    monkeypatch.setattr(asyncio, "to_thread", _spy_to_thread)
    return calls


def test_document_extraction_quota_runs_off_loop(client, isolated_db, monkeypatch, offload_calls):
    observed: list[bool] = []
    quota = _spy(observed)
    monkeypatch.setattr(documents, "enforce_document_extraction_quota", quota)
    monkeypatch.setattr(documents.settings, "DOCUMENT_EXTRACTION_ENABLED", True, raising=False)
    app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=1)
    try:
        response = client.post(
            "/api/v1/documents/extract",
            content=b"not a pdf",
            headers={"content-type": "text/plain"},
        )
    finally:
        app.dependency_overrides.pop(require_current_user, None)

    assert response.status_code == 415, response.text
    assert observed == [False], "문서 추출 쿼터가 이벤트 루프 스레드에서 실행되었습니다"
    assert quota in offload_calls


def test_signup_quota_runs_off_loop(client, monkeypatch, offload_calls):
    observed: list[bool] = []
    check = _spy(observed)
    record = _spy(observed)
    monkeypatch.setattr(signup_rate_limiter, "check_rate_limit", check)
    monkeypatch.setattr(signup_rate_limiter, "record_attempt", record)
    monkeypatch.setattr(ui, "_register_user_sync", lambda payload, response: None)

    response = client.post(
        "/accounts/signup/",
        data=csrf_form(client, "/accounts/signup/", SIGNUP_FORM),
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert observed == [False, False], "회원가입 제한기가 이벤트 루프 스레드에서 실행되었습니다"
    assert check in offload_calls
    assert record in offload_calls


def test_login_quota_and_failure_record_run_off_loop(client, monkeypatch, offload_calls):
    observed: list[bool] = []
    check = _spy(observed)
    failure = _spy(observed)
    monkeypatch.setattr(login_rate_limiter, "check_rate_limit", check)
    monkeypatch.setattr(login_rate_limiter, "record_failure", failure)
    monkeypatch.setattr(
        ui,
        "_authenticate_and_update_login",
        lambda _username, _password: {"status": "not_found"},
    )

    response = client.post(
        "/accounts/login/",
        data=csrf_form(
            client,
            "/accounts/login/",
            {"username": "quota_offload_none", "password": "offload-pass-1234"},
        ),
        follow_redirects=False,
    )

    assert response.status_code == 401, response.text
    assert observed == [False, False], "로그인 제한기가 이벤트 루프 스레드에서 실행되었습니다"
    assert check in offload_calls
    assert failure in offload_calls


def test_login_success_record_runs_off_loop(client, monkeypatch, offload_calls):
    observed: list[bool] = []
    success = _spy(observed)
    monkeypatch.setattr(login_rate_limiter, "record_success", success)
    monkeypatch.setattr(
        ui,
        "_authenticate_and_update_login",
        lambda _username, _password: {
            "status": "success",
            "user_id": 5,
            "username": "quota_offload_user",
        },
    )
    monkeypatch.setattr(ui, "create_session", lambda _user_id, _username: "session-token")

    response = client.post(
        "/accounts/login/",
        data=csrf_form(
            client,
            "/accounts/login/",
            {"username": "quota_offload_user", "password": "offload-pass-1234"},
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert observed == [False], "로그인 성공 기록이 이벤트 루프 스레드에서 실행되었습니다"
    assert success in offload_calls
