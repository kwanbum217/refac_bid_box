"""
src/app/services/evaluation_scoring.py

일반용역 적격심사 결정론적 점수 계산 도메인 모듈.
부동소수점을 배제하고 decimal.Decimal 과 ROUND_HALF_UP 만을 사용하여
가격점수, A값 반영 최저 투찰금액, 최저 투찰률 역산, 복수예가 시나리오, 종합 적격 판정을 수행합니다.
외부 DB, HTTP 요청, 파일 I/O, 시스템 시각에 의존하지 않는 순수 함수로 동작합니다.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

# 소수점 4자리 반올림 단위 (가격비율 x 확정용)
FOUR_DECIMALS = Decimal("0.0001")

# 원 단위 반올림 단위 (투찰금액 및 예가 계산용)
WON_UNIT = Decimal("1")


@dataclass(frozen=True)
class PriceScoreResult:
    """가격점수 계산 결과 객체."""

    bid_price: Decimal
    pred_price: Decimal
    price_ratio: Decimal  # x: 소수점 넷째 자리 확정 비율 (예: 0.8149)
    base_rate: Decimal  # 기준비율 (예: 0.90)
    max_price_score: Decimal  # B: 배점한도
    multiplier: Decimal  # k: 평점 산식 계수
    score: Decimal  # P: 계산된 가격점수
    raw_score: Decimal


@dataclass(frozen=True)
class MinBidAmountResult:
    """최저 투찰금액 계산 결과 객체."""

    pred_price: Decimal
    lwlt_rate_pct: Decimal  # 하한율 (백분율, 예: 89.995)
    lwlt_rate_ratio: Decimal  # 하한율 (비율, 예: 0.89995)
    a_value: Decimal | None
    has_a_value: bool
    min_bid_amount: Decimal  # 원 단위 반올림 투찰금액
    min_bid_amount_exact: Decimal  # 반올림 전 정밀 금액


@dataclass(frozen=True)
class InvertRateResult:
    """최저 가능 투찰률 역산 결과 객체."""

    pass_threshold: Decimal  # T: 통과점수
    non_price_score: Decimal  # Q: 수행능력 등 정량점수 합계
    p_req: Decimal  # P_req = T - Q
    calculated_rate_pct: Decimal  # 산출 역산 투찰률 (%)
    calculated_rate_ratio: Decimal  # 산출 역산 투찰률 (비율)
    announcement_rate_pct: Decimal  # 공고 하한율 (%)
    announcement_rate_ratio: Decimal  # 공고 하한율 (비율)
    effective_rate_pct: Decimal  # 실질 구속 하한 투찰률 (%)
    effective_rate_ratio: Decimal  # 실질 구속 하한 투찰률 (비율)
    binding_constraint: Literal["ANNOUNCEMENT_LWLT_RATE", "CALCULATED_SCORE_RATE"]
    binding_constraint_kr: str  # 구속력 소재 설명 ("공고 낙찰하한율" 또는 "점수 역산 최저 투찰률")
    can_pass: bool  # P_req <= B 충족 여부
    warnings: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PredPriceScenariosResult:
    """복수예비가격 시나리오 구성 결과 객체."""

    base_amount: Decimal  # 기초금액
    tot_prdprc_num: int  # 복수예비가격 총수 (통상 15)
    drwt_prdprc_num: int  # 추첨수 (통상 4)
    range_rate: Decimal  # 변동 범위 (예: 0.02)
    range_source: str  # 범위 출처 ("ANNOUNCEMENT", "NATIONAL_DEFAULT", "LOCAL_DEFAULT")
    scenario_lower: Decimal  # 하단: 기초금액 * (1 - 범위)
    scenario_base: Decimal  # 기준: 기초금액
    scenario_upper: Decimal  # 상단: 기초금액 * (1 + 범위)


@dataclass(frozen=True)
class QualificationResult:
    """종합점수 및 적격 판정 결과 객체."""

    is_qualified: bool  # 3가지 적격 조건 전량 충족 여부
    total_score: Decimal  # 총점 (Q + P)
    non_price_score: Decimal  # Q = 수행능력 + 근로조건이행계획 + 신인도가감점
    price_score: Decimal  # P
    pass_threshold: Decimal  # T
    condition_no_disqualification: bool  # 조건 1: 결격사유 없음
    condition_bid_price_valid: bool  # 조건 2: 입찰금액 <= 예정가격
    condition_total_score_valid: bool  # 조건 3: 총점 >= T
    warnings: list[str] = field(default_factory=list)


def compute_price_ratio(bid_price: Decimal, pred_price: Decimal) -> Decimal:
    """입찰금액 / 예정가격을 소수점 다섯째 자리에서 반올림하여 넷째 자리까지 확정합니다.

    [규약]
    x = ROUND_HALF_UP(입찰금액 / 예정가격, 소수점 4자리)
    참고 자료 실측 예시: 407,448,800 / 500,000,000 = 0.8148976 -> 0.8149
    """
    if pred_price <= Decimal("0"):
        raise ValueError("예정가격은 0보다 커야 합니다.")
    if bid_price < Decimal("0"):
        raise ValueError("입찰금액은 0 이상이어야 합니다.")

    raw_ratio = bid_price / pred_price
    return raw_ratio.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)


def calculate_price_score(
    bid_price: Decimal,
    pred_price: Decimal,
    base_rate: Decimal,
    max_price_score: Decimal,
    multiplier: Decimal,
) -> PriceScoreResult:
    """일반용역 적격심사 가격점수를 계산합니다.

    [산식]
    x = ROUND_HALF_UP(입찰금액 / 예정가격, 소수점 4자리)
    P = B - k * |(기준비율 - x) * 100|

    기준비율은 1을 초과하는 백분율(예: 90) 또는 비율(예: 0.90)을 모두 수용하여 비율로 정규화합니다.
    """
    x = compute_price_ratio(bid_price, pred_price)

    normalized_base_rate = base_rate / Decimal("100") if base_rate > Decimal("1") else base_rate

    diff_percentage = abs(normalized_base_rate - x) * Decimal("100")
    score = max_price_score - multiplier * diff_percentage

    return PriceScoreResult(
        bid_price=bid_price,
        pred_price=pred_price,
        price_ratio=x,
        base_rate=normalized_base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
        score=score,
        raw_score=score,
    )


def calculate_min_bid_amount(
    pred_price: Decimal,
    lwlt_rate: Decimal,
    a_value: Decimal | None = None,
) -> MinBidAmountResult:
    """A값(국민연금, 건강보험 등 합산액) 반영 최저 투찰금액을 산출합니다.

    [산식]
    A값이 있는 경우: 최저 투찰금액 = (예정가격 - A값) * 하한율 + A값
    A값이 없는 경우: 최저 투찰금액 = 예정가격 * 하한율

    금액은 원 단위로 반올림(ROUND_HALF_UP)합니다.
    """
    if pred_price <= Decimal("0"):
        raise ValueError("예정가격은 0보다 커야 합니다.")

    # lwlt_rate 가 백분율(예: 89.995)로 들어오면 비율(0.89995)로 변환
    if lwlt_rate > Decimal("1"):
        rate_pct = lwlt_rate
        rate_ratio = lwlt_rate / Decimal("100")
    else:
        rate_pct = lwlt_rate * Decimal("100")
        rate_ratio = lwlt_rate

    has_a = a_value is not None and a_value > Decimal("0")

    if has_a:
        assert a_value is not None
        exact_amount = (pred_price - a_value) * rate_ratio + a_value
    else:
        exact_amount = pred_price * rate_ratio

    rounded_amount = exact_amount.quantize(WON_UNIT, rounding=ROUND_HALF_UP)

    return MinBidAmountResult(
        pred_price=pred_price,
        lwlt_rate_pct=rate_pct,
        lwlt_rate_ratio=rate_ratio,
        a_value=a_value,
        has_a_value=has_a,
        min_bid_amount=rounded_amount,
        min_bid_amount_exact=exact_amount,
    )


def invert_lowest_bid_rate(
    pass_threshold: Decimal,
    non_price_score: Decimal,
    base_rate: Decimal,
    max_price_score: Decimal,
    multiplier: Decimal,
    announcement_lwlt_rate: Decimal,
) -> InvertRateResult:
    """통과점수(T)를 충족하기 위해 필요한 최저 투찰률을 역산하고 실질 구속 하한을 판별합니다.

    [산식]
    필요 가격점수 P_req = T - Q
    최저 투찰률 = 기준비율 - (B - P_req) / (100 * k)

    역산 결과가 공고 하한율보다 낮으면 공고 하한율이 실질 하한이 되며,
    둘 중 큰 값을 실질 구속 하한으로 반환합니다.
    """
    if multiplier <= Decimal("0"):
        raise ValueError("계수(multiplier)는 0보다 커야 합니다.")

    p_req = pass_threshold - non_price_score

    normalized_base_rate = base_rate / Decimal("100") if base_rate > Decimal("1") else base_rate

    if announcement_lwlt_rate > Decimal("1"):
        ann_pct = announcement_lwlt_rate
        ann_ratio = announcement_lwlt_rate / Decimal("100")
    else:
        ann_pct = announcement_lwlt_rate * Decimal("100")
        ann_ratio = announcement_lwlt_rate

    warnings: list[str] = []
    can_pass = True
    if p_req > max_price_score:
        can_pass = False
        warnings.append(
            f"수행능력 점수({non_price_score}점) 부족으로 가격점수 만점({max_price_score}점)을 "
            f"받아도 통과점수({pass_threshold}점)에 도달할 수 없습니다."
        )

    # (B - P_req) / (100 * k)
    rate_deduction = (max_price_score - p_req) / (Decimal("100") * multiplier)
    calculated_ratio = normalized_base_rate - rate_deduction
    calculated_pct = calculated_ratio * Decimal("100")

    if calculated_pct < ann_pct:
        effective_pct = ann_pct
        effective_ratio = ann_ratio
        binding_code: Literal["ANNOUNCEMENT_LWLT_RATE", "CALCULATED_SCORE_RATE"] = (
            "ANNOUNCEMENT_LWLT_RATE"
        )
        binding_kr = "공고 낙찰하한율"
    else:
        effective_pct = calculated_pct
        effective_ratio = calculated_ratio
        binding_code = "CALCULATED_SCORE_RATE"
        binding_kr = "점수 역산 최저 투찰률"

    return InvertRateResult(
        pass_threshold=pass_threshold,
        non_price_score=non_price_score,
        p_req=p_req,
        calculated_rate_pct=calculated_pct,
        calculated_rate_ratio=calculated_ratio,
        announcement_rate_pct=ann_pct,
        announcement_rate_ratio=ann_ratio,
        effective_rate_pct=effective_pct,
        effective_rate_ratio=effective_ratio,
        binding_constraint=binding_code,
        binding_constraint_kr=binding_kr,
        can_pass=can_pass,
        warnings=warnings,
    )


def generate_pred_price_scenarios(
    base_amount: Decimal,
    tot_prdprc_num: int = 15,
    drwt_prdprc_num: int = 4,
    range_rate: Decimal | None = None,
    is_local_contract: bool = False,
) -> PredPriceScenariosResult:
    """기초금액과 복수예비가격 추첨 매개변수를 기반으로 3대 예가 시나리오를 구성합니다.

    [시나리오]
    하단: 기초금액 * (1 - 범위)
    기준: 기초금액
    상단: 기초금액 * (1 + 범위)

    기본 범위: 국가계약 +-2% (0.02), 지방계약 +-3% (0.03).
    공고에 범위가 명시된 경우 공고값이 최우선 적용됩니다.
    주의: 본 산출물은 예측치가 아니며 공고 사양에 따른 시나리오 구간입니다.
    """
    if base_amount <= Decimal("0"):
        raise ValueError("기초금액은 0보다 커야 합니다.")

    if range_rate is not None:
        effective_range = range_rate / Decimal("100") if range_rate > Decimal("0.5") else range_rate
        range_source = "ANNOUNCEMENT"
    elif is_local_contract:
        effective_range = Decimal("0.03")
        range_source = "LOCAL_DEFAULT"
    else:
        effective_range = Decimal("0.02")
        range_source = "NATIONAL_DEFAULT"

    lower_price = (base_amount * (Decimal("1") - effective_range)).quantize(
        WON_UNIT, rounding=ROUND_HALF_UP
    )
    base_price = base_amount.quantize(WON_UNIT, rounding=ROUND_HALF_UP)
    upper_price = (base_amount * (Decimal("1") + effective_range)).quantize(
        WON_UNIT, rounding=ROUND_HALF_UP
    )

    return PredPriceScenariosResult(
        base_amount=base_amount,
        tot_prdprc_num=tot_prdprc_num,
        drwt_prdprc_num=drwt_prdprc_num,
        range_rate=effective_range,
        range_source=range_source,
        scenario_lower=lower_price,
        scenario_base=base_price,
        scenario_upper=upper_price,
    )


def evaluate_qualification(
    bid_price: Decimal,
    pred_price: Decimal,
    pass_threshold: Decimal,
    price_score: Decimal,
    performance_score: Decimal,
    labor_condition_score: Decimal = Decimal("0"),
    reputation_score: Decimal = Decimal("0"),
    has_disqualification: bool = False,
) -> QualificationResult:
    """종합점수를 산출하고 적격 판정 3대 조건을 결정론적으로 평가합니다.

    [평가 공식]
    Q = 수행능력(실적 + 경영상태) + 근로조건 이행계획 + 신인도 가감점
    총점 = Q + P
    적격 조건 = 결격사유 없음 AND 입찰금액 <= 예정가격 AND 총점 >= T

    근로조건 이행계획이 0점인 경우 실무상 통과 불가 위험 경고를 생성합니다.
    """
    warnings: list[str] = []

    non_price_score = performance_score + labor_condition_score + reputation_score
    total_score = non_price_score + price_score

    cond_no_disqual = not has_disqualification
    cond_price_valid = bid_price <= pred_price
    cond_score_valid = total_score >= pass_threshold

    is_qualified = cond_no_disqual and cond_price_valid and cond_score_valid

    if labor_condition_score == Decimal("0"):
        warnings.append(
            "근로조건 이행계획 점수가 0점입니다. 단순노무용역 등 필수 직종에서는 "
            "근로조건 이행계획 0점 시 사실상 적격심사 통과가 불가능하므로 확인이 필요합니다."
        )

    if not cond_price_valid:
        warnings.append(
            f"입찰금액({bid_price:,}원)이 예정가격({pred_price:,}원)을 초과하여 적격 대상에서 제외됩니다."
        )

    if not cond_no_disqual:
        warnings.append("등록된 결격사유가 존재하여 적격 대상에서 제외됩니다.")

    if not cond_score_valid:
        warnings.append(
            f"종합점수({total_score}점)가 통과점수({pass_threshold}점)에 미달하여 탈락 대상입니다."
        )

    return QualificationResult(
        is_qualified=is_qualified,
        total_score=total_score,
        non_price_score=non_price_score,
        price_score=price_score,
        pass_threshold=pass_threshold,
        condition_no_disqualification=cond_no_disqual,
        condition_bid_price_valid=cond_price_valid,
        condition_total_score_valid=cond_score_valid,
        warnings=warnings,
    )
