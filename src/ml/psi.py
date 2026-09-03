"""
src/ml/psi.py

Population Stability Index (PSI) 계산 및 단일 특징 드리프트 판정.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

DEFAULT_MIN_SAMPLES = 100
DEFAULT_PSI_THRESHOLD = 0.2
DEFAULT_NUM_BUCKETS = 10


class InsufficientSampleError(ValueError):
    """PSI 를 계산할 표본이 없거나 부족함을 알립니다."""

    def __init__(
        self, expected_size: int, actual_size: int, min_samples: int = DEFAULT_MIN_SAMPLES
    ) -> None:
        self.expected_size = expected_size
        self.actual_size = actual_size
        self.min_samples = min_samples
        super().__init__(
            f"PSI 계산 표본 부족: baseline {expected_size}건, recent {actual_size}건 (최소 필요: {min_samples}건)"
        )


def calculate_psi(
    expected: np.ndarray | pd.Series | list[float],
    actual: np.ndarray | pd.Series | list[float],
    num_buckets: int = DEFAULT_NUM_BUCKETS,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> float:
    """
    Population Stability Index (PSI) 계산.
    PSI < 0.1: 변화 없음 (안정)
    0.1 <= PSI < 0.2: 경미한 변화 (주의)
    PSI >= 0.2: 유의미한 분포 변화 (재학습 검토 필요)
    """
    exp_arr = np.asarray(expected, dtype=float)
    act_arr = np.asarray(actual, dtype=float)

    if len(exp_arr) < min_samples or len(act_arr) < min_samples:
        # 표본이 최소 기준(기본 100건)에 미달하면 판정 불가로 거부합니다.
        # 0.0 을 돌려주면 호출부가 STABLE 로 오인해 감시가 조용히 꺼집니다.
        raise InsufficientSampleError(len(exp_arr), len(act_arr), min_samples)

    def scale_range(arr: np.ndarray, min_val: float, max_val: float) -> np.ndarray:
        return (arr - min_val) / (max_val - min_val + 1e-5)

    min_v = float(min(np.min(exp_arr), np.min(act_arr)))
    max_v = float(max(np.max(exp_arr), np.max(act_arr)))

    exp_scaled = scale_range(exp_arr, min_v, max_v)
    act_scaled = scale_range(act_arr, min_v, max_v)

    buckets = np.linspace(0, 1, num_buckets + 1)
    exp_counts, _ = np.histogram(exp_scaled, bins=buckets)
    act_counts, _ = np.histogram(act_scaled, bins=buckets)

    exp_pct = exp_counts / (len(exp_arr) + 1e-5)
    act_pct = act_counts / (len(act_arr) + 1e-5)

    # 0 분모 방지 (1e-4 이중 보정)
    exp_pct = np.where(exp_pct == 0, 1e-4, exp_pct)
    act_pct = np.where(act_pct == 0, 1e-4, act_pct)

    psi_val = np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct))
    return float(round(psi_val, 4))


def calculate_categorical_psi(
    expected_counts: dict[str, int] | pd.Series,
    actual_counts: dict[str, int] | pd.Series,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> float:
    """범주형 특징의 PSI 계산."""
    if isinstance(expected_counts, pd.Series):
        exp_dict = expected_counts.to_dict()
    else:
        exp_dict = dict(expected_counts)

    if isinstance(actual_counts, pd.Series):
        act_dict = actual_counts.to_dict()
    else:
        act_dict = dict(actual_counts)

    exp_total = sum(exp_dict.values())
    act_total = sum(act_dict.values())

    if exp_total < min_samples or act_total < min_samples:
        raise InsufficientSampleError(int(exp_total), int(act_total), min_samples)

    all_categories = sorted(set(exp_dict.keys()) | set(act_dict.keys()))

    exp_pcts = []
    act_pcts = []
    for cat in all_categories:
        exp_c = exp_dict.get(cat, 0)
        act_c = act_dict.get(cat, 0)
        exp_pcts.append(exp_c / (exp_total + 1e-5))
        act_pcts.append(act_c / (act_total + 1e-5))

    exp_arr = np.where(np.array(exp_pcts) == 0, 1e-4, np.array(exp_pcts))
    act_arr = np.where(np.array(act_pcts) == 0, 1e-4, np.array(act_pcts))

    psi_val = np.sum((act_arr - exp_arr) * np.log(act_arr / exp_arr))
    return float(round(psi_val, 4))


def check_feature_drift(
    baseline_features: np.ndarray | pd.Series | list[float],
    recent_features: np.ndarray | pd.Series | list[float],
    threshold: float = DEFAULT_PSI_THRESHOLD,
    min_samples: int = DEFAULT_MIN_SAMPLES,
) -> dict[str, Any]:
    """단일 특징 드리프트 검사 및 판단.

    표본이 없거나 부족하면 STABLE 로 승격하지 않고 INSUFFICIENT_DATA 를 돌려줍니다.
    감시할 근거가 없는 상태와 안정된 상태는 다릅니다.
    """
    try:
        psi = calculate_psi(baseline_features, recent_features, min_samples=min_samples)
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
