"""기술용역 적격심사의 공고별 하한율 판별 계약 테스트."""

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_MANUAL_EVALUATION,
    BLOCK_CODE_NEGOTIATION_CONTRACT,
    BLOCK_CODE_RULE_NOT_FOUND,
    BLOCK_CODE_TECH_SERVICE_MISSING_LWLT,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)


def test_tech_qualification_uses_announcement_lwlt_rate():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "srvceDivNm": "기술용역",
            "sucsfbidMthdNm": "적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준",
            "sucsfbidLwltRate": "79.9950",
        },
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"
    assert result.rule.table_name == "기술용역 적격심사"
    assert result.rule.service_type == "TECH"
    assert result.effective_lwlt_rate == Decimal("79.9950")
    assert result.rate_source == "ANNOUNCEMENT"
    assert result.rate_source != "RULE_DEFAULT"


def test_tech_service_division_matches_without_tech_service_in_method_name():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "srvceDivNm": "기술용역",
            "sucsfbidMthdNm": "적격심사제-추정가격이 10억원미만 5억원이상인 용역",
            "sucsfbidLwltRate": "85.4950",
        },
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"


@pytest.mark.parametrize("lwlt_rate", [None, "", "0", "-1", "not-a-number"])
def test_tech_qualification_without_positive_lwlt_is_blocked(lwlt_rate):
    result = resolve_evaluation_rule(
        "Servc",
        "복수예가",
        "적격심사제-추정가격이 10억원 이상인 기술용역 평가기준",
        sucsfbid_lwlt_rate=lwlt_rate,
        srvce_div_nm="기술용역",
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_TECH_SERVICE_MISSING_LWLT
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"
    assert result.rate_source != "RULE_DEFAULT"


def test_manual_evaluation_precedes_tech_service_rule():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "srvceDivNm": "기술용역",
            "sucsfbidMthdNm": "적격심사제-관리규정외 수기심사",
            "sucsfbidLwltRate": "88.7450",
        },
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_MANUAL_EVALUATION
    assert result.rule is None


def test_negotiation_contract_precedes_tech_service_rule():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "srvceDivNm": "기술용역",
            "sucsfbidMthdNm": "협상에의한계약-협상에 의한 낙찰자 결정(엔지니어링)",
            "sucsfbidLwltRate": "88.7450",
        },
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_NEGOTIATION_CONTRACT
    assert result.rule is None


def test_existing_general_service_annex_rule_is_unchanged():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "srvceDivNm": "일반용역",
            "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 미만",
            "sucsfbidLwltRate": "89.995",
        },
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_POST_20260526_ATTACH_01"


def test_general_service_does_not_enter_tech_service_branch():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        {
            "srvceDivNm": "일반용역",
            "sucsfbidMthdNm": "적격심사제-추정가격이 10억원 이상인 P.Q대상 기술용역의 평가기준",
            "sucsfbidLwltRate": "79.9950",
        },
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
