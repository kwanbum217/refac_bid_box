"""지방공기업·특수법인 공고의 조달청 기본 규칙 대체 경로 시험.

정본: `.orca/task_local_entity_pps_20261106/capsule.yaml`
- 지방공사·지방공단(지방공기업법상 법인)과 대한적십자사 등 특수법인은 지방계약법
  제2조의 "지방자치단체"가 아니어서 시·도 세부기준 적용 대상이 아니다.
- 시·도 매핑이 없어 LOCAL_RULE_NOT_FOUND 가 된 공고만 공고가 인용한 조달청 기본 규칙으로
  풀고, 시·도 매핑이 있으면 종전 판정을 유지한다.
- 교육기관 제외와 전남 준용 판정은 바꾸지 않는다.
- 기관 유형 필드를 우선하고, 필드가 비어 있을 때만 이름 표기를 보조로 쓴다.

DB·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.app.services.demand_institutions import is_sido_rule_excluded
from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    EDU_PPS_FALLBACK_WARNING,
    RULE_SCOPE_ALL,
    RULE_SCOPE_REGION,
    SIDO_RULE_EXCLUDED_PPS_WARNING,
    resolve_evaluation_rule_from_raw_data,
)

METHOD_FACILITY = "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만"
METHOD_FREIGHT = "적격심사제-화물 육상운송용역 적격심사 추정가격 고시금액미만"
METHOD_SIMPLE_LABOR = "적격심사제-단순노무 용역"
BID_DATE = "2025-12-04"

# 실제 20건 목록과 같은 구성입니다. 기관 유형 필드는 raw_data 에 실리지 않으므로
# 수요기관명 표기로 보조 판정합니다.
LOCAL_DISTRICT_CORPORATION: dict[str, Any] = {
    "dminsttNm": "서울특별시서대문구도시관리공단",
    "sucsfbidMthdNm": METHOD_FACILITY,
    "bidNtceDt": BID_DATE,
}
RED_CROSS_BLOOD_CENTER: dict[str, Any] = {
    "dminsttNm": "대한적십자사강원도혈액원",
    "sucsfbidMthdNm": METHOD_FREIGHT,
    "bidNtceDt": "2026-04-02",
}
LOCAL_GOVERNMENT: dict[str, Any] = {
    "dminsttNm": "서울특별시 종로구",
    "sucsfbidMthdNm": METHOD_SIMPLE_LABOR,
    "bidNtceDt": BID_DATE,
}
EDUCATION_OFFICE: dict[str, Any] = {
    "dminsttNm": "부산광역시교육청",
    "sucsfbidMthdNm": METHOD_FACILITY,
    "bidNtceDt": BID_DATE,
}


def _resolve(
    raw: dict[str, Any],
    *,
    regime: str | None = "LOCAL",
    region_code: str | None = None,
    region_name: str | None = None,
    education: bool = False,
):
    return resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw,
        institution_regime=regime,
        region_code=region_code,
        region_name=region_name,
        estimated_price="100000000",
        education_institution=education,
    )


def _pps_reference(raw: dict[str, Any]):
    """같은 공고를 조달청 기본 경로(비 LOCAL)로 판별한 기준 결과입니다."""
    return _resolve(raw, regime=None)


def test_local_district_corporation_uses_pps_rule() -> None:
    reference = _pps_reference(LOCAL_DISTRICT_CORPORATION)
    assert reference.is_blocked is False
    assert reference.rule is not None

    result = _resolve(LOCAL_DISTRICT_CORPORATION)

    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == reference.rule.rule_id
    assert result.rule.institution_scope == RULE_SCOPE_ALL
    assert result.scope_stage == RULE_SCOPE_ALL
    assert SIDO_RULE_EXCLUDED_PPS_WARNING in result.warnings


def test_red_cross_blood_center_uses_pps_rule() -> None:
    reference = _pps_reference(RED_CROSS_BLOOD_CENTER)
    assert reference.is_blocked is False
    assert reference.rule is not None

    result = _resolve(RED_CROSS_BLOOD_CENTER)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == reference.rule.rule_id
    assert result.scope_stage == RULE_SCOPE_ALL
    assert SIDO_RULE_EXCLUDED_PPS_WARNING in result.warnings


def test_local_government_keeps_sido_rule() -> None:
    result = _resolve(
        LOCAL_GOVERNMENT,
        region_code="11",
        region_name="서울특별시",
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR"
    assert result.scope_stage == RULE_SCOPE_REGION
    assert SIDO_RULE_EXCLUDED_PPS_WARNING not in result.warnings


def test_education_office_keeps_existing_judgment() -> None:
    reference = _pps_reference(EDUCATION_OFFICE)

    result = _resolve(EDUCATION_OFFICE, education=True)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == reference.rule.rule_id
    assert EDU_PPS_FALLBACK_WARNING in result.warnings
    assert SIDO_RULE_EXCLUDED_PPS_WARNING not in result.warnings


def test_local_public_enterprise_with_sido_keeps_existing_route() -> None:
    result = _resolve(
        {
            "dminsttNm": "서울특별시 강북구도시관리공단",
            "sucsfbidMthdNm": METHOD_SIMPLE_LABOR,
            "bidNtceDt": BID_DATE,
        },
        region_code="11",
        region_name="서울특별시",
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR"
    assert result.scope_stage == RULE_SCOPE_REGION
    assert SIDO_RULE_EXCLUDED_PPS_WARNING not in result.warnings


def test_institution_type_field_takes_priority_over_name() -> None:
    raw = {**LOCAL_DISTRICT_CORPORATION, "jrsdctnDivNm": "기타공공기관"}

    result = _resolve(raw)

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert SIDO_RULE_EXCLUDED_PPS_WARNING not in result.warnings


@pytest.mark.parametrize(
    ("institution", "expected"),
    [
        ({"jrsdctn_div_nm": "지방공기업"}, True),
        (
            {"jrsdctn_div_nm": "지방공기업", "dminstt_nm": "서울특별시서대문구도시관리공단"},
            True,
        ),
        ({"jrsdctn_div_nm": "기타기관"}, True),
        ({"jrsdctn_div_nm": "기타공공기관", "dminstt_nm": "한국산업단지공단"}, False),
        ({"jrsdctn_div_nm": "지방자치단체", "dminstt_nm": "서울특별시 종로구"}, False),
        ({"dminstt_nm": "대한적십자사강원도혈액원"}, True),
        ({"dminstt_nm": "전남개발공사"}, True),
        ({"dminstt_nm": "서울특별시서대문구도시관리공단"}, True),
        ({"dminstt_nm": "서울특별시 종로구"}, False),
        (
            {
                "instt_ty_lrgclsfc_nm": "교육행정조직",
                "instt_ty_midclsfc_nm": "지역교육청",
                "dminstt_nm": "부산광역시교육청",
            },
            False,
        ),
        (None, False),
    ],
)
def test_sido_rule_exclusion_classification(institution, expected) -> None:
    assert is_sido_rule_excluded(institution) is expected
