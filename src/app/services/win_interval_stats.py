"""
src/app/services/win_interval_stats.py

용역 적격 과거 낙찰의 `승리 구간 중앙값`(기초금액 대비 %) 분포를
`win_interval_stats` 로 재집계하고, 그 분포에서 사용자별로 서로 다른 분위를
결정론적으로 골라 추천 투찰가를 계산합니다.

정의(백테스트 보고서 2장):
  - `s = P/B*100`(사정률), `r = W/P*100`(낙찰률), `m = r - L`(낙찰 마진)
  - 승리 구간은 `[L*s/100, s*(L+m)/100)`, 중앙값은 두 끝점의 평균
  - 낙찰률은 같은 하한율(소수 3자리) 표본으로 조건화하고, 그 표본이 최소치에
    못 미치면 같은 범위의 `m` 분포를 현재 `L` 에 더해 근사합니다.
  - 범위 대체는 발주처 -> 시·도 -> 업종 순입니다.

사용자 분산은 적격심사 점수가 같은 서로 다른 사용자가 같은 공고에서 같은
추천가를 받지 않게 하려는 것입니다. `user_key:notice_key` 의 sha256 으로
25~75% 구간의 한 점을 고르므로 같은 입력은 항상 같은 값을 냅니다.

분위표가 회원 하한 아래에 있으면 역사적 p25~p75 폭을 그대로 하한 위로
평행이동합니다. 하한을 넘는 분위 조각이 일부면 그 조각에만 해시를 대응시켜,
클립으로 여러 사용자가 한 금액에 모이는 일을 막습니다.

정의 근거: docs/analysis/win_prob_backtest_20261125.md 2장, 6장.
"""

from __future__ import annotations

import hashlib
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from decimal import ROUND_CEILING, ROUND_HALF_UP, Decimal, InvalidOperation
from itertools import pairwise
from typing import Any, Literal

from sqlalchemy import Numeric, and_, cast, delete, select

from src.app.core.timeutil import kst_now, utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.prearng_prices import BidPrearngPrice, WinIntervalStat
from src.app.services.sajeong_rate_stats import derive_sido

logger = logging.getLogger(__name__)

DEFAULT_WINDOW_DAYS = 365
MIN_INSTITUTION_SAMPLES = 30
MIN_REGION_SAMPLES = 50
MIN_CATEGORY_SAMPLES = 30
MIN_EXACT_SAMPLES = 30

CATEGORY = "Servc"
SCOPE_INSTITUTION = "institution"
SCOPE_REGION = "region"
SCOPE_CATEGORY = "category"

LOWER_BOUND_MIN = Decimal("70")
LOWER_BOUND_MAX = Decimal("100")

QUANTILE_PERCENTILES = tuple(range(5, 100, 5))
WIN_INTERVAL_QUANTILE_COLUMNS = tuple(f"p{percentile:02d}" for percentile in QUANTILE_PERCENTILES)
WIN_INTERVAL_QUANTILE_COUNT = len(WIN_INTERVAL_QUANTILE_COLUMNS)
FIRST_QUANTILE = Decimal(QUANTILE_PERCENTILES[0]) / 100
LAST_QUANTILE = Decimal(QUANTILE_PERCENTILES[-1]) / 100

DEFAULT_DISPERSION_BAND = (Decimal("0.25"), Decimal("0.75"))
SOURCE_INTERVAL: Literal["interval"] = "interval"
SOURCE_FALLBACK: Literal["fallback"] = "fallback"

_RATE_QUANTUM = Decimal("0.0001")
_LWLT_QUANTUM = Decimal("0.001")
_WON_UNIT = Decimal("1")
_HUNDRED = Decimal("100")
_RATE_DENOMINATOR = Decimal("10000")
_HASH_DENOMINATOR = Decimal(0xFFFFFFFF)

# (하한율, 사정률, 낙찰 마진). 마진은 항상 0보다 큽니다.
_Record = tuple[Decimal, Decimal, Decimal]


def _to_decimal(value: Any, name: str) -> Decimal:
    try:
        result = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{name} 값을 Decimal 로 해석할 수 없습니다.") from exc
    if not result.is_finite():
        raise ValueError(f"{name} 값이 유한한 수가 아닙니다.")
    return result


def _quantize_rate(value: float | Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(_RATE_QUANTUM, rounding=ROUND_HALF_UP)


def _percentile(sorted_values: list[float], quantile: float) -> float | None:
    """선형 보간 백분위수. 빈 목록이면 None 입니다."""
    if not sorted_values:
        return None
    if len(sorted_values) == 1:
        return sorted_values[0]
    position = (len(sorted_values) - 1) * quantile
    lower = int(position)
    upper = min(lower + 1, len(sorted_values) - 1)
    fraction = position - lower
    return sorted_values[lower] * (1.0 - fraction) + sorted_values[upper] * fraction


def _interval_midpoint(lwlt_rate: Decimal, sajeong_rate: Decimal, margin: Decimal) -> Decimal:
    """승리 구간 `[L*s/100, s*(L+m)/100)` 의 중앙값을 돌려줍니다."""
    low = lwlt_rate * sajeong_rate / _HUNDRED
    high = sajeong_rate * (lwlt_rate + margin) / _HUNDRED
    return (low + high) / 2


def _scope_rows(
    scope: str,
    groups: dict[tuple[str, str], list[_Record]],
    *,
    min_samples: int,
    min_exact_samples: int,
    window_days: int,
    rebuilt_at: Any,
) -> list[dict[str, Any]]:
    """한 범위의 표본을 하한율별로 나눠 분위 행을 만듭니다.

    같은 하한율 표본이 `min_exact_samples` 이상이면 그 표본만 씁니다. 모자라면
    같은 범위 전체의 마진 분포를 현재 하한율에 더해 근사합니다(보고서 2.3).
    범위 전체 표본이 `min_samples` 미만이면 행을 만들지 않습니다.
    """
    rows: list[dict[str, Any]] = []
    for (scope_name, category_key), values in groups.items():
        if len(values) < min_samples:
            continue
        exact_groups: dict[Decimal, list[tuple[Decimal, Decimal]]] = {}
        for lwlt_rate, sajeong_rate, margin in values:
            exact_groups.setdefault(lwlt_rate, []).append((sajeong_rate, margin))

        for lwlt_rate, exact_pairs in exact_groups.items():
            if len(exact_pairs) >= min_exact_samples:
                pairs = exact_pairs
                sample_count = len(exact_pairs)
            else:
                pairs = [(sajeong_rate, margin) for _, sajeong_rate, margin in values]
                sample_count = len(values)

            midpoints = sorted(
                float(_interval_midpoint(lwlt_rate, sajeong_rate, margin))
                for sajeong_rate, margin in pairs
            )
            row: dict[str, Any] = {
                "scope": scope,
                "institution_name": scope_name,
                "category": category_key,
                "lwlt_rate": lwlt_rate,
                "window_days": window_days,
                "sample_count": sample_count,
                "rebuilt_at": rebuilt_at,
            }
            for percentile, column in zip(
                QUANTILE_PERCENTILES, WIN_INTERVAL_QUANTILE_COLUMNS, strict=True
            ):
                row[column] = _quantize_rate(_percentile(midpoints, percentile / 100))
            rows.append(row)
    return rows


def rebuild_win_interval_stats(
    session: Any,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
    min_institution_samples: int = MIN_INSTITUTION_SAMPLES,
    min_region_samples: int = MIN_REGION_SAMPLES,
    min_category_samples: int = MIN_CATEGORY_SAMPLES,
    min_exact_samples: int = MIN_EXACT_SAMPLES,
) -> dict[str, Any]:
    """`win_interval_stats` 를 통째로 다시 만듭니다.

    `bid_prearng_prices` 를 `bid_results`, `bid_announcements` 와 고유 키로 조인해
    한 번만 스캔하고, 발주처 -> 시·도 -> 업종 세 범위를 함께 만듭니다. 용역
    (`category='Servc'`) 이고 하한율이 70~100% 인 적격 표본만 씁니다.
    """
    cutoff = kst_now(utcnow()) - timedelta(days=window_days)
    lwlt_expr = cast(
        BidAnnouncement.raw_data["sucsfbidLwltRate"].as_string(),
        Numeric(10, 3),
    )
    stmt = (
        select(
            BidPrearngPrice.dminstt_nm,
            BidPrearngPrice.category,
            BidPrearngPrice.bssamt,
            BidPrearngPrice.plnprc,
            BidResult.sucsf_bid_amt,
            lwlt_expr,
        )
        .outerjoin(
            BidResult,
            and_(
                BidResult.bid_ntce_no == BidPrearngPrice.bid_ntce_no,
                BidResult.bid_ntce_ord == BidPrearngPrice.bid_ntce_ord,
                BidResult.category == BidPrearngPrice.category,
            ),
        )
        .outerjoin(
            BidAnnouncement,
            and_(
                BidAnnouncement.bid_ntce_no == BidPrearngPrice.bid_ntce_no,
                BidAnnouncement.bid_ntce_ord == BidPrearngPrice.bid_ntce_ord,
                BidAnnouncement.category == BidPrearngPrice.category,
            ),
        )
        .where(
            BidPrearngPrice.category == CATEGORY,
            BidPrearngPrice.bssamt.is_not(None),
            BidPrearngPrice.bssamt > 0,
            BidPrearngPrice.plnprc.is_not(None),
            BidPrearngPrice.plnprc > 0,
            BidPrearngPrice.rl_openg_dt.is_not(None),
            BidPrearngPrice.rl_openg_dt >= cutoff,
            BidResult.sucsf_bid_amt.is_not(None),
            BidResult.sucsf_bid_amt > 0,
            lwlt_expr.is_not(None),
            lwlt_expr >= LOWER_BOUND_MIN,
            lwlt_expr <= LOWER_BOUND_MAX,
        )
    )

    institution_groups: dict[tuple[str, str], list[_Record]] = {}
    region_groups: dict[tuple[str, str], list[_Record]] = {}
    category_groups: dict[tuple[str, str], list[_Record]] = {}

    for name, category, bssamt, plnprc, won_amount, lwlt in session.execute(stmt).yield_per(10_000):
        if bssamt is None or plnprc is None or won_amount is None or lwlt is None:
            continue
        lwlt_rate = Decimal(str(lwlt)).quantize(_LWLT_QUANTUM, rounding=ROUND_HALF_UP)
        if lwlt_rate < LOWER_BOUND_MIN or lwlt_rate > LOWER_BOUND_MAX:
            continue
        base_amount = Decimal(int(bssamt))
        pred_price = Decimal(int(plnprc))
        awarded_amount = Decimal(int(won_amount))
        sajeong_rate = pred_price / base_amount * _HUNDRED
        winning_rate = awarded_amount / pred_price * _HUNDRED
        margin = winning_rate - lwlt_rate
        if margin <= 0:
            continue

        category_key = str(category or CATEGORY)
        record: _Record = (lwlt_rate, sajeong_rate, margin)
        if name:
            institution_groups.setdefault((str(name), category_key), []).append(record)
            sido = derive_sido(str(name))
            if sido:
                region_groups.setdefault((sido, category_key), []).append(record)
        category_groups.setdefault(("", category_key), []).append(record)

    rebuilt_at = utcnow()
    rows = _scope_rows(
        SCOPE_INSTITUTION,
        institution_groups,
        min_samples=min_institution_samples,
        min_exact_samples=min_exact_samples,
        window_days=window_days,
        rebuilt_at=rebuilt_at,
    )
    rows.extend(
        _scope_rows(
            SCOPE_REGION,
            region_groups,
            min_samples=min_region_samples,
            min_exact_samples=min_exact_samples,
            window_days=window_days,
            rebuilt_at=rebuilt_at,
        )
    )
    rows.extend(
        _scope_rows(
            SCOPE_CATEGORY,
            category_groups,
            min_samples=min_category_samples,
            min_exact_samples=min_exact_samples,
            window_days=window_days,
            rebuilt_at=rebuilt_at,
        )
    )

    institution_rows = sum(1 for row in rows if row["scope"] == SCOPE_INSTITUTION)
    region_rows = sum(1 for row in rows if row["scope"] == SCOPE_REGION)
    category_rows = sum(1 for row in rows if row["scope"] == SCOPE_CATEGORY)

    session.execute(delete(WinIntervalStat))
    if rows:
        session.bulk_insert_mappings(WinIntervalStat, rows)
    session.commit()

    logger.info(
        "승리 구간 통계 재집계 완료: 전체 %d행 (기관 %d, 지역 %d, 업종 %d), 창 %d일, 기준 %s",
        len(rows),
        institution_rows,
        region_rows,
        category_rows,
        window_days,
        rebuilt_at.isoformat(),
    )

    return {
        "rows": len(rows),
        "institution_rows": institution_rows,
        "region_rows": region_rows,
        "category_rows": category_rows,
        "window_days": window_days,
        "rebuilt_at": rebuilt_at.isoformat(),
    }


def lookup_win_interval_quantiles(
    session: Any,
    institution_name: str | None,
    lwlt_rate: Decimal | float | str,
    category: str = CATEGORY,
    *,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> dict[str, Any] | None:
    """(수요기관명, 하한율) 의 승리 구간 중앙값 분위를 대체 순서로 조회합니다.

    발주처 -> 시·도 -> 업종 순으로 찾고, 같은 하한율 행이 어디에도 없으면
    None 을 돌려줍니다. 분위는 p05~p95 19개를 오름차순 튜플로 담습니다.
    """
    rate = Decimal(str(lwlt_rate)).quantize(_LWLT_QUANTUM, rounding=ROUND_HALF_UP)
    name = " ".join(str(institution_name or "").split())
    sido = derive_sido(name)
    category_key = str(category or CATEGORY)

    candidates: list[tuple[str, str]] = []
    if name:
        candidates.append((SCOPE_INSTITUTION, name))
    if sido:
        candidates.append((SCOPE_REGION, sido))
    candidates.append((SCOPE_CATEGORY, ""))

    columns = [
        WinIntervalStat.sample_count,
        *(getattr(WinIntervalStat, column) for column in WIN_INTERVAL_QUANTILE_COLUMNS),
    ]
    for scope, scope_name in candidates:
        row = session.execute(
            select(*columns).where(
                WinIntervalStat.scope == scope,
                WinIntervalStat.institution_name == scope_name,
                WinIntervalStat.category == category_key,
                WinIntervalStat.lwlt_rate == rate,
                WinIntervalStat.window_days == window_days,
            )
        ).one_or_none()
        if row is None:
            continue
        quantiles: list[Decimal] = []
        for value in row[1:]:
            quantized = _quantize_rate(value)
            if quantized is None:
                quantiles = []
                break
            quantiles.append(quantized)
        if len(quantiles) != WIN_INTERVAL_QUANTILE_COUNT:
            continue
        return {
            "scope": scope,
            "institution_name": scope_name,
            "category": category_key,
            "lwlt_rate": rate,
            "window_days": window_days,
            "sample_count": int(row[0]),
            "quantiles": tuple(quantiles),
        }
    return None


@dataclass(frozen=True)
class DispersedBid:
    """사용자별 분산 추천 한 건.

    `quantile` 은 고른 분위 확률(0~1), `bid_rate` 는 기초금액 대비 투찰률(%),
    `amount` 는 원 단위 투찰금액입니다. `source` 는 분포 사용 여부이고,
    `clipped` 는 회원 하한 때문에 금액을 올렸는지 여부입니다.
    """

    quantile: Decimal
    bid_rate: Decimal
    amount: int
    source: Literal["interval", "fallback"]
    clipped: bool


def _dispersion_unit(user_key: str, notice_key: str) -> Decimal:
    digest = hashlib.sha256(f"{user_key}:{notice_key}".encode()).hexdigest()
    return Decimal(int(digest[:8], 16)) / _HASH_DENOMINATOR


def _normalize_band(
    band: tuple[Decimal | float | str, Decimal | float | str],
) -> tuple[Decimal, Decimal]:
    try:
        low_value, high_value = band
    except (TypeError, ValueError) as exc:
        raise ValueError("band 는 (하한, 상한) 두 값이어야 합니다.") from exc
    low = _to_decimal(low_value, "band[0]")
    high = _to_decimal(high_value, "band[1]")
    if not (Decimal(0) <= low <= high <= Decimal(1)):
        raise ValueError("band 는 0 이상 1 이하이며 하한이 상한보다 작거나 같아야 합니다.")
    return low, high


def _interpolate_quantile(quantiles: Sequence[Decimal], quantile: Decimal) -> Decimal:
    """19개 분위(p05~p95) 사이를 선형 보간합니다.

    `quantile` 이 0.05 미만이면 p05, 0.95 초과면 p95 로 고정합니다.
    """
    if len(quantiles) != WIN_INTERVAL_QUANTILE_COUNT:
        raise ValueError(
            f"분위는 {WIN_INTERVAL_QUANTILE_COUNT}개여야 합니다(받은 값 {len(quantiles)}개)."
        )
    if any(later < earlier for earlier, later in pairwise(quantiles)):
        raise ValueError("분위는 오름차순이어야 합니다.")
    if quantile <= FIRST_QUANTILE:
        return quantiles[0]
    if quantile >= LAST_QUANTILE:
        return quantiles[-1]
    position = quantile * 20 - 1
    lower = int(position)
    upper = min(lower + 1, WIN_INTERVAL_QUANTILE_COUNT - 1)
    fraction = position - Decimal(lower)
    return quantiles[lower] + (quantiles[upper] - quantiles[lower]) * fraction


def _won_from_rate(base_amount: Decimal, rate_percent: Decimal) -> int:
    return int((base_amount * rate_percent / _HUNDRED).quantize(_WON_UNIT, rounding=ROUND_HALF_UP))


def _member_floor_amount(
    base_amount: Decimal,
    member_floor_rate: Decimal,
    center_sajeong_rate: Decimal,
) -> int:
    """회원 보완 투찰률과 p50 사정률로 최소 통과 금액을 원 단위 올림으로 구합니다.

    두 비율 모두 퍼센트이므로 100 으로 두 번 나눕니다(보완 투찰률 -> 비율,
    사정률 -> 예정가격). 이 값은 p50 사정률 시나리오의 하한입니다.
    """
    exact = base_amount * member_floor_rate * center_sajeong_rate / _RATE_DENOMINATOR
    return int(exact.to_integral_value(rounding=ROUND_CEILING))


def _effective_floor_rate(member_floor_rate: Decimal, center_sajeong_rate: Decimal) -> Decimal:
    """회원 하한 투찰률(%)을 기초금액 대비 투찰률(%)로 환산합니다."""
    return member_floor_rate * center_sajeong_rate / _HUNDRED


def _quantile_for_rate(quantiles: Sequence[Decimal], target: Decimal) -> Decimal:
    """분위표에서 `target` 투찰률에 처음 도달하는 분위를 선형 보간으로 구합니다."""
    if target <= quantiles[0]:
        return FIRST_QUANTILE
    if target >= quantiles[-1]:
        return LAST_QUANTILE
    for index in range(len(quantiles) - 1):
        left_rate = quantiles[index]
        right_rate = quantiles[index + 1]
        if target > right_rate:
            continue
        left_quantile = Decimal(QUANTILE_PERCENTILES[index]) / _HUNDRED
        right_quantile = Decimal(QUANTILE_PERCENTILES[index + 1]) / _HUNDRED
        if right_rate <= left_rate:
            return right_quantile
        fraction = (target - left_rate) / (right_rate - left_rate)
        return left_quantile + (right_quantile - left_quantile) * fraction
    return LAST_QUANTILE


@dataclass(frozen=True)
class _DispersionPlan:
    """회원 하한을 반영한 분산 구간과 해시 대응 방식.

    `interpolate` 가 참이면 `quantile_low`~`quantile_high` 구간을 보간해
    투찰률을 고르고, 거짓이면 역사적 폭만큼 하한 위로 평행이동한 구간에서
    고릅니다. `high_rate` 가 `low_rate` 와 같으면 폭이 없어 하한 한 금액입니다.
    """

    low_rate: Decimal
    high_rate: Decimal
    quantile_low: Decimal
    quantile_high: Decimal
    interpolate: bool

    @property
    def usable(self) -> bool:
        return self.high_rate > self.low_rate


def _dispersion_plan(
    values: Sequence[Decimal],
    low: Decimal,
    high: Decimal,
    floor_rate: Decimal,
) -> _DispersionPlan:
    """역사적 분위 폭을 회원 하한 위로 옮긴 분산 계획을 만듭니다."""
    low_rate = _interpolate_quantile(values, low)
    high_rate = _interpolate_quantile(values, high)
    width = high_rate - low_rate
    if width <= 0:
        return _DispersionPlan(floor_rate, floor_rate, low, high, interpolate=True)
    if low_rate >= floor_rate:
        return _DispersionPlan(low_rate, high_rate, low, high, interpolate=True)
    if high_rate < floor_rate:
        # 전 구간이 하한 아래이면 폭을 유지한 채 하한 위로 평행이동합니다.
        return _DispersionPlan(
            floor_rate,
            floor_rate + width,
            low,
            high,
            interpolate=False,
        )
    # 일부만 하한 위이면 하한에 닿는 분위부터 상단까지의 조각만 씁니다.
    quantile_low = _quantile_for_rate(values, floor_rate)
    if quantile_low >= high:
        return _DispersionPlan(floor_rate, floor_rate, low, high, interpolate=True)
    return _DispersionPlan(floor_rate, high_rate, quantile_low, high, interpolate=True)


def _plan_rate(values: Sequence[Decimal], plan: _DispersionPlan, unit: Decimal) -> Decimal:
    if not plan.usable:
        return plan.low_rate
    if not plan.interpolate:
        return plan.low_rate + (plan.high_rate - plan.low_rate) * unit
    quantile = plan.quantile_low + (plan.quantile_high - plan.quantile_low) * unit
    return _interpolate_quantile(values, quantile)


def user_dispersed_bid(
    base_amount: Decimal,
    quantiles: Sequence[Decimal] | None,
    member_floor_rate: Decimal,
    center_sajeong_rate: Decimal,
    user_key: str,
    notice_key: str,
    band: tuple[Decimal | float | str, Decimal | float | str] = DEFAULT_DISPERSION_BAND,
    floor_amount: int | None = None,
) -> DispersedBid:
    """사용자·공고별로 결정론적으로 다른 분위의 투찰가를 계산합니다.

    같은 `user_key`·`notice_key` 는 항상 같은 값을 냅니다. 분위가 없으면
    (`quantiles is None`) 현행 단일 추천과 같은 하한 금액을 돌려줍니다.
    분위가 있으면 기본 25~75% 폭을 회원 하한 위에 두고, 그 폭 안에서 해시로
    고른 한 점을 금액화합니다. 폭이 0 이면 하한 한 금액으로 클립합니다.

    `floor_amount` 는 호출자가 이미 확정한 회원 하한 금액(원)입니다. 넘기지
    않으면 투찰률과 사정률로 올림 계산합니다. 표시 하한이 별도로 있으면 그
    값을 넘겨 금액과 구간의 기준을 화면과 맞춥니다.

    DB·HTTP·시스템 시각에 의존하지 않는 순수 함수입니다.
    """
    base = _to_decimal(base_amount, "base_amount")
    floor_rate = _to_decimal(member_floor_rate, "member_floor_rate")
    center = _to_decimal(center_sajeong_rate, "center_sajeong_rate")
    if base <= 0:
        raise ValueError("base_amount 는 0보다 커야 합니다.")

    floor = (
        _member_floor_amount(base, floor_rate, center)
        if floor_amount is None
        else int(floor_amount)
    )
    if quantiles is None:
        return DispersedBid(
            quantile=Decimal("0.5"),
            bid_rate=(floor_rate * center / _HUNDRED).quantize(
                _RATE_QUANTUM, rounding=ROUND_HALF_UP
            ),
            amount=floor,
            source=SOURCE_FALLBACK,
            clipped=False,
        )

    values = tuple(_to_decimal(value, "quantiles") for value in quantiles)
    low, high = _normalize_band(band)
    unit = _dispersion_unit(str(user_key), str(notice_key))
    plan = _dispersion_plan(values, low, high, _effective_floor_rate(floor_rate, center))
    if plan.usable and plan.interpolate:
        quantile = plan.quantile_low + (plan.quantile_high - plan.quantile_low) * unit
    else:
        quantile = low + (high - low) * unit
    if plan.usable:
        amount = _won_from_rate(base, _plan_rate(values, plan, unit))
        if amount < floor:
            amount = floor
    else:
        amount = floor
    return DispersedBid(
        quantile=quantile,
        bid_rate=(Decimal(amount) / base * _HUNDRED).quantize(
            _RATE_QUANTUM, rounding=ROUND_HALF_UP
        ),
        amount=amount,
        source=SOURCE_INTERVAL,
        clipped=not plan.usable,
    )


def dispersed_band_amounts(
    base_amount: Decimal,
    quantiles: Sequence[Decimal],
    member_floor_rate: Decimal,
    center_sajeong_rate: Decimal,
    band: tuple[Decimal | float | str, Decimal | float | str] = DEFAULT_DISPERSION_BAND,
    floor_amount: int | None = None,
) -> tuple[int, int]:
    """공고 단위 분산 구간의 하단·상단 금액을 계산합니다.

    회원 하한을 반영한 같은 구간이므로 모든 사용자에게 같은 값입니다.
    사용자별 금액은 이 두 값 사이에 있습니다.
    """
    base = _to_decimal(base_amount, "base_amount")
    floor_rate = _to_decimal(member_floor_rate, "member_floor_rate")
    center = _to_decimal(center_sajeong_rate, "center_sajeong_rate")
    if base <= 0:
        raise ValueError("base_amount 는 0보다 커야 합니다.")
    floor = (
        _member_floor_amount(base, floor_rate, center)
        if floor_amount is None
        else int(floor_amount)
    )
    values = tuple(_to_decimal(value, "quantiles") for value in quantiles)
    low, high = _normalize_band(band)
    plan = _dispersion_plan(values, low, high, _effective_floor_rate(floor_rate, center))
    if not plan.usable:
        return floor, floor
    low_amount = max(_won_from_rate(base, plan.low_rate), floor)
    high_amount = max(_won_from_rate(base, plan.high_rate), low_amount)
    return low_amount, high_amount
