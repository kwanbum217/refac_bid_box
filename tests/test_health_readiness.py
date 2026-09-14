"""tests/test_health_readiness.py

Readiness 헬스체크 게이트 및 LLM 분리 검증 테스트.

계약 (코디네이터 확정 및 정정):
1. READINESS_REQUIRE_LLM=false 환경에서 LLM 이 가용하지 않더라도
   핵심 의존성(mysql, redis, model_registry)이 정상이면
   status 는 degraded 이며 HTTP 200 을 반환합니다 (503 not_ready 가 아님).
2. LLM 점검 결과(ok, detail, latency_ms)는 status 가 degraded 일 때도 응답 본문에 유지됩니다.
3. READINESS_REQUIRE_LLM=true 로 설정된 경우 LLM 장애 시 status 는 not_ready 이며 HTTP 503 입니다.
4. mysql, redis, model_registry 등 기존 critical 의존성 실패 시에는
   READINESS_REQUIRE_LLM 값과 무관하게 not_ready 및 HTTP 503 을 유지합니다.
"""

from fastapi.testclient import TestClient

from src.app.api.v1 import health
from src.app.core.config import settings
from src.app.main import app

client = TestClient(app)


def _setup_base_healthy_state(monkeypatch):
    """모든 기본 의존성 및 예열 상태를 정상으로 설정합니다."""
    for name in (
        "_check_mysql",
        "_check_redis",
        "_check_meilisearch",
        "_check_model_registry",
        "_check_chromadb",
    ):
        monkeypatch.setattr(health, name, lambda: None)

    health.warmup_state.mark_llm_done(success=True)
    health.warmup_state.mark_predictor_done(success=True)
    health.warmup_state.mark_vector_done(success=True)
    monkeypatch.setattr(health.warmup_state, "_started", True, raising=False)


def test_readiness_is_degraded_and_200_when_llm_fails_and_not_required(monkeypatch):
    """READINESS_REQUIRE_LLM=false 일 때 LLM 실패 시 status 는 degraded 이고 HTTP 200 이어야 합니다."""
    _setup_base_healthy_state(monkeypatch)
    monkeypatch.setattr(settings, "READINESS_REQUIRE_LLM", False)

    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {
            "ok": False,
            "provider": "ollama",
            "detail": "llm_service_unavailable",
            "latency_ms": 1.23,
        },
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["llm"]["ok"] is False
    assert data["llm"]["provider"] == "ollama"
    assert data["llm"]["detail"] == "llm_service_unavailable"
    assert isinstance(data["llm"]["latency_ms"], float)
    assert data["checks"]["mysql"]["ok"] is True
    assert data["checks"]["redis"]["ok"] is True
    assert data["checks"]["model_registry"]["ok"] is True


def test_readiness_is_not_ready_and_503_when_llm_fails_and_required(monkeypatch):
    """READINESS_REQUIRE_LLM=true 일 때 LLM 실패 시 status 는 not_ready 이고 HTTP 503 이어야 합니다."""
    _setup_base_healthy_state(monkeypatch)
    monkeypatch.setattr(settings, "READINESS_REQUIRE_LLM", True)

    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {
            "ok": False,
            "provider": "ollama",
            "detail": "llm_service_unavailable",
            "latency_ms": 1.23,
        },
    )

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["llm"]["ok"] is False
    assert data["llm"]["detail"] == "llm_service_unavailable"


def test_readiness_is_not_ready_when_mysql_fails_regardless_of_llm(monkeypatch):
    """READINESS_REQUIRE_LLM=false 상태여도 mysql 등 critical 의존성 실패 시 503 not_ready 여야 합니다."""
    _setup_base_healthy_state(monkeypatch)
    monkeypatch.setattr(settings, "READINESS_REQUIRE_LLM", False)

    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {"ok": True, "provider": "ollama", "detail": None, "latency_ms": 0.5},
    )

    def mysql_fail():
        raise RuntimeError("mysql connection failed")

    monkeypatch.setattr(health, "_check_mysql", mysql_fail)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["mysql"]["ok"] is False


def test_readiness_is_degraded_when_non_critical_meilisearch_fails(monkeypatch):
    """비-critical 인 meilisearch 실패 시에는 degraded 와 HTTP 200 을 반환해야 합니다."""
    _setup_base_healthy_state(monkeypatch)
    monkeypatch.setattr(settings, "READINESS_REQUIRE_LLM", False)

    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {"ok": True, "provider": "ollama", "detail": None, "latency_ms": 0.5},
    )

    def meilisearch_fail():
        raise ConnectionError("meilisearch down")

    monkeypatch.setattr(health, "_check_meilisearch", meilisearch_fail)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["checks"]["meilisearch"]["ok"] is False
