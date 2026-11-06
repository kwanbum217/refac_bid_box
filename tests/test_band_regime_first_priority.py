"""첨부 판별 갈래를 시·도 규칙보다 먼저 보는 해석 순서 시험.

정본: `.orca/capsules/task_619f854e3edc/capsule.yaml`

(a) MOIS_ACADEMIC 판별과 시·도 일반 별표가 함께 있는 공고는 행안부 [별표 4]
학술연구용역 2억미만 1억이상 열로 계산합니다. (b) 판별 행이 없으면 시·도 규칙을
그대로 씁니다. (c) 기관 규칙이 있는 공고는 판별이 있어도 기관 규칙을 씁니다.
(d) 띠 금액 밖 공고는 판별이 있어도 시·도 규칙을 씁니다. (e) PPS·LOCAL 판별은
종전과 같습니다. DB·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    MOIS_ACADEMIC_ATTACHMENT_WARNING,
    MOIS_TECH_ATTACHMENT_WARNING,
    RULE_SCOPE_ALL,
    RULE_SCOPE_INSTITUTION,
    RULE_SCOPE_REGION,
    RuleResolutionResult,
    resolve_evaluation_rule,
)

METHOD_MIXED = "적격심사제-추정가격 2억미만 1억이상"
METHOD_OVER_2E = "적격심사제-추정가격 2억이상"
IIAC_OTHER_METHOD = "적격심사제-기타용역 추정가격 2억미만 1억이상"
BID_DATE = "2026-06-01"

SIDO_GYEONGGI = ("41", "경기도")
GYEONGGI_GENERAL_RULE_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_6"
MOIS_ACADEMIC_1E_2E_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E"
MOIS_TECH_1E_2E_RULE_ID = "SERVC_LOCAL_MOIS_TECH_20250701_1E_2E"
IIAC_CODE = "B551177"
IIAC_NAME = "인천국제공항공사"
IIAC_OTHER_RULE_ID = "SERVC_INST_IIAC_20250101_OTHER"


def _resolve(
    method: str = METHOD_MIXED,
    *,
    attachment_regime: str | None = None,
    contract_regime: str | None = "LOCAL",
    sido: tuple[str | None, str | None] = SIDO_GYEONGGI,
    bid_ntce_dt: str = BID_DATE,
    institution_code: str | None = None,
    institution_name: str | None = None,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        contract_regime=contract_regime,
        region_code=sido[0],
        region_name=sido[1],
        bid_ntce_dt=bid_ntce_dt,
        estimated_price="150000000",
        attachment_regime=attachment_regime,
        institution_code=institution_code,
        institution_name=institution_name,
    )


# --------------------------------------------------------------------------- #
# (a) MOIS_ACADEMIC 판별이 시·도 일반 별표보다 먼저 적용된다
# --------------------------------------------------------------------------- #


def test_mois_academic_attachment_beats_sido_rule() -> None:
    result = _resolve(attachment_regime="MOIS_ACADEMIC")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_ACADEMIC_1E_2E_RULE_ID
    assert result.rule.max_price_score == Decimal("60")
    assert result.rule.multiplier == Decimal("2")
    assert result.rule.pass_threshold == Decimal("85")
    assert result.effective_lwlt_rate == Decimal("80.495")
    assert result.scope_stage == RULE_SCOPE_ALL
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING in result.warnings


def test_mois_tech_attachment_beats_sido_rule() -> None:
    result = _resolve(attachment_regime="MOIS_TECH")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_TECH_1E_2E_RULE_ID
    assert result.scope_stage == RULE_SCOPE_ALL
    assert MOIS_TECH_ATTACHMENT_WARNING in result.warnings


# --------------------------------------------------------------------------- #
# (b) 판별 행이 없으면 시·도 규칙을 그대로 쓴다
# --------------------------------------------------------------------------- #


def test_without_attachment_sido_rule_is_unchanged() -> None:
    result = _resolve()

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == GYEONGGI_GENERAL_RULE_ID
    assert result.scope_stage == RULE_SCOPE_REGION
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING not in result.warnings


def test_attachment_before_effective_date_falls_back_to_sido_rule() -> None:
    result = _resolve(attachment_regime="MOIS_ACADEMIC", bid_ntce_dt="2025-06-30")

    assert result.rule is not None
    assert result.rule.rule_id == GYEONGGI_GENERAL_RULE_ID
    assert result.scope_stage == RULE_SCOPE_REGION
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (c) 기관 규칙이 있으면 첨부 판별보다 먼저 적용된다
# --------------------------------------------------------------------------- #


def test_institution_rule_beats_attachment() -> None:
    baseline = _resolve(
        IIAC_OTHER_METHOD,
        contract_regime=None,
        sido=(None, None),
        institution_code=IIAC_CODE,
        institution_name=IIAC_NAME,
    )
    result = _resolve(
        IIAC_OTHER_METHOD,
        contract_regime=None,
        sido=(None, None),
        institution_code=IIAC_CODE,
        institution_name=IIAC_NAME,
        attachment_regime="MOIS_ACADEMIC",
    )

    assert baseline.rule is not None
    assert baseline.rule.rule_id == IIAC_OTHER_RULE_ID
    assert baseline.scope_stage == RULE_SCOPE_INSTITUTION
    assert result == baseline
    assert result.scope_stage == RULE_SCOPE_INSTITUTION
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (d) 띠 금액 밖 공고는 판별이 있어도 시·도 규칙을 쓴다
# --------------------------------------------------------------------------- #


def test_band_outside_1e_2e_keeps_sido_rule() -> None:
    result = _resolve(METHOD_OVER_2E, attachment_regime="MOIS_ACADEMIC")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == GYEONGGI_GENERAL_RULE_ID
    assert result.scope_stage == RULE_SCOPE_REGION
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING not in result.warnings


def test_national_contract_does_not_use_attachment() -> None:
    baseline = _resolve(contract_regime="NATIONAL", sido=(None, None))
    result = _resolve(
        contract_regime="NATIONAL", sido=(None, None), attachment_regime="MOIS_ACADEMIC"
    )

    assert result == baseline
    assert result.is_blocked is True
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (e) PPS·LOCAL 판별은 종전과 같다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("attachment_regime", ["PPS", "LOCAL"])
def test_other_attachment_regimes_are_unchanged(attachment_regime: str) -> None:
    assert _resolve(attachment_regime=attachment_regime) == _resolve()
