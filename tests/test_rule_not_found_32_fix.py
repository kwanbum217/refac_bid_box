"""RULE_NOT_FOUND 32건 해소 회귀 시험.

정본:
 - docs/analysis/rule_not_found_32_source_20261106.md 2.2~2.4, 3.1~3.3, 4.1
 - docs/analysis/rule_not_found_32_fix_regression_20261106.md

묶음별 대표 공고로 (a) 한국지역난방공사 지사 코드가 현행 기타용역 규칙으로,
(b) 2025-12 공고가 직전판 규칙으로, (c) SW 비대상 두 띠가 새 고시금액 이상 규칙으로,
(d) 여객 5억원 이상이 제2026-390호 규칙으로 해석되는지, (e) 260판 공고나 목록 밖
기관 코드에는 새 규칙이 적용되지 않는지 단언합니다.
"""

from __future__ import annotations

from decimal import Decimal

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_NOT_FOUND,
    INSTITUTION_RULES,
    PASSENGER_NOTICE_ABOVE_RULES,
    POST_20260526_RULES,
    POST_20260727_RULES,
    PREDECESSOR_INSTITUTION_RULES,
    match_rule_by_mthd_nm,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

CURRENT_OTHER_ID = "SERVC_INST_KDHC_20260101_OTHER"
PREDECESSOR_OTHER_ID = "SERVC_INST_KDHC_20230719_OTHER"
SW_HIGH_ID = "SERVC_QUAL_POST_20260526_ATTACH_21"
SW_LOW_ID = "SERVC_QUAL_POST_20260526_ATTACH_05"
PASSENGER_390_ID = "SERVC_QUAL_POST_20260727_ATTACH_03_HIGH"

KDHC_OTHER_OVER = (
    "적격심사제-기타용역(사용자기계실 유지관리용역 등) 적격심사 추정가격 고시금액 이상"
)
KDHC_OTHER_UNDER = (
    "적격심사제-기타용역(사용자기계실 유지관리용역 등) 적격심사 추정가격 고시금액 미만"
)
SW_UNDER_500_ABOVE_NOTICE = (
    "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 "
    "추정가격 5억원 미만-추정가격 고시금액이상"
)
SW_ABOVE_500 = (
    "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 이상"
)
SW_BELOW_NOTICE = (
    "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 고시금액미만"
)
PASSENGER_ABOVE_500 = "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원이상"


def _raw(
    bid_ntce_dt: str,
    institution_code: str,
    institution_name: str,
    method_name: str,
    price: str,
    **extra: str,
) -> dict[str, str]:
    data = {
        "dminsttCd": institution_code,
        "dminsttNm": institution_name,
        "ntceInsttCd": institution_code,
        "ntceInsttNm": institution_name,
        "bidNtceDt": bid_ntce_dt,
        "sucsfbidMthdNm": method_name,
        "presmptPrce": price,
        "bidNtceNm": extra.pop("bidNtceNm", institution_name),
    }
    data.update(extra)
    return data


def _resolve(raw: dict[str, str], price: str):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        estimated_price=Decimal(price),
    )


def _rule(rule_id: str):
    return next(
        rule
        for rule in (*INSTITUTION_RULES, *PREDECESSOR_INSTITUTION_RULES)
        if rule.rule_id == rule_id
    )


def test_kdhc_branch_code_uses_current_other_rule() -> None:
    raw = _raw(
        "2026-06-19 15:03:25",
        "D325102",
        "한국지역난방공사 대구지사",
        KDHC_OTHER_OVER,
        "371311000",
    )
    result = _resolve(raw, "371311000")

    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_OTHER_ID
    assert result.effective_lwlt_rate == Decimal("80.495")

    params = resolve_score_params(result.rule, Decimal("371311000"), None, None)
    assert params.max_price_score == Decimal("50")
    assert params.multiplier == Decimal("2")
    assert params.pass_threshold == Decimal("85")
    assert result.rule.base_rate == Decimal("0.88")


def test_kdhc_branch_code_uses_current_other_rule_below_notice() -> None:
    raw = _raw(
        "2026-06-26 15:43:22",
        "D325150",
        "한국지역난방공사 강남지사",
        KDHC_OTHER_UNDER,
        "16604141",
    )
    result = _resolve(raw, "16604141")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == CURRENT_OTHER_ID
    assert result.effective_lwlt_rate == Decimal("84.995")

    params = resolve_score_params(result.rule, Decimal("16604141"), None, None)
    assert params.max_price_score == Decimal("80")
    assert params.multiplier == Decimal("5")
    assert params.pass_threshold == Decimal("85")


def test_kdhc_2025_12_announcement_uses_predecessor_rule() -> None:
    raw = _raw(
        "2025-12-09 17:49:49",
        "D325107",
        "한국지역난방공사 김해사업소",
        KDHC_OTHER_UNDER,
        "17161000",
    )
    result = _resolve(raw, "17161000")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PREDECESSOR_OTHER_ID
    assert result.rule.effective_date == "2023-07-19"
    assert result.rule.superseded_date == "2026-01-01"
    assert result.effective_lwlt_rate == Decimal("84.995")

    params = resolve_score_params(result.rule, Decimal("17161000"), None, None)
    assert params.max_price_score == Decimal("80")
    assert params.multiplier == Decimal("5")
    assert params.pass_threshold == Decimal("85")
    assert result.rule.base_rate == Decimal("0.88")


def test_sw_non_sme_under_500m_above_notice_uses_high_rule() -> None:
    raw = _raw(
        "2026-06-05 10:20:15",
        "Z006079",
        "군인공제회C_C",
        SW_UNDER_500_ABOVE_NOTICE,
        "373968000",
    )
    result = _resolve(raw, "373968000")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SW_HIGH_ID
    assert result.effective_lwlt_rate == Decimal("82.495")

    params = resolve_score_params(result.rule, Decimal("373968000"), None, None)
    assert params.max_price_score == Decimal("70")
    assert params.multiplier == Decimal("2")
    assert params.pass_threshold == Decimal("85")
    assert result.rule.base_rate == Decimal("0.90")


def test_sw_non_sme_above_500m_uses_high_rule() -> None:
    raw = _raw(
        "2026-07-24 09:19:13",
        "1723325",
        "과학기술정보통신부 우정사업본부 우정정보관리원",
        SW_ABOVE_500,
        "12413224545",
    )
    result = _resolve(raw, "12413224545")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SW_HIGH_ID
    assert result.effective_lwlt_rate == Decimal("82.495")

    params = resolve_score_params(result.rule, Decimal("12413224545"), None, None)
    assert params.max_price_score == Decimal("60")
    assert params.multiplier == Decimal("2")
    assert params.pass_threshold == Decimal("85")


def test_sw_non_sme_below_notice_rule_is_unchanged() -> None:
    raw = _raw(
        "2026-06-05 10:20:15",
        "7007971",
        "인천대학교",
        SW_BELOW_NOTICE,
        "200000000",
    )
    result = _resolve(raw, "200000000")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SW_LOW_ID
    assert result.effective_lwlt_rate == Decimal("86.245")

    params = resolve_score_params(
        result.rule,
        Decimal("200000000"),
        "2026-06-05",
        SW_BELOW_NOTICE,
    )
    assert params.max_price_score == Decimal("70")
    assert params.multiplier == Decimal("4")
    assert params.pass_threshold == Decimal("85")


def test_passenger_above_500m_uses_2026_390_rule() -> None:
    raw = _raw(
        "2026-10-01 10:54:17",
        "1482021",
        "기후에너지환경부 국립환경과학원",
        PASSENGER_ABOVE_500,
        "3927814909",
    )
    result = _resolve(raw, "3927814909")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PASSENGER_390_ID
    assert result.rule.effective_date == "2026-07-27"
    assert result.effective_lwlt_rate == Decimal("89.995")

    params = resolve_score_params(result.rule, Decimal("3927814909"), None, None)
    assert params.max_price_score == Decimal("60")
    assert params.multiplier == Decimal("4")
    assert params.pass_threshold == Decimal("88")
    assert result.rule.base_rate == Decimal("0.93")


def test_passenger_above_500m_is_not_added_to_2026_260_rule() -> None:
    assert match_rule_by_mthd_nm(PASSENGER_ABOVE_500, rules=POST_20260526_RULES) is None

    raw = _raw(
        "2026-06-05 10:20:15",
        "7007971",
        "인천대학교",
        PASSENGER_ABOVE_500,
        "600000000",
    )
    result = _resolve(raw, "600000000")

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


def test_kdhc_rule_does_not_apply_to_unlisted_institution_code() -> None:
    raw = _raw(
        "2026-06-19 15:03:25",
        "D325199",
        "한국지역난방공사 가상지사",
        KDHC_OTHER_OVER,
        "300000000",
    )
    result = _resolve(raw, "300000000")

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert result.rule is None


def test_new_passenger_pattern_is_scoped_to_2026_390_rule() -> None:
    high_patterns = set(PASSENGER_NOTICE_ABOVE_RULES[0].patterns)
    assert "여객 육상운송용역 적격심사 추정가격 5억원 이상" in high_patterns
    assert high_patterns.isdisjoint(POST_20260526_RULES[2].patterns)
    assert high_patterns.isdisjoint(POST_20260727_RULES[2].patterns)

    rule = _rule(CURRENT_OTHER_ID)
    assert rule.institution_code == "B550373"
    assert rule.patterns == ("기타용역", "기타")
