"""대전광역시 일반용역 적격심사 구판(공고 제2024-2호, 시행 2024-01-20) 적용 시험.

정본:
 - docs/analysis/regime_mismatch_predecessor_a_20261018.md
 - 원문: 대전광역시 공고 제2024-2호, 시행 2024-01-20, 별표 6

현행 규칙(공고 제2025-9528호, 시행 2026-01-01) 시행일 이전 대전 공고는 구판 규칙으로
계산되어야 하며 RULE_REGIME_MISMATCH 로 차단되지 않아야 합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    resolve_evaluation_rule_from_raw_data,
)

PREDECESSOR_GENERAL_ID = "SERVC_LOCAL_DAEJEON_20240120_ATTACH_01"
PREDECESSOR_SIMPLE_LABOR_ID = "SERVC_LOCAL_DAEJEON_20240120_SIMPLE_LABOR"
CURRENT_GENERAL_ID = "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01"


def _raw(bid_ntce_dt: str, method: str, price: str, **extra) -> dict[str, str]:
    base = {
        "dminsttNm": "대전광역시",
        "bidNtceDt": bid_ntce_dt,
        "sucsfbidMthdNm": method,
        "presmptPrce": price,
        "pubPrcrmntClsfcNm": "건설폐기물처리서비스",
    }
    base.update(extra)
    return base


def _resolve(raw: dict, estimated_price: Decimal | None = None, **kwargs):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="30",
        region_name="대전광역시",
        estimated_price=estimated_price,
        **kwargs,
    )


def test_predecessor_period_general_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-10-22 14:23:59",
        "적격심사제-추정가격 30억원 미만 15억원 이상인 용역",
        "1606410000",
    )
    result = _resolve(raw, estimated_price=Decimal("1606410000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_GENERAL_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_5eok_2eok_band_lower_bound() -> None:
    raw = _raw(
        "2025-11-05 13:26:12",
        "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
        "204400000",
    )
    result = _resolve(raw, estimated_price=Decimal("204400000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_GENERAL_ID
    assert result.is_blocked is False
    band = next(
        (b for b in (result.rule.price_bands or ()) if b.label == "5억원 미만 2억원 이상"),
        None,
    )
    # fallback label search by upper bound
    if band is None:
        band = next(
            (b for b in (result.rule.price_bands or ()) if "2억" in (b.label or "")),
            None,
        )
    assert band is not None
    assert band.lwlt_rate == Decimal("86.745")


def test_predecessor_period_under_2eok_band_lower_bound() -> None:
    raw = _raw(
        "2025-12-05 10:00:00",
        "적격심사제-추정가격 2억원 미만인 용역",
        "175028182",
    )
    result = _resolve(raw, estimated_price=Decimal("175028182"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_GENERAL_ID
    assert result.is_blocked is False


def test_after_cutoff_uses_current_rule() -> None:
    raw = _raw(
        "2026-01-05 10:00:00",
        "적격심사제-추정가격 30억원 미만 15억원 이상인 용역",
        "1606410000",
    )
    result = _resolve(raw, estimated_price=Decimal("1606410000"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_GENERAL_ID
    assert result.is_blocked is False


def test_before_effective_date_stays_blocked() -> None:
    raw = _raw(
        "2024-01-19 10:00:00",
        "적격심사제-추정가격 30억원 미만 15억원 이상인 용역",
        "1606410000",
    )
    result = _resolve(raw, estimated_price=Decimal("1606410000"))
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_predecessor_period_simple_labor_uses_predecessor() -> None:
    raw = _raw(
        "2025-10-22 14:23:59",
        "적격심사제-청소용역",
        "100000000",
    )
    result = _resolve(raw, estimated_price=Decimal("100000000"), local_service_type="SIMPLE_LABOR")
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_SIMPLE_LABOR_ID
    assert result.is_blocked is False


# sanity: lwlt band for 1.6e9 case is 77.995
def test_predecessor_band_1606410000_lwlt() -> None:
    raw = _raw(
        "2025-10-22 14:23:59",
        "적격심사제-추정가격 30억원 미만 15억원 이상인 용역",
        "1606410000",
    )
    result = _resolve(raw, estimated_price=Decimal("1606410000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_GENERAL_ID
    band = next(
        (
            b
            for b in (result.rule.price_bands or ())
            if "30억원 미만 10억원 이상" in (b.label or "")
        ),
        None,
    )
    assert band is not None
    assert band.lwlt_rate == Decimal("77.995")


def test_predecessor_band_175028182_lwlt() -> None:
    raw = _raw(
        "2025-12-05 10:00:00",
        "적격심사제-추정가격 2억원 미만인 용역",
        "175028182",
    )
    result = _resolve(raw, estimated_price=Decimal("175028182"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_GENERAL_ID
    # find band with lwlt 87.745
    bands = [b for b in (result.rule.price_bands or ()) if b.lwlt_rate == Decimal("87.745")]
    assert bands
