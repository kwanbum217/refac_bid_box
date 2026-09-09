"""
src/app/api/v1/evaluations.py

일반용역 적격심사 정량평가 통합 분석 API 및 프로필/스냅샷 CRUD.

| 기능 | 엔드포인트 |
| --- | --- |
| 통합 분석 | POST /api/v1/evaluations/analyze |
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
가격배점한도(B)·평점계수(k)·통과점수(T) 는 규칙 레지스트리가 실측으로 확정하지 않은 값이라
사용자가 공고문 배점표로 입력하며, 입력이 없으면 추측 대신 점수 계산만 차단합니다.

차단 코드:
- 규칙 판별 차단 (evaluation_rules): NOT_SERVC, NON_PRED_PRICE, MANUAL_EVALUATION, RULE_NOT_FOUND
- 입력·데이터 부족 차단 (본 파일): MISSING_SCORE_TABLE, PRED_PRICE_UNAVAILABLE
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.api.v1.accounts import require_current_user
from src.app.api.v1.predictions import predict_price_api
from src.app.core.db import get_db
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.models.evaluations import (
    BidEvaluationEvidence,
    BidEvaluationProfile,
    BidEvaluationSnapshot,
)
from src.app.schemas.evaluations import (
    EvaluationProfileCreate,
    EvaluationProfileResponse,
    EvaluationProfileUpdate,
    EvaluationRequest,
    EvaluationResponse,
    EvaluationSnapshotCreate,
    EvaluationSnapshotResponse,
    EvidenceMetadata,
    PriceScenarioConfig,
    QualificationInput,
    ScenarioEvaluationResult,
)
from src.app.schemas.predictions import PredictPriceRequest
from src.app.services.evaluation_rules import (
    EvaluationRule,
    RuleResolutionResult,
    resolve_evaluation_rule_from_raw_data,
)
from src.app.services.evaluation_scoring import (
    calculate_min_bid_amount,
    calculate_price_score,
    compute_price_ratio,
    evaluate_qualification,
    generate_pred_price_scenarios,
    invert_lowest_bid_rate,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/evaluations", tags=["Evaluations"])


# =============================================================================
# 헬퍼 함수
# =============================================================================

# 규칙 레지스트리는 별표 식별 문자열과 낙찰하한율만 실측으로 확정했습니다.
# 가격배점한도(B)·평점계수(k)·통과점수(T) 는 별표마다 다르고 공고 데이터에 없으므로
# 사용자가 공고문 배점표를 입력합니다. 이 계층은 세 값을 추측하지 않습니다.
SCORE_TABLE_LABELS: dict[str, str] = {
    "max_price_score": "가격배점한도",
    "multiplier": "평점계수",
    "pass_threshold": "통과점수",  # nosec B105 - 배점표 항목의 한국어 표기이지 비밀번호가 아닙니다
}

# 공고 raw_data 안에서 A값(국민연금·건강보험 등 합산액)이 노출되는 필드명입니다.
A_VALUE_RAW_KEYS: tuple[str, ...] = ("a_value", "aValue", "A값", "nonBidCost", "non_bid_cost")

# 규칙 판별(도메인)이 아니라 입력·데이터 부족으로 계산을 멈추는 코드입니다.
BLOCK_CODE_MISSING_SCORE_TABLE = "MISSING_SCORE_TABLE"
BLOCK_CODE_PRED_PRICE_UNAVAILABLE = "PRED_PRICE_UNAVAILABLE"


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
) -> tuple[ScoreTable | None, list[str]]:
    """가격점수에 필요한 배점표 파라미터를 사용자 입력에서 읽습니다.

    가격배점한도·평점계수·통과점수는 규칙 레지스트리가 실측으로 확정하지 못한 값이라
    공고문 배점표에서 읽은 사용자 입력이 정본입니다. 하나라도 없으면 추측하지 않고
    결측 필드명만 돌려 점수 계산을 차단합니다. 기준비율은 규칙 객체의 선언값을 씁니다.
    """
    supplied: dict[str, float | None] = {
        "max_price_score": qualification.max_price_score,
        "multiplier": qualification.multiplier,
        "pass_threshold": qualification.pass_threshold,
    }
    resolved: dict[str, Decimal] = {}
    missing: list[str] = []
    for field_name, value in supplied.items():
        if value is None:
            missing.append(field_name)
        else:
            resolved[field_name] = Decimal(str(value))
    if missing:
        return None, missing

    return (
        ScoreTable(
            max_price_score=resolved["max_price_score"],
            multiplier=resolved["multiplier"],
            pass_threshold=resolved["pass_threshold"],
            base_rate=rule.base_rate,
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


def _is_local_contract(bid: BidAnnouncement) -> bool:
    """계약 방법 명칭에서 지방계약 여부를 판단합니다 (복수예가 변동 범위 선택용)."""
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    methods = f"{raw_data.get('cntrctCnclsMthdNm') or ''} {bid.cntrct_mthd_nm or ''}"
    return "지방" in methods


def _scenario_prices(
    bid: BidAnnouncement,
    request_scenarios: list[PriceScenarioConfig] | None,
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
    is_local = _is_local_contract(bid)
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


def _extract_a_value(bid: BidAnnouncement) -> Decimal | None:
    """공고 raw_data 에 노출된 A값(국민연금·건강보험 등 합산액) 필드를 읽습니다."""
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    for key in A_VALUE_RAW_KEYS:
        raw_value = raw_data.get(key)
        if raw_value is None:
            continue
        try:
            value = Decimal(str(raw_value))
        except (ArithmeticError, TypeError, ValueError):
            logger.debug("A값 필드 변환 실패: key=%s", key)
            continue
        if value > Decimal("0"):
            return value
    return None


def _qualification_scores(
    qualification: QualificationInput,
) -> tuple[Decimal, Decimal, Decimal]:
    """설계서 4.5 정의대로 사용자 입력을 수행능력(실적+경영상태), 근로조건, 신인도로 나눕니다."""
    performance = Decimal(str(qualification.performance_score)) + Decimal(
        str(qualification.management_score)
    )
    labor = Decimal(str(qualification.labor_plan_score))
    credibility = Decimal(str(qualification.credibility_score))
    return performance, labor, credibility


def _as_percent(value: Decimal) -> float:
    """비율을 응답 스키마가 요구하는 퍼센트 숫자로 바꿉니다."""
    return float(value * Decimal("100")) if value <= Decimal("1") else float(value)


def _evaluate_scenario(
    scenario: ScenarioPrice,
    candidate_bid_amount: Decimal,
    scores: tuple[Decimal, Decimal, Decimal],
    qualification: QualificationInput,
    table: ScoreTable,
) -> ScenarioEvaluationResult:
    """단일 시나리오의 가격점수와 적격 판정을 evaluation_scoring 에 위임합니다."""
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
        warnings=list(judgement.warnings),
    )


def _rule_basis(bid: BidAnnouncement, rule_result: RuleResolutionResult) -> str:
    """규칙 판별 근거. 매칭에 쓴 낙찰방법 식별 문자열과 별표명을 그대로 노출합니다."""
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    method_name = raw_data.get("sucsfbidMthdNm") or "N/A"
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
) -> EvaluationResponse:
    """배점표 입력이 없어 점수는 계산하지 않습니다. 하한율·A값·시나리오 구간은 그대로 전달합니다."""
    assert rule_result.rule is not None
    assert rule_result.effective_lwlt_rate is not None
    rule = rule_result.rule
    effective_lwlt = rule_result.effective_lwlt_rate
    candidate_bid_amount = Decimal(str(payload.candidate_bid_amount))
    a_value = _extract_a_value(bid)
    min_bid_result = calculate_min_bid_amount(
        pred_price=pred_price,
        lwlt_rate=effective_lwlt,
        a_value=a_value,
    )
    if min_bid_result.has_a_value:
        floor_note = f"A값 반영 최저 투찰금액: {int(min_bid_result.min_bid_amount):,}원"
    else:
        floor_note = (
            f"낙찰하한율 {min_bid_result.lwlt_rate_pct}% 적용 최저 투찰금액: "
            f"{int(min_bid_result.min_bid_amount):,}원"
        )

    labels = ", ".join(SCORE_TABLE_LABELS.get(name, name) for name in missing_fields)
    warnings = [
        *rule_result.warnings,
        floor_note,
        "가격점수·종합점수·적격 판정·최저 투찰률 역산은 배점표를 입력한 뒤에 계산됩니다.",
    ]
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
        a_value_amount=int(a_value) if a_value is not None else None,
        min_bid_amount_with_a=(
            int(min_bid_result.min_bid_amount) if min_bid_result.has_a_value else None
        ),
        scenario_results=_unscored_scenario_results(scenarios, candidate_bid_amount),
        warnings=warnings,
    )


def _success_response(
    bid: BidAnnouncement,
    payload: EvaluationRequest,
    rule_result: RuleResolutionResult,
    table: ScoreTable,
    pred_price: Decimal,
    scenarios: list[ScenarioPrice],
    provenance: ModelProvenance,
) -> EvaluationResponse:
    """규칙 판별 결과와 evaluation_scoring 계산 결과를 응답 스키마로 담습니다."""
    assert rule_result.rule is not None
    assert rule_result.effective_lwlt_rate is not None
    rule = rule_result.rule
    effective_lwlt = rule_result.effective_lwlt_rate
    candidate_bid_amount = Decimal(str(payload.candidate_bid_amount))
    qualification = payload.qualification_input
    scores = _qualification_scores(qualification)
    non_price_score = scores[0] + scores[1] + scores[2]
    a_value = _extract_a_value(bid)

    warnings = list(rule_result.warnings)
    if provenance.actual_model is None:
        warnings.append(f"모델 출처를 확정할 수 없습니다. {provenance.fallback_reason}")

    min_bid_result = calculate_min_bid_amount(
        pred_price=pred_price,
        lwlt_rate=effective_lwlt,
        a_value=a_value,
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
        a_value_amount=int(a_value) if a_value is not None else None,
        min_bid_amount_with_a=(
            int(min_bid_result.min_bid_amount) if min_bid_result.has_a_value else None
        ),
        min_possible_bid_rate=float(invert_result.effective_rate_pct),
        scenario_results=[
            _evaluate_scenario(
                scenario=scenario,
                candidate_bid_amount=candidate_bid_amount,
                scores=scores,
                qualification=qualification,
                table=table,
            )
            for scenario in scenarios
        ],
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
) -> BidEvaluationSnapshot | None:
    """분석 스냅샷 저장. 실패해도 분석 응답을 막지 않고 로그만 남김."""
    try:
        snapshot = BidEvaluationSnapshot(
            bid_id=bid_id,
            user_id=user_id,
            rule_id=rule_id,
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
) -> EvaluationResponse:
    """규칙 판별과 점수 계산을 도메인 모듈에 위임한 채 분석 응답을 조립합니다.

    판별은 evaluation_rules, 계산은 evaluation_scoring, 모델 출처는 predict_price_api 가 정본이며,
    그들이 값을 주지 못하는 구간은 추측하지 않고 차단합니다.
    """
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    rule_result = resolve_evaluation_rule_from_raw_data(
        category=bid.category,
        raw_data=raw_data,
    )
    if rule_result.is_blocked:
        return _blocked_response(
            bid,
            rule_result,
            str(rule_result.block_reason_code),
            rule_result.block_reason_message or "계산 조건을 충족하지 않았습니다.",
        )

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

    scenarios = _scenario_prices(bid, payload.price_scenarios)

    table, missing_fields = _score_table(payload.qualification_input, rule)
    if table is None:
        return _score_table_missing_response(
            bid=bid,
            payload=payload,
            rule_result=rule_result,
            pred_price=pred_price,
            scenarios=scenarios,
            missing_fields=missing_fields,
        )

    return _success_response(
        bid=bid,
        payload=payload,
        rule_result=rule_result,
        table=table,
        pred_price=pred_price,
        scenarios=scenarios,
        provenance=_model_provenance(payload, request, db),
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
    3. 가격점수, A값 반영 최저 투찰금액, 최저 투찰률 역산 계산
    4. 복수예가 시나리오별 종합 평가
    5. 분석 성공 시 스냅샷 저장 (실패해도 응답은 정상 반환)

    소유권: 요청 사용자 본인만 접근 가능 (인증된 사용자에서 user_id 추출).
    """
    bid = _get_bid_or_404(db, payload.bid_id)
    response = _analyze_bid(bid, payload, request, db)

    # 차단된 경우도 스냅샷으로 남깁니다. 저장 실패가 응답을 막지는 못합니다.
    if response.status in ("success", "blocked"):
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
        )

    return response


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
    query = select(BidEvaluationSnapshot).where(BidEvaluationSnapshot.user_id == user.id)
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
