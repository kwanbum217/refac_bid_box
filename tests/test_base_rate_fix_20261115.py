"""기준비율 정정(2026-11-15 결정) 계약 테스트.

환경부고시 건설폐기물 규칙 6종의 기준비율 88/100 과, 공고가 행안부 예규
「지방자치단체 입찰시 낙찰자 결정기준」을 명시한 기술용역 공고의 기준비율 88/100 을
고정합니다. 조달청·기관 자체 기준을 명시한 공고와 구판 기술용역 규칙은 종전 값을
유지하는지도 함께 봅니다.

2026-11-18 정정: 행안부 지목 기술용역은 결과 객체의 base_rate 뿐 아니라 실제 계산
경로가 읽는 규칙 자체(rule.base_rate, rule.price_bands)가 예규 값이어야 합니다.
평가 경로는 resolve_score_params 가 rule.price_bands 에서 고른 base_rate 를,
예측 경로는 rule.base_rate 를 읽으므로 두 경로를 모두 단언합니다.
"""

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    MOE_CDW_RULES,
    MOIS_BIDDER_DECISION_STANDARD_MARKER,
    MOIS_TECH_BASE_RATE_WARNING,
    MOIS_TECH_LOCAL_ANNEX_01,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

MOIS_APP_STD = "지방자치단체 입찰시 낙찰자 결정기준"
PPS_APP_STD = "조달청 기술용역 적격심사 세부기준"
INSTITUTION_APP_STD = "한국도로공사 기술용역 적격심사 세부기준"
METHOD_NAME = "적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준"


def _resolve(
    app_std: str | None,
    *,
    announced: str = "2026-06-10",
    lwlt: str = "87.745",
):
    raw_data = {
        "srvceDivNm": "기술용역",
        "sucsfbidMthdNm": METHOD_NAME,
        "sucsfbidLwltRate": lwlt,
        "bidNtceDt": announced,
    }
    if app_std:
        raw_data["sucsfbidMthdAppStd"] = app_std
    return resolve_evaluation_rule_from_raw_data("Servc", raw_data)


def _evaluation_path_base_rate(result) -> Decimal | None:
    """평가 경로(evaluations.py)가 읽는 기준비율을 같은 함수로 구합니다."""
    resolution = resolve_score_params(
        result.rule,
        Decimal("600000000"),
        "2026-06-10",
        METHOD_NAME,
    )
    return resolution.base_rate or result.rule.base_rate


def test_moe_cdw_rules_use_88_base_rate():
    assert len(MOE_CDW_RULES) == 6
    assert {rule.base_rate for rule in MOE_CDW_RULES} == {Decimal("0.88")}


def test_mois_stated_tech_announcement_uses_mois_rule_on_both_paths():
    result = _resolve(MOIS_APP_STD)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_TECH_LOCAL_ANNEX_01.rule_id
    assert result.base_rate == Decimal("0.88")
    assert MOIS_TECH_BASE_RATE_WARNING in result.warnings

    # 예측 경로(predictions.py:366)는 rule.base_rate 를 읽습니다.
    assert result.rule.base_rate == Decimal("0.88")
    # 평가 경로(evaluations.py:414)는 resolve_score_params 의 base_rate 를 읽습니다.
    assert _evaluation_path_base_rate(result) == Decimal("0.88")


def test_mois_stated_marker_compares_without_spaces():
    result = _resolve(MOIS_BIDDER_DECISION_STANDARD_MARKER)

    assert result.base_rate == Decimal("0.88")
    assert result.rule is not None
    assert result.rule.base_rate == Decimal("0.88")
    assert MOIS_TECH_BASE_RATE_WARNING in result.warnings


@pytest.mark.parametrize("app_std", [PPS_APP_STD, INSTITUTION_APP_STD])
def test_non_mois_stated_tech_announcement_keeps_rule_base_rate(app_std: str):
    result = _resolve(app_std)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.base_rate is None
    assert result.rule.base_rate == Decimal("0.90")
    assert _evaluation_path_base_rate(result) == Decimal("0.90")
    assert MOIS_TECH_BASE_RATE_WARNING not in result.warnings


def test_pre_20260526_tech_rule_is_unchanged():
    result = _resolve(MOIS_APP_STD, announced="2026-05-25")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526.rule_id
    assert result.base_rate is None
    assert result.rule.base_rate == Decimal("0.88")
