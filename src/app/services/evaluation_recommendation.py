"""
src/app/services/evaluation_recommendation.py

무상태 투찰가 추천 계산의 순수 함수 모음.

설계 문서: docs/design/web_feedback_redesign_20261006.md 5.3, 5.4

이 모듈은 DB·HTTP·시스템 시각에 의존하지 않습니다. 사정률 범위를 인자로 받는
`compute_price_bounds` 가 최저가·최상가를 확정하며, 나중에 실측 분포(min_rate/max_rate)를
주입할 수 있도록 범위를 호출자가 정합니다. 통과 투찰률 구간 역산은
price_score_verification.invert_pass_bid_range 를, 평점 산식은 evaluation_scoring 을
재사용하고 이 모듈에서 다시 구현하지 않습니다.

결격 입력이 없는 경우(None)는 '미확인'으로 다루되 점수 계산은 결격 없이 수행합니다.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from src.app.services.evaluation_rules import find_reputation_item
from src.app.services.evaluation_scoring import WON_UNIT
from src.app.services.price_score_verification import invert_pass_bid_range

# 사정률 범위 출처. theoretical 은 과거 실측이 아니라 이론 범위임을 뜻합니다.
RATE_SOURCE_THEORETICAL = "theoretical"
RATE_SOURCE_MEASURED = "measured"

THEORETICAL_RATE_NOTICE = (
    "과거 실측 사정률이 아니라 이론 범위(기초금액 ±2%/±3%)입니다. 실제 사정률과 다를 수 있습니다."
)


def disqualification_status(value: bool | None) -> Literal["not_checked", "clear", "disqualified"]:
    """결격 입력을 응답 상태 문구로 바꿉니다. 생략(None)은 '미확인'입니다."""
    if value is None:
        return "not_checked"
    return "disqualified" if value else "clear"


def has_disqualification(value: bool | None) -> bool:
    """점수 계산용 결격 여부. '미확인'(None)은 결격 없이 계산합니다(하위 호환)."""
    return bool(value)


def theoretical_rate_range(range_rate: Decimal) -> tuple[Decimal, Decimal]:
    """이론 사정률 범위(예: 0.02)를 예정가격 배수 (하한, 상한) 으로 바꿉니다."""
    if range_rate < 0:
        raise ValueError("사정률 범위는 0 이상이어야 합니다.")
    if range_rate >= 1:
        raise ValueError("사정률 범위는 1 미만이어야 합니다.")
    return Decimal("1") - range_rate, Decimal("1") + range_rate


@dataclass(frozen=True)
class PriceBoundsResult:
    """사정률 하한·상한 시나리오의 통과 투찰금액 구간.

    min_bid_amount·max_bid_amount 는 각 시나리오 예정가격에서 통과점수를 넘기는 금액이며
    낙찰하한율 이상입니다. status 가 blocked 면 reasons 에 사유가 담기고 금액은 None 입니다.
    """

    status: Literal["ok", "blocked"]
    rate_low: Decimal
    rate_high: Decimal
    min_bid_amount: Decimal | None = None
    max_bid_amount: Decimal | None = None
    min_pred_price: Decimal | None = None
    max_pred_price: Decimal | None = None
    ratio_low: Decimal | None = None
    ratio_high: Decimal | None = None
    required_price_score: Decimal | None = None
    reasons: tuple[str, ...] = ()


def _blocked_bounds(
    rate_low: Decimal,
    rate_high: Decimal,
    reasons: Sequence[str],
    *,
    min_pred_price: Decimal | None = None,
    max_pred_price: Decimal | None = None,
) -> PriceBoundsResult:
    return PriceBoundsResult(
        status="blocked",
        rate_low=rate_low,
        rate_high=rate_high,
        min_pred_price=min_pred_price,
        max_pred_price=max_pred_price,
        reasons=tuple(reasons),
    )


def compute_price_bounds(
    *,
    base_amount: Decimal,
    rate_low: Decimal,
    rate_high: Decimal,
    pass_threshold: Decimal,
    non_price_score: Decimal,
    base_rate: Decimal,
    max_price_score: Decimal,
    multiplier: Decimal,
    announcement_lwlt_rate: Decimal,
    flat_ratio: Decimal | None = None,
    flat_score: Decimal | None = None,
) -> PriceBoundsResult:
    """사정률 하한·상한 시나리오에서 통과점수를 넘기는 최저가·최상가를 확정합니다.

    [산식]
    필요 가격점수 P = T - S 를 invert_pass_bid_range 로 통과 투찰률 구간으로 바꾼 뒤,
    최저가 = 사정률 하한 예정가격(기초금액 * rate_low) 의 통과 금액 하한,
    최상가 = 사정률 상한 예정가격(기초금액 * rate_high) 의 통과 금액 상한입니다.

    invert_pass_bid_range 의 유효 금액(effective_amount_*)을 그대로 쓰므로 두 금액 모두
    낙찰하한율 이상이고, 원 단위 격자와 평탄 규정이 반영됩니다. 사정률 범위(rate_low·
    rate_high)를 인자로 받아, 실측 분포가 확보되면 이 값만 바꿔 주입할 수 있습니다.
    """
    reasons: list[str] = []
    if base_amount <= 0:
        return _blocked_bounds(rate_low, rate_high, ["기초금액이 0보다 커야 합니다."])
    if rate_low <= 0 or rate_high <= 0:
        return _blocked_bounds(rate_low, rate_high, ["사정률 범위는 0보다 커야 합니다."])
    if rate_high < rate_low:
        return _blocked_bounds(
            rate_low, rate_high, ["사정률 상한이 하한보다 작아 구간을 정할 수 없습니다."]
        )

    min_pred_price = (base_amount * rate_low).quantize(WON_UNIT, rounding=ROUND_HALF_UP)
    max_pred_price = (base_amount * rate_high).quantize(WON_UNIT, rounding=ROUND_HALF_UP)

    low_result = invert_pass_bid_range(
        pass_threshold=pass_threshold,
        non_price_score=non_price_score,
        base_rate=base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
        pred_price=min_pred_price,
        announcement_lwlt_rate=announcement_lwlt_rate,
        flat_ratio=flat_ratio,
        flat_score=flat_score,
    )
    if low_result.effective_amount_low is None:
        reasons.extend(
            low_result.reasons
            or ["사정률 하한 시나리오에서 통과 가능한 최저 투찰금액을 확정하지 못했습니다."]
        )
        return _blocked_bounds(
            rate_low,
            rate_high,
            reasons,
            min_pred_price=min_pred_price,
            max_pred_price=max_pred_price,
        )

    high_result = invert_pass_bid_range(
        pass_threshold=pass_threshold,
        non_price_score=non_price_score,
        base_rate=base_rate,
        max_price_score=max_price_score,
        multiplier=multiplier,
        pred_price=max_pred_price,
        announcement_lwlt_rate=announcement_lwlt_rate,
        flat_ratio=flat_ratio,
        flat_score=flat_score,
    )
    if high_result.effective_amount_high is None:
        reasons.extend(
            high_result.reasons
            or ["사정률 상한 시나리오에서 통과 가능한 최고 투찰금액을 확정하지 못했습니다."]
        )
        return _blocked_bounds(
            rate_low,
            rate_high,
            reasons,
            min_pred_price=min_pred_price,
            max_pred_price=max_pred_price,
        )

    min_bid_amount = low_result.effective_amount_low
    max_bid_amount = high_result.effective_amount_high
    if min_bid_amount > max_bid_amount:
        return _blocked_bounds(
            rate_low,
            rate_high,
            ["최저가가 최상가보다 커 통과 구간을 확정할 수 없습니다."],
            min_pred_price=min_pred_price,
            max_pred_price=max_pred_price,
        )

    return PriceBoundsResult(
        status="ok",
        rate_low=rate_low,
        rate_high=rate_high,
        min_bid_amount=min_bid_amount,
        max_bid_amount=max_bid_amount,
        min_pred_price=min_pred_price,
        max_pred_price=max_pred_price,
        ratio_low=low_result.effective_ratio_low,
        ratio_high=high_result.effective_ratio_high,
        required_price_score=low_result.required_price_score,
    )


@dataclass(frozen=True)
class ReputationConversion:
    """회원 신인도 원자료의 평점 환산 결과.

    values 는 항목별 평점입니다. 회원이 고른 평점(dict)은 그대로 쓰고, 구형 항목 코드
    목록(list)은 선택지가 하나로 정해지는 항목만 자동 환산합니다. needs_grade_selection 은
    원자료만으로 평점을 정할 수 없어 회원 평점 선택이 필요한 항목 코드입니다.
    """

    values: dict[str, float] = field(default_factory=dict)
    needs_grade_selection: list[str] = field(default_factory=list)


def convert_reputation_codes(
    items: Mapping[str, float] | Sequence[str] | None,
) -> ReputationConversion:
    """신인도 원자료를 평점으로 환산합니다.

    저장 형식은 두 가지를 함께 받습니다. 회원이 고른 항목별 평점(dict)은 값을 그대로 쓰고,
    구형 항목 코드 목록(list)은 별표 11 항목의 선택지가 하나일 때만 자동 환산합니다. 복수
    선택지·구간 항목은 코드만으로 평점을 정할 수 없으므로 추측하지 않고
    needs_grade_selection 으로 돌려주어 요청 수정값(reputation_items)으로 지정하게 합니다.
    """
    if items is None:
        return ReputationConversion()
    values: dict[str, float] = {}
    needs: list[str] = []
    if isinstance(items, Mapping):
        for raw_code, raw_value in items.items():
            code = str(raw_code).strip()
            if not code:
                continue
            item = find_reputation_item(code)
            if item is None:
                needs.append(code)
                continue
            try:
                values[code] = float(raw_value)
            except (TypeError, ValueError):
                needs.append(code)
        return ReputationConversion(values=values, needs_grade_selection=needs)
    for raw in items:
        code = str(raw).strip()
        if not code:
            continue
        item = find_reputation_item(code)
        if item is None:
            needs.append(code)
            continue
        if len(item.options) == 1:
            values[code] = float(item.options[0])
        else:
            needs.append(code)
    return ReputationConversion(values=values, needs_grade_selection=needs)


@dataclass(frozen=True)
class ParticipantCountSummary:
    """발주처 과거 참가업체 수 요약 (금액 산식에는 넣지 않음)."""

    sample_count: int = 0
    average: Decimal | None = None
    minimum: int | None = None
    maximum: int | None = None


def extract_participant_count(raw_data: dict | None) -> int | None:
    """낙찰 결과 raw_data 의 참가업체 수(prtcptCnum)를 정수로 읽습니다. 없으면 None."""
    if not isinstance(raw_data, dict):
        return None
    value = raw_data.get("prtcptCnum")
    if value is None:
        return None
    try:
        count = int(str(value).strip())
    except (ArithmeticError, TypeError, ValueError):
        return None
    return count if count > 0 else None


def summarize_participant_counts(counts: Sequence[int] | None) -> ParticipantCountSummary:
    """참가업체 수 목록의 평균·최소·최대와 표본 수를 냅니다. float 를 거치지 않습니다."""
    valid = [int(count) for count in counts or () if count and count > 0]
    if not valid:
        return ParticipantCountSummary()
    total = sum(valid)
    average = (Decimal(total) / Decimal(len(valid))).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    return ParticipantCountSummary(
        sample_count=len(valid),
        average=average,
        minimum=min(valid),
        maximum=max(valid),
    )


@dataclass(frozen=True)
class NonPriceBreakdown:
    """회원 정량점수 S 의 항목별 내역. 합계는 performance + labor_plan + reputation."""

    performance: Decimal
    management: Decimal
    labor_plan: Decimal
    reputation: Decimal

    @property
    def total(self) -> Decimal:
        return self.performance + self.labor_plan + self.reputation


def build_non_price_breakdown(
    *, performance: Decimal, management: Decimal, labor_plan: Decimal, reputation: Decimal
) -> NonPriceBreakdown:
    """경영상태를 수행능력에서 분리해 항목별 내역을 만듭니다.

    performance 는 경영상태를 포함한 수행능력 계이고, management 는 그중 경영상태 몫입니다.
    합계(total)는 기존 정량점수 S 와 같습니다.
    """
    return NonPriceBreakdown(
        performance=performance,
        management=management,
        labor_plan=labor_plan,
        reputation=reputation,
    )
