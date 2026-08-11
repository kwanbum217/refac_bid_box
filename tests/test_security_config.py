"""운영 보안 설정의 시동 차단 계약을 검증합니다."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.core.config import Settings


def test_secret_key_is_required(monkeypatch):
    monkeypatch.delenv("SECRET_KEY", raising=False)

    with pytest.raises(ValidationError, match="SECRET_KEY"):
        Settings(_env_file=None)


def test_secret_key_must_be_at_least_32_characters():
    with pytest.raises(ValidationError, match="32자"):
        Settings(SECRET_KEY="too-short", _env_file=None)


def test_unknown_environment_cannot_bypass_production_guards():
    with pytest.raises(ValidationError, match="ENVIRONMENT"):
        Settings(
            ENVIRONMENT="prodction",
            SECRET_KEY="test-only-secret-key-at-least-32-characters",
            _env_file=None,
        )


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"DEBUG": True}, "DEBUG"),
        (
            {"SECRET_KEY": "change-this-in-production-to-a-secure-random-key"},
            "예제 SECRET_KEY",
        ),
        ({"DB_PASSWORD": "rootpassword"}, "데이터베이스 비밀번호"),
        (
            {"DATABASE_URL": "mysql+pymysql://root:rootpassword@db:3306/procurement"},
            "데이터베이스 비밀번호",
        ),
    ],
)
def test_production_rejects_insecure_defaults(overrides, message):
    # 기준값은 전부 명시합니다. DEBUG 를 비워 두면 .env 가 os.environ 에 실린
    # 실행에서 DEBUG 가드가 먼저 걸려 검증하려던 메시지를 가립니다.
    values = {
        "ENVIRONMENT": "production",
        "DEBUG": False,
        "SECRET_KEY": "production-test-secret-key-that-is-long-enough",
        "DATABASE_URL": "mysql+pymysql://app:strong-password@db:3306/procurement",
        "DB_PASSWORD": "strong-password",
        "_env_file": None,
    }
    values.update(overrides)

    with pytest.raises(ValidationError, match=message):
        Settings(**values)


def test_production_accepts_explicit_secure_settings():
    configured = Settings(
        ENVIRONMENT="production",
        DEBUG=False,
        SECRET_KEY="production-test-secret-key-that-is-long-enough",
        DATABASE_URL="mysql+pymysql://app:strong-password@db:3306/procurement",
        DB_PASSWORD="strong-password",
        _env_file=None,
    )

    assert configured.ENVIRONMENT == "production"
