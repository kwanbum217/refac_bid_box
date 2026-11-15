"""통합특별시 출범 전 전남 공고의 예규 제1075호 제11조 ① 준용 시험.

정본: .orca/capsules/task_jeonnam_fallback_fix_20261115/capsule.yaml
- 통합 전 공고는 institution_sido 가 12(전남광주통합특별시)로 잡혀도 수요기관명이
  전남 계열이면 전남 준용 분기(조달청 매칭 결과 + JEONNAM_PPS_FALLBACK_WARNING)로
  계산한다.
- 학술연구용역은 원문 적용 범위가 확정되지 않아 종전처럼 차단한다.
- 광주 계열, 2026-07-16 이후 공고, 다른 시·도는 이 분기에 걸리지 않는다.

DB·Redis·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from typing import Any

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    JEONNAM_PPS_FALLBACK_WARNING,
    resolve_evaluation_rule_from_raw_data,
)

METHOD_LEASE = "적격심사제-임대차 적격심사 추정가격 고시금액 이상"
METHOD_INSURANCE = "적격심사제-보험용역 적격심사 추정가격 5억원미만"
METHOD_REPAIR = "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만"
METHOD_ACADEMIC = "적격심사제-학술연구용역 적격심사 추정가격 고시금액 미만"

PPS_LEASE_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_16"
PPS_INSURANCE_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_02"
PPS_REPAIR_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_15"

MERGED_REGION_CODE = "12"
MERGED_REGION_NAME = "전남광주통합특별시"
MERGED_REGIME_CHANGE = "2026-07-16"


def _resolve(
    *,
    method: str,
    announced: str,
    institution_name: str,
    institution_code: str = "6130769",
    region_code: str = MERGED_REGION_CODE,
    region_name: str = MERGED_REGION_NAME,
    local_service_type: str | None = None,
    education_institution: bool = False,
) -> Any:
    raw_data = {
        "bidNtceNo": "R25BK00000000",
        "bidNtceDt": announced,
        "sucsfbidMthdNm": method,
        "dminsttNm": institution_name,
        "dminsttCd": institution_code,
        "cntrctCnclsMthdNm": "지방계약",
    }
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw_data,
        region_code=region_code,
        region_name=region_name,
        local_service_type=local_service_type,
        education_institution=education_institution,
    )


def test_legacy_lease_uses_pps_rule() -> None:
    result = _resolve(
        method=METHOD_LEASE,
        announced="2025-12-02 14:49:34",
        institution_name=("전남광주통합특별시교육청 전남광주통합특별시고흥교육지원청"),
        institution_code="8592000",
        education_institution=True,
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_LEASE_RULE_ID
    assert JEONNAM_PPS_FALLBACK_WARNING in result.warnings


def test_legacy_insurance_uses_pps_rule() -> None:
    result = _resolve(
        method=METHOD_INSURANCE,
        announced="2025-11-24 20:19:48",
        institution_name="전남광주통합특별시 무안청사",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JEONNAM_PPS_FALLBACK_WARNING in result.warnings


def test_legacy_repair_inspection_uses_pps_rule() -> None:
    result = _resolve(
        method=METHOD_REPAIR,
        announced="2026-05-15 18:37:37",
        institution_name="전남광주통합특별시 무안청사",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_REPAIR_RULE_ID
    assert JEONNAM_PPS_FALLBACK_WARNING in result.warnings


def test_legacy_academic_stays_blocked() -> None:
    result = _resolve(
        method=METHOD_ACADEMIC,
        announced="2026-05-19 13:55:40",
        institution_name=("전남광주통합특별시교육청 전남광주통합특별시장성교육지원청"),
        institution_code="8692000",
        education_institution=True,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


def test_post_merge_announcement_stays_blocked() -> None:
    result = _resolve(
        method=METHOD_REPAIR,
        announced=f"{MERGED_REGIME_CHANGE} 09:00:00",
        institution_name="전남광주통합특별시 무안청사",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


def test_gwangju_institution_stays_blocked() -> None:
    result = _resolve(
        method=METHOD_REPAIR,
        announced="2026-03-19 10:00:00",
        institution_name="전남광주통합특별시 광주광역시 동구청",
        institution_code="1234567",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


def test_unmapped_legacy_institution_stays_blocked() -> None:
    result = _resolve(
        method=METHOD_REPAIR,
        announced="2026-03-19 10:00:00",
        institution_name="전남광주통합특별시 해양수산재단",
        institution_code="2345678",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


def test_other_region_keeps_local_rule_not_found() -> None:
    result = _resolve(
        method=METHOD_REPAIR,
        announced="2026-03-19 10:00:00",
        institution_name="전남광주통합특별시 무안청사",
        region_code="44",
        region_name="충청남도",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings
