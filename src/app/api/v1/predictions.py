"""
src/app/api/v1/predictions.py

낙찰가 예측 API (원본 apps/predictions/views.py 1:1 이식).

| 원본 Django 라우트 | 본 API |
| --- | --- |
| `predictions:predict_price` | `POST /api/v1/predictions/predict-price` |
| `predictions:list_models` | `GET /api/v1/predictions/list-models` |
"""

from __future__ import annotations

import logging
import time
from decimal import Decimal, InvalidOperation
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy.orm import Session

from src.app.api.v1.accounts import get_current_user
from src.app.core.config import settings
from src.app.core.db import get_db
from src.app.core.security import enforce_anonymous_api_quota
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.schemas.predictions import (
    PredictionRequest,
    PredictionResponse,
    PredictPriceRequest,
    PredictPriceResponse,
    PredictPriceScoreVerdict,
)
from src.app.services.bid_queries import (
    DEFAULT_PREDICTION_MODEL,
    DEFAULT_PREDICTION_MODEL_BY_CATEGORY,
)
from src.app.services.evaluation_rules import (
    RuleResolutionResult,
    resolve_evaluation_rule_from_raw_data,
)
from src.app.services.evaluation_scoring import format_decimal_plain
from src.app.services.price_score_verification import (
    invert_pass_bid_range,
    verify_price_score,
)
from src.ml.dataset import announcement_feature_payload
from src.ml.features import build_feature_dict
from src.ml.model_registry import (
    ModelRegistry,
    PriceDecisionMethod,
    classify_price_decision_method,
    predict_interval,
    predict_optimal_price_with_provenance,
)
from src.ml.predictor import predictor

logger = logging.getLogger(__name__)
latency_logger = logging.getLogger("uvicorn.error")

# ==============================================================================
# Servc missing_lwlt 및 불확실성 경고 임계값 (docs/analysis/servc_missing_lwlt_policy_20260902.md)
# ==============================================================================
# 구간 폭 임계값 (15.0%p):
# OOS 3,589건 실측(servc_missing_lwlt_policy_20260902.md 2.2절 및 4.2절)에서
# 결측 집단(missing_lwlt)의 구간 폭 중앙값(~10-12%p) 대비 15.0%p는 상위 25% 분위에 해당하며,
# "비정상적으로 넓은 구간(불확실성 과대)"을 식별하는 운영 경고 기준입니다.
WIDE_INTERVAL_THRESHOLD_PERCENT: float = 15.0

# 극단 낙찰률 경고 범위 (80.0% ~ 100.0%):
# 클리핑 전 점 추정 낙찰률이 정상 조달 낙찰률 범위(80%~100%)를 벗어나는 경우
# 비정상 예측값으로 soft 경고 플래그를 부착합니다.
EXTREME_RATE_MIN_PERCENT: float = 80.0
EXTREME_RATE_MAX_PERCENT: float = 100.0


def _classify_lwlt_missing_reason(
    features: dict[str, Any], bid: BidAnnouncement | None = None
) -> str:
    """features.py 가 추출한 단일 특징을 기반으로 결측의 제도적 사유를 분류합니다."""
    cntrct_mthd = str(features.get("cntrct_mthd_nm") or (bid.cntrct_mthd_nm if bid else "") or "")
    bid_methd = str(features.get("bid_methd_nm") or (bid.bid_methd_nm if bid else "") or "")
    sucsfbid_mthd = str(features.get("sucsfbid_mthd_nm") or "")

    combined = f"{cntrct_mthd} {bid_methd} {sucsfbid_mthd}"
    if "수의" in combined:
        return "제도적 부재 (수의계약·수의시담)"
    if "협상" in combined:
        return "제도적 부재 (협상에 의한 계약)"
    if "규격" in combined or "동시" in combined:
        return "제도적 부재 (규격가격동시입찰)"
    if "최저" in combined:
        return "제도적 부재 (최저가낙찰제)"
    return "제도적 부재 (낙찰하한율 미적용 공고)"


# ==============================================================================
# 정량평가 점수 통과 판정 (price_score_verification 정본 연동)
# ==============================================================================
# 가격배점한도 B·평점계수 k·통과점수 T 는 공고 데이터에 없어 사용자가 공고문
# 적격심사 배점표를 보고 입력합니다. 규칙 레지스트리가 실측으로 확정한 값이
# 아니므로 추측값을 넣지 않습니다. 하나라도 없으면 점수를 만들지 않습니다.
_SCORE_TABLE_LABELS: dict[str, str] = {
    "max_price_score": "가격 배점한도(B)",
    "multiplier": "평점 계수(k)",
    "pass_threshold": "적격 통과점수(T)",  # nosec B105 - 배점표 항목 표기이지 비밀번호가 아닙니다
}


def _decimal_or_none(value: Any) -> Decimal | None:
    try:
        return Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError):
        return None


def _plain(value: Decimal | None) -> str | None:
    """Decimal 을 지수 표기 없는 평문 문자열로 만듭니다 (없으면 None)."""
    return format_decimal_plain(value) if value is not None else None


def _announcement_lwlt_rate(raw: dict[str, Any]) -> Decimal | None:
    """공고 raw_data 의 낙찰하한율(백분율, 예 89.995)을 Decimal 로 읽습니다."""
    rate = _decimal_or_none(raw.get("sucsfbidLwltRate"))
    if rate is None or rate <= 0:
        return None
    return rate


def _score_table_attempted(payload: PredictPriceRequest) -> bool:
    """배점표 입력을 하나라도 준 요청인지 봅니다.

    안 준 요청은 판정 대상이 아니므로 기존 불확실성 경고를 건드리지 않습니다.
    """
    return any(
        value is not None
        for value in (
            payload.max_price_score,
            payload.multiplier,
            payload.pass_threshold,
            payload.non_price_score,
        )
    )


def _join_warning(existing: str | None, extra: str) -> str:
    return f"{existing} {extra}" if existing else extra


def _interval_overlap_ratio(
    predicted_low: int | None,
    predicted_high: int | None,
    pass_low: Decimal | None,
    pass_high: Decimal | None,
) -> Decimal | None:
    """예측 구간과 통과 구간의 교집합 금액을 예측 구간 폭으로 나눈 겹침 비율."""
    if predicted_low is None or predicted_high is None or pass_low is None or pass_high is None:
        return None
    width = Decimal(predicted_high) - Decimal(predicted_low)
    if width <= 0:
        return None
    overlap = min(Decimal(predicted_high), pass_high) - max(Decimal(predicted_low), pass_low)
    if overlap <= 0:
        return Decimal("0")
    return overlap / width


def _score_verdict(
    payload: PredictPriceRequest,
    bid: BidAnnouncement,
    pred_price: Decimal,
    optimal_price: int,
    price_low: int | None,
    price_high: int | None,
) -> PredictPriceScoreVerdict:
    """추천가와 예측 구간을 price_score_verification 정본 함수로 채점합니다.

    산식은 재구현하지 않고 verify_price_score·invert_pass_bid_range 만 호출합니다.
    B·k·T 가 하나라도 없거나 규칙을 판별하지 못하면 점수를 만들지 않고 사유를 담습니다.
    """
    raw: dict[str, Any] = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    missing = [
        name
        for name, value in (
            ("max_price_score", payload.max_price_score),
            ("multiplier", payload.multiplier),
            ("pass_threshold", payload.pass_threshold),
        )
        if value is None
    ]

    base_rate: Decimal | None = None
    unavailable: list[str] = []
    rule_result: RuleResolutionResult | None
    try:
        rule_result = resolve_evaluation_rule_from_raw_data(category=bid.category, raw_data=raw)
    except Exception as exc:
        rule_result = None
        unavailable.append(f"적격심사 규칙 판별 중 오류가 발생했습니다 ({exc}).")
    if rule_result is not None:
        if rule_result.is_blocked:
            code = rule_result.block_reason_code or "RULE_BLOCKED"
            reason = (
                rule_result.block_reason_message
                or "낙찰방법으로 적격심사 규칙을 판별하지 못했습니다."
            )
            unavailable.append(f"적격심사 규칙 판별 차단({code}): {reason}")
        elif rule_result.rule is None:
            unavailable.append(
                "낙찰방법으로 적격심사 규칙을 찾지 못해 기준비율을 확정할 수 없습니다."
            )
        else:
            base_rate = _decimal_or_none(rule_result.rule.base_rate)
            if base_rate is None or base_rate <= 0:
                base_rate = None
                unavailable.append("기준비율이 없거나 0 이하라 평점을 계산할 수 없습니다.")

    if missing:
        labels = ", ".join(_SCORE_TABLE_LABELS[name] for name in missing)
        unavailable.append(
            f"공고문 적격심사 배점표({labels})를 입력해야 점수를 계산할 수 있습니다."
        )
    if pred_price <= 0:
        unavailable.append("예정가격이 0보다 커야 합니다.")

    if unavailable:
        return PredictPriceScoreVerdict(verifiable=False, unavailable_reasons=unavailable)

    assert payload.max_price_score is not None
    assert payload.multiplier is not None
    assert payload.pass_threshold is not None
    assert base_rate is not None
    max_price_score = Decimal(str(payload.max_price_score))
    multiplier = Decimal(str(payload.multiplier))
    pass_threshold = Decimal(str(payload.pass_threshold))
    if payload.non_price_score is None:
        q_assumed = True
        non_price_score = Decimal("0")
    else:
        q_assumed = False
        non_price_score = Decimal(str(payload.non_price_score))

    optimal_result = verify_price_score(
        bid_price=Decimal(optimal_price),
        pred_price=pred_price,
        base_rate=base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
    )
    low_score: Decimal | None = None
    high_score: Decimal | None = None
    if price_low is not None:
        low_score = verify_price_score(
            bid_price=Decimal(price_low),
            pred_price=pred_price,
            base_rate=base_rate,
            max_price_score=max_price_score,
            multiplier=multiplier,
        ).score
    if price_high is not None:
        high_score = verify_price_score(
            bid_price=Decimal(price_high),
            pred_price=pred_price,
            base_rate=base_rate,
            max_price_score=max_price_score,
            multiplier=multiplier,
        ).score

    range_result = invert_pass_bid_range(
        pass_threshold=pass_threshold,
        non_price_score=non_price_score,
        base_rate=base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
        pred_price=pred_price,
        announcement_lwlt_rate=_announcement_lwlt_rate(raw),
    )

    verdict = PredictPriceScoreVerdict(
        verifiable=True,
        base_rate=format_decimal_plain(base_rate),
        max_price_score=format_decimal_plain(max_price_score),
        multiplier=format_decimal_plain(multiplier),
        pass_threshold=format_decimal_plain(pass_threshold),
        non_price_score=format_decimal_plain(non_price_score),
        non_price_score_assumed_zero=q_assumed,
        optimal_price_score=_plain(optimal_result.score),
        price_low_score=_plain(low_score),
        price_high_score=_plain(high_score),
        pass_range_status=range_result.status,
        pass_range_reasons=list(range_result.reasons),
    )

    if q_assumed:
        verdict.uncertainty_note = (
            "비가격 정량점수 합계 Q 를 0 으로 가정해 통과 가능 구간을 역산했습니다. "
            "Q 는 실제 수행능력 점수가 나오기 전에는 알 수 없어, 이 가정에 따라 구간이 "
            "실제보다 관대하거나 엄격할 수 있습니다."
        )

    if range_result.is_feasible:
        verdict.pass_ratio_low = _plain(range_result.ratio_low)
        verdict.pass_ratio_high = _plain(range_result.ratio_high)
        verdict.pass_amount_low = (
            int(range_result.amount_low) if range_result.amount_low is not None else None
        )
        verdict.pass_amount_high = (
            int(range_result.amount_high) if range_result.amount_high is not None else None
        )
        verdict.effective_ratio_low = _plain(range_result.effective_ratio_low)
        verdict.effective_ratio_high = _plain(range_result.effective_ratio_high)
        verdict.effective_amount_low = (
            int(range_result.effective_amount_low)
            if range_result.effective_amount_low is not None
            else None
        )
        verdict.effective_amount_high = (
            int(range_result.effective_amount_high)
            if range_result.effective_amount_high is not None
            else None
        )
        effective_low = (
            range_result.effective_amount_low
            if range_result.effective_amount_low is not None
            else range_result.amount_low
        )
        effective_high = (
            range_result.effective_amount_high
            if range_result.effective_amount_high is not None
            else range_result.amount_high
        )
        if effective_low is not None and effective_high is not None:
            verdict.optimal_price_passes = effective_low <= Decimal(optimal_price) <= effective_high
        verdict.predicted_interval_overlap_ratio = _plain(
            _interval_overlap_ratio(price_low, price_high, effective_low, effective_high)
        )

    return verdict


router = APIRouter(prefix="/predictions", tags=["Predictions"])


def _default_model_for_bid(bid: BidAnnouncement) -> str:
    return DEFAULT_PREDICTION_MODEL_BY_CATEGORY.get(bid.category, DEFAULT_PREDICTION_MODEL)


def _prediction_dispatch_wait_ms(request: Request) -> float:
    started_ns = request.scope.get("prediction_dispatch_start_ns")
    if not isinstance(started_ns, int):
        return 0.0
    current_ns = time.perf_counter_ns()
    if not isinstance(current_ns, int):
        return 0.0
    return max(0.0, (current_ns - started_ns) / 1_000_000.0)


@router.get("/list-models", summary="사용 가능한 예측 모델 목록")
def list_models_api():
    """Return the currently available prediction models."""
    return {"status": "success", "models": ModelRegistry.list_models_info()}


@router.post("/predict-price", response_model=PredictPriceResponse, summary="공고 기반 낙찰가 예측")
def predict_price_api(
    payload: PredictPriceRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
):
    """공고 ID를 받아 Champion 모델로 최적 투찰가를 산출합니다."""
    enforce_anonymous_api_quota(request, user)
    t_start = time.perf_counter()
    c_start = time.thread_time()
    dispatch_wait_ms = _prediction_dispatch_wait_ms(request)

    user_price = "".join(
        char for char in str(payload.user_price or "0") if char.isdigit() or char == "."
    )

    t_db_start = time.perf_counter()
    bid = db.get(BidAnnouncement, payload.bid_id)
    t_db_lookup = max(0.0, time.perf_counter() - t_db_start)
    if bid is None:
        raise HTTPException(status_code=404, detail="공고를 찾을 수 없습니다.")

    selected_model = payload.selected_model or _default_model_for_bid(bid)
    reference_amount = float(bid.prediction_reference_amount or 0)

    # 원본은 금액이 없어도 예측을 진행해 추천 투찰가 0 원을 돌려줍니다.
    # 0 원은 답이 아니라 오답이므로 여기서 끊습니다. 기초금액과 예정가격이
    # 모두 없는 공고가 10만 건 이상이며 외자는 절반 가까이가 이 상태입니다.
    if reference_amount <= 0:
        raise HTTPException(
            status_code=422,
            detail="기초금액과 예정가격이 모두 공개되지 않은 공고라 투찰가를 산출할 수 없습니다.",
        )

    # 비예가 판정: model_registry.classify_price_decision_method 단일 함수 사용.
    # 명시적 Servc 비예가만 차단하고 missing/unknown/non-Servc는 pass-through 한다.
    # 근거: docs/design/servc_nonprearng_population_cause_20260812.md
    raw: dict[str, Any] = bid.raw_data if isinstance(bid.raw_data, dict) else {}
    method_class = classify_price_decision_method(raw)
    if method_class == PriceDecisionMethod.NON_PREARNG and bid.category == "Servc":
        raise HTTPException(
            status_code=422,
            detail="비예가 공고는 예정가격을 작성하지 않는 제도라 "
            "낙찰률 기반 투찰가를 산출할 수 없습니다.",
        )

    # 제도 특징은 raw_data JSON 안에 있어 공고 컬럼만으로는 못 채웁니다.
    # 이 병합을 빼면 학습이 쓰는 34개 중 30개가 기본값으로 떨어집니다.
    t_feature_start = time.perf_counter()
    features = {
        **announcement_feature_payload(bid),
        "title": bid.bid_ntce_nm or "",
        "agency_name": bid.dminstt_nm or bid.ntce_instt_nm or "",
        "scenario_mode": "2",
        "presmpt_prce": reference_amount,
        "presmptPrce": reference_amount,
        "real_budget": reference_amount,
        "bid_ntce_nm": bid.bid_ntce_nm or "",
        "ntce_instt_nm": bid.ntce_instt_nm or "",
        "ntceInsttNm": bid.ntce_instt_nm or "",
        "dminstt_nm": bid.dminstt_nm or "",
        "bidMethdNm": bid.bid_methd_nm or "",
        "cntrctCnclsMthdNm": bid.cntrct_mthd_nm or "",
        "category": bid.category or "",
        "bid_ntce_dt": bid.bid_ntce_dt,
        "bid_clse_dt": bid.bid_clse_dt,
        "openg_dt": bid.openg_dt,
    }

    # 기관 이력과 재발주 이력은 DB 조회가 필요합니다. session 을 넘기지 않으면
    # 상수로 떨어져 학습과 다른 값을 보게 됩니다.
    # 원본 키 위에 덮어씁니다. 통째로 갈아끼우면 규칙 기반 구 모델이 쓰는
    # title / agency_name / scenario_mode 가 사라집니다.
    features = {**features, **build_feature_dict(features, db)}
    t_feature_build = max(0.0, time.perf_counter() - t_feature_start)

    # 후보 순회는 함수 안에서 끝납니다. 여기서 다시 fallback 을 시도하면 같은
    # 후보 목록을 두 번 돌 뿐이라 대체 사실이 그대로 은폐됩니다. 어느 모델이
    # 답했는지는 outcome.actual_model 하나만 봅니다.
    try:
        t_point_start = time.perf_counter()
        c_point_start = time.thread_time()
        outcome = predict_optimal_price_with_provenance(selected_model, features)
        t_point_infer = max(0.0, time.perf_counter() - t_point_start)
        c_point_infer = max(0.0, time.thread_time() - c_point_start)
    except Exception as exc:
        logger.error("모델 후보 전량 실패 (요청 모델 %s): %s", selected_model, exc)
        raise HTTPException(
            status_code=503,
            detail="예측 모델을 사용할 수 없어 투찰가를 산출하지 못했습니다.",
        ) from exc

    predicted_rate = outcome.predicted_rate
    actual_model = outcome.actual_model
    wrapper = ModelRegistry.get_model(actual_model)
    base_name = wrapper.get_display_name() if wrapper else actual_model
    model_name = f"{base_name} (Fallback)" if outcome.fallback_used else base_name

    estimated_price = reference_amount
    if predicted_rate < 2.0:
        optimal_price = int(estimated_price * predicted_rate)
        prediction_rate_percent = round(predicted_rate * 100, 4)
    else:
        optimal_price = int(predicted_rate)
        prediction_rate_percent = round(predicted_rate, 4)

    # 입력 투찰가가 추천가에 얼마나 가까운지입니다. 모델 불확실성과는 무관하며
    # 종전 이름(confidence)은 사용자가 이를 신뢰도로 읽게 만들었습니다. 모델
    # 불확실성은 아래 예측 구간으로 전달합니다.
    # 값이 낮을 때 난수로 채우던 종전 동작은 제거했습니다. 같은 입력은 항상
    # 같은 응답을 내야 합니다.
    user_bid_similarity = None
    try:
        user_price_value = float(user_price) if user_price else 0.0
    except ValueError:
        user_price_value = 0.0
    if user_price_value > 0 and estimated_price > 0:
        diff_ratio = abs(user_price_value - optimal_price) / estimated_price
        user_bid_similarity = max(0, min(100, int(100 - (diff_ratio * 400))))

    # 예측 구간. 큰 건일수록 산포가 커지므로 단일 숫자만 주면 사용자가 그 값을
    # 그대로 신뢰합니다. 구 모델은 분위 아티팩트가 없어 None 이 나옵니다.
    # 점 추정을 낸 모델과 같은 모델에서 뽑아야 합니다.
    rate_low = rate_high = price_low = price_high = coverage = None
    t_interval_start = time.perf_counter()
    c_interval_start = time.thread_time()
    bounds = predict_interval(actual_model, features)
    t_interval_infer = max(0.0, time.perf_counter() - t_interval_start)
    c_interval_infer = max(0.0, time.thread_time() - c_interval_start)
    if bounds is not None:
        low, high, coverage = bounds
        rate_low, rate_high = round(low, 4), round(high, 4)
        price_low = int(estimated_price * low / 100)
        price_high = int(estimated_price * high / 100)

    # missing_lwlt 취약 집단 판정 (features.py 의 단일 특징 공급원 기준)
    lwlt_missing = bool(features.get("lwlt_rate_missing", 0.0) == 1.0)
    lwlt_missing_reason = _classify_lwlt_missing_reason(features, bid) if lwlt_missing else None

    # 구간 폭 및 극단 예측 경고 판정 (docs/analysis/servc_missing_lwlt_policy_20260902.md 4.2절)
    wide_interval_warning = False
    if rate_low is not None and rate_high is not None:
        interval_width = rate_high - rate_low
        wide_interval_warning = interval_width > WIDE_INTERVAL_THRESHOLD_PERCENT

    extreme_prediction_warning = (
        prediction_rate_percent < EXTREME_RATE_MIN_PERCENT
        or prediction_rate_percent > EXTREME_RATE_MAX_PERCENT
    )

    uncertainty_warning: str | None = None
    if lwlt_missing:
        uncertainty_warning = (
            "낙찰하한율 정보가 없는 공고 유형(수의시담·협상·규격가격동시 등)으로 "
            "예측 불확실성이 큽니다. 예측 구간을 반드시 참고하십시오."
        )
    elif wide_interval_warning:
        uncertainty_warning = "예측 구간 폭이 넓어 불확실성이 큽니다. 참고용으로만 활용하십시오."

    message = (
        f"{model_name} 분석이 완료되었습니다. 예상 낙찰률은 {prediction_rate_percent}% 입니다."
    )
    if outcome.fallback_used:
        message = (
            f"요청하신 모델({outcome.requested_model})을 쓸 수 없어 "
            f"{base_name} 으로 예측했습니다. "
            f"예상 낙찰률은 {prediction_rate_percent}% 입니다."
        )
    if lwlt_missing:
        message += " (낙찰하한율 부재 공고로 예측 불확실성이 큽니다)"

    # 정량평가 점수 통과 판정. 배점표 B·k·T 는 공고 데이터에 없어 사용자 입력이
    # 정본이며, 없으면 점수를 만들지 않고 사유만 돌려줍니다.
    score_verdict = _score_verdict(
        payload=payload,
        bid=bid,
        pred_price=Decimal(str(reference_amount)),
        optimal_price=optimal_price,
        price_low=price_low,
        price_high=price_high,
    )
    if not score_verdict.verifiable:
        reason_text = "; ".join(score_verdict.unavailable_reasons)
        message += f" (정량평가 점수 통과 판정을 하지 못했습니다: {reason_text})"
        # 배점표를 주지 않은 요청은 판정 대상이 아니므로 기존 불확실성 경고를
        # 건드리지 않습니다. 배점표를 줬는데도 판정하지 못했을 때만 이유를 덧붙입니다.
        if _score_table_attempted(payload):
            uncertainty_warning = _join_warning(
                uncertainty_warning, f"정량평가 점수 판정 불가: {reason_text}"
            )
    elif score_verdict.uncertainty_note is not None:
        uncertainty_warning = _join_warning(uncertainty_warning, score_verdict.uncertainty_note)

    t_model = t_point_infer + t_interval_infer
    c_model = c_point_infer + c_interval_infer
    t_total = max(0.0, time.perf_counter() - t_start)
    c_total = max(0.0, time.thread_time() - c_start)
    if settings.LATENCY_SEGMENT_LOGGING:
        latency_logger.info(
            "endpoint=predict_price_api, wall_ms=%.2f, thread_cpu_ms=%.2f, model_wall_ms=%.2f, model_thread_cpu_ms=%.2f, db_lookup_ms=%.2f, feature_build_ms=%.2f, point_infer_ms=%.2f, interval_infer_ms=%.2f",
            t_total * 1000.0,
            c_total * 1000.0,
            t_model * 1000.0,
            c_model * 1000.0,
            t_db_lookup * 1000.0,
            t_feature_build * 1000.0,
            t_point_infer * 1000.0,
            t_interval_infer * 1000.0,
        )
        latency_logger.info(
            "endpoint=predict_price_api, executor_queue_wait_ms=%.2f",
            dispatch_wait_ms,
        )

    return PredictPriceResponse(
        status="success",
        optimal_price=optimal_price,
        prediction_rate=prediction_rate_percent,
        user_bid_similarity=user_bid_similarity,
        model_name=model_name,
        model_id=actual_model,
        requested_model=outcome.requested_model,
        fallback_used=outcome.fallback_used,
        fallback_reason=outcome.fallback_reason,
        rate_low=rate_low,
        rate_high=rate_high,
        price_low=price_low,
        price_high=price_high,
        interval_coverage=coverage,
        lwlt_missing=lwlt_missing,
        lwlt_missing_reason=lwlt_missing_reason,
        wide_interval_warning=wide_interval_warning,
        extreme_prediction_warning=extreme_prediction_warning,
        uncertainty_warning=uncertainty_warning,
        message=message,
        score_verdict=score_verdict,
    )


@router.post("/predict", response_model=PredictionResponse, summary="특징 직접 입력 예측")
def predict_winning_price(
    payload: PredictionRequest,
    request: Request,
    db: Session = Depends(get_db),
    user: CustomUser | None = Depends(get_current_user),
):
    """공고 레코드 없이 특징을 직접 넣어 예측합니다 (리팩토링 신규 계약).

    db 는 inst_hist_rate 를 실제 기관 이력으로 채우기 위해 필요합니다.
    빼면 상수로 떨어져 학습과 정의가 갈립니다.
    """
    enforce_anonymous_api_quota(request, user)
    t_start = time.perf_counter()
    c_start = time.thread_time()
    dispatch_wait_ms = _prediction_dispatch_wait_ms(request)

    t_payload_start = time.perf_counter()
    dumped_payload = payload.model_dump()
    t_payload_dump = max(0.0, time.perf_counter() - t_payload_start)

    t_model_start = time.perf_counter()
    c_model_start = time.thread_time()
    result = predictor.predict(dumped_payload, session=db)
    t_model = max(0.0, time.perf_counter() - t_model_start)
    c_model = max(0.0, time.thread_time() - c_model_start)

    t_total = max(0.0, time.perf_counter() - t_start)
    c_total = max(0.0, time.thread_time() - c_start)
    if settings.LATENCY_SEGMENT_LOGGING:
        latency_logger.info(
            "endpoint=predict_winning_price, wall_ms=%.2f, thread_cpu_ms=%.2f, model_wall_ms=%.2f, model_thread_cpu_ms=%.2f, payload_dump_ms=%.2f",
            t_total * 1000.0,
            c_total * 1000.0,
            t_model * 1000.0,
            c_model * 1000.0,
            t_payload_dump * 1000.0,
        )
        latency_logger.info(
            "endpoint=predict_winning_price, executor_queue_wait_ms=%.2f",
            dispatch_wait_ms,
        )

    return PredictionResponse(
        bid_notice_no=payload.bid_notice_no,
        predicted_price=result["predicted_price"],
        predicted_rate=result["predicted_rate"],
        model_version=result["model_version"],
        features_used=result["features_used"],
    )
