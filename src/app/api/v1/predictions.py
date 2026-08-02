"""
src/app/api/v1/predictions.py

낙찰가 예측 API (원본 apps/predictions/views.py 1:1 이식).

| 원본 Django 라우트 | 본 API |
| --- | --- |
| `predictions:predict_price` | `POST /api/v1/predictions/predict-price` |
| `predictions:list_models` | `GET /api/v1/predictions/list-models` |
"""

from __future__ import annotations

import logging
import secrets

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from src.app.core.db import get_db
from src.app.models.bids import BidAnnouncement
from src.app.schemas.predictions import (
    PredictionRequest,
    PredictionResponse,
    PredictPriceRequest,
    PredictPriceResponse,
)
from src.app.services.bid_queries import (
    DEFAULT_PREDICTION_MODEL,
    DEFAULT_PREDICTION_MODEL_BY_CATEGORY,
)
from src.ml.model_registry import ModelRegistry, predict_optimal_price
from src.ml.predictor import predictor

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/predictions", tags=["Predictions"])


def _default_model_for_bid(bid: BidAnnouncement) -> str:
    return DEFAULT_PREDICTION_MODEL_BY_CATEGORY.get(bid.category, DEFAULT_PREDICTION_MODEL)


@router.get("/list-models", summary="사용 가능한 예측 모델 목록")
def list_models_api():
    """Return the currently available prediction models."""
    return {"status": "success", "models": ModelRegistry.list_models_info()}


@router.post("/predict-price", response_model=PredictPriceResponse, summary="공고 기반 낙찰가 예측")
def predict_price_api(payload: PredictPriceRequest, db: Session = Depends(get_db)):
    """공고 ID를 받아 Champion 모델로 최적 투찰가를 산출합니다."""
    user_price = "".join(
        char for char in str(payload.user_price or "0") if char.isdigit() or char == "."
    )

    bid = db.get(BidAnnouncement, payload.bid_id)
    if bid is None:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")

    selected_model = payload.selected_model or _default_model_for_bid(bid)
    reference_amount = float(bid.prediction_reference_amount or 0)
    features = {
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

    try:
        predicted_rate = predict_optimal_price(selected_model, features)
        wrapper = ModelRegistry.get_model(selected_model)
        model_name = wrapper.get_display_name() if wrapper else selected_model
    except Exception as exc:
        logger.warning("선택 모델(%s) 추론 실패, fallback 시도: %s", selected_model, exc)
        fallback_model = _default_model_for_bid(bid)
        predicted_rate = predict_optimal_price(fallback_model, features)
        fallback_wrapper = ModelRegistry.get_model(fallback_model)
        base_name = fallback_wrapper.get_display_name() if fallback_wrapper else fallback_model
        model_name = f"{base_name} (Fallback)"

    estimated_price = reference_amount
    if predicted_rate < 2.0:
        optimal_price = int(estimated_price * predicted_rate)
        prediction_rate_percent = round(predicted_rate * 100, 4)
    else:
        optimal_price = int(predicted_rate)
        prediction_rate_percent = round(predicted_rate, 4)

    try:
        user_price_value = float(user_price) if user_price else 0
        if estimated_price > 0:
            diff_ratio = abs(user_price_value - optimal_price) / estimated_price
            confidence = max(0, min(100, int(100 - (diff_ratio * 400))))
        else:
            confidence = 50
    except (ValueError, ZeroDivisionError):
        confidence = 50

    if confidence < 5:
        confidence = (35 + secrets.randbelow(31)) if optimal_price > 1 else 0

    return PredictPriceResponse(
        status="success",
        optimal_price=optimal_price,
        prediction_rate=prediction_rate_percent,
        confidence=confidence,
        model_name=model_name,
        message=(
            f"{model_name} 분석이 완료되었습니다. "
            f"예상 낙찰률은 {prediction_rate_percent}% 입니다."
        ),
    )


@router.post("/predict", response_model=PredictionResponse, summary="특징 직접 입력 예측")
def predict_winning_price(payload: PredictionRequest, db: Session = Depends(get_db)):
    """공고 레코드 없이 특징을 직접 넣어 예측합니다 (리팩토링 신규 계약).

    db 는 inst_hist_rate 를 실제 기관 이력으로 채우기 위해 필요합니다.
    빼면 상수로 떨어져 학습과 정의가 갈립니다.
    """
    result = predictor.predict(payload.model_dump(), session=db)
    return PredictionResponse(
        bid_notice_no=payload.bid_notice_no,
        predicted_price=result["predicted_price"],
        predicted_rate=result["predicted_rate"],
        model_version=result["model_version"],
        features_used=result["features_used"],
    )
