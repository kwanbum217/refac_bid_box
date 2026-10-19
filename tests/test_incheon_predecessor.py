"""인천광역시 일반용역 적격심사 세부기준 구판(예규 제484호, 시행 2024-12-04) 적용 시험.

정본:
 - docs/analysis/incheon_predecessor_pass_score_20261019.md
 - .cache/incheon_inst/raw/incheon_3061306_attach1.bin (별표 1 HWP)
 - ELIS 예규 제484호 (histNo=007) 본문 제5조

현행 규칙(예규 제488호, 시행 2025-12-24) 시행일 이전 인천 공고는 구판 규칙으로
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

PREDECESSOR_ID = "SERVC_LOCAL_INCHEON_20241204_ATTACH_01"
CURRENT_ID = "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"


def _raw(bid_ntce_dt: str, method: str, price: str, **extra) -> dict[str, str]:
    base = {
        "dminsttNm": extra.pop("dminsttNm", "인천광역시"),
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
        region_code="28",
        region_name="인천광역시",
        estimated_price=estimated_price,
        local_service_type="GENERAL",
        **kwargs,
    )


def test_predecessor_period_under_2eok_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-11-07 17:51:35",
        "적격심사제-추정가격 2억원 미만인 용역",
        "171100000",
    )
    result = _resolve(raw, estimated_price=Decimal("171100000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_2to5eok_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-11-03 16:28:09",
        "적격심사제-추정가격 5억원 미만 2억원 이상인 용역",
        "362954000",
    )
    result = _resolve(raw, estimated_price=Decimal("362954000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_10to30eok_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-11-11 18:01:59",
        "적격심사제-추정가격 30억원 미만 10억원 이상인 용역",
        "1685270000",
    )
    result = _resolve(raw, estimated_price=Decimal("1685270000"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_after_cutoff_uses_current_rule() -> None:
    raw = _raw(
        "2025-12-24 10:00:00",
        "적격심사제-추정가격 2억원 미만인 용역",
        "171100000",
    )
    result = _resolve(raw, estimated_price=Decimal("171100000"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_ID
    assert result.is_blocked is False


def test_before_effective_date_stays_blocked() -> None:
    raw = _raw(
        "2024-12-03 10:00:00",
        "적격심사제-추정가격 2억원 미만인 용역",
        "171100000",
    )
    result = _resolve(raw, estimated_price=Decimal("171100000"))
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_predecessor_band_values() -> None:
    rule = next(r for r in LOCAL_RULES if r.rule_id == PREDECESSOR_ID)
    cases = (
        ("100000000", "90", "20", "87.745", Decimal("95")),
        ("300000000", "70", "4", "86.745", Decimal("95")),
        ("700000000", "50", "2", "85.495", Decimal("95")),
        ("1500000000", "30", "1", "77.995", Decimal("90")),
    )
    for price, b, k, lwlt, t in cases:
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b), price
        assert result.multiplier == Decimal(k), price
        assert result.pass_threshold == t, price
        assert (result.base_rate or rule.base_rate) == Decimal("0.88"), price
        band = rule.price_bands[result.price_band_index]
        assert band.lwlt_rate == Decimal(lwlt), price
        assert band.base_rate == Decimal("0.88"), price

    # 30억 미만 10억 이상 구간의 상한은 30억으로 닫혀 있다.
    top_band = rule.price_bands[3]
    assert top_band.upper_bound == Decimal("3000000000")
    assert top_band.label == "30억원 미만 10억원 이상"


def test_predecessor_superseded_date() -> None:
    rule = next(r for r in LOCAL_RULES if r.rule_id == PREDECESSOR_ID)
    assert rule.effective_date == "2024-12-04"
    assert rule.superseded_date == "2025-12-24"
    assert rule.region_code == "28"
    assert rule.region_name == "인천광역시"
    assert rule.bounded_price_top is True


def test_predecessor_over_30eok_not_silently_computed() -> None:
    """구판 기간의 추정가격 30억원 이상 공고는 가격 구간이 없어 조용히 계산되지 않는다."""
    rule = next(r for r in LOCAL_RULES if r.rule_id == PREDECESSOR_ID)
    for price in ("3000000000", "4000000000"):
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score is None, price
        assert result.price_band_label is None, price
        assert result.price_band_index is None, price
        assert any("구간" in (w or "") for w in result.warnings), price
    # 72.995(현행 30억 이상 값)이 구판 규칙 어디에도 들어 있지 않다.
    lwlt_values = {str(b.lwlt_rate) for b in rule.price_bands if b.lwlt_rate is not None}
    assert "72.995" not in lwlt_values
    assert rule.lwlt_rate != Decimal("72.995")
    assert all(b.lwlt_rate != Decimal("72.995") for b in rule.price_bands)
    # 통과점수는 95/90/85 세 구간이고 30억 이상 전용 T=85 가격 구간은 존재하지 않는다.
    threshold_values = {str(b.pass_threshold) for b in rule.threshold_bands}
    assert threshold_values == {"95", "90", "85"}
    # bounded top 이므로 30억 이상은 price band 미존재로 차단 경로에 들어간다.
    assert rule.bounded_price_top is True
