"""첨부 판별 PPS '2억미만 1억이상' 띠 공고의 조달청 학술연구 구제 시험.

정본: `.orca/capsules/task_3c0c9840ef73/capsule.yaml`

첨부 판별이 `PPS` 이고 낙찰방법명에 `2억미만`·`1억이상` 띠 표기가 있으며 조달청
기본 매칭이 RULE_NOT_FOUND 로 끝난 공고만, 판별 근거나 공고의 낙찰방법 적용 기준이
[별표 1] 학술연구용역을 지목할 때 공고일 판본의 학술연구용역 고시금액 미만 규칙으로
계산합니다. 하한율은 지금처럼 공고값이 우선합니다. DB·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_NEGOTIATION_CONTRACT,
    BLOCK_CODE_RULE_NOT_FOUND,
    MOIS_ACADEMIC_ATTACHMENT_WARNING,
    PPS_ACADEMIC_BAND_ATTACHMENT_WARNING,
    RULE_SCOPE_ALL,
    RuleResolutionResult,
    resolve_evaluation_rule,
    resolve_evaluation_rule_from_raw_data,
)

METHOD_MIXED = "적격심사제-추정가격 2억미만 1억이상"
METHOD_5E_UNDER = "적격심사제-추정가격 5억원미만"
APP_STD_ACADEMIC = "학술연구용역 적격심사 세부기준"
APP_STD_FACILITY = "시설분야용역 적격심사 세부기준"
EVIDENCE_ACADEMIC = (
    "적격심사기준 : 조달청 일반용역 적격심사 세부기준 [조달청공고 최신호, "
    "[별표1] 학술연구용역 적격심사"
)
PRE_20230501_RULE_ID = "SERVC_QUAL_PRE_20230501_ATTACH_06"
PRE_20250901_RULE_ID = "SERVC_QUAL_PRE_20250901_ATTACH_06"
POST_20260526_RULE_ID = "SERVC_QUAL_POST_20260526_ATTACH_06"
MOIS_ACADEMIC_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E"


def _resolve(
    *,
    method: str = METHOD_MIXED,
    attachment_regime: str | None = "PPS",
    raw_data: dict[str, object] | None = None,
    contract_regime: str | None = None,
    announced: str | None = "2025-12-31",
    lwlt: str | None = None,
    region_code: str | None = None,
    region_name: str | None = None,
    education_institution: bool = False,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        sucsfbid_lwlt_rate=lwlt,
        bid_ntce_dt=announced,
        contract_regime=contract_regime,
        region_code=region_code,
        region_name=region_name,
        education_institution=education_institution,
        raw_data=raw_data,
        attachment_regime=attachment_regime,
    )


# --------------------------------------------------------------------------- #
# (a) PPS 판별 + 2억미만 1억이상 + 학술연구 근거 -> 조달청 학술연구 고시금액 미만
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw_data",
    [
        {"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
        {"matched_rules": "R6,R7"},
        {"matchedRules": ["R6", "R7"]},
        {"evidence": EVIDENCE_ACADEMIC},
        {"bidNtceNm": "2026년 학술연구 조사 용역"},
    ],
)
def test_pps_band_academic_attachment_unblocks_with_notice_under_rule(
    raw_data: dict[str, object],
) -> None:
    result = _resolve(raw_data=raw_data)

    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == PRE_20250901_RULE_ID
    assert result.rule.max_price_score == Decimal("70")
    assert result.rule.multiplier == Decimal("4")
    assert result.rule.pass_threshold == Decimal("85")
    assert result.effective_lwlt_rate == Decimal("84.245")
    assert result.rate_source == "RULE_DEFAULT"
    assert PPS_ACADEMIC_BAND_ATTACHMENT_WARNING in result.warnings
    assert result.scope_stage == RULE_SCOPE_ALL


@pytest.mark.parametrize(
    ("announced", "expected_rule_id"),
    [
        ("2023-05-01", PRE_20230501_RULE_ID),
        ("2024-06-01", PRE_20230501_RULE_ID),
        ("2025-08-31", PRE_20230501_RULE_ID),
        ("2025-09-01", PRE_20250901_RULE_ID),
        ("2025-12-31", PRE_20250901_RULE_ID),
        ("2026-05-26", POST_20260526_RULE_ID),
        ("2026-08-01", POST_20260526_RULE_ID),
    ],
)
def test_rescue_rule_follows_announcement_edition(announced: str, expected_rule_id: str) -> None:
    result = _resolve(
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
        announced=announced,
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule_id


def test_local_announcement_is_rescued_before_local_rule_selection() -> None:
    result = _resolve(
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
        contract_regime="LOCAL",
        education_institution=True,
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PRE_20250901_RULE_ID
    assert result.scope_stage == RULE_SCOPE_ALL


def test_from_raw_data_forwards_pps_band_evidence() -> None:
    raw_data = {
        "sucsfbidMthdNm": METHOD_MIXED,
        "prearngPrceDcsnMthdNm": "복수예가",
        "bidNtceDt": "2025-12-24",
        "sucsfbidMthdAppStd": APP_STD_ACADEMIC,
        "sucsfbidLwltRate": "88",
    }
    result = resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw_data,
        attachment_regime="PPS",
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PRE_20250901_RULE_ID
    assert result.effective_lwlt_rate == Decimal("88")
    assert result.rate_source == "ANNOUNCEMENT"


# --------------------------------------------------------------------------- #
# (b) 학술연구 별표를 확인하지 못하면 종전 차단을 유지한다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    "raw_data",
    [
        {},
        {"sucsfbidMthdAppStd": APP_STD_FACILITY},
        {"matched_rules": "R6"},
        {"evidence": "조달청 일반용역 적격심사 세부기준 [별표 2] 시설분야용역"},
        {"bidNtceNm": "2025년 수탁검사 용역 입찰 재공고"},
    ],
)
def test_pps_band_without_academic_annex_stays_blocked(
    raw_data: dict[str, object],
) -> None:
    result = _resolve(raw_data=raw_data)

    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert PPS_ACADEMIC_BAND_ATTACHMENT_WARNING not in result.warnings


@pytest.mark.parametrize("attachment_regime", [None, "MOIS_OTHER", "NO_ATTACH"])
def test_non_pps_attachment_regime_is_unchanged(
    attachment_regime: str | None,
) -> None:
    result = _resolve(
        attachment_regime=attachment_regime,
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
    )

    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert PPS_ACADEMIC_BAND_ATTACHMENT_WARNING not in result.warnings


def test_pps_without_band_markers_is_unchanged() -> None:
    result = _resolve(
        method=METHOD_5E_UNDER,
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
    )

    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert PPS_ACADEMIC_BAND_ATTACHMENT_WARNING not in result.warnings


def test_other_block_code_is_not_rescued() -> None:
    result = _resolve(
        method="협상에의한계약-추정가격 2억미만 1억이상",
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
    )

    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_NEGOTIATION_CONTRACT
    assert PPS_ACADEMIC_BAND_ATTACHMENT_WARNING not in result.warnings


def test_missing_announcement_date_stays_blocked() -> None:
    result = _resolve(
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
        announced=None,
    )

    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


def test_announcement_before_earliest_edition_stays_blocked() -> None:
    result = _resolve(
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
        announced="2023-04-01",
    )

    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


# --------------------------------------------------------------------------- #
# (c) MOIS_ACADEMIC 판별은 기존 행안부 규칙 그대로다
# --------------------------------------------------------------------------- #


def test_mois_academic_regime_keeps_existing_rule() -> None:
    result = _resolve(
        attachment_regime="MOIS_ACADEMIC",
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
        contract_regime="LOCAL",
        announced="2026-06-01",
        region_code="44",
        region_name="충청남도",
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_ACADEMIC_RULE_ID
    assert result.effective_lwlt_rate == Decimal("80.495")
    assert MOIS_ACADEMIC_ATTACHMENT_WARNING in result.warnings
    assert PPS_ACADEMIC_BAND_ATTACHMENT_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (d) 공고 하한율이 있으면 그 값이 우선한다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("lwlt", ["88", "80.495", "84.245"])
def test_announcement_lwlt_wins_over_rule_default(lwlt: str) -> None:
    result = _resolve(
        raw_data={"sucsfbidMthdAppStd": APP_STD_ACADEMIC},
        lwlt=lwlt,
    )

    assert result.rule is not None
    assert result.rule.rule_id == PRE_20250901_RULE_ID
    assert result.effective_lwlt_rate == Decimal(lwlt)
    assert result.rate_source == "ANNOUNCEMENT"
