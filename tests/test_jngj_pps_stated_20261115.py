"""전남광주통합특별시 공고 명시 조달청 기준 적용 시험.

정본: .orca/capsules/task_jngj_pps_stated_20261115/capsule.yaml
- 지침 시행일(2026-07-16) 이후 통합특별시 공고 가운데 지침에 해당 유형 별표가 없어
  LOCAL_RULE_NOT_FOUND 로 끝나고, 공고의 낙찰방법 적용 기준(sucsfbidMthdAppStd)이
  조달청 일반용역 적격심사 세부기준을 명시하며, 조달청 매칭 결과가 있는 공고는
  조달청 별표로 계산하고 JNGJ_STATED_PPS_WARNING 을 붙인다.
- 수요기관명이 통합 명칭으로 시작하면 지역 축이 옛 계열 코드(46·29)로 남아 있어도 같다.
- 같은 세부유형의 지침 별표가 있어도 공고가 조달청 기준을 명시하면 조달청 별표로
  계산하고 JNGJ_STATED_PPS_WARNING 을 붙인다(사용자 결정, 2026-11-15).
- 명시 기준이 없거나 다른 값이면 종전처럼 차단하고, 시행일 이전 공고·다른 지역·
  건설폐기물 띠 표기 공고는 가로채지 않는다.

DB·Redis·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    JEONNAM_PPS_FALLBACK_WARNING,
    JNGJ_LOCAL_RULE_EFFECTIVE_DATE,
    JNGJ_STATED_PPS_WARNING,
    RuleResolutionResult,
    resolve_evaluation_rule_from_raw_data,
)

REPAIR_UNDER_METHOD = "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만"
REPAIR_OVER_METHOD = "적격심사제-수리ㆍ점검용역 적격심사 5억원 미만 고시금액 이상"
LEASE_METHOD = "적격심사제-임대차 적격심사 추정가격 고시금액 미만"
INSURANCE_METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원미만"
WASTE_METHOD = "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만"
CDW_BAND_METHOD = "적격심사제-추정가격 2억원 미만인 용역"

PPS_REPAIR_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_15"
PPS_REPAIR_OVER_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_16"
PPS_LEASE_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_17"
PPS_INSURANCE_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_02"
PPS_WASTE_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_08"
JNGJ_WASTE_RULE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"

STATED_PPS = "조달청 일반용역 적격심사 세부기준"
MERGED_REGION_CODE = "12"
MERGED_REGION_NAME = "전남광주통합특별시"
LEGACY_JEONNAM_CODE = "46"
LEGACY_JEONNAM_NAME = "전라남도"


def _resolve(
    *,
    method: str,
    announced: str,
    institution_name: str,
    institution_code: str,
    region_code: str = MERGED_REGION_CODE,
    region_name: str = MERGED_REGION_NAME,
    app_std: str | None = STATED_PPS,
    price: str = "132016364",
    lwlt_rate: str = "86.245",
) -> RuleResolutionResult:
    raw_data = {
        "bidNtceNo": "R26BK00000000",
        "bidNtceDt": announced,
        "sucsfbidMthdNm": method,
        "sucsfbidLwltRate": lwlt_rate,
        "dminsttNm": institution_name,
        "dminsttCd": institution_code,
        "cntrctCnclsMthdNm": "지방계약",
        "presmptPrce": price,
    }
    if app_std is not None:
        raw_data["sucsfbidMthdAppStd"] = app_std
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw_data,
        institution_regime="LOCAL",
        region_code=region_code,
        region_name=region_name,
        estimated_price=Decimal(price),
    )


def test_stated_repair_uses_pps_rule() -> None:
    result = _resolve(
        method=REPAIR_UNDER_METHOD,
        announced="2026-07-20 17:49:16",
        institution_name="전남광주통합특별시 무안청사",
        institution_code="6130769",
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_REPAIR_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_stated_repair_over_notice_amount_uses_pps_rule() -> None:
    result = _resolve(
        method=REPAIR_OVER_METHOD,
        announced="2026-08-20 18:45:24",
        institution_name="전남광주통합특별시 무안청사",
        institution_code="6130769",
        price="239410909",
        lwlt_rate="82.495",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_REPAIR_OVER_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_stated_repair_uses_institution_name_on_legacy_region_axis() -> None:
    result = _resolve(
        method=REPAIR_UNDER_METHOD,
        announced="2026-08-27 15:46:18",
        institution_name="전남광주통합특별시 신안군",
        institution_code="5910000",
        region_code=LEGACY_JEONNAM_CODE,
        region_name=LEGACY_JEONNAM_NAME,
        price="112614790",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_REPAIR_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_stated_lease_uses_pps_rule() -> None:
    result = _resolve(
        method=LEASE_METHOD,
        announced="2026-08-10 13:28:23",
        institution_name="전남광주통합특별시교육청 전남광주통합특별시무안교육지원청",
        institution_code="8662000",
        price="138292636",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_LEASE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_stated_insurance_uses_pps_rule() -> None:
    result = _resolve(
        method=INSURANCE_METHOD,
        announced="2026-09-21 09:20:20",
        institution_name="전남광주통합특별시 영암군",
        institution_code="5875000",
        price="217000000",
        lwlt_rate="47.995",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_missing_stated_standard_stays_blocked() -> None:
    result = _resolve(
        method=REPAIR_UNDER_METHOD,
        announced="2026-08-01 10:00:00",
        institution_name="전남광주통합특별시 무안청사",
        institution_code="6130769",
        app_std=None,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_other_stated_standard_stays_blocked() -> None:
    result = _resolve(
        method=REPAIR_UNDER_METHOD,
        announced="2026-08-01 10:00:00",
        institution_name="전남광주통합특별시 무안청사",
        institution_code="6130769",
        app_std="지방자치단체 입찰 및 계약집행기준",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_pre_effective_announcement_keeps_previous_branch() -> None:
    before = JNGJ_LOCAL_RULE_EFFECTIVE_DATE - timedelta(days=1)
    result = _resolve(
        method=REPAIR_UNDER_METHOD,
        announced=f"{before.isoformat()} 23:59:59",
        institution_name="전남광주통합특별시 무안청사",
        institution_code="6130769",
    )
    assert JNGJ_STATED_PPS_WARNING not in result.warnings
    assert JEONNAM_PPS_FALLBACK_WARNING in result.warnings


def test_other_region_stays_blocked() -> None:
    result = _resolve(
        method=REPAIR_UNDER_METHOD,
        announced="2026-08-01 10:00:00",
        institution_name="강원특별자치도청",
        institution_code="4200000",
        region_code="42",
        region_name="강원특별자치도",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_stated_pps_uses_pps_rule_even_with_own_annex_type() -> None:
    """지침에 같은 세부유형 별표가 있어도 공고 명시 조달청 기준을 우선합니다."""
    result = _resolve(
        method=WASTE_METHOD,
        announced="2026-08-01 10:00:00",
        institution_name="전남광주통합특별시 화순군",
        institution_code="5890000",
        price="163636364",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_WASTE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_missing_stated_standard_keeps_own_annex_type() -> None:
    """공고 명시가 없으면 지침 자체 별표를 그대로 씁니다."""
    result = _resolve(
        method=WASTE_METHOD,
        announced="2026-08-01 10:00:00",
        institution_name="전남광주통합특별시 화순군",
        institution_code="5890000",
        price="163636364",
        app_std=None,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == JNGJ_WASTE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_cdw_band_route_is_not_intercepted() -> None:
    result = _resolve(
        method=CDW_BAND_METHOD,
        announced="2026-08-01 10:00:00",
        institution_name="전남광주통합특별시 무안청사",
        institution_code="6130769",
    )
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_QUAL_MOE_CDW_")
    assert JNGJ_STATED_PPS_WARNING not in result.warnings
