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
import time

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
from src.ml.dataset import announcement_feature_payload
from src.ml.features import build_feature_dict
from src.ml.model_registry import (
    ModelRegistry,
    PriceDecisionMethod,
    classify_price_decision_method,
    predict_interval,
    predict_optimal_price_with_provenance,
)
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
    t_start = time.perf_counter()
    c_start = time.process_time()

    user_price = "".join(
        char for char in str(payload.user_price or "0") if char.isdigit() or char == "."
    )

    bid = db.get(BidAnnouncement, payload.bid_id)
    if bid is None:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")

    selected_model = payload.selected_model or _default_model_for_bid(bid)
    reference_amount = float(bid.prediction_reference_amount or 0)

    # 원본은 금액이 없어도 예측을 진행해 추천 투찰가 0 원을 돌려줍니다.
    # 0 원은 답이 아니라 오답이므로 여기서 끊습니다. 기초금액과 예정가격이
    # 모두 없는 공고가 10만 건 이상이며 외자는 절반 가까이가 이 상태입니다.
    if reference_amount <= 0:
        raise HTTPException(
            status_code=422,
            detail="기초금액과 예정가격이 모두 공개되지 않은 공고라 투찰가를 산출할 수 없습니다.",
        )

    # 비예가 판정: model_registry.classify_price_decision_method 단일 함수 사용.
    # 명시적 Servc 비예가만 차단하고 missing/unknown/non-Servc는 pass-through 한다.
    # 근거: docs/design/servc_nonprearng_population_cause_20260812.md
    raw = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    method_class = classify_price_decision_method(raw)
    if method_class == PriceDecisionMethod.NON_PREARNG and bid.category == "Servc":
        raise HTTPException(
            status_code=422,
            detail="비예가 공고는 예정가격을 작성하지 않는 제도라 "
                   "낙찰률 기반 투찰가를 산출할 수 없습니다.",
        )

    # 제도 특징은 raw_data JSON 안에 있어 공고 컬럼만으로는 못 채웁니다.
    # 이 병합을 빼면 학습이 쓰는 34개 중 30개가 기본값으로 떨어집니다.
    features = {
        **announcement_feature_payload(bid),
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

    # 기관 이력과 재발주 이력은 DB 조회가 필요합니다. session 을 넘기지 않으면
    # 상수로 떨어져 학습과 다른 값을 보게 됩니다.
    # 원본 키 위에 덮어씁니다. 통째로 갈아끼우면 규칙 기반 구 모델이 쓰는
    # title / agency_name / scenario_mode 가 사라집니다.
    features = {**features, **build_feature_dict(features, db)}

    # 후보 순회는 함수 안에서 끝납니다. 여기서 다시 fallback 을 시도하면 같은
    # 후보 목록을 두 번 돌 뿐이라 대체 사실이 그대로 은폐됩니다. 어느 모델이
    # 답했는지는 outcome.actual_model 하나만 봅니다.
    try:
        t_model_start = time.perf_counter()
        c_model_start = time.process_time()
        outcome = predict_optimal_price_with_provenance(selected_model, features)
        t_model = time.perf_counter() - t_model_start
        c_model = time.process_time() - c_model_start
    except Exception as exc:
        logger.error("모델 후보 전량 실패 (요청 모델 %s): %s", selected_model, exc)
        raise HTTPException(
            status_code=503,
            detail="예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다.",
        ) from exc

    predicted_rate = outcome.predicted_rate
    actual_model = outcome.actual_model
    wrapper = ModelRegistry.get_model(actual_model)
    base_name = wrapper.get_display_name() if wrapper else actual_model
    model_name = f"{base_name} (Fallback)" if outcome.fallback_used else base_name

    estimated_price = reference_amount
    if predicted_rate < 2.0:
        optimal_price = int(estimated_price * predicted_rate)
        prediction_rate_percent = round(predicted_rate * 100, 4)
    else:
        optimal_price = int(predicted_rate)
        prediction_rate_percent = round(predicted_rate, 4)

    # 입력 투찰가가 추천가에 얼마나 가까운지입니다. 모델 불확실성과는 무관하며
    # 종전 이름(confidence)은 사용자가 이를 신뢰도로 읽게 만들었습니다. 모델
    # 불확실성은 아래 예측 구간으로 전달합니다.
    # 값이 낮을 때 난수로 채우던 종전 동작은 제거했습니다. 같은 입력은 항상
    # 같은 응답을 내야 합니다.
    user_bid_similarity = None
    try:
        user_price_value = float(user_price) if user_price else 0.0
    except ValueError:
        user_price_value = 0.0
    if user_price_value > 0 and estimated_price > 0:
        diff_ratio = abs(user_price_value - optimal_price) / estimated_price
        user_bid_similarity = max(0, min(100, int(100 - (diff_ratio * 400))))

    # 예측 구간. 큰 건일수록 산포가 커지므로 단일 숫자만 주면 사용자가 그 값을
    # 그대로 신뢰합니다. 구 모델은 분위 아티팩트가 없어 None 이 나옵니다.
    # 점 추정을 낸 모델과 같은 모델에서 뽑아야 합니다.
    rate_low = rate_high = price_low = price_high = coverage = None
    bounds = predict_interval(actual_model, features)
    if bounds is not None:
        low, high, coverage = bounds
        rate_low, rate_high = round(low, 4), round(high, 4)
        price_low = int(estimated_price * low / 100)
        price_high = int(estimated_price * high / 100)

    message = (
        f"{model_name} 분석이 완료되었습니다. 예상 낙찰률은 {prediction_rate_percent}% 입니다."
    )
    if outcome.fallback_used:
        message = (
            f"요청하신 모델({outcome.requested_model})을 쓸 수 없어 "
            f"{base_name} 으로 예측했습니다. "
            f"예상 낙찰률은 {prediction_rate_percent}% 입니다."
        )

    t_total = time.perf_counter() - t_start
    c_total = time.process_time() - c_start
    logger.info(
        "predict_price_api | Wall: %.2fms (CPU: %.2fms) | Model Wall: %.2fms (CPU: %.2fms)",
        t_total * 1000.0,
        c_total * 1000.0,
        t_model * 1000.0,
        c_model * 1000.0,
    )

    return PredictPriceResponse(
        status="success",
        optimal_price=optimal_price,
        prediction_rate=prediction_rate_percent,
        user_bid_similarity=user_bid_similarity,
        model_name=model_name,
        model_id=actual_model,
        requested_model=outcome.requested_model,
        fallback_used=outcome.fallback_used,
        fallback_reason=outcome.fallback_reason,
        rate_low=rate_low,
        rate_high=rate_high,
        price_low=price_low,
        price_high=price_high,
        interval_coverage=coverage,
        message=message,
    )


@router.post("/predict", response_model=PredictionResponse, summary="특징 직접 입력 예측")
def predict_winning_price(payload: PredictionRequest, db: Session = Depends(get_db)):
    """공고 레코드 없이 특징을 직접 넣어 예측합니다 (리팩토링 신규 계약).

    db 는 inst_hist_rate 를 실제 기관 이력으로 채우기 위해 필요합니다.
    빼면 상수로 떨어져 학습과 정의가 갈립니다.
    """
    t_start = time.perf_counter()
    c_start = time.process_time()
    dumped_payload = payload.model_dump()

    t_model_start = time.perf_counter()
    c_model_start = time.process_time()
    result = predictor.predict(dumped_payload, session=db)
    t_model = time.perf_counter() - t_model_start
    c_model = time.process_time() - c_model_start

    t_total = time.perf_counter() - t_start
    c_total = time.process_time() - c_start
    logger.info(
        "predict_winning_price | Wall: %.2fms (CPU: %.2fms) | Model Wall: %.2fms (CPU: %.2fms)",
        t_total * 1000.0,
        c_total * 1000.0,
        t_model * 1000.0,
        c_model * 1000.0,
    )

    return PredictionResponse(
        bid_notice_no=payload.bid_notice_no,
        predicted_price=result["predicted_price"],
        predicted_rate=result["predicted_rate"],
        model_version=result["model_version"],
        features_used=result["features_used"],
    )
