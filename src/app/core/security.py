"""
src/app/core/security.py

비밀번호 해시와 세션 인증.

비밀번호는 Django 의 `pbkdf2_sha256$<iterations>$<salt>$<hash>` 포맷을 그대로 사용합니다.
원본 accounts_customuser 에 저장된 기존 계정이 그대로 로그인되어야 하기 때문입니다.
표준 라이브러리만 사용하므로 신규 의존성이 없습니다.

세션 저장소는 일반 조회 캐시(src/app/core/cache.py 의 cache)와 다른 객체이며
연결도 따로 씁니다. 조회 캐시의 로컬 degrade 정책이 인증 상태로 전파되면
프로세스마다 다른 세션 집합을 보게 되어 로그인 사용자가 요청마다 임의로
로그아웃됩니다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import json
import logging
import secrets
import time
from typing import Any

from fastapi import HTTPException

from src.app.core.cache import RedisConnection
from src.app.core.config import settings

logger = logging.getLogger(__name__)

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
PASSWORD_SALT_BYTES = 11
PASSWORD_MAX_LENGTH = 4096
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
SESSION_IDLE_TIMEOUT_SECONDS = 60 * 60 * 24 * 7
SESSION_ACTIVITY_REFRESH_SECONDS = 300
SESSION_ACTIVITY_KEY = "last_activity"
SESSION_COOKIE_NAME = "bidbox_session"
SESSION_CACHE_PREFIX = "auth:session:"
# 사용자별 세대 번호. 세션을 만들 때 그 시점의 세대를 함께 저장하고, 읽을 때
# 저장된 세대가 현재보다 작으면 그 세션을 파기합니다. 세대를 1 올리면 그
# 사용자의 모든 세션이 한 번에 무효가 되며, 이것이 전체 로그아웃입니다.
# 세대 키에는 만료를 두지 않습니다(세션 절대 수명 14일보다 오래 살아야 함).
SESSION_GENERATION_PREFIX = "auth:user_epoch:"
SESSION_GENERATION_FIELD = "generation"
CSRF_COOKIE_NAME = "bidbox_csrf"
CSRF_HEADER_NAME = "X-CSRF-Token"
CSRF_FORM_FIELD = "csrf_token"
CSRF_SALT = "bidbox.csrf"
CSRF_MAX_AGE = 60 * 60 * 24


def make_csrf_token() -> str:
    """기존 자동화 토큰과 동일한 SECRET_KEY/HMAC 형식의 토큰을 발급합니다."""
    timestamp = str(int(time.time()))
    value = secrets.token_urlsafe(32)
    payload = f"{value}:{timestamp}"
    digest = hmac.new(
        f"{settings.SECRET_KEY}:{CSRF_SALT}".encode(), payload.encode(), hashlib.sha256
    ).digest()
    signature = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"{payload}:{signature}"


def csrf_tokens_match(cookie_token: str | None, request_token: str | None) -> bool:
    """서명된 이중 제출 토큰을 상수 시간으로 비교·검증합니다."""
    if not cookie_token or not request_token:
        return False
    if not hmac.compare_digest(cookie_token, request_token):
        return False
    try:
        value, timestamp, signature = cookie_token.rsplit(":", 2)
        payload = f"{value}:{timestamp}"
        expected = hmac.new(
            f"{settings.SECRET_KEY}:{CSRF_SALT}".encode(), payload.encode(), hashlib.sha256
        ).digest()
        expected_signature = base64.urlsafe_b64encode(expected).decode().rstrip("=")
        if not hmac.compare_digest(signature, expected_signature):
            return False
        return time.time() - int(timestamp) <= CSRF_MAX_AGE
    except (TypeError, ValueError):
        return False


def make_password(
    raw_password: str, salt: str | None = None, iterations: int = DEFAULT_ITERATIONS
) -> str:
    salt = salt or secrets.token_hex(PASSWORD_SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", raw_password.encode(), salt.encode(), iterations)
    encoded = base64.b64encode(digest).decode().strip()
    return f"{ALGORITHM}${iterations}${salt}${encoded}"


def needs_rehash(encoded: str) -> bool:
    """저장된 해시가 현재 정책보다 약하면 재해시가 필요하다고 알립니다.

    반복 수가 DEFAULT_ITERATIONS 보다 낮으면 True 입니다. 알고리즘이 다르거나
    형식이 깨진 값도 True 로 보지만, 그런 해시는 check_password 가 이미 거짓이므로
    로그인 성공 경로에서는 도달하지 않습니다.
    """
    if not encoded or "$" not in encoded:
        return True
    try:
        algorithm, iterations, _salt, _hash = encoded.split("$", 3)
    except ValueError:
        return True
    if algorithm != ALGORITHM:
        return True
    try:
        return int(iterations) < DEFAULT_ITERATIONS
    except (TypeError, ValueError):
        return True


def rehash_password(raw_password: str) -> str:
    """현재 정책(DEFAULT_ITERATIONS, 늘어난 salt)으로 비밀번호를 다시 해싱합니다."""
    return make_password(raw_password)


def check_password(raw_password: str, encoded: str) -> bool:
    if not encoded or "$" not in encoded:
        return False
    try:
        algorithm, iterations, salt, _hash = encoded.split("$", 3)
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False
    try:
        candidate = make_password(raw_password, salt=salt, iterations=int(iterations))
    except (TypeError, ValueError):
        return False
    return hmac.compare_digest(candidate, encoded)


class SessionStoreUnavailable(RuntimeError):
    """세션 저장소에 접근할 수 없습니다.

    세션 없음(정상적인 비로그인)과 저장소 장애를 구분하기 위한 신호입니다.
    호출부는 이 예외를 401 이 아니라 503 으로 다뤄야 합니다.
    """


class SessionStore:
    """인증 세션 전용 저장소. Redis 를 쓸 수 없으면 fail-closed 입니다.

    development 환경에서만 프로세스 로컬 저장소를 허용합니다. 로컬 저장소는
    다중 프로세스에서 세션이 어긋나므로, 내려갈 때 ERROR 로그로 드러냅니다.
    """

    def __init__(
        self,
        connection: RedisConnection | None = None,
        allow_local_fallback: bool | None = None,
    ):
        self._conn = connection or RedisConnection(label="session")
        self._allow_local_fallback = allow_local_fallback
        self._local: dict[str, tuple[float, dict[str, Any]]] = {}
        self._degraded_logged = False

    @property
    def local_fallback_allowed(self) -> bool:
        if self._allow_local_fallback is None:
            return settings.ENVIRONMENT == "development"
        return self._allow_local_fallback

    @staticmethod
    def _key(token: str) -> str:
        return f"{SESSION_CACHE_PREFIX}{token}"

    def _fallback(self, reason: str) -> dict[str, tuple[float, dict[str, Any]]]:
        if not self.local_fallback_allowed:
            logger.error("인증 세션 저장소를 사용할 수 없어 요청을 실패시킵니다: %s", reason)
            raise SessionStoreUnavailable(reason)
        if not self._degraded_logged:
            logger.error(
                "인증 세션이 프로세스 로컬 저장소로 내려갔습니다. "
                "다중 프로세스에서는 세션이 어긋납니다: %s",
                reason,
            )
            self._degraded_logged = True
        return self._local

    def create(self, token: str, payload: dict[str, Any], ttl: int) -> None:
        now = time.time()
        stamped = {**payload, SESSION_ACTIVITY_KEY: now}
        client = self._conn.client()
        if client is None:
            self._fallback("Redis 연결 없음")[token] = (now + ttl, stamped)
            return
        self._degraded_logged = False
        try:
            client.setex(self._key(token), ttl, json.dumps(stamped, ensure_ascii=False))
        except Exception as exc:
            self._conn.invalidate(exc)
            self._fallback(f"세션 저장 실패: {exc}")[token] = (now + ttl, stamped)

    def read(self, token: str) -> dict[str, Any] | None:
        client = self._conn.client()
        if client is None:
            return self._read_local(self._fallback("Redis 연결 없음"), token)
        self._degraded_logged = False
        try:
            raw = client.get(self._key(token))
        except Exception as exc:
            self._conn.invalidate(exc)
            return self._read_local(self._fallback(f"세션 조회 실패: {exc}"), token)
        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except ValueError:
            logger.warning("세션 값 역직렬화 실패")
            return None
        if not isinstance(payload, dict):
            return None
        if not self._check_activity(payload, token, client):
            return None
        return self._public_payload(payload)

    @staticmethod
    def _generation_key(user_id: int) -> str:
        return f"{SESSION_GENERATION_PREFIX}{user_id}"

    def current_generation(self, user_id: int) -> int:
        """사용자의 현재 세대 번호. 키가 없으면 0 입니다.

        기존 세션(세대 필드 없음)은 세대 0 으로 보므로, 배포 직후에는 현재
        세대도 0 이라 종전 세션이 일괄 로그아웃되지 않습니다.
        """
        client = self._conn.client()
        if client is None:
            self._fallback("Redis 연결 없음")
            return 0
        self._degraded_logged = False
        try:
            raw = client.get(self._generation_key(user_id))
        except Exception as exc:
            self._conn.invalidate(exc)
            self._fallback(f"세대 조회 실패: {exc}")
            return 0
        if raw is None:
            return 0
        try:
            return int(raw)
        except (TypeError, ValueError):
            return 0

    def bump_generation(self, user_id: int) -> int:
        """세대를 1 올리고 새 값을 돌려줍니다. 전체 로그아웃이 이 값을 씁니다.

        Redis 장애 처리는 다른 세션 연산과 같게 맞춥니다(fail-closed, 개발
        환경에서만 프로세스 로컬 대체). 유휴·절대 만료 동작은 건드리지 않습니다.
        """
        client = self._conn.client()
        if client is None:
            self._fallback("Redis 연결 없음")
            return self._discard_local_sessions(user_id)
        self._degraded_logged = False
        try:
            return int(client.incr(self._generation_key(user_id)))
        except Exception as exc:
            self._conn.invalidate(exc)
            self._fallback(f"세대 증가 실패: {exc}")
            return self._discard_local_sessions(user_id)

    def _discard_local_sessions(self, user_id: int) -> int:
        """로컬 대체 저장소에서 그 사용자의 세션을 모두 지웁니다.

        Redis 를 쓸 수 없는 개발 환경에서는 세대 키 대신 직접 삭제로 같은
        효과를 냅니다. 돌려주는 값은 세대가 아니라 삭제 결과 표시인 1 입니다.
        """
        victims = [
            key for key, (_, payload) in self._local.items() if payload.get("user_id") == user_id
        ]
        for key in victims:
            self._local.pop(key, None)
        return 1

    def _check_activity(self, payload: dict[str, Any], token: str, client: Any) -> bool:
        """유휴 만료를 검사하고, 필요하면 마지막 활동 시각을 갱신합니다.

        마지막 활동 시각이 없는 기존 세션은 생성 시각을 알 수 없으므로 지금 활동한
        것으로 보아 배포 직후 전원이 로그아웃되지 않게 합니다.
        """
        now = time.time()
        last = payload.get(SESSION_ACTIVITY_KEY)
        if not isinstance(last, (int, float)):
            return True
        if now - float(last) > SESSION_IDLE_TIMEOUT_SECONDS:
            self.destroy(token)
            return False
        if now - float(last) >= SESSION_ACTIVITY_REFRESH_SECONDS:
            payload[SESSION_ACTIVITY_KEY] = now
            self._refresh_activity(client, token, payload)
        return True

    def _refresh_activity(self, client: Any, token: str, payload: dict[str, Any]) -> None:
        """절대 만료(남은 TTL)를 유지한 채 활동 시각만 다시 씁니다.

        갱신은 쓰기 부담을 줄이려 일정 간격이 지났을 때만 부르며, 실패해도 이미
        유효성이 확인된 세션을 로그아웃시키지 않도록 삼킵니다.
        """
        key = self._key(token)
        try:
            ttl = client.ttl(key)
            if ttl is None or int(ttl) <= 0:
                return
            client.setex(key, int(ttl), json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning("세션 활동 시각 갱신 중 Redis 오류 발생: %s", exc)

    @staticmethod
    def _public_payload(payload: dict[str, Any]) -> dict[str, Any]:
        """내부 활동 시각 키를 뺀 사본을 돌려줍니다.

        세대 필드는 여기서 지우지 않습니다. `read_session` 이 저장된 세대와 현재
        세대를 대조한 뒤 최종 반환에서 제거합니다.
        """
        return {key: value for key, value in payload.items() if key != SESSION_ACTIVITY_KEY}

    def destroy(self, token: str) -> None:
        client = self._conn.client()
        if client is None:
            self._fallback("Redis 연결 없음").pop(token, None)
            return
        self._degraded_logged = False
        try:
            client.delete(self._key(token))
        except Exception as exc:
            self._conn.invalidate(exc)
            self._fallback(f"세션 삭제 실패: {exc}").pop(token, None)

    def _read_local(
        self, store: dict[str, tuple[float, dict[str, Any]]], token: str
    ) -> dict[str, Any] | None:
        entry = store.get(token)
        if entry is None:
            return None
        expires_at, payload = entry
        now = time.time()
        if expires_at < now:
            store.pop(token, None)
            return None
        last = payload.get(SESSION_ACTIVITY_KEY)
        if isinstance(last, (int, float)):
            if now - float(last) > SESSION_IDLE_TIMEOUT_SECONDS:
                store.pop(token, None)
                return None
            if now - float(last) >= SESSION_ACTIVITY_REFRESH_SECONDS:
                payload[SESSION_ACTIVITY_KEY] = now
        return self._public_payload(payload)


session_store = SessionStore()


def create_session(user_id: int, username: str) -> str:
    """세션을 만들고 그 시점의 사용자 세대를 payload 에 기록합니다.

    세대를 세션 값에 남겨 두면 전체 로그아웃 뒤 이전 세션을 읽을 때 현재
    세대와 대조해 파기할 수 있습니다. 세션 저장소 호출은 create 한 번뿐이라
    저장소 연산별 장애 처리 계약(invalidate 1회)이 그대로 유지됩니다.
    """
    token = secrets.token_urlsafe(32)
    session_store.create(
        token,
        {
            "user_id": int(user_id),
            "username": username,
            SESSION_GENERATION_FIELD: session_store.current_generation(int(user_id)),
        },
        SESSION_TTL_SECONDS,
    )
    return token


def read_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    payload = session_store.read(token)
    if payload is None:
        return None
    return _apply_generation(payload, token)


def _apply_generation(payload: dict[str, Any], token: str) -> dict[str, Any] | None:
    """저장된 세대가 현재 세대보다 작으면 세션을 파기하고 None 을 돌려줍니다.

    세대 필드가 없는 배포 이전 세션은 세대 0 으로 봅니다. 최종 반환값에서는
    세대 필드를 제거해 세션 payload 계약을 바꾸지 않습니다.
    """
    user_id = payload.get("user_id")
    stored = payload.get(SESSION_GENERATION_FIELD, 0)
    if isinstance(user_id, int) and isinstance(stored, int):
        current = session_store.current_generation(user_id)
        if isinstance(current, int) and stored < current:
            session_store.destroy(token)
            return None
    return {key: value for key, value in payload.items() if key != SESSION_GENERATION_FIELD}


def destroy_session(token: str | None) -> None:
    if token:
        session_store.destroy(token)


def invalidate_all_sessions(user_id: int) -> int:
    """그 사용자의 모든 세션(현재 세션 포함)을 무효로 만듭니다.

    Redis 에서는 세대 번호를 1 올리고, 이전 세대로 만들어진 세션은 읽을 때
    파기됩니다. Redis 를 쓸 수 없는 개발 환경에서는 그 사용자의 로컬 세션을
    직접 지웁니다. 돌려주는 값은 새 세대 번호입니다.
    """
    return session_store.bump_generation(int(user_id))


RATE_LIMIT_IP_PREFIX = "auth:ratelimit:ip:"
RATE_LIMIT_ACCOUNT_PREFIX = "auth:ratelimit:account:"
RATE_LIMIT_EXCEEDED_DETAIL = "너무 많은 로그인 시도가 발생했습니다. 잠시 후 다시 시도해 주십시오."
ANONYMOUS_API_RATE_LIMIT_PREFIX = "api:ratelimit:anonymous:"
ANONYMOUS_API_RATE_LIMIT_EXCEEDED_DETAIL = "요청이 너무 많습니다. 잠시 후 다시 시도해 주십시오."
AUTHENTICATED_API_RATE_LIMIT_PREFIX = "api:ratelimit:user:"
AUTHENTICATED_API_RATE_LIMIT_MAX_REQUESTS = 120
AUTHENTICATED_API_RATE_LIMIT_WINDOW_SECONDS = 60
AUTHENTICATED_API_RATE_LIMIT_EXCEEDED_DETAIL = "요청이 너무 많습니다. 잠시 후 다시 시도해 주십시오."
SIGNUP_RATE_LIMIT_PREFIX = "auth:ratelimit:signup:ip:"
SIGNUP_RATE_LIMIT_EXCEEDED_DETAIL = (
    "너무 많은 회원가입 시도가 발생했습니다. 잠시 후 다시 시도해 주십시오."
)
DOCUMENT_EXTRACTION_RATE_LIMIT_USER_PREFIX = "api:ratelimit:document_extraction:user:"
DOCUMENT_EXTRACTION_RATE_LIMIT_IP_PREFIX = "api:ratelimit:document_extraction:ip:"
DOCUMENT_EXTRACTION_RATE_LIMIT_USER_MAX_REQUESTS = 10
DOCUMENT_EXTRACTION_RATE_LIMIT_IP_MAX_REQUESTS = 30
DOCUMENT_EXTRACTION_RATE_LIMIT_WINDOW_SECONDS = 3600
DOCUMENT_EXTRACTION_RATE_LIMIT_EXCEEDED_DETAIL = (
    "요청이 너무 많습니다. 잠시 후 다시 시도해 주십시오."
)


AUTH_SERVICE_UNAVAILABLE_DETAIL = (
    "일시적으로 인증 요청을 처리할 수 없습니다. 잠시 후 다시 시도해 주십시오."
)


class LoginRateLimiter:
    """로그인 시도 제한기 (IP 축 및 계정 축).

    Redis 를 사용하여 로그인 실패 횟수를 기록하고 임계치 초과 시 429 로 차단합니다.
    Redis 가 다운되거나 사용 불가할 때는 503 으로 차단합니다 (fail-closed).
    임계값과 잠금 시간은 settings 에서 동적으로 조회하여 변경에 즉각 반응합니다.
    """

    def __init__(self, connection: RedisConnection | None = None):
        self._conn = connection or RedisConnection(label="rate_limit")

    @property
    def ip_max_attempts(self) -> int:
        return int(getattr(settings, "AUTH_RATE_LIMIT_IP_MAX_ATTEMPTS", 10))

    @property
    def account_max_attempts(self) -> int:
        return int(getattr(settings, "AUTH_RATE_LIMIT_ACCOUNT_MAX_ATTEMPTS", 5))

    @property
    def lockout_seconds(self) -> int:
        return int(getattr(settings, "AUTH_RATE_LIMIT_LOCKOUT_SECONDS", 300))

    def _ip_key(self, ip: str) -> str:
        return f"{RATE_LIMIT_IP_PREFIX}{ip}"

    def _account_key(self, username: str) -> str:
        return f"{RATE_LIMIT_ACCOUNT_PREFIX}{username.strip().lower()}"

    def check_rate_limit(self, ip: str | None, username: str | None) -> None:
        """시도 제한 초과 여부를 검사합니다.

        초과 시 429 HTTPException 을 발생시킵니다 (남은 시간은 노출하지 않음).
        Redis 미가용 시에는 503 HTTPException 을 발생시킵니다 (fail-closed).
        """
        client = self._conn.client()
        if client is None:
            raise HTTPException(
                status_code=503,
                detail=AUTH_SERVICE_UNAVAILABLE_DETAIL,
            )

        try:
            if ip:
                ip_count = client.get(self._ip_key(ip))
                if ip_count is not None and int(ip_count) >= self.ip_max_attempts:
                    logger.warning("IP 로그인 시도 제한 초과: %s", ip)
                    raise HTTPException(
                        status_code=429,
                        detail=RATE_LIMIT_EXCEEDED_DETAIL,
                    )

            if username:
                acc_count = client.get(self._account_key(username))
                if acc_count is not None and int(acc_count) >= self.account_max_attempts:
                    logger.warning("계정 로그인 시도 제한 초과: %s", username)
                    raise HTTPException(
                        status_code=429,
                        detail=RATE_LIMIT_EXCEEDED_DETAIL,
                    )
        except HTTPException:
            raise
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning("로그인 시도 제한 조회 중 Redis 오류 발생: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=AUTH_SERVICE_UNAVAILABLE_DETAIL,
            ) from exc

    def record_failure(self, ip: str | None, username: str | None) -> None:
        """로그인 실패 시 카운터를 증가시킵니다.

        Redis 미가용 시에는 조용히 무시합니다.
        """
        client = self._conn.client()
        if client is None:
            return

        lockout = self.lockout_seconds
        try:
            pipe = client.pipeline()
            if ip:
                key_ip = self._ip_key(ip)
                pipe.incr(key_ip)
                pipe.expire(key_ip, lockout)
            if username:
                key_acc = self._account_key(username)
                pipe.incr(key_acc)
                pipe.expire(key_acc, lockout)
            pipe.execute()
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning("로그인 실패 카운터 기록 중 Redis 오류 발생: %s", exc)

    def record_success(self, ip: str | None, username: str | None) -> None:
        """로그인 성공 시 계정 카운터를 초기화합니다."""
        client = self._conn.client()
        if client is None:
            return

        try:
            if username:
                client.delete(self._account_key(username))
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning("로그인 카운터 초기화 중 Redis 오류 발생: %s", exc)


login_rate_limiter = LoginRateLimiter()


class AnonymousAPIRateLimiter:
    """익명 챗봇 API 요청 제한기 (IP 축).

    Redis 장애 시에는 요청을 차단하지 않고 제한을 건너뜁니다. 임계값과
    윈도우는 settings 속성으로 읽어 환경별 운영 조정을 허용합니다.
    """

    def __init__(self, connection: RedisConnection | None = None):
        self._conn = connection or RedisConnection(label="anonymous_api_rate_limit")

    @property
    def max_requests(self) -> int:
        return settings.ANONYMOUS_API_RATE_LIMIT_MAX_REQUESTS

    @property
    def window_seconds(self) -> int:
        return settings.ANONYMOUS_API_RATE_LIMIT_WINDOW_SECONDS

    @staticmethod
    def _key(ip: str) -> str:
        return f"{ANONYMOUS_API_RATE_LIMIT_PREFIX}{ip}"

    def check_rate_limit(self, ip: str | None) -> None:
        """현재 익명 요청 수가 임계를 넘었는지 검사합니다."""
        client = self._conn.client()
        if client is None or not ip:
            return
        try:
            count = client.get(self._key(ip))
            if count is not None and int(count) >= self.max_requests:
                logger.warning("익명 API 요청 제한 초과: %s", ip)
                raise HTTPException(
                    status_code=429,
                    detail=ANONYMOUS_API_RATE_LIMIT_EXCEEDED_DETAIL,
                )
        except HTTPException:
            raise
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning("익명 API 요청 제한 조회 중 Redis 오류 발생, 제한을 건너뜁니다: %s", exc)

    def record_request(self, ip: str | None) -> None:
        """익명 요청을 현재 윈도우에 기록합니다."""
        client = self._conn.client()
        if client is None or not ip:
            return
        try:
            pipe = client.pipeline()
            key = self._key(ip)
            pipe.incr(key)
            pipe.expire(key, self.window_seconds)
            pipe.execute()
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning("익명 API 요청 제한 기록 중 Redis 오류 발생, 제한을 건너뜁니다: %s", exc)


anonymous_api_rate_limiter = AnonymousAPIRateLimiter()


class AuthenticatedAPIRateLimiter:
    """로그인 사용자 API 요청 제한기 (user 축).

    Redis 장애 시에는 익명 제한기와 같이 요청을 차단하지 않고 제한을 건너뜁니다.
    한도와 윈도우는 모듈 상수로 고정합니다.
    """

    def __init__(self, connection: RedisConnection | None = None):
        self._conn = connection or RedisConnection(label="authenticated_api_rate_limit")

    @property
    def max_requests(self) -> int:
        return AUTHENTICATED_API_RATE_LIMIT_MAX_REQUESTS

    @property
    def window_seconds(self) -> int:
        return AUTHENTICATED_API_RATE_LIMIT_WINDOW_SECONDS

    @staticmethod
    def _key(user_id: int) -> str:
        return f"{AUTHENTICATED_API_RATE_LIMIT_PREFIX}{user_id}"

    def check_rate_limit(self, user_id: int | None) -> None:
        """현재 로그인 요청 수가 임계를 넘었는지 검사합니다."""
        client = self._conn.client()
        if client is None or user_id is None:
            return
        try:
            count = client.get(self._key(user_id))
            if count is not None and int(count) >= self.max_requests:
                logger.warning("로그인 API 요청 제한 초과: %s", user_id)
                raise HTTPException(
                    status_code=429,
                    detail=AUTHENTICATED_API_RATE_LIMIT_EXCEEDED_DETAIL,
                )
        except HTTPException:
            raise
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning(
                "로그인 API 요청 제한 조회 중 Redis 오류 발생, 제한을 건너뜁니다: %s", exc
            )

    def record_request(self, user_id: int | None) -> None:
        """로그인 요청을 현재 윈도우에 기록합니다."""
        client = self._conn.client()
        if client is None or user_id is None:
            return
        try:
            pipe = client.pipeline()
            key = self._key(user_id)
            pipe.incr(key)
            pipe.expire(key, self.window_seconds)
            pipe.execute()
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning(
                "로그인 API 요청 제한 기록 중 Redis 오류 발생, 제한을 건너뜁니다: %s", exc
            )


authenticated_api_rate_limiter = AuthenticatedAPIRateLimiter()


class DocumentExtractionRateLimiter:
    """문서 추출 API 요청 제한기 (사용자·IP 축, 고정 윈도우).

    사용자 기준 시간당 10회, IP 기준 시간당 30회로 제한합니다. Redis 장애 시에는
    로그인 사용자 제한기와 같이 요청을 차단하지 않고 제한을 건너뜁니다. 카운터
    키에는 반드시 TTL 을 겁니다(운영 Redis 는 volatile-lru).
    """

    def __init__(self, connection: RedisConnection | None = None):
        self._conn = connection or RedisConnection(label="document_extraction_rate_limit")

    @staticmethod
    def _user_key(user_id: int) -> str:
        return f"{DOCUMENT_EXTRACTION_RATE_LIMIT_USER_PREFIX}{user_id}"

    @staticmethod
    def _ip_key(ip: str) -> str:
        return f"{DOCUMENT_EXTRACTION_RATE_LIMIT_IP_PREFIX}{ip}"

    def check_rate_limit(self, user_id: int | None, ip: str | None) -> None:
        """사용자·IP 축 한도를 모두 검사합니다. 초과 시 429 를 발생시킵니다."""
        client = self._conn.client()
        if client is None:
            return
        try:
            if user_id is not None:
                count = client.get(self._user_key(user_id))
                if (
                    count is not None
                    and int(count) >= DOCUMENT_EXTRACTION_RATE_LIMIT_USER_MAX_REQUESTS
                ):
                    logger.warning("문서 추출 요청 제한 초과(사용자): %s", user_id)
                    raise HTTPException(
                        status_code=429,
                        detail=DOCUMENT_EXTRACTION_RATE_LIMIT_EXCEEDED_DETAIL,
                    )
            if ip:
                count = client.get(self._ip_key(ip))
                if (
                    count is not None
                    and int(count) >= DOCUMENT_EXTRACTION_RATE_LIMIT_IP_MAX_REQUESTS
                ):
                    logger.warning("문서 추출 요청 제한 초과(IP): %s", ip)
                    raise HTTPException(
                        status_code=429,
                        detail=DOCUMENT_EXTRACTION_RATE_LIMIT_EXCEEDED_DETAIL,
                    )
        except HTTPException:
            raise
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning(
                "문서 추출 요청 제한 조회 중 Redis 오류 발생, 제한을 건너뜁니다: %s", exc
            )

    def record_request(self, user_id: int | None, ip: str | None) -> None:
        """요청을 사용자·IP 축 카운터에 기록합니다. 두 키 모두 TTL 을 겁니다."""
        client = self._conn.client()
        if client is None:
            return
        try:
            pipe = client.pipeline()
            if user_id is not None:
                key = self._user_key(user_id)
                pipe.incr(key)
                pipe.expire(key, DOCUMENT_EXTRACTION_RATE_LIMIT_WINDOW_SECONDS)
            if ip:
                key = self._ip_key(ip)
                pipe.incr(key)
                pipe.expire(key, DOCUMENT_EXTRACTION_RATE_LIMIT_WINDOW_SECONDS)
            pipe.execute()
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning(
                "문서 추출 요청 제한 기록 중 Redis 오류 발생, 제한을 건너뜁니다: %s", exc
            )


document_extraction_rate_limiter = DocumentExtractionRateLimiter()


def enforce_document_extraction_quota(request: Any, user: Any) -> None:
    """문서 추출 요청의 사용자·IP 축 한도를 검사하고 기록합니다."""
    user_id = getattr(user, "id", None)
    peer = request.client.host if request.client and request.client.host else ""
    ip = resolve_client_ip(peer, request.headers.get("x-forwarded-for"))
    document_extraction_rate_limiter.check_rate_limit(user_id, ip)
    document_extraction_rate_limiter.record_request(user_id, ip)


def enforce_anonymous_api_quota(request: Any, user: Any) -> None:
    if user is not None:
        user_id = getattr(user, "id", None)
        authenticated_api_rate_limiter.check_rate_limit(user_id)
        authenticated_api_rate_limiter.record_request(user_id)
        return
    peer = request.client.host if request.client and request.client.host else ""
    ip = resolve_client_ip(peer, request.headers.get("x-forwarded-for"))
    anonymous_api_rate_limiter.check_rate_limit(ip)
    anonymous_api_rate_limiter.record_request(ip)


class SignupRateLimiter:
    """회원가입 요청 제한기 (IP 축 고정 윈도우).

    Redis 를 사용하여 회원가입 시도 횟수를 기록하고 임계치 초과 시 429 로 차단합니다.
    Redis 가 다운되거나 사용 불가할 때는 503 으로 차단합니다 (fail-closed).
    임계값과 윈도우 시간은 settings 에서 동적으로 조회하여 변경에 즉각 반응합니다.
    """

    def __init__(self, connection: RedisConnection | None = None):
        self._conn = connection or login_rate_limiter._conn

    @property
    def max_attempts(self) -> int:
        return int(getattr(settings, "SIGNUP_RATE_LIMIT_MAX", 10))

    @property
    def window_seconds(self) -> int:
        return int(getattr(settings, "SIGNUP_RATE_LIMIT_WINDOW_SECONDS", 3600))

    def _key(self, ip: str) -> str:
        return f"{SIGNUP_RATE_LIMIT_PREFIX}{ip}"

    def check_rate_limit(self, ip: str | None) -> None:
        """회원가입 요청 수가 임계를 넘었는지 검사합니다.

        초과 시 429 HTTPException 을 발생시킵니다.
        Redis 미가용 시에는 503 HTTPException 을 발생시킵니다 (fail-closed).
        """
        client = self._conn.client()
        if client is None:
            raise HTTPException(
                status_code=503,
                detail=AUTH_SERVICE_UNAVAILABLE_DETAIL,
            )
        if not ip:
            return

        try:
            count = client.get(self._key(ip))
            if count is not None and int(count) >= self.max_attempts:
                logger.warning("IP 회원가입 시도 제한 초과: %s", ip)
                raise HTTPException(
                    status_code=429,
                    detail=SIGNUP_RATE_LIMIT_EXCEEDED_DETAIL,
                )
        except HTTPException:
            raise
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning("회원가입 시도 제한 조회 중 Redis 오류 발생: %s", exc)
            raise HTTPException(
                status_code=503,
                detail=AUTH_SERVICE_UNAVAILABLE_DETAIL,
            ) from exc

    def record_attempt(self, ip: str | None) -> None:
        """회원가입 시도를 기록합니다.

        성공·실패와 무관하게 시도마다 1회 기록합니다.
        Redis 미가용 시에는 제한을 건너뛰고 경고 로그를 남깁니다.
        """
        client = self._conn.client()
        if client is None or not ip:
            return

        key = self._key(ip)
        window = self.window_seconds
        try:
            pipe = client.pipeline()
            pipe.incr(key)
            pipe.expire(key, window)
            pipe.execute()
        except Exception as exc:
            self._conn.invalidate(exc)
            logger.warning(
                "회원가입 시도 카운터 기록 중 Redis 오류 발생, 제한을 건너뜁니다: %s", exc
            )


signup_rate_limiter = SignupRateLimiter()


def _parse_trusted_proxies() -> list[ipaddress._BaseNetwork]:
    """settings.TRUSTED_PROXY_IPS 를 네트워크 목록으로 해석합니다.

    잘못된 항목은 조용히 버립니다. 설정 오타 하나로 인증 전체가 죽는 편보다
    그 항목만 신뢰하지 않는 편이 안전합니다.
    """
    networks: list[ipaddress._BaseNetwork] = []
    for raw in str(getattr(settings, "TRUSTED_PROXY_IPS", "") or "").split(","):
        item = raw.strip()
        if not item:
            continue
        try:
            networks.append(ipaddress.ip_network(item, strict=False))
        except ValueError:
            logger.warning("TRUSTED_PROXY_IPS 항목을 해석하지 못해 무시합니다: %s", item)
    return networks


def _is_trusted_proxy(addr: str, networks: list[ipaddress._BaseNetwork]) -> bool:
    if not networks:
        return False
    try:
        parsed = ipaddress.ip_address(addr)
    except ValueError:
        return False
    return any(parsed in net for net in networks)


def resolve_client_ip(peer_ip: str | None, forwarded_for: str | None) -> str:
    """시도 제한에 쓸 클라이언트 IP 를 정합니다.

    직접 연결한 피어가 신뢰 프록시일 때만 X-Forwarded-For 를 해석합니다.
    검증 없이 헤더를 믿으면 공격자가 값을 위조해 IP 축 제한을 우회하거나
    임의의 주소를 잠글 수 있으므로, 신뢰 목록이 비어 있으면 헤더를 무시합니다.

    헤더는 왼쪽이 원 클라이언트이고 오른쪽으로 갈수록 가까운 프록시입니다.
    오른쪽부터 신뢰 프록시를 걷어내고 처음 만나는 비신뢰 주소를 씁니다.
    """
    peer = (peer_ip or "").strip() or "127.0.0.1"
    networks = _parse_trusted_proxies()
    if not _is_trusted_proxy(peer, networks):
        return peer

    hops = [h.strip() for h in str(forwarded_for or "").split(",") if h.strip()]
    for hop in reversed(hops):
        if not _is_trusted_proxy(hop, networks):
            try:
                ipaddress.ip_address(hop)
            except ValueError:
                continue
            return hop
    # 모든 홉이 신뢰 프록시이거나 헤더가 비었으면 피어 주소로 되돌아갑니다.
    return peer
