"""지방계약 교육 계열 기관 공고의 조달청 일반용역 기준 대체 경로 시험.

정본: .orca/capsules/task_edu_pps_fallback_20261017/capsule.yaml
- 시·도를 산출하지 못한 교육 계열 공고만 LOCAL_RULE_NOT_FOUND 대신 진입 직전의 조달청
  별표 매칭 결과로 풀고 경고(EDU_PPS_FALLBACK_WARNING)를 붙인다.
- 시·도 규칙으로 풀리던 교육 계열 공고, 교육 계열이 아닌 지방계약 공고, 조달청 별표에도
  없는 공고, 기술용역 분기의 판정은 바꾸지 않는다.
- is_education_institution 과 classify_contract_regime 의 교육 판정이 일치한다.

DB·.env 를 쓰지 않습니다. 전량 시험은 -m 'not data_assets' 로 돌립니다.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.app.services.demand_institutions import (
    classify_contract_regime,
    institution_sido,
    is_education_institution,
)
from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
    BLOCK_CODE_RULE_NOT_FOUND,
    EDU_PPS_FALLBACK_WARNING,
    RULE_SCOPE_ALL,
    RULE_SCOPE_REGION,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)

METHOD_FACILITY = "시설분야용역 적격심사 추정가격 5억원 이상"
METHOD_GENERIC = "추정가격 2억원 미만인 용역"
METHOD_UNKNOWN = "알수없는 낙찰방법"
BID_DATE = "2026-06-01"

# 실제 g2b_demand_institutions 행과 같은 구성입니다. 교육청·공립 학교는 toplvl_instt_nm 이
# 시·도 본청이 아니라 교육청 이름이라 institution_sido 가 (None, None) 을 돌려줍니다.
EDU_OFFICE: dict[str, Any] = {
    "dminstt_cd": "7150000",
    "dminstt_nm": "부산광역시교육청",
    "jrsdctn_div_nm": "지방자치단체",
    "instt_ty_lrgclsfc_nm": "교육행정조직",
    "instt_ty_midclsfc_nm": "시, 도교육청",
    "rgn_cd": "26230",
    "rgn_nm": "부산광역시 부산진구",
    "toplvl_instt_cd": "7150000",
    "toplvl_instt_nm": "부산광역시교육청",
}
EDU_SCHOOL: dict[str, Any] = {
    "dminstt_cd": "7010077",
    "dminstt_nm": "서울특별시교육청 면목고등학교",
    "jrsdctn_div_nm": "교육기관",
    "instt_ty_lrgclsfc_nm": "고등학교",
    "instt_ty_smlclsfc_nm": "공립",
    "rgn_cd": "11260",
    "rgn_nm": "서울특별시 중랑구",
    "toplvl_instt_cd": "7010000",
    "toplvl_instt_nm": "서울특별시교육청",
}
# 시·도 본청 값이 살아 있는 교육 계열 기관입니다. institution_sido 가 시·도를 산출합니다.
EDU_WITH_SIDO: dict[str, Any] = {
    "dminstt_cd": "7240000",
    "dminstt_nm": "경상북도교육청",
    "jrsdctn_div_nm": "지방자치단체",
    "instt_ty_lrgclsfc_nm": "교육행정조직",
    "instt_ty_midclsfc_nm": "시, 도교육청",
    "rgn_cd": "47110",
    "rgn_nm": "경상북도 안동시",
    "toplvl_instt_cd": "7240000",
    "toplvl_instt_nm": "경상북도",
}
LOCAL_GOVERNMENT: dict[str, Any] = {
    "dminstt_cd": "9990000",
    "dminstt_nm": "시험시청",
    "jrsdctn_div_nm": "지방자치단체",
    "rgn_cd": "11110",
    "rgn_nm": "서울특별시 종로구",
}


def _resolve(**kwargs: Any):
    params: dict[str, Any] = {
        "category": "Servc",
        "prearng_prce_dcsn_mthd_nm": "복수예가",
        "sucsfbid_mthd_nm": METHOD_FACILITY,
        "contract_regime": "LOCAL",
        "bid_ntce_dt": BID_DATE,
    }
    params.update(kwargs)
    return resolve_evaluation_rule(**params)


def _pps_reference():
    """같은 공고를 조달청 기본 경로(비 LOCAL)로 판별한 기준 결과입니다."""
    return _resolve(contract_regime=None)


# --------------------------------------------------------------------------- #
# 1. 시·도 미산출 교육 계열 공고가 조달청 기준으로 풀린다
# --------------------------------------------------------------------------- #


def test_education_without_sido_uses_pps_rule() -> None:
    assert institution_sido(EDU_OFFICE) == (None, None)
    reference = _pps_reference()
    assert reference.is_blocked is False
    assert reference.rule is not None

    result = _resolve(education_institution=True)
    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == reference.rule.rule_id
    assert result.rule.institution_scope == RULE_SCOPE_ALL
    assert result.scope_stage == RULE_SCOPE_ALL
    assert result.effective_lwlt_rate == reference.effective_lwlt_rate
    assert EDU_PPS_FALLBACK_WARNING in result.warnings


def test_education_school_without_sido_uses_pps_rule() -> None:
    assert institution_sido(EDU_SCHOOL) == (None, None)
    result = _resolve(education_institution=True)
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.scope_stage == RULE_SCOPE_ALL
    assert EDU_PPS_FALLBACK_WARNING in result.warnings


def test_education_without_sido_keeps_rule_not_found_without_pps_rule() -> None:
    """조달청 별표에도 없는 낙찰방법은 RULE_NOT_FOUND 로 남고 경고를 붙이지 않는다."""
    result = _resolve(sucsfbid_mthd_nm=METHOD_UNKNOWN, education_institution=True)
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert result.rule is None
    assert EDU_PPS_FALLBACK_WARNING not in result.warnings


def test_fallback_requires_education_flag() -> None:
    """교육 계열이 아니면 기존처럼 LOCAL_RULE_NOT_FOUND 로 막는다."""
    result = _resolve(education_institution=False)
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None

    default = _resolve()
    assert default.is_blocked is True
    assert default.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND


def test_fallback_requires_local_regime() -> None:
    """국가계약 경로에는 대체 경로가 끼어들지 않는다."""
    result = _resolve(contract_regime="NATIONAL", education_institution=True)
    assert result.is_blocked is False
    assert result.rule is not None
    assert EDU_PPS_FALLBACK_WARNING not in result.warnings


def test_raw_data_path_passes_education_flag() -> None:
    """호출부가 쓰는 raw_data 경로도 같은 판정을 낸다."""
    raw_data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": METHOD_FACILITY,
        "sucsfbidLwltRate": "87.995",
        "bidNtceDt": "2026-06-01 10:00:00",
        "cntrctCnclsMthdNm": "지방자치단체 입찰",
        "dminsttCd": "7150000",
    }
    result = resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw_data,
        institution_regime=classify_contract_regime(EDU_OFFICE),
        region_code=None,
        region_name=None,
        education_institution=is_education_institution(EDU_OFFICE),
    )
    assert result.contract_regime == "LOCAL"
    assert result.is_blocked is False
    assert result.rule is not None
    assert EDU_PPS_FALLBACK_WARNING in result.warnings

    without_flag = resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw_data,
        institution_regime=classify_contract_regime(EDU_OFFICE),
        region_code=None,
        region_name=None,
    )
    assert without_flag.is_blocked is True
    assert without_flag.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert EDU_PPS_FALLBACK_WARNING not in without_flag.warnings


# --------------------------------------------------------------------------- #
# 2. 바꾸지 않는 경로
# --------------------------------------------------------------------------- #


def test_education_with_sido_keeps_region_rule() -> None:
    assert institution_sido(EDU_WITH_SIDO) == ("47", "경상북도")
    result = _resolve(
        region_code="47",
        region_name="경상북도",
        education_institution=True,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.institution_scope == RULE_SCOPE_REGION
    assert result.rule.region_code == "47"
    assert result.scope_stage == RULE_SCOPE_REGION
    assert EDU_PPS_FALLBACK_WARNING not in result.warnings


def test_education_with_sido_unresolved_service_type_stays_blocked() -> None:
    """세부유형 미확정 차단은 시·도 판정 그대로 유지된다(대체 경로는 미산출 전용)."""
    result = _resolve(
        sucsfbid_mthd_nm=METHOD_GENERIC,
        region_code="28",
        region_name="인천광역시",
        education_institution=True,
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.rule is None
    assert EDU_PPS_FALLBACK_WARNING not in result.warnings


def test_local_education_tech_service_keeps_announcement_lwlt() -> None:
    """기술용역 분기는 그대로 공고 하한율 경로를 쓴다."""
    result = _resolve(
        sucsfbid_mthd_nm="기술용역 적격심사",
        srvce_div_nm="기술용역",
        sucsfbid_lwlt_rate="88.5",
        education_institution=True,
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"
    assert str(result.effective_lwlt_rate) == "88.5"
    assert EDU_PPS_FALLBACK_WARNING not in result.warnings


def test_non_education_local_announcement_is_unchanged() -> None:
    assert classify_contract_regime(LOCAL_GOVERNMENT) == "LOCAL"
    assert is_education_institution(LOCAL_GOVERNMENT) is False
    result = _resolve(education_institution=is_education_institution(LOCAL_GOVERNMENT))
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND


# --------------------------------------------------------------------------- #
# 3. is_education_institution 과 classify_contract_regime 의 판정 일치
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("row", "is_education", "regime"),
    [
        (EDU_OFFICE, True, "LOCAL"),
        (EDU_SCHOOL, True, "LOCAL"),
        (EDU_WITH_SIDO, True, "LOCAL"),
        (
            {"instt_ty_lrgclsfc_nm": "교육행정조직", "instt_ty_midclsfc_nm": "지역교육청"},
            True,
            "LOCAL",
        ),
        (
            {
                "instt_ty_lrgclsfc_nm": "교육행정조직",
                "instt_ty_midclsfc_nm": "시, 도교육청 직속기관",
            },
            True,
            "LOCAL",
        ),
        ({"instt_ty_lrgclsfc_nm": "유치원", "instt_ty_smlclsfc_nm": "공립"}, True, "LOCAL"),
        ({"instt_ty_lrgclsfc_nm": "특수학교", "instt_ty_smlclsfc_nm": "공립"}, True, "LOCAL"),
        ({"instt_ty_lrgclsfc_nm": "중학교", "instt_ty_smlclsfc_nm": "국립"}, False, None),
        ({"instt_ty_lrgclsfc_nm": "초등학교", "instt_ty_smlclsfc_nm": "사립"}, False, None),
        (
            {"instt_ty_lrgclsfc_nm": "교육행정조직", "instt_ty_midclsfc_nm": "하부조직/보조기관"},
            False,
            None,
        ),
        (LOCAL_GOVERNMENT, False, "LOCAL"),
        ({"jrsdctn_div_nm": "국가기관"}, False, "NATIONAL"),
        ({}, False, None),
    ],
)
def test_education_classification_matches_regime(
    row: dict[str, Any], is_education: bool, regime: str | None
) -> None:
    assert is_education_institution(row) is is_education
    assert classify_contract_regime(row) == regime
    if is_education:
        assert classify_contract_regime(row) == "LOCAL"


def test_education_classification_accepts_raw_api_field_names() -> None:
    institution = {
        "jrsdctnDivNm": "교육기관",
        "insttTyCdLrgclsfcNm": "교육행정조직",
        "insttTyCdMidclsfcNm": "지역교육청",
        "rgnCd": "26000",
        "rgnNm": "부산광역시",
    }
    assert is_education_institution(institution) is True
    assert classify_contract_regime(institution) == "LOCAL"
    assert is_education_institution(None) is False
    assert classify_contract_regime(None) is None
