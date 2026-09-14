"""tests/test_llm_observability.py

RAG LLM 관측성 메트릭 계측 단위 및 통합 테스트.
- (a) 네 지표(rag_llm_ttft_ms, rag_llm_generation_ms, rag_llm_tokens, rag_llm_requests) 기록 검증
- (b) 스트리밍 첫 청크 시간(TTFT) 기록 검증
- (c) 토큰 필드가 없을 때 토큰 지표 생략(추정 금지) 검증
- (d) 예외 발생 시 outcome=error 기록 및 예외 재전파 검증 (중복 기록 방지)
- (e) 지표 비활성화 시 무동작(No-op) 및 정상 응답 반환 검증
- (f) Gemini 백엔드 계측 및 프롬프트/질의 등 PII 라벨 배제 검증
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from typing import Any
from unittest.mock import MagicMock, patch

import httpx
import pytest
from opentelemetry.sdk.metrics.export import InMemoryMetricReader

from src.app.core.config import settings
from src.app.core.observability import (
    RAG_LLM_GENERATION_MS,
    RAG_LLM_REQUESTS,
    RAG_LLM_TOKENS,
    RAG_LLM_TTFT_MS,
    get_metric_instruments,
    reset_observability_for_testing,
    setup_observability,
)
from src.rag.llm import GeminiBackend, OllamaBackend


@pytest.fixture(autouse=True)
def _cleanup_observability():
    """각 테스트 전후로 관측성 레지스트리를 깨끗하게 초기화합니다."""
    reset_observability_for_testing()
    orig_otel = settings.OTEL_ENABLED
    orig_metrics = settings.OTEL_METRICS_ENABLED
    yield
    reset_observability_for_testing()
    settings.OTEL_ENABLED = orig_otel
    settings.OTEL_METRICS_ENABLED = orig_metrics


def _collect_metric_data_points(
    reader: InMemoryMetricReader,
) -> dict[str, list[tuple[Any, dict[str, Any]]]]:
    """InMemoryMetricReader 로부터 수집된 메트릭 데이터 포인트를 {metric_name: [(value, attrs)]} 로 매핑합니다."""
    metrics_data = reader.get_metrics_data()
    result: dict[str, list[tuple[Any, dict[str, Any]]]] = {}
    if not metrics_data:
        return result
    for rm in metrics_data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                dp_list = result.setdefault(m.name, [])
                for dp in getattr(m.data, "data_points", []):
                    val = getattr(dp, "value", None)
                    if val is None:
                        val = getattr(dp, "sum", None)
                    dp_list.append((val, dict(dp.attributes)))
    return result


class DummyStreamResponse:
    """httpx.stream 컨텍스트 매니저를 흉내내는 가짜 스트림 응답 클래스."""

    def __init__(self, lines: list[str], status_code: int = 200, error: Exception | None = None):
        self._lines = lines
        self.status_code = status_code
        self._error = error

    def raise_for_status(self) -> None:
        if self._error:
            raise self._error
        if self.status_code >= 400:
            request = httpx.Request("POST", "http://fake/api/chat")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("HTTP Error", request=request, response=response)

    def iter_lines(self):
        yield from self._lines


@contextmanager
def _mock_httpx_stream(lines: list[str], status_code: int = 200, error: Exception | None = None):
    yield DummyStreamResponse(lines=lines, status_code=status_code, error=error)


def test_ollama_generate_all_metrics_recorded():
    """Ollama generate 호출 시 요청, 생성 시간, 입출력 토큰 지표가 정상 기록되는지 검증합니다."""
    reader = InMemoryMetricReader()
    setup_observability(custom_metric_exporter=reader)

    backend = OllamaBackend(base_url="http://localhost:11434", model="gemma4:e2b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "model": "gemma4:e2b",
        "message": {"role": "assistant", "content": "안녕하세요! 입찰 분석 결과입니다."},
        "prompt_eval_count": 42,
        "eval_count": 88,
        "done": True,
    }

    with patch("httpx.post", return_value=mock_resp):
        res = backend.generate("시스템 지시문", [{"role": "user", "content": "공고 알려줘"}])

    assert res == "안녕하세요! 입찰 분석 결과입니다."

    data = _collect_metric_data_points(reader)

    # 1. rag_llm_requests
    assert RAG_LLM_REQUESTS in data
    req_points = data[RAG_LLM_REQUESTS]
    assert len(req_points) == 1
    assert req_points[0][0] == 1
    assert req_points[0][1] == {
        "backend": "ollama",
        "model": "gemma4:e2b",
        "outcome": "success",
    }

    # 2. rag_llm_generation_ms
    assert RAG_LLM_GENERATION_MS in data
    gen_points = data[RAG_LLM_GENERATION_MS]
    assert len(gen_points) == 1
    assert gen_points[0][0] >= 0.0
    assert gen_points[0][1] == {"backend": "ollama", "model": "gemma4:e2b"}

    # 3. rag_llm_tokens
    assert RAG_LLM_TOKENS in data
    tok_points = data[RAG_LLM_TOKENS]
    assert len(tok_points) == 2
    tokens_by_dir = {p[1]["direction"]: p[0] for p in tok_points}
    assert tokens_by_dir["input"] == 42
    assert tokens_by_dir["output"] == 88
    for _, attrs in tok_points:
        assert attrs["backend"] == "ollama"
        assert attrs["model"] == "gemma4:e2b"

    # 4. generate 에서는 ttft 미기록
    assert RAG_LLM_TTFT_MS not in data


def test_ollama_stream_generate_all_four_metrics_and_ttft():
    """Ollama stream_generate 호출 시 TTFT를 포함한 4대 지표가 모두 기록되는지 검증합니다."""
    reader = InMemoryMetricReader()
    setup_observability(custom_metric_exporter=reader)

    backend = OllamaBackend(base_url="http://localhost:11434", model="gemma4:e2b")

    stream_chunks = [
        json.dumps({"message": {"content": "첫번째 "}, "done": False}),
        json.dumps({"message": {"content": "두번째"}, "done": False}),
        json.dumps({"done": True, "prompt_eval_count": 30, "eval_count": 50}),
    ]

    with patch("httpx.stream", return_value=_mock_httpx_stream(stream_chunks)):
        tokens = list(
            backend.stream_generate("시스템 지시문", [{"role": "user", "content": "질의"}])
        )

    assert tokens == ["첫번째 ", "두번째"]

    data = _collect_metric_data_points(reader)

    # 1. TTFT 기록 검증
    assert RAG_LLM_TTFT_MS in data
    ttft_points = data[RAG_LLM_TTFT_MS]
    assert len(ttft_points) == 1
    assert ttft_points[0][0] >= 0.0
    assert ttft_points[0][1] == {"backend": "ollama", "model": "gemma4:e2b"}

    # 2. Generation duration 검증
    assert RAG_LLM_GENERATION_MS in data
    gen_points = data[RAG_LLM_GENERATION_MS]
    assert len(gen_points) == 1
    assert gen_points[0][0] >= ttft_points[0][0]
    assert gen_points[0][1] == {"backend": "ollama", "model": "gemma4:e2b"}

    # 3. Requests counter 검증
    assert RAG_LLM_REQUESTS in data
    req_points = data[RAG_LLM_REQUESTS]
    assert len(req_points) == 1
    assert req_points[0][0] == 1
    assert req_points[0][1]["outcome"] == "success"

    # 4. Tokens counter 검증
    assert RAG_LLM_TOKENS in data
    tok_points = data[RAG_LLM_TOKENS]
    assert len(tok_points) == 2
    tokens_by_dir = {p[1]["direction"]: p[0] for p in tok_points}
    assert tokens_by_dir["input"] == 30
    assert tokens_by_dir["output"] == 50


def test_token_metrics_omitted_when_not_provided():
    """응답에 토큰 수가 누락되었을 때 추정하지 않고 토큰 지표를 생략하는지 검증합니다."""
    reader = InMemoryMetricReader()
    setup_observability(custom_metric_exporter=reader)

    backend = OllamaBackend(base_url="http://localhost:11434", model="gemma4:e2b")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # 토큰 필드가 전혀 없는 응답
    mock_resp.json.return_value = {
        "model": "gemma4:e2b",
        "message": {"role": "assistant", "content": "토큰 정보 없는 응답"},
        "done": True,
    }

    with patch("httpx.post", return_value=mock_resp):
        res = backend.generate("프롬프트", [{"role": "user", "content": "질문"}])

    assert res == "토큰 정보 없는 응답"

    data = _collect_metric_data_points(reader)
    assert RAG_LLM_TOKENS not in data
    assert RAG_LLM_REQUESTS in data
    assert RAG_LLM_GENERATION_MS in data


def test_exception_outcome_error_and_repropagation_generate():
    """generate 중 오류 발생 시 outcome=error 기록, generation_ms 1회 기록, 예외 재전파를 검증합니다."""
    reader = InMemoryMetricReader()
    setup_observability(custom_metric_exporter=reader)

    backend = OllamaBackend(base_url="http://localhost:11434", model="gemma4:e2b")

    with (
        patch("httpx.post", side_effect=httpx.ConnectError("연결 실패")),
        pytest.raises(httpx.ConnectError),
    ):
        backend.generate("프롬프트", [{"role": "user", "content": "질문"}])

    data = _collect_metric_data_points(reader)

    # requests 에 outcome=error 가 1회 기록되어야 함
    assert RAG_LLM_REQUESTS in data
    req_points = data[RAG_LLM_REQUESTS]
    assert len(req_points) == 1
    assert req_points[0][0] == 1
    assert req_points[0][1] == {
        "backend": "ollama",
        "model": "gemma4:e2b",
        "outcome": "error",
    }

    # generation_ms 가 1회 기록되어야 함 (중복 기록 없음)
    assert RAG_LLM_GENERATION_MS in data
    assert len(data[RAG_LLM_GENERATION_MS]) == 1

    # 토큰은 기록되지 않아야 함
    assert RAG_LLM_TOKENS not in data


def test_exception_outcome_error_and_repropagation_stream():
    """stream_generate 중 오류 발생 시 outcome=error 기록 및 예외 재전파를 검증합니다."""
    reader = InMemoryMetricReader()
    setup_observability(custom_metric_exporter=reader)

    backend = OllamaBackend(base_url="http://localhost:11434", model="gemma4:e2b")

    err = httpx.ConnectError("스트림 연결 끊김")
    with patch("httpx.stream", return_value=_mock_httpx_stream([], status_code=500, error=err)):
        gen = backend.stream_generate("프롬프트", [{"role": "user", "content": "질문"}])
        with pytest.raises(httpx.ConnectError):
            next(gen)

    data = _collect_metric_data_points(reader)

    assert RAG_LLM_REQUESTS in data
    req_points = data[RAG_LLM_REQUESTS]
    assert len(req_points) == 1
    assert req_points[0][1]["outcome"] == "error"

    assert RAG_LLM_GENERATION_MS in data
    assert len(data[RAG_LLM_GENERATION_MS]) == 1


def test_early_stream_termination_no_double_record():
    """소비자가 스트림을 조기 중단(break)해도 예외나 중복 기록이 발생하지 않음을 검증합니다."""
    reader = InMemoryMetricReader()
    setup_observability(custom_metric_exporter=reader)

    backend = OllamaBackend(base_url="http://localhost:11434", model="gemma4:e2b")

    stream_chunks = [
        json.dumps({"message": {"content": "첫 청크"}, "done": False}),
        json.dumps({"message": {"content": "두번째 청크"}, "done": False}),
        json.dumps({"done": True, "prompt_eval_count": 10, "eval_count": 20}),
    ]

    with patch("httpx.stream", return_value=_mock_httpx_stream(stream_chunks)):
        gen = backend.stream_generate("프롬프트", [{"role": "user", "content": "질문"}])
        first = next(gen)
        assert first == "첫 청크"
        gen.close()  # 조기 종료 (GeneratorExit 발생)

    data = _collect_metric_data_points(reader)

    # 첫 청크를 읽었으므로 TTFT는 기록됨
    assert RAG_LLM_TTFT_MS in data
    assert len(data[RAG_LLM_TTFT_MS]) == 1

    # 조기 중단 시 generation_ms 가 2회 이상 중복 기록되지 않음
    if RAG_LLM_GENERATION_MS in data:
        assert len(data[RAG_LLM_GENERATION_MS]) <= 1


def test_metrics_disabled_noop():
    """관측성이 비활성화되었을 때 계측 함수가 완전히 No-op 으로 동작하는지 검증합니다."""
    settings.OTEL_ENABLED = False
    settings.OTEL_METRICS_ENABLED = False
    setup_observability()

    instruments = get_metric_instruments()
    assert instruments["rag_llm_ttft_ms"] is None
    assert instruments["rag_llm_generation_ms"] is None
    assert instruments["rag_llm_tokens"] is None
    assert instruments["rag_llm_requests"] is None

    backend = OllamaBackend(base_url="http://localhost:11434", model="gemma4:e2b")
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": "비활성화 상태 정상 응답"},
        "prompt_eval_count": 10,
        "eval_count": 20,
    }

    with patch("httpx.post", return_value=mock_resp):
        res = backend.generate("프롬프트", [{"role": "user", "content": "질의"}])

    assert res == "비활성화 상태 정상 응답"


def test_gemini_backend_instrumentation():
    """GeminiBackend 의 generate 및 stream_generate 메트릭 계측을 검증합니다."""
    reader = InMemoryMetricReader()
    setup_observability(custom_metric_exporter=reader)

    backend = GeminiBackend(api_key="fake-key", model="gemini-1.5-flash")

    mock_client = MagicMock()
    backend._client = mock_client

    # 1. generate 검증
    mock_usage = MagicMock()
    mock_usage.prompt_token_count = 15
    mock_usage.candidates_token_count = 35

    mock_gen_response = MagicMock()
    mock_gen_response.text = "Gemini 생성 응답"
    mock_gen_response.usage_metadata = mock_usage
    mock_client.models.generate_content.return_value = mock_gen_response

    res = backend.generate("시스템 지시문", [{"role": "user", "content": "안녕"}])
    assert res == "Gemini 생성 응답"

    data = _collect_metric_data_points(reader)
    assert RAG_LLM_REQUESTS in data
    assert data[RAG_LLM_REQUESTS][0][1]["backend"] == "gemini"
    assert data[RAG_LLM_REQUESTS][0][1]["model"] == "gemini-1.5-flash"
    assert data[RAG_LLM_REQUESTS][0][1]["outcome"] == "success"

    tokens_by_dir = {p[1]["direction"]: p[0] for p in data[RAG_LLM_TOKENS]}
    assert tokens_by_dir["input"] == 15
    assert tokens_by_dir["output"] == 35

    # 2. stream_generate 검증
    mock_chunk1 = MagicMock()
    mock_chunk1.text = "스트림 토큰 1"
    mock_chunk1.usage_metadata = None

    mock_chunk2 = MagicMock()
    mock_chunk2.text = "스트림 토큰 2"
    mock_chunk2.usage_metadata = mock_usage

    mock_client.models.generate_content_stream.return_value = [mock_chunk1, mock_chunk2]

    stream_res = list(backend.stream_generate("시스템", [{"role": "user", "content": "테스트"}]))
    assert stream_res == ["스트림 토큰 1", "스트림 토큰 2"]

    data2 = _collect_metric_data_points(reader)
    assert RAG_LLM_TTFT_MS in data2
    assert any(p[1]["backend"] == "gemini" for p in data2[RAG_LLM_TTFT_MS])


def test_pii_and_query_excluded_from_metrics_attributes():
    """프롬프트, 사용자 질의, 응답 텍스트 등 PII가 속성 라벨에 일절 들어가지 않음을 검증합니다."""
    reader = InMemoryMetricReader()
    setup_observability(custom_metric_exporter=reader)

    backend = OllamaBackend(base_url="http://localhost:11434", model="gemma4:e2b")

    confidential_prompt = "비밀 시스템 프롬프트"
    confidential_query = "극비 사용자 질의"
    confidential_response = "비밀 응답 내용"

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {
        "message": {"content": confidential_response},
        "prompt_eval_count": 5,
        "eval_count": 10,
    }

    with patch("httpx.post", return_value=mock_resp):
        backend.generate(confidential_prompt, [{"role": "user", "content": confidential_query}])

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None

    all_attrs: list[dict[str, Any]] = []
    for rm in metrics_data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                for dp in getattr(m.data, "data_points", []):
                    all_attrs.append(dict(dp.attributes))

    for attrs in all_attrs:
        for k, v in attrs.items():
            val_str = str(v)
            key_str = str(k)
            assert confidential_prompt not in val_str
            assert confidential_query not in val_str
            assert confidential_response not in val_str
            assert confidential_prompt not in key_str
            assert confidential_query not in key_str
