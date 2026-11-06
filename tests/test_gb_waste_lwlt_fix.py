"""경상북도 폐기물처리용역(2026) 규칙 구간 하한율 회귀 시험.

정본:
 - 자치법규정보시스템 경상북도 예규 제1571호, 시행 2026-01-08, 별표 3
 - docs/analysis/lwlt_region_rule_value_check_20261106.md 2.2·2.5절

원문 별표 3 은 낙찰하한율을 인쇄하지 않고 평점산식과 평탄점만 둡니다. B 는 추정가격
5억원 미만/이상 70/50, k 는 20/4, 기준비율은 88, 통과점수는 전 구간 95 이므로
5억원 미만은 70-20x|88-투찰률|=65 에서 87.75% → 87.745%, 5억원 이상은
50-4x|88-투찰률|=45 에서 86.75% → 86.745% 입니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    LOCAL_RULES,
    EvaluationRule,
    resolve_evaluation_rule_from_raw_data,
)

GB_WASTE_ID = "SERVC_LOCAL_GB_20260108_ATTACH_03"
GB_PREDECESSOR_WASTE_ID = "SERVC_LOCAL_GB_20241212_ATTACH_05"
JNGJ_WASTE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"
CHUNGNAM_WASTE_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03"
SEJONG_WASTE_ID = "SERVC_LOCAL_SEJONG_20251201_ATTACH_04"


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def _raw(price: str, *, lwlt: str | None = None) -> dict[str, str]:
    raw = {
        "dminsttNm": "경상북도 포항시 맑은물사업소",
        "bidNtceDt": "2026-02-01 10:00:00",
        "sucsfbidMthdNm": "적격심사제-추정가격 2억원 미만인 용역",
        "presmptPrce": price,
        "pubPrcrmntClsfcNm": "폐기물처리서비스",
    }
    if lwlt is not None:
        raw["sucsfbidLwltRate"] = lwlt
    return raw


def _resolve(price: str, *, lwlt: str | None = None):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        _raw(price, lwlt=lwlt),
        institution_regime="LOCAL",
        region_code="47",
        region_name="경상북도",
        estimated_price=Decimal(price),
    )


def test_rule_bands_carry_source_formula_rates() -> None:
    """5억원 미만 87.745%, 5억원 이상 86.745% 를 구간 하한율로 등록한다."""
    rule = _rule(GB_WASTE_ID)
    assert rule.service_type == "WASTE"
    assert rule.lwlt_rate == Decimal("87.745")
    assert [(band.upper_bound, band.lwlt_rate) for band in rule.price_bands] == [
        (Decimal("500000000"), Decimal("87.745")),
        (None, Decimal("86.745")),
    ]


def test_rule_bands_keep_source_formula_params() -> None:
    """B·k·기준비율·통과점수는 원문 그대로다."""
    rule = _rule(GB_WASTE_ID)
    below, above = rule.price_bands
    assert (below.max_price_score, below.multiplier, below.base_rate) == (
        Decimal("70"),
        Decimal("20"),
        Decimal("0.88"),
    )
    assert (above.max_price_score, above.multiplier, above.base_rate) == (
        Decimal("50"),
        Decimal("4"),
        Decimal("0.88"),
    )
    assert [(band.upper_bound, band.pass_threshold) for band in rule.threshold_bands] == [
        (None, Decimal("95"))
    ]


@pytest.mark.parametrize(
    ("price", "expected"),
    [
        ("145739091", "87.745"),
        ("499999999", "87.745"),
        ("500000000", "86.745"),
        ("600000000", "86.745"),
    ],
)
def test_effective_rate_uses_band_when_announcement_omits_rate(price: str, expected: str) -> None:
    """공고에 하한율이 없어도 추정가격 구간의 원문 산식값을 적용한다."""
    result = _resolve(price)
    assert result.rule is not None
    assert result.rule.rule_id == GB_WASTE_ID
    assert result.is_blocked is False
    assert result.effective_lwlt_rate == Decimal(expected)
    assert result.rate_source == "RULE_DEFAULT"


def test_announcement_rate_still_wins() -> None:
    """공고 하한율 우선순위는 그대로다."""
    result = _resolve("600000000", lwlt="85.495")
    assert result.rule is not None
    assert result.rule.rule_id == GB_WASTE_ID
    assert result.effective_lwlt_rate == Decimal("85.495")
    assert result.rate_source == "ANNOUNCEMENT"


@pytest.mark.parametrize(
    ("rule_id", "rule_rate", "band_rates"),
    [
        (GB_PREDECESSOR_WASTE_ID, "87.745", ("87.745", "86.745", "85.495", "77.995", "72.995")),
        (JNGJ_WASTE_ID, "84.245", ("87.745", "87.745", "82.995", "77.995", "72.995")),
        (CHUNGNAM_WASTE_ID, "84.245", ("84.245", "80.495", "80.495")),
        (SEJONG_WASTE_ID, "87.745", (None, None)),
    ],
)
def test_other_local_waste_rules_unchanged(
    rule_id: str, rule_rate: str, band_rates: tuple[str | None, ...]
) -> None:
    """정정 대상이 아닌 다른 시·도 폐기물 규칙 값은 그대로다."""
    rule = _rule(rule_id)
    assert rule.lwlt_rate == Decimal(rule_rate), rule_id
    assert (
        tuple(None if band.lwlt_rate is None else str(band.lwlt_rate) for band in rule.price_bands)
        == band_rates
    ), rule_id
