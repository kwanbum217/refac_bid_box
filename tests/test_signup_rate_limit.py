"""tests/test_signup_rate_limit.py

회원가입 요청 제한(SignupRateLimiter) 검증 테스트.
- IP 축 고정 윈도우 기반 회원가입 제한
- 한도 초과 시 API 경로(POST /api/v1/accounts/signup) 429 반환
- 한도 초과 시 SSR 경로(POST /accounts/signup/) 429 및 폼 재렌더링
- 한도 내에서는 정상 가입 처리
- Redis 미가용 시 fail-open (통과 및 경고 로깅)
- 성공/실패와 무관하게 시도마다 1회 기록
- 로그인 제한 키 및 익명 API 제한 키와의 접두사 충돌 방지
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.app.core.config import settings
from src.app.core.security import (
    ANONYMOUS_API_RATE_LIMIT_PREFIX,
    AUTH_SERVICE_UNAVAILABLE_DETAIL,
    RATE_LIMIT_ACCOUNT_PREFIX,
    RATE_LIMIT_IP_PREFIX,
    SIGNUP_RATE_LIMIT_EXCEEDED_DETAIL,
    SIGNUP_RATE_LIMIT_PREFIX,
    signup_rate_limiter,
)
from tests.test_csrf import csrf_form


class FakeRedisPipeline:
    def __init__(self, outer: FakeRedisClient):
        self.outer = outer
        self.ops: list[tuple[str, tuple]] = []

    def incr(self, key: str) -> FakeRedisPipeline:
        self.ops.append(("incr", (key, 1)))
        return self

    def expire(self, key: str, seconds: int) -> FakeRedisPipeline:
        self.ops.append(("expire", (key, seconds)))
        return self

    def execute(self) -> list[int]:
        results = []
        for op, args in self.ops:
            if op == "incr":
                key, amount = args
                current = int(self.outer.store.get(key, "0"))
                new_val = current + amount
                self.outer.store[key] = str(new_val)
                results.append(new_val)
            elif op == "expire":
                key, ttl = args
                self.outer.ttls[key] = ttl
                results.append(1)
        self.ops.clear()
        return results


class FakeRedisClient:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                deleted += 1
            self.ttls.pop(key, None)
        return deleted

    def pipeline(self) -> FakeRedisPipeline:
        return FakeRedisPipeline(self)


@pytest.fixture
def fake_redis(monkeypatch):
    client = FakeRedisClient()
    monkeypatch.setattr(signup_rate_limiter._conn, "client", lambda: client)
    return client


def test_signup_rate_limiter_key_prefix_isolation():
    """회원가입 제한 키 접두사가 로그인 제한 및 익명 API 제한 키와 충돌하지 않아야 합니다."""
    assert SIGNUP_RATE_LIMIT_PREFIX != RATE_LIMIT_IP_PREFIX
    assert SIGNUP_RATE_LIMIT_PREFIX != RATE_LIMIT_ACCOUNT_PREFIX
    assert SIGNUP_RATE_LIMIT_PREFIX != ANONYMOUS_API_RATE_LIMIT_PREFIX
    assert not SIGNUP_RATE_LIMIT_PREFIX.startswith(RATE_LIMIT_IP_PREFIX)
    assert not RATE_LIMIT_IP_PREFIX.startswith(SIGNUP_RATE_LIMIT_PREFIX)


def test_api_signup_rate_limit_within_limit_and_exceeded(
    client: TestClient, fake_redis: FakeRedisClient, monkeypatch
):
    """API 회원가입 경로에서 한도 안에서는 정상 가입되고 초과 시 429 를 돌려주어야 합니다."""
    monkeypatch.setattr(settings, "SIGNUP_RATE_LIMIT_MAX", 2, raising=False)

    payload_base = {
        "password1": "password1234!",
        "password2": "password1234!",
        "nickname": "가입테스터",
        "birth_date": "1995-05-05",
        "gender": "M",
        "agree_terms": True,
        "agree_privacy": True,
    }

    # 1회차: 정상 가입 성공
    res1 = client.post(
        "/api/v1/accounts/signup",
        json={**payload_base, "username": "testuser_api_1", "email": "test1@example.com"},
    )
    assert res1.status_code == 200
    expected_key = f"{SIGNUP_RATE_LIMIT_PREFIX}testclient"
    assert fake_redis.store.get(expected_key) == "1"

    # 2회차: 정상 가입 성공
    res2 = client.post(
        "/api/v1/accounts/signup",
        json={**payload_base, "username": "testuser_api_2", "email": "test2@example.com"},
    )
    assert res2.status_code == 200
    assert fake_redis.store.get(expected_key) == "2"

    # 3회차: 한도(2회) 초과로 429 반환
    res3 = client.post(
        "/api/v1/accounts/signup",
        json={**payload_base, "username": "testuser_api_3", "email": "test3@example.com"},
    )
    assert res3.status_code == 429
    assert res3.json()["detail"] == SIGNUP_RATE_LIMIT_EXCEEDED_DETAIL


def test_ssr_signup_rate_limit_within_limit_and_exceeded(
    client: TestClient, fake_redis: FakeRedisClient, monkeypatch
):
    """SSR 회원가입 경로에서 한도 초과 시 429 와 함께 오류 문구가 렌더링되어야 합니다."""
    monkeypatch.setattr(settings, "SIGNUP_RATE_LIMIT_MAX", 1, raising=False)

    form_data = {
        "username": "testuser_ssr_1",
        "password1": "password1234!",
        "password2": "password1234!",
        "nickname": "SSR테스터",
        "email": "ssr1@example.com",
        "birth_date": "1992-02-02",
        "gender": "F",
        "agree_terms": "on",
        "agree_privacy": "on",
    }

    # 1회차: 정상 가입 성공 (303 리다이렉트)
    res1 = client.post(
        "/accounts/signup/",
        data=csrf_form(client, "/accounts/signup/", form_data),
        follow_redirects=False,
    )
    assert res1.status_code == 303
    expected_key = f"{SIGNUP_RATE_LIMIT_PREFIX}testclient"
    assert fake_redis.store.get(expected_key) == "1"

    # 로그인 세션 쿠키를 비워 다음 요청에서 인증 리다이렉트가 일어나지 않도록 함
    client.cookies.clear()

    # 2회차: 한도(1회) 초과로 429 및 폼 재렌더링
    form_data_2 = {**form_data, "username": "testuser_ssr_2", "email": "ssr2@example.com"}
    res2 = client.post(
        "/accounts/signup/",
        data=csrf_form(client, "/accounts/signup/", form_data_2),
        follow_redirects=False,
    )
    assert res2.status_code == 429
    assert SIGNUP_RATE_LIMIT_EXCEEDED_DETAIL in res2.text


def test_signup_rate_limiter_fail_closed_when_redis_unavailable(client: TestClient, monkeypatch):
    """Redis 미가용 시 두 가입 경로 모두 503 으로 차단(fail-closed)되어야 합니다."""
    # client 가 None 인 경우
    monkeypatch.setattr(signup_rate_limiter._conn, "client", lambda: None)

    # API 경로 503 차단
    payload_api = {
        "username": "failclosed_user_api",
        "password1": "password1234!",
        "password2": "password1234!",
        "nickname": "페일클로즈",
        "email": "failclosed_api@example.com",
        "birth_date": "1990-01-01",
        "gender": "M",
        "agree_terms": True,
        "agree_privacy": True,
    }
    res_api = client.post("/api/v1/accounts/signup", json=payload_api)
    assert res_api.status_code == 503
    assert res_api.json()["detail"] == AUTH_SERVICE_UNAVAILABLE_DETAIL

    # SSR 경로 503 및 오류 문구 폼 재렌더링
    form_data_ssr = {
        "username": "failclosed_user_ssr",
        "password1": "password1234!",
        "password2": "password1234!",
        "nickname": "페일클로즈SSR",
        "email": "failclosed_ssr@example.com",
        "birth_date": "1990-01-01",
        "gender": "F",
        "agree_terms": "on",
        "agree_privacy": "on",
    }
    res_ssr = client.post(
        "/accounts/signup/",
        data=csrf_form(client, "/accounts/signup/", form_data_ssr),
        follow_redirects=False,
    )
    assert res_ssr.status_code == 503
    assert AUTH_SERVICE_UNAVAILABLE_DETAIL in res_ssr.text


def test_signup_attempt_recorded_regardless_of_success_or_failure(
    client: TestClient, fake_redis: FakeRedisClient
):
    """가입 처리 결과(실패/성공)와 무관하게 시도마다 카운터가 증가해야 합니다."""
    expected_key = f"{SIGNUP_RATE_LIMIT_PREFIX}testclient"

    # 비밀번호 불일치 실패 (400)
    bad_payload = {
        "username": "attempt_user_fail",
        "password1": "password1234!",
        "password2": "mismatch!",
        "nickname": "실패테스트",
        "email": "attempt_fail@example.com",
        "birth_date": "1990-01-01",
        "gender": "M",
        "agree_terms": True,
        "agree_privacy": True,
    }
    res = client.post("/api/v1/accounts/signup", json=bad_payload)
    assert res.status_code == 400
    assert fake_redis.store.get(expected_key) == "1"

    # 정상 성공 (200)
    good_payload = {**bad_payload, "password2": "password1234!"}
    res_ok = client.post("/api/v1/accounts/signup", json=good_payload)
    assert res_ok.status_code == 200
    assert fake_redis.store.get(expected_key) == "2"

    # 중복 아이디 실패 (409)
    res_dup = client.post("/api/v1/accounts/signup", json=good_payload)
    assert res_dup.status_code == 409
    assert fake_redis.store.get(expected_key) == "3"
