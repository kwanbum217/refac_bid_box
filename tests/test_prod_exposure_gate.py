"""운영 노출 게이트(API 문서, CORS)와 SSE 오류 응답의 정보 노출을 검증합니다.

전역 `settings` 객체는 건드리지 않습니다. 모듈 로드 시점에 한 번 만들어지므로
변조하면 같은 세션의 다른 테스트가 함께 깨집니다. 대신 `Settings` 를 직접
인스턴스화해 `create_app` 에 넘깁니다.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.app.api.v1 import chatbot as chatbot_module
from src.app.core.config import Settings
from src.app.main import create_app

PRODUCTION_ORIGIN = "https://app.example.com"
FOREIGN_ORIGIN = "https://evil.example.net"


def _production_settings(**overrides) -> Settings:
    values = {
        "ENVIRONMENT": "production",
        "DEBUG": False,
        "SECRET_KEY": "production-test-secret-key-that-is-long-enough",
        "DATABASE_URL": "mysql+pymysql://app:strong-password@db:3306/procurement",
        "DB_PASSWORD": "strong-password",
        "CORS_ALLOWED_ORIGINS": PRODUCTION_ORIGIN,
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


def _development_settings(**overrides) -> Settings:
    values = {
        "ENVIRONMENT": "development",
        "SECRET_KEY": "test-only-secret-key-at-least-32-characters",
        "CORS_ALLOWED_ORIGINS": "",
        "_env_file": None,
    }
    values.update(overrides)
    return Settings(**values)


@pytest.fixture
def production_client() -> TestClient:
    return TestClient(create_app(_production_settings()))


@pytest.fixture
def development_client() -> TestClient:
    return TestClient(create_app(_development_settings()))


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_production_hides_api_documentation(production_client, path):
    """docs_url 만 닫고 openapi_url 을 남기면 스키마가 그대로 노출됩니다."""
    assert production_client.get(path).status_code == 404


@pytest.mark.parametrize("path", ["/docs", "/redoc", "/openapi.json"])
def test_development_keeps_api_documentation(development_client, path):
    assert development_client.get(path).status_code == 200


def test_production_rejects_unlisted_origin_with_credentials(production_client):
    """목록 밖 오리진에는 자격증명 허용 헤더가 나가지 않아야 합니다."""
    response = production_client.get(
        "/api/v1/health",
        headers={"Origin": FOREIGN_ORIGIN, "Cookie": "sessionid=whatever"},
    )

    # Access-Control-Allow-Origin 이 없으면 브라우저가 응답을 스크립트에 넘기지
    # 않습니다. Starlette 은 allow_credentials 가 켜져 있으면 오리진 허용 여부와
    # 무관하게 Allow-Credentials 를 붙이므로, 실제 관문은 Allow-Origin 쪽입니다.
    assert "access-control-allow-origin" not in response.headers


def test_production_rejects_unlisted_origin_preflight(production_client):
    response = production_client.options(
        "/api/v1/chatbot/chat",
        headers={
            "Origin": FOREIGN_ORIGIN,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )

    assert response.headers.get("access-control-allow-origin") != FOREIGN_ORIGIN
    assert response.headers.get("access-control-allow-origin") != "*"


def test_production_allows_listed_origin(production_client):
    response = production_client.get(
        "/api/v1/health",
        headers={"Origin": PRODUCTION_ORIGIN},
    )

    assert response.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN
    assert response.headers.get("access-control-allow-credentials") == "true"


def test_development_reflects_origin_for_local_work(development_client):
    """로컬 개발은 기존 범위를 유지합니다. 좁히면 화면이 깨집니다."""
    response = development_client.get(
        "/api/v1/health",
        headers={"Origin": FOREIGN_ORIGIN},
    )

    assert response.headers.get("access-control-allow-origin") in {FOREIGN_ORIGIN, "*"}


def test_development_with_explicit_origins_stops_reflecting():
    """개발에서도 목록을 채우면 그 목록만 허용합니다."""
    client = TestClient(create_app(_development_settings(CORS_ALLOWED_ORIGINS=PRODUCTION_ORIGIN)))

    allowed = client.get("/api/v1/health", headers={"Origin": PRODUCTION_ORIGIN})
    rejected = client.get("/api/v1/health", headers={"Origin": FOREIGN_ORIGIN})

    assert allowed.headers.get("access-control-allow-origin") == PRODUCTION_ORIGIN
    assert "access-control-allow-origin" not in rejected.headers


# 예외 문자열에 섞여 들 수 있는 접속 정보를 모방한 값입니다. 실제 자격증명이
# 아니며, 응답 본문에 이 문자열이 나타나지 않는지 확인하는 용도입니다.
SECRET_IN_EXCEPTION = "mysql+pymysql://app:super-secret-password@db:3306/procurement"  # noqa: S105


def _sse_events(body: str) -> list[dict]:
    events = []
    for block in body.split("\n\n"):
        for line in block.splitlines():
            if line.startswith("data:"):
                events.append(json.loads(line[len("data:") :].strip()))
    return events


def test_canonical_stream_error_hides_exception_text(client, monkeypatch):
    """정본 SSE 오류에 예외 원문이 실리면 접속 정보가 화면으로 나갑니다."""

    def explode(*_args, **_kwargs):
        raise RuntimeError(f"connection failed: {SECRET_IN_EXCEPTION}")

    monkeypatch.setattr(chatbot_module, "_prepare_chat", explode)

    response = client.post(
        "/api/v1/chatbot/chat/stream",
        json={"message": "적격심사 감점 요인"},
    )

    assert response.status_code == 200
    assert SECRET_IN_EXCEPTION not in response.text
    assert "super-secret-password" not in response.text
    assert "RuntimeError" not in response.text
    assert chatbot_module.STREAM_ERROR_MESSAGE in response.text

    errors = [event for event in _sse_events(response.text) if event.get("trace_id")]
    assert errors, "오류 이벤트에 추적 id 가 실려야 합니다"
    assert errors[-1]["message"] == chatbot_module.STREAM_ERROR_MESSAGE


def test_trace_id_matches_provenance_format():
    """추적 id 는 src/rag/engine.py 의 provenance.trace_id 와 같은 형식입니다."""
    trace_id = chatbot_module._new_trace_id()

    assert len(trace_id) == 22
    assert trace_id[:14].isdigit()
    int(trace_id[14:], 16)
