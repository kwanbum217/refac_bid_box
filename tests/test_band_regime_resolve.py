"""첨부 판별 갈래와 적격심사 규칙 해석기의 연결 시험.

정본: `.orca/capsules/task_band_regime_resolve_20261106/capsule.yaml`

`resolve_evaluation_rule` 의 attachment_regime 인자가 없거나 None 이면 종전 판정과
같아야 합니다. MOIS_ACADEMIC 이면서 낙찰방법명이 '2억미만 1억이상' 띠를 담고,
국가계약이 아니며, 시·도·기관 규칙으로 확정하지 못해 차단된 공고만 행안부 예규
제2장의2 [별표 4] 학술연구용역 2억미만 1억이상 열로 계산합니다. DB·.env 를 쓰지
않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_RULE_NOT_FOUND,
    MOIS_ACADEMIC_ATTACHMENT_WARNING,
    RULE_SCOPE_ALL,
    RuleResolutionResult,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)

NEW_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E"
UNDER_1E_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E"
METHOD_MIXED = "적격심사제-추정가격 2억미만 1억이상"
METHOD_UNDER_1E = "적격심사제-추정가격 1억미만"
BID_DATE = "2026-06-01"
SIDO_CHUNGNAM = ("44", "충청남도")


def _resolve(
    *,
    method: str = METHOD_MIXED,
    attachment_regime: str | None = None,
    contract_regime: str | None = "LOCAL",
    sido: tuple[str | None, str | None] = SIDO_CHUNGNAM,
    bid_ntce_dt: str | None = BID_DATE,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        contract_regime=contract_regime,
        region_code=sido[0],
        region_name=sido[1],
        bid_ntce_dt=bid_ntce_dt,
        attachment_regime=attachment_regime,
    )


# --------------------------------------------------------------------------- #
# (a) 인자가 없거나 None 이면 종전과 같은 차단
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("contract_regime", "sido", "expected_block"),
    [
        ("LOCAL", SIDO_CHUNGNAM, BLOCK_CODE_LOCAL_RULE_NOT_FOUND),
        (None, (None, None), BLOCK_CODE_RULE_NOT_FOUND),
    ],
)
@pytest.mark.parametrize("attachment_regime", [None, "UNSPECIFIED_SUBTABLE"])
def test_default_path_is_unchanged(
    contract_regime: str | None,
    sido: tuple[str | None, str | None],
    expected_block: str,
    attachment_regime: str | None,
) -> None:
    result = _resolve(
        contract_regime=contract_regime,
        sido=sido,
        attachment_regime=attachment_regime,
    )

    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == expected_block
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING not in result.warnings


def test_omitted_argument_equals_explicit_none() -> None:
    assert _resolve() == _resolve(attachment_regime=None)


# --------------------------------------------------------------------------- #
# (b) MOIS_ACADEMIC 이면 학술연구 1억~2억 규칙으로 계산한다
# --------------------------------------------------------------------------- #


def test_mois_academic_attachment_unblocks_with_new_rule() -> None:
    result = _resolve(attachment_regime="MOIS_ACADEMIC")

    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == NEW_RULE_ID
    assert result.effective_lwlt_rate == Decimal("80.495")
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING in result.warnings
    assert result.scope_stage == RULE_SCOPE_ALL


# --------------------------------------------------------------------------- #
# (c) 국가계약은 첨부 판별이 학술연구여도 바꾸지 않는다
# --------------------------------------------------------------------------- #


def test_national_contract_is_unchanged() -> None:
    baseline = _resolve(contract_regime="NATIONAL")
    result = _resolve(contract_regime="NATIONAL", attachment_regime="MOIS_ACADEMIC")

    assert result == baseline
    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


# --------------------------------------------------------------------------- #
# (d) 다른 첨부 판별 값은 결과를 바꾸지 않는다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("attachment_regime", ["PPS", "UNSPECIFIED_SUBTABLE", "EXTRACT_FAIL"])
def test_other_attachment_regimes_are_unchanged(attachment_regime: str) -> None:
    assert _resolve(attachment_regime=attachment_regime) == _resolve()


# --------------------------------------------------------------------------- #
# (e) 다른 띠 공고는 바꾸지 않는다
# --------------------------------------------------------------------------- #


def test_other_band_is_unchanged() -> None:
    baseline = _resolve(method=METHOD_UNDER_1E)
    result = _resolve(method=METHOD_UNDER_1E, attachment_regime="MOIS_ACADEMIC")

    assert baseline.rule is not None
    assert baseline.rule.rule_id == UNDER_1E_RULE_ID
    assert result == baseline


# --------------------------------------------------------------------------- #
# (f) 규칙 시행일 이전 공고에는 적용하지 않는다
# --------------------------------------------------------------------------- #


def test_announcement_before_effective_date_is_unchanged() -> None:
    baseline = _resolve(bid_ntce_dt="2025-06-30")
    result = _resolve(bid_ntce_dt="2025-06-30", attachment_regime="MOIS_ACADEMIC")

    assert result == baseline
    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# raw_data 경로도 같은 인자를 그대로 넘긴다
# --------------------------------------------------------------------------- #


def test_from_raw_data_forwards_attachment_regime() -> None:
    raw_data = {
        "sucsfbidMthdNm": METHOD_MIXED,
        "prearngPrceDcsnMthdNm": "복수예가",
        "bidNtceDt": BID_DATE,
    }
    baseline = resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw_data,
        institution_regime="LOCAL",
        region_code=SIDO_CHUNGNAM[0],
        region_name=SIDO_CHUNGNAM[1],
    )
    result = resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw_data,
        institution_regime="LOCAL",
        region_code=SIDO_CHUNGNAM[0],
        region_name=SIDO_CHUNGNAM[1],
        attachment_regime="MOIS_ACADEMIC",
    )

    assert baseline.rule is None
    assert baseline.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.rule is not None
    assert result.rule.rule_id == NEW_RULE_ID
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING in result.warnings
