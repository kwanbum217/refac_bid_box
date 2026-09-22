"""staging CORS 정책의 fail-closed 계약을 검증합니다.

staging 은 development 의 임의 오리진 허용 편의를 물려받지 않습니다.
CORS_ALLOWED_ORIGINS 명시는 production 과 같은 기동 시 필수 조건입니다.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from src.app.core.config import Settings
from src.app.main import _cors_kwargs

STAGING_BASE = {
    "ENVIRONMENT": "staging",
    "SECRET_KEY": "test-only-secret-key-at-least-32-characters",
}

DEVELOPMENT_BASE = {
    "ENVIRONMENT": "development",
    "SECRET_KEY": "test-only-secret-key-at-least-32-characters",
}


def test_staging_rejects_empty_origins_even_with_dev_allow_all():
    with pytest.raises(ValidationError, match="staging"):
        Settings(
            **STAGING_BASE,
            CORS_ALLOWED_ORIGINS="",
            CORS_DEV_ALLOW_ALL=True,
            _env_file=None,
        )


@pytest.mark.parametrize("origins", ["*", "https://a.example.com,*"])
def test_staging_rejects_wildcard_origins(origins):
    with pytest.raises(ValidationError, match="staging"):
        Settings(**STAGING_BASE, CORS_ALLOWED_ORIGINS=origins, _env_file=None)


def test_staging_uses_explicit_origins_without_wildcard():
    configured = Settings(
        **STAGING_BASE,
        CORS_ALLOWED_ORIGINS="https://a.example.com, https://b.example.com",
        CORS_DEV_ALLOW_ALL=True,
        _env_file=None,
    )

    kwargs = _cors_kwargs(configured)

    assert kwargs["allow_origins"] == ["https://a.example.com", "https://b.example.com"]
    assert "*" not in kwargs["allow_origins"]


def test_development_empty_origins_with_allow_all_still_wildcard():
    configured = Settings(
        **DEVELOPMENT_BASE,
        CORS_ALLOWED_ORIGINS="",
        CORS_DEV_ALLOW_ALL=True,
        _env_file=None,
    )

    assert _cors_kwargs(configured)["allow_origins"] == ["*"]


def test_development_empty_origins_with_allow_all_disabled_is_empty():
    configured = Settings(
        **DEVELOPMENT_BASE,
        CORS_ALLOWED_ORIGINS="",
        CORS_DEV_ALLOW_ALL=False,
        _env_file=None,
    )

    assert _cors_kwargs(configured)["allow_origins"] == []


def test_production_rejection_is_unchanged():
    with pytest.raises(ValidationError, match="와일드카드"):
        Settings(
            ENVIRONMENT="production",
            DEBUG=False,
            SECRET_KEY="production-test-secret-key-that-is-long-enough",
            DATABASE_URL="mysql+pymysql://app:strong-password@db:3306/procurement",
            DB_PASSWORD="strong-password",
            CORS_ALLOWED_ORIGINS="https://app.example.com,*",
            _env_file=None,
        )
