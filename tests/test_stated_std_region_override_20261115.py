"""지역 규칙 공고의 공고 명시 기준 우선 적용 시험.

정본: .orca/capsules/task_stated_std_region_override_20261115/capsule.yaml
- 시·도 규칙이 확정된 공고라도 낙찰방법 적용 기준(sucsfbidMthdAppStd)이 조달청
  일반용역 적격심사 세부기준을 명시하면 조달청 매칭 결과로 계산하고
  JNGJ_STATED_PPS_WARNING 을 붙인다(D13, 사용자 결정 2026-11-15).
- 같은 값이 건설폐기물처리용역 적격업체 평가기준을 명시하면 낙찰방법명 띠에 맞는
  환경부고시 [별표] 규칙으로 계산하고 MOE_CDW_STATED_WARNING 을 붙인다.
- 명시가 없거나 다른 기준을 명시한 공고, 조달청·환경부 매칭 결과가 없는 공고는
  기존 시·도 규칙 판정을 유지한다.

DB·Redis·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    JNGJ_STATED_PPS_WARNING,
    MOE_CDW_STATED_WARNING,
    RULE_SCOPE_ALL,
    RuleResolutionResult,
    resolve_evaluation_rule_from_raw_data,
)

STATED_PPS = "조달청 일반용역 적격심사 세부기준"
STATED_MOE = "건설폐기물처리용역 적격업체 평가기준"
STATED_ACADEMIC = "학술연구용역 적격심사 세부기준"
OTHER_STATED = "지방자치단체 입찰시 낙찰자 결정기준"

INSURANCE_UNDER_METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원미만"
INSURANCE_OVER_METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원이상"
PASSENGER_UNDER_METHOD = "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만"
CDW_MID_METHOD = "적격심사제-추정가격 5억원 미만 2억원 이상인 용역"
FISHERY_METHOD = "적격심사제-어장정화·정비용역 적격심사 추정가격 고시금액 미만"

PPS_INSURANCE_2025_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_02"
SEOUL_INSURANCE_RULE_ID = "SERVC_LOCAL_SEOUL_20240812_ATTACH_01_5"
GN_GENERAL_RULE_ID = "SERVC_LOCAL_GN_20230105_ATTACH_01"
JEONNAM_WASTE_RULE_ID = "SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4"
JNGJ_FISHERY_RULE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_06"
MOE_CDW_MID_RULE_ID = "SERVC_QUAL_MOE_CDW_ATTACH_03"


def _resolve(
    *,
    method: str,
    announced: str,
    region_code: str,
    region_name: str,
    institution_name: str,
    institution_code: str = "0000000",
    app_std: str | None = None,
    price: str = "200000000",
    lwlt_rate: str | None = None,
    procurement_class: str | None = None,
) -> RuleResolutionResult:
    raw_data = {
        "bidNtceNo": "R25BK00000000",
        "bidNtceDt": announced,
        "sucsfbidMthdNm": method,
        "dminsttNm": institution_name,
        "dminsttCd": institution_code,
        "cntrctCnclsMthdNm": "지방계약",
        "presmptPrce": price,
    }
    if procurement_class is not None:
        raw_data["pubPrcrmntDtlClsfcNm"] = procurement_class
    if app_std is not None:
        raw_data["sucsfbidMthdAppStd"] = app_std
    if lwlt_rate is not None:
        raw_data["sucsfbidLwltRate"] = lwlt_rate
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw_data,
        institution_regime="LOCAL",
        region_code=region_code,
        region_name=region_name,
        estimated_price=Decimal(price),
    )


def test_stated_pps_uses_pps_same_subtype() -> None:
    """(a) 시·도에 같은 세부유형 별표가 있어도 조달청 명시 공고는 조달청 규칙입니다."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2025-10-01 10:00:00",
        region_code="11",
        region_name="서울특별시",
        institution_name="서울특별시 용산구",
        app_std=STATED_PPS,
        lwlt_rate="47.995",
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_2025_RULE_ID
    assert result.rule.rule_id != SEOUL_INSURANCE_RULE_ID
    assert result.scope_stage == RULE_SCOPE_ALL
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_stated_pps_replaces_local_general_fallback() -> None:
    """(b) 시·도 일반 별표로 폴백하던 공고도 조달청 명시면 조달청 동일 세부유형입니다."""
    result = _resolve(
        method=INSURANCE_OVER_METHOD,
        announced="2025-10-01 10:00:00",
        region_code="48",
        region_name="경상남도",
        institution_name="경상남도 함안군",
        app_std=STATED_PPS,
        price="600000000",
        lwlt_rate="47.995",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_2025_RULE_ID
    assert result.rule.rule_id != GN_GENERAL_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_local_regime_mismatch_is_not_overridden() -> None:
    """시·도 규칙 시행일이 공고일보다 늦어 막히던 공고는 공고 명시로 풀지 않습니다."""
    result = _resolve(
        method=PASSENGER_UNDER_METHOD,
        announced="2026-03-06 17:11:40",
        region_code="12",
        region_name="전남광주통합특별시",
        institution_name="전남광주통합특별시교육청 전남광주통합특별시교육청AI교육원",
        app_std=STATED_PPS,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == "RULE_REGIME_MISMATCH"
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_stated_moe_cdw_uses_environment_rule() -> None:
    """(c) 건설폐기물 기준 명시 공고는 환경부고시 규칙으로 계산합니다."""
    result = _resolve(
        method=CDW_MID_METHOD,
        announced="2025-10-01 10:00:00",
        region_code="46",
        region_name="전라남도",
        institution_name="전라남도 고흥군",
        app_std=STATED_MOE,
        price="300000000",
        procurement_class="건설폐기물처리서비스",
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == MOE_CDW_MID_RULE_ID
    assert result.rule.rule_id != JEONNAM_WASTE_RULE_ID
    assert result.effective_lwlt_rate == Decimal("86.745")
    assert result.scope_stage == RULE_SCOPE_ALL
    assert MOE_CDW_STATED_WARNING in result.warnings


def test_missing_stated_standard_keeps_local_rule() -> None:
    """(d) 명시가 없는 공고는 기존 시·도 규칙 판정을 유지합니다."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2025-10-01 10:00:00",
        region_code="11",
        region_name="서울특별시",
        institution_name="서울특별시 용산구",
        lwlt_rate="47.995",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SEOUL_INSURANCE_RULE_ID
    assert result.scope_stage == "REGION"
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_other_stated_standard_keeps_local_rule() -> None:
    """(d) 다른 기준을 명시한 공고도 기존 시·도 규칙 판정을 유지합니다."""
    for app_std in (STATED_ACADEMIC, OTHER_STATED):
        result = _resolve(
            method=INSURANCE_UNDER_METHOD,
            announced="2025-10-01 10:00:00",
            region_code="11",
            region_name="서울특별시",
            institution_name="서울특별시 용산구",
            app_std=app_std,
            lwlt_rate="47.995",
        )
        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == SEOUL_INSURANCE_RULE_ID
        assert JNGJ_STATED_PPS_WARNING not in result.warnings
        assert MOE_CDW_STATED_WARNING not in result.warnings


def test_stated_pps_without_pps_match_keeps_local_rule() -> None:
    """(e) 조달청 매칭 결과가 없으면 기존 시·도 규칙 판정을 유지합니다."""
    result = _resolve(
        method=FISHERY_METHOD,
        announced="2026-08-01 10:00:00",
        region_code="12",
        region_name="전남광주통합특별시",
        institution_name="전남광주통합특별시 완도군",
        app_std=STATED_PPS,
        price="300000000",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == JNGJ_FISHERY_RULE_ID
    assert result.scope_stage == "REGION"
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_stated_moe_without_moe_match_keeps_local_rule() -> None:
    """(e) 환경부고시 쪽 매칭 결과가 없으면 기존 시·도 규칙 판정을 유지합니다."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2025-10-01 10:00:00",
        region_code="11",
        region_name="서울특별시",
        institution_name="서울특별시 용산구",
        app_std=STATED_MOE,
        lwlt_rate="47.995",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SEOUL_INSURANCE_RULE_ID
    assert result.scope_stage == "REGION"
    assert MOE_CDW_STATED_WARNING not in result.warnings
