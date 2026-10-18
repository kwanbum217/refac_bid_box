"""통합 지침 이전 전라남도 계열 시설분야 공고의 전신 기준(구판 지역 규칙) 적용 시험.

정본:
 - docs/analysis/regime_mismatch_predecessor_b_20261018.md
 - 원문: 자치법규정보시스템 전라남도 일반용역 적격심사 세부기준,
   전라남도 예규 제1075호, 시행 2023-03-02 (histNo=005) 별표 1 시설분야용역

호출 방식은 tests/test_merged_region_lineage.py 를 따른다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    resolve_evaluation_rule_from_raw_data,
)

NEW_FACILITY_ID = "SERVC_LOCAL_JEONNAM_20230302_ATTACH_1_1_4"
JNGJ_FACILITY_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_01"


def _raw(dminstt_nm: str, bid_ntce_dt: str, method: str, price: str) -> dict[str, str]:
    return {
        "dminsttNm": dminstt_nm,
        "bidNtceDt": bid_ntce_dt,
        "sucsfbidMthdNm": method,
        "presmptPrce": price,
    }


FACILITY_METHOD_5EOK_PLUS = "시설분야용역 적격심사 추정가격 5억원 이상"
FACILITY_METHOD_UNDER_5EOK = "시설분야용역 적격심사 추정가격 5억원 미만"


def test_mokpo_facility_5eok_plus_uses_jeonnam_predecessor() -> None:
    raw = _raw(
        "전남광주통합특별시 목포시",
        "2026-03-20 10:00:00",
        "적격심사제-" + FACILITY_METHOD_5EOK_PLUS,
        "1205179091",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("1205179091"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == NEW_FACILITY_ID
    assert result.is_blocked is False


def test_yeosu_edu_facility_under_5eok_uses_jeonnam_predecessor() -> None:
    raw = _raw(
        "전남광주통합특별시교육청 전남광주통합특별시여수교육지원청",
        "2025-12-09 10:00:00",
        "적격심사제-" + FACILITY_METHOD_UNDER_5EOK,
        "146449091",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("146449091"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == NEW_FACILITY_ID
    assert result.is_blocked is False


def test_same_condition_after_cutoff_uses_current_jngj_rule() -> None:
    raw = _raw(
        "전남광주통합특별시교육청 전남광주통합특별시여수교육지원청",
        "2026-07-20 10:00:00",
        "적격심사제-" + FACILITY_METHOD_UNDER_5EOK,
        "146449091",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("146449091"),
    )
    assert result.rule is not None
    assert result.rule.rule_id == JNGJ_FACILITY_ID
    assert result.is_blocked is False


def test_gwangju_chungsa_software_stays_blocked() -> None:
    raw = _raw(
        "전남광주통합특별시 광산구",
        "2025-10-21 10:01:34",
        "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
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
    assert result.is_blocked is True


def test_before_predecessor_effective_date_stays_blocked() -> None:
    raw = _raw(
        "전남광주통합특별시 목포시",
        "2023-03-01 10:00:00",
        "적격심사제-" + FACILITY_METHOD_5EOK_PLUS,
        "1205179091",
    )
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code="12",
        region_name="전남광주통합특별시",
        estimated_price=Decimal("1205179091"),
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH
