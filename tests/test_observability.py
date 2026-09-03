"""OpenTelemetry 분산 추적 계측 테스트.

계측 기본 비활성화, 활성화 시 HTTP/DB/Arq 태스크 span 생성,
수집기 장애 시 내결함성, 민감 정보 노출 방지, 기존 API 무결성을 검증합니다.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SpanExporter, SpanExportResult
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode
from sqlalchemy import create_engine, text

from src.app.core.config import settings
from src.app.core.observability import (
    _is_sensitive_key,
    arq_on_job_end,
    arq_on_job_start,
    get_observability_status,
    is_otel_enabled,
    reset_observability_for_testing,
    setup_observability,
    trace_worker_task,
)


class FailingSpanExporter(SpanExporter):
    """내보내기 시 고의로 네트워크 장애 예외를 발생시키는 테스트용 Exporter."""

    def export(self, spans: list[ReadableSpan]) -> SpanExportResult:
        raise ConnectionRefusedError("수집기 서버에 연결할 수 없습니다: Connection refused")

    def shutdown(self) -> None:
        pass


@pytest.fixture(autouse=True)
def cleanup_observability():
    """각 테스트 전후에 관측성 레지스트리를 깨끗하게 초기화합니다."""
    reset_observability_for_testing()
    yield
    reset_observability_for_testing()


def test_otel_disabled_by_default():
    """기본 설정에서 OpenTelemetry 가 비활성화되어 있고 비용이 발생하지 않는지 검증합니다."""
    # 기본 환경 설정값 검증
    assert settings.OTEL_ENABLED is False

    setup_observability()
    assert is_otel_enabled() is False

    status = get_observability_status()
    assert status["enabled"] is False
    assert status["spans_exported"] == 0

    # 비활성 상태에서는 컨텍스트 매니저가 비용 없이 None 을 반환해야 함
    with trace_worker_task("dummy_task") as span:
        assert span is None


def test_disabled_arq_lifecycle_hooks_cost_free():
    """비활성화 상태에서 Arq 훅이 아무런 부가 작업 없이 즉시 리턴하는지 검증합니다."""
    setup_observability()
    ctx = {"job_id": "job_123", "job_try": 1}

    # 예외 없이 즉시 반환 및 ctx 변경 없음
    import asyncio

    asyncio.run(arq_on_job_start(ctx))
    assert "_otel_span" not in ctx

    asyncio.run(arq_on_job_end(ctx))
    assert "_otel_span" not in ctx


def test_fastapi_http_instrumentation():
    """FastAPI HTTP 요청 시 span 이 정상 생성되고 기존 응답 형태가 보존되는지 검증합니다."""
    app = FastAPI()

    @app.get("/api/v1/sample")
    def sample_endpoint():
        return {"result": "success", "count": 42}

    memory_exporter = InMemorySpanExporter()
    setup_observability(app=app, custom_exporter=memory_exporter)

    assert is_otel_enabled() is True

    client = TestClient(app)
    response = client.get("/api/v1/sample")

    # 기존 API 응답 형태 및 상태 코드 확인
    assert response.status_code == 200
    assert response.json() == {"result": "success", "count": 42}

    spans = memory_exporter.get_finished_spans()
    assert len(spans) > 0

    # HTTP span 검증
    http_spans = [s for s in spans if s.name == "GET /api/v1/sample"]
    assert len(http_spans) == 1
    http_span = http_spans[0]
    attrs = http_span.attributes or {}
    assert attrs.get("http.method") == "GET"
    assert attrs.get("http.status_code") == 200
    assert attrs.get("http.route") == "/api/v1/sample"


def test_sqlalchemy_db_instrumentation():
    """SQLAlchemy 질의 실행 시 DB span 이 정상 생성되는지 검증합니다."""
    memory_exporter = InMemorySpanExporter()
    engine = create_engine("sqlite:///:memory:")

    setup_observability(engine=engine, custom_exporter=memory_exporter)

    with engine.connect() as conn:
        conn.execute(text("SELECT 100 AS num"))

    spans = memory_exporter.get_finished_spans()
    db_spans = [s for s in spans if "SELECT" in s.name or s.name == "connect"]
    assert len(db_spans) > 0

    select_spans = [s for s in spans if "SELECT" in s.name]
    assert len(select_spans) >= 1
    attrs = select_spans[0].attributes or {}
    assert attrs.get("db.system") == "sqlite"
    assert "SELECT 100 AS num" in str(attrs.get("db.statement", ""))


def test_arq_worker_task_instrumentation_success():
    """Arq 워커 태스크가 trace_worker_task 컨텍스트를 통해 성공 span 을 기록하는지 검증합니다."""
    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    with trace_worker_task("manual_retrain_task", task_id="retrain_999", model="servc") as span:
        assert span is not None

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    task_span = spans[0]
    assert task_span.name == "arq.task:manual_retrain_task"
    assert task_span.status.status_code == StatusCode.OK
    attrs = task_span.attributes or {}
    assert attrs.get("task.name") == "manual_retrain_task"
    assert attrs.get("task.id") == "retrain_999"
    assert attrs.get("task.system") == "arq"
    assert attrs.get("task.param.model") == "servc"


def test_arq_worker_task_instrumentation_error():
    """Arq 워커 태스크 실행 중 예외 발생 시 span 에 ERROR 상태와 예외가 기록되는지 검증합니다."""
    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    with (
        pytest.raises(ValueError, match="데이터 부족"),
        trace_worker_task("collect_bids_task", task_id="collect_001"),
    ):
        raise ValueError("데이터 부족")

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    task_span = spans[0]
    assert task_span.name == "arq.task:collect_bids_task"
    assert task_span.status.status_code == StatusCode.ERROR
    assert "데이터 부족" in str(task_span.status.description)


def test_arq_lifecycle_hooks():
    """Arq 워커 라이프사이클 훅(on_job_start, on_job_end)을 통한 span 생성을 검증합니다."""
    import asyncio

    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    ctx = {"job_id": "arq_job_test_1", "job_try": 2}
    asyncio.run(arq_on_job_start(ctx))
    assert "_otel_span" in ctx
    assert "_otel_token" in ctx

    asyncio.run(arq_on_job_end(ctx))
    assert "_otel_span" not in ctx

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 1
    job_span = spans[0]
    assert job_span.name == "arq.job:arq_job_test_1"
    attrs = job_span.attributes or {}
    assert attrs.get("task.id") == "arq_job_test_1"
    assert attrs.get("task.try") == 2


def test_safe_span_exporter_fault_tolerance():
    """내보내기 대상 수집기가 죽어 있어도 애플리케이션이 죽지 않고 상태가 관측 가능한지 검증합니다."""
    failing_exporter = FailingSpanExporter()
    setup_observability(custom_exporter=failing_exporter)

    # span 생성 및 종료 (SimpleSpanProcessor 로 즉시 export 시도)
    with trace_worker_task("resilience_task", task_id="task_fail_test"):
        pass

    status = get_observability_status()
    # 애플리케이션이 중단되지 않고 실패 횟수 및 에러 내용이 상태에 기록됨
    assert status["export_errors"] >= 1
    assert "ConnectionRefusedError" in str(status["last_export_error"])


def test_no_secrets_leaked_in_spans():
    """DB 접속 문자열 비밀번호나 요청 인증 토큰 등 비밀이 span 속성에 새지 않는지 검증합니다."""
    memory_exporter = InMemorySpanExporter()

    # 1. 민감 속성 필터링 함수 검증
    for key in ("user_password", "SECRET_KEY", "auth_token", "api_key", "cookie_value"):
        assert _is_sensitive_key(key) is True

    for key in ("task_name", "model_category", "run_id", "status"):
        assert _is_sensitive_key(key) is False

    # 2. 태스크 속성 주입 시 비밀 필터링 검증
    setup_observability(custom_exporter=memory_exporter)
    with trace_worker_task(
        "secure_task",
        password="super_secret_password",
        auth_token="jwt_secret_token",
        safe_param="public_value",
    ):
        pass

    spans = memory_exporter.get_finished_spans()
    attrs = spans[0].attributes or {}
    assert "task.param.safe_param" in attrs
    assert "task.param.password" not in attrs
    assert "task.param.auth_token" not in attrs
    for v in attrs.values():
        assert "super_secret_password" not in str(v)
        assert "jwt_secret_token" not in str(v)

    # 3. HTTP 요청 헤더 비밀 누출 방지 검증
    app = FastAPI()

    @app.get("/secure-endpoint")
    def secure_endpoint():
        return {"status": "ok"}

    setup_observability(app=app, custom_exporter=memory_exporter)
    client = TestClient(app)
    client.get(
        "/secure-endpoint",
        headers={
            "Authorization": "Bearer sensitive_token_xyz_999",
            "Cookie": "session_id=confidential_session_456",
        },
    )

    all_spans = memory_exporter.get_finished_spans()
    for s in all_spans:
        for k, v in (s.attributes or {}).items():
            assert "sensitive_token_xyz_999" not in str(v), f"Token leaked in {k}: {v}"
            assert "confidential_session_456" not in str(v), f"Cookie leaked in {k}: {v}"


def test_existing_health_api_integrity():
    """OpenTelemetry 계측 전후로 기존 /api/v1/health 응답 형태와 상태 코드가 보존되는지 검증합니다."""
    from src.app.main import app

    client = TestClient(app)
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "healthy"
    assert data["service"] == "refac_bid_box"
    assert data["framework"] == "FastAPI (ASGI)"
    assert data["database"] == "MySQL 8 (Docker)"
    assert data["task_queue"] == "Arq (asyncio)"
