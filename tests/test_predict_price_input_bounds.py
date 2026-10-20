"""predict-price 배점표 입력 상한과 낙찰하한율 미상 처리 시험.

두 가지를 함께 지킨다.

- 공고문 적격심사 배점표는 100점 만점이므로 B·k·T·Q 는 0 초과 100 이하만 받는다.
  범위 밖 값은 Pydantic 이 거부하고 predict-price 엔드포인트는 422 를 돌려준다.
- compute_price_bounds 의 announcement_lwlt_rate 는 공고 낙찰하한율이라 None(미상)을
  받을 수 있다. None 이면 하한율 제약이 없는 통과 구간이 나오고, 하한율을 준 경우보다
  하한 금액이 낮거나 같다.

DB·Redis·실제 모델 추론은 호출하지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from pydantic import ValidationError

from src.app.schemas.predictions import PredictPriceRequest
from src.app.services.evaluation_recommendation import compute_price_bounds

# 배점표 사용자 입력 4종. 모두 100점 만점 안쪽이다.
SCORE_TABLE_FIELDS = ("max_price_score", "multiplier", "pass_threshold", "non_price_score")

# 사정률 하한·상한이 확정된 상태의 공고 하나를 전제로 한 산식 입력.
BOUNDS_BASE = {
    "base_amount": Decimal("500000000"),
    "rate_low": Decimal("0.98"),
    "rate_high": Decimal("1.02"),
    "pass_threshold": Decimal("95"),
    "non_price_score": Decimal("40"),
    "base_rate": Decimal("0.93"),
    "max_price_score": Decimal("60"),
    "multiplier": Decimal("2"),
}


# --------------------------------------------------------------------------- #
# 1. 배점표 입력 상한
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("field_name", SCORE_TABLE_FIELDS)
def test_score_table_upper_bound_accepts_100(field_name: str) -> None:
    """상한 100 은 만점 경계값이라 그대로 통과한다."""
    payload = PredictPriceRequest(bid_id=1, **{field_name: 100.0})

    assert getattr(payload, field_name) == 100.0


@pytest.mark.parametrize("field_name", SCORE_TABLE_FIELDS)
def test_score_table_upper_bound_rejects_101(field_name: str) -> None:
    """상한 101 은 만점을 넘으므로 Pydantic 이 거부한다(엔드포인트는 422)."""
    with pytest.raises(ValidationError):
        PredictPriceRequest(bid_id=1, **{field_name: 101.0})


def test_score_table_lower_bound_still_rejects_zero() -> None:
    """상한을 넣어도 하한 조건(0 초과)은 그대로 남는다."""
    with pytest.raises(ValidationError):
        PredictPriceRequest(bid_id=1, max_price_score=0.0)


# --------------------------------------------------------------------------- #
# 2. 공고 낙찰하한율 미상(None) 처리
# --------------------------------------------------------------------------- #


def test_compute_price_bounds_accepts_missing_lwlt_rate() -> None:
    """공고 낙찰하한율이 미상(None)이면 예외 없이 통과 구간이 나온다."""
    result = compute_price_bounds(announcement_lwlt_rate=None, **BOUNDS_BASE)

    assert result.status == "ok", result.reasons
    assert result.reasons == ()
    assert result.min_bid_amount is not None
    assert result.max_bid_amount is not None
    assert result.min_bid_amount <= result.max_bid_amount


@pytest.mark.parametrize("lwlt_rate", [Decimal("89.995"), Decimal("95")])
def test_missing_lwlt_rate_min_amount_is_not_higher(lwlt_rate: Decimal) -> None:
    """하한율 미상(None)의 하한 금액은 하한율을 준 경우보다 낮거나 같다."""
    without_lwlt = compute_price_bounds(announcement_lwlt_rate=None, **BOUNDS_BASE)
    with_lwlt = compute_price_bounds(announcement_lwlt_rate=lwlt_rate, **BOUNDS_BASE)

    assert without_lwlt.status == "ok", without_lwlt.reasons
    assert with_lwlt.status == "ok", with_lwlt.reasons
    assert without_lwlt.min_bid_amount is not None
    assert with_lwlt.min_bid_amount is not None
    assert without_lwlt.min_bid_amount <= with_lwlt.min_bid_amount


def test_missing_lwlt_rate_keeps_pass_range_unconstrained() -> None:
    """하한율이 통과 구간을 실제로 묶는 값이면, 미상(None)은 묶이지 않은 구간을 돌려준다."""
    without_lwlt = compute_price_bounds(announcement_lwlt_rate=None, **BOUNDS_BASE)
    with_lwlt = compute_price_bounds(announcement_lwlt_rate=Decimal("95"), **BOUNDS_BASE)

    assert without_lwlt.min_bid_amount is not None
    assert with_lwlt.min_bid_amount is not None
    assert without_lwlt.min_bid_amount < with_lwlt.min_bid_amount
    # 상한은 하한율과 무관하므로 두 경우에 같다.
    assert without_lwlt.max_bid_amount == with_lwlt.max_bid_amount
