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
