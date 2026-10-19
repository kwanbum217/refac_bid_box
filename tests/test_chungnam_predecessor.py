"""충청남도 일반용역 적격심사 세부기준 구판(공고 제2019-2047호, 시행 2020-02-01) 적용 시험.

정본:
 - docs/analysis/regime_mismatch_predecessor_chungnam_20261019.md
 - .cache/chungnam_2019/singu.hwpx (공고 제2019-2047호 신·구 대비표, colAddr=0 열)

현행 규칙(공고 제2026-1235호, 시행 2026-07-13) 시행일 이전 충청남도 공고는 구판 규칙으로
계산되어야 하며 RULE_REGIME_MISMATCH 로 차단되지 않아야 합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    resolve_evaluation_rule_from_raw_data,
)

PREDECESSOR_FACILITY_ID = "SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_01"
PREDECESSOR_WASTE_ID = "SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_03"
PREDECESSOR_LAND_TRANSPORT_ID = "SERVC_LOCAL_CHUNGNAM_20200201_ATTACH_04"
CURRENT_FACILITY_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_01"
CURRENT_WASTE_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03"
CURRENT_LAND_TRANSPORT_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_04"


def _raw(
    bid_ntce_dt: str, method: str, price: str, cls: str | None = None, **extra
) -> dict[str, str]:
    base = {
        "dminsttNm": extra.pop("dminsttNm", "충청남도 아산시"),
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
        region_code="44",
        region_name="충청남도",
        estimated_price=estimated_price,
        **kwargs,
    )


def test_predecessor_period_facility_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-12-03 11:04:28",
        "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        "283578190",
    )
    result = _resolve(raw, estimated_price=Decimal("283578190"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_FACILITY_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_waste_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-10-20 14:49:54",
        "적격심사제-추정가격 2억원 미만인 용역",
        "145739091",
        cls="폐기물처리서비스",
    )
    result = _resolve(raw, estimated_price=Decimal("145739091"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_WASTE_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_predecessor_period_land_transport_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-11-11 07:35:46",
        "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만",
        "179965455",
    )
    result = _resolve(raw, estimated_price=Decimal("179965455"))
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_LAND_TRANSPORT_ID
    assert result.is_blocked is False
    assert result.block_reason_code is None


def test_after_cutoff_uses_current_facility_rule() -> None:
    raw = _raw(
        "2026-08-01 10:00:00",
        "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        "283578190",
    )
    result = _resolve(raw, estimated_price=Decimal("283578190"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_FACILITY_ID
    assert result.is_blocked is False


def test_after_cutoff_uses_current_waste_rule() -> None:
    raw = _raw(
        "2026-08-01 10:00:00",
        "적격심사제-추정가격 2억원 미만인 용역",
        "145739091",
        cls="폐기물처리서비스",
    )
    result = _resolve(raw, estimated_price=Decimal("145739091"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_WASTE_ID
    assert result.is_blocked is False


def test_after_cutoff_uses_current_land_transport_rule() -> None:
    raw = _raw(
        "2026-08-01 10:00:00",
        "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만",
        "179965455",
    )
    result = _resolve(raw, estimated_price=Decimal("179965455"))
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_LAND_TRANSPORT_ID
    assert result.is_blocked is False


def test_before_effective_date_stays_blocked() -> None:
    raw = _raw(
        "2020-01-31 10:00:00",
        "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        "283578190",
    )
    result = _resolve(raw, estimated_price=Decimal("283578190"))
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_predecessor_facility_band_values() -> None:
    from src.app.services.evaluation_rules import LOCAL_RULES, resolve_score_params

    rule = next(r for r in LOCAL_RULES if r.rule_id == PREDECESSOR_FACILITY_ID)
    for price, b, k, lwlt in (
        ("300000000", "70", "5", "87.995"),
        ("600000000", "60", "5", "87.995"),
    ):
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b)
        assert result.multiplier == Decimal(k)
        assert result.base_rate == Decimal("0.91")
        assert result.pass_threshold == Decimal("85")
        assert rule.lwlt_rate == Decimal(lwlt)


def test_predecessor_waste_band_values() -> None:
    from src.app.services.evaluation_rules import LOCAL_RULES, resolve_score_params

    rule = next(r for r in LOCAL_RULES if r.rule_id == PREDECESSOR_WASTE_ID)
    cases = (
        ("200000000", "70", "4", "84.245"),
        ("300000000", "70", "2", "80.495"),
        ("600000000", "60", "2", "80.495"),
    )
    for price, b, k, lwlt in cases:
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b), price
        assert result.multiplier == Decimal(k), price
        assert result.pass_threshold == Decimal("85"), price
        assert (result.base_rate or rule.base_rate) == Decimal("0.88"), price
        band = rule.price_bands[result.price_band_index]
        assert band.lwlt_rate == Decimal(lwlt), price


def test_predecessor_land_transport_band_values() -> None:
    from src.app.services.evaluation_rules import LOCAL_RULES, resolve_score_params

    rule = next(r for r in LOCAL_RULES if r.rule_id == PREDECESSOR_LAND_TRANSPORT_ID)
    cases = (
        ("200000000", "70", "4", "84.245"),
        ("300000000", "70", "2", "80.495"),
        ("600000000", "60", "2", "80.495"),
    )
    for price, b, k, lwlt in cases:
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b), price
        assert result.multiplier == Decimal(k), price
        assert result.pass_threshold == Decimal("85"), price
        assert (result.base_rate or rule.base_rate) == Decimal("0.88"), price
        band = rule.price_bands[result.price_band_index]
        assert band.lwlt_rate == Decimal(lwlt), price


def test_predecessor_superseded_date() -> None:
    from src.app.services.evaluation_rules import LOCAL_RULES

    for rid in (PREDECESSOR_FACILITY_ID, PREDECESSOR_WASTE_ID, PREDECESSOR_LAND_TRANSPORT_ID):
        rule = next(r for r in LOCAL_RULES if r.rule_id == rid)
        assert rule.effective_date == "2020-02-01"
        assert rule.superseded_date == "2026-07-13"
    # region code check via rule.region_code
    for rid in (PREDECESSOR_FACILITY_ID, PREDECESSOR_WASTE_ID, PREDECESSOR_LAND_TRANSPORT_ID):
        rule = next(r for r in LOCAL_RULES if r.rule_id == rid)
        assert rule.region_code == "44"
        assert rule.region_name == "충청남도"
