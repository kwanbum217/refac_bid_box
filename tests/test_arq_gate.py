"""scripts.arq_gate의 일관성 게이트 판정 회귀 테스트."""

from __future__ import annotations

import json

import pytest

from scripts.arq_gate import (
    GateThresholds,
    RepetitionThresholds,
    ThroughputGateResult,
    ThroughputSample,
    evaluate_benchmark_files,
    evaluate_repetition_gate,
    evaluate_throughput_gate,
    load_benchmark_samples,
    sample_from_benchmark_payload,
)


def _make_sample(
    tasks_total: int,
    tasks_failed: int,
    p95_ms: float,
    tasks_per_second: float = 100.0,
    error_count: int = 0,
) -> ThroughputSample:
    return ThroughputSample(
        tasks_total=tasks_total,
        tasks_failed=tasks_failed,
        latency_p95_ms=p95_ms,
        tasks_per_second=tasks_per_second,
        error_count=error_count,
    )


def _baseline_default() -> ThroughputSample:
    return _make_sample(tasks_total=1000, tasks_failed=5, p95_ms=20.0, tasks_per_second=100.0)


def _current_default() -> ThroughputSample:
    return _make_sample(tasks_total=1000, tasks_failed=5, p95_ms=20.0, tasks_per_second=98.0)


def test_all_metrics_pass_when_within_margins():
    baseline = _baseline_default()
    current = _current_default()
    result = evaluate_throughput_gate(
        baseline=baseline,
        current=current,
    )
    assert result.passed is True
    assert {v.metric for v in result.verdicts} == {"throughput", "p95_latency", "failure_rate"}


def test_throughput_drop_beyond_margin_fails():
    baseline = _baseline_default()
    result = evaluate_throughput_gate(
        baseline=baseline,
        current=_make_sample(1000, 5, 20.0, tasks_per_second=80.0),
    )
    assert result.passed is False
    throughput = next(v for v in result.verdicts if v.metric == "throughput")
    assert throughput.passed is False
    assert "drop_ratio" in throughput.detail


def test_p95_latency_inflate_beyond_margin_fails():
    baseline = _baseline_default()
    current = _make_sample(tasks_total=1000, tasks_failed=5, p95_ms=24.0)
    result = evaluate_throughput_gate(
        baseline=baseline,
        current=current,
    )
    assert result.passed is False
    p95 = next(v for v in result.verdicts if v.metric == "p95_latency")
    assert p95.passed is False
    assert "inflate_ratio" in p95.detail


def test_failure_rate_inflate_beyond_margin_fails():
    baseline = _baseline_default()
    current = _make_sample(tasks_total=1000, tasks_failed=20, p95_ms=20.0)
    result = evaluate_throughput_gate(
        baseline=baseline,
        current=current,
    )
    assert result.passed is False
    failure = next(v for v in result.verdicts if v.metric == "failure_rate")
    assert failure.passed is False
    assert "inflate_pp" in failure.detail


def test_thresholds_overrides_change_pass_status():
    baseline = _baseline_default()
    current = _make_sample(tasks_total=1000, tasks_failed=20, p95_ms=20.0)
    strict = GateThresholds(failure_inflate=0.005)
    permissive = GateThresholds(failure_inflate=0.5)

    strict_result = evaluate_throughput_gate(baseline, current, thresholds=strict)
    permissive_result = evaluate_throughput_gate(baseline, current, thresholds=permissive)

    assert strict_result.passed is False
    assert permissive_result.passed is True


def test_throughput_property_returns_measured_value():
    sample = _make_sample(10, 0, 5.0, tasks_per_second=12.5)

    assert sample.throughput == 12.5


def test_empty_result_does_not_fail_open():
    assert ThroughputGateResult().passed is False


def test_benchmark_payload_is_mapped_to_gate_sample():
    sample = sample_from_benchmark_payload(
        {
            "status": "success",
            "summary": {
                "total_enqueued": 600,
                "failed_jobs": 2,
                "error_count": 2,
                "jobs_per_second": 1150.48,
            },
            "latency_ms": {"p95_ms": 499.457},
        }
    )

    assert sample.tasks_total == 600
    assert sample.tasks_failed == 2
    assert sample.error_count == 2
    assert sample.throughput == 1150.48
    assert sample.latency_p95_ms == 499.457
    assert sample.to_failure_rate() == 2 / 600


def test_benchmark_payload_rejects_non_finite_values():
    payload = {
        "status": "success",
        "summary": {
            "total_enqueued": 600,
            "failed_jobs": 0,
            "error_count": 0,
            "jobs_per_second": float("nan"),
        },
        "latency_ms": {"p95_ms": 1.0},
    }

    with pytest.raises(ValueError, match="jobs_per_second"):
        sample_from_benchmark_payload(payload)


def test_evaluate_benchmark_files_uses_strict_json(tmp_path):
    baseline_path = tmp_path / "baseline.json"
    current_path = tmp_path / "current.json"
    baseline = {
        "status": "success",
        "summary": {
            "total_enqueued": 600,
            "failed_jobs": 0,
            "error_count": 0,
            "jobs_per_second": 100.0,
        },
        "latency_ms": {"p95_ms": 100.0},
    }
    current = {
        "status": "success",
        "summary": {
            "total_enqueued": 600,
            "failed_jobs": 0,
            "error_count": 0,
            "jobs_per_second": 95.0,
        },
        "latency_ms": {"p95_ms": 105.0},
    }
    baseline_path.write_text(json.dumps(baseline), encoding="utf-8")
    current_path.write_text(json.dumps(current), encoding="utf-8")

    result = evaluate_benchmark_files(baseline_path, current_path)

    assert result.passed is True


def test_repetition_gate_requires_three_runs_and_checks_all_metrics():
    samples = [
        _make_sample(600, 0, 499.0, tasks_per_second=1150.0),
        _make_sample(600, 0, 505.0, tasks_per_second=1138.0),
        _make_sample(600, 0, 495.0, tasks_per_second=1158.0),
    ]

    result = evaluate_repetition_gate(samples)

    assert result.passed is True
    assert len(result.verdicts) == 3
    assert result.verdicts[1].run_index == 2


def test_repetition_gate_fails_closed_when_runs_are_missing():
    result = evaluate_repetition_gate([_make_sample(600, 0, 499.0, tasks_per_second=1150.0)])

    assert result.passed is False
    assert "반복 회차가 부족합니다" in result.errors[0]


def test_repetition_gate_fails_when_any_run_exceeds_absolute_threshold():
    samples = [
        _make_sample(600, 0, 499.0, tasks_per_second=1150.0),
        _make_sample(600, 0, 601.0, tasks_per_second=1150.0),
        _make_sample(600, 0, 495.0, tasks_per_second=1150.0),
    ]

    result = evaluate_repetition_gate(samples)

    assert result.passed is False
    assert result.verdicts[1].passed is False
    assert "p95=FAIL" in result.verdicts[1].detail


def test_repetition_gate_supports_custom_thresholds():
    samples = [
        _make_sample(600, 0, 499.0, tasks_per_second=950.0),
        _make_sample(600, 0, 499.0, tasks_per_second=950.0),
        _make_sample(600, 0, 499.0, tasks_per_second=950.0),
    ]
    thresholds = RepetitionThresholds(min_throughput_tasks_per_sec=1000.0)

    result = evaluate_repetition_gate(samples, thresholds)

    assert result.passed is False
    assert all(not verdict.passed for verdict in result.verdicts)


def test_load_benchmark_samples_reads_multiple_strict_files(tmp_path):
    paths = []
    for index in range(3):
        path = tmp_path / f"run{index + 1}.json"
        path.write_text(
            json.dumps(
                {
                    "status": "success",
                    "summary": {
                        "total_enqueued": 600,
                        "failed_jobs": 0,
                        "error_count": 0,
                        "jobs_per_second": 1100.0 + index,
                    },
                    "latency_ms": {"p95_ms": 500.0 + index},
                }
            ),
            encoding="utf-8",
        )
        paths.append(path)

    samples = load_benchmark_samples(paths)

    assert [sample.throughput for sample in samples] == [1100.0, 1101.0, 1102.0]


def test_benchmark_payload_rejects_failed_run():
    payload = {
        "status": "failed",
        "summary": {
            "total_enqueued": 10,
            "failed_jobs": 1,
            "error_count": 1,
            "jobs_per_second": 10.0,
        },
        "latency_ms": {"p95_ms": 100.0},
    }

    with pytest.raises(ValueError, match="success"):
        sample_from_benchmark_payload(payload)
