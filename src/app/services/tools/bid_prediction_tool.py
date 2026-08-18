"""
src/app/services/tools/bid_prediction_tool.py

공고 투찰가 예측 도구 (원본 apps/chatbot/tools/bid_prediction_tool.py 1:1 이식).

A4 교정:
- 비예가 판정을 model_registry.classify_price_decision_method 단일 함수로 통합.
- 도달 불가 재시도 패턴을 제거하고 predict_optimal_price_with_provenance 사용.
- actual_model, fallback_used, fallback_reason 이 실제 예측 모델을 가리키게 한다.
"""

from __future__ import annotations

import re
from typing import Any

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement
from src.ml.model_registry import (
    CATEGORY_DEFAULT_MODELS,
    ModelRegistry,
    PriceDecisionMethod,
    classify_price_decision_method,
    predict_optimal_price_with_provenance,
)

# 정본은 model_registry 입니다.
DEFAULT_MODEL_BY_CATEGORY = CATEGORY_DEFAULT_MODELS

MODEL_ALIASES = {
    "quantum_leap_v25_pro": "quantum_leap_v25_pro",
    "ssh_hist_premium": "ssh_hist_premium",
    "ssh": "ssh_hist_premium",
    "servc_institution_v1": "servc_institution_v1",
    "servc": "servc_institution_v1",
    "v13_hybrid": "v13_hybrid",
    "v13": "v13_hybrid",
    "v25": "v25",
}
KOREAN_LIMIT_WORDS = {
    "한": 1,
    "하나": 1,
    "두": 2,
    "둘": 2,
    "세": 3,
    "셋": 3,
    "네": 4,
    "넷": 4,
    "다섯": 5,
    "여섯": 6,
    "일곱": 7,
    "여덟": 8,
    "아홉": 9,
    "열": 10,
}
MAX_PREDICTION_LIMIT = 10

# raw_data 예산이 "0" 인 건이 섞여 있어 SQL 필터만으로는 요청 건수를 못 채웁니다.
# 여유분을 더 읽고 파이썬에서 최종 판정한 뒤 자릅니다.
CANDIDATE_OVERSAMPLE = 3


def _default_model_for_bid(bid: BidAnnouncement) -> str:
    return DEFAULT_MODEL_BY_CATEGORY.get(bid.category, "v25")


def _resolve_model_id(query: str, model_id: str = "") -> str:
    normalized = f"{model_id} {query}".strip().lower()
    for alias, resolved in MODEL_ALIASES.items():
        if alias in normalized:
            return resolved
    return ""


def coerce_limit(value: Any, query: str = "") -> int:
    try:
        limit = int(value)
    except (TypeError, ValueError):
        limit = 0
    if limit <= 0:
        match = re.search(r"(?<![a-zA-Z])(\d{1,2})\s*(?:개|건)\s*(?:만)?", query)
        if match:
            limit = int(match.group(1))
    if limit <= 0:
        normalized = query.replace(" ", "")
        for word, number in KOREAN_LIMIT_WORDS.items():
            if f"{word}개" in normalized or f"{word}건" in normalized:
                limit = number
                break
    if limit <= 0:
        limit = 1
    return max(1, min(limit, MAX_PREDICTION_LIMIT))


def _build_prediction_features(bid: BidAnnouncement) -> dict[str, Any]:
    reference_amount = float(bid.prediction_reference_amount or 0)
    return {
        "title": bid.bid_ntce_nm or "",
        "agency_name": bid.dminstt_nm or bid.ntce_instt_nm or "",
        "scenario_mode": "2",
        "presmpt_prce": reference_amount,
        "presmptPrce": reference_amount,
        "real_budget": reference_amount,
        "bid_ntce_nm": bid.bid_ntce_nm or "",
        "ntce_instt_nm": bid.ntce_instt_nm or "",
        "ntceInsttNm": bid.ntce_instt_nm or "",
        "dminstt_nm": bid.dminstt_nm or "",
        "bidMethdNm": bid.bid_methd_nm or "",
        "cntrctCnclsMthdNm": bid.cntrct_mthd_nm or "",
        "category": bid.category or "",
        "bid_ntce_dt": bid.bid_ntce_dt,
        "bid_clse_dt": bid.bid_clse_dt,
        "openg_dt": bid.openg_dt,
    }


def _latest_predictable_bids(db: Session, category: str = "", limit: int = 1):
    # NULL 만 거르면 presmpt_prce = 0 인 공고가 통과합니다. 금액이 0 이면
    # 추천 투찰가가 0 원으로 나와 답변 전체가 무의미해집니다. 외자(Frgcpt)는
    # 절반 가까이가 이 상태라 필터를 0 초과로 둡니다.
    stmt = select(BidAnnouncement).where(
        or_(BidAnnouncement.base_amount > 0, BidAnnouncement.presmpt_prce > 0)
    )
    if category:
        stmt = stmt.where(BidAnnouncement.category == category)
    stmt = stmt.order_by(
        BidAnnouncement.collected_at.desc(),
        BidAnnouncement.bid_ntce_dt.desc(),
        BidAnnouncement.id.desc(),
    ).limit(limit * CANDIDATE_OVERSAMPLE)

    # 최종 판정은 prediction_reference_amount 로 합니다. raw_data 의 예산 필드가
    # "0" 이면 SQL 필터를 통과하고도 기준 금액이 0 이 됩니다.
    rows = [
        row
        for row in db.execute(stmt).scalars().all()
        if float(row.prediction_reference_amount or 0) > 0
    ]
    return rows[:limit]


def _model_display_name(model_id: str) -> str:
    wrapper = ModelRegistry.get_model(model_id)
    return wrapper.get_display_name() if wrapper else model_id


def _predict_bid(bid: BidAnnouncement, requested_model: str) -> dict[str, Any]:
    """공고 한 건에 대해 투찰가를 예측한다.

    비예가 공고는 낙찰률 모델로 보내지 않고 사유를 반환한다.
    모델 출처는 predict_optimal_price_with_provenance 가 추적하므로
    이 함수에서 별도 재시도를 하지 않는다.
    """
    features = _build_prediction_features(bid)

    # 비예가 판정: model_registry.classify_price_decision_method 단일 함수 사용.
    # 명시적 Servc 비예가만 차단하고 missing/unknown/non-Servc는 pass-through 한다.
    raw = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    method_class = classify_price_decision_method(raw)
    if method_class == PriceDecisionMethod.NON_PREARNG and bid.category == "Servc":
        reference_amount = float(bid.prediction_reference_amount or 0)
        return {
            "bid": {
                "id": bid.id,
                "bid_ntce_no": bid.bid_ntce_no,
                "bid_ntce_ord": bid.bid_ntce_ord,
                "bid_ntce_nm": bid.bid_ntce_nm or "",
                "dminstt_nm": bid.dminstt_nm or "",
                "ntce_instt_nm": bid.ntce_instt_nm or "",
                "category": bid.category,
                "category_label": bid.category_label,
                "bid_ntce_dt": (bid.bid_ntce_dt.isoformat() if bid.bid_ntce_dt else ""),
                "collected_at": (bid.collected_at.isoformat() if bid.collected_at else ""),
            },
            "model_id": "",
            "model_name": "",
            "requested_model": requested_model,
            "fallback_used": False,
            "fallback_reason": "",
            "reference_amount": int(reference_amount),
            "optimal_price": 0,
            "prediction_rate": 0,
            "skipped": True,
            "skip_reason": (
                "비예가 공고는 예정가격을 작성하지 않는 제도라 "
                "낙찰률 기반 투찰가를 산출할 수 없습니다."
            ),
        }

    # predict_optimal_price_with_provenance 를 사용하여 actual_model,
    # fallback_used, fallback_reason 이 실제 예측 모델을 가리키게 한다.
    # 종전의 도달 불가 재시도 패턴(요청 모델 실패 -> 카테고리 기본 모델 재시도)은
    # provenance 함수 내부의 후보 순회와 중복이므로 제거한다.
    try:
        outcome = predict_optimal_price_with_provenance(requested_model, features)
    except Exception:
        # 후보 전량 실패 시 챗봇은 오류 대신 사유를 반환한다.
        reference_amount = float(bid.prediction_reference_amount or 0)
        return {
            "bid": {
                "id": bid.id,
                "bid_ntce_no": bid.bid_ntce_no,
                "bid_ntce_ord": bid.bid_ntce_ord,
                "bid_ntce_nm": bid.bid_ntce_nm or "",
                "dminstt_nm": bid.dminstt_nm or "",
                "ntce_instt_nm": bid.ntce_instt_nm or "",
                "category": bid.category,
                "category_label": bid.category_label,
                "bid_ntce_dt": (bid.bid_ntce_dt.isoformat() if bid.bid_ntce_dt else ""),
                "collected_at": (bid.collected_at.isoformat() if bid.collected_at else ""),
            },
            "model_id": "",
            "model_name": "",
            "requested_model": requested_model,
            "fallback_used": True,
            "fallback_reason": "모델 후보 전량 실패",
            "reference_amount": int(reference_amount),
            "optimal_price": 0,
            "prediction_rate": 0,
            "skipped": True,
            "skip_reason": "예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다.",
        }

    predicted_rate = outcome.predicted_rate
    actual_model = outcome.actual_model
    model_name = _model_display_name(actual_model)
    if outcome.fallback_used:
        model_name = f"{model_name} (Fallback)"

    reference_amount = float(bid.prediction_reference_amount or 0)
    if predicted_rate < 2.0:
        optimal_price = int(reference_amount * predicted_rate)
        prediction_rate_percent = round(predicted_rate * 100, 4)
    else:
        optimal_price = int(predicted_rate)
        prediction_rate_percent = round(predicted_rate, 4)

    return {
        "bid": {
            "id": bid.id,
            "bid_ntce_no": bid.bid_ntce_no,
            "bid_ntce_ord": bid.bid_ntce_ord,
            "bid_ntce_nm": bid.bid_ntce_nm or "",
            "dminstt_nm": bid.dminstt_nm or "",
            "ntce_instt_nm": bid.ntce_instt_nm or "",
            "category": bid.category,
            "category_label": bid.category_label,
            "bid_ntce_dt": bid.bid_ntce_dt.isoformat() if bid.bid_ntce_dt else "",
            "collected_at": bid.collected_at.isoformat() if bid.collected_at else "",
        },
        "model_id": actual_model,
        "model_name": model_name,
        "requested_model": outcome.requested_model,
        "fallback_used": outcome.fallback_used,
        "fallback_reason": outcome.fallback_reason or "",
        "reference_amount": int(reference_amount),
        "optimal_price": optimal_price,
        "prediction_rate": prediction_rate_percent,
    }


def execute(
    *,
    db: Session,
    query: str = "",
    category: str = "",
    model_id: str = "",
    limit: int = 1,
    **_ignored: Any,
) -> dict[str, Any]:
    resolved_limit = coerce_limit(limit, query)
    bids = _latest_predictable_bids(db, category, resolved_limit)
    if not bids:
        return {
            "status": "error",
            "message": "예측 가능한 최근 공고를 찾지 못했습니다.",
            "query": query,
            "category": category,
            "requested_count": resolved_limit,
            "result_count": 0,
        }

    first_model = _resolve_model_id(query, model_id) or _default_model_for_bid(bids[0])
    predictions = [_predict_bid(bid, first_model) for bid in bids]
    first_prediction = predictions[0]

    return {
        "status": "success",
        "query": query,
        "requested_count": resolved_limit,
        "result_count": len(predictions),
        "predictions": predictions,
        **first_prediction,
    }
