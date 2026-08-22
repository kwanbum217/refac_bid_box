from scripts import benchmark_latency
from scripts.benchmark_latency import (
    HostLoadMonitor,
    Samples,
    _query_for_round,
    benchmark_predict,
    build_evidence,
    compute_host_load_stats,
    host_load_metadata,
    single_host_load_sample,
)


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


def test_single_host_load_sample_marks_unavailable_load(monkeypatch):
    monkeypatch.setattr(benchmark_latency.os, "cpu_count", lambda: 8)
    monkeypatch.setattr(benchmark_latency.os, "getloadavg", lambda: (_ for _ in ()).throw(OSError))

    sample = single_host_load_sample()

    assert sample["cpu_count"] == 8
    assert sample["load_1m"] is None
    assert sample["per_core_percent"] is None
    assert "observed_at_utc" in sample


def test_single_host_load_sample_handles_missing_getloadavg(monkeypatch):
    monkeypatch.setattr(benchmark_latency.os, "cpu_count", lambda: 4)
    if hasattr(benchmark_latency.os, "getloadavg"):
        monkeypatch.delattr(benchmark_latency.os, "getloadavg")

    sample = single_host_load_sample()

    assert sample["cpu_count"] == 4
    assert sample["load_1m"] is None
    assert sample["per_core_percent"] is None


def test_compute_host_load_stats_calculates_min_median_max():
    samples = [
        {"observed_at_utc": "t1", "load_1m": 1.0, "cpu_count": 8, "per_core_percent": 12.5},
        {"observed_at_utc": "t2", "load_1m": 3.0, "cpu_count": 8, "per_core_percent": 37.5},
        {"observed_at_utc": "t3", "load_1m": 2.0, "cpu_count": 8, "per_core_percent": 25.0},
    ]

    stats = compute_host_load_stats(samples)

    assert stats["cpu_count"] == 8
    assert stats["samples"] == samples
    assert stats["load_1m"] == {"min": 1.0, "median": 2.0, "max": 3.0}
    assert stats["per_core_percent"] == {"min": 12.5, "median": 25.0, "max": 37.5}


def test_compute_host_load_stats_handles_unsupported_platform():
    samples = [
        {"observed_at_utc": "t1", "load_1m": None, "cpu_count": 8, "per_core_percent": None},
        {"observed_at_utc": "t2", "load_1m": None, "cpu_count": 8, "per_core_percent": None},
        {"observed_at_utc": "t3", "load_1m": None, "cpu_count": 8, "per_core_percent": None},
    ]

    stats = compute_host_load_stats(samples)

    assert stats["cpu_count"] == 8
    assert stats["samples"] == samples
    assert stats["load_1m"] == {"min": None, "median": None, "max": None}
    assert stats["per_core_percent"] == {"min": None, "median": None, "max": None}


def test_host_load_metadata_collects_samples_without_wait(monkeypatch):
    calls = 0

    def mock_sample():
        nonlocal calls
        calls += 1
        return {
            "observed_at_utc": f"t{calls}",
            "load_1m": float(calls),
            "cpu_count": 4,
            "per_core_percent": float(calls) * 25.0,
        }

    monkeypatch.setattr(benchmark_latency, "single_host_load_sample", mock_sample)

    metadata = host_load_metadata(min_samples=3, interval_seconds=0.0)

    assert calls == 3
    assert len(metadata["samples"]) == 3
    assert metadata["load_1m"] == {"min": 1.0, "median": 2.0, "max": 3.0}
    assert metadata["per_core_percent"] == {"min": 25.0, "median": 50.0, "max": 75.0}


def test_host_load_monitor_guarantees_minimum_samples():
    monitor = HostLoadMonitor(interval_seconds=0.001, min_samples=3)
    monitor.start()
    summary = monitor.stop()

    assert len(summary["samples"]) >= 3
    assert "min" in summary["load_1m"]
    assert "median" in summary["load_1m"]
    assert "max" in summary["load_1m"]
    assert "min" in summary["per_core_percent"]
    assert "median" in summary["per_core_percent"]
    assert "max" in summary["per_core_percent"]


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
    mock_host_load = {
        "cpu_count": 8,
        "samples": [
            {"observed_at_utc": "t1", "load_1m": 1.0, "cpu_count": 8, "per_core_percent": 12.5},
            {"observed_at_utc": "t2", "load_1m": 2.0, "cpu_count": 8, "per_core_percent": 25.0},
            {"observed_at_utc": "t3", "load_1m": 1.5, "cpu_count": 8, "per_core_percent": 18.75},
        ],
        "load_1m": {"min": 1.0, "median": 1.5, "max": 2.0},
        "per_core_percent": {"min": 12.5, "median": 18.75, "max": 25.0},
    }
    sample = Samples("test", values=[1.0])

    evidence = build_evidence(
        "http://test",
        600,
        10,
        sample,
        sample,
        sample,
        sample,
        sample,
        host_load=mock_host_load,
    )

    assert evidence["predict_rounds"] == 600
    assert evidence["predict_concurrency"] == 10
    assert evidence["predict_warmup_requests"] == 10
    assert evidence["meta"]["git_sha"] == "abc"
    assert evidence["meta"]["host_load"] == mock_host_load


def test_reproducibility_metadata_marks_empty_docker_lookup_unknown(monkeypatch):
    monkeypatch.setattr(
        benchmark_latency.subprocess, "check_output", lambda _command, **_kwargs: ""
    )

    assert (
        benchmark_latency._command_output(["docker", "compose", "images", "-q", "backend"])
        == "unknown"
    )
