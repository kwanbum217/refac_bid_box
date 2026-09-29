"""
src/ml/drift_verdict.py

PSI 드리프트 판정 규칙.

평가 창과 기준선 구성의 차이를 그대로 반영해 구조적으로 오탐하는 달력 특징 4종과
is_post_regime_shift 를 판정에서 제외하고, 제외 후 드리프트 특징이 정족수 이상일 때만
창 드리프트로 인정합니다. 겹치지 않는 직전 창까지 창 드리프트였을 때만 알림 단계로
확정합니다. monitoring.py 를 import 하지 않아 순환을 만들지 않습니다.
"""

from __future__ import annotations

from typing import Any

DRIFT_VERDICT_EXCLUDED_FEATURES = frozenset(
    {
        "month_sin",
        "month_cos",
        "weekday_sin",
        "weekday_cos",
        "is_post_regime_shift",
    }
)

# 제외 후 드리프트 특징이 이 개수 이상일 때만 창 드리프트로 인정합니다.
DRIFT_FEATURE_QUORUM = 2

# 직전 겹치지 않는 창까지 창 드리프트여야 DRIFT_DETECTED 로 확정합니다.
DRIFT_PERSISTENCE_WINDOWS = 2

__all__ = [
    "DRIFT_FEATURE_QUORUM",
    "DRIFT_PERSISTENCE_WINDOWS",
    "DRIFT_VERDICT_EXCLUDED_FEATURES",
    "apply_drift_persistence",
    "summarize_drift_verdict",
    "tag_subgroup_entries",
]


def tag_subgroup_entries(
    entries: list[dict[str, Any]],
    subgroup: str,
    subgroup_key: str,
) -> list[dict[str, Any]]:
    """집단별 드리프트 항목에 subgroup 라벨을 붙여 합칠 수 있게 합니다."""
    return [{**entry, "subgroup": subgroup, "subgroup_key": subgroup_key} for entry in entries]


def _mark_excluded(
    results_by_feature: dict[str, dict[str, Any]],
    excluded_features: frozenset[str],
) -> None:
    for feat_name, feat_result in results_by_feature.items():
        if feat_name in excluded_features:
            feat_result["excluded_from_verdict"] = True


def summarize_drift_verdict(
    results_by_feature: dict[str, dict[str, Any]],
    excluded_features: frozenset[str],
    quorum: int,
) -> dict[str, Any]:
    """특징별 PSI 결과를 제외·정족수 규칙으로 집계한 판정 필드를 돌려줍니다.

    제외 특징도 drift_results 에는 남기되 excluded_from_verdict 로 표시하고
    drift_features 와 INSUFFICIENT_DATA, 정족수 계산에서는 뺍니다.
    """
    _mark_excluded(results_by_feature, excluded_features)

    def _entry(name: str, result: dict[str, Any]) -> dict[str, Any]:
        return {"feature": name, "psi": result["psi"], "sample_size": result["sample_size"]}

    drift_features = [
        _entry(name, result)
        for name, result in results_by_feature.items()
        if result.get("drift_detected") is True and name not in excluded_features
    ]
    excluded_drift_features = [
        _entry(name, result)
        for name, result in results_by_feature.items()
        if result.get("drift_detected") is True and name in excluded_features
    ]
    has_insufficient = any(
        result.get("action") == "INSUFFICIENT_DATA"
        for name, result in results_by_feature.items()
        if name not in excluded_features
    )

    drift_feature_count = len(drift_features)
    below_quorum = False
    if drift_feature_count >= quorum:
        overall_action, verdict_status = "TRIGGER_RETRAIN", "DRIFT_DETECTED"
    elif drift_feature_count >= 1:
        below_quorum = True
        overall_action, verdict_status = "STABLE", "STABLE"
    elif has_insufficient:
        overall_action, verdict_status = "INSUFFICIENT_DATA", "INSUFFICIENT_DATA"
    else:
        overall_action, verdict_status = "STABLE", "STABLE"

    return {
        "status": verdict_status,
        "overall_action": overall_action,
        "drift_feature_count": drift_feature_count,
        "drift_features": drift_features,
        "excluded_drift_features": excluded_drift_features,
        "excluded_features": sorted(excluded_features),
        "quorum": quorum,
        "below_quorum": below_quorum,
    }


def apply_drift_persistence(
    verdict: dict[str, Any],
    previous_window_drift: bool | None,
    *,
    required_windows: int = DRIFT_PERSISTENCE_WINDOWS,
) -> dict[str, Any]:
    """겹치지 않는 직전 평가 창의 창 드리프트 여부로 지속성 조건을 적용한 판정을 돌려줍니다.

    지속성 창 수가 2 이면 이번 창과 직전 창이 모두 창 드리프트여야 DRIFT_DETECTED 로
    확정합니다. 직전 창이 아니면 DRIFT_PENDING 으로 보류해 알림을 내보내지 않습니다.
    규칙 도입 직후에는 직전 창 기록이 없어 None 이 들어오므로 첫 주는 DRIFT_PENDING 으로만
    남는 것이 설계 의도입니다.
    """
    if required_windows not in (1, 2):
        raise ValueError(f"지원하지 않는 지속성 창 수입니다: {required_windows}")

    result = dict(verdict)
    window_drift = verdict.get("status") == "DRIFT_DETECTED"
    result["window_drift"] = window_drift
    result["previous_window_drift"] = previous_window_drift
    result["persistence_required_windows"] = required_windows

    if required_windows == 2 and window_drift and previous_window_drift is not True:
        result["status"] = "DRIFT_PENDING"
        result["overall_action"] = "PENDING_PERSISTENCE"

    return result
