"""낙찰방법 코드 계열 판별과 공고일 대비 별표 시행일 대조 계약 테스트."""

from datetime import date, datetime

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_NEGOTIATION_CONTRACT,
    BLOCK_CODE_NOT_QUALIFICATION_METHOD,
    BLOCK_CODE_RULE_NOT_FOUND,
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    METHOD_SOURCE_ANNOUNCEMENT,
    METHOD_SOURCE_CODE,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
    resolve_method_name,
)

POST_REGIME_DT = "2026-07-10 11:30:45"
PRE_REGIME_DT = "2025-08-27 15:13:28"


def _raw(**overrides):
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": "공고서참조",
        "srvceDivNm": "일반용역",
        "bidNtceDt": POST_REGIME_DT,
    }
    data.update(overrides)
    return data


@pytest.mark.parametrize(
    ("code", "family"),
    [
        ("낙030029", "소액수의견적"),
        ("낙030022", "제한적최저가(낙찰하한율)"),
        ("낙030002", "규격가격동시입찰"),
        ("낙030004", "다수공급자계약"),
        ("낙030031", "카탈로그계약"),
    ],
)
def test_placeholder_with_non_qualification_code_is_not_qualification(code, family):
    result = resolve_evaluation_rule_from_raw_data("Servc", _raw(sucsfbidMthdCd=code))

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_NOT_QUALIFICATION_METHOD
    assert family in (result.block_reason_message or "")
    assert result.method_source == METHOD_SOURCE_CODE


def test_placeholder_with_negotiation_code_uses_negotiation_flow():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        _raw(sucsfbidMthdCd="낙030005", techAbltEvlRt="80", bidPrceEvlRt="20"),
    )

    assert result.block_reason_code == BLOCK_CODE_NEGOTIATION_CONTRACT
    assert result.negotiation_variant == "STANDARD"
    assert result.method_source == METHOD_SOURCE_CODE


def test_placeholder_with_qualification_code_explains_attachment_is_needed():
    result = resolve_evaluation_rule_from_raw_data("Servc", _raw(sucsfbidMthdCd="낙030001"))

    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert "공고서" in (result.block_reason_message or "")
    assert "낙030001" in (result.block_reason_message or "")


def test_placeholder_with_qualification_code_for_tech_service_uses_announcement_rate():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        _raw(sucsfbidMthdCd="낙030001", srvceDivNm="기술용역", sucsfbidLwltRate="79.995"),
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"


def test_unknown_code_keeps_rule_not_found_with_warning():
    result = resolve_evaluation_rule_from_raw_data("Servc", _raw(sucsfbidMthdCd="낙039999"))

    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert any("낙039999" in w for w in result.warnings)


def test_announced_method_name_takes_precedence_over_code():
    name, source, warnings = resolve_method_name(
        "적격심사제-추정가격 2억원 미만인 용역", "낙030029"
    )

    assert name == "적격심사제-추정가격 2억원 미만인 용역"
    assert source == METHOD_SOURCE_ANNOUNCEMENT
    assert warnings == []


def test_announced_non_qualification_family_is_blocked():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        _raw(sucsfbidMthdNm="소액수의견적-소액수의견적(2인 이상 견적 제출)"),
    )

    assert result.block_reason_code == BLOCK_CODE_NOT_QUALIFICATION_METHOD
    assert result.method_source == METHOD_SOURCE_ANNOUNCEMENT


def test_pre_regime_announcement_is_blocked_even_when_rule_matches():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        _raw(
            sucsfbidMthdNm="적격심사제-추정가격 2억원 미만인 용역",
            sucsfbidLwltRate="87.745",
            bidNtceDt=PRE_REGIME_DT,
        ),
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH
    assert result.rule is not None
    assert result.effective_lwlt_rate is None
    assert "2025-08-27" in (result.block_reason_message or "")


def test_pre_regime_tech_service_is_blocked():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        _raw(
            sucsfbidMthdNm="적격심사제-추정가격이 10억원 이상인 기술용역의 평가기준",
            srvceDivNm="기술용역",
            sucsfbidLwltRate="79.995",
            bidNtceDt=PRE_REGIME_DT,
        ),
    )

    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


@pytest.mark.parametrize(
    "bid_ntce_dt",
    ["2026-05-26 00:00:00", date(2026, 5, 26), datetime(2026, 9, 11, 23, 4)],
)
def test_announcement_on_or_after_effective_date_is_calculated(bid_ntce_dt):
    result = resolve_evaluation_rule(
        "Servc",
        "복수예가",
        "적격심사제-추정가격 2억원 미만인 용역",
        sucsfbid_lwlt_rate="87.745",
        bid_ntce_dt=bid_ntce_dt,
    )

    assert result.is_blocked is False


def test_unreadable_announcement_date_warns_without_blocking():
    result = resolve_evaluation_rule(
        "Servc",
        "복수예가",
        "적격심사제-추정가격 2억원 미만인 용역",
        sucsfbid_lwlt_rate="87.745",
        bid_ntce_dt="미상",
    )

    assert result.is_blocked is False
    assert any("공고일(미상)" in w for w in result.warnings)


def test_negotiation_is_not_subject_to_regime_guard():
    result = resolve_evaluation_rule_from_raw_data(
        "Servc",
        _raw(
            sucsfbidMthdNm="협상에의한계약-협상에 의한 낙찰자 결정",
            techAbltEvlRt="80",
            bidPrceEvlRt="20",
            bidNtceDt=PRE_REGIME_DT,
        ),
    )

    assert result.block_reason_code == BLOCK_CODE_NEGOTIATION_CONTRACT
    assert result.negotiation_tech_eval_rate is not None
