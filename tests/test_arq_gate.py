"""scripts.arq_gate의 일관성 게이트 판정 회귀 테스트."""

from __future__ import annotations

import pytest

from scripts.arq_gate import (
    GateThresholds,
    GateVerdict,
    ThroughputSample,
    evaluate_throughput_gate,
)


def _make_sample(tasks_total: int, tasks_failed: int, p95_ms: float) -> ThroughputSample:
    return ThroughputSample(tasks_total=tasks_total, tasks_failed=tasks_failed, latency_p95_ms=p95_ms)


def _baseline_default() -> ThroughputSample:
    return _make_sample(tasks_total=1000, tasks_failed=5, p95_ms=20.0)


def _current_default() -> ThroughputSample:
    return _make_sample(tasks_total=1000, tasks_failed=5, p95_ms=20.0)


def test_all_metrics_pass_when_within_margins():
    baseline = _baseline_default()
    current = _current_default()
    result = evaluate_throughput_gate(
        baseline=baseline,
        current=current,
        baseline_throughput=100.0,
        current_throughput=98.0,
    )
    assert result.passed is True
    assert {v.metric for v in result.verdicts} == {"throughput", "p95_latency", "failure_rate"}


def test_throughput_drop_beyond_margin_fails():
    baseline = _baseline_default()
    current = _current_default()
    result = evaluate_throughput_gate(
        baseline=baseline,
        current=current,
        baseline_throughput=100.0,
        current_throughput=80.0,
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
        baseline_throughput=100.0,
        current_throughput=100.0,
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
        baseline_throughput=100.0,
        current_throughput=100.0,
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

    strict_result = evaluate_throughput_gate(
        baseline, current, 100.0, 100.0, thresholds=strict
    )
    permissive_result = evaluate_throughput_gate(
        baseline, current, 100.0, 100.0, thresholds=permissive
    )

    assert strict_result.passed is False
    assert permissive_result.passed is True
