from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class PredictionRequest(BaseModel):
    bid_notice_no: Optional[str] = Field(None, description="공고번호 (선택)")
    presumed_price: float = Field(..., gt=0, description="추정가격")
    base_price: float = Field(..., gt=0, description="기초금액")
    category_code: str = Field("Thng", description="카테고리 코드")
    order_institution: Optional[str] = Field(None, description="발주기관")
    inst_hist_rate: Optional[float] = Field(None, description="기관 과거 평균 낙찰률 (미입력 시 DB/Redis 조회)")


class PredictionResponse(BaseModel):
    bid_notice_no: Optional[str] = None
    predicted_price: float = Field(..., description="예측 사투가")
    predicted_rate: float = Field(..., description="예측 투찰률 (%)")
    model_version: str = Field(..., description="사용한 ML Champion 모델 버전")
    features_used: dict[str, Any] = Field(..., description="추론에 사용된 단일 특징 레코드")
    created_at: datetime = Field(default_factory=datetime.utcnow)


class PredictPriceRequest(BaseModel):
    """원본 predict_price_api 폼 파라미터 대응."""

    bid_id: int = Field(..., description="입찰공고 ID")
    user_price: Optional[str] = Field("0", description="사용자 투찰 금액 (문자열 허용)")
    selected_model: Optional[str] = Field(None, description="선택 모델 ID (미지정 시 카테고리 기본값)")


class PredictPriceResponse(BaseModel):
    """원본 predict_price_api JsonResponse 계약과 동일."""

    status: str = "success"
    optimal_price: int = Field(..., description="최적 투찰 추천가")
    prediction_rate: float = Field(..., description="예상 낙찰률 (%)")
    confidence: int = Field(..., description="신뢰도 점수 (0~100)")
    model_name: str = Field(..., description="사용한 모델 표시명")
    message: str = Field(..., description="사용자 안내 메시지")
