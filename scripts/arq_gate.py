"""Arq 큐 처리량 일관성 게이트 판정 모듈.

처리량, P95 latency, 실패율 3개 지표에 대해 baseline과 current 표본을 비교해
PASS/FAIL 을 결정합니다. 임계치는 호출 측에서 우선 주입되며, 미주입 시 기본
보수값을 사용합니다. benchmark evidence 입력은 P2-3R의 strict JSON 파서를
통해 읽습니다.
"""

from __future__ import annotations

import argparse
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts._strict_json import load_strict_json
except ModuleNotFoundError:
    from _strict_json import load_strict_json  # type: ignore[no-redef]

DEFAULT_TP_TOLERANCE = 0.10  # 처리량 -10% 이내 (current >= baseline * 0.9)
DEFAULT_P95_TOLERANCE = 0.10  # P95 latency +10% 이내 (current <= baseline * 1.1)
DEFAULT_FAILURE_TOLERANCE = 0.01  # 실패율 +1pp 이내 (current - baseline <= 0.01)


@dataclass
class ThroughputSample:
    """단일 회차의 처리량 표본."""

    tasks_total: int
    tasks_failed: int
    latency_p95_ms: float
    tasks_per_second: float
    error_count: int = 0

    def __post_init__(self) -> None:
        if self.tasks_total <= 0:
            raise ValueError("tasks_total은 양수여야 합니다.")
        if self.tasks_failed < 0 or self.tasks_failed > self.tasks_total:
            raise ValueError("tasks_failed 범위가 올바르지 않습니다.")
        if self.error_count < 0:
            raise ValueError("error_count는 음수가 될 수 없습니다.")
        if self.tasks_per_second <= 0 or not math.isfinite(self.tasks_per_second):
            raise ValueError("tasks_per_second는 유한한 양수여야 합니다.")
        if self.latency_p95_ms <= 0 or not math.isfinite(self.latency_p95_ms):
            raise ValueError("latency_p95_ms는 유한한 양수여야 합니다.")

    @property
    def throughput(self) -> float:
        """측정된 초당 처리량을 반환합니다."""
        return self.tasks_per_second

    def to_failure_rate(self) -> float:
        if self.tasks_total <= 0:
            return 1.0
        failed = max(self.tasks_failed, self.error_count)
        return max(0.0, min(1.0, failed / self.tasks_total))


@dataclass
class GateThresholds:
    """3개 지표의 임계치 마진."""

    throughput_drop: float = DEFAULT_TP_TOLERANCE
    p95_inflate: float = DEFAULT_P95_TOLERANCE
    failure_inflate: float = DEFAULT_FAILURE_TOLERANCE

    def __post_init__(self) -> None:
        for name, value in (
            ("throughput_drop", self.throughput_drop),
            ("p95_inflate", self.p95_inflate),
            ("failure_inflate", self.failure_inflate),
        ):
            if value < 0 or not math.isfinite(value):
                raise ValueError(f"{name}은 유한한 음이 아닌 값이어야 합니다.")


@dataclass
class RepetitionThresholds:
    """반복 측정의 절대 기준선.

    min_throughput_tasks_per_sec 와 max_p95_latency_ms 는 반드시 명시해야 한다.
    이 두 값은 2026-08-24 캘리브레이션으로 폐기된 잠정 900.0/600.0 을
    기본값으로 되살리는 경로를 막기 위해 기본값을 두지 않는다. 실제 판정에는
    WORKER_MODE_THRESHOLDS 의 경로별 프리셋을 쓴다.
    """

    min_throughput_tasks_per_sec: float
    max_p95_latency_ms: float
    min_runs: int = 3
    max_failure_rate: float = 0.0

    def __post_init__(self) -> None:
        if self.min_runs < 1:
            raise ValueError("min_runs는 양의 정수여야 합니다.")
        for name, value in (
            ("min_throughput_tasks_per_sec", self.min_throughput_tasks_per_sec),
            ("max_p95_latency_ms", self.max_p95_latency_ms),
            ("max_failure_rate", self.max_failure_rate),
        ):
            if value < 0 or not math.isfinite(value):
                raise ValueError(f"{name}은 유한한 음이 아닌 값이어야 합니다.")
        if self.max_failure_rate > 1:
            raise ValueError("max_failure_rate는 1 이하이어야 합니다.")


# 2026-08-24 정식 캘리브레이션(경로별 10회, git sha 0ab8c3e)에서 도출한 기준선이다.
# 도출식은 arq_calibration_design_20260824.md 6장을 그대로 따른다.
#
#   min_throughput = median(T) * (1 - rt),  rt = max(3 * CV(T), 0.06)
#   max_p95        = median(P) * (1 + rp),  rp = max(3 * CV(P), 0.06)
#
# 두 경로 모두 3 * CV 가 하한 0.06 보다 작아 rt = rp = 0.06 이 적용됐다.
# 회차별 raw 와 기준선 요약은 data/benchmarks/frozen/arq/<mode>/0ab8c3e/ 에 있다.
#
#   in_process      median 1195.59 jps / 480.42ms  (CV 0.0172 / 0.0162)
#   docker_container median 1756.94 jps / 327.06ms (CV 0.0145 / 0.0154)
#
# 두 경로는 처리량이 1.47배 차이나므로 단일 임계값으로는 어느 쪽도 판정할 수 없다.
IN_PROCESS_THRESHOLDS = RepetitionThresholds(
    min_runs=3,
    min_throughput_tasks_per_sec=1123.85,
    max_p95_latency_ms=509.25,
    max_failure_rate=0.0,
)

DOCKER_CONTAINER_THRESHOLDS = RepetitionThresholds(
    min_runs=3,
    min_throughput_tasks_per_sec=1651.52,
    max_p95_latency_ms=346.68,
    max_failure_rate=0.0,
)

WORKER_MODE_THRESHOLDS: dict[str, RepetitionThresholds] = {
    "in_process": IN_PROCESS_THRESHOLDS,
    "docker_container": DOCKER_CONTAINER_THRESHOLDS,
}

# 2026-08-24 정식 캘리브레이션을 수행한 호스트 지문이다.
# 출처: data/benchmarks/frozen/arq/<mode>/0ab8c3e/ 의 각 JSON environment 블록
#   (environment.platform, environment.host_cpu_count, environment.python).
# 기준선은 이 특정 Mac 호스트의 실측이므로, 다른 호스트의 측정에 그대로
# 적용되어서는 안 된다. 게이트 평가는 이 지문과 대조해 일치할 때만 통과로
# 인정한다 (fail-closed).
CALIBRATION_HOST_PLATFORM_OS = "macos"
CALIBRATION_HOST_PLATFORM_ARCH = "arm64"
CALIBRATION_HOST_CPU_COUNT = 14
CALIBRATION_HOST_PYTHON = "3.12.14"

# 호스트 결박을 의도적으로 끄는 옵트인 플래그. 기본값은 결박이 켜진 상태
# (fail-closed)다. 재캘리브레이션 검증이나 다른 호스트에서 기준선을 새로
# 만들 때만 명시적으로 True 를 넘긴다.
ALLOW_CALIBRATION_HOST_MISMATCH = False


def _platform_os(platform: str) -> str:
    """platform 문자열에서 OS 계열 소문자를 추출한다.

    예: 'macOS-26.6.2-arm64-arm-64bit' -> 'macos'
    """
    return platform.split("-", 1)[0].lower()


def _platform_arch(platform: str) -> str:
    """platform 문자열에서 아키텍처 소문자를 추출한다.

    예: 'macOS-26.6.2-arm64-arm-64bit' -> 'arm64'
    """
    parts = platform.split("-")
    for part in parts:
        low = part.lower()
        if low in ("arm64", "x86_64", "amd64", "aarch64"):
            return low
    return ""


def verify_calibration_host(
    environment: Mapping[str, Any] | None,
    *,
    allow_mismatch: bool = ALLOW_CALIBRATION_HOST_MISMATCH,
) -> None:
    """evidence 의 environment 지문이 캘리브레이션 호스트와 일치하는지 확인한다.

    불일치하면 재캘리브레이션이 필요하다는 사유와 함께 ValueError 를 일으켜
    통과로 판정하지 못하게 막는다. platform 은 OS 계열과 아키텍처 수준에서만
    비교해 마이너 버전 차이로 오탐이 나지 않게 한다. host_cpu_count 는 완전
    일치를 요구한다. allow_mismatch=True 면 결박을 해제한다(명시적 옵트인).
    """
    if allow_mismatch:
        return
    if environment is None or not isinstance(environment, Mapping):
        raise ValueError(
            "환경 지문(environment)이 없어 캘리브레이션 호스트 결박을 확인할 수 없습니다."
        )
    platform = environment.get("platform")
    host_cpu_count = environment.get("host_cpu_count")
    if not isinstance(platform, str) or not platform:
        raise ValueError(
            "환경 지문에 platform 이 없어 캘리브레이션 호스트 결박을 확인할 수 없습니다."
        )
    if not isinstance(host_cpu_count, int):
        raise ValueError(
            "환경 지문에 host_cpu_count 가 없어 캘리브레이션 호스트 결박을 확인할 수 없습니다."
        )
    os_ok = _platform_os(platform) == CALIBRATION_HOST_PLATFORM_OS
    arch_ok = _platform_arch(platform) == CALIBRATION_HOST_PLATFORM_ARCH
    cpu_ok = host_cpu_count == CALIBRATION_HOST_CPU_COUNT
    if not (os_ok and arch_ok and cpu_ok):
        raise ValueError(
            "측정 호스트가 캘리브레이션 기준선 호스트와 다릅니다. "
            "이 기준선은 특정 호스트의 실측이므로 다른 호스트에 적용할 수 없습니다. "
            "재캘리브레이션이 필요합니다. "
            f"(evidence platform={platform!r}, host_cpu_count={host_cpu_count}; "
            f"기준 platform=macOS/{CALIBRATION_HOST_PLATFORM_ARCH}, "
            f"host_cpu_count={CALIBRATION_HOST_CPU_COUNT})"
        )


def thresholds_for_worker_mode(worker_mode: str) -> RepetitionThresholds:
    """워커 경로에 해당하는 실측 기준선을 반환한다.

    알 수 없는 경로는 임의 기본값으로 조용히 넘어가지 않고 거부한다.
    """
    try:
        return WORKER_MODE_THRESHOLDS[worker_mode]
    except KeyError:
        known = ", ".join(sorted(WORKER_MODE_THRESHOLDS))
        raise ValueError(
            f"기준선이 없는 워커 경로입니다: {worker_mode!r} (알려진 경로: {known})"
        ) from None


@dataclass
class GateVerdict:
    """단일 지표의 PASS/FAIL 판정."""

    metric: str
    baseline: float
    current: float
    threshold: float
    passed: bool
    detail: str = ""


@dataclass
class ThroughputGateResult:
    """통합 게이트 판정 결과."""

    verdicts: list[GateVerdict] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.verdicts) and all(v.passed for v in self.verdicts)

    def summary(self) -> str:
        rows = [
            f"{v.metric}: baseline={v.baseline:.6f} current={v.current:.6f} "
            f"threshold={v.threshold:.6f} {'PASS' if v.passed else 'FAIL'} {v.detail}".strip()
            for v in self.verdicts
        ]
        head = "PASS" if self.passed else "FAIL"
        return f"{head}\n" + "\n".join(rows)


@dataclass
class RepetitionVerdict:
    """반복 측정 한 회차의 절대 기준 판정."""

    run_index: int
    throughput_tasks_per_sec: float
    p95_latency_ms: float
    failure_rate: float
    passed: bool
    detail: str = ""


@dataclass
class RepetitionGateResult:
    """최소 반복 회차와 회차별 절대 기준을 함께 판정한 결과."""

    verdicts: list[RepetitionVerdict] = field(default_factory=list)
    thresholds: RepetitionThresholds = field(default_factory=RepetitionThresholds)
    errors: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return (
            not self.errors
            and len(self.verdicts) >= self.thresholds.min_runs
            and bool(self.verdicts)
            and all(verdict.passed for verdict in self.verdicts)
        )

    def summary(self) -> str:
        head = "PASS" if self.passed else "FAIL"
        rows = [
            f"run={verdict.run_index}: throughput={verdict.throughput_tasks_per_sec:.2f} "
            f"p95={verdict.p95_latency_ms:.3f} failure_rate={verdict.failure_rate:.4f} "
            f"{'PASS' if verdict.passed else 'FAIL'} {verdict.detail}".strip()
            for verdict in self.verdicts
        ]
        if self.errors:
            rows.extend(f"error: {error}" for error in self.errors)
        return f"{head}\n" + "\n".join(rows)


def _check_throughput(
    baseline_tasks_per_sec: float,
    current_tasks_per_sec: float,
    threshold: float,
) -> GateVerdict:
    if baseline_tasks_per_sec <= 0:
        return GateVerdict(
            metric="throughput",
            baseline=baseline_tasks_per_sec,
            current=current_tasks_per_sec,
            threshold=threshold,
            passed=False,
            detail="baseline_throughput_must_be_positive",
        )
    drop_ratio = (baseline_tasks_per_sec - current_tasks_per_sec) / baseline_tasks_per_sec
    passed = drop_ratio <= threshold
    detail = f"drop_ratio={drop_ratio:.4f}"
    return GateVerdict(
        metric="throughput",
        baseline=baseline_tasks_per_sec,
        current=current_tasks_per_sec,
        threshold=threshold,
        passed=passed,
        detail=detail,
    )


def _check_p95(baseline_p95_ms: float, current_p95_ms: float, threshold: float) -> GateVerdict:
    if baseline_p95_ms <= 0:
        return GateVerdict(
            metric="p95_latency",
            baseline=baseline_p95_ms,
            current=current_p95_ms,
            threshold=threshold,
            passed=False,
            detail="baseline_p95_must_be_positive",
        )
    inflate_ratio = (current_p95_ms - baseline_p95_ms) / baseline_p95_ms
    passed = inflate_ratio <= threshold
    detail = f"inflate_ratio={inflate_ratio:.4f}"
    return GateVerdict(
        metric="p95_latency",
        baseline=baseline_p95_ms,
        current=current_p95_ms,
        threshold=threshold,
        passed=passed,
        detail=detail,
    )


def _check_failure(
    baseline_failure_rate: float,
    current_failure_rate: float,
    threshold: float,
) -> GateVerdict:
    inflate_pp = current_failure_rate - baseline_failure_rate
    passed = inflate_pp <= threshold
    detail = f"inflate_pp={inflate_pp:.4f}"
    return GateVerdict(
        metric="failure_rate",
        baseline=baseline_failure_rate,
        current=current_failure_rate,
        threshold=threshold,
        passed=passed,
        detail=detail,
    )


def evaluate_throughput_gate(
    baseline: ThroughputSample,
    current: ThroughputSample,
    thresholds: GateThresholds | None = None,
) -> ThroughputGateResult:
    """baseline/current 표본을 받아 게이트 PASS/FAIL을 결정합니다.

    Args:
      baseline: baseline 회차 표본.
      current: current 회차 표본.
      thresholds: 마진 임계치. None 이면 보수 기본값.
    """

    if thresholds is None:
        thresholds = GateThresholds()

    verdicts = [
        _check_throughput(baseline.throughput, current.throughput, thresholds.throughput_drop),
        _check_p95(baseline.latency_p95_ms, current.latency_p95_ms, thresholds.p95_inflate),
        _check_failure(
            baseline.to_failure_rate(), current.to_failure_rate(), thresholds.failure_inflate
        ),
    ]
    return ThroughputGateResult(verdicts=verdicts)


def evaluate_repetition_gate(
    samples: Sequence[ThroughputSample],
    thresholds: RepetitionThresholds,
) -> RepetitionGateResult:
    """반복 표본을 최악 회차 기준의 절대 기준선으로 판정합니다.

    thresholds 는 필수다. 기본 임계값이 없으므로 폐기된 잠정 900/600 이
    조용히 재적용되는 경로가 존재하지 않는다.
    """
    errors: list[str] = []
    if len(samples) < thresholds.min_runs:
        errors.append(f"반복 회차가 부족합니다: {len(samples)}회/{thresholds.min_runs}회")

    verdicts = []
    for index, sample in enumerate(samples, start=1):
        throughput_passed = sample.throughput >= thresholds.min_throughput_tasks_per_sec
        p95_passed = sample.latency_p95_ms <= thresholds.max_p95_latency_ms
        failure_passed = sample.to_failure_rate() <= thresholds.max_failure_rate
        passed = throughput_passed and p95_passed and failure_passed
        detail = (
            f"throughput={'PASS' if throughput_passed else 'FAIL'} "
            f"p95={'PASS' if p95_passed else 'FAIL'} "
            f"failure={'PASS' if failure_passed else 'FAIL'}"
        )
        verdicts.append(
            RepetitionVerdict(
                run_index=index,
                throughput_tasks_per_sec=sample.throughput,
                p95_latency_ms=sample.latency_p95_ms,
                failure_rate=sample.to_failure_rate(),
                passed=passed,
                detail=detail,
            )
        )
    return RepetitionGateResult(verdicts=verdicts, thresholds=thresholds, errors=errors)


def _required_number(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name}은 유한한 숫자여야 합니다.")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name}은 유한한 숫자여야 합니다.")
    return number


def sample_from_benchmark_payload(payload: Mapping[str, Any]) -> ThroughputSample:
    """benchmark_arq_throughput.py 출력 JSON에서 게이트 표본을 만듭니다."""
    if payload.get("status") != "success":
        raise ValueError("benchmark evidence 상태가 success가 아닙니다.")
    summary = payload.get("summary")
    latency = payload.get("latency_ms")
    if not isinstance(summary, Mapping) or not isinstance(latency, Mapping):
        raise ValueError("benchmark evidence에 summary 또는 latency_ms가 없습니다.")

    total = _required_number(summary.get("total_enqueued"), "summary.total_enqueued")
    failed = _required_number(summary.get("failed_jobs"), "summary.failed_jobs")
    errors = _required_number(summary.get("error_count"), "summary.error_count")
    throughput = _required_number(summary.get("jobs_per_second"), "summary.jobs_per_second")
    p95 = _required_number(latency.get("p95_ms"), "latency_ms.p95_ms")
    if not total.is_integer() or total <= 0:
        raise ValueError("summary.total_enqueued는 양의 정수여야 합니다.")
    if not failed.is_integer() or failed < 0 or failed > total:
        raise ValueError("summary.failed_jobs 범위가 올바르지 않습니다.")
    if not errors.is_integer() or errors < 0:
        raise ValueError("summary.error_count는 음수가 될 수 없습니다.")
    if throughput <= 0 or p95 <= 0:
        raise ValueError("처리량과 P95 latency는 양수여야 합니다.")
    return ThroughputSample(
        tasks_total=int(total),
        tasks_failed=int(failed),
        latency_p95_ms=p95,
        tasks_per_second=throughput,
        error_count=int(errors),
    )


def load_benchmark_sample(path: str | Path) -> ThroughputSample:
    """strict JSON benchmark evidence 파일을 게이트 표본으로 읽습니다."""
    payload = load_strict_json(Path(path))
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark evidence는 JSON 객체여야 합니다.")
    return sample_from_benchmark_payload(payload)


def load_benchmark_samples(paths: Iterable[str | Path]) -> list[ThroughputSample]:
    """여러 strict JSON benchmark evidence 파일을 순서대로 읽습니다."""
    return [load_benchmark_sample(path) for path in paths]


def load_worker_mode(path: str | Path) -> str:
    """evidence JSON 의 benchmark_worker_mode 를 읽습니다."""
    payload = load_strict_json(Path(path))
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark evidence는 JSON 객체여야 합니다.")
    mode = payload.get("benchmark_worker_mode")
    if not isinstance(mode, str) or not mode:
        raise ValueError(f"benchmark_worker_mode 가 없습니다: {path}")
    return mode


def load_environment(path: str | Path) -> Mapping[str, Any]:
    """evidence JSON 의 environment 블록을 읽습니다."""
    payload = load_strict_json(Path(path))
    if not isinstance(payload, Mapping):
        raise ValueError("benchmark evidence는 JSON 객체여야 합니다.")
    environment = payload.get("environment")
    if not isinstance(environment, Mapping):
        raise ValueError(f"environment 블록이 없습니다: {path}")
    return environment


def resolve_repetition_thresholds(paths: Sequence[str | Path]) -> RepetitionThresholds:
    """반복 evidence 들이 같은 경로인지 확인하고 그 경로의 실측 기준선을 고릅니다.

    경로가 섞이면 어느 기준선도 맞지 않으므로 판정하지 않고 거부합니다.
    또한 기준선을 도출한 호스트가 아닌 다른 호스트의 측정이면 재캘리브레이션이
    필요하다고 판단해 거부합니다 (호스트 결박, fail-closed).
    """
    modes = {load_worker_mode(path) for path in paths}
    if len(modes) != 1:
        raise ValueError(f"반복 evidence 의 워커 경로가 섞여 있습니다: {sorted(modes)}")
    for path in paths:
        verify_calibration_host(load_environment(path))
    return thresholds_for_worker_mode(modes.pop())


def evaluate_benchmark_files(
    baseline_path: str | Path,
    current_path: str | Path,
    thresholds: GateThresholds | None = None,
) -> ThroughputGateResult:
    """두 strict JSON benchmark evidence 파일을 비교합니다."""
    return evaluate_throughput_gate(
        load_benchmark_sample(baseline_path),
        load_benchmark_sample(current_path),
        thresholds=thresholds,
    )


def summarize_verdicts(verdicts: Iterable[GateVerdict]) -> str:
    return "\n".join(f"{v.metric}: {'PASS' if v.passed else 'FAIL'} {v.detail}" for v in verdicts)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arq 처리량 일관성 게이트")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--baseline", type=Path, help="baseline evidence JSON")
    group.add_argument(
        "--repetition",
        action="append",
        dest="repetitions",
        type=Path,
        help="반복 측정 evidence JSON (최소 3회, 여러 번 지정)",
    )
    parser.add_argument("--current", type=Path, help="current evidence JSON")
    parser.add_argument(
        "--mode",
        choices=sorted(WORKER_MODE_THRESHOLDS),
        help="반복 판정에 쓸 워커 경로 기준선. 생략하면 evidence 의 benchmark_worker_mode 로 판별합니다",
    )
    args = parser.parse_args(argv)

    try:
        if args.repetitions:
            if args.mode:
                thresholds = thresholds_for_worker_mode(args.mode)
                for path in args.repetitions:
                    verify_calibration_host(load_environment(path))
            else:
                thresholds = resolve_repetition_thresholds(args.repetitions)
            result = evaluate_repetition_gate(
                load_benchmark_samples(args.repetitions), thresholds=thresholds
            )
        else:
            if args.current is None:
                parser.error("--baseline 사용 시 --current가 필요합니다.")
            result = evaluate_benchmark_files(args.baseline, args.current)
    except (OSError, TypeError, ValueError) as exc:
        print(f"게이트 판정 불가: {exc}")
        return 2

    print(result.summary())
    return 0 if result.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
