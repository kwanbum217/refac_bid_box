"""tests/test_observability_dev_stack.py

개발 compose 의 관측성 프로파일 정합성을 검증합니다.

검증 항목:
1. 네 서비스(otel-collector, tempo, prometheus, grafana)가 observability 프로파일에 있다
2. 프로파일을 지정하지 않는 기본 기동 대상이 늘어나지 않는다
3. 개발 Prometheus 설정이 운영과 스크랩 대상 및 규칙 파일을 공유한다
4. 개발 스택은 alertmanager 를 참조하지 않는다 (비밀 파일 의존 회피)
5. 관측성 서비스가 요구하는 볼륨이 선언되어 있다
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEV_COMPOSE = PROJECT_ROOT / "docker-compose.yml"
PROD_COMPOSE = PROJECT_ROOT / "docker-compose.prod.yml"
PROM_DEV = PROJECT_ROOT / "docker" / "prometheus.dev.yml"
PROM_PROD = PROJECT_ROOT / "docker" / "prometheus.yml"

OBSERVABILITY_SERVICES = ("otel-collector", "tempo", "prometheus", "grafana")
PROFILE = "observability"

# 프로파일 없이 docker compose up 을 했을 때 뜨는 서비스. 관측성 도입으로 늘어나면
# 개발 기동 비용이 오르므로 목록을 고정합니다.
DEFAULT_SERVICES = {"app", "worker", "db", "redis", "meilisearch"}


def load(path: Path) -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


@pytest.fixture(scope="module")
def dev_compose() -> dict:
    return load(DEV_COMPOSE)


@pytest.mark.parametrize("service", OBSERVABILITY_SERVICES)
def test_observability_service_is_profile_gated(dev_compose: dict, service: str):
    """관측성 서비스는 observability 프로파일에만 속합니다."""
    services = dev_compose["services"]
    assert service in services, f"개발 compose 에 {service} 서비스가 있어야 합니다."
    profiles = services[service].get("profiles")
    assert profiles == [PROFILE], (
        f"{service} 는 profiles: ['{PROFILE}'] 이어야 합니다 (현재: {profiles})."
    )


def test_default_startup_set_is_unchanged(dev_compose: dict):
    """프로파일이 없는 서비스 집합이 늘어나지 않았습니다."""
    default = {name for name, spec in dev_compose["services"].items() if not spec.get("profiles")}
    assert default == DEFAULT_SERVICES, (
        f"기본 기동 대상이 바뀌었습니다. 늘리려면 기동 비용을 함께 판단하십시오: {default}"
    )


def test_dev_prometheus_shares_scrape_and_rules_with_prod():
    """개발 Prometheus 설정이 운영과 스크랩 대상 및 규칙 파일을 공유합니다."""
    dev = load(PROM_DEV)
    prod = load(PROM_PROD)
    assert dev["scrape_configs"] == prod["scrape_configs"], (
        "개발과 운영의 스크랩 대상이 다릅니다. 두 설정이 조용히 어긋나면 "
        "로컬에서 본 지표가 운영과 달라집니다."
    )
    assert dev["rule_files"] == prod["rule_files"], "규칙 파일 목록이 운영과 같아야 합니다."


def test_dev_stack_does_not_reference_alertmanager(dev_compose: dict):
    """개발 스택은 alertmanager 를 두지 않고 설정도 참조하지 않습니다."""
    assert "alertmanager" not in dev_compose["services"]
    assert "alerting" not in load(PROM_DEV), (
        "개발 Prometheus 에 alerting 블록이 있으면 존재하지 않는 alertmanager 를 "
        "계속 조회해 오류 로그가 쌓입니다."
    )
    prometheus = dev_compose["services"]["prometheus"]
    mounted = " ".join(prometheus.get("volumes", []))
    assert "prometheus.dev.yml" in mounted, (
        "개발 prometheus 는 docker/prometheus.dev.yml 을 마운트해야 합니다."
    )


def test_observability_volumes_declared(dev_compose: dict):
    """관측성 서비스가 쓰는 볼륨이 선언되어 있습니다."""
    volumes = set(dev_compose.get("volumes") or {})
    for name in ("tempo_data", "prometheus_data", "grafana_data"):
        assert name in volumes, f"{name} 볼륨 선언이 필요합니다."


def test_prod_compose_still_runs_observability_unconditionally():
    """운영 compose 는 관측성을 프로파일로 가리지 않습니다."""
    services = load(PROD_COMPOSE)["services"]
    for service in (*OBSERVABILITY_SERVICES, "alertmanager"):
        assert service in services, f"운영 compose 에 {service} 가 있어야 합니다."
        assert not services[service].get("profiles"), (
            f"운영의 {service} 는 항상 기동 대상이어야 합니다."
        )
