from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.prod.yml"
COLLECTOR_CONFIG_PATH = REPO_ROOT / "docker" / "otel-collector-config.yaml"
PROMETHEUS_CONFIG_PATH = REPO_ROOT / "docker" / "prometheus.yml"
GRAFANA_PROMETHEUS_DATASOURCE_PATH = (
    REPO_ROOT / "docker" / "grafana" / "provisioning" / "datasources" / "prometheus.yaml"
)


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


def _depends_on_names(service: dict) -> set[str]:
    depends_on = service.get("depends_on", {})
    if isinstance(depends_on, dict):
        return set(depends_on)
    return set(depends_on)


def _load_yaml(path: Path) -> dict:
    with path.open(encoding="utf-8") as yaml_file:
        parsed = yaml.safe_load(yaml_file)
    assert isinstance(parsed, dict)
    return parsed


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


def test_observability_services_stay_on_internal_network(compose: dict):
    services = compose["services"]
    for name in ("otel-collector", "tempo", "prometheus", "grafana"):
        assert services[name]["networks"] == ["internal"]
        assert "ports" not in services[name]


def test_prometheus_scrapes_collector_without_host_publish(compose: dict):
    prometheus = compose["services"]["prometheus"]
    collector = compose["services"]["otel-collector"]

    assert prometheus["image"].startswith("prom/prometheus:")
    assert "@sha256:" in prometheus["image"]
    assert prometheus["restart"] == "unless-stopped"
    assert prometheus["volumes"] == [
        "./docker/prometheus.yml:/etc/prometheus/prometheus.yml:ro",
        "prometheus_data:/prometheus",
    ]
    assert "otel-collector" in _depends_on_names(prometheus)
    assert compose["volumes"]["prometheus_data"] is None

    assert collector["expose"] == ["8889"]
    assert "ports" not in collector

    scrape = _load_yaml(PROMETHEUS_CONFIG_PATH)
    assert scrape["global"]["scrape_interval"] == "15s"
    jobs = scrape["scrape_configs"]
    assert len(jobs) == 1
    assert jobs[0]["job_name"] == "otel-collector"
    assert jobs[0]["static_configs"][0]["targets"] == ["otel-collector:8889"]


def test_otel_collector_keeps_traces_and_adds_metrics_pipeline():
    config = _load_yaml(COLLECTOR_CONFIG_PATH)
    traces = config["service"]["pipelines"]["traces"]
    metrics = config["service"]["pipelines"]["metrics"]

    assert traces["receivers"] == ["otlp"]
    assert traces["processors"] == ["tail_sampling", "batch"]
    assert traces["exporters"] == ["otlp/tempo"]
    assert metrics["receivers"] == ["otlp"]
    assert metrics["processors"] == ["batch"]
    assert metrics["exporters"] == ["prometheus"]
    assert config["exporters"]["prometheus"]["endpoint"] == "0.0.0.0:8889"


def test_grafana_provisions_prometheus_datasource(compose: dict):
    grafana = compose["services"]["grafana"]
    assert (
        "./docker/grafana/provisioning/datasources:"
        "/etc/grafana/provisioning/datasources:ro" in grafana["volumes"]
    )
    assert "prometheus" in _depends_on_names(grafana)

    datasource = _load_yaml(GRAFANA_PROMETHEUS_DATASOURCE_PATH)
    entries = datasource["datasources"]
    assert len(entries) == 1
    assert entries[0]["type"] == "prometheus"
    assert entries[0]["url"] == "http://prometheus:9090"
