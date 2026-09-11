"""OpenTelemetry 분산 추적 및 관측성 모듈.

HTTP(ASGI/FastAPI), DB(SQLAlchemy), Arq 워커 태스크의 지연과 오류를 계측합니다.
기본값은 비활성화(OTEL_ENABLED=False)이며, 꺼져 있을 때 계측 비용이 발생하지 않습니다.
특정 벤더 SDK 없이 표준 OpenTelemetry API/SDK 및 OTLP Exporter를 사용합니다.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Iterator, Sequence
from contextlib import contextmanager, suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from fastapi import FastAPI
from opentelemetry import context, metrics, trace
from opentelemetry.metrics import Counter, Histogram
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    ConsoleMetricExporter,
    MetricExporter,
    MetricExportResult,
    MetricReader,
    MetricsData,
    PeriodicExportingMetricReader,
)
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
from sqlalchemy import event
from sqlalchemy.engine import Engine
from starlette.types import ASGIApp, Receive, Scope, Send

from src.app.core.config import get_app_version, settings

logger = logging.getLogger(__name__)

# OpenTelemetry 표준 시맨틱 컨벤션 메트릭 명칭 및 단위
HTTP_SERVER_REQUEST_DURATION: str = "http.server.request.duration"
DB_CLIENT_OPERATION_DURATION: str = "db.client.operation.duration"
HTTP_SERVER_REQUEST_COUNT: str = "http.server.request.count"

# DB 질의 연산 카디널리티 관리를 위한 표준 SQL 명령어 허용 목록
KNOWN_DB_OPERATIONS: frozenset[str] = frozenset(
    {
        "SELECT",
        "INSERT",
        "UPDATE",
        "DELETE",
        "COMMIT",
        "ROLLBACK",
        "BEGIN",
        "CREATE",
        "ALTER",
        "DROP",
        "PRAGMA",
        "SHOW",
        "SET",
    }
)

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


class SafeMetricExporter(MetricExporter):
    """수집기 장애 시 애플리케이션 장애 전파를 차단하고 메트릭 내보내기 상태를 기록하는 래퍼."""

    def __init__(self, delegate: MetricExporter) -> None:
        super().__init__(
            preferred_temporality=getattr(delegate, "_preferred_temporality", None),
            preferred_aggregation=getattr(delegate, "_preferred_aggregation", None),
        )
        self._delegate = delegate
        self.metrics_exported: int = 0
        self.export_errors: int = 0
        self.last_export_error: str | None = None
        self.last_export_at: str | None = None

    def export(
        self,
        metrics_data: MetricsData,
        timeout_millis: float = 10_000,
        **kwargs: Any,
    ) -> MetricExportResult:
        try:
            result = self._delegate.export(metrics_data, timeout_millis=timeout_millis, **kwargs)
            if result == MetricExportResult.SUCCESS:
                self.metrics_exported += 1
                self.last_export_at = datetime.now(UTC).isoformat()
                return result
            self.export_errors += 1
            self.last_export_error = f"MetricExportResult: {result}"
            logger.warning("OpenTelemetry 메트릭 내보내기 실패: %s", self.last_export_error)
            return result
        except Exception as exc:
            self.export_errors += 1
            self.last_export_error = f"{type(exc).__name__}: {exc}"
            logger.warning("OpenTelemetry 메트릭 내보내기 예외: %s", self.last_export_error)
            return MetricExportResult.FAILURE

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        try:
            self._delegate.shutdown(timeout_millis=timeout_millis, **kwargs)
        except Exception as exc:
            logger.warning("OpenTelemetry metric exporter shutdown 예외: %s", exc)

    def force_flush(self, timeout_millis: float = 10_000) -> bool:
        try:
            return self._delegate.force_flush(timeout_millis=timeout_millis)
        except Exception as exc:
            logger.warning("OpenTelemetry metric exporter force_flush 예외: %s", exc)
            return False


def _extract_route_template(scope: Scope) -> str:
    """경로 템플릿을 추출합니다.

    실제 경로 값(ID, 파라미터 등) 대신 /api/v1/bids/{bid_id} 형태의 템플릿을 반환하여
    카디널리티 폭발을 방지합니다. 매칭되지 않은 경로는 'unmatched' 로 분류합니다.
    """
    route = scope.get("route")
    if route and hasattr(route, "path") and isinstance(route.path, str):
        return route.path
    return "unmatched"


def _record_http_metrics(scope: Scope, status_code: int, duration_seconds: float) -> None:
    """HTTP 요청 지연 및 요청 수 메트릭을 기록합니다."""
    if not _registry.metrics_enabled:
        return
    route_template = _extract_route_template(scope)
    method = str(scope.get("method", "UNKNOWN")).upper()

    attrs: dict[str, Any] = {
        "http.route": route_template,
        "http.request.method": method,
        "http.response.status_code": status_code,
    }
    # 민감 키 마스킹 검증 (추가 방어)
    safe_attrs = {k: v for k, v in attrs.items() if not _is_sensitive_key(str(k))}

    if _registry.http_duration_histogram is not None:
        _registry.http_duration_histogram.record(duration_seconds, safe_attrs)
    if _registry.http_requests_counter is not None:
        _registry.http_requests_counter.add(1, safe_attrs)


class OTelMetricsMiddleware:
    """HTTP 요청 지연 및 요청 수를 계측하는 ASGI 미들웨어."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not is_metrics_enabled():
            await self.app(scope, receive, send)
            return

        status_code = 500

        async def send_wrapper(message: Any) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 200)
            await send(message)

        start_time = time.perf_counter()
        try:
            await self.app(scope, receive, send_wrapper)
        finally:
            duration = time.perf_counter() - start_time
            try:
                _record_http_metrics(scope, status_code, duration)
            except Exception as exc:
                logger.warning("HTTP 메트릭 기록 예외: %s", exc)


def _extract_db_operation(statement: str | None) -> str:
    """SQL 문에서 연산자(SELECT, INSERT 등)를 추출하여 저카디널리티 라벨을 보장합니다."""
    if not statement:
        return "UNKNOWN"
    first_token = statement.strip().split()[0].upper()
    return first_token if first_token in KNOWN_DB_OPERATIONS else "OTHER"


def _before_cursor_execute(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    with suppress(Exception):
        conn.info["_otel_db_start"] = time.perf_counter()


def _after_cursor_execute(
    conn: Any,
    cursor: Any,
    statement: str,
    parameters: Any,
    context: Any,
    executemany: bool,
) -> None:
    try:
        start = conn.info.pop("_otel_db_start", None)
        if (
            start is not None
            and _registry.metrics_enabled
            and _registry.db_duration_histogram is not None
        ):
            duration = time.perf_counter() - start
            op = _extract_db_operation(statement)
            dialect = getattr(getattr(conn, "dialect", None), "name", "unknown")
            attrs = {"db.system": dialect, "db.operation": op}
            safe_attrs = {k: v for k, v in attrs.items() if not _is_sensitive_key(str(k))}
            _registry.db_duration_histogram.record(duration, safe_attrs)
    except Exception as exc:
        logger.warning("DB 메트릭 기록 예외: %s", exc)


def _handle_error(exception_context: Any) -> None:
    try:
        conn = getattr(exception_context, "connection", None)
        start = conn.info.pop("_otel_db_start", None) if conn and hasattr(conn, "info") else None
        if (
            start is not None
            and _registry.metrics_enabled
            and _registry.db_duration_histogram is not None
        ):
            duration = time.perf_counter() - start
            statement = getattr(exception_context, "statement", None)
            op = _extract_db_operation(statement)
            dialect = getattr(getattr(conn, "dialect", None), "name", "unknown")
            attrs = {"db.system": dialect, "db.operation": op}
            safe_attrs = {k: v for k, v in attrs.items() if not _is_sensitive_key(str(k))}
            _registry.db_duration_histogram.record(duration, safe_attrs)
    except Exception as exc:
        logger.warning("DB 에러 메트릭 기록 예외: %s", exc)


def _attach_db_metrics_listeners(engine: Engine) -> None:
    """SQLAlchemy Engine 에 DB 쿼리 지연 메트릭 리스너를 등록합니다."""
    if not event.contains(engine, "before_cursor_execute", _before_cursor_execute):
        event.listen(engine, "before_cursor_execute", _before_cursor_execute)
    if not event.contains(engine, "after_cursor_execute", _after_cursor_execute):
        event.listen(engine, "after_cursor_execute", _after_cursor_execute)
    if not event.contains(engine, "handle_error", _handle_error):
        event.listen(engine, "handle_error", _handle_error)


def _detach_db_metrics_listeners(engine: Engine) -> None:
    """SQLAlchemy Engine 에 등록된 DB 쿼리 지연 메트릭 리스너를 해제합니다."""
    if event.contains(engine, "before_cursor_execute", _before_cursor_execute):
        event.remove(engine, "before_cursor_execute", _before_cursor_execute)
    if event.contains(engine, "after_cursor_execute", _after_cursor_execute):
        event.remove(engine, "after_cursor_execute", _after_cursor_execute)
    if event.contains(engine, "handle_error", _handle_error):
        event.remove(engine, "handle_error", _handle_error)


@dataclass
class ObservabilityRegistry:
    enabled: bool = False
    metrics_enabled: bool = False
    initialized: bool = False
    service_name: str = ""
    exporter_type: str = "none"
    endpoint: str = ""
    safe_exporter: SafeSpanExporter | None = None
    safe_metric_exporter: SafeMetricExporter | None = None
    tracer_provider: TracerProvider | None = None
    meter_provider: MeterProvider | None = None
    http_duration_histogram: Histogram | None = None
    db_duration_histogram: Histogram | None = None
    http_requests_counter: Counter | None = None
    fastapi_instrumented: bool = False
    sqlalchemy_instrumented: bool = False
    arq_instrumented: bool = False
    sqlalchemy_metrics_engine: Engine | None = None


_registry = ObservabilityRegistry()


def is_otel_enabled() -> bool:
    """OpenTelemetry 활성화 여부를 반환합니다."""
    return _registry.enabled


def is_metrics_enabled() -> bool:
    """OpenTelemetry 메트릭 활성화 여부를 반환합니다."""
    return _registry.metrics_enabled


def get_tracer_provider() -> TracerProvider | None:
    """현재 등록된 TracerProvider 를 반환합니다."""
    return _registry.tracer_provider


def get_meter_provider() -> MeterProvider | None:
    """현재 등록된 MeterProvider 를 반환합니다."""
    return _registry.meter_provider


def get_metric_instruments() -> dict[str, Any]:
    """등록된 세 가지 핵심 메트릭 계측기 딕셔너리를 반환합니다."""
    return {
        "http_request_duration": _registry.http_duration_histogram,
        "db_operation_duration": _registry.db_duration_histogram,
        "http_request_count": _registry.http_requests_counter,
    }


def setup_observability(
    app: FastAPI | None = None,
    engine: Engine | None = None,
    custom_exporter: SpanExporter | None = None,
    custom_metric_exporter: MetricExporter | MetricReader | None = None,
) -> None:
    """OpenTelemetry 분산 추적 및 메트릭 계측을 초기화하고 배선합니다.

    settings.OTEL_ENABLED 가 False 일 때는 어떤 자원도 할당하지 않고 즉시 반환하여
    런타임 오버헤드를 0 으로 유지합니다.
    """
    if not settings.OTEL_ENABLED and custom_exporter is None and custom_metric_exporter is None:
        _registry.enabled = False
        _registry.metrics_enabled = False
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

    # MeterProvider 및 메트릭 계측 초기화
    should_enable_metrics = settings.is_metrics_enabled or (custom_metric_exporter is not None)
    if should_enable_metrics and _registry.meter_provider is None:
        resource = Resource.create(
            {
                "service.name": settings.OTEL_SERVICE_NAME,
                "service.version": get_app_version(),
            }
        )
        safe_metric_exporter: SafeMetricExporter | None = None
        metric_readers: list[MetricReader] = []

        if custom_metric_exporter is not None:
            if isinstance(custom_metric_exporter, MetricReader):
                metric_readers.append(custom_metric_exporter)
            else:
                safe_metric_exporter = SafeMetricExporter(custom_metric_exporter)
                metric_readers.append(
                    PeriodicExportingMetricReader(
                        safe_metric_exporter,
                        export_interval_millis=settings.OTEL_METRIC_EXPORT_INTERVAL_MILLIS,
                    )
                )
        elif settings.OTEL_EXPORTER_TYPE == "console":
            safe_metric_exporter = SafeMetricExporter(ConsoleMetricExporter())
            metric_readers.append(
                PeriodicExportingMetricReader(
                    safe_metric_exporter,
                    export_interval_millis=settings.OTEL_METRIC_EXPORT_INTERVAL_MILLIS,
                )
            )
        elif settings.OTEL_EXPORTER_TYPE == "otlp":
            try:
                from opentelemetry.exporter.otlp.proto.http.metric_exporter import (
                    OTLPMetricExporter,
                    _append_metrics_path,
                )

                endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
                metric_endpoint: str | None = None
                if endpoint:
                    if endpoint.endswith("/v1/traces"):
                        metric_endpoint = endpoint[:-10] + "/v1/metrics"
                    elif endpoint.endswith("/v1/traces/"):
                        metric_endpoint = endpoint[:-11] + "/v1/metrics"
                    elif not endpoint.endswith("/v1/metrics"):
                        metric_endpoint = _append_metrics_path(endpoint)
                    else:
                        metric_endpoint = endpoint

                raw_metric_exporter = (
                    OTLPMetricExporter(endpoint=metric_endpoint)
                    if metric_endpoint
                    else OTLPMetricExporter()
                )
                safe_metric_exporter = SafeMetricExporter(raw_metric_exporter)
                metric_readers.append(
                    PeriodicExportingMetricReader(
                        safe_metric_exporter,
                        export_interval_millis=settings.OTEL_METRIC_EXPORT_INTERVAL_MILLIS,
                    )
                )
            except Exception as exc:
                logger.warning("OTLP Metric Exporter 초기화 실패: %s", exc)

        meter_provider = MeterProvider(resource=resource, metric_readers=metric_readers)
        metrics.set_meter_provider(meter_provider)

        meter = meter_provider.get_meter("refac_bid_box", get_app_version())

        # 3가지 핵심 계측기 등록 (OpenTelemetry 시맨틱 컨벤션 준수)
        _registry.http_duration_histogram = meter.create_histogram(
            name=HTTP_SERVER_REQUEST_DURATION,
            description="Duration of HTTP server requests in seconds.",
            unit="s",
        )
        _registry.db_duration_histogram = meter.create_histogram(
            name=DB_CLIENT_OPERATION_DURATION,
            description="Duration of database client operations in seconds.",
            unit="s",
        )
        _registry.http_requests_counter = meter.create_counter(
            name=HTTP_SERVER_REQUEST_COUNT,
            description="Total count of HTTP server requests.",
            unit="{request}",
        )

        _registry.safe_metric_exporter = safe_metric_exporter
        _registry.meter_provider = meter_provider
        _registry.metrics_enabled = True

    _registry.initialized = True
    provider = _registry.tracer_provider

    # FastAPI 계측 배선 (Tracer)
    if app is not None and not _registry.fastapi_instrumented and provider is not None:
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

    # FastAPI 메트릭 미들웨어 배선
    if app is not None and _registry.metrics_enabled:
        user_middlewares = getattr(app, "user_middleware", [])
        if not any(m.cls == OTelMetricsMiddleware for m in user_middlewares):
            app.add_middleware(OTelMetricsMiddleware)

    # SQLAlchemy 계측 배선 (Tracer)
    if engine is not None and not _registry.sqlalchemy_instrumented and provider is not None:
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

    # SQLAlchemy DB 질의 지연 메트릭 배선
    if engine is not None and _registry.metrics_enabled:
        _attach_db_metrics_listeners(engine)
        _registry.sqlalchemy_metrics_engine = engine


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


def _resolve_cancel_reason(ctx: dict[str, Any] | None = None) -> str:
    """작업 취소 원인을 판별합니다.

    정상 종료(워커 셧다운으로 인한 배경 태스크 취소)와 사용자 abort 등을 구분합니다.
    asyncio.CancelledError 는 대개 인자를 갖지 않으므로 예외 문자열을 파싱하지 않고,
    워커가 ctx 에 넣는 worker_shutting_down 과 is_background_catchup 만 본다.
    """
    if isinstance(ctx, dict):
        if ctx.get("worker_shutting_down") or ctx.get("shutdown"):
            return "worker_shutdown"
        if ctx.get("cancel_reason"):
            return str(ctx["cancel_reason"])
        if ctx.get("is_background_catchup"):
            return "worker_shutdown"

    return "aborted"


async def arq_on_job_end(ctx: dict[str, Any]) -> None:
    """Arq 워커 작업 종료 시 span 을 정상 완료하거나 예외 상태를 기록하고 닫습니다."""
    if not _registry.enabled:
        return
    token = ctx.pop("_otel_token", None)
    span: trace.Span | None = ctx.pop("_otel_span", None)
    cancelled = ctx.pop("_task_cancelled", False)
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
            # 이미 ERROR 로 기록되었거나 취소된 span 은 그대로 두고, 정상 완료인 경우에만 OK 로 설정
            status = getattr(span, "status", None)
            status_code = getattr(status, "status_code", None)
            span_cancelled = getattr(span, "_task_cancelled", False)
            if not cancelled and not span_cancelled and status_code != StatusCode.ERROR:
                span.set_status(Status(StatusCode.OK))
            span.end()


@contextmanager
def trace_worker_task(
    task_name: str,
    task_id: str | None = None,
    ctx: dict[str, Any] | None = None,
    **attributes: Any,
) -> Iterator[trace.Span | None]:
    """워커 태스크 및 작업 구간을 계측하는 컨텍스트 매니저입니다.

    비활성화 상태(OTEL_ENABLED=False)에서는 아무 비용 없이 즉시 제어를 넘깁니다.
    """
    if not _registry.enabled:
        yield None
        return

    # 최상위 span 참조 확보 (ctx 의 _otel_span 또는 현재 context 의 span)
    top_span: trace.Span | None = None
    if isinstance(ctx, dict):
        top_span = ctx.get("_otel_span")
    if top_span is None:
        current_span = trace.get_current_span()
        if current_span is not None and current_span.is_recording():
            top_span = current_span

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
        except asyncio.CancelledError:
            cancel_reason = _resolve_cancel_reason(ctx)
            span.set_attribute("task.cancelled", True)
            span.set_attribute("task.cancel_reason", cancel_reason)
            setattr(span, "_task_cancelled", True)  # noqa: B010
            if top_span is not None and top_span.is_recording():
                top_span.set_attribute("task.cancelled", True)
                top_span.set_attribute("task.cancel_reason", cancel_reason)
                setattr(top_span, "_task_cancelled", True)  # noqa: B010
            if isinstance(ctx, dict):
                ctx["_task_cancelled"] = True
                ctx["_task_cancel_reason"] = cancel_reason
            raise
        except Exception as exc:
            span.record_exception(exc)
            span.set_status(Status(StatusCode.ERROR, str(exc)))
            if top_span is not None and top_span.is_recording():
                top_span.record_exception(exc)
                top_span.set_status(Status(StatusCode.ERROR, str(exc)))
            raise


def traced_worker_task(
    fn_or_name: Any = None,
    *,
    task_name: str | None = None,
    **default_attributes: Any,
) -> Any:
    """Arq 워커 태스크 함수를 trace_worker_task 로 감싸는 데코레이터.

    비활성화 상태(OTEL_ENABLED=False)에서는 오버헤드 없이 원래 함수를 즉시 호출합니다.
    """
    import inspect
    from functools import wraps

    def decorator(fn: Any) -> Any:
        resolved_name: str = str(task_name or getattr(fn, "__name__", "unnamed_task"))

        if inspect.iscoroutinefunction(fn):

            @wraps(fn)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not _registry.enabled:
                    return await fn(*args, **kwargs)

                ctx = args[0] if args and isinstance(args[0], dict) else None
                job_id = str(ctx.get("job_id")) if ctx and "job_id" in ctx else None
                attrs = dict(default_attributes)
                with trace_worker_task(resolved_name, task_id=job_id, ctx=ctx, **attrs):
                    return await fn(*args, **kwargs)

            wrapper = async_wrapper
        else:

            @wraps(fn)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                if not _registry.enabled:
                    return fn(*args, **kwargs)

                ctx = args[0] if args and isinstance(args[0], dict) else None
                job_id = str(ctx.get("job_id")) if ctx and "job_id" in ctx else None
                attrs = dict(default_attributes)
                with trace_worker_task(resolved_name, task_id=job_id, ctx=ctx, **attrs):
                    return fn(*args, **kwargs)

            wrapper = sync_wrapper

        wrapper.__traced_worker_task__ = True  # type: ignore[attr-defined]
        wrapper.__task_name__ = resolved_name  # type: ignore[attr-defined]
        return wrapper

    if callable(fn_or_name):
        return decorator(fn_or_name)
    if isinstance(fn_or_name, str) and task_name is None:
        task_name = fn_or_name
    return decorator


def get_observability_status() -> dict[str, Any]:
    """현재 OpenTelemetry 계측 및 내보내기 상태를 반환합니다."""
    safe_exporter = _registry.safe_exporter
    safe_metric_exporter = _registry.safe_metric_exporter
    return {
        "enabled": _registry.enabled,
        "metrics_enabled": _registry.metrics_enabled,
        "initialized": _registry.initialized,
        "service_name": _registry.service_name,
        "exporter_type": _registry.exporter_type,
        "endpoint": _registry.endpoint,
        "spans_exported": safe_exporter.spans_exported if safe_exporter else 0,
        "export_errors": safe_exporter.export_errors if safe_exporter else 0,
        "last_export_error": safe_exporter.last_export_error if safe_exporter else None,
        "last_export_at": safe_exporter.last_export_at if safe_exporter else None,
        "metrics_exported": safe_metric_exporter.metrics_exported if safe_metric_exporter else 0,
        "metric_export_errors": safe_metric_exporter.export_errors if safe_metric_exporter else 0,
        "last_metric_export_error": (
            safe_metric_exporter.last_export_error if safe_metric_exporter else None
        ),
        "last_metric_export_at": safe_metric_exporter.last_export_at
        if safe_metric_exporter
        else None,
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

    if _registry.sqlalchemy_metrics_engine is not None:
        try:
            _detach_db_metrics_listeners(_registry.sqlalchemy_metrics_engine)
        except Exception as exc:
            logger.debug("SQLAlchemy 메트릭 리스너 해제 예외: %s", exc)

    if _registry.meter_provider is not None:
        try:
            _registry.meter_provider.shutdown()
        except Exception as exc:
            logger.debug("MeterProvider shutdown 예외: %s", exc)
        with suppress(Exception):
            from opentelemetry.metrics import _internal as _metrics_internal

            _metrics_internal._METER_PROVIDER = None
            _metrics_internal._METER_PROVIDER_SET_ONCE._done = False

    _registry.enabled = False
    _registry.metrics_enabled = False
    _registry.initialized = False
    _registry.service_name = ""
    _registry.exporter_type = "none"
    _registry.endpoint = ""
    _registry.safe_exporter = None
    _registry.safe_metric_exporter = None
    _registry.tracer_provider = None
    _registry.meter_provider = None
    _registry.http_duration_histogram = None
    _registry.db_duration_histogram = None
    _registry.http_requests_counter = None
    _registry.fastapi_instrumented = False
    _registry.sqlalchemy_instrumented = False
    _registry.arq_instrumented = False
    _registry.sqlalchemy_metrics_engine = None
