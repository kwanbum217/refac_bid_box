import hashlib
import re

import numpy as np
import pandas as pd


SEMANTIC_DIMS = 32
INTERACTION_INDEXES = (10, 12, 13, 17, 30)
DEFAULT_INST_RATE = 0.925
DEFAULT_INST_RATE_STD = 0.015


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


def _build_semantic_vector(text, dims=SEMANTIC_DIMS):
    vector = np.zeros(dims, dtype=float)
    tokens = [token for token in re.split(r"[^0-9A-Za-z가-힣]+", text) if token]
    if not tokens:
        return vector

    for token in tokens:
        digest = hashlib.sha256(token.encode("utf-8")).digest()
        index = digest[0] % dims
        sign = 1.0 if digest[1] % 2 == 0 else -1.0
        magnitude = 1.0 + (digest[2] / 255.0)
        vector[index] += sign * magnitude

    norm = np.linalg.norm(vector)
    return vector / norm if norm else vector


def preprocess(features_dict):
    """V25 앙상블이 요구하는 52차원 입력 피처를 생성합니다."""
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
    ] + [f"sem_{idx}" for idx in range(SEMANTIC_DIMS)] + [
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

    df = pd.DataFrame(0.0, index=[0], columns=feature_names)
    reference_ts = _reference_ts(features_dict)
    price = max(_safe_float(features_dict.get("presmpt_prce"), 0.0), 0.0)
    inst_rate = _safe_float(features_dict.get("inst_hist_rate"), DEFAULT_INST_RATE)
    inst_rate_mean_30d = _safe_float(
        features_dict.get("inst_rate_mean_30d"),
        inst_rate,
    )
    inst_rate_std_90d = _safe_float(
        features_dict.get("inst_rate_std_90d"),
        DEFAULT_INST_RATE_STD,
    )
    semantic_seed = " ".join(
        str(part).strip()
        for part in (
            features_dict.get("bid_ntce_nm"),
            features_dict.get("ntce_instt_nm"),
            features_dict.get("dminstt_nm"),
            features_dict.get("category"),
        )
        if part
    ) or "BIDBOX"
    semantic_vector = _build_semantic_vector(semantic_seed)

    df.at[0, "log_price"] = np.log1p(price) if price > 0 else 0.0
    df.at[0, "month"] = float(reference_ts.month)
    df.at[0, "weekday"] = float(reference_ts.weekday())
    df.at[0, "month_sin"] = np.sin(2 * np.pi * reference_ts.month / 12)
    df.at[0, "month_cos"] = np.cos(2 * np.pi * reference_ts.month / 12)
    df.at[0, "weekday_sin"] = np.sin(2 * np.pi * reference_ts.weekday() / 7)
    df.at[0, "weekday_cos"] = np.cos(2 * np.pi * reference_ts.weekday() / 7)
    df.at[0, "inst_hist_rate"] = inst_rate
    df.at[0, "inst_rate_mean_30d"] = inst_rate_mean_30d
    df.at[0, "inst_rate_std_90d"] = inst_rate_std_90d

    for idx, value in enumerate(semantic_vector):
        df.at[0, f"sem_{idx}"] = float(value)

    for idx in INTERACTION_INDEXES:
        df.at[0, f"inter_sem_{idx}"] = (
            df.at[0, "log_price"] * df.at[0, f"sem_{idx}"]
        )
        df.at[0, f"inst_inter_sem_{idx}"] = (
            df.at[0, "inst_hist_rate"] * df.at[0, f"sem_{idx}"]
        )

    return df
