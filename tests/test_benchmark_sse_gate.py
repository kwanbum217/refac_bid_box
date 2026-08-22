from scripts import benchmark_sse_gate


def test_sse_reproducibility_metadata_contract(monkeypatch):
    def command_output(command: list[str]) -> str:
        return "sha" if command[0] == "git" else "sha256:image"

    monkeypatch.setattr(benchmark_sse_gate, "_command_output", command_output)

    metadata = benchmark_sse_gate.reproducibility_metadata()

    assert metadata["git_sha"] == "sha"
    assert metadata["docker_image_id"] == "sha256:image"
    assert set(metadata) == {
        "git_sha",
        "measured_at_utc",
        "python_version",
        "platform",
        "docker_image_id",
        "gc",
        "instrumentation",
    }


def test_sse_reproducibility_metadata_handles_docker_lookup_failure(monkeypatch):
    monkeypatch.setattr(benchmark_sse_gate, "_command_output", lambda _command: "unknown")

    assert benchmark_sse_gate.reproducibility_metadata()["docker_image_id"] == "unknown"


def test_sse_empty_docker_lookup_is_unknown(monkeypatch):
    monkeypatch.setattr(
        benchmark_sse_gate.subprocess, "check_output", lambda _command, **_kwargs: ""
    )

    assert (
        benchmark_sse_gate._command_output(["docker", "compose", "images", "-q", "backend"])
        == "unknown"
    )
