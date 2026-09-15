"""
tests/test_rate_limit_fail_closed.py

Redis 미가용(장애) 시 요청 제한 동작 검증 테스트:
1. 로그인 API (POST /api/v1/accounts/login) -> fail-closed (503)
2. 로그인 SSR (POST /accounts/login/) -> fail-closed (503 및 폼 재렌더링)
3. 회원가입 API (POST /api/v1/accounts/signup) -> fail-closed (503)
4. 회원가입 SSR (POST /accounts/signup/) -> fail-closed (503 및 폼 재렌더링)
5. 익명 챗봇 요청 제한 -> fail-open (통과, 503 차단 없음)
6. 익명 예측 요청 제한 -> fail-open (통과, 503 차단 없음)
"""

from __future__ import annotations

from unittest.mock import MagicMock

from fastapi.testclient import TestClient

from src.app.core.security import (
    AUTH_SERVICE_UNAVAILABLE_DETAIL,
    AnonymousAPIRateLimiter,
    anonymous_api_rate_limiter,
    login_rate_limiter,
    signup_rate_limiter,
)
from tests.test_csrf import csrf_form


def test_login_api_fail_closed_when_redis_unavailable(client: TestClient, monkeypatch):
    """Redis 미가용 시 로그인 API 요청은 503 으로 차단(fail-closed)되어야 합니다."""
    monkeypatch.setattr(login_rate_limiter._conn, "client", lambda: None)

    res = client.post(
        "/api/v1/accounts/login",
        json={"username": "any_user", "password": "AnyPassword123!"},
    )
    assert res.status_code == 503
    assert res.json()["detail"] == AUTH_SERVICE_UNAVAILABLE_DETAIL


def test_login_ssr_fail_closed_when_redis_unavailable(client: TestClient, monkeypatch):
    """Redis 미가용 시 SSR 로그인 제출은 503 과 함께 폼 오류 문구로 재렌더링되어야 합니다."""
    monkeypatch.setattr(login_rate_limiter._conn, "client", lambda: None)

    form_data = {"username": "any_ssr_user", "password": "AnyPassword123!"}
    res = client.post(
        "/accounts/login/",
        data=csrf_form(client, "/accounts/login/", form_data),
        follow_redirects=False,
    )
    assert res.status_code == 503
    # accounts/login.html 은 form.errors 발생 시 오류 박스를 렌더링함
    assert "아이디 또는 비밀번호가 올바르지 않습니다." in res.text


def test_signup_api_fail_closed_when_redis_unavailable(client: TestClient, monkeypatch):
    """Redis 미가용 시 회원가입 API 요청은 503 으로 차단(fail-closed)되어야 합니다."""
    monkeypatch.setattr(signup_rate_limiter._conn, "client", lambda: None)

    payload = {
        "username": "failclosed_user",
        "password1": "StrongPass1234!",
        "password2": "StrongPass1234!",
        "nickname": "페일클로즈",
        "email": "failclosed@example.com",
        "birth_date": "1995-05-05",
        "gender": "M",
        "agree_terms": True,
        "agree_privacy": True,
    }
    res = client.post("/api/v1/accounts/signup", json=payload)
    assert res.status_code == 503
    assert res.json()["detail"] == AUTH_SERVICE_UNAVAILABLE_DETAIL


def test_signup_ssr_fail_closed_when_redis_unavailable(client: TestClient, monkeypatch):
    """Redis 미가용 시 SSR 회원가입 제출은 503 과 함께 폼 오류 문구로 재렌더링되어야 합니다."""
    monkeypatch.setattr(signup_rate_limiter._conn, "client", lambda: None)

    form_data = {
        "username": "failclosed_ssr_user",
        "password1": "StrongPass1234!",
        "password2": "StrongPass1234!",
        "nickname": "페일클로즈SSR",
        "email": "failclosed_ssr@example.com",
        "birth_date": "1995-05-05",
        "gender": "F",
        "agree_terms": "on",
        "agree_privacy": "on",
    }
    res = client.post(
        "/accounts/signup/",
        data=csrf_form(client, "/accounts/signup/", form_data),
        follow_redirects=False,
    )
    assert res.status_code == 503
    assert AUTH_SERVICE_UNAVAILABLE_DETAIL in res.text


def test_anonymous_chatbot_passes_rate_limit_when_redis_unavailable(monkeypatch):
    """Redis 미가용 시 익명 챗봇 API 요청 제한은 기존처럼 통과(fail-open)해야 합니다."""
    # client is None 일 때
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: None)

    # 요청 제한 검사와 기록 모두 예외 없이 통과해야 함
    anonymous_api_rate_limiter.check_rate_limit("203.0.113.10")
    anonymous_api_rate_limiter.record_request("203.0.113.10")

    # Redis 조회/기록 중 예외 발생 시에도 정상 통과
    failing_client = MagicMock()
    failing_client.get.side_effect = RuntimeError("Redis error")
    failing_client.pipeline.side_effect = RuntimeError("Redis error")
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: failing_client)

    anonymous_api_rate_limiter.check_rate_limit("203.0.113.10")
    anonymous_api_rate_limiter.record_request("203.0.113.10")


def test_anonymous_prediction_passes_rate_limit_when_redis_unavailable(monkeypatch):
    """Redis 미가용 시 익명 예측 요청 제한은 기존처럼 통과(fail-open)해야 합니다."""
    mock_conn = MagicMock()
    mock_conn.client.return_value = None
    limiter = AnonymousAPIRateLimiter(connection=mock_conn)

    # client is None 상태에서 check 와 record 모두 예외 없이 통과
    limiter.check_rate_limit("203.0.113.20")
    limiter.record_request("203.0.113.20")

    # 예외 발생 클라이언트 상태에서도 정상 통과
    failing_client = MagicMock()
    failing_client.get.side_effect = RuntimeError("Redis connection broken")
    failing_client.pipeline.side_effect = RuntimeError("Redis connection broken")
    mock_conn.client.return_value = failing_client

    limiter.check_rate_limit("203.0.113.20")
    limiter.record_request("203.0.113.20")
