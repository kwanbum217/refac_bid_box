"""
tests/test_startup_warmup.py

기동 예열 검증.

기동 직후 첫 요청들이 모델 로드 비용을 무는 것을 막는 장치입니다. 2026-08-06
실측에서 예측 API 가 기동 직후 100회 P95 164.1ms 로 목표 100ms 를 넘겼고,
같은 부하를 예열 뒤에 다시 주니 P95 16.4ms 였습니다.

두 가지를 고정합니다.

1. **예열 실패가 기동을 막지 않을 것.** 예열은 부가 기능이며, 실패하면 첫
   요청이 지연 로드로 처리하면 됩니다. 여기서 예외가 새면 앱이 못 뜹니다.
2. **테스트 환경에서는 모델을 올리지 않을 것.** `SKIP_MODEL_LOAD` 가 켜져
   있는데 가중치를 읽으면 CI 가 데이터 자산에 묶입니다.
"""

from unittest.mock import Mock

import pytest

from src.app import main


@pytest.mark.asyncio
async def test_predictor_warmup_skipped_when_model_load_disabled(monkeypatch):
    monkeypatch.setenv("SKIP_MODEL_LOAD", "true")
    loader = Mock()
    monkeypatch.setattr("src.ml.model_registry.ModelRegistry.load_all_models", loader)

    await main._warm_predictor()

    loader.assert_not_called()


@pytest.mark.asyncio
async def test_predictor_warmup_loads_models(monkeypatch):
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    loader = Mock()
    monkeypatch.setattr("src.ml.model_registry.ModelRegistry.load_all_models", loader)

    await main._warm_predictor()

    loader.assert_called_once()


@pytest.mark.asyncio
async def test_predictor_warmup_swallows_failure(monkeypatch):
    """가중치가 없거나 깨져도 앱은 떠야 합니다."""
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    monkeypatch.setattr(
        "src.ml.model_registry.ModelRegistry.load_all_models",
        Mock(side_effect=RuntimeError("model.bin 손상")),
    )

    await main._warm_predictor()


@pytest.mark.asyncio
async def test_llm_warmup_skipped_when_disabled(monkeypatch):
    from src.app.core.config import settings

    monkeypatch.setattr(settings, "LLM_WARMUP_ON_STARTUP", False, raising=False)
    builder = Mock()
    monkeypatch.setattr("src.rag.llm.build_backend", builder)

    await main._warm_llm_backend()

    builder.assert_not_called()
