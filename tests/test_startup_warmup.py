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
    mock_logger = Mock()
    monkeypatch.setattr(main, "logger", mock_logger)

    await main._warm_predictor()

    loader.assert_not_called()
    assert mock_logger.info.called
    info_args = mock_logger.info.call_args[0]
    assert info_args[0] == "event=predictor_warmup, status=skipped, elapsed_ms=0.00"


@pytest.mark.asyncio
async def test_predictor_warmup_loads_models(monkeypatch):
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    loader = Mock(return_value=4)
    monkeypatch.setattr("src.ml.model_registry.ModelRegistry.load_all_models", loader)
    mock_logger = Mock()
    monkeypatch.setattr(main, "logger", mock_logger)

    await main._warm_predictor()

    loader.assert_called_once()
    assert mock_logger.info.called
    info_args = mock_logger.info.call_args[0]
    assert (
        info_args[0] == "event=predictor_warmup, status=success, elapsed_ms=%.2f, models_loaded=%d"
    )
    elapsed_ms = info_args[1]
    loaded_count = info_args[2]
    assert elapsed_ms >= 0.0
    assert loaded_count == 4


@pytest.mark.asyncio
async def test_predictor_warmup_swallows_failure(monkeypatch):
    """가중치가 없거나 깨져도 앱은 떠야 합니다."""
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    monkeypatch.setattr(
        "src.ml.model_registry.ModelRegistry.load_all_models",
        Mock(side_effect=RuntimeError("model.bin 손상")),
    )
    mock_logger = Mock()
    monkeypatch.setattr(main, "logger", mock_logger)

    await main._warm_predictor()

    assert mock_logger.warning.called
    warn_args = mock_logger.warning.call_args[0]
    assert warn_args[0] == "event=predictor_warmup, status=failed, elapsed_ms=%.2f, error=%s"
    elapsed_ms = warn_args[1]
    assert elapsed_ms >= 0.0
    assert "model.bin 손상" in str(warn_args[2])


@pytest.mark.asyncio
async def test_llm_warmup_skipped_when_disabled(monkeypatch):
    from src.app.core.config import settings

    monkeypatch.setattr(settings, "LLM_WARMUP_ON_STARTUP", False, raising=False)
    builder = Mock()
    monkeypatch.setattr("src.rag.llm.build_backend", builder)

    await main._warm_llm_backend()

    builder.assert_not_called()


@pytest.mark.asyncio
async def test_vector_warmup_calls_retrieval_once(monkeypatch):
    """기동 예열이 벡터 검색 경로를 한 번 부르고 성공 로그를 남겨야 합니다.

    2026-09-01 컨테이너 실측에서 프로세스 첫 retrieve_semantic_context 가
    13,142ms 였고 이후 46~56ms 였습니다. 비용은 HNSW 인덱스 적재와 Ollama 임베딩
    첫 연결에 있으며 keep_alive 로는 덮이지 않습니다.
    """
    from src.app.core.config import settings

    monkeypatch.setattr(settings, "VECTOR_WARMUP_ON_STARTUP", True, raising=False)
    called = []

    def fake_retrieve(plan):
        called.append(plan)
        return Mock(documents=[], ok=True)

    monkeypatch.setattr("src.rag.vector_store.retrieve_semantic_context", fake_retrieve)

    await main._warm_vector_search()

    assert len(called) == 1
    assert called[0].semantic_query == "예열"


@pytest.mark.asyncio
async def test_vector_warmup_skipped_when_disabled(monkeypatch):
    from src.app.core.config import settings

    monkeypatch.setattr(settings, "VECTOR_WARMUP_ON_STARTUP", False, raising=False)
    retrieve = Mock()
    monkeypatch.setattr("src.rag.vector_store.retrieve_semantic_context", retrieve)

    await main._warm_vector_search()

    retrieve.assert_not_called()


@pytest.mark.asyncio
async def test_vector_warmup_failure_does_not_raise(monkeypatch):
    """예열 실패가 기동을 막으면 안 됩니다. 서비스 정합성 요소가 아닙니다."""
    from src.app.core.config import settings

    monkeypatch.setattr(settings, "VECTOR_WARMUP_ON_STARTUP", True, raising=False)

    def boom(_plan):
        raise RuntimeError("ChromaDB 연결 실패")

    monkeypatch.setattr("src.rag.vector_store.retrieve_semantic_context", boom)
    warned = []
    monkeypatch.setattr(main.logger, "warning", lambda *args, **kwargs: warned.append(args))

    await main._warm_vector_search()

    assert warned, "실패는 조용히 넘기지 말고 경고로 남겨야 합니다."
    assert "vector_warmup" in str(warned[0][0])
