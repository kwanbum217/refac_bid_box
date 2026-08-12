"""
tests/test_ssr_session_store.py

A2 태스크 전용: SSR 로그인·로그아웃 경로의 SessionStoreUnavailable fail-closed,
운영/개발 쿠키 속성, GET/POST logout 계약을 monkeypatch 기반으로 검증합니다.
실제 Redis 를 호출하지 않습니다.
"""

from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import (
    SESSION_COOKIE_NAME,
    SESSION_TTL_SECONDS,
    SessionStoreUnavailable,
    make_password,
)
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser


@pytest.fixture
def login_user(isolated_db):
    user = CustomUser(
        username="a2_tester",
        password=make_password("a2-pass-1234"),
        email="a2@example.com",
        nickname="A2 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    return user


# ---------------------------------------------------------------------------
# 쿠키 속성 검증
# ---------------------------------------------------------------------------


def test_login_cookie_development_not_secure(client, login_user):
    """development 환경에서는 secure 쿠키를 발급하지 않는다."""
    response = client.post(
        "/accounts/login/",
        data={"username": "a2_tester", "password": "a2-pass-1234"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie_header = response.headers.get("set-cookie", "")
    # conftest 에서 ENVIRONMENT 기본값이 development 이므로 secure 가 없어야 한다
    assert "secure" not in cookie_header.lower()


def test_login_cookie_production_is_secure(client, login_user):
    """production 환경에서는 secure, samesite=lax, httponly, max_age 가 발급된다."""
    with patch("src.app.api.ui.settings") as mock_settings:
        mock_settings.ENVIRONMENT = "production"
        response = client.post(
            "/accounts/login/",
            data={"username": "a2_tester", "password": "a2-pass-1234"},
            follow_redirects=False,
        )
    assert response.status_code == 303
    cookie_header = response.headers.get("set-cookie", "").lower()
    assert "secure" in cookie_header
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header
    assert f"max-age={SESSION_TTL_SECONDS}".lower() in cookie_header


def test_login_cookie_has_correct_ttl(client, login_user):
    """SSR 쿠키의 max-age 가 SESSION_TTL_SECONDS 와 일치한다."""
    response = client.post(
        "/accounts/login/",
        data={"username": "a2_tester", "password": "a2-pass-1234"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie_header = response.headers.get("set-cookie", "").lower()
    assert f"max-age={SESSION_TTL_SECONDS}" in cookie_header


def test_login_cookie_has_httponly_and_samesite(client, login_user):
    """development 에서도 httponly 와 samesite=lax 는 반드시 포함된다."""
    response = client.post(
        "/accounts/login/",
        data={"username": "a2_tester", "password": "a2-pass-1234"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    cookie_header = response.headers.get("set-cookie", "").lower()
    assert "httponly" in cookie_header
    assert "samesite=lax" in cookie_header


# ---------------------------------------------------------------------------
# login create 장애 503
# ---------------------------------------------------------------------------


def test_login_create_session_unavailable_returns_503(client, login_user):
    """SessionStore.create 가 실패하면 성공 리다이렉트 없이 503 을 반환한다."""
    with patch(
        "src.app.api.ui.create_session",
        side_effect=SessionStoreUnavailable("Redis 연결 없음"),
    ):
        response = client.post(
            "/accounts/login/",
            data={"username": "a2_tester", "password": "a2-pass-1234"},
            follow_redirects=False,
        )
    assert response.status_code == 503
    # 성공 리다이렉트가 없어야 한다
    assert response.headers.get("location") is None
    # 쿠키가 발급되지 않아야 한다
    assert SESSION_COOKIE_NAME not in response.cookies


def test_login_create_unavailable_does_not_expose_exception(client, login_user):
    """503 응답에 예외 원문이 그대로 노출되지 않는다."""
    internal_reason = "Redis sentinel auth token leak"
    with patch(
        "src.app.api.ui.create_session",
        side_effect=SessionStoreUnavailable(internal_reason),
    ):
        response = client.post(
            "/accounts/login/",
            data={"username": "a2_tester", "password": "a2-pass-1234"},
            follow_redirects=False,
        )
    assert response.status_code == 503
    assert internal_reason not in response.text


# ---------------------------------------------------------------------------
# logout destroy 장애 503
# ---------------------------------------------------------------------------


def test_logout_destroy_session_unavailable_get_returns_503(isolated_db):
    """GET logout 에서 destroy_session 이 실패하면 503 이다."""
    auth_client = TestClient(app, cookies={SESSION_COOKIE_NAME: "live-token"})
    with patch(
        "src.app.api.ui.destroy_session",
        side_effect=SessionStoreUnavailable("Redis 다운"),
    ):
        response = auth_client.get("/accounts/logout/", follow_redirects=False)
    assert response.status_code == 503
    # 로그인 페이지로 리다이렉트되지 않아야 한다
    assert response.headers.get("location") is None


def test_logout_destroy_session_unavailable_post_returns_503(isolated_db):
    """POST logout 에서 destroy_session 이 실패하면 503 을 반환한다."""
    auth_client = TestClient(app, cookies={SESSION_COOKIE_NAME: "live-token"})
    with patch(
        "src.app.api.ui.destroy_session",
        side_effect=SessionStoreUnavailable("Redis 다운"),
    ):
        response = auth_client.post("/accounts/logout/", follow_redirects=False)
    assert response.status_code == 503


def test_logout_destroy_unavailable_does_not_delete_cookie(isolated_db):
    """destroy_session 실패 시 쿠키 삭제 헤더가 포함되지 않는다."""
    auth_client = TestClient(app, cookies={SESSION_COOKIE_NAME: "live-token"})
    with patch(
        "src.app.api.ui.destroy_session",
        side_effect=SessionStoreUnavailable("Redis 다운"),
    ):
        response = auth_client.get("/accounts/logout/", follow_redirects=False)
    assert response.status_code == 503
    # set-cookie 헤더에 삭제(Max-Age=0) 지시가 없어야 한다
    cookie_header = response.headers.get("set-cookie", "").lower()
    assert "max-age=0" not in cookie_header


# ---------------------------------------------------------------------------
# 정상 login / logout
# ---------------------------------------------------------------------------


def test_normal_login_redirects_to_home(client, login_user):
    """정상 로그인은 303 으로 홈에 보내고 세션 쿠키를 발급한다."""
    response = client.post(
        "/accounts/login/",
        data={"username": "a2_tester", "password": "a2-pass-1234"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"
    assert SESSION_COOKIE_NAME in response.cookies


def test_normal_logout_get_redirects_to_login(isolated_db):
    """정상 GET 로그아웃은 303 으로 로그인 화면에 보내고 쿠키를 삭제한다."""
    auth_client = TestClient(app, cookies={SESSION_COOKIE_NAME: "normal-token"})
    with patch("src.app.api.ui.destroy_session"):
        response = auth_client.get("/accounts/logout/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/login/"


def test_normal_logout_post_redirects_to_login(isolated_db):
    """정상 POST 로그아웃도 303 으로 로그인 화면에 보낸다."""
    auth_client = TestClient(app, cookies={SESSION_COOKIE_NAME: "normal-token-post"})
    with patch("src.app.api.ui.destroy_session"):
        response = auth_client.post("/accounts/logout/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/login/"
