"""통합 지침 이전 광주광역시 공고의 전신 기준(구판 지역 규칙) 적용 시험.

정본:
 - docs/analysis/gwangju_predecessor_apply_20261017.md
 - 원문: 자치법규정보시스템 광주광역시 일반용역 적격심사 세부 기준,
   광주광역시 예규 제377호, 시행 2022-11-15 (alrNo=29000068001145, histNo=007)

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

PREDECESSOR_WASTE_ID = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_3"
PREDECESSOR_LAND_TRANSPORT_ID = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_5"
JNGJ_WASTE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"
JNGJ_LAND_TRANSPORT_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_05"

WASTE_METHOD = "폐기물처리용역 적격심사 추정가격 고시금액미만"
LAND_TRANSPORT_METHOD = "여객 육상운송용역 적격심사 추정가격 5억원미만"

GWANGJU_INSTITUTION = {"toplvlInsttNm": None, "rgnNm": "광주광역시 북구"}
JEONNAM_INSTITUTION = {"toplvlInsttNm": None, "rgnNm": "전라남도 순천시"}

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


def test_institution_sido_keeps_gwangju_lineage() -> None:
    assert institution_sido(GWANGJU_INSTITUTION) == ("29", "광주광역시")


@pytest.mark.parametrize(
    ("method", "expected_rule_id"),
    [
        (WASTE_METHOD, PREDECESSOR_WASTE_ID),
        (LAND_TRANSPORT_METHOD, PREDECESSOR_LAND_TRANSPORT_ID),
    ],
)
def test_gwangju_before_regime_uses_predecessor_rule(method: str, expected_rule_id: str) -> None:
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
    result = _resolve(GWANGJU_INSTITUTION, method, REGIME_CHANGE_DATE, estimated_price=400000000)
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id
    assert result.is_blocked is False


def test_jeonnam_before_regime_uses_jeonnam_predecessor() -> None:
    result = _resolve(JEONNAM_INSTITUTION, WASTE_METHOD, "2026-06-01", estimated_price=400000000)
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_JEONNAM_20230302_ATTACH_4_1_4"


def test_gwangju_before_effective_date_stays_blocked() -> None:
    result = _resolve(GWANGJU_INSTITUTION, WASTE_METHOD, "2022-10-01", estimated_price=400000000)
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_announcement_without_date_keeps_current_rule() -> None:
    result = _resolve(GWANGJU_INSTITUTION, WASTE_METHOD, None, estimated_price=400000000)
    assert result.rule is not None
    assert result.rule.rule_id == JNGJ_WASTE_ID


def test_predecessor_rules_declare_supersede_window() -> None:
    predecessors = {
        rule.rule_id: rule
        for rule in LOCAL_RULES
        if rule.rule_id in {PREDECESSOR_WASTE_ID, PREDECESSOR_LAND_TRANSPORT_ID}
    }
    assert set(predecessors) == {PREDECESSOR_WASTE_ID, PREDECESSOR_LAND_TRANSPORT_ID}
    for rule in predecessors.values():
        assert rule.region_code == "29"
        assert rule.region_name == "광주광역시"
        assert rule.effective_date == "2022-11-15"
        assert rule.superseded_date == REGIME_CHANGE_DATE


SOURCE_BAND_CASES = (
    (PREDECESSOR_WASTE_ID, "50000000", "추정가격 1억원 미만", "90", "20", "95", "87.745"),
    (
        PREDECESSOR_WASTE_ID,
        "300000000",
        "지역제한 금액 미만 1억원 이상",
        "80",
        "20",
        "95",
        "87.745",
    ),
    (PREDECESSOR_WASTE_ID, "700000000", "지역제한 금액 이상", "30", "1", "95", "82.995"),
    (PREDECESSOR_LAND_TRANSPORT_ID, "300000000", "지역제한 금액 미만", "70", "2", "95", "85.495"),
    (PREDECESSOR_LAND_TRANSPORT_ID, "700000000", "지역제한 금액 이상", "60", "2", "95", "85.495"),
)


@pytest.mark.parametrize(
    ("rule_id", "price", "label", "b_value", "k_value", "threshold", "lwlt_rate"),
    SOURCE_BAND_CASES,
)
def test_predecessor_bands_match_source(
    rule_id, price, label, b_value, k_value, threshold, lwlt_rate
):
    rule = _rule(rule_id)
    band = next((b for b in rule.price_bands or () if b.label == label), None)
    assert band is not None, f"구간 {label} 이 없습니다."
    result = resolve_score_params(rule, Decimal(price), None, None)
    assert result.price_band_label == label, rule_id
    assert result.max_price_score == Decimal(b_value), rule_id
    assert result.multiplier == Decimal(k_value), rule_id
    assert result.pass_threshold == Decimal(threshold), rule_id
    assert band.lwlt_rate == Decimal(lwlt_rate), rule_id
