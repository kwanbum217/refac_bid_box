"""수요기관 자체 기술용역 기준 판본별 기준비율 계약 테스트 (2026-11-15).

한국지역난방공사·인천국제공항공사의 자체 기술용역 적격심사 세부기준을 공고가
명시하면, 규칙 선택은 조달청 현행 판본을 그대로 두고 공고일이 속한 기관 원문
판본의 기준비율 88/100 만 resolution.base_rate 에 채우는지 고정합니다.
"""

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    INST_TECH_BASE_RATE_WARNING,
    MOIS_BIDDER_DECISION_STANDARD_MARKER,
    MOIS_TECH_BASE_RATE_WARNING,
    MOIS_TECH_LOCAL_ANNEX_01,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT,
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
)

KDHC_APP_STD = "한국지역난방공사 기술용역 적격심사 세부기준"
IIAC_APP_STD = "인천국제공항공사 기술용역 적격심사 세부기준"
PPS_APP_STD = "조달청 기술용역 적격심사 세부기준"
METHOD_NAME = "적격심사제-추정가격이 10억원 미만 5억원 이상인 P.Q 대상 기술용역의 평가기준"


def _resolve(app_std: str | None, *, announced: str | None = "2026-06-01"):
    raw_data = {
        "srvceDivNm": "기술용역",
        "sucsfbidMthdNm": METHOD_NAME,
        "sucsfbidLwltRate": "87.745",
    }
    if announced is not None:
        raw_data["bidNtceDt"] = announced
    if app_std is not None:
        raw_data["sucsfbidMthdAppStd"] = app_std
    return resolve_evaluation_rule_from_raw_data("Servc", raw_data)


def test_kdhc_20260101_version_uses_88_base_rate():
    result = _resolve(KDHC_APP_STD, announced="2026-06-01")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.rule.base_rate == Decimal("0.90")
    assert result.base_rate == Decimal("0.88")
    assert INST_TECH_BASE_RATE_WARNING in result.warnings


def test_kdhc_20260818_version_keeps_rule_base_rate():
    result = _resolve(KDHC_APP_STD, announced="2026-09-01")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.base_rate is None
    assert result.rule.base_rate == Decimal("0.90")
    assert INST_TECH_BASE_RATE_WARNING not in result.warnings


def test_iiac_uses_88_base_rate():
    result = _resolve(IIAC_APP_STD, announced="2026-07-01")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.rule.base_rate == Decimal("0.90")
    assert result.base_rate == Decimal("0.88")
    assert INST_TECH_BASE_RATE_WARNING in result.warnings


def test_pps_stated_tech_announcement_keeps_rule_base_rate():
    result = _resolve(PPS_APP_STD, announced="2026-06-01")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.base_rate is None
    assert result.rule.base_rate == Decimal("0.90")
    assert INST_TECH_BASE_RATE_WARNING not in result.warnings


def test_mois_stated_selects_mois_annex_rule_on_both_paths():
    """행안부 지목 공고는 예규 별표 규칙을 쓰고 두 계산 경로가 0.88 을 읽습니다.

    2026-11-18 정정: 종전에는 이 분기가 조달청 규칙(rule_id
    SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT)을 그대로 두고 result.base_rate 만 0.88 로 바꿨습니다.
    그 결과 평가 경로(resolve_score_params 의 base_rate)와 예측 경로(rule.base_rate)는
    조달청 값 0.90 을 읽어 경고 문구만 88 이 되는 결함이 있었습니다. 이제 규칙 자체를
    예규 별표(기준비율 88, 예규 구간)로 갈아 끼우므로 두 경로 모두 0.88 입니다.
    """
    result = _resolve(MOIS_BIDDER_DECISION_STANDARD_MARKER, announced="2026-06-01")

    assert result.rule is not None
    assert result.rule.rule_id == MOIS_TECH_LOCAL_ANNEX_01.rule_id
    # 예측 경로(predictions.py)는 rule.base_rate 를 읽습니다.
    assert result.rule.base_rate == Decimal("0.88")
    # 평가 경로(evaluations.py)는 resolve_score_params 의 base_rate 를 읽습니다.
    resolution = resolve_score_params(result.rule, Decimal("600000000"), "2026-06-01", METHOD_NAME)
    assert resolution.base_rate == Decimal("0.88")
    assert result.base_rate == Decimal("0.88")
    assert MOIS_TECH_BASE_RATE_WARNING in result.warnings
    assert INST_TECH_BASE_RATE_WARNING not in result.warnings


@pytest.mark.parametrize(
    ("announced", "expected"),
    [
        ("2026-05-26", Decimal("0.88")),
        ("2026-08-17", Decimal("0.88")),
        ("2026-08-18", None),
    ],
)
def test_kdhc_version_boundaries(announced: str, expected: Decimal | None):
    result = _resolve(KDHC_APP_STD, announced=announced)

    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.base_rate == expected


@pytest.mark.parametrize("announced", ["2023-07-23", "2023-07-24", "2024-06-01"])
def test_iiac_before_current_rule_keeps_pre_rule(announced: str):
    result = _resolve(IIAC_APP_STD, announced=announced)

    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526.rule_id
    assert result.base_rate is None
    assert result.rule.base_rate == Decimal("0.88")


def test_kdhc_pre_20260526_rule_is_unchanged():
    result = _resolve(KDHC_APP_STD, announced="2026-05-25")

    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT_PRE_20260526.rule_id
    assert result.base_rate is None
    assert INST_TECH_BASE_RATE_WARNING not in result.warnings


def test_app_std_compares_without_spaces():
    result = _resolve("한국지역난방공사기술용역적격심사세부기준", announced="2026-06-01")

    assert result.base_rate == Decimal("0.88")
    assert INST_TECH_BASE_RATE_WARNING in result.warnings


def test_missing_announcement_date_keeps_rule_base_rate():
    result = _resolve(KDHC_APP_STD, announced=None)

    assert result.rule is not None
    assert result.rule.rule_id == SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT.rule_id
    assert result.base_rate is None
    assert INST_TECH_BASE_RATE_WARNING not in result.warnings
