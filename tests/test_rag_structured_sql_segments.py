"""정형 검색 SQL 구간 계측의 비노출·귀속 계약을 검증합니다."""

from __future__ import annotations

from src.app.core.config import settings
from src.rag import structured_data


def test_latency_record_is_inert_when_flag_is_off(monkeypatch):
    monkeypatch.setattr(settings, "LATENCY_SEGMENT_LOGGING", False)

    record = structured_data._open_latency_record()

    assert record is None
    assert structured_data.get_structured_latency_segments() is None


def test_latency_record_contains_segments_cursor_total_and_residual(monkeypatch):
    monkeypatch.setattr(settings, "LATENCY_SEGMENT_LOGGING", True)
    record = structured_data._open_latency_record()
    assert record is not None
    try:
        structured_data._record_segment("cache_lookup_ms", 2.0)
        structured_data._record_segment("corrupted_probe_ms", 3.0)
        structured_data._before_cursor_execute(None, None, "", None, None, False)
        structured_data._after_cursor_execute(None, None, "", None, None, False)
    finally:
        structured_data._close_latency_record(record)

    result = structured_data.get_structured_latency_segments()
    assert result is not None
    assert "cache_lookup_ms" in result["segments"]
    assert "corrupted_probe_ms" in result["segments"]
    assert "cursor_ms" in result
    assert "cursor_count" in result
    assert "residual_ms" in result
    assert result["cursor_ms"] <= result["total_ms"]


def test_measurement_exception_does_not_escape(monkeypatch):
    monkeypatch.setattr(settings, "LATENCY_SEGMENT_LOGGING", True)

    @structured_data._measure_call("failing_phase")
    def failing_phase():
        raise RuntimeError("원래 경로 예외")

    record = structured_data._open_latency_record()
    assert record is not None
    try:
        try:
            failing_phase()
        except RuntimeError:
            pass
        else:
            raise AssertionError("원래 함수 예외가 사라지면 안 됩니다")
    finally:
        structured_data._close_latency_record(record)

    result = structured_data.get_structured_latency_segments()
    assert result is not None
    assert "failing_phase_1" in result["segments"]


def test_cursor_listener_registration_is_idempotent(monkeypatch):
    monkeypatch.setattr(settings, "LATENCY_SEGMENT_LOGGING", True)
    monkeypatch.setattr(structured_data, "_listeners_registered", False)
    structured_data._register_cursor_listeners()
    structured_data._register_cursor_listeners()
    assert structured_data._listeners_registered is True
