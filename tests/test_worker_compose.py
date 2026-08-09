"""Docker Compose의 Arq 워커 배선 계약을 검증합니다."""

from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def _worker_service() -> str:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    return compose.split("\n  worker:\n", maxsplit=1)[1].split("\n  frontend:\n", maxsplit=1)[0]


def test_default_compose_runs_arq_worker_with_shared_services_and_assets():
    worker = _worker_service()

    assert 'command: ["arq", "src.tasks.worker.WorkerSettings"]' in worker
    assert "DATABASE_URL=mysql+pymysql://root:rootpassword@db:3306/procurement" in worker
    assert "REDIS_URL=redis://redis:6379/0" in worker
    assert "CHROMA_DB_PATH=/app/chroma_db" in worker
    assert "./ml_registry:/app/ml_registry" in worker
    assert "./data:/app/data" in worker
    assert "./chroma_db:/app/chroma_db" in worker


def test_default_compose_disables_scheduled_jobs_until_explicitly_enabled():
    worker = _worker_service()

    assert "AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=false" in worker
    assert "ML_WEEKLY_RETRAIN_ENABLED=false" in worker
