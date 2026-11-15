"""대구 예규 제238호·충남 공고 제2026-1235호 개정 후 판본 공고 명시 조달청 기준 시험.

정본: .orca/capsules/task_dgcn_revised_pps_stated_20261115/capsule.yaml
- 대구(27) 2026-05-11 시행 이후, 충남(44) 2026-07-13 시행 이후 공고 가운데 해당
  시·도 규칙에 유형 별표가 없어 LOCAL_RULE_NOT_FOUND 로 끝나고, 공고의 낙찰방법 적용
  기준(sucsfbidMthdAppStd)이 조달청 일반용역 적격심사 세부기준을 명시하며, 조달청 매칭
  결과가 있는 공고는 조달청 별표로 계산하고 JNGJ_STATED_PPS_WARNING 을 붙인다.
- 개정 후 판본의 별표 선택 조항도 조달청을 지목하지 않으므로 근거는 지침 조항이 아니라
  구판과 같은 '공고 명시' 다.
- 명시 기준이 없거나 다른 값이면 종전처럼 차단하고, 다른 지역·자체 별표가 있는 유형·
  건설폐기물 띠 표기 공고는 가로채지 않는다. 구판(예규 제223호·공고 제2019-2047호)
  판정도 그대로다.

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
LEASE_OVER_METHOD = "적격심사제-임대차 적격심사 추정가격 고시금액 이상"
FREIGHT_METHOD = "적격심사제-화물운송용역 적격심사 추정가격 고시금액미만"
WASTE_METHOD = "적격심사제-폐기물처리용역 적격심사 추정가격 고시금액미만"
CDW_BAND_METHOD = "적격심사제-추정가격 2억원 미만인 용역"

PPS_INSURANCE_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_02"
PPS_LEASE_OVER_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_18"
PPS_INSURANCE_PRE_20250901_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_02"
LOCAL_DAEGU_WASTE_RULE_ID = "SERVC_LOCAL_DAEGU_20260511_ATTACH_04"
LOCAL_CHUNGNAM_WASTE_RULE_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_03"

STATED_PPS = "조달청 일반용역 적격심사 세부기준"

DAEGU_CODE = "27"
DAEGU_NAME = "대구광역시"
CHUNGNAM_CODE = "44"
CHUNGNAM_NAME = "충청남도"
GANGWON_CODE = "42"
GANGWON_NAME = "강원특별자치도"

INSURANCE_LWLT_RATE = "47.995"


def _resolve(
    *,
    method: str,
    announced: str,
    institution_name: str,
    institution_code: str,
    region_code: str,
    region_name: str,
    app_std: str | None = STATED_PPS,
    price: str = "243999150",
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


def test_daegu_revised_insurance_uses_pps_rule() -> None:
    """R26BK01580775: 2026-06-15 대구공공시설관리공단 자동차종합보험."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-06-15 10:00:00",
        institution_name="대구공공시설관리공단",
        institution_code="B554808",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
        price="243999150",
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_daegu_revised_lease_uses_pps_rule() -> None:
    """R26BK01664152: 2026-08-11 대구공공시설관리공단 업무용 차량 임차."""
    result = _resolve(
        method=LEASE_OVER_METHOD,
        announced="2026-08-11 10:00:00",
        institution_name="대구공공시설관리공단",
        institution_code="B554808",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
        price="310229500",
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_LEASE_OVER_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_chungnam_revised_insurance_uses_pps_rule() -> None:
    """R26BK01815773: 2026-11-09 충청남도 아산시 시민 자전거보험."""
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-11-09 10:00:00",
        institution_name="충청남도 아산시",
        institution_code="4520000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
        price="219460000",
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_daegu_revised_window_starts_on_effective_date() -> None:
    """대구 예규 제238호 시행일 2026-05-11 00:00:00 부터 새 판본 구간이다."""
    on_start = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-05-11 00:00:00",
        institution_name="대구공공시설관리공단",
        institution_code="B554808",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
    )
    assert on_start.is_blocked is False
    assert on_start.rule is not None
    assert on_start.rule.rule_id == PPS_INSURANCE_PRE_20250901_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in on_start.warnings

    before = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-05-10 23:59:59",
        institution_name="대구공공시설관리공단",
        institution_code="B554808",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
    )
    assert before.is_blocked is False
    assert before.rule is not None
    assert before.rule.rule_id == PPS_INSURANCE_PRE_20250901_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in before.warnings


def test_chungnam_revised_window_starts_on_effective_date() -> None:
    """충남 공고 제2026-1235호 시행일 2026-07-13 00:00:00 부터 새 판본 구간이다."""
    on_start = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-07-13 00:00:00",
        institution_name="충청남도 아산시",
        institution_code="4520000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
        price="219460000",
    )
    assert on_start.is_blocked is False
    assert on_start.rule is not None
    assert on_start.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in on_start.warnings

    before = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-07-12 23:59:59",
        institution_name="충청남도 아산시",
        institution_code="4520000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
        price="219460000",
    )
    assert before.is_blocked is False
    assert before.rule is not None
    assert before.rule.rule_id == PPS_INSURANCE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in before.warnings


def test_revised_announcement_before_local_rule_window_stays_blocked() -> None:
    """시·도 규칙 선언의 가장 이른 시행일보다 앞선 공고는 새 분기 대상이 아니다."""
    daegu_before = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2022-09-29 23:59:59",
        institution_name="대구광역시",
        institution_code="5100000",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
    )
    assert daegu_before.is_blocked is True
    assert daegu_before.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert daegu_before.rule is None
    assert JNGJ_STATED_PPS_WARNING not in daegu_before.warnings

    chungnam_before = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2020-01-31 23:59:59",
        institution_name="충청남도",
        institution_code="4500000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
    )
    assert chungnam_before.is_blocked is True
    assert chungnam_before.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert chungnam_before.rule is None
    assert JNGJ_STATED_PPS_WARNING not in chungnam_before.warnings


def test_daegu_revised_missing_stated_standard_stays_blocked() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-06-15 10:00:00",
        institution_name="대구공공시설관리공단",
        institution_code="B554808",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
        app_std=None,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_chungnam_revised_other_stated_standard_stays_blocked() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-11-09 10:00:00",
        institution_name="충청남도 아산시",
        institution_code="4520000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
        app_std="지방자치단체 입찰 및 계약집행기준",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_other_region_in_revised_window_is_not_intercepted() -> None:
    result = _resolve(
        method=INSURANCE_UNDER_METHOD,
        announced="2026-06-15 10:00:00",
        institution_name="강원특별자치도청",
        institution_code="4200000",
        region_code=GANGWON_CODE,
        region_name=GANGWON_NAME,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_daegu_revised_own_annex_type_is_not_intercepted() -> None:
    """대구 예규 제238호 별표 4(폐기물처리용역)가 있는 유형은 지역 규칙을 유지한다."""
    result = _resolve(
        method=WASTE_METHOD,
        announced="2026-06-15 10:00:00",
        institution_name="대구광역시",
        institution_code="5100000",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
        price="199128182",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == LOCAL_DAEGU_WASTE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_chungnam_revised_own_annex_type_is_not_intercepted() -> None:
    """충남 공고 제2026-1235호 별표 3(폐기물처리용역)이 있는 유형은 지역 규칙을 유지한다."""
    result = _resolve(
        method=WASTE_METHOD,
        announced="2026-11-09 10:00:00",
        institution_name="충청남도",
        institution_code="4500000",
        region_code=CHUNGNAM_CODE,
        region_name=CHUNGNAM_NAME,
        price="199128182",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == LOCAL_CHUNGNAM_WASTE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_daegu_revised_cdw_band_route_is_not_intercepted() -> None:
    result = _resolve(
        method=CDW_BAND_METHOD,
        announced="2026-06-15 10:00:00",
        institution_name="대구광역시",
        institution_code="5100000",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
        price="150000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_QUAL_MOE_CDW_")
    assert JNGJ_STATED_PPS_WARNING not in result.warnings
