"""전체 로그아웃(모든 기기에서 로그아웃) 시험.

정본: .orca/capsules/task_ca934d35d437/capsule.yaml.
 - POST /accounts/mypage/logout-all/ 는 로그인 + CSRF 를 요구한다.
 - 전체 로그아웃 후 그 사용자의 모든 세션(현재 세션 포함)은 무효다.
 - 다른 사용자의 세션과 전체 로그아웃 뒤 새로 만든 세션은 영향을 받지 않는다.
 - 세대 필드가 없는 배포 이전 세션은 계속 유효하다.
 - 비로그인 POST 는 로그인 화면으로 리다이렉트된다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.core import security
from src.app.core.security import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    create_session,
    make_password,
)
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from tests.test_csrf import csrf_form

LOGOUT_ALL_URL = "/accounts/mypage/logout-all/"
MYPAGE_URL = "/accounts/mypage/"


@pytest.fixture(autouse=True)
def _isolate_local_sessions(monkeypatch):
    """세션 저장소 로컬 대체 상태(세대 포함)를 시험마다 비웁니다.

    Redis 가 없는 시험 환경에서는 session_store 가 프로세스 로컬 dict 로
    내려갑니다. 이 dict 는 전역 단일 객체라 시험 간 세대 값이 새지 않도록
    매 시험 앞에서 비웁니다.
    """
    monkeypatch.setattr(security.session_store, "_local", {})


def _create_user(db, *, username: str) -> CustomUser:
    user = CustomUser(
        username=username,
        password=make_password("pw-test-1234"),
        email=f"{username}@example.com",
        nickname=username,
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _auth_client(user: CustomUser) -> TestClient:
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def _is_logged_in(client: TestClient) -> bool:
    return client.get(MYPAGE_URL, follow_redirects=False).status_code == 200


def test_logout_all_invalidates_every_session_of_the_user(isolated_db):
    """같은 사용자의 두 세션(다른 기기)이 모두 무효가 된다."""
    user = _create_user(isolated_db, username="logout_all_two")
    client_one = _auth_client(user)
    client_two = _auth_client(user)
    assert _is_logged_in(client_one)
    assert _is_logged_in(client_two)

    response = client_one.post(
        LOGOUT_ALL_URL, data=csrf_form(client_one, MYPAGE_URL, {}), follow_redirects=False
    )

    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/login/"
    # 현재 세션 쿠키도 지운다.
    assert SESSION_COOKIE_NAME not in response.cookies
    assert not _is_logged_in(client_one)
    assert not _is_logged_in(client_two)


def test_logout_all_keeps_other_users_sessions(isolated_db):
    """다른 사용자의 세션은 영향을 받지 않는다."""
    owner = _create_user(isolated_db, username="logout_all_owner")
    other = _create_user(isolated_db, username="logout_all_other")
    owner_client = _auth_client(owner)
    other_client = _auth_client(other)

    owner_client.post(
        LOGOUT_ALL_URL, data=csrf_form(owner_client, MYPAGE_URL, {}), follow_redirects=False
    )

    assert not _is_logged_in(owner_client)
    assert _is_logged_in(other_client)


def test_new_session_after_logout_all_is_valid(isolated_db):
    """전체 로그아웃 뒤 새로 로그인한 세션은 유효하다."""
    user = _create_user(isolated_db, username="logout_all_relogin")
    client = _auth_client(user)
    client.post(LOGOUT_ALL_URL, data=csrf_form(client, MYPAGE_URL, {}), follow_redirects=False)

    fresh_client = _auth_client(user)

    assert _is_logged_in(fresh_client)


def test_logout_all_without_csrf_is_rejected(monkeypatch, isolated_db):
    """CSRF 토큰 없는 POST 는 403 이고 세션은 그대로다."""
    user = _create_user(isolated_db, username="logout_all_csrf")
    monkeypatch.setattr(security.settings, "CSRF_PROTECTION_ENABLED", True, raising=False)
    client = _auth_client(user)

    response = client.post(LOGOUT_ALL_URL, data={}, follow_redirects=False)

    assert response.status_code == 403
    assert _is_logged_in(client)


def test_logout_all_anonymous_post_redirects_to_login(client):
    """비로그인 POST 는 로그인 화면으로 리다이렉트된다."""
    response = client.post(LOGOUT_ALL_URL, data={}, follow_redirects=False)

    assert response.status_code == 303
    assert response.headers["location"] == f"/accounts/login/?next={LOGOUT_ALL_URL}"


def test_legacy_session_without_generation_field_stays_valid(isolated_db):
    """세대 필드가 없는 배포 이전 세션은 계속 유효하다."""
    user = _create_user(isolated_db, username="logout_all_legacy")
    legacy_session_id = "legacy-session-without-generation"
    security.session_store._local[legacy_session_id] = (
        security.time.time() + SESSION_TTL_SECONDS,
        {"user_id": user.id, "username": user.username},
    )
    client = TestClient(app, cookies={SESSION_COOKIE_NAME: legacy_session_id})

    assert _is_logged_in(client)


def test_invalidate_all_sessions_discards_old_and_accepts_new():
    """저장소 수준에서 이전 세대 세션은 파기되고 새 세대 세션은 유효하다."""
    user_id = 424242
    token = create_session(user_id, "epoch-user")
    assert security.read_session(token) is not None

    generation = security.invalidate_all_sessions(user_id)

    assert generation >= 1
    assert security.read_session(token) is None
    fresh_token = create_session(user_id, "epoch-user")
    assert security.read_session(fresh_token) == {
        "user_id": user_id,
        "username": "epoch-user",
    }


def test_mypage_renders_logout_all_form(client, isolated_db):
    """마이페이지에 전체 로그아웃 POST 폼과 CSRF 필드가 있다."""
    user = _create_user(isolated_db, username="logout_all_form")
    body = _auth_client(user).get(MYPAGE_URL).text

    assert f'action="{LOGOUT_ALL_URL}"' in body
    assert 'name="csrf_token"' in body
    assert "모든 기기에서 로그아웃" in body
