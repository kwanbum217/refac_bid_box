"""Arq 큐 처리량 일관성 게이트 판정 모듈.

처리량, P95 latency, 실패율 3개 지표에 대해 baseline과 current 표본을 비교해
PASS/FAIL 을 결정합니다. 임계치는 호출 측에서 우선 주입되며, 미주입 시 기본
보수값을 사용합니다. 본 모듈은 P2-3R을 거쳐 dump_strict_json 헬퍼를 import
하지 않고 표준 library 만으로 동작합니다 (P1-2의 일관성 유지).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable


DEFAULT_TP_TOLERANCE = 0.10  # 처리량 -10% 이내 (current >= baseline * 0.9)
DEFAULT_P95_TOLERANCE = 0.10  # P95 latency +10% 이내 (current <= baseline * 1.1)
DEFAULT_FAILURE_TOLERANCE = 0.01  # 실패율 +1pp 이내 (current - baseline <= 0.01)


@dataclass
class ThroughputSample:
    """단일 회차의 처리량 표본."""

    tasks_total: int
    tasks_failed: int
    latency_p95_ms: float

    @property
    def throughput(self) -> float:
        """초당 처리량. 측정자가 표본 외 시간 정보로 환산한 tasks/sec을 사용.

        본 골격에서는 작업을 받지 않고 합리적 기본값 0을 반환한다. 측정은
        scripts/benchmark_arq_throughput.py 결과를 그대로 사용하되, 본 모듈은
        단순 환산을 적용해 골격을 검증 가능 상태로 둔다.
        """

    def to_failure_rate(self) -> float:
        if self.tasks_total <= 0:
            return 0.0
        return max(0.0, min(1.0, self.tasks_failed / self.tasks_total))


@dataclass
class GateThresholds:
    """3개 지표의 임계치 마진."""

    throughput_drop: float = DEFAULT_TP_TOLERANCE
    p95_inflate: float = DEFAULT_P95_TOLERANCE
    failure_inflate: float = DEFAULT_FAILURE_TOLERANCE


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
        return all(v.passed for v in self.verdicts)

    def summary(self) -> str:
        rows = [
            f"{v.metric}: baseline={v.baseline:.6f} current={v.current:.6f} "
            f"threshold={v.threshold:.6f} {'PASS' if v.passed else 'FAIL'} {v.detail}".strip()
            for v in self.verdicts
        ]
        head = "PASS" if self.passed else "FAIL"
        return f"{head}\n" + "\n".join(rows)


def _check_throughput(baseline_tasks_per_sec: float, current_tasks_per_sec: float, threshold: float) -> GateVerdict:
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


def _check_failure(baseline_failure_rate: float, current_failure_rate: float, threshold: float) -> GateVerdict:
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
    baseline_throughput: float,
    current_throughput: float,
    thresholds: GateThresholds | None = None,
) -> ThroughputGateResult:
    """baseline/current 표본 + 처리량을 받아 게이트 PASS/FAIL 결정.

    Args:
      baseline: baseline 회차 표본.
      current: current 회차 표본.
      baseline_throughput: baseline 회차의 측정된 tasks/sec.
      current_throughput: current 회차의 측정된 tasks/sec.
      thresholds: 마진 임계치. None 이면 보수 기본값.
    """

    if thresholds is None:
        thresholds = GateThresholds()

    verdicts = [
        _check_throughput(baseline_throughput, current_throughput, thresholds.throughput_drop),
        _check_p95(baseline.latency_p95_ms, current.latency_p95_ms, thresholds.p95_inflate),
        _check_failure(baseline.to_failure_rate(), current.to_failure_rate(), thresholds.failure_inflate),
    ]
    return ThroughputGateResult(verdicts=verdicts)


def summarize_verdicts(verdicts: Iterable[GateVerdict]) -> str:
    return "\n".join(
        f"{v.metric}: {'PASS' if v.passed else 'FAIL'} {v.detail}" for v in verdicts
    )
