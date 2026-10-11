"""헬스 응답이 예외 원문을 노출하지 않는지 검증합니다.

LLM 점검과 기동 예열(warmup)의 실패는 /api/v1/health/ready 응답에 실립니다.
예외 원문에는 DSN·키·내부 경로가 섞일 수 있으므로 응답에는 분류 문자열만
남기고 원문은 로그로만 보냅니다. 응답 키 구조는 바꾸지 않습니다.
"""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from src.app import main
from src.app.api.v1 import health
from src.app.core.config import settings
from src.app.main import app

client = TestClient(app)

# 응답에 나오면 안 되는 비밀값이 섞인 원문 예외 메시지입니다.
_LEAK = "RuntimeError: mysql+pymysql://app:sup3rsecret@db:3306/procurement"


def _patch_base_healthy(monkeypatch) -> None:
    for name in (
        "_check_mysql",
        "_check_redis",
        "_check_meilisearch",
        "_check_model_registry",
        "_check_chromadb",
    ):
        monkeypatch.setattr(health, name, lambda: None)

    health.warmup_state.mark_llm_done(success=True)
    health.warmup_state.mark_predictor_done(success=True)
    health.warmup_state.mark_vector_done(success=True)
    monkeypatch.setattr(health.warmup_state, "_started", True, raising=False)
    monkeypatch.setattr(settings, "READINESS_REQUIRE_WARMUP", False, raising=False)
    monkeypatch.setattr(settings, "READINESS_REQUIRE_LLM", False, raising=False)


def test_llm_check_detail_redacts_exception_message(monkeypatch):
    def boom():
        raise RuntimeError(_LEAK)

    monkeypatch.setattr("src.rag.llm.build_backend", boom)

    result = health._check_llm()

    assert result["ok"] is False
    assert _LEAK not in result["detail"]
    assert "sup3rsecret" not in result["detail"]


def test_readiness_response_does_not_leak_llm_exception(monkeypatch):
    _patch_base_healthy(monkeypatch)

    def boom():
        raise RuntimeError(_LEAK)

    monkeypatch.setattr("src.rag.llm.build_backend", boom)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["llm"]["ok"] is False
    assert set(data["llm"]) == {"ok", "provider", "detail", "latency_ms"}
    assert "sup3rsecret" not in response.text
    assert _LEAK not in response.text


@pytest.mark.asyncio
async def test_llm_warmup_error_is_classified_not_raw(monkeypatch):
    monkeypatch.setattr(settings, "LLM_WARMUP_ON_STARTUP", True, raising=False)

    def boom():
        raise RuntimeError(_LEAK)

    monkeypatch.setattr("src.rag.llm.build_backend", boom)
    health.warmup_state.start()
    try:
        await main._warm_llm_backend()

        error = health.warmup_state.get_summary()["details"]["llm"]["error"]
        assert error is not None
        assert _LEAK not in error
        assert "sup3rsecret" not in error
    finally:
        health.warmup_state.reset()


@pytest.mark.asyncio
async def test_predictor_warmup_error_is_classified_not_raw(monkeypatch):
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")

    def boom():
        raise RuntimeError(_LEAK)

    monkeypatch.setattr("src.ml.model_registry.ModelRegistry.load_all_models", boom)
    health.warmup_state.start()
    try:
        await main._warm_predictor()

        error = health.warmup_state.get_summary()["details"]["predictor"]["error"]
        assert error is not None
        assert _LEAK not in error
        assert "sup3rsecret" not in error
    finally:
        health.warmup_state.reset()


@pytest.mark.asyncio
async def test_vector_warmup_error_is_classified_not_raw(monkeypatch):
    monkeypatch.setattr(settings, "VECTOR_WARMUP_ON_STARTUP", True, raising=False)

    def boom(_plan):
        raise RuntimeError(_LEAK)

    monkeypatch.setattr("src.rag.vector_store.retrieve_semantic_context", boom)
    health.warmup_state.start()
    try:
        await main._warm_vector_search()

        error = health.warmup_state.get_summary()["details"]["vector_search"]["error"]
        assert error is not None
        assert _LEAK not in error
        assert "sup3rsecret" not in error
    finally:
        health.warmup_state.reset()


def test_readiness_response_does_not_leak_warmup_error(monkeypatch):
    _patch_base_healthy(monkeypatch)
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")

    def boom():
        raise RuntimeError(_LEAK)

    monkeypatch.setattr("src.ml.model_registry.ModelRegistry.load_all_models", boom)

    try:
        asyncio.run(main._warm_predictor())

        response = client.get("/api/v1/health/ready")

        assert "sup3rsecret" not in response.text
        assert _LEAK not in response.text
        data = response.json()
        assert (
            data["warmup"]["details"]["predictor"]["error"]
            == "RuntimeError: dependency_check_failed"
        )
        assert set(data["warmup"]["details"]["predictor"]) == {"ok", "error"}
    finally:
        health.warmup_state.reset()
