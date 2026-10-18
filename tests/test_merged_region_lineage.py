"""통합특별시 출범 이전 전남광주 공고가 수요기관명으로 옛 계열 전신 규칙을 받는지 시험.

정본: .cache/regime_mismatch_predecessor_b_20261018.md (조사 문서)
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)

WASTE_METHOD = "폐기물처리용역 적격심사 추정가격 고시금액미만"
LAND_TRANSPORT_METHOD = "여객 육상운송용역 적격심사 추정가격 5억원미만"

JNGJ_WASTE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"
JNGJ_LAND_TRANSPORT_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_05"
JEONNAM_WASTE_ID = "SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4"
JEONNAM_LAND_TRANSPORT_ID = "SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4"
GWANGJU_WASTE_ID = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3"
GWANGJU_LAND_TRANSPORT_ID = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5"


def _raw(dminstt_nm: str, bid_ntce_dt: str, method: str, price: str) -> dict[str, str]:
    return {
        "dminsttNm": dminstt_nm,
        "bidNtceDt": bid_ntce_dt,
        "sucsfbidMthdNm": method,
        "presmptPrce": price,
    }


def test_hwasun_waste_uses_jeonnam_predecessor() -> None:
    raw = _raw(
        "전남광주통합특별시 화순군",
        "2025-10-21 10:01:34",
        "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
        "163636364",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("163636364"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == JEONNAM_WASTE_ID
    assert result.is_blocked is False


def test_muan_land_transport_uses_jeonnam_predecessor() -> None:
    # blocks.json 에서 고른 무안청사 육상운송 공고
    raw = _raw(
        "전남광주통합특별시 무안청사",
        "2025-09-01 00:00:00",
        "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만",
        "400000000",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("400000000"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == JEONNAM_LAND_TRANSPORT_ID
    assert result.is_blocked is False


def test_gwangsan_waste_uses_gwangju_predecessor() -> None:
    raw = _raw(
        "전남광주통합특별시 광산구",
        "2025-10-21 10:01:34",
        "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
        "163636364",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("163636364"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == GWANGJU_WASTE_ID
    assert result.is_blocked is False


def test_education_office_uses_gwangju_series() -> None:
    raw = _raw(
        "전남광주통합특별시교육청 전남광주통합특별시광주서부교육지원청",
        "2025-10-21 10:01:34",
        "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만",
        "400000000",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("400000000"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == GWANGJU_LAND_TRANSPORT_ID
    assert result.is_blocked is False


def test_ai_education_center_stays_blocked() -> None:
    raw = _raw(
        "전남광주통합특별시교육청 전남광주통합특별시교육청AI교육원",
        "2025-10-21 10:01:34",
        "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만",
        "400000000",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("400000000"),
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_after_cutoff_uses_current_jngj_rule() -> None:
    raw = _raw(
        "전남광주통합특별시 화순군",
        "2026-07-20 10:00:00",
        "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만",
        "400000000",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("400000000"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == JNGJ_WASTE_ID
    assert result.is_blocked is False


def test_legacy_determination_direct_resolve() -> None:
    # 직접 resolve 경로에서도 동작해야 한다.
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=WASTE_METHOD,
        contract_regime="LOCAL",
        bid_ntce_dt="2025-10-21",
        region_code="12",
        region_name="전남광주통합특별시",
        institution_name="전남광주통합특별시 화순군",
        estimated_price=Decimal("163636364"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == JEONNAM_WASTE_ID
    assert result.is_blocked is False
