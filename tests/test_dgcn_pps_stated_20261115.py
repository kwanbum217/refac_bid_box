"""대구 예규 제223호·충남 공고 제2019-2047호 구판 공고 명시 조달청 기준 적용 시험.

정본: .orca/capsules/task_dgcn_pps_stated_20261115/capsule.yaml
- 대구(27)·충남(44) 구판 적용 구간 공고 가운데 해당 시·도 규칙에 유형 별표가 없어
  LOCAL_RULE_NOT_FOUND 로 끝나고, 공고의 낙찰방법 적용 기준(sucsfbidMthdAppStd)이
  조달청 일반용역 적격심사 세부기준을 명시하며, 조달청 매칭 결과가 있는 공고는
  조달청 별표로 계산하고 JNGJ_STATED_PPS_WARNING 을 붙인다.
- 같은 세부유형의 시·도 별표가 있어도 공고가 조달청 기준을 명시하면 조달청 별표로
  계산하고 JNGJ_STATED_PPS_WARNING 을 붙인다(사용자 결정, 2026-11-15).
- 명시 기준이 없거나 다른 값이면 종전처럼 차단한다. 공고 명시가 없는 다른 지역 공고는
  시·도 자체 별표를 유지하고, 시·도 규칙도 없으면 종전 차단을 유지한다. 조달청 명시는
  2026-11-18부터 지역을 가리지 않는다.
- 대구 예규 제238호(2026-05-11 시행)·충남 공고 제2026-1235호(2026-07-13 시행) 이후
  공고도 같은 근거로 계산합니다(사용자 결정, 2026-11-15).

DB·Redis·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    JNGJ_STATED_PPS_WARNING,
    RuleResolutionResult,
    resolve_evaluation_rule_from_raw_data,
)

INSURANCE_UNDER_METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원미만"
INSURANCE_OVER_METHOD = "적격심사제-보험용역 적격심사 추정가격 5억원이상"
DEMAND_AGENCY_METHOD = "적격심사제-수요기관 지정형 적격심사  추정가격 고시금액 미만"

PPS_INSURANCE_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_02"
PPS_INSURANCE_RULE_POST_20260526_ID = "SERVC_QUAL_POST_20260526_ATTACH_02"
PPS_DEMAND_AGENCY_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_17"

STATED_PPS = "조달청 일반용역 적격심사 세부기준"

DAEGU_CODE = "27"
DAEGU_NAME = "대구광역시"
CHUNGNAM_CODE = "44"
CHUNGNAM_NAME = "충청남도"
INSURANCE_LWLT_RATE = "47.995"
DEMAND_AGENCY_LWLT_RATE = "84.245"


def _resolve(
    *,
    method: str,
    announced: str,
    institution_name: str,
    institution_code: str,
    region_code: str,
    region_name: str,
    app_std: str | None = STATED_PPS,
    price: str = "132016364",
    lwlt_rate: str = INSURANCE_LWLT_RATE,
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


def test_daegu_demand_agency_uses_pps_rule() -> None:
    result = _resolve(
        method=DEMAND_AGENCY_METHOD,
        announced="2026-02-27 10:00:00",
        institution_name="대구광역시",
        institution_code="6270000",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
        lwlt_rate=DEMAND_AGENCY_LWLT_RATE,
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_DEMAND_AGENCY_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_daegu_insurance_uses_pps_rule() -> None:
    result = _resolve(
        method=INSURANCE_OVER_METHOD,
        announced="2026-04-07 10:00:00",
        institution_name="대구공공시설관리공단",
        institution_code="B554808",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
        price="217000000",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_chungnam_insurance_uses_pps_rule() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-01-13 10:00:00",
        institution_name="충청남도 예산군",
        institution_code="4610000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_daegu_day_before_new_version_uses_pps_rule() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-05-10 23:59:59",
        institution_name="대구공공시설관리공단",
        institution_code="B554808",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_chungnam_day_before_new_version_uses_pps_rule() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-07-12 23:59:59",
        institution_name="충청남도 아산시",
        institution_code="4520000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_POST_20260526_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_missing_stated_standard_stays_blocked() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-02-27 10:00:00",
        institution_name="충청남도 예산군",
        institution_code="4610000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
        app_std=None,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_other_stated_standard_stays_blocked() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-02-27 10:00:00",
        institution_name="충청남도 예산군",
        institution_code="4610000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
        app_std="지방자치단체 입찰 및 계약집행기준",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_daegu_new_version_announcement_uses_pps_rule() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-05-11 00:00:00",
        institution_name="대구공공시설관리공단",
        institution_code="B554808",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_chungnam_new_version_announcement_uses_pps_rule() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-07-13 00:00:00",
        institution_name="충청남도 아산시",
        institution_code="4520000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_POST_20260526_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_other_region_without_local_rule_uses_pps_rule() -> None:
    """시·도 규칙이 없어도 공고 명시 조달청 기준이면 다른 지역도 조달청 별표를 씁니다."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-02-27 10:00:00",
        institution_name="강원특별자치도청",
        institution_code="4200000",
        region_code="42",
        region_name="강원특별자치도",
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_other_region_without_stated_standard_stays_blocked() -> None:
    """공고 명시가 없고 시·도 규칙도 없으면 종전 LOCAL_RULE_NOT_FOUND 차단을 유지합니다."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-02-27 10:00:00",
        institution_name="강원특별자치도청",
        institution_code="4200000",
        region_code="42",
        region_name="강원특별자치도",
        app_std=None,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_other_region_stated_pps_uses_pps_rule() -> None:
    """공고 명시 조달청 기준은 다른 지역의 같은 세부유형 별표보다 우선합니다."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-02-27 10:00:00",
        institution_name="서울특별시",
        institution_code="6110000",
        region_code="11",
        region_name="서울특별시",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_other_region_without_stated_standard_keeps_local_rule() -> None:
    """공고 명시가 없으면 다른 지역의 자체 별표를 그대로 씁니다."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-02-27 10:00:00",
        institution_name="서울특별시",
        institution_code="6110000",
        region_code="11",
        region_name="서울특별시",
        app_std=None,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_LOCAL_SEOUL_")
    assert JNGJ_STATED_PPS_WARNING not in result.warnings
