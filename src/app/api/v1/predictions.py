from fastapi import APIRouter
from src.app.schemas.predictions import PredictionRequest, PredictionResponse
from src.ml.features import build_feature_dict

router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.post("/predict", response_model=PredictionResponse)
def predict_winning_price(payload: PredictionRequest):
    # 단일 특징 공급원(features.py)을 이용하여 요청 데이터로부터 동일 특징 dict 생성
    feature_dict = build_feature_dict(payload.model_dump())

    # 추론 예시 (Champion 모델 가중치 상주 연동)
    presumed = feature_dict["presumed_price"]
    rate = feature_dict.get("inst_hist_rate", 0.925) * 100.0
    predicted_price = presumed * (rate / 100.0)

    return PredictionResponse(
        bid_notice_no=payload.bid_notice_no,
        predicted_price=predicted_price,
        predicted_rate=rate,
        model_version="quantum_leap_v25_pro",
        features_used=feature_dict,
    )
