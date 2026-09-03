from pathlib import Path

import pytest
import yaml

COMPOSE_PATH = Path(__file__).parents[1] / "docker-compose.prod.yml"


@pytest.fixture(scope="module")
def compose() -> dict:
    with COMPOSE_PATH.open(encoding="utf-8") as compose_file:
        parsed = yaml.safe_load(compose_file)
    assert isinstance(parsed, dict)
    return parsed


def _environment(service: dict) -> dict[str, str]:
    environment = service.get("environment", {})
    if isinstance(environment, dict):
        return {str(key): str(value) for key, value in environment.items()}
    return {key: value for entry in environment for key, value in [entry.split("=", 1)]}


def _healthcheck_command(service: dict) -> str:
    test = service["healthcheck"]["test"]
    return " ".join(str(part) for part in test)


def test_data_tier_isolated_and_application_services_have_egress(compose: dict):
    networks = compose["networks"]
    assert networks["internal"]["internal"] is True
    assert networks["egress"].get("internal", False) is False

    services = compose["services"]
    assert services["db"]["networks"] == ["internal"]
    assert services["redis"]["networks"] == ["internal"]
    assert services["meilisearch"]["networks"] == ["internal"]
    assert services["app"]["networks"] == ["internal", "egress"]
    assert services["worker"]["networks"] == ["internal", "egress"]
    assert services["proxy"]["networks"] == ["egress"]


def test_app_readiness_requires_ready_and_production_gates(compose: dict):
    app = compose["services"]["app"]
    app_healthcheck = _healthcheck_command(app)
    assert "['status'] == 'ready'" in app_healthcheck
    assert "degraded" not in app_healthcheck

    environment = _environment(app)
    assert environment["READINESS_REQUIRE_WARMUP"] == "true"
    assert environment["READINESS_REQUIRE_LLM"] == "true"


def test_worker_healthcheck_requires_fresh_heartbeat(compose: dict):
    worker = compose["services"]["worker"]
    healthcheck = _healthcheck_command(worker)
    assert "r.ping()" in healthcheck
    assert "bidbox:worker:heartbeat" in healthcheck
    assert "last_seen_at" in healthcheck
    assert "WORKER_HEARTBEAT_MAX_AGE_SECONDS" in healthcheck
    assert "age_seconds" in healthcheck

    environment = _environment(worker)
    assert "WORKER_HEARTBEAT_MAX_AGE_SECONDS" in environment
