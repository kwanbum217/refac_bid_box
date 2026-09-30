from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from src.app.core.timeutil import utcnow


class PredictionRequest(BaseModel):
    bid_notice_no: str | None = Field(None, description="공고번호 (선택)")
    presumed_price: float = Field(..., gt=0, description="추정가격")
    base_price: float = Field(..., gt=0, description="기초금액")
    category_code: str = Field("Thng", description="카테고리 코드")
    order_institution: str | None = Field(None, description="발주기관")
    inst_hist_rate: float | None = Field(
        None, description="기관 과거 평균 낙찰률 (미입력 시 DB/Redis 조회)"
    )


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
    # 적격심사 배점표 값은 공고 데이터에 없어 사용자가 공고문을 보고 입력합니다.
    # 전부 선택이며, 하나라도 없으면 추측값을 넣지 않고 점수 판정만 하지 않습니다.
    max_price_score: float | None = Field(
        None, gt=0.0, description="가격 배점한도 B. 공고문 적격심사 배점표에서 입력 (선택)"
    )
    multiplier: float | None = Field(
        None, gt=0.0, description="가격평점 계수 k. 공고문 적격심사 배점표에서 입력 (선택)"
    )
    pass_threshold: float | None = Field(
        None, gt=0.0, description="적격 통과점수 T. 공고문 적격심사 배점표에서 입력 (선택)"
    )
    non_price_score: float | None = Field(
        None, gt=0.0, description="비가격 정량점수 합계 Q. 미입력 시 0 으로 가정 (선택)"
    )


class PredictPriceScoreVerdict(BaseModel):
    """추천가와 예측 구간의 정량평가 점수 통과 판정.

    점수 산식은 price_score_verification 정본 함수만 호출해 계산하며, B·k·T 가
    없거나 규칙을 판별하지 못하면 점수를 만들지 않고 사유를 담습니다.
    """

    verifiable: bool = Field(
        False, description="점수 판정 가능 여부. 적격심사 규칙과 배점표(B·k·T)가 모두 있어야 True"
    )
    unavailable_reasons: list[str] = Field(
        default_factory=list, description="판정 불가 사유 (규칙 미판별, 배점표 결측 등)"
    )
    base_rate: str | None = Field(None, description="가격점수 기준비율 (%)")
    max_price_score: str | None = Field(None, description="가격 배점한도 B")
    multiplier: str | None = Field(None, description="평점 계수 k")
    pass_threshold: str | None = Field(None, description="적격 통과점수 T")
    non_price_score: str | None = Field(None, description="비가격 정량점수 합계 Q")
    non_price_score_assumed_zero: bool = Field(
        False, description="Q 미입력으로 0 을 가정했는지 여부"
    )
    optimal_price_score: str | None = Field(None, description="추천가 optimal_price 의 가격평점 P")
    price_low_score: str | None = Field(None, description="예측 구간 하단 price_low 의 가격평점 P")
    price_high_score: str | None = Field(
        None, description="예측 구간 상단 price_high 의 가격평점 P"
    )
    optimal_price_passes: bool | None = Field(
        None, description="추천가가 통과 조건(가격평점 P >= T - Q)을 만족하는지"
    )
    pass_range_status: Literal["feasible", "impossible", "unverifiable"] | None = Field(
        None, description="통과 가능 낙찰가 구간 역산 상태"
    )
    pass_ratio_low: str | None = Field(None, description="통과 가능 낙찰가 비율 하한")
    pass_ratio_high: str | None = Field(None, description="통과 가능 낙찰가 비율 상한")
    pass_amount_low: int | None = Field(None, description="통과 가능 낙찰가 금액 하한 (원)")
    pass_amount_high: int | None = Field(None, description="통과 가능 낙찰가 금액 상한 (원)")
    effective_ratio_low: str | None = Field(None, description="낙찰하한율 반영 유효 통과 비율 하한")
    effective_ratio_high: str | None = Field(
        None, description="낙찰하한율 반영 유효 통과 비율 상한"
    )
    effective_amount_low: int | None = Field(
        None, description="낙찰하한율 반영 유효 통과 금액 하한 (원)"
    )
    effective_amount_high: int | None = Field(
        None, description="낙찰하한율 반영 유효 통과 금액 상한 (원)"
    )
    predicted_interval_overlap_ratio: str | None = Field(
        None, description="예측 구간이 유효 통과 구간과 겹치는 비율 (교집합 금액 / 예측 구간 폭)"
    )
    pass_range_reasons: list[str] = Field(
        default_factory=list, description="통과 가능 구간을 확정하지 못한 사유"
    )
    uncertainty_note: str | None = Field(
        None, description="Q=0 가정 등 판정 가정과 그 영향에 대한 경고"
    )


class PredictPriceResponse(BaseModel):
    """원본 predict_price_api JsonResponse 계약과 동일."""

    status: str = "success"
    optimal_price: int = Field(..., description="최적 투찰 추천가")
    prediction_rate: float = Field(..., description="예상 낙찰률 (%)")
    # 종전 confidence 를 대체합니다. 입력 투찰가와 추천가의 근접도이며 모델
    # 신뢰도가 아닙니다. 투찰가를 넣지 않으면 계산할 값이 없어 None 입니다.
    # 모델 불확실성은 아래 rate_low / rate_high 구간으로 표현합니다.
    user_bid_similarity: int | None = Field(
        None, description="입력 투찰가와 추천가의 근접도 (0~100). 모델 신뢰도가 아님"
    )
    model_name: str = Field(..., description="실제로 예측한 모델의 표시명")
    # 출처. 후보 순회로 다른 모델이 답할 수 있어 요청 모델과 실제 모델을
    # 함께 노출합니다. 이 값이 없으면 조용한 대체를 밖에서 알 수 없습니다.
    model_id: str = Field(..., description="실제로 예측한 모델 ID")
    requested_model: str = Field(..., description="호출부가 요청한 모델 ID")
    fallback_used: bool = Field(False, description="요청 모델이 아닌 대체 모델이 답했는지 여부")
    fallback_reason: str | None = Field(None, description="대체 사유 (실패한 모델과 예외)")
    message: str = Field(..., description="사용자 안내 메시지")
    # 구간은 분위 모델을 가진 모델에서만 나옵니다. 구 모델은 None 이라
    # 원본 JsonResponse 계약을 깨지 않습니다.
    rate_low: float | None = Field(None, description="예상 낙찰률 하단 (%)")
    rate_high: float | None = Field(None, description="예상 낙찰률 상단 (%)")
    price_low: int | None = Field(None, description="예상 낙찰가 하단")
    price_high: int | None = Field(None, description="예상 낙찰가 상단")
    interval_coverage: float | None = Field(None, description="구간 명목 피복률")
    # missing_lwlt 취약 집단 및 불확실성 경고 필드 (docs/analysis/servc_missing_lwlt_policy_20260902.md)
    lwlt_missing: bool = Field(False, description="낙찰하한율 결측 여부 (제도적 부재)")
    lwlt_missing_reason: str | None = Field(
        None, description="낙찰하한율 결측 사유 (제도적 부재 구분)"
    )
    wide_interval_warning: bool = Field(False, description="예측 구간 폭이 임계값(15%p) 초과 여부")
    extreme_prediction_warning: bool = Field(
        False, description="클리핑 전 예측 낙찰률이 정상 범위(80%~100%) 이탈 여부"
    )
    uncertainty_warning: str | None = Field(None, description="불확실성 안내 및 경고 메시지")
    # 정량평가 점수 통과 판정. 배점표 B·k·T 를 주지 않으면 판정하지 않고 사유를
    # 담습니다. 기본값이 있는 추가 필드라 기존 호출부 계약은 그대로입니다.
    score_verdict: PredictPriceScoreVerdict | None = Field(
        None, description="정량평가 점수 통과 판정 결과 (배점표 미입력 시 판정 불가 사유 포함)"
    )
