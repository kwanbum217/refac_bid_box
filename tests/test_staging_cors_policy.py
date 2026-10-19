"""staging CORS 정책의 fail-closed 계약을 검증합니다.

staging 은 development 의 임의 오리진 허용 편의를 물려받지 않습니다.
CORS_ALLOWED_ORIGINS 명시는 production 과 같은 기동 시 필수 조건입니다.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.app.core.config import Settings
from src.app.main import _cors_kwargs, create_app

STAGING_BASE = {
    "ENVIRONMENT": "staging",
    # DEBUG 와 DB 값은 안전한 값을 명시합니다. 실행 환경의 DEBUG=True·기본 DB
    # 비밀번호가 그대로 실리면 staging 에 새로 적용된 fail-closed 검사가 CORS 검사
    # 보다 먼저 걸려 검증하려던 메시지를 가립니다.
    "DEBUG": False,
    "SECRET_KEY": "test-only-secret-key-at-least-32-characters",
    "DATABASE_URL": "mysql+pymysql://app:strong-password@db:3306/procurement",
    "DB_PASSWORD": "strong-password",
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


def test_development_empty_origins_with_allow_all_disabled_uses_local_list():
    configured = Settings(
        **DEVELOPMENT_BASE,
        CORS_ALLOWED_ORIGINS="",
        CORS_DEV_ALLOW_ALL=False,
        _env_file=None,
    )

    assert _cors_kwargs(configured)["allow_origins"] == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert "*" not in _cors_kwargs(configured)["allow_origins"]


def test_development_empty_origins_unspecified_allow_all_uses_local_list():
    # (a) CORS_DEV_ALLOW_ALL 미지정 → 기본값 False → 로컬 목록 4개, * 없음
    configured = Settings(
        **DEVELOPMENT_BASE,
        CORS_ALLOWED_ORIGINS="",
        _env_file=None,
    )

    kwargs = _cors_kwargs(configured)
    assert kwargs["allow_origins"] == [
        "http://localhost:8000",
        "http://127.0.0.1:8000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]
    assert "*" not in kwargs["allow_origins"]


def test_settings_default_cors_dev_allow_all_is_false():
    # (b) Settings() 기본값의 CORS_DEV_ALLOW_ALL 이 False
    configured = Settings(
        SECRET_KEY="test-only-secret-key-at-least-32-characters",
        _env_file=None,
    )

    assert configured.CORS_DEV_ALLOW_ALL is False


def test_development_default_app_rejects_foreign_origin_allows_local():
    # (c) TestClient 로 개발 기본 설정 앱
    client = TestClient(
        create_app(
            Settings(
                **DEVELOPMENT_BASE,
                CORS_ALLOWED_ORIGINS="",
                _env_file=None,
            )
        )
    )

    foreign = client.get("/api/v1/health", headers={"Origin": "https://evil.example"})
    assert "access-control-allow-origin" not in foreign.headers

    local = client.get("/api/v1/health", headers={"Origin": "http://localhost:5173"})
    assert local.headers.get("access-control-allow-origin") == "http://localhost:5173"


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
