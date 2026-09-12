"""
tests/test_security_coverage.py

src/app/core/security.py 모듈의 인증, CSRF, 세션, 레이트리밋, 프록시 IP 파싱 등
미커버 구간과 예외/실패 경로를 엄밀하게 검증하는 테스트.
"""

from __future__ import annotations

import json
import time
from unittest.mock import MagicMock

import pytest
from fastapi import HTTPException

import src.app.core.security as sec
from src.app.core.security import (
    CSRF_MAX_AGE,
    AnonymousAPIRateLimiter,
    LoginRateLimiter,
    SessionStore,
    SessionStoreUnavailable,
    _is_trusted_proxy,
    _parse_trusted_proxies,
    check_password,
    create_session,
    csrf_tokens_match,
    destroy_session,
    enforce_anonymous_api_quota,
    make_csrf_token,
    read_session,
    resolve_client_ip,
)

# ==============================================================================
# 1. CSRF 토큰 발급 및 검증 (make_csrf_token, csrf_tokens_match)
# ==============================================================================


def test_make_csrf_token_format_and_verification():
    """정상 발급된 CSRF 토큰은 value:timestamp:signature 형태이며 자체 검증을 통과해야 한다."""
    token = make_csrf_token()
    parts = token.rsplit(":", 2)
    assert len(parts) == 3
    assert int(parts[1]) > 0
    assert len(parts[2]) > 0
    assert csrf_tokens_match(token, token) is True


def test_csrf_tokens_match_missing_or_mismatch():
    """토큰 누락 또는 쿠키/헤더 토큰 불일치 시 False 를 반환해야 한다."""
    token = make_csrf_token()
    assert csrf_tokens_match(None, token) is False
    assert csrf_tokens_match(token, None) is False
    assert csrf_tokens_match("", token) is False
    assert csrf_tokens_match(token, "") is False
    assert csrf_tokens_match(token, "different_token") is False


def test_csrf_tokens_match_malformed_token():
    """형식이 올바르지 않은 토큰(콜론 부족, 타임스탬프 오류)은 False 를 반환해야 한다."""
    assert csrf_tokens_match("no_colons", "no_colons") is False
    assert csrf_tokens_match("one:colon", "one:colon") is False
    assert csrf_tokens_match("val:not_an_int:sig", "val:not_an_int:sig") is False


def test_csrf_tokens_match_tampered_signature():
    """서명이 위조된 토큰은 불일치로 판정되어 False 를 반환해야 한다."""
    valid_token = make_csrf_token()
    val, ts, _ = valid_token.rsplit(":", 2)
    forged_token = f"{val}:{ts}:forgedsignature123"
    assert csrf_tokens_match(forged_token, forged_token) is False


def test_csrf_tokens_match_expired():
    """유효 기간(CSRF_MAX_AGE)이 지난 토큰은 서명이 맞더라도 False 를 반환해야 한다."""
    val = "somevalue"
    old_ts = str(int(time.time()) - CSRF_MAX_AGE - 100)
    payload = f"{val}:{old_ts}"
    import base64
    import hashlib
    import hmac

    from src.app.core.config import settings

    digest = hmac.new(
        f"{settings.SECRET_KEY}:{sec.CSRF_SALT}".encode(),
        payload.encode(),
        hashlib.sha256,
    ).digest()
    sig = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    expired_token = f"{payload}:{sig}"

    assert csrf_tokens_match(expired_token, expired_token) is False


# ==============================================================================
# 2. 비밀번호 생성 및 검증 (make_password, check_password)
# ==============================================================================


# conftest 의 _fast_password autouse fixture 실행 전 원본 함수 참조 보존
_ORIGINAL_MAKE_PASSWORD = sec.make_password


def test_make_and_check_password_success():
    """임의 비밀번호에 대해 make_password 로 생성한 해시가 check_password 로 정상 검증되어야 한다."""
    raw = "test_strong_password_123"
    hashed = sec.make_password(raw, salt="testsalt")
    assert "$testsalt$" in hashed
    assert check_password(raw, hashed) is True
    assert check_password("wrong_password", hashed) is False

    # 원본 make_password 구현(lines 82-85) 검증 (CI 지연 방지를 위해 낮은 반복수 사용)
    orig_hashed = _ORIGINAL_MAKE_PASSWORD(raw, salt="testsalt", iterations=5)
    assert orig_hashed.startswith("pbkdf2_sha256$5$testsalt$")
    assert _ORIGINAL_MAKE_PASSWORD(raw, salt="testsalt", iterations=5) == orig_hashed


def test_check_password_invalid_formats():
    """빈 값, 구분자 누락, 필드 개수 부족, 잘못된 알고리즘 또는 반복횟수 오류 시 False 를 반환해야 한다."""
    assert check_password("pw", "") is False
    assert check_password("pw", "nohashesatall") is False
    assert check_password("pw", "pbkdf2_sha256$only_two") is False
    assert check_password("pw", "argon2$1000$salt$hash") is False
    assert check_password("pw", "pbkdf2_sha256$not_a_number$salt$hash") is False


# ==============================================================================
# 3. 세션 저장소 (SessionStore, create_session, read_session, destroy_session)
# ==============================================================================


def test_session_store_local_fallback_allowed_switch(monkeypatch):
    """local_fallback_allowed 속성이 명시적 설정 및 settings.ENVIRONMENT 에 따라 결정되어야 한다."""
    store_explicit_true = SessionStore(allow_local_fallback=True)
    assert store_explicit_true.local_fallback_allowed is True

    store_explicit_false = SessionStore(allow_local_fallback=False)
    assert store_explicit_false.local_fallback_allowed is False

    store_env_dev = SessionStore(allow_local_fallback=None)
    monkeypatch.setattr(sec.settings, "ENVIRONMENT", "development")
    assert store_env_dev.local_fallback_allowed is True

    store_env_prod = SessionStore(allow_local_fallback=None)
    monkeypatch.setattr(sec.settings, "ENVIRONMENT", "production")
    assert store_env_prod.local_fallback_allowed is False


def test_session_store_fail_closed_when_fallback_disallowed():
    """로컬 폴백이 금지된 상태에서 Redis 연결이 없으면 SessionStoreUnavailable 예외가 발생해야 한다."""
    mock_conn = MagicMock()
    mock_conn.client.return_value = None
    store = SessionStore(connection=mock_conn, allow_local_fallback=False)

    with pytest.raises(SessionStoreUnavailable) as exc_info:
        store.create("token1", {"user_id": 1}, ttl=3600)
    assert "Redis 연결 없음" in str(exc_info.value)

    with pytest.raises(SessionStoreUnavailable) as exc_info:
        store.read("token1")
    assert "Redis 연결 없음" in str(exc_info.value)

    with pytest.raises(SessionStoreUnavailable) as exc_info:
        store.destroy("token1")
    assert "Redis 연결 없음" in str(exc_info.value)


def test_session_store_local_fallback_lifecycle():
    """로컬 폴백 허용 시 Redis 가 없을 때 프로세스 로컬 dict 에 세션이 생성, 조회, 만료, 삭제되어야 한다."""
    mock_conn = MagicMock()
    mock_conn.client.return_value = None
    store = SessionStore(connection=mock_conn, allow_local_fallback=True)

    # 1. 생성 및 정상 조회
    store.create("token_local_1", {"user_id": 42, "username": "alice"}, ttl=300)
    read_data = store.read("token_local_1")
    assert read_data == {"user_id": 42, "username": "alice"}

    # 2. 존재하지 않는 세션 조회
    assert store.read("non_existent_token") is None

    # 3. 만료된 세션 조회 시 정리 및 None 반환
    store.create("token_expired", {"user_id": 99}, ttl=-10)
    assert store.read("token_expired") is None
    assert "token_expired" not in store._local

    # 4. 삭제
    store.destroy("token_local_1")
    assert store.read("token_local_1") is None
    assert "token_local_1" not in store._local


def test_session_store_redis_exceptions_trigger_fallback():
    """Redis 연산 중 예외 발생 시 connection.invalidate 가 호출되고 로컬 폴백으로 전환되어야 한다."""
    mock_conn = MagicMock()
    mock_client = MagicMock()
    mock_client.setex.side_effect = RuntimeError("Redis write error")
    mock_client.get.side_effect = RuntimeError("Redis read error")
    mock_client.delete.side_effect = RuntimeError("Redis delete error")
    mock_conn.client.return_value = mock_client

    store = SessionStore(connection=mock_conn, allow_local_fallback=True)

    # create 시 예외 발생 -> 로컬 저장
    store.create("err_token", {"user_id": 7}, ttl=600)
    assert mock_conn.invalidate.call_count == 1
    assert "err_token" in store._local

    # read 시 예외 발생 -> 로컬 조회
    payload = store.read("err_token")
    assert payload == {"user_id": 7}
    assert mock_conn.invalidate.call_count == 2

    # destroy 시 예외 발생 -> 로컬 삭제
    store.destroy("err_token")
    assert "err_token" not in store._local
    assert mock_conn.invalidate.call_count == 3


def test_session_store_redis_corrupted_payload():
    """Redis 에서 유효하지 않은 JSON 이나 dict 가 아닌 값이 조회되면 None 을 반환해야 한다."""
    mock_conn = MagicMock()
    mock_client = MagicMock()
    mock_conn.client.return_value = mock_client
    store = SessionStore(connection=mock_conn, allow_local_fallback=False)

    # 1. 빈 데이터
    mock_client.get.return_value = None
    assert store.read("tok1") is None

    # 2. 파싱 불가능한 JSON
    mock_client.get.return_value = "{invalid_json"
    assert store.read("tok2") is None

    # 3. dict 가 아닌 JSON 값 (예: 정수, 문자열)
    mock_client.get.return_value = json.dumps("just_a_string")
    assert store.read("tok3") is None

    mock_client.get.return_value = json.dumps(12345)
    assert store.read("tok4") is None

    # 4. 올바른 dict JSON
    mock_client.get.return_value = json.dumps({"user_id": 1, "username": "admin"})
    assert store.read("tok5") == {"user_id": 1, "username": "admin"}


def test_session_convenience_functions(monkeypatch):
    """create_session, read_session, destroy_session 편의 함수의 정상 및 None 입력 처리."""
    fake_store = MagicMock()
    fake_store.create = MagicMock()
    fake_store.read = MagicMock(return_value={"user_id": 10})
    fake_store.destroy = MagicMock()

    monkeypatch.setattr(sec, "session_store", fake_store)

    token = create_session(10, "tester")
    assert isinstance(token, str)
    assert len(token) > 0
    fake_store.create.assert_called_once()

    assert read_session(None) is None
    assert read_session("") is None
    assert read_session(token) == {"user_id": 10}

    destroy_session(None)
    destroy_session("")
    fake_store.destroy.assert_not_called()

    destroy_session(token)
    fake_store.destroy.assert_called_once_with(token)


# ==============================================================================
# 4. 로그인 시도 제한기 (LoginRateLimiter)
# ==============================================================================


def test_login_rate_limiter_fail_open_when_redis_unavailable():
    """Redis 가 없거나 조회/기록 중 예외가 발생할 때 요청을 차단하지 않고 정상 통과해야 한다 (fail-open)."""
    mock_conn = MagicMock()
    mock_conn.client.return_value = None
    limiter = LoginRateLimiter(connection=mock_conn)

    # 에러 없이 통과해야 함
    limiter.check_rate_limit("1.2.3.4", "testuser")
    limiter.record_failure("1.2.3.4", "testuser")
    limiter.record_success("1.2.3.4", "testuser")

    # 예외 발생 시에도 경고 로깅 후 정상 통과
    failing_client = MagicMock()
    failing_client.get.side_effect = RuntimeError("Redis read fail")
    failing_client.pipeline.side_effect = RuntimeError("Redis pipe fail")
    failing_client.delete.side_effect = RuntimeError("Redis delete fail")
    mock_conn.client.return_value = failing_client

    limiter.check_rate_limit("1.2.3.4", "testuser")
    assert mock_conn.invalidate.call_count == 1

    limiter.record_failure("1.2.3.4", "testuser")
    assert mock_conn.invalidate.call_count == 2

    limiter.record_success("1.2.3.4", "testuser")
    assert mock_conn.invalidate.call_count == 3


def test_login_rate_limiter_ip_and_account_limits():
    """IP 또는 계정 실패 수가 임계치에 도달하면 429 HTTPException 이 발생해야 한다."""
    mock_conn = MagicMock()
    mock_client = MagicMock()
    mock_conn.client.return_value = mock_client
    limiter = LoginRateLimiter(connection=mock_conn)

    # 1. 미만일 때 통과
    mock_client.get.side_effect = lambda key: "2"
    limiter.check_rate_limit("1.2.3.4", "normal_user")

    # 2. IP 초과 시 429
    def get_ip_blocked(key):
        if "ip:1.2.3.4" in key:
            return str(limiter.ip_max_attempts)
        return "0"

    mock_client.get.side_effect = get_ip_blocked
    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit("1.2.3.4", "user1")
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == sec.RATE_LIMIT_EXCEEDED_DETAIL

    # 3. 계정 초과 시 429
    def get_acc_blocked(key):
        if "account:blocked_user" in key:
            return str(limiter.account_max_attempts)
        return "0"

    mock_client.get.side_effect = get_acc_blocked
    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit("10.0.0.1", "blocked_user")
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == sec.RATE_LIMIT_EXCEEDED_DETAIL


def test_login_rate_limiter_record_failure_and_success_pipeline():
    """record_failure 는 IP/계정 키를 pipeline 으로 incr/expire 하고, record_success 는 delete 한다."""
    mock_conn = MagicMock()
    mock_client = MagicMock()
    mock_pipe = MagicMock()
    mock_client.pipeline.return_value = mock_pipe
    mock_conn.client.return_value = mock_client
    limiter = LoginRateLimiter(connection=mock_conn)

    limiter.record_failure("192.168.1.1", "Alice")
    assert mock_pipe.incr.call_count == 2
    assert mock_pipe.expire.call_count == 2
    mock_pipe.execute.assert_called_once()

    limiter.record_success("192.168.1.1", "Alice")
    mock_client.delete.assert_called_once_with(f"{sec.RATE_LIMIT_ACCOUNT_PREFIX}alice")


# ==============================================================================
# 5. 익명 API 요청 제한기 (AnonymousAPIRateLimiter, enforce_anonymous_api_quota)
# ==============================================================================


def test_anonymous_api_rate_limiter_checks_and_exceptions():
    """AnonymousAPIRateLimiter 의 임계치 초과(429), fail-open, 파이프라인 기록 검증."""
    mock_conn = MagicMock()
    mock_client = MagicMock()
    mock_pipe = MagicMock()
    mock_client.pipeline.return_value = mock_pipe
    mock_conn.client.return_value = mock_client
    limiter = AnonymousAPIRateLimiter(connection=mock_conn)

    # 1. IP 누락 또는 client None 시 조용히 통과
    limiter.check_rate_limit(None)
    limiter.record_request(None)
    mock_client.get.assert_not_called()

    # 2. 임계치 미만
    mock_client.get.return_value = "5"
    limiter.check_rate_limit("127.0.0.1")

    # 3. 임계치 초과 시 429
    mock_client.get.return_value = str(limiter.max_requests)
    with pytest.raises(HTTPException) as exc_info:
        limiter.check_rate_limit("127.0.0.1")
    assert exc_info.value.status_code == 429
    assert exc_info.value.detail == sec.ANONYMOUS_API_RATE_LIMIT_EXCEEDED_DETAIL

    # 4. Redis 조회 예외 시 fail-open
    mock_client.get.side_effect = RuntimeError("Redis error")
    limiter.check_rate_limit("127.0.0.1")
    assert mock_conn.invalidate.call_count == 1

    # 5. 정상 기록
    limiter.record_request("127.0.0.1")
    mock_pipe.incr.assert_called_once_with(f"{sec.ANONYMOUS_API_RATE_LIMIT_PREFIX}127.0.0.1")
    mock_pipe.expire.assert_called_once_with(
        f"{sec.ANONYMOUS_API_RATE_LIMIT_PREFIX}127.0.0.1", limiter.window_seconds
    )
    mock_pipe.execute.assert_called_once()

    # 6. 기록 시 Redis 예외 fail-open
    mock_client.pipeline.side_effect = RuntimeError("Pipe error")
    limiter.record_request("127.0.0.1")
    assert mock_conn.invalidate.call_count == 2


def test_enforce_anonymous_api_quota_authenticated_vs_anonymous(monkeypatch):
    """로그인 사용자는 쿼터 검사를 건너뛰고, 익명 요청만 클라이언트 IP 를 추출해 제한한다."""
    mock_limiter = MagicMock()
    monkeypatch.setattr(sec, "anonymous_api_rate_limiter", mock_limiter)

    # 1. 로그인 사용자 (user is not None)
    mock_request = MagicMock()
    enforce_anonymous_api_quota(mock_request, user={"user_id": 1})
    mock_limiter.check_rate_limit.assert_not_called()
    mock_limiter.record_request.assert_not_called()

    # 2. 익명 사용자 (user is None)
    mock_request.client.host = "203.0.113.195"
    mock_request.headers.get.return_value = None
    enforce_anonymous_api_quota(mock_request, user=None)
    mock_limiter.check_rate_limit.assert_called_once_with("203.0.113.195")
    mock_limiter.record_request.assert_called_once_with("203.0.113.195")


# ==============================================================================
# 6. 신뢰 프록시 및 클라이언트 IP 추출 (_parse_trusted_proxies, resolve_client_ip)
# ==============================================================================


def test_parse_trusted_proxies(monkeypatch):
    """TRUSTED_PROXY_IPS 설정에서 유효한 IP/CIDR만 추출하고 공백 및 잘못된 항목은 건너뛴다."""
    monkeypatch.setattr(
        sec.settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8, 192.168.1.1, invalid_cidr, , 172.16.0.0/12"
    )
    networks = _parse_trusted_proxies()
    assert len(networks) == 3
    assert any(str(net) == "10.0.0.0/8" for net in networks)
    assert any(str(net) == "192.168.1.1/32" for net in networks)
    assert any(str(net) == "172.16.0.0/12" for net in networks)


def test_is_trusted_proxy(monkeypatch):
    """IP 가 신뢰 네트워크 범위 내에 있는지 검사하며 파싱 불가능한 주소는 False 를 반환한다."""
    monkeypatch.setattr(sec.settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8")
    networks = _parse_trusted_proxies()

    assert _is_trusted_proxy("10.1.2.3", networks) is True
    assert _is_trusted_proxy("192.168.1.1", networks) is False
    assert _is_trusted_proxy("invalid_ip", networks) is False
    assert _is_trusted_proxy("10.1.2.3", []) is False


def test_resolve_client_ip_peer_untrusted(monkeypatch):
    """피어가 신뢰 프록시가 아닌 경우 X-Forwarded-For 헤더가 있더라도 피어 주소를 그대로 사용해야 한다."""
    monkeypatch.setattr(sec.settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8")
    # 피어가 203.0.113.5 (외부 공개망 주소)
    resolved = resolve_client_ip("203.0.113.5", "198.51.100.1, 10.0.0.1")
    assert resolved == "203.0.113.5"

    # peer_ip 가 None 또는 공백인 경우 127.0.0.1 기본값
    assert resolve_client_ip(None, None) == "127.0.0.1"
    assert resolve_client_ip("  ", None) == "127.0.0.1"


def test_resolve_client_ip_trusted_proxy_hops(monkeypatch):
    """피어가 신뢰 프록시인 경우 X-Forwarded-For 의 오른쪽부터 신뢰 프록시를 걷어내고 첫 비신뢰 주소를 추출한다."""
    monkeypatch.setattr(sec.settings, "TRUSTED_PROXY_IPS", "10.0.0.0/8, 172.16.0.0/12")
    peer = "10.0.0.1"

    # 1. 클라이언트(203.0.113.10) -> 중간 프록시(172.16.0.2) -> 피어 프록시(10.0.0.1)
    forwarded = "203.0.113.10, 172.16.0.2"
    assert resolve_client_ip(peer, forwarded) == "203.0.113.10"

    # 2. 잘못된 형식의 hop 이 섞여 있는 경우 건너뛰고 이전 hop 을 해석
    forwarded_with_invalid = "203.0.113.10, invalid_hop_ip, 172.16.0.2"
    assert resolve_client_ip(peer, forwarded_with_invalid) == "203.0.113.10"

    # 3. 모든 hop 이 신뢰 프록시인 경우 피어 IP 로 회귀
    all_trusted = "10.0.0.2, 172.16.0.3"
    assert resolve_client_ip(peer, all_trusted) == peer

    # 4. X-Forwarded-For 가 비어 있는 경우 피어 IP 반환
    assert resolve_client_ip(peer, "") == peer
    assert resolve_client_ip(peer, None) == peer
