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
from src.ml.repeat_history import (
    DEFAULT_REPEAT_RATE,
    NO_HISTORY_DAYS,
    lookup_repeat_history,
)

DEFAULT_INST_RATE = 0.925
DEFAULT_INST_RATE_STD = 0.015
DEFAULT_NOTICE_DURATION_DAYS = 14.0
DEFAULT_INSTITUTION_NAME = "미상기관"
DEFAULT_PPI = 100.0
DEFAULT_EXCHANGE_RATE = 1300.0

# 낙찰하한율 2%p 일괄 인상 시행일. 이 날 이후 최초 공고분부터 신 기준이 적용됩니다.
# 근거: 조달청공고 제2026-260호
REGIME_SHIFT_DATE = pd.Timestamp("2026-05-26")

# WTO 정부조달협정 기준 고시금액(중앙행정기관 물품·용역). 적격심사 배점표의
# 구간을 가르는 임계값이라 연도별 실제 값을 써야 합니다.
NOTICE_AMOUNT_BY_YEAR = {2025: 230_000_000, 2026: 230_000_000}
DEFAULT_NOTICE_AMOUNT = 220_000_000

MISSING_CATEGORY = "미상"

# 범주형으로 학습하는 제도 특징입니다. 학습과 추론이 같은 범주 수준을 써야
# 코드가 어긋나지 않으므로, 수준 목록을 모델 메타데이터에 저장하고
# apply_categorical_dtypes 로 양쪽에서 동일하게 되살립니다.
CATEGORICAL_FEATURES = (
    "srvce_div_nm",
    "lrg_clsfc_nm",
    "cntrct_mthd_nm",
    "prearng_mthd",
    "sucsfbid_mthd_nm",
    "mid_clsfc_nm",
    "clsfc_nm",
    "ntce_kind_nm",
    "bid_methd_nm",
    "intrbid_yn",
    "ppsw_gnrl_srvce_yn",
)


def collect_category_levels(df: pd.DataFrame) -> dict[str, list[str]]:
    """학습 프레임에서 범주 수준을 뽑습니다. 결과는 모델과 함께 저장합니다."""
    levels: dict[str, list[str]] = {}
    for column in CATEGORICAL_FEATURES:
        if column not in df.columns:
            continue
        values = df[column].astype("string").fillna(MISSING_CATEGORY)
        unique = sorted(set(values.tolist()) | {MISSING_CATEGORY})
        levels[column] = unique
    return levels


def apply_categorical_dtypes(
    df: pd.DataFrame,
    levels: dict[str, list[str]] | None,
) -> pd.DataFrame:
    """저장된 범주 수준으로 dtype 을 복원합니다.

    수준을 고정하지 않으면 추론 시점 프레임의 범주 코드가 학습 때와 달라져
    모델이 조용히 다른 값을 읽습니다. train/serve skew 의 전형적인 형태입니다.
    학습에서 못 본 값은 MISSING_CATEGORY 로 되돌립니다. 소분류 200종은 신규
    코드가 계속 생기므로 미학습 값 유입은 예외가 아니라 상시 상황입니다.
    """
    if not levels:
        return df
    out = df.copy()
    for column, categories in levels.items():
        if column not in out.columns:
            continue
        dtype = pd.CategoricalDtype(categories=categories)
        # astype 에 미학습 값을 그대로 넘기면 pandas 4 에서 예외가 됩니다.
        # 수준 밖 값을 먼저 MISSING_CATEGORY 로 접어 넣고 변환합니다.
        known = set(categories)
        fallback = MISSING_CATEGORY if MISSING_CATEGORY in known else None
        normalized = out[column].astype("string").fillna(MISSING_CATEGORY)
        if fallback is not None:
            normalized = normalized.where(normalized.isin(known), fallback)
        out[column] = normalized.astype(dtype)
    return out


def _notice_amount_for(reference_ts) -> float:
    return float(NOTICE_AMOUNT_BY_YEAR.get(reference_ts.year, DEFAULT_NOTICE_AMOUNT))


def _repeat_features(features_dict: dict[str, Any], session: Any) -> dict[str, float]:
    """재발주 이력 6종을 확정합니다.

    프레임에 값이 있으면 그대로 씁니다(학습 경로). 없으면 조회하고, 조회도
    실패하면 "이력 없음" 기본값으로 채웁니다.
    """
    if features_dict.get("is_repeat") is not None:
        return {
            "is_repeat": _coerce_float(features_dict.get("is_repeat"), 0.0),
            "repeat_cnt": _coerce_float(features_dict.get("repeat_cnt"), 0.0),
            "repeat_hist_rate": _coerce_float(
                features_dict.get("repeat_hist_rate"), DEFAULT_REPEAT_RATE
            ),
            "repeat_prev_rate": _coerce_float(
                features_dict.get("repeat_prev_rate"), DEFAULT_REPEAT_RATE
            ),
            "repeat_hist_std": _coerce_float(features_dict.get("repeat_hist_std"), 0.0),
            "repeat_days_since": _coerce_float(
                features_dict.get("repeat_days_since"), NO_HISTORY_DAYS
            ),
        }

    found = lookup_repeat_history(features_dict, session)
    if found is not None:
        return found
    return {
        "is_repeat": 0.0,
        "repeat_cnt": 0.0,
        "repeat_hist_rate": DEFAULT_REPEAT_RATE,
        "repeat_prev_rate": DEFAULT_REPEAT_RATE,
        "repeat_hist_std": 0.0,
        "repeat_days_since": NO_HISTORY_DAYS,
    }


def _coerce_category(value: Any) -> str:
    if _is_missing(value) or value == "":
        return MISSING_CATEGORY
    return str(value)


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

    # 재발주 이력도 같은 구조입니다. 학습은 trainer 가 attach_repeat_history 로
    # 미리 채우고, 추론은 여기서 조회합니다. 정의는 "기준 시점 이전 같은 기관의
    # 같은 사업(정규화 공고명) 낙찰 결과" 로 양쪽이 같습니다.
    repeat = _repeat_features(features_dict, session)

    inst_sample_cnt = _coerce_float(features_dict.get("inst_sample_cnt"), 0.0)
    inst_rate_mean_30d = _coerce_float(features_dict.get("inst_rate_mean_30d"), inst_hist_rate)
    inst_rate_std_90d = _coerce_float(features_dict.get("inst_rate_std_90d"), DEFAULT_INST_RATE_STD)
    # 데이터셋은 기초금액을 base_amount 로 내보냅니다. 별칭을 받지 않으면
    # base_price 가 항상 price 로 폴백해 price_ratio 가 상수 1.0 이 됩니다.
    base_price = _coerce_float(
        features_dict.get("base_price", features_dict.get("base_amount")), price
    )
    price_ratio = (base_price / price) if price > 0 else 1.0

    # 제도 특징입니다. 낙찰하한율은 낙찰률과 Spearman 0.71 로 가장 강한 신호지만
    # 학습 표본의 33%, 추론 시점의 63% 가 결측이라 결측 지시자를 반드시 함께 냅니다.
    # 결측을 0 으로 채우면 "하한율이 0" 과 구분되지 않아 모델이 잘못 학습합니다.
    raw_lwlt = features_dict.get("lwlt_rate")
    lwlt_missing = _is_missing(raw_lwlt) or _coerce_float(raw_lwlt, 0.0) <= 0.0
    lwlt_rate = 0.0 if lwlt_missing else _coerce_float(raw_lwlt, 0.0)

    notice_amount = _notice_amount_for(reference_ts)
    notice_ts = _coerce_timestamp(features_dict.get("bid_ntce_dt")) or reference_ts

    feature_map: dict[str, Any] = {
        "lwlt_rate": lwlt_rate,
        "lwlt_rate_missing": 1.0 if lwlt_missing else 0.0,
        "is_post_regime_shift": 1.0 if notice_ts >= REGIME_SHIFT_DATE else 0.0,
        "notice_amt_ratio": (price / notice_amount) if notice_amount > 0 else 0.0,
        "is_over_notice_amt": 1.0 if price >= notice_amount else 0.0,
        # 협상에 의한 계약의 배점 구성. 기술 비중이 높을수록 낙찰률이 가격에
        # 고정되지 않아 산포가 커집니다 (90:10 구간 표준편차 11.9).
        "tech_ablt_evl_rt": _coerce_float(features_dict.get("tech_ablt_evl_rt"), 0.0),
        "bid_prce_evl_rt": _coerce_float(features_dict.get("bid_prce_evl_rt"), 0.0),
        "tot_prdprc_num": _coerce_float(features_dict.get("tot_prdprc_num"), 0.0),
        "drwt_prdprc_num": _coerce_float(features_dict.get("drwt_prdprc_num"), 0.0),
        "srvce_div_nm": _coerce_category(features_dict.get("srvce_div_nm")),
        "lrg_clsfc_nm": _coerce_category(features_dict.get("lrg_clsfc_nm")),
        "cntrct_mthd_nm": _coerce_category(features_dict.get("cntrct_mthd_nm")),
        "prearng_mthd": _coerce_category(features_dict.get("prearng_mthd")),
        "sucsfbid_mthd_nm": _coerce_category(features_dict.get("sucsfbid_mthd_nm")),
        # 대분류 11종으로는 용역 종류별 하한율 별표를 담지 못합니다. 중분류 40종,
        # 소분류 200종이 그 차이를 대리합니다 (제도 분석서 5.4 절).
        "mid_clsfc_nm": _coerce_category(features_dict.get("mid_clsfc_nm")),
        "clsfc_nm": _coerce_category(features_dict.get("clsfc_nm")),
        "ntce_kind_nm": _coerce_category(features_dict.get("ntce_kind_nm")),
        "bid_methd_nm": _coerce_category(features_dict.get("bid_methd_nm")),
        "intrbid_yn": _coerce_category(features_dict.get("intrbid_yn")),
        "ppsw_gnrl_srvce_yn": _coerce_category(features_dict.get("ppsw_gnrl_srvce_yn")),
        # 재발주 이력. 용역은 같은 기관이 1~2년 주기로 같은 사업을 다시 냅니다
        # (재발주 주기 중앙값 358일, 직전 낙찰률과의 절대차 중앙값 0.252%p).
        **repeat,
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
