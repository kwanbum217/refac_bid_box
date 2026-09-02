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
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
SESSION_COOKIE_NAME = "bidbox_session"
SESSION_CACHE_PREFIX = "auth:session:"


def make_password(
    raw_password: str, salt: str | None = None, iterations: int = DEFAULT_ITERATIONS
) -> str:
    salt = salt or secrets.token_hex(6)
    digest = hashlib.pbkdf2_hmac("sha256", raw_password.encode(), salt.encode(), iterations)
    encoded = base64.b64encode(digest).decode().strip()
    return f"{ALGORITHM}${iterations}${salt}${encoded}"


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
        client = self._conn.client()
        if client is None:
            self._fallback("Redis 연결 없음")[token] = (time.time() + ttl, payload)
            return
        self._degraded_logged = False
        try:
            client.setex(self._key(token), ttl, json.dumps(payload, ensure_ascii=False))
        except Exception as exc:
            self._conn.invalidate(exc)
            self._fallback(f"세션 저장 실패: {exc}")[token] = (time.time() + ttl, payload)

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
        return payload if isinstance(payload, dict) else None

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

    @staticmethod
    def _read_local(
        store: dict[str, tuple[float, dict[str, Any]]], token: str
    ) -> dict[str, Any] | None:
        entry = store.get(token)
        if entry is None:
            return None
        expires_at, payload = entry
        if expires_at < time.time():
            store.pop(token, None)
            return None
        return payload


session_store = SessionStore()


def create_session(user_id: int, username: str) -> str:
    token = secrets.token_urlsafe(32)
    session_store.create(
        token,
        {"user_id": int(user_id), "username": username},
        SESSION_TTL_SECONDS,
    )
    return token


def read_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    return session_store.read(token)


def destroy_session(token: str | None) -> None:
    if token:
        session_store.destroy(token)


RATE_LIMIT_IP_PREFIX = "auth:ratelimit:ip:"
RATE_LIMIT_ACCOUNT_PREFIX = "auth:ratelimit:account:"
RATE_LIMIT_EXCEEDED_DETAIL = "너무 많은 로그인 시도가 발생했습니다. 잠시 후 다시 시도해 주십시오."


class LoginRateLimiter:
    """로그인 시도 제한기 (IP 축 및 계정 축).

    Redis 를 사용하여 로그인 실패 횟수를 기록하고 임계치 초과 시 429 로 차단합니다.
    Redis 가 다운되거나 사용 불가할 때는 로그인을 차단하지 않고 제한만 건너뜁니다 (fail-open).
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
        Redis 미가용 시에는 제한을 건너뛰고 정상 통과합니다.
        """
        client = self._conn.client()
        if client is None:
            return

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
            logger.warning("로그인 시도 제한 조회 중 Redis 오류 발생, 제한을 건너뜁니다: %s", exc)

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
