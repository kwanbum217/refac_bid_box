"""
src/app/services/automation_tokens.py

자동화 토큰 서명 및 검증 모듈 (원본 django.core.signing.TimestampSigner 대체, 표준 라이브러리만 사용).
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import time

from src.app.core.cache import RedisConnection
from src.app.core.config import settings

logger = logging.getLogger(__name__)

CONFIRMATION_SALT = "bidbox.automation.confirmation"
CALLBACK_SALT = "bidbox.automation.callback"
CONFIRMATION_MAX_AGE = 60 * 30

_confirmation_redis_conn: RedisConnection | None = None


def get_confirmation_redis_conn() -> RedisConnection:
    global _confirmation_redis_conn
    if _confirmation_redis_conn is None:
        _confirmation_redis_conn = RedisConnection(label="automation_tokens")
    return _confirmation_redis_conn


def set_confirmation_redis_conn(conn: RedisConnection | None) -> None:
    global _confirmation_redis_conn
    _confirmation_redis_conn = conn


def consume_confirmation_token(
    token: str,
    conn: RedisConnection | None = None,
    ttl: int = CONFIRMATION_MAX_AGE,
) -> None:
    """확인 토큰을 Redis 에서 원자적으로 단일 소비합니다 (SET NX EX).

    이미 소비되었거나 Redis 연결이 불가능한 경우 AutomationError 를 발생시킵니다 (fail-closed).
    """
    if not token:
        raise AutomationError("확인 토큰이 필요합니다.")

    redis_conn = conn or get_confirmation_redis_conn()
    client = redis_conn.client()
    if client is None:
        raise AutomationError("Redis 연결이 불가능하여 확인 토큰을 검증할 수 없습니다.")

    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    key = f"bidbox:automation:consumed_token:{token_hash}"

    try:
        acquired = client.set(key, "1", ex=ttl, nx=True)
    except Exception as exc:
        redis_conn.invalidate(exc)
        logger.warning("Redis 토큰 소비 처리 중 오류 발생: %s", exc)
        raise AutomationError("Redis 오류로 확인 토큰을 처리할 수 없습니다.") from exc

    if not acquired:
        raise AutomationError("이미 사용된 확인 토큰입니다.")


# 콜백 토큰은 실행 중인 작업이 결과를 보고하는 동안만 유효해야 합니다.
# 만료가 없으면 유출된 토큰이 영구히 사용 가능하고, 종료된 지 한참 지난
# 작업의 늦은 보고도 그대로 받아들여집니다. 재학습 등 장시간 작업을
# 감안해 24시간으로 둡니다.
CALLBACK_MAX_AGE = 60 * 60 * 24


class AutomationError(RuntimeError):
    """자동화 실행 계층 오류 (원본 HarnessTriggerError 대응)."""


def _sign(value: str, salt: str) -> str:
    timestamp = str(int(time.time()))
    payload = f"{value}:{timestamp}"
    digest = hmac.new(
        f"{settings.SECRET_KEY}:{salt}".encode(),
        payload.encode(),
        hashlib.sha256,
    ).digest()
    signature = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    return f"{payload}:{signature}"


def _unsign(token: str, salt: str, max_age: int | None = None) -> str:
    try:
        value, timestamp, signature = token.rsplit(":", 2)
    except ValueError as exc:
        raise AutomationError("서명 형식이 올바르지 않습니다.") from exc

    payload = f"{value}:{timestamp}"
    expected = hmac.new(
        f"{settings.SECRET_KEY}:{salt}".encode(),
        payload.encode(),
        hashlib.sha256,
    ).digest()
    expected_signature = base64.urlsafe_b64encode(expected).decode().rstrip("=")
    if not hmac.compare_digest(signature, expected_signature):
        raise AutomationError("서명이 일치하지 않습니다.")

    if max_age is not None and (time.time() - int(timestamp)) > max_age:
        raise AutomationError("토큰이 만료되었습니다.")
    return value


def make_confirmation_token(job_id: str) -> str:
    return _sign(job_id, CONFIRMATION_SALT)


def resolve_confirmation_token(token: str, max_age: int = CONFIRMATION_MAX_AGE) -> str:
    return _unsign(token, CONFIRMATION_SALT, max_age)


def make_callback_token(job_id: str) -> str:
    return _sign(job_id, CALLBACK_SALT)


def verify_callback_token(job_id: str, token: str, max_age: int = CALLBACK_MAX_AGE) -> bool:
    if not token:
        return False
    try:
        return _unsign(token, CALLBACK_SALT, max_age) == str(job_id)
    except AutomationError:
        return False
