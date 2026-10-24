"""tests/test_observability_metrics_path.py

opentelemetry-exporter-otlp-proto-http 1.45.1 에서 제거된 _append_metrics_path 를
같은 동작의 내장 헬퍼로 대체한 뒤, 1.44.0 과 동일한 OTLP 메트릭 경로 규칙을 검증합니다.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from opentelemetry.sdk.metrics.export import MetricExporter, MetricExportResult, MetricsData
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from src.app.core.config import settings
from src.app.core.observability import (
    _append_metrics_path,
    reset_observability_for_testing,
    setup_observability,
)


@pytest.fixture(autouse=True)
def _reset_observability() -> Iterator[None]:
    reset_observability_for_testing()
    yield
    reset_observability_for_testing()


def test_append_metrics_path_without_trailing_slash() -> None:
    assert _append_metrics_path("http://c:4318") == "http://c:4318/v1/metrics"


def test_append_metrics_path_with_trailing_slash() -> None:
    assert _append_metrics_path("http://c:4318/") == "http://c:4318/v1/metrics"


@pytest.mark.parametrize(
    ("traces_endpoint", "expected"),
    [
        ("http://c:4318/v1/traces", "http://c:4318/v1/metrics"),
        ("http://c:4318/v1/traces/", "http://c:4318/v1/metrics"),
    ],
)
def test_setup_rewrites_traces_endpoint_to_metrics(
    monkeypatch: pytest.MonkeyPatch,
    traces_endpoint: str,
    expected: str,
) -> None:
    captured: dict[str, str | None] = {}

    class _CapturingMetricExporter(MetricExporter):
        def __init__(self, endpoint: str | None = None) -> None:
            super().__init__()
            captured["endpoint"] = endpoint

        def export(
            self,
            metrics_data: MetricsData,
            timeout_millis: float = 10000,
            **kwargs: object,
        ) -> MetricExportResult:
            return MetricExportResult.SUCCESS

        def force_flush(self, timeout_millis: float = 10000) -> bool:
            return True

        def shutdown(self, timeout_millis: float = 30000, **kwargs: object) -> None:
            return None

    monkeypatch.setattr(settings, "OTEL_ENABLED", True)
    monkeypatch.setattr(settings, "OTEL_EXPORTER_TYPE", "otlp")
    monkeypatch.setattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", traces_endpoint)
    monkeypatch.setattr(
        "opentelemetry.exporter.otlp.proto.http.metric_exporter.OTLPMetricExporter",
        _CapturingMetricExporter,
    )

    setup_observability(custom_exporter=InMemorySpanExporter())

    assert captured["endpoint"] == expected
