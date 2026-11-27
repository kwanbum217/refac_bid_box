"""
tests/test_dispersed_bid_floor_band_20261126.py

회원 하한 아래 분위표에서도 사용자별 분산 추천가가 한 금액으로 모이지 않는지
검증합니다.

막으려는 사고:
  - 역사적 p25~p75 폭이 전부 회원 하한 아래일 때 모든 사용자가 하한 한
    금액으로 클립되는 것 (2026-11-25 분산 결정 붕괴)
  - 하한 위로 올릴 때 역사적 폭을 넘어 낙찰 가능 구간 전체로 펼치는 것
  - 폭이 0 인 표에서 사용자별로 다른 금액을 만드는 것

정본: .orca/capsules/task_14df4921381b/capsule.yaml
"""

from __future__ import annotations

import importlib.util
from decimal import ROUND_CEILING, Decimal

BASE_AMOUNT = Decimal("500000000")
MEMBER_FLOOR_RATE = Decimal("90.0")
CENTER_SAJEONG_RATE = Decimal("100.0")
FLOOR_AMOUNT = int(
    (BASE_AMOUNT * MEMBER_FLOOR_RATE * CENTER_SAJEONG_RATE / Decimal("10000")).to_integral_value(
        rounding=ROUND_CEILING
    )
)
USER_COUNT = 32


def _load_service():
    """기준 코드에도 있는 서비스 모듈을 시험 함수 안에서 불러옵니다."""
    spec = importlib.util.find_spec("src.app.services.win_interval_stats")
    assert spec is not None, "win_interval_stats 서비스 모듈이 없습니다."
    return importlib.import_module("src.app.services.win_interval_stats")


def _results(service, quantiles: tuple[Decimal, ...], users: int = USER_COUNT):
    return [
        service.user_dispersed_bid(
            base_amount=BASE_AMOUNT,
            quantiles=quantiles,
            member_floor_rate=MEMBER_FLOOR_RATE,
            center_sajeong_rate=CENTER_SAJEONG_RATE,
            user_key=f"floor-band-user-{index}",
            notice_key="floor-band-notice",
        )
        for index in range(users)
    ]


# 전 분위가 하한(90.0%) 아래지만 p25=85.4%, p75=86.4% 로 폭이 1.0%p 있다.
BELOW_FLOOR_QUANTILES = tuple(Decimal("85.0") + Decimal("0.1") * index for index in range(19))
# p25=86.6% 는 하한 아래, p75=90.6% 는 하한 위인 기울어진 표.
PARTIAL_QUANTILES = tuple(Decimal("85.0") + Decimal("0.4") * index for index in range(19))
# 폭이 0 인 표.
FLAT_QUANTILES = tuple(Decimal("85.0") for _ in range(19))


def test_all_below_floor_spreads_users_over_historical_width() -> None:
    service = _load_service()
    results = _results(service, BELOW_FLOOR_QUANTILES)

    # 이 단언은 기준 코드에서 실패한다. 기준 코드는 모두 FLOOR_AMOUNT 로 클립된다.
    assert all(result.amount >= FLOOR_AMOUNT for result in results)
    assert len({result.amount for result in results}) == USER_COUNT
    assert all(result.clipped is False for result in results)
    # 역사적 폭(1.0%p)만 하한 위로 올린다: 90.0% ~ 91.0%.
    assert all(MEMBER_FLOOR_RATE <= result.bid_rate <= Decimal("91.0") for result in results)


def test_partial_above_floor_uses_only_above_floor_piece() -> None:
    service = _load_service()
    results = _results(service, PARTIAL_QUANTILES)

    assert all(result.amount >= FLOOR_AMOUNT for result in results)
    assert len({result.amount for result in results}) == USER_COUNT
    assert all(result.clipped is False for result in results)
    # 하한 위 조각(90.0% ~ p75 90.6%)만 쓴다.
    assert all(result.bid_rate <= Decimal("90.6") for result in results)


def test_flat_quantiles_keep_single_clipped_floor_amount() -> None:
    service = _load_service()
    results = _results(service, FLAT_QUANTILES, users=8)

    assert len({result.amount for result in results}) == 1
    assert results[0].amount == FLOOR_AMOUNT
    assert all(result.clipped is True for result in results)


def test_same_user_and_notice_returns_same_bid() -> None:
    service = _load_service()
    arguments = {
        "base_amount": BASE_AMOUNT,
        "quantiles": BELOW_FLOOR_QUANTILES,
        "member_floor_rate": MEMBER_FLOOR_RATE,
        "center_sajeong_rate": CENTER_SAJEONG_RATE,
        "user_key": "floor-band-user-0",
        "notice_key": "floor-band-notice",
    }

    assert service.user_dispersed_bid(**arguments) == service.user_dispersed_bid(**arguments)


def test_band_amounts_are_shared_and_contain_each_user_amount() -> None:
    service = _load_service()
    band_amounts = getattr(service, "dispersed_band_amounts", None)
    # 새 공개 심볼은 시험 함수 안에서만 만진다. 기준 코드에서는 여기서 실패한다.
    assert band_amounts is not None, "dispersed_band_amounts 가 없습니다."

    low, high = band_amounts(
        base_amount=BASE_AMOUNT,
        quantiles=BELOW_FLOOR_QUANTILES,
        member_floor_rate=MEMBER_FLOOR_RATE,
        center_sajeong_rate=CENTER_SAJEONG_RATE,
    )
    assert low == FLOOR_AMOUNT
    assert high == 455_000_000
    for result in _results(service, BELOW_FLOOR_QUANTILES):
        assert low <= result.amount <= high
