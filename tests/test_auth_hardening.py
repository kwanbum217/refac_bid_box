"""
tests/test_auth_hardening.py

인증 경계 보강 검증 테스트:
 1. 비활성 계정의 선택적 인증(get_current_user) 및 필수 인증(require_current_user) 차단 검증
 2. 로그인 시도 제한 (IP 축 및 계정 축) 임계 초과 시 429 차단, 시간 비노출, 성공 시 리셋
 3. Redis 장애 시 로그인 시도 제한 fail-open (로그인 차단 방지) 검증
 4. 시도 제한 및 본문 크기 상한 설정(settings) 동적 반영 검증
 5. 요청 본문 크기 상한 초과 시 413 거부 및 SSE 스트리밍 응답 정상 동작 검증
 6. GET /accounts/logout/ 제거 (405 Method Not Allowed) 및 POST 로그아웃 정상 동작 검증
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from src.app.api.v1.accounts import SignUpRequest, get_current_user, register_user
from src.app.core.config import settings
from src.app.core.security import (
    SESSION_COOKIE_NAME,
    create_session,
    login_rate_limiter,
    resolve_client_ip,
)
from src.app.main import app, create_app
from src.app.models.accounts import CustomUser
from tests.test_csrf import csrf_form

VALID_USER_DATA = {
    "username": "auth_hard_user",
    "password1": "StrongPass1234!",
    "password2": "StrongPass1234!",
    "nickname": "보강테스터",
    "email": "auth_hard@example.com",
    "birth_date": "1995-03-15",
    "gender": "M",
    "agree_terms": True,
    "agree_privacy": True,
}


def _create_user(db, username: str = "auth_hard_user", is_active: bool = True) -> CustomUser:
    """테스트용 사용자 생성 헬퍼."""
    payload = SignUpRequest.model_validate(
        {**VALID_USER_DATA, "username": username, "email": f"{username}@example.com"}
    )
    mock_response = MagicMock()
    register_user(payload, mock_response, db)
    user = db.execute(select(CustomUser).where(CustomUser.username == username)).scalar_one()
    if not is_active:
        user.is_active = 0
        db.commit()
        db.refresh(user)
    return user


# ===========================================================================
# 1. 비활성 계정 처리 검증 (선택적 인증 및 필수 인증)
# ===========================================================================


def test_inactive_account_session_treated_as_unauthenticated_in_optional_auth(isolated_db):
    """비활성 계정의 세션 쿠키로는 get_current_user 에서 None(미인증)으로 해석된다."""
    user = _create_user(isolated_db, username="inactive_user_1", is_active=False)
    session_token = create_session(user.id, user.username)

    # get_current_user 직접 호출 검증
    resolved_user = get_current_user(db=isolated_db, bidbox_session=session_token)
    assert resolved_user is None


def test_inactive_account_session_rejected_in_required_auth(client, isolated_db):
    """비활성 계정의 세션 쿠키로 require_current_user 엔드포인트 접근 시 401 을 반환한다."""
    user = _create_user(isolated_db, username="inactive_user_2", is_active=False)
    session_token = create_session(user.id, user.username)

    client.cookies.set(SESSION_COOKIE_NAME, session_token)
    response = client.get("/api/v1/accounts/me")
    assert response.status_code == 401
    assert "로그인이 필요합니다" in response.json()["detail"]


def test_inactive_user_cannot_login_rest(client, isolated_db):
    """비활성 계정으로 REST 로그인 시도 시 403 Forbidden 을 반환한다."""
    _create_user(isolated_db, username="inactive_user_3", is_active=False)
    response = client.post(
        "/api/v1/accounts/login",
        json={"username": "inactive_user_3", "password": "StrongPass1234!"},
    )
    assert response.status_code == 403
    assert "비활성화된 계정" in response.json()["detail"]


def test_inactive_user_cannot_login_ssr(client, isolated_db):
    """비활성 계정으로 SSR 로그인 시도 시 403 상태 코드를 반환한다."""
    _create_user(isolated_db, username="inactive_user_4", is_active=False)
    response = client.post(
        "/accounts/login/",
        data={"username": "inactive_user_4", "password": "StrongPass1234!"},
        follow_redirects=False,
    )
    assert response.status_code == 403


# ===========================================================================
# 2. 로그인 시도 제한 (IP 축 및 계정 축) 검증
# ===========================================================================


class MockRedisStore:
    """테스트용 인메모리 Redis 모의 객체."""

    def __init__(self):
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def set(self, key: str, value: str, ex: int | None = None) -> None:
        self.store[key] = str(value)
        if ex:
            self.ttls[key] = ex

    def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.ttls.pop(key, None)

    def pipeline(self):
        class MockPipeline:
            def __init__(self, outer):
                self.outer = outer
                self.ops = []

            def incr(self, key):
                self.ops.append(("incr", key))
                return self

            def expire(self, key, ttl):
                self.ops.append(("expire", key, ttl))
                return self

            def execute(self):
                for op in self.ops:
                    if op[0] == "incr":
                        key = op[1]
                        current = int(self.outer.store.get(key, "0"))
                        self.outer.store[key] = str(current + 1)
                    elif op[0] == "expire":
                        key, ttl = op[1], op[2]
                        self.outer.ttls[key] = ttl
                return True

        return MockPipeline(self)


@pytest.fixture
def mock_redis_for_rate_limit(monkeypatch):
    """LoginRateLimiter 가 테스트용 모의 Redis 를 사용하도록 패치."""
    fake_redis = MockRedisStore()
    monkeypatch.setattr(login_rate_limiter._conn, "client", lambda: fake_redis)
    return fake_redis


def test_login_rate_limit_ip_axis(client, isolated_db, mock_redis_for_rate_limit, monkeypatch):
    """IP 축 로그인 시도 제한: 한 IP 에서 임계치 초과 실패 시 429 로 차단되며 남은 시간을 노출하지 않는다."""
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_IP_MAX_ATTEMPTS", 3)
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_ACCOUNT_MAX_ATTEMPTS", 10)

    # 3회 실패 시도
    for i in range(3):
        res = client.post(
            "/api/v1/accounts/login",
            json={"username": f"random_user_{i}", "password": "WrongPassword!"},
        )
        assert res.status_code == 401

    # 4번째 시도 -> 429 차단
    res4 = client.post(
        "/api/v1/accounts/login",
        json={"username": "another_user", "password": "WrongPassword!"},
    )
    assert res4.status_code == 429
    detail = res4.json()["detail"]
    assert "너무 많은 로그인 시도가 발생했습니다" in detail
    # 남은 시간(초, 분 등)이 노출되지 않는지 확인
    assert "초" not in detail
    assert "분" not in detail


def test_login_rate_limit_account_axis(client, isolated_db, mock_redis_for_rate_limit, monkeypatch):
    """계정 축 로그인 시도 제한: 동일 계정에 대해 임계치 초과 실패 시 429 로 차단된다."""
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_IP_MAX_ATTEMPTS", 10)
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_ACCOUNT_MAX_ATTEMPTS", 3)
    _create_user(isolated_db, username="target_victim")

    for _ in range(3):
        res = client.post(
            "/api/v1/accounts/login",
            json={"username": "target_victim", "password": "WrongPassword!"},
        )
        assert res.status_code == 401

    # 4번째 시도 -> 429 차단
    res4 = client.post(
        "/api/v1/accounts/login",
        json={"username": "target_victim", "password": "StrongPass1234!"},
    )
    assert res4.status_code == 429
    assert "너무 많은 로그인 시도가 발생했습니다" in res4.json()["detail"]


def test_login_rate_limit_resets_on_success(
    client, isolated_db, mock_redis_for_rate_limit, monkeypatch
):
    """로그인 성공 시 계정의 실패 카운터가 리셋된다."""
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_IP_MAX_ATTEMPTS", 10)
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_ACCOUNT_MAX_ATTEMPTS", 3)
    _create_user(isolated_db, username="success_user")

    # 2회 실패
    for _ in range(2):
        res = client.post(
            "/api/v1/accounts/login",
            json={"username": "success_user", "password": "WrongPassword!"},
        )
        assert res.status_code == 401

    # 1회 성공 -> 카운터 리셋
    res_ok = client.post(
        "/api/v1/accounts/login",
        json={"username": "success_user", "password": "StrongPass1234!"},
    )
    assert res_ok.status_code == 200

    # 이후 다시 2회 실패해도 아직 429가 발생하지 않음
    for _ in range(2):
        res = client.post(
            "/api/v1/accounts/login",
            json={"username": "success_user", "password": "WrongPassword!"},
        )
        assert res.status_code == 401


def test_login_rate_limit_fail_open_when_redis_unavailable(client, isolated_db, monkeypatch):
    """Redis 가 다운/미가용 상태일 때 로그인이 차단되지 않고 정상 검증으로 통과(fail-open)한다."""
    # Redis client() 가 None 을 반환하도록 패치
    monkeypatch.setattr(login_rate_limiter._conn, "client", lambda: None)
    _create_user(isolated_db, username="redis_down_user")

    # 잘못된 비밀번호 -> 401
    res_wrong = client.post(
        "/api/v1/accounts/login",
        json={"username": "redis_down_user", "password": "WrongPassword!"},
    )
    assert res_wrong.status_code == 401

    # 올바른 비밀번호 -> 200 성공 (Redis 다운이어도 로그인이 막히지 않음)
    res_ok = client.post(
        "/api/v1/accounts/login",
        json={"username": "redis_down_user", "password": "StrongPass1234!"},
    )
    assert res_ok.status_code == 200


def test_ssr_login_rate_limit(client, isolated_db, mock_redis_for_rate_limit, monkeypatch):
    """SSR 로그인 경로에서도 시도 제한이 동일하게 동작한다."""
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_IP_MAX_ATTEMPTS", 2)
    monkeypatch.setattr(settings, "AUTH_RATE_LIMIT_ACCOUNT_MAX_ATTEMPTS", 10)

    for i in range(2):
        res = client.post(
            "/accounts/login/",
            data=csrf_form(
                client,
                "/accounts/login/",
                {"username": f"ssr_test_{i}", "password": "WrongPassword!"},
            ),
            follow_redirects=False,
        )
        assert res.status_code == 401

    res_blocked = client.post(
        "/accounts/login/",
        data=csrf_form(
            client, "/accounts/login/", {"username": "ssr_test_block", "password": "WrongPassword!"}
        ),
        follow_redirects=False,
    )
    assert res_blocked.status_code == 429


# ===========================================================================
# 3. 요청 본문 크기 상한 미들웨어 검증
# ===========================================================================


def test_request_body_size_content_length_exceeded_returns_413(isolated_db, monkeypatch):
    """Content-Length 헤더가 MAX_REQUEST_BODY_SIZE 상한을 초과하면 413 으로 즉시 거부한다."""
    custom_settings = settings.model_copy()
    custom_settings.MAX_REQUEST_BODY_SIZE = 100
    custom_app = create_app(custom_settings)
    custom_client = TestClient(custom_app)

    # 100바이트 초과하는 150바이트 요청
    large_payload = {"dummy": "x" * 150}
    response = custom_client.post("/api/v1/accounts/signup", json=large_payload)
    assert response.status_code == 413
    assert "요청 본문 크기가 제한을 초과했습니다" in response.json()["detail"]


def test_request_body_size_within_limit_passes_middleware(client):
    """MAX_REQUEST_BODY_SIZE 상한 이내의 요청은 미들웨어를 정상 통과한다."""
    normal_payload = {
        **VALID_USER_DATA,
        "username": "within_limit_user",
        "email": "within@example.com",
    }
    response = client.post("/api/v1/accounts/signup", json=normal_payload)
    assert response.status_code == 200


def test_sse_streaming_not_affected_by_body_middleware(client):
    """SSE 스트리밍 응답 경로가 본문 크기 미들웨어에 의해 방해받지 않고 정상 동작한다."""
    payload = {"message": "테스트 공고 질의"}
    response = client.post("/api/v1/chatbot/chat/stream", json=payload)
    assert response.status_code == 200
    assert "text/event-stream" in response.headers.get("content-type", "")


# ===========================================================================
# 4. 로그아웃 하드닝 (GET 제거 및 POST 전용) 검증
# ===========================================================================


def test_get_logout_returns_405_method_not_allowed(client):
    """GET /accounts/logout/ 요청은 405 Method Not Allowed 로 거부된다."""
    response = client.get("/accounts/logout/", follow_redirects=False)
    assert response.status_code == 405


def test_post_logout_succeeds_and_deletes_session_cookie(isolated_db):
    """POST /accounts/logout/ 요청은 세션을 정상 파기하고 로그인 화면으로 리다이렉트(303)한다."""
    user = _create_user(isolated_db, username="logout_test_user")
    token = create_session(user.id, user.username)

    auth_client = TestClient(app, cookies={SESSION_COOKIE_NAME: token})
    response = auth_client.post(
        "/accounts/logout/", data=csrf_form(auth_client, "/chatbot/", {}), follow_redirects=False
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/login/"
    # 쿠키 삭제 지시 확인
    cookie_header = response.headers.get("set-cookie", "").lower()
    assert "max-age=0" in cookie_header or SESSION_COOKIE_NAME not in auth_client.cookies


def test_api_post_logout_succeeds_and_deletes_session_cookie(isolated_db):
    """POST /api/v1/accounts/logout 요청은 세션을 정상 파기하고 200 성공을 반환한다."""
    user = _create_user(isolated_db, username="api_logout_user")
    token = create_session(user.id, user.username)

    auth_client = TestClient(app, cookies={SESSION_COOKIE_NAME: token})
    response = auth_client.post("/api/v1/accounts/logout")
    assert response.status_code == 200
    assert response.json() == {"status": "success"}


class TestResolveClientIpTrustedProxy:
    """신뢰 프록시 기반 클라이언트 IP 해석.

    코디네이터가 추가한 구간입니다. IP 축 시도 제한이 리버스 프록시 뒤에서
    전체 사용자 잠금으로 바뀌는 문제와, 헤더를 무검증 신뢰할 때 생기는
    제한 우회 및 타인 잠금 문제를 함께 막습니다.
    """

    def test_no_trusted_proxy_ignores_forwarded_header(self, monkeypatch):
        """신뢰 목록이 비면 헤더를 일절 믿지 않습니다. 위조로 제한을 우회할 수 없습니다."""
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "", raising=False)
        assert resolve_client_ip("203.0.113.9", "1.2.3.4") == "203.0.113.9"

    def test_untrusted_peer_forged_header_is_ignored(self, monkeypatch):
        """신뢰 목록이 있어도 피어가 그 목록 밖이면 헤더를 무시합니다."""
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8", raising=False)
        assert resolve_client_ip("203.0.113.9", "1.2.3.4") == "203.0.113.9"

    def test_trusted_peer_uses_forwarded_client(self, monkeypatch):
        """신뢰 프록시 뒤에서는 원 클라이언트 주소를 씁니다. 전체 잠금이 생기지 않습니다."""
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8", raising=False)
        assert resolve_client_ip("10.1.2.3", "198.51.100.7") == "198.51.100.7"

    def test_multi_hop_strips_trusted_proxies_from_right(self, monkeypatch):
        """오른쪽부터 신뢰 프록시를 걷어내고 처음 만나는 비신뢰 주소를 씁니다."""
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8", raising=False)
        assert resolve_client_ip("10.1.1.1", "198.51.100.7, 10.9.9.9, 10.8.8.8") == "198.51.100.7"

    def test_spoofed_leading_hop_does_not_win(self, monkeypatch):
        """공격자가 왼쪽에 값을 끼워 넣어도 실제 진입 주소가 선택됩니다."""
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8", raising=False)
        assert resolve_client_ip("10.1.1.1", "9.9.9.9, 203.0.113.5, 10.0.0.2") == "203.0.113.5"

    def test_all_hops_trusted_falls_back_to_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8", raising=False)
        assert resolve_client_ip("10.1.1.1", "10.2.2.2, 10.3.3.3") == "10.1.1.1"

    def test_malformed_hop_is_skipped(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8", raising=False)
        assert resolve_client_ip("10.1.1.1", "not-an-ip, 198.51.100.7, 10.0.0.2") == "198.51.100.7"

    def test_empty_header_falls_back_to_peer(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8", raising=False)
        assert resolve_client_ip("10.1.1.1", None) == "10.1.1.1"

    def test_missing_peer_defaults_safely(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "", raising=False)
        assert resolve_client_ip(None, None) == "127.0.0.1"

    def test_invalid_trusted_entry_is_ignored_not_fatal(self, monkeypatch):
        """설정 오타가 인증 전체를 죽이지 않고 그 항목만 무시됩니다."""
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "not-a-cidr, 10.0.0.0/8", raising=False)
        assert resolve_client_ip("10.1.1.1", "198.51.100.7") == "198.51.100.7"

    def test_ipv6_trusted_proxy(self, monkeypatch):
        monkeypatch.setattr(settings, "TRUSTED_PROXY_IPS", "2001:db8::/32", raising=False)
        assert resolve_client_ip("2001:db8::1", "198.51.100.7") == "198.51.100.7"
