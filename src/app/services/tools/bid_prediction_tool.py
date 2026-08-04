"""
src/app/services/tools/bid_prediction_tool.py

공고 투찰가 예측 도구 (원본 apps/chatbot/tools/bid_prediction_tool.py 1:1 이식).
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
    predict_optimal_price,
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
    features = _build_prediction_features(bid)
    fallback_used = False

    try:
        predicted_rate = predict_optimal_price(requested_model, features)
        resolved_model = requested_model
        model_name = _model_display_name(resolved_model)
    except Exception as exc:
        fallback_model = _default_model_for_bid(bid)
        predicted_rate = predict_optimal_price(fallback_model, features)
        resolved_model = fallback_model
        model_name = f"{_model_display_name(fallback_model)} (Fallback)"
        fallback_used = True
        fallback_reason = str(exc)
    else:
        fallback_reason = ""

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
        "model_id": resolved_model,
        "model_name": model_name,
        "requested_model": requested_model,
        "fallback_used": fallback_used,
        "fallback_reason": fallback_reason,
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
