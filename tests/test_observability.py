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
    traced_worker_task,
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


def test_arq_context_token_detach_lifecycle():
    """Arq 작업 시작 시 context 에 span 이 바인딩되고 종료 시 token 이 detach 되는지 검증합니다."""
    import asyncio

    from opentelemetry import trace

    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    ctx = {"job_id": "arq_job_test_detach", "job_try": 1}

    async def _run():
        before_span = trace.get_current_span()
        await arq_on_job_start(ctx)
        active_span = trace.get_current_span()
        assert ctx.get("_otel_span") is not None
        assert active_span is ctx["_otel_span"]
        assert active_span is not before_span

        await arq_on_job_end(ctx)
        after_span = trace.get_current_span()
        assert after_span is not active_span
        assert "_otel_token" not in ctx
        assert "_otel_span" not in ctx

    asyncio.run(_run())


def test_arq_job_end_closes_span_even_if_detach_fails(monkeypatch):
    """detach 가 실패해도 span 은 종료되어야 합니다. 종료하지 않으면 span 이 누수됩니다."""
    import asyncio

    from src.app.core import observability as observability_module

    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    ctx = {"job_id": "arq_job_detach_failure", "job_try": 1}

    def _raising_detach(_token):
        raise RuntimeError("detach 실패 모사")

    async def _run():
        await arq_on_job_start(ctx)
        span = ctx["_otel_span"]
        monkeypatch.setattr(observability_module.context, "detach", _raising_detach)
        await arq_on_job_end(ctx)
        assert span.end_time is not None
        assert "_otel_span" not in ctx
        assert "_otel_token" not in ctx

    asyncio.run(_run())


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


@pytest.mark.asyncio
async def test_arq_failed_task_top_level_span_is_error():
    """실패한 Arq 작업의 최상위 span 및 태스크 span 이 ERROR 로 기록되고 예외가 남는지 검증합니다.

    arq_on_job_end 가 ERROR 로 설정된 최상위 span 을 OK 로 덮어쓰지 않고,
    예외가 원래대로 호출자에게 전파되는지 확인합니다.
    """
    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    ctx = {"job_id": "job_fail_999", "job_try": 1}
    await arq_on_job_start(ctx)

    @traced_worker_task
    async def sample_failing_task(ctx: dict):
        raise RuntimeError("태스크 실행 중 치명적 오류 발생")

    with pytest.raises(RuntimeError, match="태스크 실행 중 치명적 오류 발생"):
        await sample_failing_task(ctx)

    await arq_on_job_end(ctx)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 2

    # 자식 태스크 span 검증
    task_spans = [s for s in spans if s.name == "arq.task:sample_failing_task"]
    assert len(task_spans) == 1
    task_span = task_spans[0]
    assert task_span.status.status_code == StatusCode.ERROR
    assert "태스크 실행 중 치명적 오류 발생" in str(task_span.status.description)
    assert any(e.name == "exception" for e in task_span.events)

    # 최상위 job span 검증
    job_spans = [s for s in spans if s.name == "arq.job:job_fail_999"]
    assert len(job_spans) == 1
    job_span = job_spans[0]
    assert job_span.status.status_code == StatusCode.ERROR
    assert "태스크 실행 중 치명적 오류 발생" in str(job_span.status.description)
    assert any(e.name == "exception" for e in job_span.events)


@pytest.mark.asyncio
async def test_arq_success_task_top_level_span_is_ok():
    """성공한 Arq 작업의 최상위 span 및 태스크 span 이 모두 OK 상태로 종료되는지 검증합니다."""
    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    ctx = {"job_id": "job_success_888", "job_try": 1}
    await arq_on_job_start(ctx)

    @traced_worker_task
    async def sample_success_task(ctx: dict, key: str = "val"):
        return {"status": "success", "echo": key}

    result = await sample_success_task(ctx, key="hello")
    assert result == {"status": "success", "echo": "hello"}

    await arq_on_job_end(ctx)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 2

    task_spans = [s for s in spans if s.name == "arq.task:sample_success_task"]
    assert len(task_spans) == 1
    assert task_spans[0].status.status_code == StatusCode.OK

    job_spans = [s for s in spans if s.name == "arq.job:job_success_888"]
    assert len(job_spans) == 1
    assert job_spans[0].status.status_code == StatusCode.OK


def test_all_worker_settings_tasks_have_instrumentation():
    """WorkerSettings 에 등록된 모든 태스크(functions 및 cron_jobs)가 계측 배선을 갖는지 검증합니다.

    신규 태스크가 등록될 때 계측 누락을 컴파일/테스트 단계에서 차단합니다.
    """
    from src.tasks.worker import WorkerSettings, is_task_traced

    # 1. functions 목록 검증
    assert len(WorkerSettings.functions) >= 13
    for fn in WorkerSettings.functions:
        target = getattr(fn, "coroutine", fn)
        name = getattr(target, "__name__", str(target))
        assert is_task_traced(target), (
            f"WorkerSettings.functions 의 {name} 태스크에 계측 배선이 누락되었습니다."
        )

    # 2. cron_jobs 목록 검증
    assert len(WorkerSettings.cron_jobs) >= 4
    for c in WorkerSettings.cron_jobs:
        target = getattr(c, "coroutine", c)
        name = getattr(target, "__name__", str(target))
        assert is_task_traced(target), (
            f"WorkerSettings.cron_jobs 의 {name} 태스크에 계측 배선이 누락되었습니다."
        )


@pytest.mark.asyncio
async def test_otel_disabled_task_zero_overhead_and_identical_behavior():
    """OTEL_ENABLED=False 일 때 태스크 실행 및 반환값, 예외가 배선 전과 완전히 동일함을 검증합니다."""
    assert is_otel_enabled() is False

    @traced_worker_task
    async def multiply_task(ctx: dict, x: int, y: int) -> int:
        return x * y

    ctx = {"job_id": "disabled_job_1"}
    ret = await multiply_task(ctx, 3, 7)
    assert ret == 21

    @traced_worker_task
    async def throwing_task(ctx: dict):
        raise KeyError("존재하지 않는 키")

    with pytest.raises(KeyError, match="존재하지 않는 키"):
        await throwing_task(ctx)


@pytest.mark.asyncio
async def test_traced_worker_task_decorator_with_real_tasks(monkeypatch):
    """실제 등록된 태스크 함수(rebuild_dataset_summary_task) 호출 시 계측 span 이 정상 생성되는지 검증합니다."""
    from types import SimpleNamespace

    import src.tasks.summary_tasks as summary_tasks_module
    from src.tasks.summary_tasks import rebuild_dataset_summary_task

    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    # DB 의존성을 격리하기 위해 summary 함수 모킹
    dummy_summary = SimpleNamespace(
        dataset="bids",
        total_count=500,
        total_amount=1000000,
        aggregation_version=1,
        rebuilt_at=None,
    )
    monkeypatch.setattr(
        summary_tasks_module,
        "rebuild_bid_dataset_summary",
        lambda db, ds: dummy_summary,
    )

    ctx = {"job_id": "summary_job_test"}
    await arq_on_job_start(ctx)
    res = await rebuild_dataset_summary_task(ctx, dataset="bids")
    await arq_on_job_end(ctx)

    assert res["total_count"] == 500
    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 2

    task_span = next(s for s in spans if s.name == "arq.task:rebuild_dataset_summary_task")
    assert task_span.status.status_code == StatusCode.OK
    job_span = next(s for s in spans if s.name == "arq.job:summary_job_test")
    assert job_span.status.status_code == StatusCode.OK


@pytest.mark.asyncio
async def test_arq_cancelled_task_top_level_span_not_ok_and_propagated():
    """사용자 중단(abort)으로 취소된 태스크의 최상위 span 이 OK 가 아니고 CancelledError 가 전파되는지 검증합니다.

    (a) 취소된 태스크의 최상위 arq.job span 상태가 OK 가 아니다.
    (b) CancelledError 가 삼켜지지 않고 호출자에게 그대로 전파된다.
    (c) task.cancelled=True 및 task.cancel_reason='aborted' 속성이 기록된다.
    (d) span 이 정상 종료(closed)된다.
    """
    import asyncio

    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    ctx = {"job_id": "job_cancelled_101", "job_try": 1}
    await arq_on_job_start(ctx)

    @traced_worker_task
    async def sample_aborted_task(ctx: dict):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await sample_aborted_task(ctx)

    await arq_on_job_end(ctx)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 2

    # 자식 태스크 span 검증
    task_spans = [s for s in spans if s.name == "arq.task:sample_aborted_task"]
    assert len(task_spans) == 1
    task_span = task_spans[0]
    assert task_span.status.status_code != StatusCode.OK
    attrs_task = task_span.attributes or {}
    assert attrs_task.get("task.cancelled") is True
    assert attrs_task.get("task.cancel_reason") == "aborted"
    assert task_span.end_time is not None

    # 최상위 job span 검증
    job_spans = [s for s in spans if s.name == "arq.job:job_cancelled_101"]
    assert len(job_spans) == 1
    job_span = job_spans[0]
    assert job_span.status.status_code != StatusCode.OK
    attrs_job = job_span.attributes or {}
    assert attrs_job.get("task.cancelled") is True
    assert attrs_job.get("task.cancel_reason") == "aborted"
    assert job_span.end_time is not None


@pytest.mark.asyncio
async def test_arq_worker_shutdown_cancellation_not_polluted():
    """워커 정상 셧다운 시 배경 catch-up 취소가 오류(ERROR)로 기록되지 않고 정상 취소로 기록되는지 검증합니다.

    (a) task.cancelled=True 및 task.cancel_reason='worker_shutdown' 속성이 기록된다.
    (b) status_code 가 StatusCode.ERROR 가 아니어서 운영 경보 노이즈를 만들지 않는다.
    (c) status_code 가 StatusCode.OK 도 아니어서 취소된 작업이 성공으로 오인되지 않는다.
    (d) CancelledError 가 정상적으로 전파된다.
    """
    import asyncio

    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    ctx = {"job_id": "job_shutdown_catchup", "worker_shutting_down": True}
    await arq_on_job_start(ctx)

    @traced_worker_task
    async def sample_shutdown_task(ctx: dict):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await sample_shutdown_task(ctx)

    await arq_on_job_end(ctx)

    spans = memory_exporter.get_finished_spans()
    assert len(spans) == 2

    for s in spans:
        attrs = s.attributes or {}
        assert attrs.get("task.cancelled") is True
        assert attrs.get("task.cancel_reason") == "worker_shutdown"
        # 운영 노이즈 방지: ERROR 로 기록되지 않음
        assert s.status.status_code != StatusCode.ERROR
        # 성공 오인 방지: OK 로 기록되지 않음
        assert s.status.status_code != StatusCode.OK
        # span 이 정상 종료됨
        assert s.end_time is not None


@pytest.mark.asyncio
async def test_otel_disabled_cancellation_zero_overhead_and_transparent():
    """OTEL_ENABLED=False 일 때 취소 예외가 삼켜지지 않고 투명하게 전파되며 비용이 0 인지 검증합니다."""
    import asyncio

    assert is_otel_enabled() is False

    @traced_worker_task
    async def cancelled_disabled_task(ctx: dict):
        raise asyncio.CancelledError("aborted")

    ctx = {"job_id": "disabled_cancel_job"}
    with pytest.raises(asyncio.CancelledError):
        await cancelled_disabled_task(ctx)

    assert "_otel_span" not in ctx
    assert "_task_cancelled" not in ctx


@pytest.mark.asyncio
async def test_cancel_reason_ignores_exception_args_and_uses_ctx():
    """취소 원인 분류는 CancelledError 인자가 아니라 ctx 플래그만 본다.

    예외 메시지에 shutdown 이 있어도 ctx 가 없으면 aborted 이고,
    인자가 비어 있어도 worker_shutting_down 이면 worker_shutdown 이다.
    """
    import asyncio

    from src.app.core.observability import _resolve_cancel_reason

    assert _resolve_cancel_reason(ctx=None) == "aborted"
    assert _resolve_cancel_reason(ctx={"job_id": "x"}) == "aborted"

    memory_exporter = InMemorySpanExporter()
    setup_observability(custom_exporter=memory_exporter)

    ctx_abort = {"job_id": "job_args_ignored"}
    await arq_on_job_start(ctx_abort)

    @traced_worker_task
    async def sample_args_ignored_task(ctx: dict):
        raise asyncio.CancelledError("worker_shutdown")

    with pytest.raises(asyncio.CancelledError):
        await sample_args_ignored_task(ctx_abort)

    await arq_on_job_end(ctx_abort)

    abort_spans = [
        s
        for s in memory_exporter.get_finished_spans()
        if s.name == "arq.task:sample_args_ignored_task"
    ]
    assert len(abort_spans) == 1
    assert (abort_spans[0].attributes or {}).get("task.cancel_reason") == "aborted"
    assert abort_spans[0].status.status_code != StatusCode.OK

    ctx_shutdown = {"job_id": "job_ctx_shutdown", "is_background_catchup": True}
    await arq_on_job_start(ctx_shutdown)

    @traced_worker_task
    async def sample_ctx_shutdown_task(ctx: dict):
        raise asyncio.CancelledError()

    with pytest.raises(asyncio.CancelledError):
        await sample_ctx_shutdown_task(ctx_shutdown)

    await arq_on_job_end(ctx_shutdown)

    shutdown_spans = [
        s
        for s in memory_exporter.get_finished_spans()
        if s.name == "arq.task:sample_ctx_shutdown_task"
    ]
    assert len(shutdown_spans) == 1
    assert (shutdown_spans[0].attributes or {}).get("task.cancel_reason") == "worker_shutdown"
    assert shutdown_spans[0].status.status_code != StatusCode.OK
    assert shutdown_spans[0].status.status_code != StatusCode.ERROR
