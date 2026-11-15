"""정량평가 산식 판정 차단 용역 공고 보완 시험.

- 조달분류 표지에 학술연구(ACADEMIC)·임대(LEASE)를 더하고, 지역에 해당 별표가 없으면
  기존 GENERAL 폴백으로 계산한다.
- 국립 학교는 국가기관이므로 국가계약(조달청) 기준으로 판정한다.

DB·.env 에 연결하지 않습니다.
"""

from __future__ import annotations

from typing import Any

from src.app.services.demand_institutions import (
    classify_contract_regime,
    is_education_institution,
    is_national_school,
)
from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    JEONNAM_PPS_FALLBACK_WARNING,
    RULE_SCOPE_ALL,
    RULE_SCOPE_REGION,
    resolve_evaluation_rule_from_raw_data,
    resolve_local_service_type,
)

METHOD_BAND_2E = "적격심사제-추정가격 2억미만 1억이상"
METHOD_BAND_2E_NAME = "적격심사제-추정가격 2억원 미만인 용역"
METHOD_REPAIR_UNDER = "적격심사제-수리ㆍ점검용역 적격심사 고시금액 미만"
METHOD_PASSENGER_UNDER = "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만"

ACADEMIC_CLASS = ("연구조사서비스", "학술연구서비스", "기타연구조사서비스")
LEASE_CLASS = ("임대*위탁 및 수리서비스", "임대", "사무용기기임대서비스")


def _raw(
    *,
    method: str,
    announced: str,
    institution_name: str,
    classes: tuple[str, str, str] = ("", "", ""),
    bid_name: str = "용역",
    estimated_price: int = 150_000_000,
) -> dict[str, Any]:
    return {
        "bidNtceNo": "R26BK00000000",
        "bidNtceNm": bid_name,
        "bidNtceDt": announced,
        "sucsfbidMthdNm": method,
        "dminsttNm": institution_name,
        "pubPrcrmntLrgClsfcNm": classes[0],
        "pubPrcrmntMidClsfcNm": classes[1],
        "pubPrcrmntClsfcNm": classes[2],
        "presmptPrce": estimated_price,
    }


def _resolve(
    raw_data: dict[str, Any],
    *,
    region_code: str | None,
    region_name: str | None,
    institution_regime: str = "LOCAL",
    education_institution: bool = False,
):
    return resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw_data,
        institution_regime=institution_regime,
        region_code=region_code,
        region_name=region_name,
        education_institution=education_institution,
        estimated_price=raw_data.get("presmptPrce"),
    )


# --------------------------------------------------------------------------- #
# (1) 조달분류 세부유형 표지 보완
# --------------------------------------------------------------------------- #


def test_academic_classification_marker_resolves_academic() -> None:
    service_type, basis, reason = resolve_local_service_type(
        _raw(
            method=METHOD_BAND_2E,
            announced="2025-11-19",
            institution_name="x",
            classes=ACADEMIC_CLASS,
        ),
        METHOD_BAND_2E,
    )
    assert (service_type, basis, reason) == ("ACADEMIC", "PROCUREMENT_CLASS", None)


def test_lease_classification_marker_resolves_lease() -> None:
    service_type, basis, reason = resolve_local_service_type(
        _raw(
            method=METHOD_BAND_2E_NAME,
            announced="2025-12-08",
            institution_name="x",
            classes=LEASE_CLASS,
        ),
        METHOD_BAND_2E_NAME,
    )
    assert (service_type, basis, reason) == ("LEASE", "PROCUREMENT_CLASS", None)


def test_jeonbuk_academic_falls_back_to_general() -> None:
    result = _resolve(
        _raw(
            method=METHOD_BAND_2E,
            announced="2025-11-19",
            institution_name="전북특별자치도 완주군",
            classes=ACADEMIC_CLASS,
        ),
        region_code="52",
        region_name="전북특별자치도",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_JEONBUK_20240118_ATTACH_01"
    assert result.scope_stage == RULE_SCOPE_REGION
    assert "별표 유형 ACADEMIC 이(가) 없어 일반 별표를 적용했습니다." in result.warnings


def test_ulsan_lease_falls_back_to_general() -> None:
    result = _resolve(
        _raw(
            method=METHOD_BAND_2E_NAME,
            announced="2025-12-08",
            institution_name="울산광역시 울주군",
            classes=LEASE_CLASS,
        ),
        region_code="31",
        region_name="울산광역시",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_ULSAN_20220810_ATTACH_01"
    assert result.scope_stage == RULE_SCOPE_REGION
    assert "별표 유형 LEASE 이(가) 없어 일반 별표를 적용했습니다." in result.warnings


def test_daejeon_academic_falls_back_to_general() -> None:
    result = _resolve(
        _raw(
            method=METHOD_BAND_2E,
            announced="2026-03-18",
            institution_name="대전광역시",
            classes=ACADEMIC_CLASS,
        ),
        region_code="30",
        region_name="대전광역시",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01"
    assert result.scope_stage == RULE_SCOPE_REGION


def test_academic_class_keeps_existing_mois_route() -> None:
    """행안부 학술연구 띠 규칙이 적용되던 표기는 종전 적용 규칙을 유지한다."""
    result = _resolve(
        _raw(
            method="적격심사제-추정가격 1억미만",
            announced="2026-01-15",
            institution_name="전북특별자치도 완주군",
            classes=ACADEMIC_CLASS,
        ),
        region_code="52",
        region_name="전북특별자치도",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_LOCAL_MOIS_ACADEMIC_")


# --------------------------------------------------------------------------- #
# (2) 국립 학교는 국가계약(조달청) 기준으로 판정한다
# --------------------------------------------------------------------------- #


def test_national_school_is_not_education_institution() -> None:
    institution = {
        "instt_ty_lrgclsfc_nm": "초등학교",
        "instt_ty_midclsfc_nm": "초등학교(본교)",
        "instt_ty_smlclsfc_nm": "국립",
        "jrsdctn_div_nm": "지방자치단체",
    }
    assert is_national_school(institution) is True
    assert is_education_institution(institution) is False
    assert classify_contract_regime(institution) == "NATIONAL"


def test_public_school_keeps_local_regime() -> None:
    institution = {
        "instt_ty_lrgclsfc_nm": "초등학교",
        "instt_ty_smlclsfc_nm": "공립",
        "jrsdctn_div_nm": "지방자치단체",
    }
    assert is_national_school(institution) is False
    assert classify_contract_regime(institution) == "LOCAL"


def test_national_school_without_jurisdiction_stays_unknown() -> None:
    institution = {"instt_ty_lrgclsfc_nm": "중학교", "instt_ty_smlclsfc_nm": "국립"}
    assert is_national_school(institution) is True
    assert classify_contract_regime(institution) is None


def test_national_school_passenger_uses_pps_rule() -> None:
    result = _resolve(
        _raw(
            method=METHOD_PASSENGER_UNDER,
            announced="2026-01-28",
            institution_name=("대구광역시교육청 대구광역시달성교육지원청 대구테크노초등학교"),
            classes=("여행*숙박*음식*운송 및 보험서비스", "운송서비스", "도로여객운송서비스"),
            estimated_price=206_866_400,
        ),
        region_code=None,
        region_name=None,
        institution_regime="NATIONAL",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_PRE_20250901_ATTACH_03"
    assert result.scope_stage == RULE_SCOPE_ALL


# --------------------------------------------------------------------------- #
# (3) 대상 밖 지역·차단 코드는 그대로 둔다
# --------------------------------------------------------------------------- #


def test_other_region_keeps_local_rule_not_found() -> None:
    result = _resolve(
        _raw(
            method=METHOD_REPAIR_UNDER,
            announced="2026-08-01",
            institution_name="대구광역시 중구",
        ),
        region_code="27",
        region_name="대구광역시",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is None
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings
