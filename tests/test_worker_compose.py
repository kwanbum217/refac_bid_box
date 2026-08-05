"""Docker Compose가 Arq 워커를 실제로 기동하는지 검증합니다."""

from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"


def test_default_compose_includes_arq_worker_with_disabled_schedules():
    """개발 Compose는 워커를 띄우되, 정기 수집·재학습은 명시적 활성화 전까지 막습니다."""
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    assert "  worker:\n" in compose
    assert 'command: ["arq", "src.tasks.worker.WorkerSettings"]' in compose
    assert "- AUTOMATION_NIGHTLY_SCHEDULE_ENABLED=false" in compose
    assert "- ML_WEEKLY_RETRAIN_ENABLED=false" in compose
