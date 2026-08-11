"""Docker Compose의 Arq 워커 배선 계약을 검증합니다."""

from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def _worker_service() -> str:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    return compose.split("\n  worker:\n", maxsplit=1)[1].split("\n  frontend:\n", maxsplit=1)[0]


def test_default_compose_runs_arq_worker_with_shared_services_and_assets():
    worker = _worker_service()

    assert 'command: ["arq", "src.tasks.worker.WorkerSettings"]' in worker
    assert "DATABASE_URL=mysql+pymysql://root:${MYSQL_ROOT_PASSWORD:-rootpassword}@db:3306/procurement" in worker
    assert "DB_PASSWORD=${MYSQL_ROOT_PASSWORD:-rootpassword}" in worker
    assert "SECRET_KEY=${SECRET_KEY:?SECRET_KEY must be set in .env}" in worker
    assert "REDIS_URL=redis://redis:6379/0" in worker
    assert "CHROMA_DB_PATH=/app/chroma_db" in worker
    assert "./ml_registry:/app/ml_registry" in worker
    assert "./data:/app/data" in worker
    assert "./chroma_db:/app/chroma_db" in worker


def test_default_compose_refreshes_data_but_disables_full_validation_and_retraining():
    worker = _worker_service()

    assert "AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED=true" in worker
    assert "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=false" in worker
    assert "ML_WEEKLY_RETRAIN_ENABLED=false" in worker


def test_default_compose_waits_for_shared_services_to_be_healthy():
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    assert compose.count("condition: service_healthy") == 7
    assert compose.count("SECRET_KEY=${SECRET_KEY:?SECRET_KEY must be set in .env}") == 2
    assert '["CMD", "redis-cli", "ping"]' in compose
    assert '["CMD", "curl", "--fail", "--silent", "--show-error", "http://localhost:7700/health"]' in compose
    assert "http://localhost:7700/health" in compose
    assert "http://localhost:8000/api/v1/health" in compose
    assert "json.load(response)['status'] == 'healthy'" in compose
