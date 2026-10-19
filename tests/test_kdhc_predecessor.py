"""한국지역난방공사 일반용역 적격심사세부기준 구판(시행 2023-07-19) 적용 시험.

정본:
 - docs/analysis/inst_predecessor_attach_20261019.md 4절
 - .cache/kdhc/R25BK01166116/seq6_ord000.bin (sha256 132ff7b89ba5fdd782f3316bbe6d2dfdb156987c822826516643e549f8ee697b)

현행 규칙(시행 2026-01-01) 시행일 이전이면서 구판 시행일 이후인
KDHC 폐기물 공고는 구판 규칙으로 계산되어야 하며 RULE_REGIME_MISMATCH 로
차단되지 않아야 합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    INSTITUTION_RULES,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

PREDECESSOR_WASTE_ID = "SERVC_INST_KDHC_20230719_WASTE"
CURRENT_WASTE_ID = "SERVC_INST_KDHC_20260101_WASTE"

KDHC_CODE = "B550373"

WASTE_METHOD = "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만"


def _raw(bid_ntce_dt: str, price: str = "100000000", **extra) -> dict[str, str]:
    base = {
        "dminsttCd": extra.pop("dminsttCd", KDHC_CODE),
        "dminsttNm": extra.pop("dminsttNm", "한국지역난방공사"),
        "ntceInsttCd": extra.pop("ntceInsttCd", KDHC_CODE),
        "ntceInsttNm": extra.pop("ntceInsttNm", "한국지역난방공사"),
        "bidNtceDt": bid_ntce_dt,
        "sucsfbidMthdNm": extra.pop("sucsfbidMthdNm", WASTE_METHOD),
        "presmptPrce": price,
        "bidNtceNm": extra.pop("bidNtceNm", "한국지역난방공사 폐기물처리용역"),
    }
    base.update(extra)
    return base


def _resolve(raw: dict, estimated_price: Decimal | None = None, **kwargs):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        estimated_price=estimated_price,
        **kwargs,
    )


def test_predecessor_period_waste_uses_predecessor_rule() -> None:
    raw = _raw("2025-12-23 10:00:00", "100000000")
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_WASTE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_after_cutoff_uses_current_rule_waste() -> None:
    raw = _raw("2026-02-10 10:00:00", "100000000")
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_WASTE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_before_effective_date_stays_blocked() -> None:
    raw = _raw("2023-07-18 10:00:00", "100000000")
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_predecessor_band_values_waste() -> None:
    rule = next(r for r in INSTITUTION_RULES if r.rule_id == PREDECESSOR_WASTE_ID)
    cases = (
        ("100000000", "70", "4", "84.245", Decimal("85")),
        ("600000000", "60", "2", "80.495", Decimal("85")),
    )
    for price, b, k, lwlt, t in cases:
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b), price
        assert result.multiplier == Decimal(k), price
        assert result.pass_threshold == t, price
        band = rule.price_bands[result.price_band_index]
        assert band.lwlt_rate == Decimal(lwlt), price
        assert band.base_rate == Decimal("0.88"), price
    assert rule.base_rate == Decimal("0.88")
    assert rule.superseded_date == "2026-01-01"
    assert rule.effective_date == "2023-07-19"


def test_predecessor_superseded_date() -> None:
    rule = next(r for r in INSTITUTION_RULES if r.rule_id == PREDECESSOR_WASTE_ID)
    assert rule.effective_date == "2023-07-19"
    assert rule.superseded_date == "2026-01-01"
    assert rule.institution_code == KDHC_CODE
    assert rule.institution_name == "한국지역난방공사"
