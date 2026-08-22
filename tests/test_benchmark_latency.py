from scripts import benchmark_latency
from scripts.benchmark_latency import Samples, _query_for_round


def test_latency_target_fails_when_any_request_errors():
    samples = Samples("test", values=[10.0, 12.0], errors=1)

    assert samples.report(target_ms=100.0) is False


def test_benchmark_queries_are_unique_across_repeated_base_queries():
    queries = [_query_for_round(index) for index in range(20)]

    assert len(set(queries)) == 20


def test_latency_evidence_contains_raw_values_and_percentiles():
    samples = Samples("test", values=[10.0, 20.0, 30.0])

    evidence = samples.as_dict()

    assert evidence["values_ms"] == [10.0, 20.0, 30.0]
    assert evidence["p95_ms"] == 29.0


def test_reproducibility_metadata_marks_failed_docker_lookup_unknown(monkeypatch):
    def fail_docker(command: list[str]) -> str:
        return "unknown" if command[0] == "docker" else "abc123"

    monkeypatch.setattr(benchmark_latency, "_command_output", fail_docker)

    metadata = benchmark_latency.reproducibility_metadata()

    assert metadata["git_sha"] == "abc123"
    assert metadata["docker_image_id"] == "unknown"
    assert set(metadata) == {
        "git_sha",
        "measured_at_utc",
        "python_version",
        "platform",
        "docker_image_id",
        "gc",
        "instrumentation",
    }


def test_reproducibility_metadata_marks_empty_docker_lookup_unknown(monkeypatch):
    monkeypatch.setattr(
        benchmark_latency.subprocess, "check_output", lambda _command, **_kwargs: ""
    )

    assert (
        benchmark_latency._command_output(["docker", "compose", "images", "-q", "backend"])
        == "unknown"
    )
