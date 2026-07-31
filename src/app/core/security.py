"""
src/app/core/security.py

비밀번호 해시와 세션 인증.

비밀번호는 Django 의 `pbkdf2_sha256$<iterations>$<salt>$<hash>` 포맷을 그대로 사용합니다.
원본 accounts_customuser 에 저장된 기존 계정이 그대로 로그인되어야 하기 때문입니다.
표준 라이브러리만 사용하므로 신규 의존성이 없습니다.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
from typing import Any

from src.app.core.cache import cache

ALGORITHM = "pbkdf2_sha256"
DEFAULT_ITERATIONS = 600_000
SESSION_TTL_SECONDS = 60 * 60 * 24 * 14
SESSION_COOKIE_NAME = "bidbox_session"
SESSION_CACHE_PREFIX = "auth:session:"


def make_password(raw_password: str, salt: str | None = None, iterations: int = DEFAULT_ITERATIONS) -> str:
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


def create_session(user_id: int, username: str) -> str:
    token = secrets.token_urlsafe(32)
    cache.set(
        f"{SESSION_CACHE_PREFIX}{token}",
        {"user_id": int(user_id), "username": username},
        SESSION_TTL_SECONDS,
    )
    return token


def read_session(token: str | None) -> dict[str, Any] | None:
    if not token:
        return None
    payload = cache.get(f"{SESSION_CACHE_PREFIX}{token}")
    return payload if isinstance(payload, dict) else None


def destroy_session(token: str | None) -> None:
    if token:
        cache.delete(f"{SESSION_CACHE_PREFIX}{token}")
