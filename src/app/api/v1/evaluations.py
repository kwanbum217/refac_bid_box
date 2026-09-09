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
"""

from __future__ import annotations

import logging
from decimal import Decimal
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.api.v1.accounts import require_current_user
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
    ScenarioEvaluationResult,
)
from src.app.services.evaluation_rules import (
    RuleResolutionResult,
    resolve_evaluation_rule_from_raw_data,
)
from src.app.services.evaluation_scoring import (
    InvertRateResult,
    MinBidAmountResult,
    PredPriceScenariosResult,
    PriceScoreResult,
    QualificationResult,
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


def _resolve_rule_and_build_warnings(
    bid: BidAnnouncement,
) -> tuple[RuleResolutionResult, list[str]]:
    """공고 raw_data에서 규칙을 판별하고 경고 목록을 구성."""
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    result = resolve_evaluation_rule_from_raw_data(
        category=bid.category,
        raw_data=raw_data,
    )
    return result, result.warnings


def _build_price_scenarios(
    bid: BidAnnouncement,
    request_scenarios: list[PriceScenarioConfig] | None,
    rule_result: RuleResolutionResult,
) -> list[PredPriceScenariosResult]:
    """복수예가 시나리오 구성. 요청 시나리오가 있으면 그것을 쓰고, 없으면 공고 기초금액으로 자동 구성."""
    if request_scenarios:
        return [
            PredPriceScenariosResult(
                base_amount=Decimal(str(s.estimated_price)),
                tot_prdprc_num=15,
                drwt_prdprc_num=4,
                range_rate=Decimal("0"),
                range_source="CUSTOM",
                scenario_lower=Decimal(str(s.estimated_price)),
                scenario_base=Decimal(str(s.estimated_price)),
                scenario_upper=Decimal(str(s.estimated_price)),
            )
            for s in request_scenarios
        ]

    base_amount = bid.resolved_base_amount or bid.presmpt_prce or 0
    if base_amount <= 0:
        return []

    # 계약 유형별 기본 범위 적용 (국가/지방 판단은 cntrct_mthd_nm 등에서 추론 가능하나,
    # 설계서 4.4절 기준 국가계약 ±2% 기본값 적용)
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    is_local = "지방" in str(raw_data.get("cntrctCnclsMthdNm") or "") or "지방" in str(
        bid.cntrct_mthd_nm or ""
    )

    return [generate_pred_price_scenarios(Decimal(str(base_amount)), is_local_contract=is_local)]


def _determine_pass_threshold(rule: Any) -> Decimal:
    """적용된 규칙의 통과점수(T) 결정. 설계서에 따라 고시금액 이상 별표는 85점, 미만은 95점 등."""
    # 서비스 종류별 통과점수는 규칙의 service_type 등으로 판별
    # 일반용역 적격심사는 대체로 95점 기준, 일부는 85점
    # 여기서는 규칙 설명이나 table_name에서 고시금액 이상/미만 구분을 통해 결정
    if "고시금액 이상" in rule.description or "5억원 이상" in rule.description:
        return Decimal("85")
    return Decimal("95")


def _determine_scoring_params(rule: Any) -> tuple[Decimal, Decimal, Decimal]:
    """배점한도(B), 계수(k), 기준비율 결정."""
    # 일반용역 적격심사 공고 기준: B=70, k=2, 기준비율=88%.
    return Decimal("70"), Decimal("2"), Decimal("0.88")


def _calculate_a_value(bid: BidAnnouncement) -> Decimal | None:
    """공고에서 A값(국민연금, 건강보험, 퇴직급여충당금 등) 추출."""
    raw_data = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    # A값 관련 필드명 추정 (실제 필드명은 데이터 확인 필요)
    for key in ["a_value", "aValue", "A값", "nonBidCost", "non_bid_cost"]:
        val = raw_data.get(key)
        if val is not None:
            try:
                return Decimal(str(val))
            except (ArithmeticError, TypeError, ValueError):
                logger.debug("A값 필드 변환 실패: key=%s", key)
    return None


def _evaluate_scenario(
    scenario: PredPriceScenariosResult,
    candidate_bid_amount: Decimal,
    qualification_input: Any,
    rule_result: RuleResolutionResult,
) -> ScenarioEvaluationResult:
    """단일 시나리오에 대한 평가 수행."""
    rule = rule_result.rule
    warnings: list[str] = []

    # 가격점수 계산
    max_price_score, multiplier, base_rate = _determine_scoring_params(rule)
    price_score_result: PriceScoreResult = calculate_price_score(
        bid_price=candidate_bid_amount,
        pred_price=scenario.scenario_base,  # 기준 시나리오 예정가격 사용
        base_rate=base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
    )

    # 정량점수 Q 계산
    non_price_score = (
        Decimal(str(qualification_input.performance_score or 0))
        + Decimal(str(qualification_input.management_score or 0))
        + Decimal(str(qualification_input.labor_plan_score or 0))
        + Decimal(str(qualification_input.credibility_score or 0))
    )

    # 종합 적격 판정
    pass_threshold = _determine_pass_threshold(rule)
    qual_result: QualificationResult = evaluate_qualification(
        bid_price=candidate_bid_amount,
        pred_price=scenario.scenario_base,
        pass_threshold=pass_threshold,
        price_score=price_score_result.score,
        performance_score=Decimal(str(qualification_input.performance_score or 0))
        + Decimal(str(qualification_input.management_score or 0)),
        labor_condition_score=Decimal(str(qualification_input.labor_plan_score or 0)),
        reputation_score=Decimal(str(qualification_input.credibility_score or 0)),
        has_disqualification=qualification_input.disqualification,
    )
    warnings.extend(qual_result.warnings)

    # 시나리오별 투찰율 계산 (각 시나리오 예정가격 대비)
    bid_to_estimated_ratio = compute_price_ratio(candidate_bid_amount, scenario.scenario_base)

    # 시나리오별 가격점수 재계산 (시나리오 예정가격 기준)
    scenario_price_score_result: PriceScoreResult = calculate_price_score(
        bid_price=candidate_bid_amount,
        pred_price=scenario.scenario_base,
        base_rate=base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
    )

    # 시나리오별 종합점수
    scenario_total = non_price_score + scenario_price_score_result.score
    scenario_qualified = (
        not qualification_input.disqualification
        and candidate_bid_amount <= scenario.scenario_base
        and scenario_total >= pass_threshold
    )

    return ScenarioEvaluationResult(
        scenario_name=scenario.scenario_name if hasattr(scenario, "scenario_name") else "기준",
        scenario_type="base",
        estimated_price=int(scenario.scenario_base),
        bid_to_estimated_ratio=float(bid_to_estimated_ratio),
        price_score=float(scenario_price_score_result.score),
        qualification_score=float(non_price_score),
        total_score=float(scenario_total),
        pass_threshold=float(pass_threshold),
        is_qualified=scenario_qualified,
        warnings=warnings,
    )


def _build_analysis_response(
    bid: BidAnnouncement,
    request: EvaluationRequest,
    user: CustomUser,
    rule_result: RuleResolutionResult,
    candidate_bid_amount: Decimal,
    a_value: Decimal | None,
    scenarios: list[PredPriceScenariosResult],
) -> EvaluationResponse:
    """분석 응답 구성."""
    warnings: list[str] = list(rule_result.warnings)

    if rule_result.is_blocked:
        return EvaluationResponse(
            status="blocked",
            rule_id=rule_result.rule.rule_id if rule_result.rule else None,
            rule_name=rule_result.rule.description if rule_result.rule else None,
            rule_basis=f"낙찰방법: {bid.raw_data.get('sucsfbidMthdNm') if isinstance(bid.raw_data, dict) else 'N/A'}",
            blocked=True,
            blocked_reason=(
                f"{rule_result.block_reason_code}: {rule_result.block_reason_message}"
                if rule_result.block_reason_code
                else rule_result.block_reason_message
            ),
            warnings=warnings,
        )

    assert rule_result.rule is not None
    assert rule_result.effective_lwlt_rate is not None
    rule = rule_result.rule
    effective_lwlt = rule_result.effective_lwlt_rate

    # 기본 파라미터
    max_price_score, multiplier, base_rate = _determine_scoring_params(rule)
    pass_threshold = _determine_pass_threshold(rule)

    # 정량점수 Q
    non_price_score = (
        Decimal(str(request.qualification_input.performance_score or 0))
        + Decimal(str(request.qualification_input.management_score or 0))
        + Decimal(str(request.qualification_input.labor_plan_score or 0))
        + Decimal(str(request.qualification_input.credibility_score or 0))
    )

    # A값 반영 최저 투찰금액
    min_bid_result: MinBidAmountResult = calculate_min_bid_amount(
        pred_price=scenarios[0].scenario_base
        if scenarios
        else Decimal(str(bid.prediction_reference_amount or 0)),
        lwlt_rate=effective_lwlt,
        a_value=a_value,
    )

    # 최저 가능 투찰률 역산
    invert_result: InvertRateResult = invert_lowest_bid_rate(
        pass_threshold=pass_threshold,
        non_price_score=non_price_score,
        base_rate=base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
        announcement_lwlt_rate=effective_lwlt,
    )
    warnings.extend(invert_result.warnings)

    # 시나리오별 평가
    scenario_results: list[ScenarioEvaluationResult] = []
    for scenario in scenarios:
        scenario_results.append(
            _evaluate_scenario(
                scenario, candidate_bid_amount, request.qualification_input, rule_result
            )
        )

    # 모델 출처 정보 (예측 API와 유사하게 구성)
    # 여기서는 평가용 모델 ID를 별도로 관리하지 않으므로 기본값 사용
    requested_model = request.selected_model or "evaluation_default"
    actual_model = requested_model
    fallback_used = False
    fallback_reason = None

    return EvaluationResponse(
        status="success",
        rule_id=rule.rule_id,
        rule_name=rule.description,
        rule_basis=f"낙찰방법 '{bid.raw_data.get('sucsfbidMthdNm') if isinstance(bid.raw_data, dict) else 'N/A'}' → 별표 '{rule.table_name}' 매칭",
        blocked=False,
        requested_model=requested_model,
        actual_model=actual_model,
        fallback_used=fallback_used,
        fallback_reason=fallback_reason,
        base_rate=float(base_rate * 100) if base_rate <= 1 else float(base_rate),
        lower_bound_rate=float(effective_lwlt) if effective_lwlt else None,
        a_value_amount=int(a_value) if a_value else None,
        min_bid_amount_with_a=int(min_bid_result.min_bid_amount)
        if min_bid_result.has_a_value
        else None,
        min_possible_bid_rate=float(invert_result.effective_rate_pct) if invert_result else None,
        scenario_results=scenario_results,
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


@router.post("/analyze", response_model=EvaluationResponse, summary="적격심사 정량평가 통합 분석")
def analyze_evaluation(
    payload: EvaluationRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CustomUser = Depends(require_current_user),
):
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
    # 1. 공고 조회
    bid = _get_bid_or_404(db, payload.bid_id)

    # 2. 규칙 판별
    rule_result, _ = _resolve_rule_and_build_warnings(bid)

    # 3. 후보 투찰금액
    candidate_bid_amount = Decimal(str(payload.candidate_bid_amount))

    # 4. A값 추출
    a_value = _calculate_a_value(bid)

    # 5. 복수예가 시나리오 구성
    scenarios = _build_price_scenarios(bid, payload.price_scenarios, rule_result)

    # 5. 분석 응답 구성
    response = _build_analysis_response(
        bid=bid,
        request=payload,
        user=user,
        rule_result=rule_result,
        candidate_bid_amount=candidate_bid_amount,
        a_value=a_value,
        scenarios=scenarios,
    )

    # 6. 분석 성공 시 스냅샷 저장 (차단된 경우도 스냅샷으로 남김)
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
        result_json = response.model_dump(mode="json")
        _save_snapshot_async(
            db=db,
            user_id=user.id,
            bid_id=bid.id,
            rule_id=response.rule_id or "BLOCKED",
            model_id=response.actual_model or "unknown",
            model_version="1.0",
            input_json=input_json,
            result_json=result_json,
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
