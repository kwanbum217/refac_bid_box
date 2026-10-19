"""한국공항공사 일반용역 적격심사세부기준 구판(지침 제777호, 시행 2026-03-02) 적용 시험.

정본:
 - docs/analysis/regime_mismatch_predecessor_incheon_inst_20261019.md 4절
 - KAC 규정 게시판 BBS_SEQ 3553791 (일반용역 적격심사세부기준 '26.3.2 이후 입찰공고부터 적용)
 - .cache/incheon_inst/raw/kac_3553810_file2.bin (신구대비표 "현 행" 열)

현행 규칙(지침 제792호, 시행 2026-08-14) 시행일 이전이면서 제777호 시행 이후인
KAC 공고는 구판 규칙으로 계산되어야 하며 RULE_REGIME_MISMATCH 로 차단되지 않아야 합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    INSTITUTION_RULES,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

PREDECESSOR_ACADEMIC_ID = "SERVC_INST_KAC_20260302_ACADEMIC"
PREDECESSOR_INSURANCE_ID = "SERVC_INST_KAC_20260302_INSURANCE"
PREDECESSOR_SOFTWARE_ID = "SERVC_INST_KAC_20260302_SOFTWARE_SME"
CURRENT_ACADEMIC_ID = "SERVC_INST_KAC_20260814_ACADEMIC"
CURRENT_INSURANCE_ID = "SERVC_INST_KAC_20260814_INSURANCE"
CURRENT_SOFTWARE_ID = "SERVC_INST_KAC_20260814_SOFTWARE_SME"

KAC_CODE = "B551178"


def _raw(bid_ntce_dt: str, method: str, price: str = "100000000", **extra) -> dict[str, str]:
    base = {
        "dminsttCd": extra.pop("dminsttCd", KAC_CODE),
        "dminsttNm": extra.pop("dminsttNm", "한국공항공사"),
        "ntceInsttCd": extra.pop("ntceInsttCd", KAC_CODE),
        "ntceInsttNm": extra.pop("ntceInsttNm", "한국공항공사"),
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
        estimated_price=estimated_price,
        **kwargs,
    )


ACADEMIC_METHOD = "적격심사제-학술연구용역 적격심사 추정가격 고시금액 미만"
INSURANCE_METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원이상"
SOFTWARE_METHOD = (
    "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만"
)


def test_predecessor_period_academic_uses_predecessor_rule() -> None:
    raw = _raw("2026-04-09 10:00:00", ACADEMIC_METHOD, "100000000")
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_ACADEMIC_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_insurance_uses_predecessor_rule() -> None:
    raw = _raw("2026-04-01 10:00:00", INSURANCE_METHOD, "600000000")
    result = _resolve(raw, estimated_price=Decimal("600000000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_INSURANCE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_software_uses_predecessor_rule() -> None:
    raw = _raw("2026-03-25 10:00:00", SOFTWARE_METHOD, "100000000")
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_SOFTWARE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_after_cutoff_uses_current_rule_academic() -> None:
    raw = _raw("2026-08-14 10:00:00", ACADEMIC_METHOD, "100000000")
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_ACADEMIC_ID
    assert result.is_blocked is False


def test_before_effective_date_stays_blocked() -> None:
    raw = _raw("2026-01-08 10:00:00", ACADEMIC_METHOD, "100000000")
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_predecessor_band_values_academic() -> None:
    rule = next(r for r in INSTITUTION_RULES if r.rule_id == PREDECESSOR_ACADEMIC_ID)
    cases = (
        ("100000000", "70", "4", "84.245", Decimal("85")),
        ("300000000", "70", "2", "80.495", Decimal("85")),
        ("600000000", "40", "2", "80.495", Decimal("85")),
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
    assert rule.superseded_date == "2026-08-14"
    assert rule.effective_date == "2026-03-02"


def test_predecessor_band_values_insurance() -> None:
    rule = next(r for r in INSTITUTION_RULES if r.rule_id == PREDECESSOR_INSURANCE_ID)
    cases = (
        ("400000000", "70", "0.375", "47.995", Decimal("85")),
        ("600000000", "60", "0.375", "47.995", Decimal("85")),
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


def test_predecessor_band_values_software() -> None:
    rule = next(r for r in INSTITUTION_RULES if r.rule_id == PREDECESSOR_SOFTWARE_ID)
    cases = (
        ("400000000", "70", "4", "87.995", Decimal("88")),
        ("600000000", "60", "4", "87.995", Decimal("88")),
    )
    for price, b, k, lwlt, t in cases:
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b), price
        assert result.multiplier == Decimal(k), price
        assert result.pass_threshold == t, price
        band = rule.price_bands[result.price_band_index]
        assert band.lwlt_rate == Decimal(lwlt), price
        assert band.base_rate == Decimal("0.91"), price
    assert rule.base_rate == Decimal("0.91")
    assert rule.superseded_date == "2026-08-14"
    assert rule.effective_date == "2026-03-02"


def test_predecessor_superseded_date() -> None:
    for rid in (PREDECESSOR_ACADEMIC_ID, PREDECESSOR_INSURANCE_ID, PREDECESSOR_SOFTWARE_ID):
        rule = next(r for r in INSTITUTION_RULES if r.rule_id == rid)
        assert rule.effective_date == "2026-03-02"
        assert rule.superseded_date == "2026-08-14"
        assert rule.institution_code == KAC_CODE
        assert rule.institution_name == "한국공항공사"
