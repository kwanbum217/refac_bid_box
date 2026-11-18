"""공고 명시 기준(환경부고시·조달청) 라우팅 두 경로 시험.

정본: .orca/capsules/task_stated_basis_routing_20261118/capsule.yaml
- 공고가 적용 기준을 환경부고시 「건설폐기물처리용역 적격업체 평가기준」으로 명시하고
  낙찰방법명이 고시 띠 표기 6종과 맞으면, 시·도 세부유형 선택 대기
  (LOCAL_SERVICE_TYPE_UNRESOLVED)로 막혀도 고시 [별표] 해당 호로 계산한다.
- 공고가 적용 기준을 조달청 일반용역 적격심사 세부기준으로 명시하고 시·도 규칙
  미발견(LOCAL_RULE_NOT_FOUND)으로 막히면 지역을 가리지 않고 조달청 매칭 결과로 계산한다.
- 명시 표지나 띠 표기가 맞지 않는 공고, 지역 기준을 명시한 공고, 조달청 매칭 결과가
  차단인 공고는 종전 판정을 유지한다. 기존 통합특별시·대구·충남 분기와 부산 인력공급
  자동 매핑 공고의 판정도 바뀌지 않는다.

DB·Redis·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
    JNGJ_STATED_PPS_WARNING,
    MOE_CDW_STATED_WARNING,
    MOE_CDW_WARNING,
    RuleResolutionResult,
    resolve_evaluation_rule_from_raw_data,
)

STATED_PPS = "조달청 일반용역 적격심사 세부기준"
STATED_MOE = "건설폐기물처리용역 적격업체 평가기준"
STATED_ACADEMIC = "학술연구용역 적격심사 세부기준"
STATED_JEONNAM = "전라남도 일반용역 적격심사 세부기준(예규 제1075호)"

CDW_UNDER_2E_METHOD = "적격심사제-추정가격 2억원 미만인 용역"
PPS_BAND_METHOD = "적격심사제-추정가격 2억미만 1억이상"
ACADEMIC_UNDER_NOTICE_METHOD = "적격심사제-학술연구용역 적격심사 추정가격 고시금액 미만"
REPAIR_UNDER_METHOD = "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만"
DEMAND_AGENCY_METHOD = "적격심사제-수요기관 지정형 적격심사  추정가격 고시금액 미만"
SIMPLE_LABOR_BAND_METHOD = "적격심사제-추정가격 2억미만 1억이상 - 지역업체참여"
PASSENGER_UNDER_NOTICE_METHOD = "적격심사제-여객 육상운송용역 적격심사 추정가격 고시금액 미만"

MOE_CDW_UNDER_2E_RULE_ID = "SERVC_QUAL_MOE_CDW_ATTACH_04"
PPS_ACADEMIC_UNDER_NOTICE_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_06"
PPS_REPAIR_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_15"
PPS_DEMAND_AGENCY_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_17"

SEOUL_CODE = "11"
SEOUL_NAME = "서울특별시"
MERGED_CODE = "12"
MERGED_NAME = "전남광주통합특별시"
DAEGU_CODE = "27"
DAEGU_NAME = "대구광역시"
BUSAN_CODE = "26"
BUSAN_NAME = "부산광역시"
GANGWON_CODE = "42"
GANGWON_NAME = "강원특별자치도"


def _resolve(
    *,
    method: str,
    announced: str,
    institution_name: str,
    institution_code: str,
    region_code: str,
    region_name: str,
    app_std: str | None = None,
    price: str = "132016364",
    lwlt_rate: str | None = None,
    procurement_class: str | None = None,
    bid_name: str = "시험 공고",
    education_institution: bool = False,
) -> RuleResolutionResult:
    raw_data = {
        "bidNtceNo": "R26BK00000000",
        "bidNtceOrd": "000",
        "bidNtceDt": announced,
        "bidNtceNm": bid_name,
        "sucsfbidMthdCd": "낙030001",
        "sucsfbidMthdNm": method,
        "dminsttCd": institution_code,
        "dminsttNm": institution_name,
        "cntrctCnclsMthdNm": "일반경쟁",
        "presmptPrce": price,
    }
    if app_std is not None:
        raw_data["sucsfbidMthdAppStd"] = app_std
    if lwlt_rate is not None:
        raw_data["sucsfbidLwltRate"] = lwlt_rate
    if procurement_class is not None:
        raw_data["pubPrcrmntClsfcNm"] = procurement_class
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw_data,
        institution_regime="LOCAL",
        region_code=region_code,
        region_name=region_name,
        estimated_price=Decimal(price),
        education_institution=education_institution,
    )


def test_moe_stated_band_unresolved_uses_moe_annex() -> None:
    """R26BK01817736: 환경부고시 명시 + 고시 띠 표기면 세부유형 대기 대신 고시 제4호."""
    result = _resolve(
        method=CDW_UNDER_2E_METHOD,
        announced="2026-11-09 14:10:21",
        institution_name="서울주택도시개발공사",
        institution_code="Z003688",
        region_code=SEOUL_CODE,
        region_name=SEOUL_NAME,
        app_std=STATED_MOE,
        price="138760800",
        lwlt_rate="87.745",
        bid_name="홍릉 스타트업 랩 기존건물 해체공사 폐기물처리용역",
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == MOE_CDW_UNDER_2E_RULE_ID
    assert MOE_CDW_STATED_WARNING in result.warnings
    assert MOE_CDW_WARNING not in result.warnings


def test_moe_stated_requires_matching_band_notation() -> None:
    """환경부고시 명시라도 낙찰방법명이 고시 띠 표기 6종과 맞지 않으면 종전 차단."""
    result = _resolve(
        method=PPS_BAND_METHOD,
        announced="2026-11-09 14:10:21",
        institution_name="서울주택도시개발공사",
        institution_code="Z003688",
        region_code=SEOUL_CODE,
        region_name=SEOUL_NAME,
        app_std=STATED_MOE,
        price="138760800",
        lwlt_rate="87.745",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.rule is None
    assert MOE_CDW_STATED_WARNING not in result.warnings


def test_pps_stated_routes_to_pps_match() -> None:
    """R26BK01531664: 전남 학술 규칙이 없어도 조달청 명시가 있으면 조달청 별표."""
    result = _resolve(
        method=ACADEMIC_UNDER_NOTICE_METHOD,
        announced="2026-05-19 13:55:40",
        institution_name="전남광주통합특별시교육청 전남광주통합특별시장성교육지원청",
        institution_code="8692000",
        region_code=MERGED_CODE,
        region_name=MERGED_NAME,
        app_std=STATED_PPS,
        price="224681818",
        lwlt_rate="84.245",
        procurement_class="교육지원서비스",
        bid_name="2026. 장성 학산림교육(에코스쿨) 활성화 인증 교육 위탁운영 용역",
        education_institution=True,
    )
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PPS_ACADEMIC_UNDER_NOTICE_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_missing_pps_statement_stays_blocked() -> None:
    """조달청 명시가 없는 전남 학술 공고는 종전 LOCAL_RULE_NOT_FOUND 차단을 유지한다."""
    result = _resolve(
        method=ACADEMIC_UNDER_NOTICE_METHOD,
        announced="2026-05-19 13:55:40",
        institution_name="전남광주통합특별시교육청 전남광주통합특별시장성교육지원청",
        institution_code="8692000",
        region_code=MERGED_CODE,
        region_name=MERGED_NAME,
        app_std=None,
        price="224681818",
        lwlt_rate="84.245",
        procurement_class="교육지원서비스",
        education_institution=True,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_jeonnam_rule_statement_is_not_intercepted() -> None:
    """예규 제1075호 등 지역 기준을 명시한 공고는 조달청 표지가 없어 종전 차단을 유지한다."""
    result = _resolve(
        method=ACADEMIC_UNDER_NOTICE_METHOD,
        announced="2026-05-19 13:55:40",
        institution_name="전남광주통합특별시교육청 전남광주통합특별시장성교육지원청",
        institution_code="8692000",
        region_code=MERGED_CODE,
        region_name=MERGED_NAME,
        app_std=STATED_JEONNAM,
        price="224681818",
        lwlt_rate="84.245",
        procurement_class="교육지원서비스",
        education_institution=True,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_pps_stated_requires_pps_match() -> None:
    """조달청 명시가 있어도 조달청 매칭 결과가 없으면 종전 차단을 유지한다."""
    result = _resolve(
        method=PASSENGER_UNDER_NOTICE_METHOD,
        announced="2026-06-01 10:00:00",
        institution_name="강원특별자치도청",
        institution_code="4200000",
        region_code=GANGWON_CODE,
        region_name=GANGWON_NAME,
        app_std=STATED_PPS,
        price="132016364",
        lwlt_rate="87.995",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings


def test_jngj_existing_branch_is_unchanged() -> None:
    """통합특별시 분기의 기존 결과(조달청 매칭 + 경고)가 그대로다."""
    result = _resolve(
        method=REPAIR_UNDER_METHOD,
        announced="2026-08-01 10:00:00",
        institution_name="전남광주통합특별시 무안청사",
        institution_code="6130769",
        region_code=MERGED_CODE,
        region_name=MERGED_NAME,
        app_std=STATED_PPS,
        price="132016364",
        lwlt_rate="86.245",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_REPAIR_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_dgcn_existing_branch_is_unchanged() -> None:
    """대구·충남 구판 분기의 기존 결과가 그대로다."""
    result = _resolve(
        method=DEMAND_AGENCY_METHOD,
        announced="2026-02-27 10:00:00",
        institution_name="대구광역시",
        institution_code="6270000",
        region_code=DAEGU_CODE,
        region_name=DAEGU_NAME,
        app_std=STATED_PPS,
        price="132016364",
        lwlt_rate="84.245",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_DEMAND_AGENCY_RULE_ID
    assert JNGJ_STATED_PPS_WARNING in result.warnings


def test_busan_simple_labor_band_is_unchanged() -> None:
    """부산 인력공급서비스 띠 공고는 이번 범위 밖이라 종전 세부유형 대기 차단을 유지한다."""
    result = _resolve(
        method=SIMPLE_LABOR_BAND_METHOD,
        announced="2025-12-22 15:49:17",
        institution_name="부산광역시 사하구 을숙도문화회관",
        institution_code="3340054",
        region_code=BUSAN_CODE,
        region_name=BUSAN_NAME,
        app_std=STATED_ACADEMIC,
        price="140999127",
        lwlt_rate="87.745",
        procurement_class="인력공급서비스",
        bid_name="2026년 을숙도 들락날락 안전요원 인력 파견 용역",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.rule is None
    assert JNGJ_STATED_PPS_WARNING not in result.warnings
