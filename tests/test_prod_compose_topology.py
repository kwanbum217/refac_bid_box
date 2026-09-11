import json
from pathlib import Path

import pytest
import yaml

from src.app.core.observability import (
    DB_CLIENT_OPERATION_DURATION,
    HTTP_SERVER_REQUEST_COUNT,
    HTTP_SERVER_REQUEST_DURATION,
)

REPO_ROOT = Path(__file__).parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.prod.yml"
COLLECTOR_CONFIG_PATH = REPO_ROOT / "docker" / "otel-collector-config.yaml"
PROMETHEUS_CONFIG_PATH = REPO_ROOT / "docker" / "prometheus.yml"
GRAFANA_PROMETHEUS_DATASOURCE_PATH = (
    REPO_ROOT / "docker" / "grafana" / "provisioning" / "datasources" / "prometheus.yaml"
)
GRAFANA_DASHBOARD_PROVIDER_PATH = (
    REPO_ROOT / "docker" / "grafana" / "provisioning" / "dashboards" / "dashboards.yaml"
)
GRAFANA_HTTP_DB_DASHBOARD_PATH = (
    REPO_ROOT / "docker" / "grafana" / "dashboards" / "http_db_latency.json"
)
PROMETHEUS_RULES_PATH = REPO_ROOT / "docker" / "prometheus_rules.yml"
ALERTMANAGER_CONFIG_PATH = REPO_ROOT / "docker" / "alertmanager.yml"
GRAFANA_SLO_DASHBOARD_PATH = REPO_ROOT / "docker" / "grafana" / "dashboards" / "slo_alerts.json"


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
    for name in ("otel-collector", "tempo", "prometheus", "alertmanager", "grafana"):
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
        "./docker/prometheus_rules.yml:/etc/prometheus/prometheus_rules.yml:ro",
        "prometheus_data:/prometheus",
    ]
    assert "otel-collector" in _depends_on_names(prometheus)
    assert "alertmanager" in _depends_on_names(prometheus)
    assert compose["volumes"]["prometheus_data"] is None

    assert collector["expose"] == ["8889"]
    assert "ports" not in collector

    scrape = _load_yaml(PROMETHEUS_CONFIG_PATH)
    assert scrape["global"]["scrape_interval"] == "15s"
    assert scrape["rule_files"] == ["/etc/prometheus/prometheus_rules.yml"]
    assert scrape["alerting"]["alertmanagers"][0]["static_configs"][0]["targets"] == [
        "alertmanager:9093"
    ]
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


def test_grafana_provisions_http_db_latency_dashboard(compose: dict):
    grafana = compose["services"]["grafana"]
    volumes = grafana["volumes"]
    assert (
        "./docker/grafana/provisioning/dashboards:"
        "/etc/grafana/provisioning/dashboards:ro" in volumes
    )
    assert "./docker/grafana/dashboards:/var/lib/grafana/dashboards:ro" in volumes

    provider = _load_yaml(GRAFANA_DASHBOARD_PROVIDER_PATH)
    assert provider["providers"][0]["options"]["path"] == "/var/lib/grafana/dashboards"

    dashboard = json.loads(GRAFANA_HTTP_DB_DASHBOARD_PATH.read_text(encoding="utf-8"))
    assert dashboard["uid"] == "bidbox-http-db-latency"
    assert dashboard["title"] == "HTTP and DB latency"
    exprs = [
        str(target.get("expr", ""))
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]
    joined = "\n".join(exprs)
    http_duration = HTTP_SERVER_REQUEST_DURATION.replace(".", "_") + "_seconds"
    db_duration = DB_CLIENT_OPERATION_DURATION.replace(".", "_") + "_seconds"
    http_count = HTTP_SERVER_REQUEST_COUNT.replace(".", "_") + "_total"
    assert http_duration in joined
    assert db_duration in joined
    assert http_count in joined
    assert "histogram_quantile(0.95" in joined
    assert "http_route" in joined
    assert "db_operation" in joined
    assert "/api/v1/bids/" not in joined


def test_prometheus_slo_alert_rules_use_g3_thresholds(compose: dict):
    rules = _load_yaml(PROMETHEUS_RULES_PATH)
    alerts = {item["alert"]: item for item in rules["groups"][0]["rules"]}
    assert set(alerts) == {
        "PredictHttpP95High",
        "PredictHttpErrorRateHigh",
        "ChatStreamHttpP95High",
        "OtelCollectorDown",
    }

    http_duration = HTTP_SERVER_REQUEST_DURATION.replace(".", "_") + "_seconds"
    http_count = HTTP_SERVER_REQUEST_COUNT.replace(".", "_") + "_total"
    predict_p95 = alerts["PredictHttpP95High"]["expr"]
    predict_errors = alerts["PredictHttpErrorRateHigh"]["expr"]
    sse_p95 = alerts["ChatStreamHttpP95High"]["expr"]

    assert http_duration in predict_p95
    assert 'http_route="/predictions/predict"' in predict_p95
    assert "> 0.1" in predict_p95
    assert http_count in predict_errors
    assert 'http_response_status_code=~"5.."' in predict_errors
    assert "> 0.001" in predict_errors
    assert 'http_route="/chatbot/chat/stream"' in sse_p95
    assert "> 20" in sse_p95
    assert "/api/v1/bids/" not in predict_p95
    assert alerts["PredictHttpP95High"]["for"] == "10m"
    assert alerts["OtelCollectorDown"]["expr"].strip() == 'up{job="otel-collector"} == 0'


def test_alertmanager_holds_alerts_without_host_publish(compose: dict):
    alertmanager = compose["services"]["alertmanager"]
    assert alertmanager["image"].startswith("prom/alertmanager:")
    assert "@sha256:" in alertmanager["image"]
    assert alertmanager["restart"] == "unless-stopped"
    assert alertmanager["expose"] == ["9093"]
    assert "ports" not in alertmanager
    assert alertmanager["networks"] == ["internal"]
    assert alertmanager["volumes"] == [
        "./docker/alertmanager.yml:/etc/alertmanager/alertmanager.yml:ro",
        "./docker/secrets/alertmanager_slack_url:/etc/alertmanager/secrets/slack_url:ro",
        "alertmanager_data:/alertmanager",
    ]
    assert compose["volumes"]["alertmanager_data"] is None
    assert "--cluster.listen-address=" in alertmanager["command"]

    # 기본 수신기는 여전히 local-hold 다. Slack 은 critical 만 받는 자식 라우트이며
    # 나머지 심각도는 밖으로 나가지 않는다. 모든 알람을 보내면 채널이 잠겨
    # 정작 중요한 것이 묻힌다.
    config = _load_yaml(ALERTMANAGER_CONFIG_PATH)
    assert config["route"]["receiver"] == "local-hold"
    assert config["route"]["routes"] == [
        {"receiver": "slack-slo", "matchers": ["severity = critical"]}
    ]
    receivers = {r["name"]: r for r in config["receivers"]}
    assert set(receivers) == {"local-hold", "slack-slo"}
    assert receivers["local-hold"] == {"name": "local-hold"}

    # 비밀값은 설정 파일이 아니라 파일 참조로만 들어온다.
    slack_cfg = receivers["slack-slo"]["slack_configs"][0]
    assert slack_cfg["api_url_file"] == "/etc/alertmanager/secrets/slack_url"
    assert "api_url" not in slack_cfg
    assert "hooks.slack.com" not in ALERTMANAGER_CONFIG_PATH.read_text(encoding="utf-8")


def test_grafana_provisions_slo_alerts_dashboard():
    dashboard = json.loads(GRAFANA_SLO_DASHBOARD_PATH.read_text(encoding="utf-8"))
    assert dashboard["uid"] == "bidbox-slo-alerts"
    assert dashboard["title"] == "SLO and alerts"
    exprs = [
        str(target.get("expr", ""))
        for panel in dashboard["panels"]
        for target in panel.get("targets", [])
    ]
    joined = "\n".join(exprs)
    http_duration = HTTP_SERVER_REQUEST_DURATION.replace(".", "_") + "_seconds"
    http_count = HTTP_SERVER_REQUEST_COUNT.replace(".", "_") + "_total"
    assert "ALERTS{slo!=" in joined
    assert http_duration in joined
    assert http_count in joined
    assert "/predictions/predict" in joined
    assert "/chatbot/chat/stream" in joined
    assert "/api/v1/predictions/predict" not in joined
    assert "/api/v1/bids/" not in joined
