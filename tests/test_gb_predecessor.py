"""경상북도 일반용역 등 적격심사 구판(예규 제1568호, 시행 2024-12-12) 적용 시험.

정본:
 - 자치법규정보시스템 경상북도 예규 제1568호, 시행 2024-12-12, 별표 1·5
 - docs/analysis/regime_mismatch_predecessor_a_20261018.md

현행 규칙(예규 제1571호, 시행 2026-01-08) 시행일 이전 경상북도 공고는 구판 규칙으로
계산되어야 하며 RULE_REGIME_MISMATCH 로 차단되지 않아야 합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    resolve_evaluation_rule_from_raw_data,
)

PREDECESSOR_WASTE_ID = "SERVC_LOCAL_GB_20241212_ATTACH_05"
PREDECESSOR_GENERAL_ID = "SERVC_LOCAL_GB_20241212_ATTACH_01"
CURRENT_WASTE_ID = "SERVC_LOCAL_GB_20260108_ATTACH_03"
CURRENT_GENERAL_ID = "SERVC_LOCAL_GB_20260108_ATTACH_04"


def _raw(
    bid_ntce_dt: str, method: str, price: str, cls: str | None = None, **extra
) -> dict[str, str]:
    base = {
        "dminsttNm": extra.pop("dminsttNm", "경상북도 포항시 맑은물사업소"),
        "bidNtceDt": bid_ntce_dt,
        "sucsfbidMthdNm": method,
        "presmptPrce": price,
    }
    if cls is not None:
        base["pubPrcrmntClsfcNm"] = cls
    base.update(extra)
    return base


def _resolve(raw: dict, estimated_price: Decimal | None = None, **kwargs):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="47",
        region_name="경상북도",
        estimated_price=estimated_price,
        **kwargs,
    )


def test_predecessor_period_waste_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-10-20 18:04:44",
        "적격심사제-추정가격 2억원 미만인 용역",
        "145739091",
        cls="폐기물처리서비스",
    )
    result = _resolve(raw, estimated_price=Decimal("145739091"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_WASTE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_general_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-11-13 09:58:12",
        "적격심사제-시설분야용역 적격심사 추정가격 5억원 이상",
        "100000000",
        dminsttNm="경상북도 김천시",
    )
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_GENERAL_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_after_cutoff_uses_current_waste_rule() -> None:
    raw = _raw(
        "2026-02-01 10:00:00",
        "적격심사제-추정가격 2억원 미만인 용역",
        "100000000",
        cls="폐기물처리서비스",
    )
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_WASTE_ID
    assert result.is_blocked is False


def test_after_cutoff_uses_current_general_rule() -> None:
    raw = _raw(
        "2026-02-01 10:00:00",
        "적격심사제-시설분야용역 적격심사 추정가격 5억원 이상",
        "100000000",
        dminsttNm="경상북도 김천시",
    )
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_GENERAL_ID
    assert result.is_blocked is False


def test_before_effective_date_stays_blocked() -> None:
    raw = _raw(
        "2024-12-11 10:00:00",
        "적격심사제-추정가격 2억원 미만인 용역",
        "100000000",
        cls="폐기물처리서비스",
    )
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_predecessor_waste_band_values() -> None:
    raw = _raw(
        "2025-10-20 18:04:44",
        "적격심사제-추정가격 2억원 미만인 용역",
        "145739091",
        cls="폐기물처리서비스",
    )
    result = _resolve(raw, estimated_price=Decimal("145739091"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_WASTE_ID
    band = next(
        (b for b in (result.rule.price_bands or ()) if "2억원 미만" in (b.label or "")),
        None,
    )
    assert band is not None
    assert band.max_price_score == Decimal("90")
    assert band.multiplier == Decimal("20")
    assert band.base_rate == Decimal("0.88")
    assert band.lwlt_rate == Decimal("87.745")
    assert result.rule.threshold_bands is not None


def test_predecessor_general_band_values() -> None:
    raw = _raw(
        "2025-11-13 09:58:12",
        "적격심사제-시설분야용역 적격심사 추정가격 5억원 이상",
        "100000000",
        dminsttNm="경상북도 김천시",
    )
    result = _resolve(raw, estimated_price=Decimal("100000000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_GENERAL_ID
    # 10억원 미만 5억원 이상 band
    band = next(
        (
            b
            for b in (result.rule.price_bands or ())
            if "5억원 이상" in (b.label or "") and "10억" in (b.label or "")
        ),
        None,
    )
    if band is None:
        band = next(
            (b for b in (result.rule.price_bands or ()) if b.max_price_score == Decimal("50")),
            None,
        )
    assert band is not None
    assert band.max_price_score == Decimal("50")
    assert band.multiplier == Decimal("2")
    assert band.base_rate == Decimal("0.88")
    assert band.lwlt_rate == Decimal("85.495")
    # threshold tiers
    thresholds = {str(b.pass_threshold) for b in (result.rule.threshold_bands or ())}
    assert "95" in thresholds
    assert "90" in thresholds
    assert "85" in thresholds


def test_predecessor_superseded_date() -> None:
    raw = _raw(
        "2025-10-20 18:04:44",
        "적격심사제-추정가격 2억원 미만인 용역",
        "145739091",
        cls="폐기물처리서비스",
    )
    result = _resolve(raw, estimated_price=Decimal("145739091"))
    assert result.rule is not None
    assert result.rule.superseded_date == "2026-01-08"
    assert result.rule.effective_date == "2024-12-12"
