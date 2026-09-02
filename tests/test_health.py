import time

from fastapi.testclient import TestClient

from src.app.api.v1 import health
from src.app.core.config import settings
from src.app.main import app

client = TestClient(app)


def test_root():
    """루트는 원본과 동일하게 로그인이 필요한 홈 화면(SSR)이다."""
    response = client.get("/", follow_redirects=False)
    assert response.status_code == 303
    assert response.headers["location"] == "/accounts/login/?next=/"


def test_health():
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "healthy",
        "service": "refac_bid_box",
        "environment": settings.ENVIRONMENT,
        "framework": "FastAPI (ASGI)",
        "database": "MySQL 8 (Docker)",
        "task_queue": "Arq (asyncio)",
    }


def _patch_checks_healthy(monkeypatch):
    """readiness 가 보는 검사를 모두 정상 상태로 만듭니다.

    readiness 는 5개 의존성 외에 warmup 완료와 LLM 가용성도 봅니다. 그 둘을
    함께 세우지 않으면 CI 처럼 Ollama 가 없는 환경에서 degraded 가 나옵니다.
    로컬에 Ollama 가 떠 있으면 우연히 통과하므로 반드시 명시적으로 세웁니다.
    """
    for name in (
        "_check_mysql",
        "_check_redis",
        "_check_meilisearch",
        "_check_model_registry",
        "_check_chromadb",
    ):
        monkeypatch.setattr(health, name, lambda: None)

    monkeypatch.setattr(
        health,
        "_check_llm",
        lambda: {"ok": True, "provider": "test", "detail": None, "latency_ms": 0.0},
    )
    health.warmup_state.mark_llm_done()
    health.warmup_state.mark_predictor_done()
    health.warmup_state.mark_vector_done()
    monkeypatch.setattr(health.warmup_state, "_started", True, raising=False)


def test_liveness_ignores_dependency_failures(monkeypatch):
    def unavailable():
        raise RuntimeError("secret connection detail")

    for name in (
        "_check_mysql",
        "_check_redis",
        "_check_meilisearch",
        "_check_model_registry",
        "_check_chromadb",
    ):
        monkeypatch.setattr(health, name, unavailable)

    response = client.get("/api/v1/health/live")

    assert response.status_code == 200
    assert response.json() == {"status": "alive"}


def test_readiness_is_ready_when_all_checks_pass(monkeypatch):
    _patch_checks_healthy(monkeypatch)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert set(data["checks"]) == {
        "mysql",
        "redis",
        "meilisearch",
        "model_registry",
        "chromadb",
    }
    assert all(check["ok"] is True for check in data["checks"].values())
    assert all(check["detail"] is None for check in data["checks"].values())
    assert all(isinstance(check["latency_ms"], float) for check in data["checks"].values())


def test_readiness_is_not_ready_when_mysql_fails(monkeypatch):
    _patch_checks_healthy(monkeypatch)

    def mysql_failure():
        raise RuntimeError("mysql://user:password@host/database")

    monkeypatch.setattr(health, "_check_mysql", mysql_failure)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["mysql"]["ok"] is False
    assert data["checks"]["mysql"]["detail"] == "RuntimeError: dependency_check_failed"
    assert "password" not in data["checks"]["mysql"]["detail"]


def test_readiness_is_degraded_when_only_meilisearch_fails(monkeypatch):
    _patch_checks_healthy(monkeypatch)

    def meilisearch_failure():
        raise ConnectionError("http://master-key@meilisearch:7700")

    monkeypatch.setattr(health, "_check_meilisearch", meilisearch_failure)

    response = client.get("/api/v1/health/ready")

    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "degraded"
    assert data["checks"]["meilisearch"]["ok"] is False
    assert data["checks"]["meilisearch"]["detail"] == "ConnectionError: dependency_check_failed"


_HANG_SECONDS = 2.0


def test_readiness_times_out_without_hanging(monkeypatch):
    _patch_checks_healthy(monkeypatch)
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.02)

    def slow_mysql():
        return None

    async def controlled_to_thread(check):
        if check is slow_mysql:
            # 행이 걸렸을 때와 타임아웃했을 때의 차이를 크게 벌립니다. 아래
            # 벽시계 단언은 러너 부하와 커버리지 계측 오버헤드를 함께 견뎌야
            # 하는데, 대비가 작으면 정상 동작에서도 실패합니다. 2026-09-02 에
            # CI 의 py3.11 러너에서 0.29초가 나와 0.08초 단언이 깨졌습니다.
            await health.asyncio.sleep(_HANG_SECONDS)
        else:
            check()

    monkeypatch.setattr(health, "_check_mysql", slow_mysql)
    monkeypatch.setattr(health.asyncio, "to_thread", controlled_to_thread)
    started_at = time.perf_counter()

    response = client.get("/api/v1/health/ready")

    elapsed = time.perf_counter() - started_at
    # 타임아웃이 실제로 걸렸다는 증거는 아래 503 과 TimeoutError 단언입니다.
    # 이 단언은 행이 걸리지 않았다는 것만 확인하므로 여유를 크게 둡니다.
    assert elapsed < _HANG_SECONDS / 2
    assert response.status_code == 503
    data = response.json()
    assert data["status"] == "not_ready"
    assert data["checks"]["mysql"]["detail"] == "TimeoutError: timeout"
