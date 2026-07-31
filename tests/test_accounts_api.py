"""
tests/test_accounts_api.py

원본 apps/accounts/tests.py SignUpFormTests 중 이식 가능한 검증을 FastAPI 환경으로 변환.
 - 회원가입 시 birth_date 가 birth_y/m/d 로 분해 저장되는지
 - 약관 동의 필수, 성별 M/F 검증, 비밀번호 일치
 - 중복 username 차단
 - 회원가입 직후 자동 로그인 (세션 쿠키 발급)
 - 로그인 / 로그아웃 / me
"""

from sqlalchemy import select

from src.app.models.accounts import CustomUser


VALID_SIGNUP = {
    "username": "testuser",
    "password1": "StrongPass123!!",
    "password2": "StrongPass123!!",
    "nickname": "테스터",
    "email": "test@example.com",
    "birth_date": "1999-05-17",
    "gender": "F",
    "agree_terms": True,
    "agree_privacy": True,
}


def _signup(client, **overrides):
    payload = {**VALID_SIGNUP, **overrides}
    return client.post("/api/v1/accounts/signup", json=payload)


def test_signup_saves_birth_date_parts_and_gender(client, isolated_db):
    response = _signup(client)
    assert response.status_code == 200, response.text

    user = isolated_db.execute(
        select(CustomUser).where(CustomUser.username == "testuser")
    ).scalar_one()
    assert user.birth_y == 1999
    assert user.birth_m == 5
    assert user.birth_d == 17
    assert user.gender == "F"
    assert user.nickname == "테스터"
    assert user.email == "test@example.com"


def test_signup_issues_session_cookie(client):
    response = _signup(client)
    assert response.status_code == 200
    assert "bidbox_session" in response.cookies


def test_signup_rejects_mismatched_passwords(client):
    response = _signup(client, password2="DifferentPass456!!")
    assert response.status_code == 400
    assert "비밀번호가 일치하지 않습니다" in response.json()["detail"]


def test_signup_rejects_duplicate_username(client):
    _signup(client)
    response = _signup(client, email="other@example.com")
    assert response.status_code == 409
    assert "이미 사용 중인 아이디" in response.json()["detail"]


def test_signup_rejects_invalid_gender(client):
    response = _signup(client, gender="X")
    assert response.status_code == 422


def test_signup_requires_terms_agreement(client):
    response = _signup(client, agree_terms=False)
    assert response.status_code == 422


def test_signup_requires_privacy_agreement(client):
    response = _signup(client, agree_privacy=False)
    assert response.status_code == 422


def test_login_succeeds_with_correct_credentials(client):
    _signup(client)
    response = client.post(
        "/api/v1/accounts/login",
        json={"username": "testuser", "password": "StrongPass123!!"},
    )
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"
    assert "bidbox_session" in response.cookies


def test_login_fails_with_wrong_password(client):
    _signup(client)
    response = client.post(
        "/api/v1/accounts/login",
        json={"username": "testuser", "password": "WrongPassword!!"},
    )
    assert response.status_code == 401


def test_login_fails_with_unknown_user(client):
    response = client.post(
        "/api/v1/accounts/login",
        json={"username": "ghost", "password": "whatever"},
    )
    assert response.status_code == 401


def test_me_requires_authentication(client):
    response = client.get("/api/v1/accounts/me")
    assert response.status_code == 401


def test_me_returns_user_after_login(client):
    _signup(client)
    client.post(
        "/api/v1/accounts/login",
        json={"username": "testuser", "password": "StrongPass123!!"},
    )
    response = client.get("/api/v1/accounts/me")
    assert response.status_code == 200
    assert response.json()["username"] == "testuser"


def test_logout_clears_session(client):
    _signup(client)
    response = client.post("/api/v1/accounts/logout")
    assert response.status_code == 200
    me_response = client.get("/api/v1/accounts/me")
    assert me_response.status_code == 401
