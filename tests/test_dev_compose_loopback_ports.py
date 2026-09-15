"""개발용 docker-compose.yml 의 포트 바인딩이 127.0.0.1 로컬 루프백으로 한정되었는지 검증합니다."""

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_PATH = REPO_ROOT / "docker-compose.yml"


@pytest.fixture(scope="module")
def dev_compose() -> dict:
    with COMPOSE_PATH.open(encoding="utf-8") as compose_file:
        parsed = yaml.safe_load(compose_file)
    assert isinstance(parsed, dict)
    return parsed


def test_all_published_ports_bind_to_localhost_loopback(dev_compose: dict):
    """docker-compose.yml 의 모든 ports 항목이 127.0.0.1 로 시작함을 검사합니다."""
    services = dev_compose.get("services", {})
    assert services, "docker-compose.yml 에 서비스가 정의되어 있어야 합니다."

    total_ports_count = 0
    services_with_ports = []

    for name, service in services.items():
        ports = service.get("ports")
        if not ports:
            continue

        services_with_ports.append(name)
        for port_entry in ports:
            port_str = str(port_entry)
            total_ports_count += 1
            assert port_str.startswith("127.0.0.1:"), (
                f"서비스 '{name}'의 포트 매핑 '{port_str}'이 127.0.0.1 로 시작하지 않습니다."
            )

    # 8개 서비스 (app, frontend, db, redis, meilisearch, otel-collector, prometheus, grafana) 총 9개 포트
    assert len(services_with_ports) == 8
    assert total_ports_count == 9


def test_specific_services_loopback_port_mappings(dev_compose: dict):
    """각 서비스별 호스트 및 컨테이너 포트 번호가 유지된 채 127.0.0.1 로 바인딩되었는지 단언합니다."""
    services = dev_compose["services"]

    expected_mappings = {
        "app": ["127.0.0.1:8000:8000"],
        "frontend": ["127.0.0.1:5173:5173"],
        "db": ["127.0.0.1:3306:3306"],
        "redis": ["127.0.0.1:6379:6379"],
        "meilisearch": ["127.0.0.1:7700:7700"],
        "otel-collector": ["127.0.0.1:4317:4317", "127.0.0.1:4318:4318"],
        "prometheus": ["127.0.0.1:9090:9090"],
        "grafana": ["127.0.0.1:3000:3000"],
    }

    for service_name, expected_ports in expected_mappings.items():
        assert service_name in services, f"서비스 '{service_name}'가 정의되어 있지 않습니다."
        actual_ports = [str(p) for p in services[service_name].get("ports", [])]
        assert actual_ports == expected_ports, (
            f"서비스 '{service_name}'의 포트 설정이 올바르지 않습니다: {actual_ports} != {expected_ports}"
        )


def test_internal_worker_and_tempo_have_no_ports_published(dev_compose: dict):
    """호스트 포트 노출이 불필요한 서비스(worker, tempo)에 ports 항목이 없음을 검증합니다."""
    services = dev_compose["services"]

    assert "ports" not in services.get("worker", {})
    assert "ports" not in services.get("tempo", {})
