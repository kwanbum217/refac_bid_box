"""한국농어촌공사 20251001판·한국공항공사 10차판 구판 규칙 적용 시험.

정본:
 - docs/analysis/inst_regime_remaining_20261020.md 3.4절·4.4절
 - 한국농어촌공사 일반용역 적격심사 세부기준(20251001) (시행 2025-10-01 ~ 2026-06-23)
 - 한국공항공사 일반용역 적격심사 세부기준(10차) (시행 2023-07-31 ~ 2026-03-01)

두 원문 모두 낙찰하한율을 인쇄하지 않으므로 구판 규칙의 구간·대표 하한율은 None 이고,
공고 하한율이 없으면 최저 투찰금액만 비우며 계산을 차단하지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_flat_zones import flat_zone_for
from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    INSTITUTION_RULES,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

KRC_CODE = "B552149"
KAC_CODE = "B551178"
NOTICE_AMOUNT = Decimal("230000000")

KRC_INSURANCE = "SERVC_INST_KRC_20251001_INSURANCE"
KRC_LEASE = "SERVC_INST_KRC_20251001_LEASE"
KRC_PASSENGER = "SERVC_INST_KRC_20251001_PASSENGER"
KAC_ACADEMIC = "SERVC_INST_KAC_20230731_ACADEMIC"
KAC_INSURANCE = "SERVC_INST_KAC_20230731_INSURANCE"
KAC_SOFTWARE = "SERVC_INST_KAC_20230731_SOFTWARE_SME"

KRC_CURRENT_INSURANCE = "SERVC_INST_KRC_20260624_INSURANCE"
KAC_777_INSURANCE = "SERVC_INST_KAC_20260302_INSURANCE"
KAC_CURRENT_INSURANCE = "SERVC_INST_KAC_20260814_INSURANCE"

KRC_INSURANCE_METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원이상"
KRC_LEASE_METHOD = "적격심사제-임대차용역 적격심사 추정가격 고시금액 미만"
KRC_PASSENGER_METHOD = "적격심사제-여객육상운송용역 적격심사 추정가격 5억원 미만"
KAC_ACADEMIC_METHOD = "적격심사제-학술연구용역 적격심사 추정가격 고시금액 미만"
KAC_INSURANCE_METHOD = KRC_INSURANCE_METHOD
KAC_SOFTWARE_METHOD = (
    "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만"
)

MISSING_LWLT_MESSAGE = "별표에 낙찰하한율이 없어 최저 투찰금액을 비웁니다."


def _raw(
    code: str,
    name: str,
    bid_ntce_dt: str,
    method: str,
    price: str = "100000000",
    **extra: str,
) -> dict[str, str]:
    base = {
        "dminsttCd": code,
        "dminsttNm": name,
        "ntceInsttCd": code,
        "ntceInsttNm": name,
        "bidNtceDt": bid_ntce_dt,
        "sucsfbidMthdNm": method,
        "presmptPrce": price,
    }
    base.update(extra)
    return base


def _resolve(raw: dict[str, str], estimated_price: Decimal | None = None):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        estimated_price=estimated_price,
    )


def _rule(rule_id: str):
    return next(rule for rule in INSTITUTION_RULES if rule.rule_id == rule_id)


def test_krc_predecessor_rules_registered() -> None:
    for rule_id in (KRC_INSURANCE, KRC_LEASE, KRC_PASSENGER):
        rule = _rule(rule_id)
        assert rule.institution_code == KRC_CODE
        assert rule.institution_name == "한국농어촌공사"
        assert rule.effective_date == "2025-10-01"
        assert rule.superseded_date == "2026-06-24"
        assert rule.lwlt_rate is None
        assert all(band.lwlt_rate is None for band in rule.price_bands or ())


def test_kac_predecessor_rules_registered() -> None:
    for rule_id in (KAC_ACADEMIC, KAC_INSURANCE, KAC_SOFTWARE):
        rule = _rule(rule_id)
        assert rule.institution_code == KAC_CODE
        assert rule.institution_name == "한국공항공사"
        assert rule.effective_date == "2023-07-31"
        assert rule.superseded_date == "2026-03-02"
        assert rule.lwlt_rate is None
        assert all(band.lwlt_rate is None for band in rule.price_bands or ())


@pytest.mark.parametrize(
    ("rule_id", "name", "code", "bid_ntce_dt", "method", "price"),
    [
        (
            KRC_INSURANCE,
            "한국농어촌공사",
            KRC_CODE,
            "2026-01-21 10:00:00",
            KRC_INSURANCE_METHOD,
            "600000000",
        ),
        (
            KRC_LEASE,
            "한국농어촌공사",
            KRC_CODE,
            "2025-10-20 10:00:00",
            KRC_LEASE_METHOD,
            "100000000",
        ),
        (
            KRC_PASSENGER,
            "한국농어촌공사",
            KRC_CODE,
            "2025-12-03 10:00:00",
            KRC_PASSENGER_METHOD,
            "400000000",
        ),
        (
            KAC_ACADEMIC,
            "한국공항공사",
            KAC_CODE,
            "2025-11-10 10:00:00",
            KAC_ACADEMIC_METHOD,
            "100000000",
        ),
        (
            KAC_INSURANCE,
            "한국공항공사",
            KAC_CODE,
            "2026-01-08 10:00:00",
            KAC_INSURANCE_METHOD,
            "600000000",
        ),
        (
            KAC_SOFTWARE,
            "한국공항공사",
            KAC_CODE,
            "2025-12-03 10:00:00",
            KAC_SOFTWARE_METHOD,
            "400000000",
        ),
    ],
)
def test_predecessor_announcement_without_lwlt_is_not_blocked(
    rule_id: str,
    name: str,
    code: str,
    bid_ntce_dt: str,
    method: str,
    price: str,
) -> None:
    result = _resolve(_raw(code, name, bid_ntce_dt, method, price), Decimal(price))
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.effective_lwlt_rate is None
    assert result.rate_source is None
    assert MISSING_LWLT_MESSAGE in result.warnings
    assert not any("None%" in warning for warning in result.warnings)


@pytest.mark.parametrize(
    ("rule_id", "name", "code", "bid_ntce_dt", "method", "price"),
    [
        (
            KRC_INSURANCE,
            "한국농어촌공사",
            KRC_CODE,
            "2026-01-21 10:00:00",
            KRC_INSURANCE_METHOD,
            "600000000",
        ),
        (
            KAC_INSURANCE,
            "한국공항공사",
            KAC_CODE,
            "2026-01-08 10:00:00",
            KAC_INSURANCE_METHOD,
            "600000000",
        ),
    ],
)
def test_announcement_lwlt_takes_priority_over_empty_rule_value(
    rule_id: str,
    name: str,
    code: str,
    bid_ntce_dt: str,
    method: str,
    price: str,
) -> None:
    raw = _raw(code, name, bid_ntce_dt, method, price, sucsfbidLwltRate="47.995")
    result = _resolve(raw, Decimal(price))
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.is_blocked is False
    assert result.effective_lwlt_rate == Decimal("47.995")
    assert result.rate_source == "ANNOUNCEMENT"
    assert not any("일치하지 않아" in warning for warning in result.warnings)


def test_krc_before_effective_date_stays_blocked() -> None:
    raw = _raw(
        KRC_CODE,
        "한국농어촌공사",
        "2025-09-30 10:00:00",
        KRC_INSURANCE_METHOD,
        "600000000",
    )
    result = _resolve(raw, Decimal("600000000"))
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_krc_cutover_insurance_uses_current_rule() -> None:
    raw = _raw(
        KRC_CODE,
        "한국농어촌공사",
        "2026-06-24 10:00:00",
        KRC_INSURANCE_METHOD,
        "600000000",
    )
    result = _resolve(raw, Decimal("600000000"))
    assert result.rule is not None
    assert result.rule.rule_id == KRC_CURRENT_INSURANCE
    assert result.is_blocked is False
    assert result.effective_lwlt_rate == Decimal("47.995")


@pytest.mark.parametrize(
    ("bid_ntce_dt", "rule_id", "expected_rate"),
    [
        ("2026-01-08 10:00:00", KAC_INSURANCE, None),
        ("2026-03-02 10:00:00", KAC_777_INSURANCE, Decimal("47.995")),
        ("2026-08-14 10:00:00", KAC_CURRENT_INSURANCE, Decimal("47.995")),
    ],
)
def test_kac_regime_boundaries(
    bid_ntce_dt: str, rule_id: str, expected_rate: Decimal | None
) -> None:
    raw = _raw(KAC_CODE, "한국공항공사", bid_ntce_dt, KAC_INSURANCE_METHOD, "600000000")
    result = _resolve(raw, Decimal("600000000"))
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.is_blocked is False
    assert result.effective_lwlt_rate == expected_rate


@pytest.mark.parametrize(
    ("rule_id", "price", "b", "k", "base", "pass_score"),
    [
        (KRC_INSURANCE, "400000000", "70", "0.375", "0.88", "85"),
        (KRC_INSURANCE, "600000000", "60", "0.375", "0.88", "85"),
        (KRC_LEASE, "100000000", "70", "4", "0.88", "85"),
        (KRC_LEASE, "300000000", "70", "2", "0.88", "85"),
        (KRC_PASSENGER, "400000000", "70", "4", "0.91", "88"),
        (KRC_PASSENGER, "600000000", "60", "4", "0.91", "88"),
        (KAC_ACADEMIC, "100000000", "70", "4", "0.88", "85"),
        (KAC_ACADEMIC, "300000000", "40", "2", "0.88", "85"),
        (KAC_INSURANCE, "400000000", "70", "0.375", "0.88", "85"),
        (KAC_INSURANCE, "600000000", "60", "0.375", "0.88", "85"),
        (KAC_SOFTWARE, "400000000", "70", "4", "0.91", "88"),
        (KAC_SOFTWARE, "600000000", "60", "4", "0.91", "88"),
    ],
)
def test_predecessor_band_values(
    rule_id: str, price: str, b: str, k: str, base: str, pass_score: str
) -> None:
    rule = _rule(rule_id)
    result = resolve_score_params(rule, Decimal(price), None, None)
    assert result.max_price_score == Decimal(b), price
    assert result.multiplier == Decimal(k), price
    assert result.pass_threshold == Decimal(pass_score), price
    assert result.price_band_index is not None
    band = rule.price_bands[result.price_band_index]
    assert band.base_rate == Decimal(base), price
    assert band.lwlt_rate is None, price


def test_kac_academic_predecessor_has_only_two_bands() -> None:
    rule = _rule(KAC_ACADEMIC)
    uppers = [band.upper_bound for band in rule.price_bands or ()]
    assert uppers == [NOTICE_AMOUNT, None]


@pytest.mark.parametrize(
    ("rule_id", "upper", "ratio", "score"),
    [
        (KRC_LEASE, NOTICE_AMOUNT, "0.9175", "55"),
        (KRC_LEASE, None, "0.955", "55"),
        (KRC_PASSENGER, Decimal("500000000"), "0.94", "58"),
        (KRC_PASSENGER, None, "0.94", "48"),
        (KAC_ACADEMIC, NOTICE_AMOUNT, "0.9175", "55"),
        (KAC_ACADEMIC, None, "0.955", "25"),
        (KAC_SOFTWARE, Decimal("500000000"), "0.94", "58"),
        (KAC_SOFTWARE, None, "0.94", "48"),
    ],
)
def test_predecessor_flat_zones(
    rule_id: str, upper: Decimal | None, ratio: str, score: str
) -> None:
    zone = flat_zone_for(rule_id, upper)
    assert zone is not None
    assert zone.flat_ratio == Decimal(ratio)
    assert zone.flat_score == Decimal(score)
    assert "산식 대입값" in zone.source


@pytest.mark.parametrize("rule_id", [KRC_INSURANCE, KAC_INSURANCE])
def test_insurance_predecessor_has_no_flat_zone(rule_id: str) -> None:
    assert flat_zone_for(rule_id, Decimal("500000000")) is None
    assert flat_zone_for(rule_id, None) is None
