"""대구광역시 일반용역 적격심사 세부기준 구판(예규 제223호, 시행 2022-09-30) 적용 시험.

정본:
 - .cache/daegu/7560ea7a13d3_[별표 4] 폐기물처리용역 적격심사 평가기준.hwp (현행 별표 4)
 - .cache/daegu/560b82365946_대구광역시 일반용역 적격심사세부기준(대구광역시예규제223호_2022.9.30).pdf (직전판 전문)

현행 규칙(예규 제238호, 시행 2026-05-11) 시행일 이전 대구 공고는 구판 규칙으로
계산되어야 하며 RULE_REGIME_MISMATCH 로 차단되지 않아야 합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    LOCAL_RULES,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

PREDECESSOR_WASTE_ID = "SERVC_LOCAL_DAEGU_20220930_ATTACH_04"
CURRENT_WASTE_ID = "SERVC_LOCAL_DAEGU_20260511_ATTACH_04"
PREDECESSOR_SIMPLE_LABOR_ID = "SERVC_LOCAL_DAEGU_20220930_ATTACH_01"
CURRENT_SIMPLE_LABOR_ID = "SERVC_LOCAL_DAEGU_20260511_ATTACH_01"


def _raw(bid_ntce_dt: str, method: str, price: str, **extra) -> dict[str, str]:
    base = {
        "dminsttNm": extra.pop("dminsttNm", "대구광역시"),
        "bidNtceDt": bid_ntce_dt,
        "sucsfbidMthdNm": method,
        "presmptPrce": price,
    }
    base.update(extra)
    return base


def _resolve(raw: dict, estimated_price: Decimal | None = None, **kwargs):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="27",
        region_name="대구광역시",
        estimated_price=estimated_price,
        **kwargs,
    )


def test_predecessor_period_waste_under_2eok_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-12-09 10:43:06",
        "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
        "199128182",
    )
    result = _resolve(raw, estimated_price=Decimal("199128182"), local_service_type="WASTE")
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_WASTE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_waste_over_2eok_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-12-09 10:43:06",
        "적격심사제-폐기물처리용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상",
        "262000000",
    )
    result = _resolve(raw, estimated_price=Decimal("262000000"), local_service_type="WASTE")
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_WASTE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_simple_labor_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-11-07 17:51:35",
        "적격심사제-단순노무 일반용역 적격심사 추정가격 2억원 미만",
        "171100000",
    )
    result = _resolve(raw, estimated_price=Decimal("171100000"), local_service_type="SIMPLE_LABOR")
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_SIMPLE_LABOR_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_after_cutoff_waste_uses_current_rule() -> None:
    raw = _raw(
        "2026-05-11 10:00:00",
        "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
        "199128182",
    )
    result = _resolve(raw, estimated_price=Decimal("199128182"), local_service_type="WASTE")
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_WASTE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_after_cutoff_simple_labor_uses_current_rule() -> None:
    raw = _raw(
        "2026-05-11 10:00:00",
        "적격심사제-단순노무 일반용역 적격심사 추정가격 2억원 미만",
        "171100000",
    )
    result = _resolve(raw, estimated_price=Decimal("171100000"), local_service_type="SIMPLE_LABOR")
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_SIMPLE_LABOR_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_before_effective_date_stays_blocked() -> None:
    raw = _raw(
        "2022-09-29 10:00:00",
        "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
        "199128182",
    )
    result = _resolve(raw, estimated_price=Decimal("199128182"), local_service_type="WASTE")
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_waste_band_values() -> None:
    rule = next(r for r in LOCAL_RULES if r.rule_id == PREDECESSOR_WASTE_ID)
    cases = (
        ("100000000", "70", "2", "80.495", Decimal("85")),
        ("262000000", "70", "2", "80.495", Decimal("85")),
        ("600000000", "60", "2", "80.495", Decimal("85")),
    )
    for price, b, k, lwlt, t in cases:
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b), price
        assert result.multiplier == Decimal(k), price
        assert result.pass_threshold == t, price
        assert (result.base_rate or rule.base_rate) == Decimal("0.88"), price
        band = rule.price_bands[result.price_band_index]
        assert band.lwlt_rate == Decimal(lwlt), price


def test_waste_band_values_current() -> None:
    rule = next(r for r in LOCAL_RULES if r.rule_id == CURRENT_WASTE_ID)
    cases = (
        ("262000000", "70", "2", "80.495", Decimal("85")),
        ("600000000", "60", "2", "80.495", Decimal("85")),
    )
    for price, b, k, lwlt, t in cases:
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b), price
        assert result.multiplier == Decimal(k), price
        assert result.pass_threshold == t, price
        assert (result.base_rate or rule.base_rate) == Decimal("0.88"), price
        band = rule.price_bands[result.price_band_index]
        assert band.lwlt_rate == Decimal(lwlt), price


def test_simple_labor_band_values() -> None:
    rule = next(r for r in LOCAL_RULES if r.rule_id == PREDECESSOR_SIMPLE_LABOR_ID)
    assert rule.lwlt_rate == Decimal("87.745")
    assert rule.effective_date == "2022-09-30"
    assert rule.superseded_date == "2026-05-11"
    assert rule.region_code == "27"


def test_predecessor_superseded_date() -> None:
    for rid, eff, sup in (
        (PREDECESSOR_WASTE_ID, "2022-09-30", "2026-05-11"),
        (PREDECESSOR_SIMPLE_LABOR_ID, "2022-09-30", "2026-05-11"),
    ):
        rule = next(r for r in LOCAL_RULES if r.rule_id == rid)
        assert rule.effective_date == eff
        assert rule.superseded_date == sup
        assert rule.region_code == "27"
        assert rule.region_name == "대구광역시"
