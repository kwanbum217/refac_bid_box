"""
src/app/api/v1/evaluations.py

일반용역 적격심사 정량평가 통합 분석 API 및 프로필/스냅샷 CRUD.

| 기능 | 엔드포인트 |
| --- | --- |
| 통합 분석 | POST /api/v1/evaluations/analyze |
| 별표 규칙 메타 | GET /api/v1/evaluations/rules |
| 프로필 목록 | GET /api/v1/evaluations/profiles |
| 프로필 생성 | POST /api/v1/evaluations/profiles |
| 프로필 조회 | GET /api/v1/evaluations/profiles/{profile_id} |
| 프로필 수정 | PUT /api/v1/evaluations/profiles/{profile_id} |
| 프로필 삭제 | DELETE /api/v1/evaluations/profiles/{profile_id} |
| 스냅샷 목록 | GET /api/v1/evaluations/snapshots |
| 스냅샷 저장 | POST /api/v1/evaluations/snapshots |
| 스냅샷 조회 | GET /api/v1/evaluations/snapshots/{snapshot_id} |
| 스냅샷 삭제 | DELETE /api/v1/evaluations/snapshots/{snapshot_id} |

설계 문서: docs/design/servc_qualification_evaluation_design_20260909.md

본 파일은 산식 상수를 하나도 가지지 않습니다. 규칙 판별과 낙찰하한율은 evaluation_rules,
점수 계산과 적격 판정과 역산은 evaluation_scoring, 모델 출처는 predict_price_api 가 정본입니다.
가격배점한도(B)·평점계수(k)·통과점수(T) 는 규칙 레지스트리가 원문으로 확정한 규칙만 선언값을
갖고, 확정하지 못한 규칙은 사용자가 공고문 배점표로 입력합니다. 사용자 입력은 규칙 선언값을
덮어쓰는 용도이며, 선언값도 입력도 없으면 추측 대신 점수 계산만 차단합니다.

차단 코드:
- 규칙 판별 차단 (evaluation_rules): NOT_SERVC, NON_PRED_PRICE, MANUAL_EVALUATION, RULE_NOT_FOUND,
  NEGOTIATION_CONTRACT, TECH_SERVICE_MISSING_LWLT, NOT_QUALIFICATION_METHOD, RULE_REGIME_MISMATCH
- 입력·데이터 부족 차단 (본 파일): MISSING_SCORE_TABLE, PRED_PRICE_UNAVAILABLE
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.app.api.v1.accounts import require_current_user
from src.app.api.v1.predictions import predict_price_api
from src.app.core.db import get_db
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.models.evaluations import (
    BidEvaluationEvidence,
    BidEvaluationProfile,
    BidEvaluationSnapshot,
)
from src.app.schemas.evaluations import (
    CreditGradePayload,
    EvaluationProfileCreate,
    EvaluationProfileResponse,
    EvaluationProfileUpdate,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationSnapshotCreate,
    EvaluationSnapshotResponse,
    EvidenceMetadata,
    NegotiationRateDistribution,
    PriceCompensation,
    PriceCompensationScenario,
    PriceScenarioConfig,
    QualificationInput,
    QuantScoreBandPayload,
    QuantScoreItemPayload,
    QuantScoreTablePayload,
    ReputationItemPayload,
    RuleScoreTable,
    ScenarioEvaluationResult,
)
from src.app.schemas.predictions import PredictPriceRequest
from src.app.services.demand_institutions import classify_contract_regime, institution_region
from src.app.services.evaluation_rules import (
    CREDIT_GRADE_SCORES,
    METHOD_FAMILY_BY_CODE,
    METHOD_SOURCE_CODE,
    POST_20260727_RULES,
    QUANT_ITEM_LABOR_PLAN,
    QUANT_ITEM_MANAGEMENT,
    QUANT_ITEM_PERFORMANCE,
    QUANT_ITEM_REPUTATION,
    QUANT_LIMIT_KIND_ABSENT,
    QUANT_LIMIT_KIND_RANGE,
    QUANT_LIMIT_KIND_SCORE,
    REPUTATION_INDUSTRIAL_ACCIDENT_MAX_BONUS,
    REPUTATION_ITEM_INDUSTRIAL_ACCIDENT,
    REPUTATION_ITEMS,
    REPUTATION_MAX_BONUS,
    REPUTATION_MAX_PENALTY,
    REPUTATION_OPTION_CHOICE,
    EvaluationRule,
    QuantScoreBand,
    QuantScoreItem,
    QuantScoreTable,
    RuleResolutionResult,
    ScoreParamResolution,
    credit_score_for_grade,
    demand_agency_credit_deduction,
    extract_contract_regime,
    find_reputation_item,
    quant_score_table_for_rule,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
    select_quant_band,
)
from src.app.services.evaluation_scoring import (
    PriceCompensationResult,
    calculate_min_bid_amount,
    calculate_price_score,
    compute_price_ratio,
    evaluate_qualification,
    format_decimal_plain,
    generate_pred_price_scenarios,
    invert_lowest_bid_rate,
    resolve_price_compensation,
)
from src.app.services.negotiation_stats import get_negotiation_stats

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluations", tags=["Evaluations"])


# =============================================================================
# 헬퍼 함수
# =============================================================================

# 규칙 레지스트리는 별표 식별 문자열과 낙찰하한율을 실측으로 확정했고, 가격배점한도(B)·
# 평점계수(k)·통과점수(T) 는 원문 별표 문서로 확정된 규칙만 선언값을 갖습니다. 확정하지
# 못한 규칙은 사용자가 공고문 배점표를 입력하며, 사용자 입력은 규칙 선언값을 덮어씁니다.
# 이 계층은 선언값도 입력도 없는 값을 추측하지 않습니다.
SCORE_TABLE_LABELS: dict[str, str] = {
    "max_price_score": "가격배점한도",
    "multiplier": "평점계수",
    "pass_threshold": "통과점수",  # nosec B105 - 배점표 항목의 한국어 표기이지 비밀번호가 아닙니다
}

# 규칙 판별(도메인)이 아니라 입력·데이터 부족으로 계산을 멈추는 코드입니다.
BLOCK_CODE_MISSING_SCORE_TABLE = "MISSING_SCORE_TABLE"
BLOCK_CODE_PRED_PRICE_UNAVAILABLE = "PRED_PRICE_UNAVAILABLE"
# 적용 별표 배점표에 없는 항목 입력 또는 배점한도 초과를 막는 코드입니다(조용히 자르지 않습니다).
BLOCK_CODE_QUANT_LIMIT_EXCEEDED = "QUANT_LIMIT_EXCEEDED"
BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE = "QUANT_ITEM_NOT_IN_TABLE"
BLOCK_CODE_QUANT_GRADE_UNKNOWN = "QUANT_GRADE_UNKNOWN"
BLOCK_CODE_QUANT_BAND_UNRESOLVED = "QUANT_BAND_UNRESOLVED"


@dataclass(frozen=True)
class ScoreTable:
    """가격점수 계산 파라미터. B·k·T 는 사용자 입력, 기준비율은 규칙 레지스트리 선언값입니다."""

    max_price_score: Decimal
    multiplier: Decimal
    pass_threshold: Decimal
    base_rate: Decimal


@dataclass(frozen=True)
class ScenarioPrice:
    """시나리오별 예정가격 입력. 값의 계산은 evaluation_scoring 이 수행합니다."""

    scenario_name: str
    scenario_type: str
    pred_price: Decimal


@dataclass(frozen=True)
class ModelProvenance:
    """predict_price_api 로부터 전달받은 모델 출처."""

    requested_model: str | None
    actual_model: str | None
    fallback_used: bool
    fallback_reason: str | None


def _get_bid_or_404(db: Session, bid_id: int) -> BidAnnouncement:
    """공고 조회 또는 404."""
    bid = db.get(BidAnnouncement, bid_id)
    if bid is None:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")
    return bid


def _get_profile_or_404(db: Session, profile_id: int, user_id: int) -> BidEvaluationProfile:
    """본인 소유 프로필 조회 또는 404 (타 사용자 자원 접근 차단)."""
    profile = db.get(BidEvaluationProfile, profile_id)
    if profile is None or profile.user_id != user_id:
        raise HTTPException(status_code=404, detail="프로필을 찾을 수 없습니다.")
    return profile


def _get_snapshot_or_404(db: Session, snapshot_id: int, user_id: int) -> BidEvaluationSnapshot:
    """본인 소유 스냅샷 조회 또는 404 (타 사용자 자원 접근 차단)."""
    snapshot = db.get(BidEvaluationSnapshot, snapshot_id)
    if snapshot is None or snapshot.user_id != user_id:
        raise HTTPException(status_code=404, detail="스냅샷을 찾을 수 없습니다.")
    return snapshot


def _score_table(
    qualification: QualificationInput,
    rule: EvaluationRule,
    bid: BidAnnouncement,
) -> tuple[ScoreTable | None, list[str], list[str], ScoreParamResolution]:
    """가격점수에 필요한 배점표 파라미터를 규칙 선언값과 사용자 입력으로 정합니다.

    규칙 레지스트리가 원문으로 확정한 선언값이 기본이고, 사용자 직접 입력은 그 선언값을
    덮어쓰는 용도입니다. 선언값도 입력도 없는 필드는 추측하지 않고, 결측 필드명과 사용자가
    선언값과 다르게 입력한 필드명을 함께 돌려 점수 계산을 차단합니다. 기준비율은 규칙
    객체의 선언값을 씁니다.
    """
    raw_price = getattr(bid, "presmpt_prce", None)
    raw_data = getattr(bid, "raw_data", None) or {}
    resolution = resolve_score_params(
        rule,
        raw_price,
        getattr(bid, "bid_ntce_dt", None),
        getattr(bid, "sucsfbid_mthd_nm", None)
        or raw_data.get("sucsfbidMthdNm")
        or raw_data.get("sucsfbid_mthd_nm"),
    )
    declared: dict[str, Decimal | None] = {
        "max_price_score": resolution.max_price_score,
        "multiplier": resolution.multiplier,
        "pass_threshold": resolution.pass_threshold,
    }
    supplied: dict[str, float | None] = {
        "max_price_score": qualification.max_price_score,
        "multiplier": qualification.multiplier,
        "pass_threshold": qualification.pass_threshold,
    }
    resolved: dict[str, Decimal] = {}
    missing: list[str] = []
    overridden: list[str] = []
    for field_name, declared_value in declared.items():
        user_value = supplied[field_name]
        if user_value is None:
            if declared_value is None:
                missing.append(field_name)
            else:
                resolved[field_name] = declared_value
            continue
        user_decimal = Decimal(str(user_value))
        resolved[field_name] = user_decimal
        if declared_value is not None and user_decimal != declared_value:
            overridden.append(field_name)
    if missing:
        return None, missing, overridden, resolution

    return (
        ScoreTable(
            max_price_score=resolved["max_price_score"],
            multiplier=resolved["multiplier"],
            pass_threshold=resolved["pass_threshold"],
            base_rate=rule.base_rate,
        ),
        [],
        overridden,
        resolution,
    )


def _rule_score_table_payload(
    rule: EvaluationRule,
    missing_fields: list[str],
    override_fields: list[str],
    resolution: ScoreParamResolution | None = None,
) -> RuleScoreTable:
    """규칙 선언 배점표와 미확정·덮어쓰기 표시를 응답 스키마로 옮깁니다."""
    return RuleScoreTable(
        max_price_score=(
            format_decimal_plain(resolution.max_price_score)
            if resolution and resolution.max_price_score is not None
            else (
                format_decimal_plain(rule.max_price_score)
                if rule.max_price_score is not None
                else None
            )
        ),
        max_price_score_basis=_score_param_basis(resolution, "B"),
        multiplier=(
            format_decimal_plain(resolution.multiplier)
            if resolution and resolution.multiplier is not None
            else (format_decimal_plain(rule.multiplier) if rule.multiplier is not None else None)
        ),
        multiplier_basis=_score_param_basis(resolution, "k"),
        pass_threshold=(
            format_decimal_plain(rule.pass_threshold) if rule.pass_threshold is not None else None
        ),
        source=rule.score_table_source,
        missing_fields=list(missing_fields),
        override_fields=list(override_fields),
    )


def _score_param_basis(resolution: ScoreParamResolution | None, axis: str) -> str | None:
    if resolution is None:
        return None
    if axis == "B":
        value, basis, boundary = (
            resolution.max_price_score,
            resolution.max_price_score_basis,
            resolution.max_price_score_boundary,
        )
    else:
        value, basis, boundary = (
            resolution.multiplier,
            resolution.multiplier_basis,
            resolution.multiplier_boundary,
        )
    if value is None or basis is None:
        return None
    if basis == "FIXED":
        return "규칙 고정값"
    if basis == "METHOD_NAME":
        return f"낙찰방법명 구간 표기 → {value}"
    if resolution.estimated_price is None or boundary is None:
        return None
    comparison = "≥" if resolution.estimated_price >= boundary else "<"
    price_label = f"{resolution.estimated_price:,.0f}"
    boundary_label = f"{boundary:,.0f}"
    return f"추정가격 {price_label} {comparison} {boundary_label} → {value}"


# =============================================================================
# 정량평가 배점표(별표 1~9) 해석·검증
# =============================================================================

# 별표 배점표에서 사용자가 점수로 입력하는 항목 종류입니다. 경영상태(등급 선택), 신인도
# (항목 합계), 입찰가격, 결격사유는 별도 경로로 처리합니다.
_QUANT_INPUT_KINDS = frozenset(
    {QUANT_LIMIT_KIND_SCORE, QUANT_LIMIT_KIND_ABSENT, QUANT_LIMIT_KIND_RANGE}
)


@dataclass(frozen=True)
class QuantInputScores:
    """별표 배점표 검증을 통과한 정량평가 입력 점수(수행능력 계/근로조건/신인도)."""

    performance: Decimal
    labor_plan: Decimal
    reputation: Decimal
    has_labor_item: bool


def _bid_estimated_price(bid: BidAnnouncement) -> Decimal | None:
    """5억원 구간 판정용 추정가격. presmpt_prce 를 우선하고 없으면 기초금액을 씁니다."""
    for attr in ("presmpt_prce", "base_amount"):
        raw = getattr(bid, attr, None)
        if raw is None:
            continue
        try:
            value = Decimal(str(raw))
        except (ArithmeticError, TypeError, ValueError):
            continue
        if value > Decimal("0"):
            return value
    return None


def _quant_item_payload(item: QuantScoreItem) -> QuantScoreItemPayload:
    """심사항목 한 줄을 응답 스키마로 옮깁니다. 값은 지수 표기 없는 문자열입니다."""
    return QuantScoreItemPayload(
        section_no=item.section_no,
        section_name=item.section_name,
        item_key=item.item_key,
        item_name=item.item_name,
        limit=(format_decimal_plain(item.limit) if item.limit is not None else None),
        limit_min=(format_decimal_plain(item.limit_min) if item.limit_min is not None else None),
        limit_kind=item.limit_kind,
        source=item.source,
        note=item.note,
    )


def _quant_table_payload(
    table: QuantScoreTable,
    band: QuantScoreBand | None,
    band_note: str | None,
) -> QuantScoreTablePayload:
    """규칙이 선언한 별표 배점표와 별표 10·11 표를 응답으로 옮깁니다.

    화면은 이 선언으로 입력란을 그리고, 서버는 같은 선언으로 입력을 검증합니다.
    """
    return QuantScoreTablePayload(
        attachment=table.attachment,
        table_name=table.table_name,
        source=table.source,
        note=table.note,
        bands=[
            QuantScoreBandPayload(
                band_key=table_band.band_key,
                band_label=table_band.band_label,
                total_limit=format_decimal_plain(table_band.total_limit),
                items=[_quant_item_payload(item) for item in table_band.items],
            )
            for table_band in table.bands
        ],
        active_band_key=band.band_key if band is not None else None,
        band_note=band_note,
        credit_grades=[
            CreditGradePayload(
                grade_group=grade.grade_group,
                grade_codes=list(grade.grade_codes),
                score_at_20=format_decimal_plain(grade.score_at_20),
                score_at_10=format_decimal_plain(grade.score_at_10),
                source=grade.source,
            )
            for grade in CREDIT_GRADE_SCORES
        ],
        reputation_items=[
            ReputationItemPayload(
                item_code=item.item_code,
                item_name=item.item_name,
                option_kind=item.option_kind,
                options=[format_decimal_plain(value) for value in item.options],
                source=item.source,
                note=item.note,
            )
            for item in REPUTATION_ITEMS
        ],
        reputation_max_bonus=format_decimal_plain(REPUTATION_MAX_BONUS),
        reputation_max_penalty=format_decimal_plain(REPUTATION_MAX_PENALTY),
    )


def _quant_value(raw: float | None) -> Decimal:
    return Decimal(str(raw)) if raw is not None else Decimal("0")


def _append_quant_violation(violations: list[tuple[str, str]], code: str, message: str) -> None:
    violations.append((code, message))


def _check_quant_item(
    limits: dict[str, QuantScoreItem],
    item_key: str,
    value: Decimal,
    fallback_name: str,
    band_label: str,
    violations: list[tuple[str, str]],
) -> None:
    """항목값이 배점표에 있는지, 배점한도를 넘는지 검사합니다. 조용히 자르지 않습니다."""
    item = limits.get(item_key)
    if item is None or item.limit_kind not in _QUANT_INPUT_KINDS:
        if value != Decimal("0"):
            name = item.item_name if item is not None else fallback_name
            _append_quant_violation(
                violations,
                BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE,
                f"{name}: {band_label} 배점표에 없는 항목이라 입력할 수 없습니다.",
            )
        return
    if item.limit is not None and value > item.limit:
        _append_quant_violation(
            violations,
            BLOCK_CODE_QUANT_LIMIT_EXCEEDED,
            f"{item.item_name}: 입력값 {format_decimal_plain(value)} 가 배점한도 "
            f"{format_decimal_plain(item.limit)} 를 초과합니다.",
        )
    if item.limit_min is not None and value < item.limit_min:
        _append_quant_violation(
            violations,
            BLOCK_CODE_QUANT_LIMIT_EXCEEDED,
            f"{item.item_name}: 입력값 {format_decimal_plain(value)} 가 하한 "
            f"{format_decimal_plain(item.limit_min)} 미만입니다.",
        )


def _management_quant_score(
    qualification: QualificationInput,
    limits: dict[str, QuantScoreItem],
    table: QuantScoreTable,
    band_label: str,
    violations: list[tuple[str, str]],
) -> Decimal:
    """경영상태 점수. 신용평가등급 선택이 정본이고 배점한도 기준을 서버가 구분합니다.

    구형 경로의 management_score 직접 입력은 배점한도 안에서만 허용합니다.
    """
    item = limits.get(QUANT_ITEM_MANAGEMENT)
    if qualification.management_grade:
        if item is None:
            _append_quant_violation(
                violations,
                BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE,
                f"경영상태: {band_label} 배점표에 없는 항목이라 신용평가등급을 적용할 수 없습니다.",
            )
            return Decimal("0")
        if table.attachment == "별표 9":
            deduction = demand_agency_credit_deduction(qualification.management_grade)
            if deduction is None or item.limit is None:
                _append_quant_violation(
                    violations,
                    BLOCK_CODE_QUANT_GRADE_UNKNOWN,
                    f"신용평가등급 '{qualification.management_grade}' 를 별표 9 기준에서 해석하지 못했습니다.",
                )
                return Decimal("0")
            return item.limit - deduction
        if item.limit is None:
            _append_quant_violation(
                violations,
                BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE,
                f"경영상태: {band_label} 배점표에 경영상태 배점한도가 없습니다.",
            )
            return Decimal("0")
        score = credit_score_for_grade(qualification.management_grade, item.limit)
        if score is None:
            _append_quant_violation(
                violations,
                BLOCK_CODE_QUANT_GRADE_UNKNOWN,
                f"신용평가등급 '{qualification.management_grade}' 를 별표 10 에서 해석하지 못했습니다.",
            )
            return Decimal("0")
        return score
    manual = _quant_value(qualification.management_score)
    if manual == Decimal("0"):
        return Decimal("0")
    if item is None or item.limit is None:
        _append_quant_violation(
            violations,
            BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE,
            f"경영상태: {band_label} 배점표에 없는 항목이라 입력할 수 없습니다.",
        )
        return Decimal("0")
    if manual > item.limit:
        _append_quant_violation(
            violations,
            BLOCK_CODE_QUANT_LIMIT_EXCEEDED,
            f"{item.item_name}: 입력값 {format_decimal_plain(manual)} 가 배점한도 "
            f"{format_decimal_plain(item.limit)} 를 초과합니다.",
        )
    return manual


def _reputation_quant_score(
    qualification: QualificationInput,
    band_label: str,
    violations: list[tuple[str, str]],
) -> Decimal:
    """신인도 점수. 별표 11 항목 합계를 내고 가점·감점 상한을 적용합니다(가감 상계)."""
    reputation_items = qualification.reputation_items
    if not reputation_items:
        # 구형 경로 단일 가감점 입력도 가점·감점 상한 안에서만 허용합니다.
        legacy = _quant_value(qualification.credibility_score)
        if legacy == Decimal("0"):
            return Decimal("0")
        if legacy > REPUTATION_MAX_BONUS:
            _append_quant_violation(
                violations,
                BLOCK_CODE_QUANT_LIMIT_EXCEEDED,
                f"신인도: 입력값 {format_decimal_plain(legacy)} 가 가점 상한 "
                f"{format_decimal_plain(REPUTATION_MAX_BONUS)} 를 초과합니다.",
            )
        elif legacy < REPUTATION_MAX_PENALTY:
            _append_quant_violation(
                violations,
                BLOCK_CODE_QUANT_LIMIT_EXCEEDED,
                f"신인도: 입력값 {format_decimal_plain(legacy)} 가 감점 상한 "
                f"{format_decimal_plain(REPUTATION_MAX_PENALTY)} 미만입니다.",
            )
        return legacy
    total = Decimal("0")
    has_accident_penalty = False
    for code, raw_value in reputation_items.items():
        item = find_reputation_item(code)
        if item is None:
            _append_quant_violation(
                violations,
                BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE,
                f"신인도 항목 '{code}' 는 별표 11 항목표에 없습니다.",
            )
            continue
        value = _quant_value(raw_value)
        if item.option_kind == REPUTATION_OPTION_CHOICE:
            if value not in item.options:
                _append_quant_violation(
                    violations,
                    BLOCK_CODE_QUANT_LIMIT_EXCEEDED,
                    f"{item.item_name}: {format_decimal_plain(value)} 는 선택 가능한 평점이 아닙니다.",
                )
                continue
        else:
            low, high = item.options[0], item.options[-1]
            if value < low or value > high:
                _append_quant_violation(
                    violations,
                    BLOCK_CODE_QUANT_LIMIT_EXCEEDED,
                    f"{item.item_name}: {format_decimal_plain(value)} 가 범위 "
                    f"{format_decimal_plain(low)}~{format_decimal_plain(high)} 밖입니다.",
                )
                continue
        if code == REPUTATION_ITEM_INDUSTRIAL_ACCIDENT and value < Decimal("0"):
            has_accident_penalty = True
        total += value
    bonus_cap = (
        REPUTATION_INDUSTRIAL_ACCIDENT_MAX_BONUS if has_accident_penalty else REPUTATION_MAX_BONUS
    )
    return min(max(total, REPUTATION_MAX_PENALTY), bonus_cap)


def _resolve_quant_inputs(
    qualification: QualificationInput,
    table: QuantScoreTable,
    band: QuantScoreBand,
) -> tuple[QuantInputScores | None, list[tuple[str, str]]]:
    """정량평가 입력을 적용 별표 배점표로 검증하고 점수로 환산합니다.

    배점표에 없는 항목 키나 배점한도 초과·하한 미만이면 자르지 않고 위반 목록을 돌려줍니다.
    위반이 하나라도 있으면 점수를 확정하지 않고 (None, 위반) 을 반환합니다.
    """
    limits = {item.item_key: item for item in band.items}
    violations: list[tuple[str, str]] = []

    # 구형 경로 필드는 quant_items 가 그 항목을 담고 있지 않을 때만 대체 입력으로 씁니다.
    items: dict[str, float] = dict(qualification.quant_items)
    if QUANT_ITEM_PERFORMANCE not in items and qualification.performance_score:
        items[QUANT_ITEM_PERFORMANCE] = qualification.performance_score
    if QUANT_ITEM_LABOR_PLAN not in items and qualification.labor_plan_score:
        items[QUANT_ITEM_LABOR_PLAN] = qualification.labor_plan_score

    performance = Decimal("0")
    labor_plan = Decimal("0")
    for item_key, raw_value in items.items():
        value = _quant_value(raw_value)
        if item_key == QUANT_ITEM_MANAGEMENT:
            # 경영상태는 신용평가등급 선택이 정본이라 점수 직접 입력을 받지 않습니다.
            if value != Decimal("0"):
                _append_quant_violation(
                    violations,
                    BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE,
                    "경영상태: 신용평가등급 선택으로 입력해야 하며 점수를 직접 넣을 수 없습니다.",
                )
            continue
        if item_key == QUANT_ITEM_REPUTATION:
            if value != Decimal("0"):
                _append_quant_violation(
                    violations,
                    BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE,
                    "신인도: 항목별 선택값(reputation_items)으로 입력해야 하며 합계를 직접 넣을 수 없습니다.",
                )
            continue
        _check_quant_item(limits, item_key, value, item_key, band.band_label, violations)
        if item_key == QUANT_ITEM_LABOR_PLAN:
            labor_plan += value
        else:
            performance += value

    management = _management_quant_score(qualification, limits, table, band.band_label, violations)
    reputation = _reputation_quant_score(qualification, band.band_label, violations)
    performance += management

    has_labor_item = any(
        item.item_key == QUANT_ITEM_LABOR_PLAN and item.limit_kind in _QUANT_INPUT_KINDS
        for item in band.items
    )

    if violations:
        return None, violations
    return (
        QuantInputScores(
            performance=performance,
            labor_plan=labor_plan,
            reputation=reputation,
            has_labor_item=has_labor_item,
        ),
        [],
    )


def _announcement_pred_price(bid: BidAnnouncement) -> Decimal | None:
    """공고의 예정가격 기준액. BidAnnouncement.prediction_reference_amount 접근자를 정본으로 씁니다."""
    reference = bid.prediction_reference_amount
    if reference is None:
        return None
    value = Decimal(str(reference))
    return value if value > Decimal("0") else None


def _raw_int(raw_data: dict[str, Any], key: str) -> int | None:
    """공고 raw_data 의 정수 필드. 결측이면 None 을 돌려 도메인 기본값에 맡깁니다."""
    try:
        value = int(str(raw_data.get(key, "")).strip())
    except (ArithmeticError, TypeError, ValueError):
        return None
    return value if value > 0 else None


def _is_local_contract(bid: BidAnnouncement, institution_regime: str | None = None) -> bool:
    """계약 방법 명칭 또는 수요기관 기준정보에서 지방계약 여부를 판단합니다."""
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    return extract_contract_regime(raw_data, bid.cntrct_mthd_nm, institution_regime) == "LOCAL"


def _demand_institution_for_bid(db: Session, bid: BidAnnouncement) -> G2BDemandInstitution | None:
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    code = str(raw_data.get("dminsttCd") or "").strip()
    return db.get(G2BDemandInstitution, code) if code else None


def _scenario_prices(
    bid: BidAnnouncement,
    request_scenarios: list[PriceScenarioConfig] | None,
    institution_regime: str | None = None,
) -> list[ScenarioPrice]:
    """복수예가 3 시나리오 예정가격을 구성합니다.

    복수예가 총수와 추첨수는 공고의 totPrdprcNum·drwtPrdprcNum 을 우선하고,
    결측일 때만 evaluation_scoring.generate_pred_price_scenarios 의 기본값이 적용됩니다.
    """
    if request_scenarios:
        return [
            ScenarioPrice(
                scenario_name=scenario.scenario_name,
                scenario_type=scenario.scenario_type,
                pred_price=Decimal(str(scenario.estimated_price)),
            )
            for scenario in request_scenarios
        ]

    base_amount = _announcement_pred_price(bid)
    if base_amount is None:
        return []

    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    is_local = _is_local_contract(bid, institution_regime)
    tot_prdprc_num = _raw_int(raw_data, "totPrdprcNum")
    drwt_prdprc_num = _raw_int(raw_data, "drwtPrdprcNum")
    if tot_prdprc_num is not None and drwt_prdprc_num is not None:
        scenarios = generate_pred_price_scenarios(
            base_amount,
            tot_prdprc_num=tot_prdprc_num,
            drwt_prdprc_num=drwt_prdprc_num,
            is_local_contract=is_local,
        )
    else:
        # 공고에 필드가 없으면 evaluation_scoring.generate_pred_price_scenarios
        # 의 기본값 계약에 맡깁니다. 이 계층에서 수치를 복제하지 않습니다.
        scenarios = generate_pred_price_scenarios(base_amount, is_local_contract=is_local)
    return [
        ScenarioPrice("하단", "lower", scenarios.scenario_lower),
        ScenarioPrice("기준", "base", scenarios.scenario_base),
        ScenarioPrice("상단", "upper", scenarios.scenario_upper),
    ]


def _qualification_scores(scores: QuantInputScores) -> tuple[Decimal, Decimal, Decimal]:
    """검증된 입력 점수를 수행능력(실적+기술능력+경영상태), 근로조건, 신인도로 나눕니다.

    구분은 적용 별표 배점표의 심사분야가 정본이며(별표 2 만 근로조건이 별도 심사번호),
    평가_qualification 도메인 함수의 성능/근로조건/신인도 인자에 그대로 대응합니다.
    """
    return scores.performance, scores.labor_plan, scores.reputation


def _as_percent(value: Decimal) -> float:
    """비율을 응답 스키마가 요구하는 퍼센트 숫자로 바꿉니다."""
    return float(value * Decimal("100")) if value <= Decimal("1") else float(value)


def _evaluate_scenario(
    scenario: ScenarioPrice,
    candidate_bid_amount: Decimal,
    scores: tuple[Decimal, Decimal, Decimal],
    qualification: QualificationInput,
    table: ScoreTable,
    has_labor_item: bool,
) -> ScenarioEvaluationResult:
    """단일 시나리오의 가격점수와 적격 판정을 evaluation_scoring 에 위임합니다.

    근로조건 이행계획이 없는 별표에서는 도메인의 '근로조건 0점' 경고를 내보내지 않습니다.
    """
    performance_score, labor_score, credibility_score = scores
    price = calculate_price_score(
        bid_price=candidate_bid_amount,
        pred_price=scenario.pred_price,
        base_rate=table.base_rate,
        max_price_score=table.max_price_score,
        multiplier=table.multiplier,
    )
    judgement = evaluate_qualification(
        bid_price=candidate_bid_amount,
        pred_price=scenario.pred_price,
        pass_threshold=table.pass_threshold,
        price_score=price.score,
        performance_score=performance_score,
        labor_condition_score=labor_score,
        reputation_score=credibility_score,
        has_disqualification=qualification.disqualification,
    )
    warnings = [
        warning
        for warning in judgement.warnings
        if has_labor_item or "근로조건 이행계획" not in warning
    ]
    return ScenarioEvaluationResult(
        scenario_name=scenario.scenario_name,
        scenario_type=scenario.scenario_type,
        estimated_price=int(scenario.pred_price),
        bid_to_estimated_ratio=float(price.price_ratio),
        price_score=float(price.score),
        qualification_score=float(judgement.non_price_score),
        total_score=float(judgement.total_score),
        pass_threshold=float(judgement.pass_threshold),
        is_qualified=judgement.is_qualified,
        warnings=warnings,
    )


def _rule_basis(bid: BidAnnouncement, rule_result: RuleResolutionResult) -> str:
    """규칙 판별 근거. 매칭에 쓴 낙찰방법 식별 문자열과 별표명을 그대로 노출합니다."""
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    method_name = raw_data.get("sucsfbidMthdNm") or "N/A"
    if rule_result.method_source == METHOD_SOURCE_CODE:
        method_code = raw_data.get("sucsfbidMthdCd")
        family = METHOD_FAMILY_BY_CODE.get(method_code or "", "N/A")
        method_name = f"{method_name}, 코드 {method_code} 에서 '{family}' 로 추정"
    if rule_result.rule is None:
        return f"낙찰방법: {method_name}"
    return f"낙찰방법 '{method_name}' → 별표 '{rule_result.rule.table_name}' 매칭"


def _blocked_response(
    bid: BidAnnouncement,
    rule_result: RuleResolutionResult,
    code: str,
    message: str,
) -> EvaluationResponse:
    """계산 차단은 500 이 아니라 사유가 적힌 정상 응답 상태로 전달됩니다."""
    return EvaluationResponse(
        status="blocked",
        rule_id=rule_result.rule.rule_id if rule_result.rule else None,
        rule_name=rule_result.rule.description if rule_result.rule else None,
        rule_basis=_rule_basis(bid, rule_result),
        negotiation_variant=rule_result.negotiation_variant,
        negotiation_tech_eval_rate=(
            float(rule_result.negotiation_tech_eval_rate)
            if rule_result.negotiation_tech_eval_rate is not None
            else None
        ),
        negotiation_price_eval_rate=(
            float(rule_result.negotiation_price_eval_rate)
            if rule_result.negotiation_price_eval_rate is not None
            else None
        ),
        blocked=True,
        blocked_reason=f"{code}: {message}",
        warnings=list(rule_result.warnings),
    )


def _model_provenance(
    payload: EvaluationRequest,
    request: Request,
    db: Session,
) -> ModelProvenance:
    """모델 출처는 predict_price_api 산출물을 그대로 전달합니다. 이 계층에서 합성하지 않습니다."""
    try:
        prediction = predict_price_api(
            PredictPriceRequest(
                bid_id=payload.bid_id,
                selected_model=payload.selected_model,
                user_price=str(payload.candidate_bid_amount),
            ),
            request,
            db,
        )
    except HTTPException as exc:
        return ModelProvenance(
            requested_model=payload.selected_model,
            actual_model=None,
            fallback_used=True,
            fallback_reason=f"예측 모델을 확인할 수 없습니다 ({exc.status_code}: {exc.detail})",
        )
    return ModelProvenance(
        requested_model=prediction.requested_model,
        actual_model=prediction.model_id,
        fallback_used=prediction.fallback_used,
        fallback_reason=prediction.fallback_reason,
    )


def _unscored_scenario_results(
    scenarios: list[ScenarioPrice],
    candidate_bid_amount: Decimal,
) -> list[ScenarioEvaluationResult]:
    """배점표 없이도 확정되는 시나리오 예정가격과 투찰률. 점수 계열은 계산하지 않았으므로 None 입니다."""
    return [
        ScenarioEvaluationResult(
            scenario_name=scenario.scenario_name,
            scenario_type=scenario.scenario_type,
            estimated_price=int(scenario.pred_price),
            bid_to_estimated_ratio=float(
                compute_price_ratio(candidate_bid_amount, scenario.pred_price)
            ),
            price_score=None,
            qualification_score=None,
            total_score=None,
            pass_threshold=None,
            is_qualified=None,
            warnings=[],
        )
        for scenario in scenarios
    ]


def _score_table_missing_response(
    bid: BidAnnouncement,
    payload: EvaluationRequest,
    rule_result: RuleResolutionResult,
    pred_price: Decimal,
    scenarios: list[ScenarioPrice],
    missing_fields: list[str],
    override_fields: list[str],
    quant_table: QuantScoreTable | None,
    band: QuantScoreBand | None,
    band_note: str | None,
    resolution: ScoreParamResolution,
) -> EvaluationResponse:
    """배점표 입력이 없어 점수는 계산하지 않습니다. 하한율과 시나리오 구간은 그대로 전달합니다."""
    assert rule_result.rule is not None
    assert rule_result.effective_lwlt_rate is not None
    rule = rule_result.rule
    effective_lwlt = rule_result.effective_lwlt_rate
    candidate_bid_amount = Decimal(str(payload.candidate_bid_amount))
    # 용역 적격심사는 A값을 적용하지 않습니다. 최저 투찰금액은 예정가격 * 하한율입니다.
    min_bid_result = calculate_min_bid_amount(
        pred_price=pred_price,
        lwlt_rate=effective_lwlt,
    )
    floor_note = (
        f"낙찰하한율 {min_bid_result.lwlt_rate_pct}% 적용 최저 투찰금액: "
        f"{int(min_bid_result.min_bid_amount):,}원"
    )

    labels = ", ".join(SCORE_TABLE_LABELS.get(name, name) for name in missing_fields)
    warnings = [
        *rule_result.warnings,
        *resolution.warnings,
        floor_note,
        "가격점수·종합점수·적격 판정·최저 투찰률 역산은 배점표를 입력한 뒤에 계산됩니다.",
        f"집중 미확인: 규칙이 확정하지 못한 배점표 항목({labels})은 공고문 적격심사 "
        "별표에서 확인해 입력해야 합니다.",
    ]
    if rule.score_table_source:
        warnings.append(f"배점표 근거: {rule.score_table_source}")
    return EvaluationResponse(
        status="blocked",
        rule_id=rule.rule_id,
        rule_name=rule.description,
        rule_basis=_rule_basis(bid, rule_result),
        blocked=True,
        blocked_reason=(
            f"{BLOCK_CODE_MISSING_SCORE_TABLE}: 공고문의 적격심사 배점표({labels})을 입력해야 "
            "점수를 계산할 수 있습니다."
        ),
        requested_model=payload.selected_model,
        actual_model=None,
        fallback_used=False,
        fallback_reason="점수 계산을 하지 않아 예측 모델을 호출하지 않았습니다.",
        lower_bound_rate=float(effective_lwlt),
        a_value_amount=None,
        min_bid_amount_with_a=None,
        scenario_results=_unscored_scenario_results(scenarios, candidate_bid_amount),
        score_table=_rule_score_table_payload(rule, missing_fields, override_fields, resolution),
        quant_score_table=(
            _quant_table_payload(quant_table, band, band_note) if quant_table is not None else None
        ),
        warnings=warnings,
    )


def _quant_violation_response(
    bid: BidAnnouncement,
    payload: EvaluationRequest,
    rule_result: RuleResolutionResult,
    pred_price: Decimal,
    scenarios: list[ScenarioPrice],
    quant_table: QuantScoreTable,
    band: QuantScoreBand,
    band_note: str | None,
    violations: list[tuple[str, str]],
) -> EvaluationResponse:
    """정량평가 입력이 배점표를 벗어나면 자르지 않고 사유와 함께 계산을 막습니다."""
    assert rule_result.rule is not None
    assert rule_result.effective_lwlt_rate is not None
    rule = rule_result.rule
    effective_lwlt = rule_result.effective_lwlt_rate
    candidate_bid_amount = Decimal(str(payload.candidate_bid_amount))
    min_bid_result = calculate_min_bid_amount(pred_price=pred_price, lwlt_rate=effective_lwlt)
    headline_code = violations[0][0]
    detail = " ".join(message for _, message in violations)
    warnings = [
        *rule_result.warnings,
        f"낙찰하한율 {min_bid_result.lwlt_rate_pct}% 적용 최저 투찰금액: "
        f"{int(min_bid_result.min_bid_amount):,}원",
        "정량평가 입력을 적용 별표 배점표와 대조해 계산을 막았습니다. 입력값을 고쳐 다시 실행하십시오.",
    ]
    return EvaluationResponse(
        status="blocked",
        rule_id=rule.rule_id,
        rule_name=rule.description,
        rule_basis=_rule_basis(bid, rule_result),
        blocked=True,
        blocked_reason=f"{headline_code}: {detail}",
        requested_model=payload.selected_model,
        actual_model=None,
        fallback_used=False,
        fallback_reason="정량평가 입력 검증에서 막혀 예측 모델을 호출하지 않았습니다.",
        lower_bound_rate=float(effective_lwlt),
        a_value_amount=None,
        min_bid_amount_with_a=None,
        scenario_results=_unscored_scenario_results(scenarios, candidate_bid_amount),
        score_table=_rule_score_table_payload(rule, [], []),
        quant_score_table=_quant_table_payload(quant_table, band, band_note),
        warnings=warnings,
    )


def _quant_band_unresolved_response(
    bid: BidAnnouncement,
    payload: EvaluationRequest,
    rule_result: RuleResolutionResult,
    pred_price: Decimal,
    scenarios: list[ScenarioPrice],
    quant_table: QuantScoreTable,
    band_note: str | None,
) -> EvaluationResponse:
    """추정가격 구간을 확정하지 못하면 임의 구간으로 계산하지 않고 막습니다."""
    assert rule_result.rule is not None
    assert rule_result.effective_lwlt_rate is not None
    rule = rule_result.rule
    effective_lwlt = rule_result.effective_lwlt_rate
    candidate_bid_amount = Decimal(str(payload.candidate_bid_amount))
    min_bid_result = calculate_min_bid_amount(pred_price=pred_price, lwlt_rate=effective_lwlt)
    reason = band_note or "추정가격 구간을 확정할 수 없습니다."
    warnings = [
        *rule_result.warnings,
        f"낙찰하한율 {min_bid_result.lwlt_rate_pct}% 적용 최저 투찰금액: "
        f"{int(min_bid_result.min_bid_amount):,}원",
        reason,
    ]
    return EvaluationResponse(
        status="blocked",
        rule_id=rule.rule_id,
        rule_name=rule.description,
        rule_basis=_rule_basis(bid, rule_result),
        blocked=True,
        blocked_reason=f"{BLOCK_CODE_QUANT_BAND_UNRESOLVED}: {reason}",
        requested_model=payload.selected_model,
        actual_model=None,
        fallback_used=False,
        fallback_reason="배점표 구간을 확정하지 못해 예측 모델을 호출하지 않았습니다.",
        lower_bound_rate=float(effective_lwlt),
        a_value_amount=None,
        min_bid_amount_with_a=None,
        scenario_results=_unscored_scenario_results(scenarios, candidate_bid_amount),
        score_table=_rule_score_table_payload(rule, [], []),
        quant_score_table=_quant_table_payload(quant_table, None, band_note),
        warnings=warnings,
    )


_PRICE_COMPENSATION_STATUS_LABELS: dict[str, str] = {
    "already_sufficient": "하한율로 이미 통과",
    "compensate": "입찰가격으로 보완",
    "impossible": "보완 불가",
}


def _price_compensation_guidance(result: PriceCompensationResult) -> str:
    """판정 상태별 안내 한 문장. P_req > B 사유와 그 밖의 불가 사유를 구분합니다."""
    if result.score_status == "already_sufficient":
        return "낙찰하한율 금액으로 이미 필요 가격점수를 충족합니다. 금액을 더 올리지 않습니다."
    if result.score_status == "compensate":
        return (
            "정량점수 부족분을 입찰가격으로 보완하려면 "
            "시나리오별 보완 금액 이상으로 투찰해야 합니다."
        )
    if result.p_req > result.max_price_score:
        return "가격점수 만점으로도 통과점수에 닿지 않습니다. 대수 투찰률은 투찰 권고가 아닙니다."
    return "기준비율 이하의 합법 금액으로는 필요 가격점수에 닿지 않습니다."


def _price_compensation_payload(result: PriceCompensationResult) -> PriceCompensation:
    """도메인 판정 결과를 지수 표기 없는 문자열·정수 JSON 으로 옮깁니다.

    점수·퍼센트는 format_decimal_plain, verified_price_ratio 는 4자리 고정 문자열,
    금액은 int 를 씁니다. float() 는 거치지 않습니다.
    """
    return PriceCompensation(
        score_status=result.score_status,
        score_status_label=_PRICE_COMPENSATION_STATUS_LABELS[result.score_status],
        amount_status=result.amount_status,
        floor_score_basis=result.floor_score_basis,
        pass_threshold=format_decimal_plain(result.pass_threshold),
        non_price_score=format_decimal_plain(result.non_price_score),
        p_req=format_decimal_plain(result.p_req),
        max_price_score=format_decimal_plain(result.max_price_score),
        score_gap=format_decimal_plain(result.score_gap),
        score_slack=(
            format_decimal_plain(result.score_slack) if result.score_slack is not None else None
        ),
        floor_price_score=(
            format_decimal_plain(result.floor_price_score)
            if result.floor_price_score is not None
            else None
        ),
        base_rate_percent=format_decimal_plain(result.base_rate_percent),
        announcement_lwlt_rate=format_decimal_plain(result.announcement_lwlt_rate_percent),
        calculated_rate_percent=format_decimal_plain(result.calculated_rate_percent),
        effective_rate_percent=format_decimal_plain(result.effective_rate_percent),
        binding_constraint=result.binding_constraint,
        score_floor_amount=(
            int(result.score_floor_amount) if result.score_floor_amount is not None else None
        ),
        guidance=_price_compensation_guidance(result),
        scenarios=[
            PriceCompensationScenario(
                scenario_name=row.scenario_name,
                scenario_type=row.scenario_type,
                estimated_price=int(row.estimated_price),
                row_status=row.row_status,
                verified_price_ratio=(
                    format(row.verified_price_ratio, "f")
                    if row.verified_price_ratio is not None
                    else None
                ),
                bid_rate_percent=(
                    format_decimal_plain(row.bid_rate_percent)
                    if row.bid_rate_percent is not None
                    else None
                ),
                verified_price_score=(
                    format_decimal_plain(row.verified_price_score)
                    if row.verified_price_score is not None
                    else None
                ),
                complement_bid_amount=(
                    int(row.complement_bid_amount)
                    if row.complement_bid_amount is not None
                    else None
                ),
                ratio_steps_raised=row.ratio_steps_raised,
                meets_p_req=row.meets_p_req,
            )
            for row in result.scenarios
        ],
    )


def _success_response(
    bid: BidAnnouncement,
    payload: EvaluationRequest,
    rule_result: RuleResolutionResult,
    table: ScoreTable,
    pred_price: Decimal,
    scenarios: list[ScenarioPrice],
    provenance: ModelProvenance,
    override_fields: list[str],
    quant_scores: QuantInputScores,
    quant_table: QuantScoreTable | None,
    band: QuantScoreBand | None,
    band_note: str | None,
    resolution: ScoreParamResolution,
) -> EvaluationResponse:
    """규칙 판별 결과와 evaluation_scoring 계산 결과를 응답 스키마로 담습니다."""
    assert rule_result.rule is not None
    assert rule_result.effective_lwlt_rate is not None
    rule = rule_result.rule
    effective_lwlt = rule_result.effective_lwlt_rate
    candidate_bid_amount = Decimal(str(payload.candidate_bid_amount))
    qualification = payload.qualification_input
    scores = _qualification_scores(quant_scores)
    non_price_score = scores[0] + scores[1] + scores[2]

    warnings = [*rule_result.warnings, *resolution.warnings]
    if provenance.actual_model is None:
        warnings.append(f"모델 출처를 확정할 수 없습니다. {provenance.fallback_reason}")
    if override_fields:
        override_labels = ", ".join(SCORE_TABLE_LABELS.get(name, name) for name in override_fields)
        warnings.append(f"사용자 입력이 규칙 선언 배점표를 덮어썼습니다: {override_labels}")

    # 용역 적격심사는 A값을 적용하지 않습니다. 최저 투찰금액은 예정가격 * 하한율입니다.
    min_bid_result = calculate_min_bid_amount(
        pred_price=pred_price,
        lwlt_rate=effective_lwlt,
    )
    warnings.append(
        f"낙찰하한율 {min_bid_result.lwlt_rate_pct}% 적용 최저 투찰금액: "
        f"{int(min_bid_result.min_bid_amount):,}원"
    )
    invert_result = invert_lowest_bid_rate(
        pass_threshold=table.pass_threshold,
        non_price_score=non_price_score,
        base_rate=table.base_rate,
        max_price_score=table.max_price_score,
        multiplier=table.multiplier,
        announcement_lwlt_rate=effective_lwlt,
    )
    warnings.extend(invert_result.warnings)

    compensation_result = resolve_price_compensation(
        pass_threshold=table.pass_threshold,
        non_price_score=non_price_score,
        base_rate=table.base_rate,
        max_price_score=table.max_price_score,
        multiplier=table.multiplier,
        announcement_lwlt_rate=effective_lwlt,
        reference_pred_price=pred_price,
        scenarios=[(s.scenario_name, s.scenario_type, s.pred_price) for s in scenarios],
    )
    for warning in compensation_result.warnings:
        if warning not in warnings:
            warnings.append(warning)

    return EvaluationResponse(
        status="success",
        rule_id=rule.rule_id,
        rule_name=rule.description,
        rule_basis=_rule_basis(bid, rule_result),
        blocked=False,
        requested_model=provenance.requested_model,
        actual_model=provenance.actual_model,
        fallback_used=provenance.fallback_used,
        fallback_reason=provenance.fallback_reason,
        base_rate=_as_percent(table.base_rate),
        lower_bound_rate=float(effective_lwlt),
        a_value_amount=None,
        min_bid_amount_with_a=None,
        min_possible_bid_rate=float(invert_result.effective_rate_pct),
        scenario_results=[
            _evaluate_scenario(
                scenario=scenario,
                candidate_bid_amount=candidate_bid_amount,
                scores=scores,
                qualification=qualification,
                table=table,
                has_labor_item=quant_scores.has_labor_item,
            )
            for scenario in scenarios
        ],
        price_compensation=_price_compensation_payload(compensation_result),
        score_table=_rule_score_table_payload(rule, [], override_fields, resolution),
        quant_score_table=(
            _quant_table_payload(quant_table, band, band_note) if quant_table is not None else None
        ),
        warnings=warnings,
    )


def _save_snapshot_async(
    db: Session,
    user_id: int,
    bid_id: int,
    rule_id: str,
    model_id: str,
    model_version: str,
    input_json: dict[str, Any],
    result_json: dict[str, Any],
    evidence_items: list[EvidenceMetadata],
    contract_regime: str | None = None,
    institution_code: str | None = None,
    institution_name: str | None = None,
    region_code: str | None = None,
    region_name: str | None = None,
) -> BidEvaluationSnapshot | None:
    """분석 스냅샷 저장. 실패해도 분석 응답을 막지 않고 로그만 남김."""
    try:
        snapshot = BidEvaluationSnapshot(
            bid_id=bid_id,
            user_id=user_id,
            rule_id=rule_id,
            contract_regime=contract_regime,
            institution_code=institution_code,
            institution_name=institution_name,
            region_code=region_code,
            region_name=region_name,
            model_id=model_id,
            model_version=model_version,
            input_json=input_json,
            result_json=result_json,
        )
        db.add(snapshot)
        db.flush()  # ID 확보

        # 증빙 메타데이터 저장
        for evidence in evidence_items:
            evidence_obj = BidEvaluationEvidence(
                snapshot_id=snapshot.id,
                item_code=evidence.item_code,
                issuer=evidence.issuer,
                reference_no=evidence.reference_no,
                valid_from=evidence.valid_from,
                valid_to=evidence.valid_to,
                note=evidence.note,
            )
            db.add(evidence_obj)

        db.commit()
        db.refresh(snapshot)
        return snapshot
    except Exception as exc:
        logger.warning("분석 스냅샷 저장 실패 (응답은 정상 반환): %s", exc)
        db.rollback()
        return None


# =============================================================================
# 통합 분석 엔드포인트
# =============================================================================


def _analyze_bid(
    bid: BidAnnouncement,
    payload: EvaluationRequest,
    request: Request,
    db: Session,
    institution: G2BDemandInstitution | None = None,
    institution_loaded: bool = False,
) -> EvaluationResponse:
    """규칙 판별과 점수 계산을 도메인 모듈에 위임한 채 분석 응답을 조립합니다.

    판별은 evaluation_rules, 계산은 evaluation_scoring, 모델 출처는 predict_price_api 가 정본이며,
    그들이 값을 주지 못하는 구간은 추측하지 않고 차단합니다.
    """
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    if not institution_loaded:
        institution = _demand_institution_for_bid(db, bid)
    institution_regime = classify_contract_regime(institution)
    region_code, region_name = institution_region(institution)
    rule_result = resolve_evaluation_rule_from_raw_data(
        category=bid.category,
        raw_data=raw_data,
        institution_name_fallback=bid.dminstt_nm,
        cntrct_mthd_nm=bid.cntrct_mthd_nm,
        institution_regime=institution_regime,
        region_code=region_code,
        region_name=region_name,
    )
    if rule_result.is_blocked:
        response = _blocked_response(
            bid,
            rule_result,
            str(rule_result.block_reason_code),
            rule_result.block_reason_message or "계산 조건을 충족하지 않았습니다.",
        )
        if rule_result.negotiation_variant is not None:
            response.negotiation_rate_distribution = NegotiationRateDistribution(
                **get_negotiation_stats(db, rule_result.negotiation_variant)
            )
        return response

    assert rule_result.rule is not None
    rule = rule_result.rule

    pred_price = _announcement_pred_price(bid)
    if pred_price is None:
        return _blocked_response(
            bid,
            rule_result,
            BLOCK_CODE_PRED_PRICE_UNAVAILABLE,
            "공고에 예정가격(기초금액)이 공개되지 않아 최저 투찰금액과 시나리오를 계산할 분모가 없습니다.",
        )

    scenarios = _scenario_prices(bid, payload.price_scenarios, institution_regime)

    # 정량평가 입력은 적용 별표의 선언 배점표로 검증합니다. 배점표가 없는 규칙(별표 귀속
    # 미확인 일반 띠)은 항목을 검증할 수 없어 값을 받지 않습니다.
    quant_table = quant_score_table_for_rule(rule)
    band: QuantScoreBand | None = None
    band_note: str | None = None
    if quant_table is None:
        if any(
            _quant_value(value) != Decimal("0")
            for value in payload.qualification_input.quant_items.values()
        ):
            return _blocked_response(
                bid,
                rule_result,
                BLOCK_CODE_QUANT_ITEM_NOT_IN_TABLE,
                "적용 별표의 귀속이 미확인이라 정량평가 입력 항목을 검증할 수 없습니다.",
            )
    else:
        band, band_note = select_quant_band(quant_table, _bid_estimated_price(bid))
        if band is None:
            return _quant_band_unresolved_response(
                bid, payload, rule_result, pred_price, scenarios, quant_table, band_note
            )

    quant_scores = QuantInputScores(
        performance=Decimal("0"),
        labor_plan=Decimal("0"),
        reputation=Decimal("0"),
        has_labor_item=False,
    )
    if quant_table is not None and band is not None:
        resolved, violations = _resolve_quant_inputs(payload.qualification_input, quant_table, band)
        if resolved is None:
            return _quant_violation_response(
                bid,
                payload,
                rule_result,
                pred_price,
                scenarios,
                quant_table,
                band,
                band_note,
                violations,
            )
        quant_scores = resolved

    table, missing_fields, override_fields, resolution = _score_table(
        payload.qualification_input, rule, bid
    )
    if table is None:
        return _score_table_missing_response(
            bid=bid,
            payload=payload,
            rule_result=rule_result,
            pred_price=pred_price,
            scenarios=scenarios,
            missing_fields=missing_fields,
            override_fields=override_fields,
            quant_table=quant_table,
            band=band,
            band_note=band_note,
            resolution=resolution,
        )

    return _success_response(
        bid=bid,
        payload=payload,
        rule_result=rule_result,
        table=table,
        pred_price=pred_price,
        scenarios=scenarios,
        provenance=_model_provenance(payload, request, db),
        override_fields=override_fields,
        quant_scores=quant_scores,
        quant_table=quant_table,
        band=band,
        band_note=band_note,
        resolution=resolution,
    )


@router.post("/analyze", response_model=EvaluationResponse, summary="적격심사 정량평가 통합 분석")
def analyze_evaluation(
    payload: EvaluationRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
) -> EvaluationResponse:
    """
    적격심사 정량평가 및 투찰 금액 통합 분석.

    서버가 다음을 한 번에 수행:
    1. 공고 조회 (bid_id)
    2. 적격심사 규칙 판별 (category, 낙찰방법, 하한율 등)
    3. 가격점수, 낙찰하한율 기준 최저 투찰금액, 최저 투찰률 역산 계산
    4. 복수예가 시나리오별 종합 평가
    5. 분석 성공 시 스냅샷 저장 (실패해도 응답은 정상 반환)

    소유권: 요청 사용자 본인만 접근 가능 (인증된 사용자에서 user_id 추출).
    """
    bid = _get_bid_or_404(db, payload.bid_id)
    institution = _demand_institution_for_bid(db, bid)
    response = _analyze_bid(bid, payload, request, db, institution, institution_loaded=True)

    # 차단된 경우도 스냅샷으로 남깁니다. 저장 실패가 응답을 막지는 못합니다.
    if response.status in ("success", "blocked"):
        raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
        institution_regime = classify_contract_regime(institution)
        region_code, region_name = institution_region(institution)
        rule_context = resolve_evaluation_rule_from_raw_data(
            category=bid.category,
            raw_data=raw_data,
            institution_name_fallback=bid.dminstt_nm,
            cntrct_mthd_nm=bid.cntrct_mthd_nm,
            institution_regime=institution_regime,
            region_code=region_code,
            region_name=region_name,
        )
        input_json = {
            "bid_id": payload.bid_id,
            "selected_model": payload.selected_model,
            "candidate_bid_amount": payload.candidate_bid_amount,
            "qualification_input": payload.qualification_input.model_dump(mode="json"),
            "price_scenarios": (
                [s.model_dump(mode="json") for s in payload.price_scenarios]
                if payload.price_scenarios
                else None
            ),
        }
        _save_snapshot_async(
            db=db,
            user_id=user.id,
            bid_id=bid.id,
            rule_id=response.rule_id or "BLOCKED",
            model_id=response.actual_model or "unknown",
            model_version="1.0",
            input_json=input_json,
            result_json=response.model_dump(mode="json"),
            evidence_items=[],  # 증빙은 별도 API로 관리
            contract_regime=rule_context.contract_regime,
            institution_code=rule_context.institution_code,
            institution_name=rule_context.institution_name,
            region_code=rule_context.region_code,
            region_name=rule_context.region_name,
        )

    return response


# =============================================================================
# 별표 규칙 메타 엔드포인트
# =============================================================================

# 산식 카드의 별표 표를 채우는 메타. 규칙 값은 evaluation_rules.py 가 유일한 정본이며
# 이 계층은 값을 만들지 않고 직렬화만 합니다. 기관별·지역별 산식은 아직 코드에 없어,
# 목록에 없는 산식이 있는 것처럼 보이지 않게 범위를 응답에 명시합니다.
SERVC_RULE_META_SCOPE_NOTE = (
    "기관별·지역별 산식은 아직 코드에 없습니다. 이 목록은 조달청 일반용역 적격심사 별표 "
    "14종만 포함하며, 그 밖의 산식이 있는 것으로 해석해서는 안 됩니다."
)


def _serialize_rule_meta(rule: EvaluationRule) -> dict[str, str | None]:
    """규칙 객체를 산식 표 여섯 열과 식별자, 그리고 선언 배점표로 옮깁니다.

    기준비율·낙찰하한율과 배점표(B·k·T)는 float 를 거치지 않고 format_decimal_plain
    문자열로 내거나, 규칙이 확정하지 못한 값은 null 로 냅니다. float 로 바꾸면 표시에
    반올림 오차가 생깁니다.
    """
    return {
        "rule_id": rule.rule_id,
        "service_type": rule.service_type,
        "table_name": rule.table_name,
        "description": rule.description,
        "effective_date": rule.effective_date,
        "source": rule.source,
        "base_rate": format_decimal_plain(rule.base_rate),
        "lwlt_rate": format_decimal_plain(rule.lwlt_rate),
        "max_price_score": (
            format_decimal_plain(rule.max_price_score) if rule.max_price_score is not None else None
        ),
        "multiplier": (
            format_decimal_plain(rule.multiplier) if rule.multiplier is not None else None
        ),
        "pass_threshold": (
            format_decimal_plain(rule.pass_threshold) if rule.pass_threshold is not None else None
        ),
        "score_table_source": rule.score_table_source,
    }


@router.get("/rules", summary="일반용역 적격심사 별표 규칙 메타 목록")
def list_evaluation_rules_meta(
    bid_id: int | None = None,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """산식 카드의 별표 표를 채울 조달청 일반용역 적격심사 별표 14종 메타를 돌려줍니다.

    값은 evaluation_rules.py 의 현행 규칙 상수에서 그대로 읽습니다. 여기서 값을 만들지 않습니다.
    기관별·지역별 산식은 아직 코드에 없어 목록에 넣지 않고 scope_note 로 그 사실을 알립니다.
    bid_id 가 주어지면 그 공고에 매칭된 별표를 matched_rule 로 함께 돌려주고, 매칭되지
    않으면 null 로 두고 목록만 돌려줍니다. 규칙은 공개 정보라 인증을 요구하지 않습니다.
    """
    matched_rule: dict[str, str | None] | None = None
    if bid_id is not None:
        bid = _get_bid_or_404(db, bid_id)
        raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
        institution = _demand_institution_for_bid(db, bid)
        institution_regime = classify_contract_regime(institution)
        region_code, region_name = institution_region(institution)
        resolution = resolve_evaluation_rule_from_raw_data(
            category=bid.category,
            raw_data=raw_data,
            institution_name_fallback=bid.dminstt_nm,
            cntrct_mthd_nm=bid.cntrct_mthd_nm,
            institution_regime=institution_regime,
            region_code=region_code,
            region_name=region_name,
        )
        matched = resolution.rule
        if matched is not None:
            matched_rule = _serialize_rule_meta(matched)

    return {
        "scope_note": SERVC_RULE_META_SCOPE_NOTE,
        "rules": [_serialize_rule_meta(rule) for rule in POST_20260727_RULES],
        "matched_rule": matched_rule,
    }


# =============================================================================
# 프로필 CRUD
# =============================================================================


@router.get(
    "/profiles", response_model=list[EvaluationProfileResponse], summary="내 평가 프로필 목록"
)
def list_evaluation_profiles(
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """로그인한 사용자의 적격심사 정량평가 프로필 목록을 조회합니다."""
    profiles = (
        db.execute(
            select(BidEvaluationProfile)
            .where(BidEvaluationProfile.user_id == user.id)
            .order_by(BidEvaluationProfile.created_at.desc())
        )
        .scalars()
        .all()
    )

    return [
        EvaluationProfileResponse(
            id=p.id,
            user_id=p.user_id,
            name=p.name,
            framework=p.framework,
            input_schema_version=p.input_schema_version,
            input_json=p.input_json,
            created_at=p.created_at,
            updated_at=p.updated_at,
        )
        for p in profiles
    ]


@router.post(
    "/profiles",
    response_model=EvaluationProfileResponse,
    status_code=201,
    summary="평가 프로필 생성",
)
def create_evaluation_profile(
    payload: EvaluationProfileCreate,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """새 평가 프로필을 생성합니다. 동일 사용자 내 프로필명은 유일해야 합니다."""
    # 동일명 중복 검사
    existing = db.execute(
        select(BidEvaluationProfile).where(
            BidEvaluationProfile.user_id == user.id,
            BidEvaluationProfile.name == payload.name,
        )
    ).scalar_one_or_none()
    if existing:
        raise HTTPException(status_code=409, detail="이미 사용 중인 프로필명입니다.")

    profile = BidEvaluationProfile(
        user_id=user.id,
        name=payload.name,
        framework=payload.framework,
        input_schema_version=payload.input_schema_version,
        input_json=payload.input_json,
    )
    db.add(profile)
    db.commit()
    db.refresh(profile)

    return EvaluationProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        name=profile.name,
        framework=profile.framework,
        input_schema_version=profile.input_schema_version,
        input_json=profile.input_json,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.get(
    "/profiles/{profile_id}", response_model=EvaluationProfileResponse, summary="평가 프로필 상세"
)
def get_evaluation_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """내 프로필 하나를 조회합니다. 타 사용자 프로필은 404로 차단합니다."""
    profile = _get_profile_or_404(db, profile_id, user.id)
    return EvaluationProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        name=profile.name,
        framework=profile.framework,
        input_schema_version=profile.input_schema_version,
        input_json=profile.input_json,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.put(
    "/profiles/{profile_id}", response_model=EvaluationProfileResponse, summary="평가 프로필 수정"
)
def update_evaluation_profile(
    profile_id: int,
    payload: EvaluationProfileUpdate,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """내 프로필을 수정합니다. 타 사용자 프로필은 404로 차단합니다."""
    profile = _get_profile_or_404(db, profile_id, user.id)

    if payload.name is not None:
        # 변경하려는 이름이 다른 내 프로필과 중복되는지 확인
        existing = db.execute(
            select(BidEvaluationProfile).where(
                BidEvaluationProfile.user_id == user.id,
                BidEvaluationProfile.name == payload.name,
                BidEvaluationProfile.id != profile_id,
            )
        ).scalar_one_or_none()
        if existing:
            raise HTTPException(status_code=409, detail="이미 사용 중인 프로필명입니다.")
        profile.name = payload.name

    if payload.framework is not None:
        profile.framework = payload.framework
    if payload.input_schema_version is not None:
        profile.input_schema_version = payload.input_schema_version
    if payload.input_json is not None:
        profile.input_json = payload.input_json

    db.commit()
    db.refresh(profile)

    return EvaluationProfileResponse(
        id=profile.id,
        user_id=profile.user_id,
        name=profile.name,
        framework=profile.framework,
        input_schema_version=profile.input_schema_version,
        input_json=profile.input_json,
        created_at=profile.created_at,
        updated_at=profile.updated_at,
    )


@router.delete("/profiles/{profile_id}", status_code=204, summary="평가 프로필 삭제")
def delete_evaluation_profile(
    profile_id: int,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """내 프로필을 삭제합니다. 타 사용자 프로필은 404로 차단합니다."""
    profile = _get_profile_or_404(db, profile_id, user.id)
    db.delete(profile)
    db.commit()
    return None


# =============================================================================
# 스냅샷 CRUD
# =============================================================================


@router.get(
    "/snapshots", response_model=list[EvaluationSnapshotResponse], summary="내 분석 스냅샷 목록"
)
def list_evaluation_snapshots(
    bid_id: int | None = None,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """로그인한 사용자의 분석 스냅샷 목록을 조회합니다. bid_id로 필터링 가능."""
    query = (
        select(BidEvaluationSnapshot)
        .options(selectinload(BidEvaluationSnapshot.evidence_items))
        .where(BidEvaluationSnapshot.user_id == user.id)
    )
    if bid_id is not None:
        query = query.where(BidEvaluationSnapshot.bid_id == bid_id)
    query = query.order_by(BidEvaluationSnapshot.created_at.desc())

    snapshots = db.execute(query).scalars().all()

    return [
        EvaluationSnapshotResponse(
            id=s.id,
            bid_id=s.bid_id,
            user_id=s.user_id,
            rule_id=s.rule_id,
            model_id=s.model_id,
            model_version=s.model_version,
            input_json=s.input_json,
            result_json=s.result_json,
            created_at=s.created_at,
            evidence_items=[
                EvidenceMetadata(
                    item_code=e.item_code,
                    issuer=e.issuer,
                    reference_no=e.reference_no,
                    valid_from=e.valid_from,
                    valid_to=e.valid_to,
                    note=e.note,
                )
                for e in s.evidence_items
            ],
        )
        for s in snapshots
    ]


@router.post(
    "/snapshots",
    response_model=EvaluationSnapshotResponse,
    status_code=201,
    summary="분석 스냅샷 저장",
)
def create_evaluation_snapshot(
    payload: EvaluationSnapshotCreate,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """분석 스냅샷을 직접 저장합니다. (통합 분석 API가 자동 저장하므로 보통은 불필요)"""
    # 공고 존재 확인
    _get_bid_or_404(db, payload.bid_id)

    snapshot = BidEvaluationSnapshot(
        bid_id=payload.bid_id,
        user_id=user.id,
        rule_id=payload.rule_id,
        model_id=payload.model_id,
        model_version=payload.model_version,
        input_json=payload.input_json,
        result_json=payload.result_json,
    )
    db.add(snapshot)
    db.flush()

    for evidence in payload.evidence_items:
        evidence_obj = BidEvaluationEvidence(
            snapshot_id=snapshot.id,
            item_code=evidence.item_code,
            issuer=evidence.issuer,
            reference_no=evidence.reference_no,
            valid_from=evidence.valid_from,
            valid_to=evidence.valid_to,
            note=evidence.note,
        )
        db.add(evidence_obj)

    db.commit()
    db.refresh(snapshot)

    return EvaluationSnapshotResponse(
        id=snapshot.id,
        bid_id=snapshot.bid_id,
        user_id=snapshot.user_id,
        rule_id=snapshot.rule_id,
        model_id=snapshot.model_id,
        model_version=snapshot.model_version,
        input_json=snapshot.input_json,
        result_json=snapshot.result_json,
        created_at=snapshot.created_at,
        evidence_items=[
            EvidenceMetadata(
                item_code=e.item_code,
                issuer=e.issuer,
                reference_no=e.reference_no,
                valid_from=e.valid_from,
                valid_to=e.valid_to,
                note=e.note,
            )
            for e in snapshot.evidence_items
        ],
    )


@router.get(
    "/snapshots/{snapshot_id}",
    response_model=EvaluationSnapshotResponse,
    summary="분석 스냅샷 상세",
)
def get_evaluation_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """내 스냅샷 하나를 조회합니다. 타 사용자 스냅샷은 404로 차단합니다."""
    snapshot = _get_snapshot_or_404(db, snapshot_id, user.id)
    return EvaluationSnapshotResponse(
        id=snapshot.id,
        bid_id=snapshot.bid_id,
        user_id=snapshot.user_id,
        rule_id=snapshot.rule_id,
        model_id=snapshot.model_id,
        model_version=snapshot.model_version,
        input_json=snapshot.input_json,
        result_json=snapshot.result_json,
        created_at=snapshot.created_at,
        evidence_items=[
            EvidenceMetadata(
                item_code=e.item_code,
                issuer=e.issuer,
                reference_no=e.reference_no,
                valid_from=e.valid_from,
                valid_to=e.valid_to,
                note=e.note,
            )
            for e in snapshot.evidence_items
        ],
    )


@router.delete("/snapshots/{snapshot_id}", status_code=204, summary="분석 스냅샷 삭제")
def delete_evaluation_snapshot(
    snapshot_id: int,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
    """내 스냅샷을 삭제합니다. 타 사용자 스냅샷은 404로 차단합니다."""
    snapshot = _get_snapshot_or_404(db, snapshot_id, user.id)
    db.delete(snapshot)
    db.commit()
    return None
