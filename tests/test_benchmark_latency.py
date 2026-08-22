from scripts import benchmark_latency
from scripts.benchmark_latency import Samples, _query_for_round, benchmark_predict, build_evidence


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


def test_host_load_metadata_marks_unavailable_load(monkeypatch):
    monkeypatch.setattr(benchmark_latency.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(benchmark_latency.os, "getloadavg", lambda: (_ for _ in ()).throw(OSError))

    metadata = benchmark_latency.host_load_metadata()

    assert metadata["cpu_count"] == 8
    assert metadata["load_1m"] is None
    assert metadata["per_core_percent"] is None


def test_predict_warmup_matches_concurrency_and_is_excluded(monkeypatch):
    calls: list[int] = []

    class Response:
        status_code = 200

    def post(_url: str, *, json: dict[str, int | str], timeout: float) -> Response:
        calls.append(json["presumed_price"])
        return Response()

    monkeypatch.setattr(benchmark_latency.httpx, "post", post)

    samples = benchmark_predict("http://test", rounds=3, concurrency=2)

    assert len(calls) == 5
    assert len(samples.values) == 3
    assert sorted(calls[:2]) == [499_999_998, 499_999_999]


def test_evidence_records_predict_execution_and_host_load(monkeypatch):
    monkeypatch.setattr(benchmark_latency, "reproducibility_metadata", lambda: {"git_sha": "abc"})
    monkeypatch.setattr(
        benchmark_latency,
        "host_load_metadata",
        lambda: {"load_1m": 1.0, "cpu_count": 8, "per_core_percent": 12.5},
    )
    sample = Samples("test", values=[1.0])

    evidence = build_evidence("http://test", 600, 10, sample, sample, sample, sample, sample)

    assert evidence["predict_rounds"] == 600
    assert evidence["predict_concurrency"] == 10
    assert evidence["predict_warmup_requests"] == 10
    assert evidence["meta"]["git_sha"] == "abc"
    assert evidence["meta"]["host_load"]["per_core_percent"] == 12.5


def test_reproducibility_metadata_marks_empty_docker_lookup_unknown(monkeypatch):
    monkeypatch.setattr(
        benchmark_latency.subprocess, "check_output", lambda _command, **_kwargs: ""
    )

    assert (
        benchmark_latency._command_output(["docker", "compose", "images", "-q", "backend"])
        == "unknown"
    )
