"""
src/app/schemas/evaluations.py

일반용역 적격심사 정량평가 및 투찰 금액 분석 Pydantic 입출력 스키마.
분석 요청(EvaluationRequest)과 분석 결과 응답(EvaluationResponse),
사용자 평가 프로필, 증빙 메타데이터, 복수예가 시나리오 평가 스키마를 정의합니다.

설계 문서: docs/design/servc_qualification_evaluation_design_20260909.md
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from src.app.core.timeutil import utcnow

# ============================================================================
# 증빙 서류 메타데이터 스키마
# ============================================================================


class EvidenceMetadata(BaseModel):
    """적격심사 증빙 서류 메타데이터.

    원문 파일 경로나 바이너리 데이터는 저장하지 않고 메타데이터만 관리합니다.
    """

    model_config = ConfigDict(from_attributes=True)

    item_code: str = Field(
        ...,
        description="평가 항목 코드 (performance/management/labor_plan/credibility)",
        examples=["performance", "management", "labor_plan"],
    )
    issuer: str = Field(..., description="발급기관명", examples=["한국소프트웨어산업협회"])
    reference_no: str = Field(..., description="문서/증빙 일련번호", examples=["KOSA-2026-00123"])
    valid_from: date | None = Field(None, description="유효기간 시작일 (YYYY-MM-DD)")
    valid_to: date | None = Field(None, description="유효기간 만료일 (YYYY-MM-DD)")
    note: str | None = Field(None, description="비고 및 메모")


# ============================================================================
# 사용자 정량평가 자격심사 입력 스키마
# ============================================================================


class QualificationInput(BaseModel):
    """사용자 적격심사 정량평가 자격 입력값.

    수행능력 점수(실적 + 경영상태), 근로조건 이행계획 점수, 신인도 가감점 등을 수집합니다.
    근로조건 이행계획 점수는 단순노무용역 필수 항목이며 미충족/0점 시 사실상 통과가 불가합니다.
    """

    model_config = ConfigDict(from_attributes=True)

    performance_score: float = Field(
        default=0.0,
        ge=0.0,
        description="수행능력 실적 평가 점수",
    )
    management_score: float = Field(
        default=0.0,
        ge=0.0,
        description="경영상태 평가 점수 (신용평가등급 등)",
    )
    labor_plan_score: float = Field(
        default=0.0,
        ge=0.0,
        description="근로조건 이행계획 적정성 점수 (단순노무용역 필수 항목, 0점 시 통과 불가 가능)",
    )
    credibility_score: float = Field(
        default=0.0,
        description="신인도 가감점 (양수 가점, 음수 감점)",
    )
    disqualification: bool = Field(
        default=False,
        description="결격사유 해당 여부 (부정당업자 제재, 영업정지 등 해당 시 True)",
    )
    evidence_date: date | None = Field(
        default=None,
        description="증빙 서류 기준일 (입찰공고일 또는 마감일 기준 확인)",
    )
    # 아래 셋은 공고문의 적격심사 배점표에서 사용자가 읽어 입력합니다.
    # 규칙 레지스트리에 넣지 않는 이유는 실측으로 확정하지 못했기 때문입니다.
    # DB 550만 건에서 확정한 것은 별표 식별 문자열과 낙찰하한율 둘뿐이고,
    # 가격배점과 계수와 통과점수는 별표마다 다른데 공고 데이터에 들어 있지
    # 않습니다. 참고 자료의 배점표는 추정가격 구간축이라 용역 종류별 별표축과
    # 대응하지 않으며 그 값으로 실측 하한율이 재현되지도 않습니다. 추측한 값을
    # 레지스트리에 박으면 전 별표에 틀린 점수가 적용되므로 사용자 입력으로
    # 받습니다. 셋 중 하나라도 없으면 점수 계산을 차단합니다.
    max_price_score: float | None = Field(
        default=None,
        gt=0.0,
        description="가격 배점한도 B. 공고문 적격심사 배점표에서 입력",
    )
    multiplier: float | None = Field(
        default=None,
        gt=0.0,
        description="가격평점 계수 k. 공고문 적격심사 배점표에서 입력",
    )
    pass_threshold: float | None = Field(
        default=None,
        gt=0.0,
        description="적격 통과점수 T. 공고문 적격심사 배점표에서 입력",
    )


# ============================================================================
# 복수예가 시나리오 입력 및 결과 스키마
# ============================================================================


class PriceScenarioConfig(BaseModel):
    """복수예가 시나리오 구성 파라미터.

    기초금액 기준 사정율 변동 범위(예: 국가계약 +-2%, 지방계약 +-3%)를 반영한 시나리오입니다.
    """

    model_config = ConfigDict(from_attributes=True)

    scenario_name: str = Field(
        ...,
        description="시나리오명 (하단/기준/상단 또는 사용자 지정 명칭)",
        examples=["하단", "기준", "상단"],
    )
    scenario_type: str = Field(
        default="base",
        description="시나리오 구분 (lower/base/upper/custom)",
        examples=["lower", "base", "upper"],
    )
    estimated_price: int = Field(
        ...,
        gt=0,
        description="시나리오 예정가격 (원)",
    )
    variance_rate: float | None = Field(
        default=None,
        description="기초금액 대비 사정율/변동율 (예: -0.02, 0.0, +0.02)",
    )


class ScenarioEvaluationResult(BaseModel):
    """시나리오별 적격심사 가격점수 및 총점 평가 결과."""

    model_config = ConfigDict(from_attributes=True)

    scenario_name: str = Field(
        ...,
        description="시나리오명 (하단/기준/상단 등)",
    )
    scenario_type: str = Field(
        default="base",
        description="시나리오 구분 (lower/base/upper/custom)",
    )
    estimated_price: int = Field(
        ...,
        description="해당 시나리오의 예정가격 (원)",
    )
    bid_to_estimated_ratio: float = Field(
        ...,
        description="투찰율/사정율 비율 x = ROUND_HALF_UP(입찰금액 / 예정가격, 4자리)",
    )
    price_score: float | None = Field(
        default=None,
        description="입찰가격 평점 P = B - k * |(기준비율 - x) * 100|",
    )
    qualification_score: float | None = Field(
        default=None,
        description="정량평가 종합점수 Q (수행능력 + 근로조건이행계획 + 신인도)",
    )
    total_score: float | None = Field(
        default=None,
        description="종합평가 점수 (총점 = Q + P)",
    )
    pass_threshold: float | None = Field(
        default=None,
        description="적격심사 통과 기준 점수 T (예: 95점 또는 85점)",
    )
    is_qualified: bool | None = Field(
        default=None,
        description="적격 통과 여부 (결격사유 없음 AND 입찰금액 <= 예정가격 AND 총점 >= T)",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="해당 시나리오 산출 시 발생한 개별 경고 목록",
    )


# ============================================================================
# 분석 요청 및 응답 스키마
# ============================================================================


class NegotiationRateDistribution(BaseModel):
    """협상 공고 변종의 과거 낙찰률 실측 분포."""

    valid_count: int = Field(..., description="유효 집계 건수")
    average: float | None = Field(None, description="평균 낙찰률 (%)")
    median: float | None = Field(None, description="중앙값 낙찰률 (%)")
    minimum: float | None = Field(None, description="최소 낙찰률 (%)")
    maximum: float | None = Field(None, description="최대 낙찰률 (%)")


class EvaluationRequest(BaseModel):
    """적격심사 정량평가 및 투찰 분석 요청.

    공고 ID와 후보 투찰금액, 사용자 정량평가 입력값, 복수예가 시나리오 구성을 전달받습니다.
    """

    model_config = ConfigDict(from_attributes=True)

    bid_id: int = Field(
        ...,
        description="입찰공고 식별자 ID",
    )
    selected_model: str | None = Field(
        default=None,
        description="선택된 추천 모델 ID (미지정 시 카테고리 기본 모델)",
    )
    candidate_bid_amount: int = Field(
        ...,
        gt=0,
        description="검토 대상 후보 투찰 금액 (원)",
    )
    qualification_input: QualificationInput = Field(
        ...,
        description="사용자 적격심사 정량평가 자격 입력값",
    )
    price_scenarios: list[PriceScenarioConfig] | None = Field(
        default=None,
        description="복수예가 시나리오 목록 (미지정 시 공고 기초금액 및 규정 범위로 자동 구성)",
    )


class EvaluationResponse(BaseModel):
    """적격심사 정량평가 및 투찰 분석 응답.

    적용된 심사 규칙, 규칙 판별 근거, 계산 차단 여부 및 사유, 모델 출처,
    A값 반영 투찰금액, 최저 가능 투찰률 역산값, 시나리오별 평가 결과 및 경고를 반환합니다.
    """

    model_config = ConfigDict(from_attributes=True)

    status: str = Field(
        default="success",
        description="분석 상태 (success / blocked / error)",
    )
    rule_id: str | None = Field(
        default=None,
        description="적용된 적격심사 세부 규칙 식별자 (예: servc_facility_under_500m)",
    )
    rule_name: str | None = Field(
        default=None,
        description="적용된 적격심사 세부 규칙 명칭",
    )
    rule_basis: str | None = Field(
        default=None,
        description="적격심사 규칙 판별 근거 (낙찰방법 식별문자열 매칭 근거 등)",
    )
    negotiation_variant: str | None = Field(
        default=None,
        description="협상에의한계약 변종 식별자 (STANDARD/SW/ENGINEERING/CONSTRUCTION_ENGINEERING)",
    )
    negotiation_tech_eval_rate: float | None = Field(
        default=None,
        description="협상에의한계약 기술능력 평가비율 (%)",
    )
    negotiation_price_eval_rate: float | None = Field(
        default=None,
        description="협상에의한계약 입찰가격 평가비율 (%)",
    )
    negotiation_rate_distribution: NegotiationRateDistribution | None = Field(
        default=None, description="협상 공고 변종의 과거 낙찰률 실측 분포 참고값"
    )
    blocked: bool = Field(
        default=False,
        description="계산 차단 여부 (지원 범위 밖, 비예가, 수기심사 등 계산 불가 조건 시 True)",
    )
    blocked_reason: str | None = Field(
        default=None,
        description="계산 차단 세부 사유",
    )
    requested_model: str | None = Field(
        default=None,
        description="요청된 추천 모델 식별자",
    )
    actual_model: str | None = Field(
        default=None,
        description="실제 적용된 추천 모델 식별자",
    )
    fallback_used: bool = Field(
        default=False,
        description="대체 모델 사용 여부",
    )
    fallback_reason: str | None = Field(
        default=None,
        description="대체 모델 사용 사유",
    )
    base_rate: float | None = Field(
        default=None,
        description="가격점수 산식 기준비율 (%)",
    )
    lower_bound_rate: float | None = Field(
        default=None,
        description="낙찰하한율 (%)",
    )
    a_value_amount: int | None = Field(
        default=None,
        description="A값 (국민연금, 건강보험, 퇴직급여충당금 등 비투찰/고정비용 합산액)",
    )
    min_bid_amount_with_a: int | None = Field(
        default=None,
        description="A값 반영 최저 투찰금액 (원)",
    )
    min_possible_bid_rate: float | None = Field(
        default=None,
        description="정량점수 충족을 위한 최저 가능 투찰률 역산 결과 (%)",
    )
    scenario_results: list[ScenarioEvaluationResult] = Field(
        default_factory=list,
        description="복수예가 시나리오별 평가 결과 목록",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="전체 종합 경고 메시지 목록",
    )
    created_at: datetime = Field(
        default_factory=utcnow,
        description="분석 일시",
    )


# ============================================================================
# 사용자 프로필 CRUD 스키마
# ============================================================================


class EvaluationProfileCreate(BaseModel):
    """사용자 정량평가 프로필 생성 요청."""

    name: str = Field(..., max_length=100, description="프로필 명칭")
    framework: str = Field(
        default="servc_qualification",
        max_length=50,
        description="평가 기준 프레임워크",
    )
    input_schema_version: str = Field(
        default="1.0",
        max_length=20,
        description="입력 스키마 버전",
    )
    input_json: dict[str, Any] = Field(
        ...,
        description="사용자 정량평가 기본 입력값 딕셔너리",
    )


class EvaluationProfileUpdate(BaseModel):
    """사용자 정량평가 프로필 수정 요청."""

    name: str | None = Field(None, max_length=100, description="프로필 명칭")
    framework: str | None = Field(None, max_length=50, description="평가 기준 프레임워크")
    input_schema_version: str | None = Field(None, max_length=20, description="입력 스키마 버전")
    input_json: dict[str, Any] | None = Field(
        None, description="사용자 정량평가 기본 입력값 딕셔너리"
    )


class EvaluationProfileResponse(BaseModel):
    """사용자 정량평가 프로필 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="프로필 식별자 ID")
    user_id: int = Field(..., description="소유자 사용자 ID")
    name: str = Field(..., description="프로필 명칭")
    framework: str = Field(..., description="평가 기준 프레임워크")
    input_schema_version: str = Field(..., description="입력 스키마 버전")
    input_json: dict[str, Any] = Field(..., description="사용자 정량평가 기본 입력값")
    created_at: datetime = Field(..., description="생성 일시")
    updated_at: datetime = Field(..., description="수정 일시")


# ============================================================================
# 분석 스냅샷 CRUD 스키마
# ============================================================================


class EvaluationSnapshotCreate(BaseModel):
    """분석 스냅샷 저장 요청."""

    bid_id: int = Field(..., description="입찰공고 식별자 ID")
    rule_id: str = Field(..., max_length=100, description="적용된 심사 규칙 ID")
    model_id: str = Field(..., max_length=100, description="적용된 추천 모델 ID")
    model_version: str = Field(..., max_length=50, description="추천 모델 버전")
    input_json: dict[str, Any] = Field(..., description="분석에 사용된 전체 입력 스냅샷")
    result_json: dict[str, Any] = Field(..., description="산출된 분석 결과 스냅샷")
    evidence_items: list[EvidenceMetadata] = Field(
        default_factory=list,
        description="함께 보존할 증빙 서류 메타데이터 목록",
    )


class EvaluationSnapshotResponse(BaseModel):
    """분석 스냅샷 응답."""

    model_config = ConfigDict(from_attributes=True)

    id: int = Field(..., description="스냅샷 식별자 ID")
    bid_id: int = Field(..., description="입찰공고 식별자 ID")
    user_id: int = Field(..., description="소유자 사용자 ID")
    rule_id: str = Field(..., description="적용된 심사 규칙 ID")
    model_id: str = Field(..., description="적용된 추천 모델 ID")
    model_version: str = Field(..., description="추천 모델 버전")
    input_json: dict[str, Any] = Field(..., description="분석 입력 스냅샷")
    result_json: dict[str, Any] = Field(..., description="분석 결과 스냅샷")
    created_at: datetime = Field(..., description="스냅샷 생성 일시")
    evidence_items: list[EvidenceMetadata] = Field(
        default_factory=list,
        description="증빙 서류 메타데이터 목록",
    )
