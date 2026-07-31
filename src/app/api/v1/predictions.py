from fastapi import APIRouter

from src.app.schemas.predictions import PredictionRequest, PredictionResponse
from src.ml.predictor import predictor

router = APIRouter(prefix="/predictions", tags=["Predictions"])


@router.post("/predict", response_model=PredictionResponse)
def predict_winning_price(payload: PredictionRequest):
    result = predictor.predict(payload.model_dump())
    return PredictionResponse(
        bid_notice_no=payload.bid_notice_no,
        predicted_price=result["predicted_price"],
        predicted_rate=result["predicted_rate"],
        model_version=result["model_version"],
        features_used=result["features_used"],
    )
