from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.app.core.timeutil import utcnow


class PredictionRequest(BaseModel):
    bid_notice_no: str | None = Field(None, description="공고번호 (선택)")
    presumed_price: float = Field(..., gt=0, description="추정가격")
    base_price: float = Field(..., gt=0, description="기초금액")
    category_code: str = Field("Thng", description="카테고리 코드")
    order_institution: str | None = Field(None, description="발주기관")
    inst_hist_rate: float | None = Field(None, description="기관 과거 평균 낙찰률 (미입력 시 DB/Redis 조회)")


class PredictionResponse(BaseModel):
    bid_notice_no: str | None = None
    predicted_price: float = Field(..., description="예측 사투가")
    predicted_rate: float = Field(..., description="예측 투찰률 (%)")
    model_version: str = Field(..., description="사용한 ML Champion 모델 버전")
    features_used: dict[str, Any] = Field(..., description="추론에 사용된 단일 특징 레코드")
    created_at: datetime = Field(default_factory=utcnow)


class PredictPriceRequest(BaseModel):
    """원본 predict_price_api 폼 파라미터 대응."""

    bid_id: int = Field(..., description="입찰공고 ID")
    user_price: str | None = Field("0", description="사용자 투찰 금액 (문자열 허용)")
    selected_model: str | None = Field(None, description="선택 모델 ID (미지정 시 카테고리 기본값)")


class PredictPriceResponse(BaseModel):
    """원본 predict_price_api JsonResponse 계약과 동일."""

    status: str = "success"
    optimal_price: int = Field(..., description="최적 투찰 추천가")
    prediction_rate: float = Field(..., description="예상 낙찰률 (%)")
    confidence: int = Field(..., description="신뢰도 점수 (0~100)")
    model_name: str = Field(..., description="사용한 모델 표시명")
    message: str = Field(..., description="사용자 안내 메시지")
    # 구간은 분위 모델을 가진 모델에서만 나옵니다. 구 모델은 None 이라
    # 원본 JsonResponse 계약을 깨지 않습니다.
    rate_low: float | None = Field(None, description="예상 낙찰률 하단 (%)")
    rate_high: float | None = Field(None, description="예상 낙찰률 상단 (%)")
    price_low: int | None = Field(None, description="예상 낙찰가 하단")
    price_high: int | None = Field(None, description="예상 낙찰가 상단")
    interval_coverage: float | None = Field(None, description="구간 명목 피복률")
