"""
tests/test_ssr_auth_offload.py

SSR 회원가입·로그인 핸들러가 동기 DB 트랜잭션과 PBKDF2 해싱을 이벤트 루프
스레드에서 수행하지 않음을 검증합니다. 두 경로는 인증 없이 누구나 호출할 수
있어 루프를 점유하면 요청 반복만으로 서비스 전체가 멈춥니다.

판정 방법: 오프로드된 스레드에는 실행 중인 이벤트 루프가 없으므로
asyncio.get_running_loop() 이 RuntimeError 를 냅니다. 루프 스레드에서
실행되면 루프 객체가 반환되며 그때 테스트가 실패합니다.
"""

import asyncio

import pytest

import src.app.api.ui as ui
from src.app.core.security import make_password
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from tests.test_csrf import csrf_form


def _on_loop_thread() -> bool:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


@pytest.fixture
def offload_user(isolated_db):
    user = CustomUser(
        username="offload_tester",
        password=make_password("offload-pass-1234"),
        email="offload@example.com",
        nickname="오프로드 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    return user


def test_login_password_verification_runs_off_loop_thread(client, offload_user, monkeypatch):
    observed: list[bool] = []
    original = ui.check_password

    def _spy(raw, encoded):
        observed.append(_on_loop_thread())
        return original(raw, encoded)

    monkeypatch.setattr(ui, "check_password", _spy)

    response = client.post(
        "/accounts/login/",
        data=csrf_form(
            client,
            "/accounts/login/",
            {"username": "offload_tester", "password": "offload-pass-1234"},
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303
    assert observed == [False], "check_password 가 이벤트 루프 스레드에서 실행되었습니다"


def test_signup_registration_runs_off_loop_thread(client, monkeypatch):
    observed: list[bool] = []
    original = ui.register_user

    def _spy(payload, response, db):
        observed.append(_on_loop_thread())
        return original(payload, response, db)

    monkeypatch.setattr(ui, "register_user", _spy)

    response = client.post(
        "/accounts/signup/",
        data=csrf_form(
            client,
            "/accounts/signup/",
            {
                "username": "offload_new",
                "password1": "offload-pass-1234",
                "password2": "offload-pass-1234",
                "nickname": "신규 오프로드",
                "email": "offload_new@example.com",
                "birth_date": "1990-01-01",
                "gender": "M",
                "agree_terms": "on",
                "agree_privacy": "on",
            },
        ),
        follow_redirects=False,
    )

    assert response.status_code == 303, response.text
    assert observed == [False], "register_user 가 이벤트 루프 스레드에서 실행되었습니다"
