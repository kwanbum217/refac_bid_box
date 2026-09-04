"""OpenTelemetry 분산 추적 및 관측성 모듈.

HTTP(ASGI/FastAPI), DB(SQLAlchemy), Arq 워커 태스크의 지연과 오류를 계측합니다.
기본값은 비활성화(OTEL_ENABLED=False)이며, 꺼져 있을 때 계측 비용이 발생하지 않습니다.
특정 벤더 SDK 없이 표준 OpenTelemetry API/SDK 및 OTLP Exporter를 사용합니다.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from opentelemetry import context, trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    ConsoleSpanExporter,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.sampling import TraceIdRatioBased
from opentelemetry.trace import Status, StatusCode
from sqlalchemy.engine import Engine

from src.app.core.config import get_app_version, settings

logger = logging.getLogger(__name__)

# 비밀 정보 노출 방지를 위한 민감 키 패턴 목록
SENSITIVE_KEY_PATTERNS: tuple[str, ...] = (
    "password",
    "secret",
    "token",
    "key",
    "auth",
    "credential",
    "cookie",
    "session",
    "private",
)


def _is_sensitive_key(key: str) -> bool:
    """속성 키가 민감 정보를 가리키는지 확인합니다."""
    lowered = key.lower()
    return any(pattern in lowered for pattern in SENSITIVE_KEY_PATTERNS)


class SafeSpanExporter(SpanExporter):
    """수집기 장애 시 애플리케이션 장애 전파를 차단하고 상태를 관측 가능하게 기록하는 래퍼."""

    def __init__(self, delegate: SpanExporter) -> None:
        self._delegate = delegate
        self.spans_exported: int = 0
        self.export_errors: int = 0
        self.last_export_error: str | None = None
        self.last_export_at: str | None = None

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        try:
            result = self._delegate.export(spans)
            if result == SpanExportResult.SUCCESS:
                self.spans_exported += len(spans)
                self.last_export_at = datetime.now(UTC).isoformat()
                return result
            self.export_errors += len(spans)
            self.last_export_error = f"SpanExportResult: {result}"
            logger.warning("OpenTelemetry 내보내기 실패: %s", self.last_export_error)
            return result
        except Exception as exc:
            self.export_errors += len(spans)
            self.last_export_error = f"{type(exc).__name__}: {exc}"
            logger.warning("OpenTelemetry 내보내기 예외: %s", self.last_export_error)
            return SpanExportResult.FAILURE

    def shutdown(self) -> None:
        try:
            self._delegate.shutdown()
        except Exception as exc:
            logger.warning("OpenTelemetry exporter shutdown 예외: %s", exc)

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        try:
            return self._delegate.force_flush(timeout_millis)
        except Exception as exc:
            logger.warning("OpenTelemetry exporter force_flush 예외: %s", exc)
            return False


@dataclass
class ObservabilityRegistry:
    enabled: bool = False
    initialized: bool = False
    service_name: str = ""
    exporter_type: str = "none"
    endpoint: str = ""
    safe_exporter: SafeSpanExporter | None = None
    tracer_provider: TracerProvider | None = None
    fastapi_instrumented: bool = False
    sqlalchemy_instrumented: bool = False
    arq_instrumented: bool = False


_registry = ObservabilityRegistry()


def is_otel_enabled() -> bool:
    """OpenTelemetry 활성화 여부를 반환합니다."""
    return _registry.enabled


def get_tracer_provider() -> TracerProvider | None:
    """현재 등록된 TracerProvider 를 반환합니다."""
    return _registry.tracer_provider


def setup_observability(
    app: FastAPI | None = None,
    engine: Engine | None = None,
    custom_exporter: SpanExporter | None = None,
) -> None:
    """OpenTelemetry 분산 추적 계측을 초기화하고 배선합니다.

    settings.OTEL_ENABLED 가 False 일 때는 어떤 자원도 할당하지 않고 즉시 반환하여
    런타임 오버헤드를 0 으로 유지합니다.
    """
    if not settings.OTEL_ENABLED and custom_exporter is None:
        _registry.enabled = False
        _registry.initialized = True
        return

    _registry.enabled = True
    _registry.service_name = settings.OTEL_SERVICE_NAME
    _registry.exporter_type = settings.OTEL_EXPORTER_TYPE
    _registry.endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT

    if not _registry.initialized or _registry.tracer_provider is None:
        resource = Resource.create(
            {
                "service.name": settings.OTEL_SERVICE_NAME,
                "service.version": get_app_version(),
            }
        )
        sampler = TraceIdRatioBased(settings.OTEL_SAMPLING_RATIO)
        provider = TracerProvider(resource=resource, sampler=sampler)

        # Exporter 설정
        safe_exporter: SafeSpanExporter | None = None
        if custom_exporter is not None:
            safe_exporter = SafeSpanExporter(custom_exporter)
            provider.add_span_processor(SimpleSpanProcessor(safe_exporter))
        elif settings.OTEL_EXPORTER_TYPE == "console":
            safe_exporter = SafeSpanExporter(ConsoleSpanExporter())
            provider.add_span_processor(SimpleSpanProcessor(safe_exporter))
        elif settings.OTEL_EXPORTER_TYPE == "otlp":
            try:
                from opentelemetry.exporter.otlp.proto.http.trace_exporter import (
                    OTLPSpanExporter,
                )

                endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
                raw_exporter = (
                    OTLPSpanExporter(endpoint=endpoint) if endpoint else OTLPSpanExporter()
                )
                safe_exporter = SafeSpanExporter(raw_exporter)
                # 애플리케이션 지연 방지를 위해 BatchSpanProcessor 사용
                provider.add_span_processor(BatchSpanProcessor(safe_exporter))
            except Exception as exc:
                logger.warning("OTLP Exporter 초기화 실패: %s", exc)

        _registry.safe_exporter = safe_exporter
        _registry.tracer_provider = provider
        trace.set_tracer_provider(provider)
        _registry.initialized = True

    provider = _registry.tracer_provider

    # FastAPI 계측 배선
    if app is not None and not _registry.fastapi_instrumented:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor().instrument_app(
                app,
                tracer_provider=provider,
                excluded_urls="api/v1/health/live",
            )
            _registry.fastapi_instrumented = True
        except Exception as exc:
            logger.warning("FastAPI 계측 배선 실패: %s", exc)

    # SQLAlchemy 계측 배선
    if engine is not None and not _registry.sqlalchemy_instrumented:
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().instrument(
                engine=engine,
                tracer_provider=provider,
                enable_commenter=False,
            )
            _registry.sqlalchemy_instrumented = True
        except Exception as exc:
            logger.warning("SQLAlchemy 계측 배선 실패: %s", exc)


async def arq_on_job_start(ctx: dict[str, Any]) -> None:
    """Arq 워커 작업 시작 시 span 을 생성하고 컨텍스트에 바인딩합니다."""
    if not _registry.enabled or not _registry.tracer_provider:
        return
    job_id = str(ctx.get("job_id", "unknown"))
    job_try = int(ctx.get("job_try", 1))
    tracer = trace.get_tracer("refac_bid_box.arq", tracer_provider=_registry.tracer_provider)
    span = tracer.start_span(f"arq.job:{job_id}")
    span.set_attribute("task.id", job_id)
    span.set_attribute("task.try", job_try)
    span.set_attribute("task.system", "arq")
    ctx["_otel_span"] = span
    ctx["_otel_token"] = context.attach(trace.set_span_in_context(span))
    _registry.arq_instrumented = True


async def arq_on_job_end(ctx: dict[str, Any]) -> None:
    """Arq 워커 작업 종료 시 span 을 정상 완료하거나 예외 상태를 기록하고 닫습니다."""
    if not _registry.enabled:
        return
    token = ctx.pop("_otel_token", None)
    span: trace.Span | None = ctx.pop("_otel_span", None)
    try:
        if token is not None:
            context.detach(token)
    except Exception as exc:
        # detach 실패를 삼키지 않고 남깁니다. 이전 구현은 debug 로 숨겨
        # 존재하지 않는 API 호출이 매번 실패하는 것을 가렸습니다.
        logger.warning("Arq 컨텍스트 detach 실패: %s", exc)
    finally:
        # detach 결과와 무관하게 span 은 반드시 종료합니다. 종료하지 않으면
        # 그 작업의 span 이 누수되어 이후 계측이 어긋납니다.
        if span is not None:
            span.set_status(Status(StatusCode.OK))
            span.end()


@contextmanager
def trace_worker_task(
    task_name: str,
    task_id: str | None = None,
    **attributes: Any,
) -> Iterator[trace.Span | None]:
    """워커 태스크 및 작업 구간을 계측하는 컨텍스트 매니저입니다.

    비활성화 상태(OTEL_ENABLED=False)에서는 아무 비용 없이 즉시 제어를 넘깁니다.
    """
    if not _registry.enabled:
        yield None
        return

    tracer = trace.get_tracer("refac_bid_box.arq", tracer_provider=_registry.tracer_provider)
    with tracer.start_as_current_span(f"arq.task:{task_name}") as span:
        span.set_attribute("task.name", task_name)
        span.set_attribute("task.system", "arq")
        if task_id is not None:
            span.set_attribute("task.id", str(task_id))
        for key, value in attributes.items():
            if not _is_sensitive_key(key):
                span.set_attribute(f"task.param.{key}", str(value))
        try:
            yield span
            span.set_status(Status(StatusCode.OK))
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def get_observability_status() -> dict[str, Any]:
    """현재 OpenTelemetry 계측 및 내보내기 상태를 반환합니다."""
    safe_exporter = _registry.safe_exporter
    return {
        "enabled": _registry.enabled,
        "initialized": _registry.initialized,
        "service_name": _registry.service_name,
        "exporter_type": _registry.exporter_type,
        "endpoint": _registry.endpoint,
        "spans_exported": safe_exporter.spans_exported if safe_exporter else 0,
        "export_errors": safe_exporter.export_errors if safe_exporter else 0,
        "last_export_error": safe_exporter.last_export_error if safe_exporter else None,
        "last_export_at": safe_exporter.last_export_at if safe_exporter else None,
        "instrumentations": {
            "fastapi": _registry.fastapi_instrumented,
            "sqlalchemy": _registry.sqlalchemy_instrumented,
            "arq": _registry.arq_instrumented,
        },
    }


def reset_observability_for_testing() -> None:
    """테스트 격리를 위해 계측 상태를 초기화합니다."""
    if _registry.fastapi_instrumented:
        try:
            from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor

            FastAPIInstrumentor().uninstrument()
        except Exception as exc:
            logger.debug("FastAPI uninstrument 예외: %s", exc)
    if _registry.sqlalchemy_instrumented:
        try:
            from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor

            SQLAlchemyInstrumentor().uninstrument()
        except Exception as exc:
            logger.debug("SQLAlchemy uninstrument 예외: %s", exc)
    _registry.enabled = False
    _registry.initialized = False
    _registry.service_name = ""
    _registry.exporter_type = "none"
    _registry.endpoint = ""
    _registry.safe_exporter = None
    _registry.tracer_provider = None
    _registry.fastapi_instrumented = False
    _registry.sqlalchemy_instrumented = False
    _registry.arq_instrumented = False
