"""tests/test_observability_metrics.py

OpenTelemetry 메트릭 계측(관측성 2단계 선행 조건) 종합 단위 및 통합 테스트.
- OTEL_ENABLED 비활성화 시 자원 무할당(조기 반환) 검증
- 핵심 3대 계측기(요청 지연, DB 질의 지연, 요청 수) 등록 및 단위(초/s) 검증
- OpenTelemetry 시맨틱 컨벤션 명칭 일치 검증
- 경로 라벨 템플릿 적용 및 고차원 값(식별자, 쿼리 등) 배제 검증
- 민감 키 패턴 라벨 차단 검증
- 메트릭 익스포터 장애 발생 시 HTTP 요청 무영향(격리) 검증
- SQLAlchemy DB 질의 지연 계측 및 연산자 라벨링 검증
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from opentelemetry.metrics import Counter, Histogram
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    MetricExporter,
    MetricExportResult,
    MetricsData,
)
from sqlalchemy import create_engine, text

from src.app.core.config import settings
from src.app.core.observability import (
    DB_CLIENT_OPERATION_DURATION,
    HTTP_SERVER_REQUEST_COUNT,
    HTTP_SERVER_REQUEST_DURATION,
    SafeMetricExporter,
    _extract_db_operation,
    _extract_route_template,
    get_meter_provider,
    get_metric_instruments,
    get_observability_status,
    get_tracer_provider,
    is_metrics_enabled,
    is_otel_enabled,
    reset_observability_for_testing,
    setup_observability,
)


@pytest.fixture(autouse=True)
def _cleanup_observability():
    """테스트 전후로 관측성 레지스트리를 깨끗하게 초기화합니다."""
    reset_observability_for_testing()
    orig_otel_enabled = settings.OTEL_ENABLED
    orig_metrics_enabled = settings.OTEL_METRICS_ENABLED
    orig_exporter_type = settings.OTEL_EXPORTER_TYPE
    orig_endpoint = settings.OTEL_EXPORTER_OTLP_ENDPOINT
    yield
    reset_observability_for_testing()
    settings.OTEL_ENABLED = orig_otel_enabled
    settings.OTEL_METRICS_ENABLED = orig_metrics_enabled
    settings.OTEL_EXPORTER_TYPE = orig_exporter_type
    settings.OTEL_EXPORTER_OTLP_ENDPOINT = orig_endpoint


def test_otel_disabled_noop():
    """OTEL_ENABLED 가 False 일 때 MeterProvider 와 익스포터가 일절 생성되지 않음을 검증합니다."""
    settings.OTEL_ENABLED = False
    settings.OTEL_METRICS_ENABLED = None

    setup_observability()

    assert not is_otel_enabled()
    assert not is_metrics_enabled()
    assert get_meter_provider() is None
    assert get_tracer_provider() is None

    instruments = get_metric_instruments()
    assert instruments["http_request_duration"] is None
    assert instruments["db_operation_duration"] is None
    assert instruments["http_request_count"] is None

    status = get_observability_status()
    assert status["enabled"] is False
    assert status["metrics_enabled"] is False
    assert status["metrics_exported"] == 0
    assert status["metric_export_errors"] == 0


def test_otel_metrics_explicitly_disabled():
    """OTEL_ENABLED 가 True 이더라도 OTEL_METRICS_ENABLED 가 False 면 메트릭만 생성되지 않음을 검증합니다."""
    settings.OTEL_ENABLED = True
    settings.OTEL_METRICS_ENABLED = False
    settings.OTEL_EXPORTER_TYPE = "none"

    setup_observability()

    assert is_otel_enabled()
    assert not is_metrics_enabled()
    assert get_meter_provider() is None
    assert get_tracer_provider() is not None

    instruments = get_metric_instruments()
    assert instruments["http_request_duration"] is None
    assert instruments["db_operation_duration"] is None
    assert instruments["http_request_count"] is None


def test_three_instruments_registered_and_semantic_conventions():
    """3대 핵심 계측기가 등록되고 명칭과 단위(s)가 OpenTelemetry 시맨틱 컨벤션을 만족하는지 검증합니다."""
    settings.OTEL_ENABLED = True
    settings.OTEL_METRICS_ENABLED = True
    settings.OTEL_EXPORTER_TYPE = "none"

    setup_observability()

    assert is_metrics_enabled()
    provider = get_meter_provider()
    assert provider is not None

    instruments = get_metric_instruments()
    http_dur = instruments["http_request_duration"]
    db_dur = instruments["db_operation_duration"]
    http_cnt = instruments["http_request_count"]

    assert isinstance(http_dur, Histogram)
    assert isinstance(db_dur, Histogram)
    assert isinstance(http_cnt, Counter)

    # 계측 명칭 검증
    assert http_dur.name == HTTP_SERVER_REQUEST_DURATION
    assert http_dur.name == "http.server.request.duration"
    assert db_dur.name == DB_CLIENT_OPERATION_DURATION
    assert db_dur.name == "db.client.operation.duration"
    assert http_cnt.name == HTTP_SERVER_REQUEST_COUNT
    assert http_cnt.name == "http.server.request.count"

    # 단위 검증 (지연 계측은 표준 초 's')
    assert http_dur.unit == "s"
    assert db_dur.unit == "s"
    assert http_cnt.unit == "{request}"


def test_route_template_label_prevents_cardinality_explosion():
    """실제 경로 값(ID 등)이 아닌 템플릿 형태만 라벨로 기록되어 카디널리티 폭발이 방지되는지 검증합니다."""
    app = FastAPI()
    reader = InMemoryMetricReader()

    @app.get("/api/v1/bids/{bid_id}")
    def get_bid(bid_id: str):
        return {"bid_id": bid_id}

    @app.get("/api/v1/organizations/{org_id}/notices/{notice_no}")
    def get_notice(org_id: str, notice_no: str):
        return {"org_id": org_id, "notice_no": notice_no}

    setup_observability(app=app, custom_metric_exporter=reader)

    client = TestClient(app)

    # 동적 파라미터가 포함된 요청 다수 전송
    r1 = client.get("/api/v1/bids/20260901-0001")
    r2 = client.get("/api/v1/bids/20260901-0002")
    r3 = client.get("/api/v1/organizations/org_999/notices/not_555?token=secret123&query=test")
    r4 = client.get("/api/v1/unknown_random_endpoint/987654")

    assert r1.status_code == 200
    assert r2.status_code == 200
    assert r3.status_code == 200
    assert r4.status_code == 404

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None

    routes_seen: set[str] = set()
    all_attributes: list[dict[str, Any]] = []

    for rm in metrics_data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                for dp in getattr(m.data, "data_points", []):
                    attrs = dict(dp.attributes)
                    all_attributes.append(attrs)
                    if "http.route" in attrs:
                        routes_seen.add(str(attrs["http.route"]))

    # 경로 라벨은 반드시 템플릿이거나 unmatched 여야 함
    assert "/api/v1/bids/{bid_id}" in routes_seen
    assert "/api/v1/organizations/{org_id}/notices/{notice_no}" in routes_seen
    assert "unmatched" in routes_seen

    # 실제 동적 파라미터 값이나 쿼리 문자열이 어떤 속성에도 노출되지 않음을 확증
    forbidden_values = {
        "20260901-0001",
        "20260901-0002",
        "org_999",
        "not_555",
        "secret123",
        "987654",
        "/api/v1/unknown_random_endpoint/987654",
    }

    for attrs in all_attributes:
        for key, val in attrs.items():
            for forbidden in forbidden_values:
                assert forbidden not in str(val), (
                    f"라벨 값에 고차원 또는 실제 파라미터가 포함됨: {key}={val}"
                )
                assert forbidden not in str(key), f"라벨 키에 고차원 값이 포함됨: {key}"


def test_sensitive_keys_excluded_from_labels():
    """비밀번호, 토큰 등 민감 정보 패턴이 메트릭 라벨에 진입하지 못하도록 차단됨을 검증합니다."""
    app = FastAPI()
    reader = InMemoryMetricReader()

    @app.get("/api/v1/login")
    def login():
        return {"status": "ok"}

    setup_observability(app=app, custom_metric_exporter=reader)
    client = TestClient(app)
    client.get("/api/v1/login", headers={"Authorization": "Bearer secret_token_123"})

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None

    sensitive_patterns = ("password", "secret", "token", "auth", "credential", "cookie", "private")

    for rm in metrics_data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                for dp in getattr(m.data, "data_points", []):
                    for attr_key in dp.attributes:
                        for pattern in sensitive_patterns:
                            assert pattern not in attr_key.lower(), (
                                f"민감 키가 메트릭 라벨에 포함됨: {attr_key}"
                            )


def test_exporter_failure_does_not_affect_request_processing():
    """메트릭 익스포터가 예외를 던지거나 수집기가 다운되어도 HTTP 요청 및 애플리케이션 처리가 정상 동작함을 검증합니다."""

    class BrokenMetricExporter(MetricExporter):
        def export(
            self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any
        ) -> MetricExportResult:
            raise RuntimeError("연결 대상 수집기(Collector) 통신 불가 장애 발생")

        def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
            raise RuntimeError("Exporter shutdown 장애")

        def force_flush(self, timeout_millis: float = 10_000) -> bool:
            raise RuntimeError("Exporter flush 장애")

    broken_exporter = BrokenMetricExporter()
    app = FastAPI()

    @app.get("/api/v1/data")
    def get_data():
        return {"result": "success"}

    setup_observability(app=app, custom_metric_exporter=broken_exporter)

    client = TestClient(app)
    # 익스포터에 치명적 장애가 있어도 요청은 정상 200 반환
    response = client.get("/api/v1/data")
    assert response.status_code == 200
    assert response.json() == {"result": "success"}

    # SafeMetricExporter 가 에러를 흡수하고 카운트를 증가시켰는지 검증
    status = get_observability_status()
    assert status["metrics_enabled"] is True

    # 수동 flush 호출 시에도 예외 전파 없이 안전하게 실패 처리되는지 확인
    safe_exporter = SafeMetricExporter(broken_exporter)
    dummy_data = MetricsData(resource_metrics=[])
    res = safe_exporter.export(dummy_data)
    assert res == MetricExportResult.FAILURE
    assert safe_exporter.export_errors == 1
    assert "RuntimeError" in str(safe_exporter.last_export_error)
    assert safe_exporter.force_flush() is False


def test_db_query_duration_recording():
    """SQLAlchemy 쿼리 실행 시 db.client.operation.duration 히스토그램이 정상 기록됨을 검증합니다."""
    engine = create_engine("sqlite:///:memory:")
    reader = InMemoryMetricReader()

    setup_observability(engine=engine, custom_metric_exporter=reader)

    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        conn.execute(text("CREATE TABLE bids_sample (id INT, title TEXT)"))
        conn.execute(text("INSERT INTO bids_sample VALUES (1, '입찰')"))
        conn.execute(text("SELECT * FROM bids_sample WHERE id = 1"))

    metrics_data = reader.get_metrics_data()
    assert metrics_data is not None

    total_query_count = 0
    db_points: list[dict[str, Any]] = []
    for rm in metrics_data.resource_metrics:
        for sm in rm.scope_metrics:
            for m in sm.metrics:
                if m.name == DB_CLIENT_OPERATION_DURATION:
                    assert m.unit == "s"
                    for dp in getattr(m.data, "data_points", []):
                        db_points.append(dict(dp.attributes))
                        total_query_count += getattr(dp, "count", 0)

    assert total_query_count >= 4
    assert len(db_points) >= 3
    operations_seen = {p.get("db.operation") for p in db_points}
    systems_seen = {p.get("db.system") for p in db_points}

    assert "SELECT" in operations_seen
    assert "CREATE" in operations_seen
    assert "INSERT" in operations_seen
    assert "sqlite" in systems_seen

    # SQL 문이나 파라미터가 라벨에 유출되지 않음을 확증
    for p in db_points:
        for v in p.values():
            assert "bids_sample" not in str(v)
            assert "WHERE" not in str(v)


def test_db_operation_extraction():
    """SQL 문으로부터 저카디널리티 표준 명령어가 올바르게 추출되는지 검증합니다."""
    assert _extract_db_operation("SELECT * FROM table") == "SELECT"
    assert _extract_db_operation("  insert into bids values(1) ") == "INSERT"
    assert _extract_db_operation("UPDATE bids SET title='a'") == "UPDATE"
    assert _extract_db_operation("DELETE FROM bids") == "DELETE"
    assert _extract_db_operation("COMMIT") == "COMMIT"
    assert _extract_db_operation("UNKNOWN_CUSTOM_QUERY 123") == "OTHER"
    assert _extract_db_operation("") == "UNKNOWN"
    assert _extract_db_operation(None) == "UNKNOWN"


def test_extract_route_template_unmatched_fallback():
    """라우트 정보가 없는 요청 스코프에서 고차원 URL 대신 'unmatched' 로 안전하게 폴백되는지 검증합니다."""
    empty_scope: dict[str, Any] = {"type": "http", "path": "/confidential/path/user_12345"}
    template = _extract_route_template(empty_scope)
    assert template == "unmatched"
    assert "12345" not in template
    assert "/confidential" not in template


def test_safe_metric_exporter_success_tracking():
    """SafeMetricExporter 가 성공 내보내기 시 카운트와 시각을 정상 갱신하는지 검증합니다."""

    class DummySuccessExporter(MetricExporter):
        def export(
            self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any
        ) -> MetricExportResult:
            return MetricExportResult.SUCCESS

        def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
            pass

        def force_flush(self, timeout_millis: float = 10_000) -> bool:
            return True

    safe_exp = SafeMetricExporter(DummySuccessExporter())
    dummy_data = MetricsData(resource_metrics=[])
    res = safe_exp.export(dummy_data)
    assert res == MetricExportResult.SUCCESS
    assert safe_exp.metrics_exported == 1
    assert safe_exp.export_errors == 0
    assert safe_exp.last_export_at is not None
    assert safe_exp.force_flush() is True
    safe_exp.shutdown()
