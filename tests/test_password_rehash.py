"""
tests/test_password_rehash.py

보안 검토 L2 보강 검증:
  - 로그인 성공 시 반복 수가 낮은 옛 해시를 현재 정책(DEFAULT_ITERATIONS)으로
    재해시해 저장한다(API·SSR 두 경로 모두).
  - 재해시에 쓰는 salt 길이를 늘린다.
  - 비밀번호 입력 상한 4096 을 넘으면 PBKDF2 를 계산하기 전에 거부한다.

conftest 의 _fast_password fixture 가 make_password 를 1회 반복 버전으로
바꾸므로, 현재 정책 반복 수를 실제로 검증하는 시험은 임포트 시점에 붙잡아 둔
원본 make_password 로 되돌려 놓고 실행한다.
"""

from __future__ import annotations

import base64
import hashlib
import secrets

import pytest

from src.app.api.v1 import accounts
from src.app.core import security
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from tests.test_csrf import csrf_form

# conftest 의 autouse fixture 가 덮어쓰기 전에 원본을 붙잡아 둔다.
_REAL_MAKE_PASSWORD = security.make_password

_RAW_PASSWORD = "RehashStrongPass1234"  # noqa: S105 - 시험용 고정 값


def _encode(raw_password: str, iterations: int) -> str:
    """지정한 반복 수로 저장 형식 해시를 만듭니다."""
    salt = secrets.token_hex(6)
    digest = hashlib.pbkdf2_hmac("sha256", raw_password.encode(), salt.encode(), iterations)
    encoded = base64.b64encode(digest).decode().strip()
    return f"pbkdf2_sha256${iterations}${salt}${encoded}"


def _seed_user(db, username: str, encoded_password: str) -> CustomUser:
    user = CustomUser(
        username=username,
        password=encoded_password,
        email=f"{username}@example.com",
        nickname="재해시",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _stored_iterations(encoded: str) -> int:
    return int(encoded.split("$", 3)[1])


# --------------------------------------------------------------------------- #
# needs_rehash 단위 판정
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "iterations,expected",
    [
        (1000, True),
        (security.DEFAULT_ITERATIONS - 1, True),
        (security.DEFAULT_ITERATIONS, False),
        (security.DEFAULT_ITERATIONS + 1, False),
    ],
)
def test_needs_rehash_iterations(iterations, expected):
    assert security.needs_rehash(_encode("pw", iterations)) is expected


@pytest.mark.parametrize(
    "encoded",
    ["", "not-a-hash", "bcrypt$12$salt$hash", "pbkdf2_sha256$abc$salt$hash"],
)
def test_needs_rehash_malformed(encoded):
    assert security.needs_rehash(encoded) is True


def test_make_password_default_salt_is_extended(monkeypatch):
    monkeypatch.setattr(security, "make_password", _REAL_MAKE_PASSWORD)
    encoded = security.make_password("salt-check")
    assert len(encoded.split("$", 3)[2]) >= security.PASSWORD_SALT_BYTES * 2


def test_check_password_accepts_legacy_low_iterations(monkeypatch):
    monkeypatch.setattr(security, "make_password", _REAL_MAKE_PASSWORD)
    legacy = _encode("legacy-pass-1234", 1000)
    assert security.check_password("legacy-pass-1234", legacy) is True


# --------------------------------------------------------------------------- #
# API 로그인 재해시
# --------------------------------------------------------------------------- #


def test_rest_login_rehashes_low_iteration_hash(client, isolated_db, monkeypatch):
    monkeypatch.setattr(security, "make_password", _REAL_MAKE_PASSWORD)
    user = _seed_user(isolated_db, "rehash_api_user", _encode(_RAW_PASSWORD, 1000))
    user_id = user.id
    assert security.needs_rehash(user.password) is True

    response = client.post(
        "/api/v1/accounts/login",
        json={"username": "rehash_api_user", "password": _RAW_PASSWORD},
    )
    assert response.status_code == 200

    # get_db 의존성 제너레이터가 요청 뒤 세션을 닫으므로 다시 연다.
    isolated_db.close()
    stored = isolated_db.get(CustomUser, user_id)
    assert stored is not None
    assert _stored_iterations(stored.password) == security.DEFAULT_ITERATIONS
    assert security.needs_rehash(stored.password) is False

    # 재해시된 해시로도 이후 로그인이 성공한다.
    second = client.post(
        "/api/v1/accounts/login",
        json={"username": "rehash_api_user", "password": _RAW_PASSWORD},
    )
    assert second.status_code == 200


def test_rest_login_does_not_rehash_current_hash(client, isolated_db, monkeypatch):
    monkeypatch.setattr(security, "make_password", _REAL_MAKE_PASSWORD)
    current = security.make_password(_RAW_PASSWORD)
    user = _seed_user(isolated_db, "current_api_user", current)
    user_id = user.id
    before = user.password

    response = client.post(
        "/api/v1/accounts/login",
        json={"username": "current_api_user", "password": _RAW_PASSWORD},
    )
    assert response.status_code == 200
    isolated_db.close()
    stored = isolated_db.get(CustomUser, user_id)
    assert stored is not None
    assert stored.password == before


# --------------------------------------------------------------------------- #
# SSR 로그인 재해시
# --------------------------------------------------------------------------- #


def test_ssr_login_rehashes_low_iteration_hash(client, isolated_db, monkeypatch):
    monkeypatch.setattr(security, "make_password", _REAL_MAKE_PASSWORD)
    user = _seed_user(isolated_db, "rehash_ssr_user", _encode(_RAW_PASSWORD, 1000))
    user_id = user.id

    form = csrf_form(
        client,
        "/accounts/login/",
        {"username": "rehash_ssr_user", "password": _RAW_PASSWORD},
    )
    response = client.post("/accounts/login/", data=form, follow_redirects=False)
    assert response.status_code == 303

    # SSR 로그인은 별도 스레드 세션에서 갱신하므로 이 세션의 사본을 버리고 다시 읽는다.
    isolated_db.close()
    stored = isolated_db.get(CustomUser, user_id)
    assert stored is not None
    assert _stored_iterations(stored.password) == security.DEFAULT_ITERATIONS
    assert security.needs_rehash(stored.password) is False


# --------------------------------------------------------------------------- #
# 비밀번호 최대 길이 4096
# --------------------------------------------------------------------------- #


def test_rest_login_rejects_overlong_password_before_hashing(client, isolated_db, monkeypatch):
    calls: list[str] = []

    def spy(raw_password: str, encoded: str) -> bool:
        calls.append(encoded)
        return True

    monkeypatch.setattr(accounts, "check_password", spy)
    response = client.post(
        "/api/v1/accounts/login",
        json={"username": "overlong_user", "password": "a" * (security.PASSWORD_MAX_LENGTH + 1)},
    )
    assert response.status_code == 422
    assert calls == []


def test_rest_signup_rejects_overlong_password_before_hashing(client, isolated_db, monkeypatch):
    calls: list[str] = []

    def spy(raw_password: str, salt: str | None = None, iterations: int = 1) -> str:
        calls.append(raw_password)
        return "pbkdf2_sha256$1$salt$hash"

    monkeypatch.setattr(accounts, "make_password", spy)
    overlong = "a" * (security.PASSWORD_MAX_LENGTH + 1)
    response = client.post(
        "/api/v1/accounts/signup",
        json={
            "username": "overlong_signup_user",
            "password1": overlong,
            "password2": overlong,
            "nickname": "긴비번",
            "email": "overlong@example.com",
            "birth_date": "1990-01-01",
            "gender": "M",
            "agree_terms": True,
            "agree_privacy": True,
        },
    )
    assert response.status_code == 422
    assert calls == []


def test_ssr_login_rejects_overlong_password_before_hashing(client, isolated_db, monkeypatch):
    import src.app.api.ui as ui

    calls: list[str] = []

    def spy(raw_password: str, encoded: str) -> bool:
        calls.append(encoded)
        return True

    monkeypatch.setattr(ui, "check_password", spy)
    form = csrf_form(
        client,
        "/accounts/login/",
        {"username": "overlong_ssr_user", "password": "a" * (security.PASSWORD_MAX_LENGTH + 1)},
    )
    response = client.post("/accounts/login/", data=form, follow_redirects=False)
    assert response.status_code == 422
    assert calls == []


def test_ssr_signup_rejects_overlong_password_before_hashing(client, isolated_db, monkeypatch):
    import src.app.api.ui as ui

    called: list[object] = []

    def spy(*args, **kwargs):
        called.append(args)

    monkeypatch.setattr(ui, "_register_user_sync", spy)
    overlong = "a" * (security.PASSWORD_MAX_LENGTH + 1)
    form = csrf_form(
        client,
        "/accounts/signup/",
        {
            "username": "overlong_ssr_signup",
            "password1": overlong,
            "password2": overlong,
            "nickname": "긴비번",
            "email": "overlong_ssr@example.com",
            "birth_date": "1990-01-01",
            "gender": "M",
            "agree_terms": "on",
            "agree_privacy": "on",
        },
    )
    response = client.post("/accounts/signup/", data=form, follow_redirects=False)
    assert response.status_code == 422
    assert called == []
