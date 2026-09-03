"""
src/ml/monitoring.py

PSI(Population Stability Index) 기반 데이터 & 예측 드리프트 감지 모니터링 모듈.
입력 특징 분포 변화(PSI >= 0.2) 탐지 시 알림 발신 및 이력을 기록합니다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from src.app.core.timeutil import utcnow
from src.ml.features import CATEGORICAL_FEATURES, MISSING_CATEGORY
from src.ml.psi import (
    DEFAULT_MIN_SAMPLES,
    DEFAULT_NUM_BUCKETS,
    DEFAULT_PSI_THRESHOLD,
    InsufficientSampleError,
    calculate_categorical_psi,
    calculate_psi,
    check_feature_drift,
)

# fmt: off
__all__ = [
    "DEFAULT_MIN_SAMPLES",
    "DEFAULT_NUM_BUCKETS",
    "DEFAULT_PSI_THRESHOLD",
    "DEFAULT_PSI_THRESHOLD_MISSING_LWLT",
    "DEFAULT_PSI_THRESHOLD_WITH_LWLT",
    "LWLT_RATE_MISSING_COLUMN",
    "SUBGROUP_KEY_MISSING_LWLT",
    "SUBGROUP_KEY_WITH_LWLT",
    "SUBGROUP_THRESHOLDS",
    "InsufficientSampleError",
    "calculate_categorical_psi",
    "calculate_psi",
    "check_dataset_drift",
    "check_feature_drift",
    "load_baseline_distributions",
    "save_baseline_distributions",
]
# fmt: on

logger = logging.getLogger(__name__)

DEFAULT_PSI_THRESHOLD_WITH_LWLT = 0.2
DEFAULT_PSI_THRESHOLD_MISSING_LWLT = 0.25
LWLT_RATE_MISSING_COLUMN = "lwlt_rate_missing"
SUBGROUP_KEY_WITH_LWLT = "0.0"
SUBGROUP_KEY_MISSING_LWLT = "1.0"
SUBGROUP_THRESHOLDS = {
    SUBGROUP_KEY_WITH_LWLT: DEFAULT_PSI_THRESHOLD_WITH_LWLT,
    SUBGROUP_KEY_MISSING_LWLT: DEFAULT_PSI_THRESHOLD_MISSING_LWLT,
}


def _summarize_feature_frame(
    df_feat: pd.DataFrame,
    feature_columns: list[str],
    config: dict[str, Any],
) -> dict[str, Any]:
    """DataFrame 과 특징 목록에 대해 히스토그램 및 빈도수 분포 요약을 생성합니다."""
    features_summary: dict[str, Any] = {}
    num_buckets = int(config.get("num_buckets", DEFAULT_NUM_BUCKETS))
    for col in feature_columns:
        if col not in df_feat.columns:
            continue

        if col in CATEGORICAL_FEATURES or not pd.api.types.is_numeric_dtype(df_feat[col]):
            # 범주형 특징
            series = df_feat[col].astype("string").fillna(MISSING_CATEGORY)
            counts_dict = {str(k): int(v) for k, v in series.value_counts().to_dict().items()}
            categories = sorted(counts_dict.keys())
            features_summary[col] = {
                "type": "categorical",
                "categories": categories,
                "counts": counts_dict,
            }
        else:
            # 수치형 특징
            series = pd.to_numeric(df_feat[col], errors="coerce").dropna()
            if series.empty:
                features_summary[col] = {
                    "type": "numeric",
                    "min": 0.0,
                    "max": 0.0,
                    "mean": 0.0,
                    "std": 0.0,
                    "quantiles": {"0.0": 0.0, "0.25": 0.0, "0.5": 0.0, "0.75": 0.0, "1.0": 0.0},
                    "histogram": {
                        "bins": num_buckets,
                        "counts": [0] * num_buckets,
                        "bin_edges": [0.0] * (num_buckets + 1),
                    },
                }
                continue

            min_v = float(series.min())
            max_v = float(series.max())
            mean_v = float(series.mean())
            std_v = float(series.std()) if len(series) > 1 else 0.0

            q_dict = series.quantile([0.0, 0.25, 0.5, 0.75, 1.0]).to_dict()
            quantiles = {str(k): float(v) for k, v in q_dict.items()}

            counts, bin_edges = np.histogram(series.to_numpy(), bins=num_buckets)
            features_summary[col] = {
                "type": "numeric",
                "min": min_v,
                "max": max_v,
                "mean": mean_v,
                "std": std_v,
                "quantiles": quantiles,
                "histogram": {
                    "bins": num_buckets,
                    "counts": [int(c) for c in counts],
                    "bin_edges": [float(e) for e in bin_edges],
                },
            }
    return features_summary


def save_baseline_distributions(
    df_feat: pd.DataFrame,
    feature_columns: list[str],
    target_dir: Path | str,
    model_name: str,
    model_version: str,
    psi_config: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """학습 성공 시점의 특징 분포 아티팩트를 ml_registry/{model_name}/baseline/ 에 저장합니다."""
    target_path = Path(target_dir)
    target_path.mkdir(parents=True, exist_ok=True)

    has_lwlt_missing_col = (
        LWLT_RATE_MISSING_COLUMN in feature_columns or LWLT_RATE_MISSING_COLUMN in df_feat.columns
    )

    config = {
        "num_buckets": DEFAULT_NUM_BUCKETS,
        "threshold": DEFAULT_PSI_THRESHOLD,
        "min_samples_per_feature": DEFAULT_MIN_SAMPLES,
        **({"subgroup_thresholds": dict(SUBGROUP_THRESHOLDS)} if has_lwlt_missing_col else {}),
        **(psi_config or {}),
    }

    features_summary = _summarize_feature_frame(df_feat, feature_columns, config)
    excluded_features = [c for c in df_feat.columns if c not in feature_columns]

    baseline_payload: dict[str, Any] = {
        "schema_version": 1,
        "model_name": model_name,
        "model_version": model_version,
        "created_at": utcnow().isoformat(),
        "training_samples": len(df_feat),
        "features": features_summary,
        "excluded_features": excluded_features,
        "psi_config": config,
    }

    if has_lwlt_missing_col and LWLT_RATE_MISSING_COLUMN in df_feat.columns:
        # lwlt_rate_missing 값별(0.0 / 1.0)로 분리 저장
        missing_series = pd.to_numeric(df_feat[LWLT_RATE_MISSING_COLUMN], errors="coerce").fillna(
            0.0
        )
        df_sub_0 = df_feat[missing_series == 0.0]
        df_sub_1 = df_feat[missing_series == 1.0]

        baseline_payload["by_lwlt_missing"] = {
            SUBGROUP_KEY_WITH_LWLT: {
                "training_samples": len(df_sub_0),
                "features": _summarize_feature_frame(df_sub_0, feature_columns, config),
            },
            SUBGROUP_KEY_MISSING_LWLT: {
                "training_samples": len(df_sub_1),
                "features": _summarize_feature_frame(df_sub_1, feature_columns, config),
            },
        }

    dist_file = target_path / "feature_distributions_v1.json"
    with open(dist_file, "w", encoding="utf-8") as f:
        json.dump(baseline_payload, f, indent=2, ensure_ascii=False)

    metadata_payload: dict[str, Any] = {
        "schema_version": 1,
        "model_name": model_name,
        "baseline_version": model_version,
        "updated_at": utcnow().isoformat(),
        "training_samples": len(df_feat),
        "features_count": len(features_summary),
        "has_subgroups": "by_lwlt_missing" in baseline_payload,
    }

    meta_file = target_path / "metadata.json"
    with open(meta_file, "w", encoding="utf-8") as f:
        json.dump(metadata_payload, f, indent=2, ensure_ascii=False)

    return baseline_payload


def load_baseline_distributions(baseline_dir: Path | str) -> dict[str, Any] | None:
    """baseline 디렉터리에서 feature_distributions_v1.json 을 읽습니다."""
    path = Path(baseline_dir) / "feature_distributions_v1.json"
    if not path.exists():
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (json.JSONDecodeError, OSError):
        return None


def _evaluate_feature_drift_on_frame(
    baseline_features: dict[str, Any],
    df_recent: pd.DataFrame,
    effective_threshold: float,
    effective_min_samples: int,
    evaluation_window_days: int = 7,
) -> dict[str, Any]:
    """단일 프레임에 대한 특징별 PSI 계산 및 종합 판정."""
    results_by_feature: dict[str, dict[str, Any]] = {}
    recent_row_count = len(df_recent)

    for feat_name, feat_meta in baseline_features.items():
        if feat_name not in df_recent.columns or recent_row_count < effective_min_samples:
            results_by_feature[feat_name] = {
                "psi": None,
                "threshold": effective_threshold,
                "drift_detected": None,
                "action": "INSUFFICIENT_DATA",
                "sample_size": recent_row_count,
                "reason": (
                    f"표본 부족 ({recent_row_count} < {effective_min_samples})"
                    if recent_row_count < effective_min_samples
                    else f"특징 컬럼 누락: {feat_name}"
                ),
            }
            continue

        feat_type = feat_meta.get("type", "numeric")
        if feat_type == "categorical":
            recent_series = df_recent[feat_name].astype("string").fillna(MISSING_CATEGORY)
            recent_counts = {
                str(k): int(v) for k, v in recent_series.value_counts().to_dict().items()
            }
            exp_counts = feat_meta.get("counts", {})
            try:
                psi_val = calculate_categorical_psi(
                    exp_counts, recent_counts, min_samples=effective_min_samples
                )
                drift_detected = psi_val >= effective_threshold
                results_by_feature[feat_name] = {
                    "psi": psi_val,
                    "threshold": effective_threshold,
                    "drift_detected": drift_detected,
                    "action": "TRIGGER_RETRAIN" if drift_detected else "STABLE",
                    "sample_size": recent_row_count,
                }
            except InsufficientSampleError as exc:
                results_by_feature[feat_name] = {
                    "psi": None,
                    "threshold": effective_threshold,
                    "drift_detected": None,
                    "action": "INSUFFICIENT_DATA",
                    "sample_size": recent_row_count,
                    "reason": str(exc),
                }
        else:
            recent_series = pd.to_numeric(df_recent[feat_name], errors="coerce").dropna()
            recent_vals = recent_series.to_numpy(dtype=float)
            hist_info = feat_meta.get("histogram", {})
            bin_edges = hist_info.get("bin_edges")
            exp_counts = hist_info.get("counts")

            if (
                bin_edges
                and exp_counts
                and len(bin_edges) > 1
                and len(exp_counts) > 0
                and len(recent_vals) >= effective_min_samples
            ):
                exp_total = sum(exp_counts)
                if exp_total < effective_min_samples:
                    results_by_feature[feat_name] = {
                        "psi": None,
                        "threshold": effective_threshold,
                        "drift_detected": None,
                        "action": "INSUFFICIENT_DATA",
                        "sample_size": len(recent_vals),
                        "reason": f"Baseline 표본 부족 ({exp_total} < {effective_min_samples})",
                    }
                    continue

                exp_pct = np.array(exp_counts, dtype=float) / (exp_total + 1e-5)
                min_edge = float(bin_edges[0])
                max_edge = float(bin_edges[-1])

                # 경계 밖 값들을 첫/마지막 버킷으로 포함하여 100% 포괄
                act_counts, _ = np.histogram(recent_vals, bins=bin_edges)
                act_counts[0] += int(np.sum(recent_vals < min_edge))
                act_counts[-1] += int(np.sum(recent_vals > max_edge))

                act_pct = act_counts / (len(recent_vals) + 1e-5)
                exp_pct = np.where(exp_pct == 0, 1e-4, exp_pct)
                act_pct = np.where(act_pct == 0, 1e-4, act_pct)

                psi_val = float(round(np.sum((act_pct - exp_pct) * np.log(act_pct / exp_pct)), 4))
                drift_detected = psi_val >= effective_threshold
                results_by_feature[feat_name] = {
                    "psi": psi_val,
                    "threshold": effective_threshold,
                    "drift_detected": drift_detected,
                    "action": "TRIGGER_RETRAIN" if drift_detected else "STABLE",
                    "sample_size": len(recent_vals),
                }
            else:
                if len(recent_vals) < effective_min_samples:
                    results_by_feature[feat_name] = {
                        "psi": None,
                        "threshold": effective_threshold,
                        "drift_detected": None,
                        "action": "INSUFFICIENT_DATA",
                        "sample_size": len(recent_vals),
                        "reason": f"유효 수치 표본 부족 ({len(recent_vals)} < {effective_min_samples})",
                    }
                else:
                    results_by_feature[feat_name] = {
                        "psi": None,
                        "threshold": effective_threshold,
                        "drift_detected": None,
                        "action": "INSUFFICIENT_DATA",
                        "sample_size": len(recent_vals),
                        "reason": "Baseline 히스토그램 정보 부족",
                    }

    drift_features = [
        {"feature": name, "psi": r["psi"], "sample_size": r["sample_size"]}
        for name, r in results_by_feature.items()
        if r.get("drift_detected") is True
    ]

    has_drift = len(drift_features) > 0
    has_insufficient = any(
        r.get("action") == "INSUFFICIENT_DATA" for r in results_by_feature.values()
    )

    if has_drift:
        overall_action = "TRIGGER_RETRAIN"
        verdict_status = "DRIFT_DETECTED"
    elif has_insufficient:
        overall_action = "INSUFFICIENT_DATA"
        verdict_status = "INSUFFICIENT_DATA"
    else:
        overall_action = "STABLE"
        verdict_status = "STABLE"

    return {
        "status": verdict_status,
        "overall_action": overall_action,
        "drift_feature_count": len(drift_features),
        "drift_features": drift_features,
        "total_features_checked": len(results_by_feature),
        "evaluation_window_days": evaluation_window_days,
        "recent_samples": recent_row_count,
        "drift_results": results_by_feature,
    }


def check_dataset_drift(
    baseline_dist: dict[str, Any],
    df_recent: pd.DataFrame,
    threshold: float | None = None,
    min_samples: int | None = None,
    evaluation_window_days: int = 7,
) -> dict[str, Any]:
    """최근 데이터셋(Single Source of Truth features.py 로 구축됨)과 baseline 간 다차원 PSI 계산.

    - baseline 에 by_lwlt_missing 키가 있고 df_recent 에 lwlt_rate_missing 컬럼이 있으면
      lwlt_rate_missing(0.0: with_lwlt, 1.0: missing_lwlt) 집단별로 분리 평가를 수행합니다.
    - with_lwlt 임계는 0.2, missing_lwlt 임계는 0.25 로 완화 적용됩니다.
    - 두 집단 중 하나라도 TRIGGER_RETRAIN 이면 전체 모델이 TRIGGER_RETRAIN (DRIFT_DETECTED)이 됩니다.
    - missing_lwlt 단독 미달 시 drift_subgroup_type="missing_lwlt_only" 로 라벨이 차별화됩니다.
    - 표본 부족(100건) 기준은 집단별로 각각 적용됩니다.
    - by_lwlt_missing 키가 없는 옛 baseline 이나 lwlt_rate_missing 특징이 없는 모델에서는
      단일 집단 방식으로 평가하며 로그를 남깁니다.
    """
    psi_cfg = baseline_dist.get("psi_config", {})
    effective_threshold = (
        threshold
        if threshold is not None
        else float(psi_cfg.get("threshold", DEFAULT_PSI_THRESHOLD))
    )
    effective_min_samples = (
        min_samples
        if min_samples is not None
        else int(psi_cfg.get("min_samples_per_feature", DEFAULT_MIN_SAMPLES))
    )

    by_lwlt_missing = baseline_dist.get("by_lwlt_missing")

    # 집단 분리 적용 조건 검사: baseline 에 by_lwlt_missing 키가 있고 recent 데이터에 lwlt_rate_missing 특징 존재
    if by_lwlt_missing is not None and LWLT_RATE_MISSING_COLUMN in df_recent.columns:
        subgroup_thresholds = psi_cfg.get("subgroup_thresholds", SUBGROUP_THRESHOLDS)
        sub_0_thresh = (
            threshold
            if threshold is not None
            else float(
                subgroup_thresholds.get(SUBGROUP_KEY_WITH_LWLT, DEFAULT_PSI_THRESHOLD_WITH_LWLT)
            )
        )
        sub_1_thresh = (
            threshold
            if threshold is not None
            else float(
                subgroup_thresholds.get(
                    SUBGROUP_KEY_MISSING_LWLT, DEFAULT_PSI_THRESHOLD_MISSING_LWLT
                )
            )
        )

        missing_series = pd.to_numeric(df_recent[LWLT_RATE_MISSING_COLUMN], errors="coerce").fillna(
            0.0
        )
        recent_sub_0 = df_recent[missing_series == 0.0]
        recent_sub_1 = df_recent[missing_series == 1.0]

        sub_0_meta = by_lwlt_missing.get(SUBGROUP_KEY_WITH_LWLT, {})
        sub_0_feat_dist = sub_0_meta.get("features", sub_0_meta)

        sub_1_meta = by_lwlt_missing.get(SUBGROUP_KEY_MISSING_LWLT, {})
        sub_1_feat_dist = sub_1_meta.get("features", sub_1_meta)

        # 0.0 (with_lwlt) 집단 평가
        if len(recent_sub_0) < effective_min_samples:
            sub_0_res: dict[str, Any] = {
                "status": "INSUFFICIENT_DATA",
                "overall_action": "INSUFFICIENT_DATA",
                "drift_feature_count": 0,
                "drift_features": [],
                "total_features_checked": len(sub_0_feat_dist),
                "recent_samples": len(recent_sub_0),
                "threshold": sub_0_thresh,
                "reason": f"표본 부족 ({len(recent_sub_0)} < {effective_min_samples})",
                "drift_results": {},
            }
        else:
            sub_0_res = _evaluate_feature_drift_on_frame(
                sub_0_feat_dist,
                recent_sub_0,
                effective_threshold=sub_0_thresh,
                effective_min_samples=effective_min_samples,
                evaluation_window_days=evaluation_window_days,
            )
            sub_0_res["threshold"] = sub_0_thresh

        # 1.0 (missing_lwlt) 집단 평가
        if len(recent_sub_1) < effective_min_samples:
            sub_1_res: dict[str, Any] = {
                "status": "INSUFFICIENT_DATA",
                "overall_action": "INSUFFICIENT_DATA",
                "drift_feature_count": 0,
                "drift_features": [],
                "total_features_checked": len(sub_1_feat_dist),
                "recent_samples": len(recent_sub_1),
                "threshold": sub_1_thresh,
                "reason": f"표본 부족 ({len(recent_sub_1)} < {effective_min_samples})",
                "drift_results": {},
            }
        else:
            sub_1_res = _evaluate_feature_drift_on_frame(
                sub_1_feat_dist,
                recent_sub_1,
                effective_threshold=sub_1_thresh,
                effective_min_samples=effective_min_samples,
                evaluation_window_days=evaluation_window_days,
            )
            sub_1_res["threshold"] = sub_1_thresh

        sub_0_drift = sub_0_res.get("status") == "DRIFT_DETECTED"
        sub_1_drift = sub_1_res.get("status") == "DRIFT_DETECTED"
        sub_0_insufficient = sub_0_res.get("status") == "INSUFFICIENT_DATA"
        sub_1_insufficient = sub_1_res.get("status") == "INSUFFICIENT_DATA"

        combined_drift_features: list[dict[str, Any]] = []
        for feat in sub_0_res.get("drift_features", []):
            combined_drift_features.append(
                {**feat, "subgroup": "with_lwlt", "subgroup_key": SUBGROUP_KEY_WITH_LWLT}
            )
        for feat in sub_1_res.get("drift_features", []):
            combined_drift_features.append(
                {**feat, "subgroup": "missing_lwlt", "subgroup_key": SUBGROUP_KEY_MISSING_LWLT}
            )

        if sub_0_drift or sub_1_drift:
            overall_action = "TRIGGER_RETRAIN"
            verdict_status = "DRIFT_DETECTED"
            if sub_1_drift and not sub_0_drift:
                drift_subgroup_type = "missing_lwlt_only"
            elif sub_0_drift and not sub_1_drift:
                drift_subgroup_type = "with_lwlt_only"
            else:
                drift_subgroup_type = "both"
        elif sub_0_insufficient or sub_1_insufficient:
            overall_action = "INSUFFICIENT_DATA"
            verdict_status = "INSUFFICIENT_DATA"
            drift_subgroup_type = None
        else:
            overall_action = "STABLE"
            verdict_status = "STABLE"
            drift_subgroup_type = None

        merged_drift_results: dict[str, dict[str, Any]] = {}
        for k, v in sub_0_res.get("drift_results", {}).items():
            merged_drift_results[f"{k} (with_lwlt)"] = v
        for k, v in sub_1_res.get("drift_results", {}).items():
            merged_drift_results[f"{k} (missing_lwlt)"] = v

        return {
            "status": verdict_status,
            "overall_action": overall_action,
            "drift_feature_count": len(combined_drift_features),
            "drift_features": combined_drift_features,
            "total_features_checked": len(sub_0_feat_dist) + len(sub_1_feat_dist),
            "evaluation_window_days": evaluation_window_days,
            "baseline_version": baseline_dist.get("model_version", ""),
            "recent_samples": len(df_recent),
            "drift_results": merged_drift_results,
            "by_subgroup": {
                SUBGROUP_KEY_WITH_LWLT: sub_0_res,
                SUBGROUP_KEY_MISSING_LWLT: sub_1_res,
            },
            "drift_subgroup_type": drift_subgroup_type,
        }

    # 옛 baseline 이거나 lwlt_rate_missing 특징이 없는 모델: 기존 단일 집단 방식으로 평가
    if by_lwlt_missing is None:
        logger.info(
            "Baseline 에 by_lwlt_missing 키가 없어 기존 단일 집단 방식으로 드리프트를 평가합니다."
        )
    elif LWLT_RATE_MISSING_COLUMN not in df_recent.columns:
        logger.info(
            "평가 데이터에 %s 특징이 없어 기존 단일 집단 방식으로 드리프트를 평가합니다.",
            LWLT_RATE_MISSING_COLUMN,
        )

    baseline_features = baseline_dist.get("features", {})
    result = _evaluate_feature_drift_on_frame(
        baseline_features,
        df_recent,
        effective_threshold=effective_threshold,
        effective_min_samples=effective_min_samples,
        evaluation_window_days=evaluation_window_days,
    )
    result["baseline_version"] = baseline_dist.get("model_version", "")
    return result
