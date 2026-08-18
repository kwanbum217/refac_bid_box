"""
src/ml/monitoring.py

PSI(Population Stability Index) 기반 데이터 & 예측 드리프트 감지 모니터링 모듈.
입력 특징 분포 변화(PSI > 0.2) 탐지 시 재학습 비동기 태스크를 발화합니다.
"""

from typing import Any

import numpy as np


class InsufficientSampleError(ValueError):
    """PSI 를 계산할 표본이 없음을 알립니다."""

    def __init__(self, expected_size: int, actual_size: int) -> None:
        self.expected_size = expected_size
        self.actual_size = actual_size
        super().__init__(f"PSI 계산 표본 부족: baseline {expected_size}건, recent {actual_size}건")


def calculate_psi(
    expected: np.ndarray,
    actual: np.ndarray,
    num_buckets: int = 10,
) -> float:
    """
    Population Stability Index (PSI) 계산.
    PSI < 0.1: 변화 없음 (안정)
    0.1 <= PSI < 0.2: 경미한 변화 (주의)
    PSI >= 0.2: 유의미한 분포 변화 (재학습 트리거 필요)
    """

    def scale_range(arr, min_val, max_val):
        return (arr - min_val) / (max_val - min_val + 1e-5)

    if len(expected) == 0 or len(actual) == 0:
        # 표본이 없으면 "변화 없음" 이 아니라 판정 불가입니다. 0.0 을 돌려주면
        # 호출부가 STABLE 로 읽어 드리프트 감시가 조용히 꺼집니다.
        raise InsufficientSampleError(len(expected), len(actual))

    min_v = min(np.min(expected), np.min(actual))
    max_v = max(np.max(expected), np.max(actual))

    exp_scaled = scale_range(expected, min_v, max_v)
    act_scaled = scale_range(actual, min_v, max_v)

    buckets = np.linspace(0, 1, num_buckets + 1)
    exp_counts, _ = np.histogram(exp_scaled, bins=buckets)
    act_counts, _ = np.histogram(act_scaled, bins=buckets)

    exp_pct = exp_counts / (len(expected) + 1e-5)
    act_pct = act_counts / (len(actual) + 1e-5)

    # 0 분모 방지 (1e-4 이중 보정)
    exp_pct = np.where(exp_pct == 0, 1e-4, exp_pct)
    act_pct = np.where(act_pct == 0, 1e-4, act_pct)

    psi_val = np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct))
    return float(round(psi_val, 4))


def check_feature_drift(
    baseline_features: np.ndarray,
    recent_features: np.ndarray,
    threshold: float = 0.2,
) -> dict[str, Any]:
    """특징 드리프트 검사 및 재학습 트리거 판단.

    표본이 없으면 STABLE 로 승격하지 않고 INSUFFICIENT_DATA 를 돌려줍니다.
    감시할 근거가 없는 상태와 안정된 상태는 다릅니다.
    """
    try:
        psi = calculate_psi(baseline_features, recent_features)
    except InsufficientSampleError as exc:
        return {
            "psi_value": None,
            "threshold": threshold,
            "drift_detected": None,
            "action": "INSUFFICIENT_DATA",
            "reason": str(exc),
        }

    is_drift_detected = psi >= threshold

    return {
        "psi_value": psi,
        "threshold": threshold,
        "drift_detected": is_drift_detected,
        "action": "TRIGGER_RETRAIN" if is_drift_detected else "STABLE",
    }
