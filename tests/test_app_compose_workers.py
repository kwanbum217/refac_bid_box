"""Docker Compose app 서비스의 Uvicorn 워커 수 조정 계약을 검증합니다."""

from pathlib import Path

COMPOSE_FILE = Path(__file__).resolve().parents[1] / "docker-compose.yml"
DOCKERFILE = Path(__file__).resolve().parents[1] / "Dockerfile"


def _app_service() -> str:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    return compose.split("\n  app:\n", maxsplit=1)[1].split("\n  worker:\n", maxsplit=1)[0]


def _worker_service() -> str:
    compose = COMPOSE_FILE.read_text(encoding="utf-8")
    return compose.split("\n  worker:\n", maxsplit=1)[1].split("\n  frontend:\n", maxsplit=1)[0]


def test_app_command_uses_exec_form_array_not_shell_string():
    """command 가 배열(exec) 형태여야 셸을 거치지 않아 값 주입·확장 여지가 없습니다."""
    app = _app_service()

    assert "command:\n      - python3\n      - -m\n      - uvicorn\n" in app
    # 셸 형태(`command: python3 -m uvicorn ...` 한 줄 문자열)가 아님을 재확인합니다.
    assert "command: python3" not in app
    assert '"sh", "-c"' not in app
    assert "/bin/sh" not in app


def test_app_command_exposes_web_concurrency_with_default_three():
    app = _app_service()

    assert '"${WEB_CONCURRENCY:-3}"' in app
    assert "--workers" in app
    # host/port 는 기존 계약과 동일하게 유지됩니다.
    assert '"0.0.0.0"' in app
    assert '"8000"' in app


def test_app_command_targets_same_entrypoint_module_as_dockerfile():
    app = _app_service()
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "src.app.main:app" in app
    assert "src.app.main:app" in dockerfile


def test_dockerfile_direct_run_contract_stays_single_worker_and_unmodified():
    """개발/테스트에서 `docker run`으로 직접 기동할 때의 계약은 이번 변경과 무관해야 합니다."""
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert (
        'CMD ["python3", "-m", "uvicorn", "src.app.main:app", "--host", "0.0.0.0", "--port", "8000"]'
        in dockerfile
    )
    assert "--workers" not in dockerfile
    assert "WEB_CONCURRENCY" not in dockerfile


def test_worker_arq_service_is_not_affected_by_web_concurrency():
    """WEB_CONCURRENCY 조정은 app 전용이며 Arq 워커 서비스는 그대로여야 합니다."""
    worker = _worker_service()

    assert 'command: ["arq", "src.tasks.worker.WorkerSettings"]' in worker
    assert "WEB_CONCURRENCY" not in worker
    assert "--workers" not in worker


def test_web_concurrency_interpolation_only_appears_in_app_service():
    compose = COMPOSE_FILE.read_text(encoding="utf-8")

    assert compose.count("${WEB_CONCURRENCY:-3}") == 1
