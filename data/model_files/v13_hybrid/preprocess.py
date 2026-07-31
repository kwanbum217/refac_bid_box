import numpy as np
import pandas as pd


DEFAULT_NOTICE_DURATION_DAYS = 14.0
DEFAULT_INST_RATE = 0.925
DEFAULT_PPI = 100.0
DEFAULT_EXCHANGE_RATE = 1300.0


def _safe_float(value, default=0.0):
    try:
        number = float(value)
    except (TypeError, ValueError):
        return float(default)
    return number if np.isfinite(number) else float(default)


def _safe_timestamp(value):
    if value in (None, ""):
        return None
    try:
        ts = pd.Timestamp(value)
    except (TypeError, ValueError):
        return None
    return None if pd.isna(ts) else ts


def _reference_ts(features_dict):
    for key in ("openg_dt", "bid_clse_dt", "bid_ntce_dt"):
        ts = _safe_timestamp(features_dict.get(key))
        if ts is not None:
            return ts
    return pd.Timestamp.now()


def _notice_duration_days(features_dict, reference_ts):
    start = _safe_timestamp(features_dict.get("bid_ntce_dt"))
    end = _safe_timestamp(features_dict.get("bid_clse_dt")) or reference_ts
    if start is not None and end is not None:
        return max((end - start).total_seconds() / 86400, 0.0)
    return _safe_float(
        features_dict.get("notice_duration"),
        DEFAULT_NOTICE_DURATION_DAYS,
    )


def preprocess(features_dict):
    """v13 Hybrid 번들이 요구하는 1/2단계 입력 피처를 함께 준비합니다."""
    feature_names = [
        "log_price",
        "notice_duration",
        "inst_part_avg",
        "month",
        "weekday",
        "ppi",
        "ex_rate",
        "real_budget",
        "ntceInsttNm",
        "inst_hist_rate",
        "silo_id",
        "pred_tier",
        "q50",
        "count_spread",
        "log_price_density_q50",
    ]
    df = pd.DataFrame(index=[0], columns=feature_names)

    price = max(_safe_float(features_dict.get("presmpt_prce"), 0.0), 0.0)
    reference_ts = _reference_ts(features_dict)
    institution_name = (
        features_dict.get("ntceInsttNm")
        or features_dict.get("ntce_instt_nm")
        or features_dict.get("dminstt_nm")
        or "미상기관"
    )
    inst_rate = _safe_float(features_dict.get("inst_hist_rate"), DEFAULT_INST_RATE)

    df.at[0, "log_price"] = np.log1p(price) if price > 0 else 0.0
    df.at[0, "notice_duration"] = _notice_duration_days(features_dict, reference_ts)
    df.at[0, "inst_part_avg"] = _safe_float(
        features_dict.get("inst_part_avg"),
        inst_rate,
    )
    df.at[0, "month"] = float(reference_ts.month)
    df.at[0, "weekday"] = float(reference_ts.weekday())
    df.at[0, "ppi"] = _safe_float(features_dict.get("ppi"), DEFAULT_PPI)
    df.at[0, "ex_rate"] = _safe_float(
        features_dict.get("ex_rate"),
        DEFAULT_EXCHANGE_RATE,
    )
    df.at[0, "real_budget"] = _safe_float(
        features_dict.get("real_budget"),
        price,
    )
    df.at[0, "ntceInsttNm"] = str(institution_name)
    df.at[0, "inst_hist_rate"] = inst_rate
    df.at[0, "silo_id"] = _safe_float(features_dict.get("silo_id"), 0.0)
    df.at[0, "pred_tier"] = _safe_float(features_dict.get("pred_tier"), 0.0)
    df.at[0, "q50"] = _safe_float(features_dict.get("q50"), 0.0)
    df.at[0, "count_spread"] = _safe_float(features_dict.get("count_spread"), 0.0)
    df.at[0, "log_price_density_q50"] = _safe_float(
        features_dict.get("log_price_density_q50"),
        0.0,
    )
    return df
