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
