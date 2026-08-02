"""
src/ml/features.py

Single Source of Truth (단일 특징 공급원)
학습과 추론의 모든 특징 추출은 본 모듈을 거쳐 산출됩니다.
"""

from __future__ import annotations

import math
from typing import Any

import numpy as np
import pandas as pd

from src.ml.institution_history import lookup_institution_history

DEFAULT_INST_RATE = 0.925
DEFAULT_INST_RATE_STD = 0.015
DEFAULT_NOTICE_DURATION_DAYS = 14.0
DEFAULT_INSTITUTION_NAME = "미상기관"
DEFAULT_PPI = 100.0
DEFAULT_EXCHANGE_RATE = 1300.0


def _coerce_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return float(default)
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return float(default)
    if not math.isfinite(numeric):
        return float(default)
    return numeric


def _coerce_timestamp(value: Any):
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(ts) else ts


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    try:
        return bool(pd.isna(value))
    except TypeError:
        return False


def _get_reference_timestamp(features_dict: dict[str, Any]):
    for key in ("openg_dt", "bid_clse_dt", "bid_ntce_dt"):
        ts = _coerce_timestamp(features_dict.get(key))
        if ts is not None:
            return ts
    return pd.Timestamp.now()


def _get_notice_duration_days(features_dict: dict[str, Any], reference_ts) -> float:
    start = _coerce_timestamp(features_dict.get("bid_ntce_dt"))
    end = _coerce_timestamp(features_dict.get("bid_clse_dt")) or reference_ts
    if start is not None and end is not None:
        delta_days = (end - start).total_seconds() / 86400
        return max(delta_days, 0.0)
    return _coerce_float(features_dict.get("notice_duration"), DEFAULT_NOTICE_DURATION_DAYS)


def _get_institution_name(features_dict: dict[str, Any]) -> str:
    for key in ("ntceInsttNm", "ntce_instt_nm", "dminstt_nm", "order_institution"):
        value = features_dict.get(key)
        if value:
            return str(value)
    return DEFAULT_INSTITUTION_NAME


def build_default_feature_map(
    features_dict: dict[str, Any],
    session: Any = None,
) -> dict[str, Any]:
    reference_ts = _get_reference_timestamp(features_dict)
    price = max(
        _coerce_float(
            features_dict.get("real_budget", features_dict.get("presumed_price", features_dict.get("presmpt_prce"))),
            0.0,
        ),
        0.0,
    )
    log_price = np.log1p(price) if price > 0 else 0.0
    # 학습 경로는 trainer 가 attach_institution_history 로 미리 채워 넣습니다.
    # 추론 경로는 값이 없으므로 여기서 조회합니다. 정의는 양쪽 모두
    # "기준 시점 이전 같은 기관의 낙찰률 평균" 으로 같습니다.
    # `or` 를 쓰면 0.0 이 falsy 로 걸려 조회로 새므로 None 검사를 씁니다.
    provided_rate = features_dict.get("inst_hist_rate")
    if provided_rate is None:
        provided_rate = lookup_institution_history(features_dict, session)
    inst_hist_rate = _coerce_float(provided_rate, DEFAULT_INST_RATE)

    inst_sample_cnt = _coerce_float(features_dict.get("inst_sample_cnt"), 0.0)
    inst_rate_mean_30d = _coerce_float(features_dict.get("inst_rate_mean_30d"), inst_hist_rate)
    inst_rate_std_90d = _coerce_float(features_dict.get("inst_rate_std_90d"), DEFAULT_INST_RATE_STD)
    # 데이터셋은 기초금액을 base_amount 로 내보냅니다. 별칭을 받지 않으면
    # base_price 가 항상 price 로 폴백해 price_ratio 가 상수 1.0 이 됩니다.
    base_price = _coerce_float(
        features_dict.get("base_price", features_dict.get("base_amount")), price
    )
    price_ratio = (base_price / price) if price > 0 else 1.0

    feature_map: dict[str, Any] = {
        "log_price": log_price,
        "month": float(reference_ts.month),
        "weekday": float(reference_ts.weekday()),
        "month_sin": float(np.sin(2 * np.pi * reference_ts.month / 12)),
        "month_cos": float(np.cos(2 * np.pi * reference_ts.month / 12)),
        "weekday_sin": float(np.sin(2 * np.pi * reference_ts.weekday() / 7)),
        "weekday_cos": float(np.cos(2 * np.pi * reference_ts.weekday() / 7)),
        "notice_duration": _get_notice_duration_days(features_dict, reference_ts),
        "inst_part_avg": _coerce_float(features_dict.get("inst_part_avg"), inst_hist_rate),
        "ppi": _coerce_float(features_dict.get("ppi"), DEFAULT_PPI),
        "ex_rate": _coerce_float(features_dict.get("ex_rate"), DEFAULT_EXCHANGE_RATE),
        "real_budget": price,
        "presumed_price": price,
        "presmpt_prce": price,
        "base_price": base_price,
        "price_ratio": price_ratio,
        "inst_hist_rate": inst_hist_rate,
        # 이력 표본 수. 모델이 이력값을 얼마나 신뢰할지 판단하는 근거가 됩니다.
        "inst_sample_cnt": inst_sample_cnt,
        "inst_rate_mean_30d": inst_rate_mean_30d,
        "inst_rate_std_90d": inst_rate_std_90d,
        "ntceInsttNm": _get_institution_name(features_dict),
        "category": str(features_dict.get("category_code") or features_dict.get("category") or "Thng"),
        "category_code": str(features_dict.get("category_code") or features_dict.get("category") or "Thng"),
        "silo_id": _coerce_float(features_dict.get("silo_id"), 0.0),
        "pred_tier": _coerce_float(features_dict.get("pred_tier"), 0.0),
        "q50": _coerce_float(features_dict.get("q50"), 0.0),
        "count_spread": _coerce_float(features_dict.get("count_spread"), 0.0),
        "log_price_density_q50": _coerce_float(features_dict.get("log_price_density_q50"), 0.0),
    }
    for idx in range(32):
        key = f"sem_{idx}"
        feature_map[key] = _coerce_float(features_dict.get(key), 0.0)
    for idx in (10, 12, 13, 17, 30):
        feature_map[f"inter_sem_{idx}"] = _coerce_float(
            features_dict.get(f"inter_sem_{idx}"),
            feature_map["log_price"] * feature_map[f"sem_{idx}"],
        )
        feature_map[f"inst_inter_sem_{idx}"] = _coerce_float(
            features_dict.get(f"inst_inter_sem_{idx}"),
            feature_map["inst_hist_rate"] * feature_map[f"sem_{idx}"],
        )
    return feature_map


def prepare_input_frame(feature_values: dict[str, Any], column_order: list[str]) -> pd.DataFrame:
    defaults = build_default_feature_map(feature_values)
    row: dict[str, Any] = {}
    for column in column_order:
        default = defaults.get(column, 0.0)
        value = feature_values.get(column, default)
        if _is_missing(value):
            value = default
        if isinstance(default, str):
            row[column] = str(value) if value not in (None, "") else default
        else:
            row[column] = _coerce_float(value, default)
    return pd.DataFrame([row], columns=column_order)


def prepare_features(
    features_dict: dict[str, Any],
    session: Any = None,
) -> pd.DataFrame:
    feature_names = [
        "log_price",
        "month",
        "weekday",
        "month_sin",
        "month_cos",
        "weekday_sin",
        "weekday_cos",
        "inst_hist_rate",
        "inst_rate_mean_30d",
        "inst_rate_std_90d",
    ] + [f"sem_{idx}" for idx in range(32)] + [
        "inter_sem_10",
        "inter_sem_12",
        "inter_sem_13",
        "inter_sem_17",
        "inter_sem_30",
        "inst_inter_sem_10",
        "inst_inter_sem_12",
        "inst_inter_sem_13",
        "inst_inter_sem_17",
        "inst_inter_sem_30",
    ]
    return prepare_input_frame(features_dict, feature_names)


def build_feature_dict(
    request_data: dict[str, Any],
    session: Any = None,
) -> dict[str, Any]:
    return build_default_feature_map(request_data, session)


def build_feature_frame(
    df_records: list[dict[str, Any]],
    session: Any = None,
) -> list[dict[str, Any]]:
    return [build_default_feature_map(rec, session) for rec in df_records]
