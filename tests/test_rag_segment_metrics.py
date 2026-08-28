"""
tests/test_rag_segment_metrics.py

RAG 구간별 소요 시간(sql, vector, lexical, llm, total 등) 계측, 구조화 로깅,
응답 메타데이터 선택적 노출 및 계측 예외 복원력 회귀 테스트.
"""

from __future__ import annotations

import logging
from unittest.mock import patch

import pytest

from src.app.core.config import settings
from src.rag.engine import HybridRAGEngine
from src.rag.schemas import AnswerBundle


class DummyBackend:
    name = "dummy_backend"

    def generate(self, system_prompt: str, messages: list[dict]) -> str:
        return "테스트 답변입니다. Source [1] 근거."

    def stream_generate(self, system_prompt: str, messages: list[dict]):
        yield "테스트 "
        yield "답변입니다. "
        yield "Source [1] 근거."


def test_segment_metrics_flag_default_is_false():
    """응답 메타데이터 노출 플래그의 기본값은 False(비노출)이어야 합니다."""
    assert getattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", None) is False


def test_segment_metrics_hidden_by_default(monkeypatch):
    """기본 상태(플래그 False)에서는 bundle.segment_metrics 가 None 이어야 합니다."""
    monkeypatch.setattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", False)

    engine = HybridRAGEngine()
    engine._backend = DummyBackend()
    engine._backend_resolved = True

    bundle = engine.get_answer_sync("최근 공고 목록 알려줘")
    assert isinstance(bundle, AnswerBundle)
    assert bundle.segment_metrics is None


def test_segment_metrics_populated_when_flag_enabled(monkeypatch):
    """플래그 활성화 시 검색(sql, vector, lexical)과 생성(llm) 구간이 분리되어 채워져야 합니다."""
    monkeypatch.setattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", True)

    engine = HybridRAGEngine()
    engine._backend = DummyBackend()
    engine._backend_resolved = True

    bundle = engine.get_answer_sync("용역 입찰 통계 알려줘")
    assert isinstance(bundle, AnswerBundle)
    metrics = bundle.segment_metrics
    assert isinstance(metrics, dict)

    # 필수 최소 지표 확인
    required_keys = ["sql_ms", "vector_ms", "lexical_ms", "llm_ms", "total_ms"]
    for key in required_keys:
        assert key in metrics, f"필수 지표 {key} 누락"
        assert isinstance(metrics[key], (int, float))
        assert metrics[key] >= 0.0

    # 세부 구간 지표 확인
    assert "plan_ms" in metrics
    assert "guard_ms" in metrics
    assert "prepare_total_ms" in metrics
    assert metrics["total_ms"] >= 0.0


def test_segment_metrics_structured_logging(monkeypatch, caplog):
    """LATENCY_SEGMENT_LOGGING 활성화 시 구조화 로그에 모든 구간 지표가 남아야 합니다."""
    monkeypatch.setattr(settings, "LATENCY_SEGMENT_LOGGING", True)

    engine = HybridRAGEngine()
    engine._backend = DummyBackend()
    engine._backend_resolved = True

    with caplog.at_level(logging.INFO, logger="src.rag.engine"):
        engine.get_answer_sync("소프트웨어 유지보수 공고 검색")

    log_records = [r for r in caplog.records if "rag_engine_latency" in r.message]
    assert len(log_records) >= 1
    log_text = log_records[0].message
    assert "sql_ms=" in log_text
    assert "vector_ms=" in log_text
    assert "lexical_ms=" in log_text
    assert "llm_ms=" in log_text
    assert "total_ms=" in log_text


@pytest.mark.asyncio
async def test_segment_metrics_stream_tokens(monkeypatch):
    """스트리밍 응답에서 플래그 상태에 따른 done 이벤트 segment_metrics 포함 여부를 검증합니다."""
    # 1. 플래그 비활성
    monkeypatch.setattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", False)
    engine = HybridRAGEngine()
    engine._backend = DummyBackend()
    engine._backend_resolved = True

    events = [event async for event in engine.stream_tokens("스트리밍 테스트")]
    done_events = [e for e in events if e.get("type") == "done"]
    assert len(done_events) == 1
    assert "segment_metrics" not in done_events[0]

    # 2. 플래그 활성
    monkeypatch.setattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", True)
    events_enabled = [event async for event in engine.stream_tokens("스트리밍 테스트")]
    done_events_enabled = [e for e in events_enabled if e.get("type") == "done"]
    assert len(done_events_enabled) == 1
    stream_metrics = done_events_enabled[0].get("segment_metrics")
    assert isinstance(stream_metrics, dict)
    assert "sql_ms" in stream_metrics
    assert "vector_ms" in stream_metrics
    assert "lexical_ms" in stream_metrics
    assert "llm_ms" in stream_metrics
    assert "total_ms" in stream_metrics


def test_instrumentation_exception_resilience(monkeypatch, caplog):
    """계측 로직 내부에서 예외가 발생해도 본 RAG 답변 경로는 정상 동작해야 합니다."""
    monkeypatch.setattr(settings, "RAG_EXPOSE_SEGMENT_METRICS", True)

    engine = HybridRAGEngine()
    engine._backend = DummyBackend()
    engine._backend_resolved = True

    with (
        patch("src.rag.engine.time.perf_counter", side_effect=RuntimeError("시계 오류")),
        caplog.at_level(logging.WARNING, logger="src.rag.engine"),
    ):
        bundle = engine.get_answer_sync("예외 안전성 검증")
        assert isinstance(bundle, AnswerBundle)
        assert bundle.answer is not None
