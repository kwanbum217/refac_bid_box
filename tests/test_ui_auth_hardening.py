"""
tests/test_ui_auth_hardening.py

보안 검토 L 계열 보강 검증:
  - L3: CSRF 쿠키가 세션 쿠키와 같은 기준으로 production 에서 Secure 로 발급된다.
  - L5: next 경로가 백슬래시·제어문자를 포함하면 루트로 되돌린다.
  - L1: 계정이 없어도 더미 해시로 비밀번호 검증을 수행해 타이밍 열거를 막는다.
"""

from __future__ import annotations

import pytest

from src.app.api.ui import _safe_next_path
from src.app.api.v1 import accounts
from src.app.core.config import settings
from src.app.core.security import make_password
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from tests.test_csrf import csrf_form


def _seed_user(db, username: str, password: str):
    user = CustomUser(
        username=username,
        password=make_password(password),
        email=f"{username}@example.com",
        nickname="보강",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# --------------------------------------------------------------------------- #
# L5: next 경로 검증
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "value",
    [
        "/\\evil.example",
        "/bids/\\evil",
        "/path\x00x",
        "/path\x1fbroken",
        "//evil.example",
        "https://evil.example",
        "evil.example",
    ],
)
def test_safe_next_path_rejects_unsafe_values(value):
    assert _safe_next_path(value) == "/"


@pytest.mark.parametrize(
    "value,expected",
    [
        ("/bids/", "/bids/"),
        ("/bids/?q=1&cat=Thng", "/bids/?q=1&cat=Thng"),
        ("/#anchor", "/#anchor"),
        ("/", "/"),
        (None, "/"),
    ],
)
def test_safe_next_path_accepts_normal_values(value, expected):
    assert _safe_next_path(value) == expected


def test_ssr_login_with_backslash_next_redirects_to_root(client, isolated_db):
    _seed_user(isolated_db, "ssr_next_user", "StrongPass1234!")
    form = csrf_form(
        client,
        "/accounts/login/",
        {"username": "ssr_next_user", "password": "StrongPass1234!"},
    )
    response = client.post(
        "/accounts/login/",
        params={"next": "/\\evil.example"},
        data=form,
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/"


# --------------------------------------------------------------------------- #
# L3: CSRF 쿠키 Secure
# --------------------------------------------------------------------------- #


def test_csrf_cookie_is_secure_outside_development(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "production")
    response = client.get("/accounts/login/")
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "bidbox_csrf" in set_cookie
    assert "secure" in set_cookie


def test_csrf_cookie_is_not_secure_in_development(client, monkeypatch):
    monkeypatch.setattr(settings, "ENVIRONMENT", "development")
    response = client.get("/accounts/login/")
    set_cookie = response.headers.get("set-cookie", "").lower()
    assert "bidbox_csrf" in set_cookie
    assert "secure" not in set_cookie


# --------------------------------------------------------------------------- #
# L1: 계정 열거 타이밍 차이
# --------------------------------------------------------------------------- #


def test_dummy_password_hash_is_real_pbkdf2_hash():
    parts = accounts._DUMMY_PASSWORD_HASH.split("$")
    assert len(parts) == 4
    assert parts[0] == "pbkdf2_sha256"
    assert int(parts[1]) > 0


def test_rest_login_unknown_user_runs_dummy_password_check(client, isolated_db, monkeypatch):
    calls: list[str] = []
    real_check = accounts.check_password

    def spy(raw_password: str, encoded: str) -> bool:
        calls.append(encoded)
        return real_check(raw_password, encoded)

    monkeypatch.setattr(accounts, "check_password", spy)
    response = client.post(
        "/api/v1/accounts/login",
        json={"username": "ghost_user", "password": "whatever"},
    )
    assert response.status_code == 401
    assert calls == [accounts._DUMMY_PASSWORD_HASH]


def test_ssr_login_unknown_user_runs_dummy_password_check(client, isolated_db, monkeypatch):
    import src.app.api.ui as ui

    calls: list[str] = []
    real_check = ui.check_password

    def spy(raw_password: str, encoded: str) -> bool:
        calls.append(encoded)
        return real_check(raw_password, encoded)

    monkeypatch.setattr(ui, "check_password", spy)
    form = csrf_form(
        client,
        "/accounts/login/",
        {"username": "ghost_ssr_user", "password": "whatever"},
    )
    response = client.post("/accounts/login/", data=form, follow_redirects=False)
    assert response.status_code == 401
    assert calls == [ui._DUMMY_PASSWORD_HASH]


def test_dummy_hash_never_authenticates():
    assert accounts.check_password("anything", accounts._DUMMY_PASSWORD_HASH) is False
