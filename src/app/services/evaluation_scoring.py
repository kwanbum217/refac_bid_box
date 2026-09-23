"""
src/app/services/evaluation_scoring.py

일반용역 적격심사 결정론적 점수 계산 도메인 모듈.
부동소수점을 배제하고 decimal.Decimal 을 사용하며, 금액과 비율 확정에는 ROUND_HALF_UP 을 쓰고
입찰가격 보완 금액 후보 산출에만 ROUND_CEILING 을 씁니다.
가격점수, 낙찰하한율 기준 최저 투찰금액, 최저 투찰률 역산, 정량점수 부족분 가격 보완,
복수예가 시나리오, 종합 적격 판정을 수행합니다.
외부 DB, HTTP 요청, 파일 I/O, 시스템 시각에 의존하지 않는 순수 함수로 동작합니다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
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
    """최저 투찰금액을 산출합니다.

    [산식]
    A값이 있는 경우: 최저 투찰금액 = (예정가격 - A값) * 하한율 + A값
    A값이 없는 경우: 최저 투찰금액 = 예정가격 * 하한율

    A값 분기는 공사 적격심사 별표 전용이며 용역 적격심사에는 쓰지 않습니다.
    용역은 A값 없이 호출되어 항상 예정가격 * 하한율을 씁니다.
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


def format_decimal_plain(value: Decimal) -> str:
    """Decimal 을 지수 표기 없이 평문 문자열로 만들고 불필요한 꼬리 0 을 제거합니다.

    Decimal.normalize() 와 float() 를 쓰지 않습니다.
    예: Decimal('20.00') -> '20', Decimal('89.9950') -> '89.995',
    Decimal('1.50') -> '1.5', Decimal('0') -> '0'
    """
    text = format(value, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text


@dataclass(frozen=True)
class CompensationScenarioResult:
    """시나리오 예정가격 한 건에 대한 가격 보완 판정 결과 객체."""

    scenario_name: str
    scenario_type: str
    estimated_price: Decimal
    row_status: Literal["already_sufficient", "compensate", "impossible"]
    verified_price_ratio: Decimal | None  # 채택 금액의 순방향 x (소수점 4자리)
    bid_rate_percent: Decimal | None  # 채택 금액 / 예정가격 * 100 (소수점 3자리)
    complement_bid_amount: Decimal | None  # 보완 입찰금액 (already_sufficient 는 최저 투찰금액)
    verified_price_score: Decimal | None  # 채택 금액의 가격점수
    ratio_steps_raised: int  # 역산 하한 비율 대비 4자리 격자 상승 횟수
    meets_p_req: bool  # 필요 가격점수 P_req 충족 여부


@dataclass(frozen=True)
class PriceCompensationResult:
    """정량점수 부족분을 입찰가격으로 보완하는 판정 결과 객체."""

    score_status: Literal["already_sufficient", "compensate", "impossible"]
    amount_status: Literal["verified", "rate_only"]
    floor_score_basis: Literal["forward_verified", "algebraic"]
    pass_threshold: Decimal  # T
    non_price_score: Decimal  # Q
    p_req: Decimal  # P_req = T - Q
    max_price_score: Decimal  # B
    score_gap: Decimal  # P_req 대비 확보 가능 최고 점수의 부족분
    score_slack: Decimal | None  # already_sufficient 일 때만 P_floor - P_req
    floor_price_score: Decimal | None  # P_floor: 하한 금액의 가격점수
    base_rate_percent: Decimal  # 기준비율 (백분율)
    announcement_lwlt_rate_percent: Decimal  # 공고 하한율 (백분율)
    calculated_rate_percent: Decimal  # 역산 최저 투찰률 (백분율)
    effective_rate_percent: Decimal  # 실질 구속 하한 투찰률 (백분율)
    binding_constraint: Literal["ANNOUNCEMENT_LWLT_RATE", "CALCULATED_SCORE_RATE"]
    score_floor_amount: Decimal | None  # 기준 예정가격의 최저 투찰금액
    scenarios: tuple[CompensationScenarioResult, ...]
    warnings: tuple[str, ...]


@dataclass(frozen=True)
class _RowOutcome:
    """행 판정 내부 중간 결과 (공개 계약 아님)."""

    status: Literal["already_sufficient", "compensate", "impossible"]
    floor_amount: Decimal
    floor_score: Decimal
    floor_ratio: Decimal
    complement_amount: Decimal | None
    verified_ratio: Decimal | None
    verified_score: Decimal | None
    bid_rate_percent: Decimal | None
    ratio_steps_raised: int
    meets_p_req: bool
    best_score: Decimal  # 기준비율 이하 x 를 가진 시도 금액 중 최고 점수 (없으면 P_floor)
    overflow: bool  # 반복 상한 초과로 불가 판정에 이른 경우


_SCORE_STATUS_SEVERITY: dict[str, int] = {
    "already_sufficient": 0,
    "compensate": 1,
    "impossible": 2,
}


def _normalize_rate_ratio(rate: Decimal) -> Decimal:
    """1 초과면 백분율, 이하면 비율로 보고 비율로 정규화합니다."""
    return rate / Decimal("100") if rate > Decimal("1") else rate


def _bid_rate_percent(amount: Decimal, pred_price: Decimal) -> Decimal:
    """채택 금액의 투찰률(%)을 소수점 셋째 자리 ROUND_HALF_UP 으로 확정합니다."""
    return (amount / pred_price * Decimal("100")).quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)


def _compute_score_gap(
    status: Literal["already_sufficient", "compensate", "impossible"],
    p_req: Decimal,
    max_price_score: Decimal,
    floor_score: Decimal,
    best_score: Decimal,
) -> Decimal:
    """상태별 P_req 대비 점수 부족분을 산출합니다."""
    if status == "already_sufficient":
        return Decimal("0")
    if status == "compensate":
        return p_req - floor_score
    if p_req > max_price_score:
        return p_req - max_price_score
    return p_req - best_score


def _resolve_compensation_row(
    pred_price: Decimal,
    base_ratio: Decimal,
    max_price_score: Decimal,
    multiplier: Decimal,
    p_req: Decimal,
    announcement_lwlt_rate: Decimal,
    announcement_ratio: Decimal,
) -> _RowOutcome:
    """예정가격 한 건에 대해 세 상태와 최저 보완 금액을 판정합니다.

    x 는 소수점 4자리 ROUND_HALF_UP 격자이므로 같은 격자 안의 금액은 점수가 같습니다.
    목표 격자의 반올림 하한 경계비율(x_target - unit/2)에 예정가격을 곱해 원 단위로
    올림(ROUND_CEILING)한 금액이 그 점수를 얻는 최저 금액입니다.
    """
    unit = FOUR_DECIMALS
    half = unit / Decimal("2")

    floor_amount = calculate_min_bid_amount(pred_price, announcement_lwlt_rate).min_bid_amount
    floor_result = calculate_price_score(
        floor_amount, pred_price, base_ratio, max_price_score, multiplier
    )
    p_floor = floor_result.score
    x_floor = floor_result.price_ratio

    if p_req > max_price_score:
        return _RowOutcome(
            status="impossible",
            floor_amount=floor_amount,
            floor_score=p_floor,
            floor_ratio=x_floor,
            complement_amount=None,
            verified_ratio=None,
            verified_score=None,
            bid_rate_percent=None,
            ratio_steps_raised=0,
            meets_p_req=False,
            best_score=p_floor,
            overflow=False,
        )

    if p_req <= p_floor:
        return _RowOutcome(
            "already_sufficient",
            floor_amount,
            p_floor,
            x_floor,
            floor_amount,
            x_floor,
            p_floor,
            _bid_rate_percent(floor_amount, pred_price),
            0,
            True,
            p_floor,
            False,
        )

    if x_floor > base_ratio and p_floor < p_req:
        return _RowOutcome(
            status="impossible",
            floor_amount=floor_amount,
            floor_score=p_floor,
            floor_ratio=x_floor,
            complement_amount=None,
            verified_ratio=None,
            verified_score=None,
            bid_rate_percent=None,
            ratio_steps_raised=0,
            meets_p_req=False,
            best_score=p_floor,
            overflow=False,
        )

    low_root = base_ratio - (max_price_score - p_req) / (Decimal("100") * multiplier)
    start_ratio = low_root if low_root > announcement_ratio else announcement_ratio
    x_target = start_ratio.quantize(unit, rounding=ROUND_CEILING)
    first_target = x_target
    iteration_limit = int((base_ratio - first_target) / unit) + 1

    best_score: Decimal | None = None
    adopted_amount: Decimal | None = None
    adopted_result: PriceScoreResult | None = None
    overflow = False
    iterations = 0

    while True:
        if iterations >= iteration_limit:
            overflow = True
            break
        iterations += 1

        if x_target > base_ratio:
            break

        boundary = x_target - half
        candidate = (pred_price * boundary).to_integral_value(rounding=ROUND_CEILING)
        if candidate < floor_amount:
            x_target += unit
            continue

        result = calculate_price_score(
            candidate, pred_price, base_ratio, max_price_score, multiplier
        )
        if result.price_ratio > base_ratio:
            lower = candidate - WON_UNIT
            lower_result: PriceScoreResult | None = None
            while lower >= floor_amount:
                probe = calculate_price_score(
                    lower, pred_price, base_ratio, max_price_score, multiplier
                )
                if probe.price_ratio <= base_ratio:
                    lower_result = probe
                    break
                lower -= WON_UNIT
            if lower_result is not None:
                best_score = (
                    lower_result.score
                    if best_score is None
                    else max(best_score, lower_result.score)
                )
                if lower_result.score >= p_req:
                    adopted_amount = lower
                    adopted_result = lower_result
            break

        if result.score >= p_req:
            adopted_amount = candidate
            adopted_result = result
            break

        best_score = result.score if best_score is None else max(best_score, result.score)
        x_target += unit

    if adopted_amount is None or adopted_result is None:
        best = best_score if best_score is not None else p_floor
        return _RowOutcome(
            status="impossible",
            floor_amount=floor_amount,
            floor_score=p_floor,
            floor_ratio=x_floor,
            complement_amount=None,
            verified_ratio=None,
            verified_score=None,
            bid_rate_percent=None,
            ratio_steps_raised=0,
            meets_p_req=False,
            best_score=best,
            overflow=overflow,
        )

    steps = int((adopted_result.price_ratio - low_root.quantize(unit, rounding=ROUND_FLOOR)) / unit)
    if steps < 0:
        steps = 0

    return _RowOutcome(
        "compensate",
        floor_amount,
        p_floor,
        x_floor,
        adopted_amount,
        adopted_result.price_ratio,
        adopted_result.score,
        _bid_rate_percent(adopted_amount, pred_price),
        steps,
        True,
        p_floor,
        overflow,
    )


def resolve_price_compensation(
    pass_threshold: Decimal,
    non_price_score: Decimal,
    base_rate: Decimal,
    max_price_score: Decimal,
    multiplier: Decimal,
    announcement_lwlt_rate: Decimal,
    reference_pred_price: Decimal | None = None,
    scenarios: Sequence[tuple[str, str, Decimal]] = (),
) -> PriceCompensationResult:
    """정량점수 부족분을 입찰가격으로 보완할 수 있는지 판정합니다.

    [판정 절차]
    P_req = T - Q 를 하한 가격점수 P_floor 및 배점한도 B 와 비교해 세 상태를 정합니다.
    already_sufficient: P_req <= P_floor, 최저 투찰금액으로 충분
    compensate: 금액을 올려 P_req 를 충족하는 최저 금액을 순방향으로 검증
    impossible: P_req > B 이거나, 최저 투찰금액의 x 가 기준비율을 넘어 원 단위로 도달 불가

    reference_pred_price 가 있으면 그 예정가격의 판정이 전역 상태가 되고,
    없고 scenarios 가 있으면 행 상태 중 가장 나쁜 것이 전역 상태가 됩니다.
    둘 다 없으면 금액 검증 없이 역산 하한(algebraic)으로만 상태를 판정합니다.
    """
    base_ratio = _normalize_rate_ratio(base_rate)
    announcement_ratio = _normalize_rate_ratio(announcement_lwlt_rate)

    invert_result = invert_lowest_bid_rate(
        pass_threshold=pass_threshold,
        non_price_score=non_price_score,
        base_rate=base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
        announcement_lwlt_rate=announcement_lwlt_rate,
    )
    p_req = invert_result.p_req

    warnings: list[str] = list(invert_result.warnings)

    scenario_rows: list[CompensationScenarioResult] = []
    outcomes: list[_RowOutcome] = []
    for scenario_name, scenario_type, estimated_price in scenarios:
        outcome = _resolve_compensation_row(
            estimated_price,
            base_ratio,
            max_price_score,
            multiplier,
            p_req,
            announcement_lwlt_rate,
            announcement_ratio,
        )
        if outcome.overflow:
            warnings.append(
                f"{scenario_name} 시나리오에서 보완 금액 탐색 반복 상한을 넘어 불가로 판정했습니다."
            )
        outcomes.append(outcome)
        scenario_rows.append(
            CompensationScenarioResult(
                scenario_name=scenario_name,
                scenario_type=scenario_type,
                estimated_price=estimated_price,
                row_status=outcome.status,
                verified_price_ratio=outcome.verified_ratio,
                bid_rate_percent=outcome.bid_rate_percent,
                complement_bid_amount=outcome.complement_amount,
                verified_price_score=outcome.verified_score,
                ratio_steps_raised=outcome.ratio_steps_raised,
                meets_p_req=outcome.meets_p_req,
            )
        )

    amount_status: Literal["verified", "rate_only"]
    floor_score_basis: Literal["forward_verified", "algebraic"]
    global_outcome: _RowOutcome | None

    if reference_pred_price is not None:
        global_outcome = _resolve_compensation_row(
            reference_pred_price,
            base_ratio,
            max_price_score,
            multiplier,
            p_req,
            announcement_lwlt_rate,
            announcement_ratio,
        )
        if global_outcome.overflow:
            warnings.append(
                "기준 예정가격에서 보완 금액 탐색 반복 상한을 넘어 불가로 판정했습니다."
            )
        amount_status = "verified"
        floor_score_basis = "forward_verified"
    elif outcomes:
        global_outcome = max(outcomes, key=lambda row: _SCORE_STATUS_SEVERITY[row.status])
        amount_status = "verified"
        floor_score_basis = "forward_verified"
    else:
        global_outcome = None
        amount_status = "rate_only"
        floor_score_basis = "algebraic"

    if global_outcome is not None:
        score_status = global_outcome.status
        floor_price_score: Decimal | None = global_outcome.floor_score
        score_floor_amount: Decimal | None = global_outcome.floor_amount
        score_gap = _compute_score_gap(
            score_status,
            p_req,
            max_price_score,
            global_outcome.floor_score,
            global_outcome.best_score,
        )
    else:
        floor_price_score = max_price_score - multiplier * abs(
            (base_ratio - announcement_ratio) * Decimal("100")
        )
        score_floor_amount = None
        if p_req > max_price_score:
            score_status = "impossible"
            score_gap = p_req - max_price_score
        elif p_req <= floor_price_score:
            score_status = "already_sufficient"
            score_gap = Decimal("0")
        else:
            score_status = "compensate"
            score_gap = p_req - floor_price_score

    score_slack = (
        floor_price_score - p_req
        if score_status == "already_sufficient" and floor_price_score is not None
        else None
    )

    return PriceCompensationResult(
        score_status=score_status,
        amount_status=amount_status,
        floor_score_basis=floor_score_basis,
        pass_threshold=pass_threshold,
        non_price_score=non_price_score,
        p_req=p_req,
        max_price_score=max_price_score,
        score_gap=score_gap,
        score_slack=score_slack,
        floor_price_score=floor_price_score,
        base_rate_percent=base_ratio * Decimal("100"),
        announcement_lwlt_rate_percent=invert_result.announcement_rate_pct,
        calculated_rate_percent=invert_result.calculated_rate_pct,
        effective_rate_percent=invert_result.effective_rate_pct,
        binding_constraint=invert_result.binding_constraint,
        score_floor_amount=score_floor_amount,
        scenarios=tuple(scenario_rows),
        warnings=tuple(warnings),
    )
