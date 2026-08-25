"""scripts.arq_gate의 일관성 게이트 판정 회귀 테스트."""

from __future__ import annotations

import json

import pytest

from scripts.arq_gate import (
    ALLOW_CALIBRATION_HOST_MISMATCH,
    CALIBRATION_HOST_CPU_COUNT,
    IN_PROCESS_THRESHOLDS,
    GateThresholds,
    RepetitionGateResult,
    RepetitionThresholds,
    ThroughputGateResult,
    ThroughputSample,
    evaluate_benchmark_files,
    evaluate_repetition_gate,
    evaluate_throughput_gate,
    load_benchmark_samples,
    sample_from_benchmark_payload,
    verify_calibration_host,
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

    result = evaluate_repetition_gate(samples, IN_PROCESS_THRESHOLDS)

    assert result.passed is True
    assert len(result.verdicts) == 3
    assert result.verdicts[1].run_index == 2


def test_repetition_gate_fails_closed_when_runs_are_missing():
    result = evaluate_repetition_gate(
        [_make_sample(600, 0, 499.0, tasks_per_second=1150.0)], IN_PROCESS_THRESHOLDS
    )

    assert result.passed is False
    assert "반복 회차가 부족합니다" in result.errors[0]


def test_repetition_gate_fails_when_any_run_exceeds_absolute_threshold():
    samples = [
        _make_sample(600, 0, 499.0, tasks_per_second=1150.0),
        _make_sample(600, 0, 601.0, tasks_per_second=1150.0),
        _make_sample(600, 0, 495.0, tasks_per_second=1150.0),
    ]

    result = evaluate_repetition_gate(samples, IN_PROCESS_THRESHOLDS)

    assert result.passed is False
    assert result.verdicts[1].passed is False
    assert "p95=FAIL" in result.verdicts[1].detail


def test_repetition_gate_supports_custom_thresholds():
    samples = [
        _make_sample(600, 0, 499.0, tasks_per_second=950.0),
        _make_sample(600, 0, 499.0, tasks_per_second=950.0),
        _make_sample(600, 0, 499.0, tasks_per_second=950.0),
    ]
    thresholds = RepetitionThresholds(min_throughput_tasks_per_sec=1000.0, max_p95_latency_ms=550.0)

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


def test_worker_mode_thresholds_match_calibrated_derivation():
    """경로별 기준선이 2026-08-24 캘리브레이션 도출식과 일치하는지 고정합니다.

    median(T) * (1 - 0.06) 과 median(P) * (1 + 0.06) 으로 도출된 값이며,
    이 상수가 근거 없이 바뀌면 이후 모든 회귀 판정이 조용히 틀립니다.
    """
    from scripts.arq_gate import (
        DOCKER_CONTAINER_THRESHOLDS,
        IN_PROCESS_THRESHOLDS,
    )

    assert IN_PROCESS_THRESHOLDS.min_throughput_tasks_per_sec == pytest.approx(
        1195.585 * (1 - 0.06), abs=0.01
    )
    assert IN_PROCESS_THRESHOLDS.max_p95_latency_ms == pytest.approx(480.424 * (1 + 0.06), abs=0.01)
    assert DOCKER_CONTAINER_THRESHOLDS.min_throughput_tasks_per_sec == pytest.approx(
        1756.94 * (1 - 0.06), abs=0.01
    )
    assert DOCKER_CONTAINER_THRESHOLDS.max_p95_latency_ms == pytest.approx(
        327.056 * (1 + 0.06), abs=0.01
    )


def test_thresholds_for_worker_mode_rejects_unknown_mode():
    """기준선이 없는 경로는 기본값으로 넘어가지 않고 거부합니다."""
    from scripts.arq_gate import thresholds_for_worker_mode

    with pytest.raises(ValueError, match="기준선이 없는 워커 경로"):
        thresholds_for_worker_mode("kubernetes_pod")


def test_resolve_repetition_thresholds_rejects_mixed_modes(tmp_path):
    """경로가 섞인 반복 evidence 는 판정하지 않고 거부합니다."""
    import json

    from scripts.arq_gate import resolve_repetition_thresholds

    paths = []
    for idx, mode in enumerate(("in_process", "docker_container")):
        path = tmp_path / f"evidence_{idx}.json"
        path.write_text(json.dumps({"benchmark_worker_mode": mode}), encoding="utf-8")
        paths.append(path)

    with pytest.raises(ValueError, match="워커 경로가 섞여"):
        resolve_repetition_thresholds(paths)


def test_load_worker_mode_rejects_missing_field(tmp_path):
    """benchmark_worker_mode 가 없는 evidence 는 조용히 통과시키지 않습니다."""
    import json

    from scripts.arq_gate import load_worker_mode

    path = tmp_path / "no_mode.json"
    path.write_text(json.dumps({"summary": {}}), encoding="utf-8")

    with pytest.raises(ValueError, match="benchmark_worker_mode"):
        load_worker_mode(path)


def test_repetition_thresholds_require_throughput_and_p95():
    """폐기된 900/600 잠정값을 기본값으로 되살리는 경로가 없어야 합니다."""
    with pytest.raises(TypeError):
        RepetitionThresholds()


def test_repetition_thresholds_defaults_do_not_contain_discarded_values():
    """min_throughput 와 max_p95 는 기본값이 없어 900.0/600.0 이 남을 수 없습니다."""
    thresholds = RepetitionThresholds(
        min_throughput_tasks_per_sec=1123.85, max_p95_latency_ms=509.25
    )
    assert thresholds.min_runs == 3
    assert thresholds.max_failure_rate == 0.0
    assert thresholds.min_throughput_tasks_per_sec == 1123.85
    assert thresholds.max_p95_latency_ms == 509.25


def test_repetition_gate_requires_thresholds():
    """evaluate_repetition_gate 는 thresholds 없이 호출할 수 없습니다."""
    from scripts.arq_gate import evaluate_repetition_gate

    with pytest.raises(TypeError):
        evaluate_repetition_gate([_make_sample(600, 0, 499.0, tasks_per_second=1150.0)])


def test_repetition_gate_result_requires_thresholds():
    """RepetitionGateResult 는 thresholds 없이 생성할 수 없습니다.

    thresholds 는 필수 생성자 인자여야 하며, default_factory 로 RepetitionThresholds 를
    다시 만들 수 없습니다. 무인자 생성은 TypeError 여야 합니다.
    """
    with pytest.raises(TypeError):
        RepetitionGateResult()


def test_repetition_gate_result_missing_thresholds_raises_type_error():
    """verdicts 만 넘기고 thresholds 를 누락한 생성도 TypeError 여야 합니다."""
    samples = [
        _make_sample(600, 0, 499.0, tasks_per_second=1150.0),
    ]

    with pytest.raises(TypeError):
        RepetitionGateResult(verdicts=samples)


def _calibration_environment() -> dict:
    return {
        "platform": "macOS-26.6.2-arm64-arm-64bit",
        "host_cpu_count": 14,
        "python": "3.12.14",
    }


def test_host_binding_passes_for_calibration_fingerprint():
    """캘리브레이션 호스트와 같은 지문은 결박을 통과합니다."""
    verify_calibration_host(_calibration_environment())


def test_host_binding_fails_for_different_platform():
    """다른 platform 의 증거는 기본 설정에서 통과하지 않습니다."""
    environment = _calibration_environment()
    environment["platform"] = "Linux-6.8.0-x86_64-with-glibc2.39"
    with pytest.raises(ValueError, match="재캘리브레이션"):
        verify_calibration_host(environment)


def test_host_binding_fails_for_different_cpu_count():
    """다른 host_cpu_count 의 증거는 기본 설정에서 통과하지 않습니다."""
    environment = _calibration_environment()
    environment["host_cpu_count"] = 8
    with pytest.raises(ValueError, match="재캘리브레이션"):
        verify_calibration_host(environment)


def test_host_binding_fails_when_environment_missing():
    """environment 블록이 없으면 fail-closed 로 중단합니다."""
    with pytest.raises(ValueError, match="환경 지문"):
        verify_calibration_host(None)


def test_host_binding_allow_mismatch_opt_in_passes():
    """옵트인 플래그를 주면 다른 호스트 지문도 통과합니다."""
    environment = _calibration_environment()
    environment["platform"] = "Linux-6.8.0-x86_64-with-glibc2.39"
    verify_calibration_host(environment, allow_mismatch=True)


def test_host_binding_platform_ignores_minor_version_difference():
    """같은 Mac OS 계열/arm64 의 마이너 버전 차이는 오탐으로 보지 않습니다."""
    environment = _calibration_environment()
    environment["platform"] = "macOS-26.7.1-arm64-arm-64bit"
    verify_calibration_host(environment)


def test_host_binding_default_is_fail_closed():
    """옵트인 플래그의 기본값은 결박이 켜진 상태여야 합니다."""
    assert ALLOW_CALIBRATION_HOST_MISMATCH is False
    assert CALIBRATION_HOST_CPU_COUNT == 14
