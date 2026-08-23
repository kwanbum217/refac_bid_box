import pytest

from scripts import benchmark_sse_gate
from scripts.benchmark_latency import BuildProvenanceError


def test_sse_reproducibility_metadata_contract(monkeypatch):
    commands_executed: list[list[str]] = []

    def command_output(command: list[str]) -> str:
        commands_executed.append(command)
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:image"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_app_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_app_123"]:
            return "sha256:image_cnt"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt_app_123"]:
            return "/app_container"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_app_123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt_app_123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        if command == ["docker", "inspect", "-f", "{{.NetworkSettings.IPAddress}}", "cnt_app_123"]:
            return "172.18.0.2"
        if command == ["docker", "inspect", "-f", "{{json .RepoDigests}}", "sha256:image_cnt"]:
            return '["refac_bid_box-app@sha256:img_digest"]'
        return "unknown"

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", command_output)

    metadata = benchmark_sse_gate.reproducibility_metadata(
        service_name="app",
        strict=True,
        base_url="http://127.0.0.1:8000",
    )

    assert metadata["git_sha"] == "sha"
    assert metadata["docker_image_id"] == "sha256:image"
    assert metadata["container_id"] == "cnt_app_123"
    assert metadata["target_container_image_id"] == "sha256:image_cnt"
    assert metadata["image_digest"] == "refac_bid_box-app@sha256:img_digest"
    assert metadata["container_name"] == "app_container"
    assert metadata["bound_port"] == 8000

    # compose service 이름 'app' 조회(backend 아님)를 검증합니다.
    assert ["docker", "compose", "images", "-q", "app"] in commands_executed
    assert ["docker", "compose", "ps", "-q", "app"] in commands_executed
    assert ["docker", "compose", "images", "-q", "backend"] not in commands_executed


def test_sse_reproducibility_metadata_handles_docker_lookup_failure(monkeypatch):
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _command: "unknown")

    meta = benchmark_sse_gate.reproducibility_metadata(strict=False)
    assert meta["docker_image_id"] == "unknown"
    assert meta["container_id"] == "unknown"
    assert meta["target_container_image_id"] == "unknown"


def test_sse_reproducibility_metadata_strict_raises_error_on_unknown(monkeypatch):
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _command: "unknown")

    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_sse_gate.reproducibility_metadata(strict=True)
    assert "lookup failed or returned unknown" in str(excinfo.value)


def test_sse_reproducibility_metadata_port_mismatch_fails(monkeypatch):
    def mock_command(command: list[str]) -> str:
        if command == ["git", "rev-parse", "HEAD"]:
            return "sha"
        if command == ["docker", "compose", "images", "-q", "app"]:
            return "sha256:image"
        if command == ["docker", "compose", "ps", "-q", "app"]:
            return "cnt_app_123"
        if command == ["docker", "inspect", "-f", "{{.Image}}", "cnt_app_123"]:
            return "sha256:image_cnt"
        if command == ["docker", "inspect", "-f", "{{.Name}}", "cnt_app_123"]:
            return "/app_container"
        if command == ["docker", "inspect", "-f", "{{.State.Running}}", "cnt_app_123"]:
            return "true"
        if command == ["docker", "inspect", "-f", "{{json .NetworkSettings.Ports}}", "cnt_app_123"]:
            return '{"8000/tcp":[{"HostIp":"0.0.0.0","HostPort":"8000"}]}'
        return "unknown"

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", mock_command)

    with pytest.raises(BuildProvenanceError) as excinfo:
        benchmark_sse_gate.reproducibility_metadata(
            service_name="app",
            strict=True,
            base_url="http://127.0.0.1:8080",
        )
    assert "port 8080 not bound" in str(excinfo.value)


def test_sse_empty_docker_lookup_is_unknown(monkeypatch):
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _command: "unknown")

    assert (
        benchmark_sse_gate._command_output(["docker", "compose", "images", "-q", "app"])
        == "unknown"
    )


def test_benchmark_sse_gate_main_provenance_failure_returns_code_2(monkeypatch):
    class MockHealthResponse:
        status_code = 200

        def raise_for_status(self):
            pass

    monkeypatch.setattr(benchmark_sse_gate.httpx, "get", lambda *a, **kw: MockHealthResponse())
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _cmd: "unknown")
    monkeypatch.setattr(
        benchmark_sse_gate.sys,
        "argv",
        ["benchmark_sse_gate.py", "--base-url", "http://127.0.0.1:8000"],
    )

    exit_code = benchmark_sse_gate.main()
    assert exit_code == 2
