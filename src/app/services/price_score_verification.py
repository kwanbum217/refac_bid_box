"""
src/app/services/price_score_verification.py

입찰가격 평점 산식 검증기와 통과 가능 낙찰가 구간 역산 모듈.

평점 산식의 유일한 정본은 evaluation_scoring.calculate_price_score 이며, 본 모듈은
그 함수를 호출해 결과를 검증하고 역산할 뿐 산식을 다시 구현하지 않습니다.
가이드 원본 규칙은 P = B - k * |(기준율 - 입찰가격/예정가격) * 100| 이고,
입찰가격/예정가격(x)은 소수점 다섯째 자리에서 반올림해 넷째 자리까지 씁니다.

통과 조건은 P >= T - Q 입니다. T 는 적격 통과점수, Q 는 비가격 정량점수 합계입니다.
P = B - k*|기준율 - x|*100 이므로 P >= N (N = T - Q) 은 |기준율 - x| <= (B - N)/(100k)
와 같습니다. B - N 이 음수면 만점으로도 통과할 수 없어 통과 불가를 반환합니다.

결정론을 위해 부동소수점을 배제하고 decimal.Decimal 과 ROUND_HALF_UP 만 사용합니다.
입력이 없거나 형식이 잘못되면 예외를 던지지 않고 확인 불가 사유를 담은 결과를
반환하며, 판정을 조용히 성공시키지 않습니다.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal
from typing import Literal

from src.app.services.evaluation_scoring import (
    FOUR_DECIMALS,
    calculate_min_bid_amount,
    calculate_price_score,
    format_decimal_plain,
)

# 소수점 넷째 자리 반올림 격자의 절반 (ROUND_HALF_UP 경계 판정용)
HALF_UNIT = FOUR_DECIMALS / Decimal("2")
ZERO = Decimal("0")
ONE = Decimal("1")
HUNDRED = Decimal("100")

RangeStatus = Literal["feasible", "impossible", "unverifiable"]
LwltStatus = Literal["not_provided", "within_range", "excludes_all"]


def round_price_ratio(raw_ratio: Decimal) -> Decimal:
    """입찰가격 비율을 소수점 다섯째 자리에서 반올림해 넷째 자리까지 확정합니다.

    compute_price_ratio 와 같은 반올림 단위(FOUR_DECIMALS)와 모드(ROUND_HALF_UP)를
    공유합니다. 예: 0.8148976 -> 0.8149, 0.81485 -> 0.8149, 0.814849 -> 0.8148
    """
    return raw_ratio.quantize(FOUR_DECIMALS, rounding=ROUND_HALF_UP)


def _to_rate_ratio(rate: Decimal) -> Decimal:
    """1 초과면 백분율로 보고 비율로 정규화합니다 (calculate_price_score 와 동일 규칙)."""
    return rate / HUNDRED if rate > ONE else rate


@dataclass(frozen=True)
class PriceScoreVerificationResult:
    """가이드 원본 규칙 대비 평점 검증 결과 객체."""

    is_verifiable: bool
    status: Literal["verified", "unverifiable"]
    reasons: tuple[str, ...]
    bid_price: Decimal | None
    pred_price: Decimal | None
    price_ratio: Decimal | None  # x: 소수점 넷째 자리 확정 비율
    base_rate_ratio: Decimal | None  # 기준율 (비율)
    max_price_score: Decimal | None  # B
    multiplier: Decimal | None  # k
    deviation: Decimal | None  # |기준율 - x| * 100
    deduction: Decimal | None  # k * deviation
    score: Decimal | None  # P
    raw_score: Decimal | None


def verify_price_score(
    bid_price: Decimal | None = None,
    pred_price: Decimal | None = None,
    base_rate: Decimal | None = None,
    max_price_score: Decimal | None = None,
    multiplier: Decimal | None = None,
    flat_ratio: Decimal | None = None,
    flat_score: Decimal | None = None,
) -> PriceScoreVerificationResult:
    """가이드 원본 규칙대로 calculate_price_score 결과를 검증합니다.

    [검증식]
    x = round_price_ratio(입찰금액 / 예정가격)
    P = B - k * |(기준율 - x) * 100|

    평점 산식을 재구현하지 않고 evaluation_scoring.calculate_price_score 를 호출합니다.
    입력이 없거나 형식이 잘못되면 계산하지 않고 status=unverifiable 과 사유를 반환합니다.
    flat_ratio·flat_score 가 주어지면 산식 함수로 그대로 전달하며, None 이면 불변입니다.
    """
    missing: list[str] = []
    if bid_price is None:
        missing.append("입찰금액")
    if pred_price is None:
        missing.append("예정가격")
    if base_rate is None:
        missing.append("기준비율")
    if max_price_score is None:
        missing.append("가격 배점한도")
    if multiplier is None:
        missing.append("평점 계수")
    reasons: list[str] = []
    if missing:
        reasons.append(f"{', '.join(missing)} 값이 없어 평점을 검증할 수 없습니다.")
    if pred_price is not None and pred_price <= ZERO:
        reasons.append("예정가격은 0보다 커야 합니다.")
    if bid_price is not None and bid_price < ZERO:
        reasons.append("입찰금액은 0 이상이어야 합니다.")
    if max_price_score is not None and max_price_score < ZERO:
        reasons.append("가격 배점한도는 0 이상이어야 합니다.")
    if multiplier is not None and multiplier < ZERO:
        reasons.append("평점 계수는 0 이상이어야 합니다.")
    if base_rate is not None and base_rate <= ZERO:
        reasons.append("기준비율은 0보다 커야 합니다.")

    if reasons:
        return PriceScoreVerificationResult(
            is_verifiable=False,
            status="unverifiable",
            reasons=tuple(reasons),
            bid_price=bid_price,
            pred_price=pred_price,
            price_ratio=None,
            base_rate_ratio=None,
            max_price_score=max_price_score,
            multiplier=multiplier,
            deviation=None,
            deduction=None,
            score=None,
            raw_score=None,
        )

    assert bid_price is not None
    assert pred_price is not None
    assert base_rate is not None
    assert max_price_score is not None
    assert multiplier is not None

    result = calculate_price_score(
        bid_price,
        pred_price,
        base_rate,
        max_price_score,
        multiplier,
        flat_ratio=flat_ratio,
        flat_score=flat_score,
    )
    deviation = abs(result.base_rate - result.price_ratio) * HUNDRED
    return PriceScoreVerificationResult(
        is_verifiable=True,
        status="verified",
        reasons=(),
        bid_price=bid_price,
        pred_price=pred_price,
        price_ratio=result.price_ratio,
        base_rate_ratio=result.base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
        deviation=deviation,
        deduction=multiplier * deviation,
        score=result.score,
        raw_score=result.raw_score,
    )


@dataclass(frozen=True)
class PassBidRangeResult:
    """통과 가능 낙찰가 구간 역산 결과 객체.

    ratio_low/ratio_high 는 연속 허용 구간 max(0, 기준율 - 허용차) ~ min(1, 기준율 + 허용차) 입니다.
    ratio_grid_low/ratio_grid_high 는 실제 평점이 쓰는 소수점 넷째 자리 격자에 맞춘 도달 가능 구간입니다.
    amount_low/amount_high 는 그 격자 구간에 대응하는 원 단위 절대금액 구간입니다.
    effective_* 는 낙찰하한율 미달 구간을 제외한 유효 구간이며, 하한율 판정(lwlt_status)은
    평점 계산과 독립적으로 분리해 담습니다.
    """

    status: RangeStatus = "unverifiable"
    is_feasible: bool = False
    reasons: tuple[str, ...] = ()
    pass_threshold: Decimal | None = None  # T
    non_price_score: Decimal | None = None  # Q
    required_price_score: Decimal | None = None  # N = T - Q
    base_rate_ratio: Decimal | None = None
    max_price_score: Decimal | None = None  # B
    multiplier: Decimal | None = None  # k
    pred_price: Decimal | None = None
    tolerance: Decimal | None = None  # (B - N) / (100k)
    ratio_low: Decimal | None = None
    ratio_high: Decimal | None = None
    ratio_grid_low: Decimal | None = None
    ratio_grid_high: Decimal | None = None
    amount_low: Decimal | None = None
    amount_high: Decimal | None = None
    lwlt_status: LwltStatus = "not_provided"
    lwlt_rate_ratio: Decimal | None = None
    lwlt_amount: Decimal | None = None
    effective_ratio_low: Decimal | None = None
    effective_ratio_high: Decimal | None = None
    effective_amount_low: Decimal | None = None
    effective_amount_high: Decimal | None = None


def invert_pass_bid_range(
    pass_threshold: Decimal | None = None,
    non_price_score: Decimal | None = None,
    base_rate: Decimal | None = None,
    max_price_score: Decimal | None = None,
    multiplier: Decimal | None = None,
    pred_price: Decimal | None = None,
    announcement_lwlt_rate: Decimal | None = None,
    flat_ratio: Decimal | None = None,
    flat_score: Decimal | None = None,
) -> PassBidRangeResult:
    """P >= T - Q 를 만족하는 통과 가능 낙찰가 구간을 비율과 절대금액으로 역산합니다.

    [역산식]
    N = T - Q
    P >= N  <=>  k*|기준율 - x|*100 <= B - N  <=>  |기준율 - x| <= (B - N) / (100k)
    비율 구간 = [max(0, 기준율 - 허용차), min(1, 기준율 + 허용차)]
    절대금액 구간 = 그 구간의 소수점 넷째 자리 격자값을 원 단위로 환산한 [하한, 상한]

    B - N < 0 이면 만점으로도 통과할 수 없어 impossible 을 반환합니다.
    k = 0 이면 나눗셈이 불가능하므로 별도로 처리하며, P 는 배점한도 B 로 고정됩니다.
    낙찰하한율이 주어지면 미달 구간을 제외한 유효 구간과 독립된 하한율 판정을 함께 담습니다.

    [평탄]
    x >= flat_ratio 에서 평점이 flat_score 로 고정되므로, flat_score >= N 이면 평탄 구간
    (비율 flat_ratio ~ 1) 전체가 통과합니다. 이 평탄 구간이 산식 통과 구간과 이어지면
    통과 상한이 예정가격(비율 1)까지 넓어지지만, flat_score 가 산식값보다 커서 두 구간이
    떨어지면 통과 구간이 둘로 나뉩니다. 이 함수는 하나의 연속 구간만 표현하므로 그때는
    기준비율을 포함한 산식 구간만 돌려주고 평탄 구간이 따로 통과함을 사유에 남깁니다.
    반대로 flat_score < N 이면 x >= flat_ratio 구간은 통과하지 못하므로, 산식 통과 상한이
    flat_ratio 이상일 때 그 상한을 flat_ratio 미만의 격자값으로 잘라냅니다.
    flat_ratio·flat_score 가 None 이면 기존 동작과 완전히 같습니다.
    """
    missing: list[str] = []
    if pass_threshold is None:
        missing.append("적격 통과점수")
    if non_price_score is None:
        missing.append("비가격 정량점수 합계")
    if base_rate is None:
        missing.append("기준비율")
    if max_price_score is None:
        missing.append("가격 배점한도")
    if multiplier is None:
        missing.append("평점 계수")
    if pred_price is None:
        missing.append("예정가격")
    reasons: list[str] = []
    if missing:
        reasons.append(f"{', '.join(missing)} 값이 없어 통과 가능 구간을 역산할 수 없습니다.")
    if pred_price is not None and pred_price <= ZERO:
        reasons.append("예정가격은 0보다 커야 합니다.")
    if max_price_score is not None and max_price_score < ZERO:
        reasons.append("가격 배점한도는 0 이상이어야 합니다.")
    if multiplier is not None and multiplier < ZERO:
        reasons.append("평점 계수는 0 이상이어야 합니다.")
    if base_rate is not None and base_rate <= ZERO:
        reasons.append("기준비율은 0보다 커야 합니다.")

    if reasons:
        return PassBidRangeResult(
            status="unverifiable",
            is_feasible=False,
            reasons=tuple(reasons),
            pass_threshold=pass_threshold,
            non_price_score=non_price_score,
            base_rate_ratio=None,
            max_price_score=max_price_score,
            multiplier=multiplier,
            pred_price=pred_price,
        )

    assert pass_threshold is not None
    assert non_price_score is not None
    assert base_rate is not None
    assert max_price_score is not None
    assert multiplier is not None
    assert pred_price is not None

    base_ratio = _to_rate_ratio(base_rate)
    required = pass_threshold - non_price_score  # N

    if announcement_lwlt_rate is None:
        lwlt_ratio: Decimal | None = None
        lwlt_amount: Decimal | None = None
        initial_lwlt_status: LwltStatus = "not_provided"
    else:
        lwlt_ratio = _to_rate_ratio(announcement_lwlt_rate)
        lwlt_amount = calculate_min_bid_amount(pred_price, announcement_lwlt_rate).min_bid_amount
        initial_lwlt_status = "excludes_all" if lwlt_amount > pred_price else "within_range"

    def build(
        status: Literal["feasible", "impossible"],
        is_feasible: bool,
        reasons: Sequence[str],
        tolerance: Decimal | None = None,
        ratio_low: Decimal | None = None,
        ratio_high: Decimal | None = None,
        ratio_grid_low: Decimal | None = None,
        ratio_grid_high: Decimal | None = None,
        amount_low: Decimal | None = None,
        amount_high: Decimal | None = None,
        effective_ratio_low: Decimal | None = None,
        effective_ratio_high: Decimal | None = None,
        effective_amount_low: Decimal | None = None,
        effective_amount_high: Decimal | None = None,
        lwlt_status: LwltStatus = initial_lwlt_status,
    ) -> PassBidRangeResult:
        return PassBidRangeResult(
            status=status,
            is_feasible=is_feasible,
            reasons=tuple(reasons),
            pass_threshold=pass_threshold,
            non_price_score=non_price_score,
            required_price_score=required,
            base_rate_ratio=base_ratio,
            max_price_score=max_price_score,
            multiplier=multiplier,
            pred_price=pred_price,
            tolerance=tolerance,
            ratio_low=ratio_low,
            ratio_high=ratio_high,
            ratio_grid_low=ratio_grid_low,
            ratio_grid_high=ratio_grid_high,
            amount_low=amount_low,
            amount_high=amount_high,
            lwlt_status=lwlt_status,
            lwlt_rate_ratio=lwlt_ratio,
            lwlt_amount=lwlt_amount,
            effective_ratio_low=effective_ratio_low,
            effective_ratio_high=effective_ratio_high,
            effective_amount_low=effective_amount_low,
            effective_amount_high=effective_amount_high,
        )

    if multiplier == ZERO:
        if max_price_score < required:
            return build(
                status="impossible",
                is_feasible=False,
                reasons=[
                    f"평점 계수가 0이면 가격점수는 배점한도 {max_price_score}점으로 고정되어 "
                    f"필요한 최소 가격점수 {required}점에 도달할 수 없습니다."
                ],
            )
        tolerance: Decimal | None = None
        ratio_low = ZERO
        ratio_high = ONE
        extra_reasons: list[str] = []
    else:
        if max_price_score < required:
            return build(
                status="impossible",
                is_feasible=False,
                reasons=[
                    f"필요한 최소 가격점수 {required}점이 배점한도 {max_price_score}점을 초과하여 "
                    "만점으로도 통과할 수 없습니다."
                ],
            )
        tolerance = (max_price_score - required) / (HUNDRED * multiplier)
        ratio_low = max(ZERO, base_ratio - tolerance)
        algebra_high = min(ONE, base_ratio + tolerance)
        extra_reasons = []
        if (
            flat_ratio is not None
            and flat_score is not None
            and flat_ratio <= ONE
            and flat_score >= required
        ):
            if flat_ratio <= algebra_high:
                # 평탄 구간이 산식 통과 구간과 이어져 하나의 연속 구간이 됩니다.
                ratio_high = ONE
            else:
                # 평탄 구간이 필요점수를 충족하지만 산식 통과 구간과 떨어져 있어 통과
                # 구간이 둘로 나뉩니다. 단일 연속 구간만 표현할 수 있으므로 기준비율을
                # 포함한 산식 구간을 돌려주고, 평탄 구간도 통과함을 사유로 남깁니다.
                ratio_high = algebra_high
                flat_plain = format_decimal_plain(flat_ratio)
                extra_reasons.append(
                    f"평탄 구간(비율 {flat_plain} 이상)이 필요 가격점수를 충족하지만 "
                    "산식 통과 구간과 떨어져 있어 통과 구간이 둘로 나뉩니다. "
                    "단일 연속 구간으로 표현할 수 없어 산식 통과 구간만 표시하며, "
                    f"평탄 구간(비율 {flat_plain} ~ 1)도 통과합니다."
                )
        else:
            ratio_high = algebra_high

    # 평탄 고정 점수가 필요 가격점수에 미달하면 x >= flat_ratio 구간은 통과하지 못한다.
    # 통과 상한이 평탄 시작 비율 이상이면 그 아래로 잘라 실제 점수 곡선과 맞춘다.
    flat_cut_ratio: Decimal | None = None
    if (
        flat_ratio is not None
        and flat_score is not None
        and flat_ratio <= ONE
        and flat_score < required
        and ratio_high >= flat_ratio
    ):
        flat_cut_ratio = flat_ratio
        ratio_high = flat_ratio
        extra_reasons.append(
            f"평탄 구간(비율 {format_decimal_plain(flat_ratio)} 이상)의 고정 점수 "
            f"{format_decimal_plain(flat_score)}점이 필요 가격점수 "
            f"{format_decimal_plain(required)}점에 미달하여 통과하지 못합니다. "
            "비율이 평탄 시작 이상이면 점수가 그 값으로 떨어지므로 "
            "통과 상한을 평탄 시작 비율 미만으로 잘랐습니다."
        )

    if multiplier == ZERO and flat_cut_ratio is None:
        extra_reasons.append(
            "평점 계수가 0이면 가격점수는 배점한도로 고정되므로 비율 구간 전체가 통과 구간입니다."
        )

    grid_low = ratio_low.quantize(FOUR_DECIMALS, rounding=ROUND_CEILING)
    if flat_cut_ratio is not None:
        # x >= flat_ratio 는 평탄으로 점수가 떨어지므로 그 미만에서 가장 큰 격자값을 쓴다.
        grid_high = flat_cut_ratio.quantize(FOUR_DECIMALS, rounding=ROUND_CEILING) - FOUR_DECIMALS
    else:
        grid_high = ratio_high.quantize(FOUR_DECIMALS, rounding=ROUND_FLOOR)
    if grid_low > grid_high:
        return build(
            status="impossible",
            is_feasible=False,
            reasons=[
                "허용 비율 구간이 소수점 넷째 자리 격자를 포함하지 않아 "
                "원 단위 입찰가로 도달할 수 없습니다."
            ],
            tolerance=tolerance,
            ratio_low=ratio_low,
            ratio_high=ratio_high,
            ratio_grid_low=grid_low,
            ratio_grid_high=grid_high,
        )
    amount_low = max(
        ZERO,
        (pred_price * (grid_low - HALF_UNIT)).to_integral_value(rounding=ROUND_CEILING),
    )
    amount_high = min(
        pred_price,
        (pred_price * (grid_high + HALF_UNIT)).to_integral_value(rounding=ROUND_CEILING) - ONE,
    )
    if amount_low > amount_high:
        return build(
            status="impossible",
            is_feasible=False,
            reasons=["허용 비율 구간에 해당하는 원 단위 금액이 존재하지 않아 도달할 수 없습니다."],
            tolerance=tolerance,
            ratio_low=ratio_low,
            ratio_high=ratio_high,
            ratio_grid_low=grid_low,
            ratio_grid_high=grid_high,
        )

    effective_ratio_low: Decimal | None = ratio_low
    effective_ratio_high: Decimal | None = ratio_high
    effective_amount_low: Decimal | None = amount_low
    effective_amount_high: Decimal | None = amount_high
    resolved_lwlt_status = initial_lwlt_status
    lwlt_reasons: list[str] = []

    if lwlt_amount is not None and lwlt_ratio is not None:
        if amount_high < lwlt_amount:
            resolved_lwlt_status = "excludes_all"
            effective_ratio_low = None
            effective_ratio_high = None
            effective_amount_low = None
            effective_amount_high = None
            lwlt_reasons.append(
                f"평점 통과 금액 상한 {amount_high:,}원이 낙찰하한율 금액 {lwlt_amount:,}원보다 "
                "낮아 하한율까지 만족하는 통과 입찰가가 없습니다."
            )
        else:
            resolved_lwlt_status = "within_range"
            effective_amount_low = max(amount_low, lwlt_amount)
            effective_ratio_low = max(ratio_low, lwlt_ratio)

    status: Literal["feasible", "impossible"] = (
        "impossible" if resolved_lwlt_status == "excludes_all" else "feasible"
    )

    return build(
        status=status,
        is_feasible=status == "feasible",
        reasons=[*extra_reasons, *lwlt_reasons],
        tolerance=tolerance,
        ratio_low=ratio_low,
        ratio_high=ratio_high,
        ratio_grid_low=grid_low,
        ratio_grid_high=grid_high,
        amount_low=amount_low,
        amount_high=amount_high,
        effective_ratio_low=effective_ratio_low,
        effective_ratio_high=effective_ratio_high,
        effective_amount_low=effective_amount_low,
        effective_amount_high=effective_amount_high,
        lwlt_status=resolved_lwlt_status,
    )
