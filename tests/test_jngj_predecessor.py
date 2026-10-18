"""통합 지침 이전 전라남도 공고의 전신 기준(구판 지역 규칙) 적용 시험.

정본:
 - docs/analysis/jngj_predecessor_apply_20261017.md (원문 인용·계열 구분 규칙·건수)
 - 원문: 자치법규정보시스템 전라남도 일반용역 적격심사 세부기준,
   전라남도 예규 제1075호, 시행 2023-03-02 (histNo=005) 본문 제7조 ①·별표 4·5 첨부

기대값은 원문이 인쇄한 배점한도·평점산식·통과점수와 그 역산 낙찰하한율이며,
시험 안에서 계수를 역산하지 않는다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.demand_institutions import institution_sido
from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    LOCAL_RULES,
    EvaluationRule,
    resolve_evaluation_rule,
    resolve_score_params,
)

PREDECESSOR_WASTE_ID = "SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4"
PREDECESSOR_LAND_TRANSPORT_ID = "SERVC_LOCAL_JEONNAM_20230302_ATTACH_5_1_4"
GWANGJU_PREDECESSOR_WASTE_ID = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3"
GWANGJU_PREDECESSOR_LAND_TRANSPORT_ID = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5"
JNGJ_WASTE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"
JNGJ_LAND_TRANSPORT_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_05"

# 낙찰방법명은 나라장터 공고 표기를 그대로 쓴다.
WASTE_METHOD = "폐기물처리용역 적격심사 추정가격 고시금액미만"
LAND_TRANSPORT_METHOD = "여객 육상운송용역 적격심사 추정가격 5억원미만"

# 수요기관 기준정보의 rgn_nm 첫 토큰이 통합 전 계열을 정한다(rgn_cd 46000·29000).
JEONNAM_INSTITUTION = {"toplvlInsttNm": None, "rgnNm": "전라남도 순천시"}
GWANGJU_INSTITUTION = {"toplvlInsttNm": None, "rgnNm": "광주광역시 북구"}
MERGED_JEONNAM_INSTITUTION = {
    "toplvlInsttNm": "전남광주통합특별시",
    "rgnNm": "전라남도 여수시",
}

REGIME_CHANGE_DATE = "2026-07-16"


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def _resolve(institution: dict[str, str | None], method: str, announced: str | None, **kwargs):
    sido_code, sido_name = institution_sido(institution)
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        contract_regime="LOCAL",
        bid_ntce_dt=announced,
        region_code=sido_code,
        region_name=sido_name,
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# 1. 계열 구분과 시행일 가르기
# --------------------------------------------------------------------------- #


def test_institution_sido_keeps_pre_merge_lineage() -> None:
    """수요기관 기준정보가 전남·광주 계열을 옛 코드(46·29)로 남긴다."""
    assert institution_sido(JEONNAM_INSTITUTION) == ("46", "전라남도")
    assert institution_sido(GWANGJU_INSTITUTION) == ("29", "광주광역시")
    assert institution_sido(MERGED_JEONNAM_INSTITUTION) == ("46", "전라남도")


@pytest.mark.parametrize(
    ("method", "expected_rule_id"),
    [
        (WASTE_METHOD, PREDECESSOR_WASTE_ID),
        (LAND_TRANSPORT_METHOD, PREDECESSOR_LAND_TRANSPORT_ID),
    ],
)
def test_jeonnam_before_regime_uses_predecessor_rule(method: str, expected_rule_id: str) -> None:
    """시행일 이전 전라남도 공고는 전신 기준(예규 제1075호) 별표로 계산한다."""
    result = _resolve(JEONNAM_INSTITUTION, method, "2026-06-01", estimated_price=400000000)
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.is_blocked is False
    assert result.block_reason_code is None


@pytest.mark.parametrize(
    ("method", "expected_rule_id"),
    [
        (WASTE_METHOD, GWANGJU_PREDECESSOR_WASTE_ID),
        (LAND_TRANSPORT_METHOD, GWANGJU_PREDECESSOR_LAND_TRANSPORT_ID),
    ],
)
def test_gwangju_before_regime_uses_predecessor_rule(method: str, expected_rule_id: str) -> None:
    """광주광역시 계열은 전신 기준(예규 제377호) 별표로 계산한다."""
    result = _resolve(GWANGJU_INSTITUTION, method, "2026-06-01", estimated_price=400000000)
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.is_blocked is False
    assert result.block_reason_code is None


@pytest.mark.parametrize(
    ("method", "expected_rule_id"),
    [
        (WASTE_METHOD, JNGJ_WASTE_ID),
        (LAND_TRANSPORT_METHOD, JNGJ_LAND_TRANSPORT_ID),
    ],
)
def test_regime_start_date_and_after_keep_current_rule(method: str, expected_rule_id: str) -> None:
    """시행일(2026-07-16) 이후 공고는 전남·광주 모두 현행 통합 지침 별표 그대로다."""
    for institution in (JEONNAM_INSTITUTION, GWANGJU_INSTITUTION):
        result = _resolve(institution, method, REGIME_CHANGE_DATE, estimated_price=400000000)
        assert result.rule is not None, institution
        assert result.rule.rule_id == expected_rule_id, institution
        assert result.is_blocked is False, institution


def test_jeonnam_before_predecessor_effective_date_stays_blocked() -> None:
    """전신 기준 시행일(2023-03-02)보다 앞선 전남 공고는 종전처럼 차단한다."""
    result = _resolve(JEONNAM_INSTITUTION, WASTE_METHOD, "2023-01-01", estimated_price=400000000)
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH
    assert result.effective_lwlt_rate is None
    assert result.rule is None or result.rule.superseded_date is None


def test_announcement_without_date_keeps_current_rule() -> None:
    """공고일이 없으면 구판과 가르지 않고 현행 규칙 판정을 유지한다."""
    result = _resolve(JEONNAM_INSTITUTION, WASTE_METHOD, None, estimated_price=400000000)
    assert result.rule is not None
    assert result.rule.rule_id == JNGJ_WASTE_ID


def test_predecessor_rules_declare_supersede_window() -> None:
    """전라남도·광주광역시 구판 규칙이 폐지 시행일을 선언한다."""
    JEONNAM_FACILITY_ID = "SERVC_LOCAL_JEONNAM_20230302_ATTACH_1_1_4"
    jeonnam_predecessors = {
        rule.rule_id: rule
        for rule in LOCAL_RULES
        if rule.rule_id
        in {
            JEONNAM_FACILITY_ID,
            PREDECESSOR_WASTE_ID,
            PREDECESSOR_LAND_TRANSPORT_ID,
        }
    }
    assert set(jeonnam_predecessors) == {
        JEONNAM_FACILITY_ID,
        PREDECESSOR_WASTE_ID,
        PREDECESSOR_LAND_TRANSPORT_ID,
    }
    for rule in jeonnam_predecessors.values():
        assert rule.region_code == "46"
        assert rule.region_name == "전라남도"
        assert rule.effective_date == "2023-03-02"
        assert rule.superseded_date == REGIME_CHANGE_DATE
    gwangju_predecessors = {
        rule.rule_id: rule
        for rule in LOCAL_RULES
        if rule.rule_id
        in {
            GWANGJU_PREDECESSOR_WASTE_ID,
            GWANGJU_PREDECESSOR_LAND_TRANSPORT_ID,
        }
    }
    assert set(gwangju_predecessors) == {
        GWANGJU_PREDECESSOR_WASTE_ID,
        GWANGJU_PREDECESSOR_LAND_TRANSPORT_ID,
    }
    for rule in gwangju_predecessors.values():
        assert rule.region_code == "29"
        assert rule.region_name == "광주광역시"
        assert rule.effective_date == "2022-11-15"
        assert rule.superseded_date == REGIME_CHANGE_DATE
    # 2026-10-18 광역시 본청·소속기관용 경계 규칙은 고시 판본 경계(2025-01-01)와 통합 시행일에서 끝난다.
    metro_windows = {
        f"{GWANGJU_PREDECESSOR_WASTE_ID}_METRO_330": ("2022-11-15", "2025-01-01"),
        f"{GWANGJU_PREDECESSOR_WASTE_ID}_METRO_350": ("2025-01-01", REGIME_CHANGE_DATE),
        f"{GWANGJU_PREDECESSOR_LAND_TRANSPORT_ID}_METRO_330": ("2022-11-15", "2025-01-01"),
        f"{GWANGJU_PREDECESSOR_LAND_TRANSPORT_ID}_METRO_350": ("2025-01-01", REGIME_CHANGE_DATE),
    }
    metro_rules = {rule.rule_id: rule for rule in LOCAL_RULES if rule.rule_id in metro_windows}
    assert set(metro_rules) == set(metro_windows)
    for rule_id, (effective, superseded_on) in metro_windows.items():
        assert metro_rules[rule_id].region_code == "29"
        assert metro_rules[rule_id].effective_date == effective
        assert metro_rules[rule_id].superseded_date == superseded_on
    # 2026-10-18 대전광역시 구판(공고 제2024-2호)은 현행(공고 제2025-9528호) 시행일에서 끝난다.
    daejeon_windows = {
        "SERVC_LOCAL_DAEJEON_20240120_ATTACH_01": ("2024-01-20", "2026-01-01"),
        "SERVC_LOCAL_DAEJEON_20240120_SIMPLE_LABOR": ("2024-01-20", "2026-01-01"),
    }
    daejeon_rules = {rule.rule_id: rule for rule in LOCAL_RULES if rule.rule_id in daejeon_windows}
    assert set(daejeon_rules) == set(daejeon_windows)
    for rule_id, (effective, superseded_on) in daejeon_windows.items():
        assert daejeon_rules[rule_id].region_code == "30"
        assert daejeon_rules[rule_id].effective_date == effective
        assert daejeon_rules[rule_id].superseded_date == superseded_on
    superseded = {rule.rule_id for rule in LOCAL_RULES if rule.superseded_date is not None}
    assert superseded == {
        "SERVC_LOCAL_JEONNAM_20230302_ATTACH_1_1_4",
        PREDECESSOR_WASTE_ID,
        PREDECESSOR_LAND_TRANSPORT_ID,
        GWANGJU_PREDECESSOR_WASTE_ID,
        GWANGJU_PREDECESSOR_LAND_TRANSPORT_ID,
        *metro_windows,
        *daejeon_windows,
    }


# --------------------------------------------------------------------------- #
# 2. 원문 인쇄값 대조 (구간 경계·B·k·기준비율·통과점수·낙찰하한율)
# --------------------------------------------------------------------------- #

# (규칙, 추정가격, 원문 구간, B, k, 통과점수, 구간 낙찰하한율)
SOURCE_BAND_CASES = (
    (
        PREDECESSOR_WASTE_ID,
        "50000000",
        "추정가격 1억원 미만",
        "90",
        "20",
        "95",
        "87.745",
    ),
    (
        PREDECESSOR_WASTE_ID,
        "300000000",
        "5억원 미만 1억원 이상",
        "80",
        "20",
        "95",
        "87.745",
    ),
    (
        PREDECESSOR_WASTE_ID,
        "700000000",
        "10억원 미만 5억원 이상",
        "30",
        "1",
        "95",
        "82.995",
    ),
    (
        PREDECESSOR_WASTE_ID,
        "1500000000",
        "30억원 미만 10억원 이상",
        "30",
        "1",
        "90",
        "77.995",
    ),
    (
        PREDECESSOR_WASTE_ID,
        "3000000000",
        "추정가격 30억원 이상",
        "30",
        "1",
        "85",
        "72.995",
    ),
    (
        PREDECESSOR_LAND_TRANSPORT_ID,
        "300000000",
        "추정가격 5억원 미만",
        "80",
        "2",
        "95",
        "85.495",
    ),
    (
        PREDECESSOR_LAND_TRANSPORT_ID,
        "700000000",
        "10억원 미만 5억원 이상",
        "60",
        "2",
        "95",
        "85.495",
    ),
    (
        PREDECESSOR_LAND_TRANSPORT_ID,
        "1500000000",
        "30억원 미만 10억원 이상",
        "60",
        "2",
        "90",
        "82.995",
    ),
    (
        PREDECESSOR_LAND_TRANSPORT_ID,
        "3000000000",
        "추정가격 30억원 이상",
        "60",
        "2",
        "85",
        "80.495",
    ),
)


@pytest.mark.parametrize(
    ("rule_id", "price", "label", "b_value", "k_value", "threshold", "lwlt_rate"),
    SOURCE_BAND_CASES,
)
def test_predecessor_bands_match_source(
    rule_id: str,
    price: str,
    label: str,
    b_value: str,
    k_value: str,
    threshold: str,
    lwlt_rate: str,
) -> None:
    """구간마다 원문 배점한도·평점계수·기준비율·통과점수와 역산 낙찰하한율이 맞는다."""
    rule = _rule(rule_id)
    band = next((band for band in rule.price_bands or () if band.label == label), None)
    assert band is not None, f"구간 {label} 이 없습니다."
    result = resolve_score_params(rule, Decimal(price), None, None)
    assert result.price_band_label == label, rule_id
    assert result.max_price_score == Decimal(b_value), rule_id
    assert result.multiplier == Decimal(k_value), rule_id
    assert result.pass_threshold == Decimal(threshold), rule_id
    assert band.lwlt_rate == Decimal(lwlt_rate), rule_id


@pytest.mark.parametrize(
    ("method", "price", "expected_lwlt"),
    [
        (WASTE_METHOD, "500000000", "82.995"),
        (WASTE_METHOD, "1500000000", "77.995"),
        (LAND_TRANSPORT_METHOD, "300000000", "85.495"),
        (LAND_TRANSPORT_METHOD, "3000000000", "80.495"),
    ],
)
def test_predecessor_band_lwlt_preferred_without_notice_rate(
    method: str, price: str, expected_lwlt: str
) -> None:
    """공고 낙찰하한율이 없으면 구판 구간 하한율을 쓴다."""
    result = _resolve(JEONNAM_INSTITUTION, method, "2026-06-01", estimated_price=Decimal(price))
    assert result.rule is not None
    assert result.rule.rule_id in {PREDECESSOR_WASTE_ID, PREDECESSOR_LAND_TRANSPORT_ID}
    assert result.effective_lwlt_rate == Decimal(expected_lwlt)
    assert result.rate_source == "RULE_DEFAULT"


def test_predecessor_price_score_differs_from_current_regime() -> None:
    """같은 추정가격에서 구판과 현행의 배점한도가 달라 값이 바뀐다(가격식 차이 확인).

    육상운송 추정가격 3억원: 구판 별표 5 는 5억원 미만 한 구간이라 B=80, 현행 별표 5 는
    2억원 미만만 B=80 이라 B=70 이다. 투찰률 88.25% 에서 75점과 72.5점으로 갈린다.
    """
    predecessor = _rule(PREDECESSOR_LAND_TRANSPORT_ID)
    current = _rule(JNGJ_LAND_TRANSPORT_ID)
    before = resolve_score_params(predecessor, Decimal("300000000"), None, None)
    after = resolve_score_params(current, Decimal("300000000"), None, None)
    assert before.max_price_score == Decimal("80")
    assert before.multiplier == Decimal("2")
    assert after.max_price_score == Decimal("70")
    assert after.multiplier == Decimal("2")
