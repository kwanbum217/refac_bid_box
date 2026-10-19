"""학술연구용역 띠 표기 공고의 행안부 예규 제2장의2 [별표 4] 적용 시험.

정본:
 - `.orca/capsules/task_local_academic_band_20261017/capsule.yaml`
 - `docs/analysis/local_academic_band_apply_20261017.md` (원문 값 표)
 - `docs/analysis/band_only_basis_20261017.md` (표기별 기준 문서 조사)

기대값은 행안부 예규 [별표 4] 학술연구용역 평가기준 원문이 인쇄한 배점한도(B)·
평점계수(k)·기준비율(88)·적격통과점수(85)이며, 시험 안에서 계수를 역산하지 않는다.
DB·.env 를 쓰지 않는다. 전량 시험은 -m 'not data_assets' 로 돌린다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_RULE_NOT_FOUND,
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    MOIS_ACADEMIC_BAND_RULES,
    MOIS_ACADEMIC_BAND_WARNING,
    QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
    RULE_SCOPE_ALL,
    resolve_evaluation_rule,
    resolve_score_params,
    select_mois_academic_band_rule,
)

UNDER_1E_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E"
OVER_2E_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_OVER_2E"

METHOD_UNDER_1E = "적격심사제-추정가격 1억미만"
METHOD_OVER_2E = "적격심사제-추정가격 2억이상"
METHOD_MIXED = "적격심사제-추정가격 2억미만 1억이상"
METHOD_UNDER_1E_LOCAL = "적격심사제-추정가격 1억미만 - 지역업체참여"

BID_DATE = "2026-06-01"

# 청남(44)·전남광주(12)는 일반 띠 규칙이 없고, 인천(28)은 GENERAL/SIMPLE_LABOR 가 갈린다.
SIDO_CHUNGNAM = ("44", "충청남도")
SIDO_JNGJ = ("12", "전남광주통합특별시")
SIDO_INCHEON = ("28", "인천광역시")
SIDO_GYEONGNAM = ("48", "경상남도")
SIDO_GYEONGGI = ("41", "경기도")
SIDO_DAEGU = ("27", "대구광역시")

GYEONGNAM_GENERAL_RULE_ID = "SERVC_LOCAL_GN_20230105_ATTACH_01"
GYEONGGI_GENERAL_RULE_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_6"
DAEGU_SIMPLE_LABOR_RULE_ID = "SERVC_LOCAL_DAEGU_20260511_ATTACH_01"


def _resolve(
    method: str,
    *,
    sido: tuple[str | None, str | None] = (None, None),
    contract_regime: str | None = None,
    bid_ntce_dt: str = BID_DATE,
    estimated_price: str | None = None,
    lwlt_rate: str | None = None,
):
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        sucsfbid_lwlt_rate=lwlt_rate,
        contract_regime=contract_regime,
        region_code=sido[0],
        region_name=sido[1],
        bid_ntce_dt=bid_ntce_dt,
        estimated_price=estimated_price,
    )


def _rule(rule_id: str):
    match = next((rule for rule in MOIS_ACADEMIC_BAND_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


# --------------------------------------------------------------------------- #
# 1. 원문 값 (행안부 예규 [별표 4] 학술연구용역 평가기준)
# --------------------------------------------------------------------------- #


def test_under_1e_column_values() -> None:
    """[별표 4] 1억미만 열: B=65, k=2, 기준비율 88, 통과점수 85."""
    rule = _rule(UNDER_1E_RULE_ID)
    assert rule.max_price_score == Decimal("65")
    assert rule.multiplier == Decimal("2")
    assert rule.base_rate == Decimal("0.88")
    assert rule.pass_threshold == Decimal("85")
    assert rule.lwlt_rate == Decimal("80.495")
    assert rule.service_type == "ACADEMIC"
    assert rule.institution_scope == RULE_SCOPE_ALL
    assert rule.quant_basis == QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED
    assert "별표 4" in rule.score_table_source


def test_over_2e_column_values() -> None:
    """[별표 4] 2억이상 열: B=30, k=2, 기준비율 88, 통과점수 85."""
    rule = _rule(OVER_2E_RULE_ID)
    assert rule.max_price_score == Decimal("30")
    assert rule.multiplier == Decimal("2")
    assert rule.base_rate == Decimal("0.88")
    assert rule.pass_threshold == Decimal("85")
    assert rule.lwlt_rate == Decimal("80.495")


def test_score_params_close_the_lwlt_formula() -> None:
    """원문 산식 역산값(88 - (100-85)/2 = 80.5 -> 80.495)이 선언 하한율과 닫힌다."""
    for rule_id, expected_b in ((UNDER_1E_RULE_ID, "65"), (OVER_2E_RULE_ID, "30")):
        rule = _rule(rule_id)
        resolution = resolve_score_params(rule, Decimal("150000000"), None, None)
        assert resolution.max_price_score == Decimal(expected_b), rule_id
        assert resolution.multiplier == Decimal("2"), rule_id
        assert resolution.pass_threshold == Decimal("85"), rule_id
        derived = (
            rule.base_rate * Decimal("100")
            - (Decimal("100") - rule.pass_threshold) / rule.multiplier
        )
        assert derived == Decimal("80.5"), rule_id
        assert rule.lwlt_rate == Decimal("80.495"), rule_id


# --------------------------------------------------------------------------- #
# 2. 두 표기가 새 규칙으로 풀린다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("method", "rule_id", "b_value"),
    [
        (METHOD_UNDER_1E, UNDER_1E_RULE_ID, "65"),
        (METHOD_OVER_2E, OVER_2E_RULE_ID, "30"),
        (METHOD_UNDER_1E_LOCAL, UNDER_1E_RULE_ID, "65"),
    ],
)
def test_band_only_methods_select_mois_rule_without_sido_rule(
    method: str, rule_id: str, b_value: str
) -> None:
    """시·도 규칙이 표기를 풀지 못한 LOCAL 공고는 행안부 [별표 4] 해당 열로 계산한다."""
    result = _resolve(method, sido=SIDO_CHUNGNAM, contract_regime="LOCAL")
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.rule.max_price_score == Decimal(b_value)
    assert result.scope_stage == RULE_SCOPE_ALL
    assert MOIS_ACADEMIC_BAND_WARNING in result.warnings


def test_incheon_unresolved_service_type_falls_back_to_mois_rule() -> None:
    """세부유형이 갈려 차단되던 표기도 행안부 [별표 4] 로 풀린다."""
    result = _resolve(METHOD_UNDER_1E, sido=SIDO_INCHEON, contract_regime="LOCAL")
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == UNDER_1E_RULE_ID


def test_unknown_regime_notice_falls_back_to_mois_rule() -> None:
    """계약 법령이 미상인 지방공사·의료원 공고도 RULE_NOT_FOUND 로 남지 않는다."""
    result = _resolve(METHOD_OVER_2E, contract_regime=None)
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == OVER_2E_RULE_ID


def test_national_regime_notice_is_not_given_mois_rule() -> None:
    """행안부 예규는 지방계약 기준이라 국가계약 공고의 띠 표기는 풀지 않는다."""
    for method in (METHOD_UNDER_1E, METHOD_OVER_2E):
        result = _resolve(method, contract_regime="NATIONAL")
        assert result.rule is None or result.rule.rule_id not in (UNDER_1E_RULE_ID, OVER_2E_RULE_ID)


def test_announcement_lwlt_rate_wins_over_rule_default() -> None:
    """공고에 낙찰하한율이 있으면 언제나 공고값이 우선한다."""
    result = _resolve(
        METHOD_UNDER_1E,
        sido=SIDO_CHUNGNAM,
        contract_regime="LOCAL",
        lwlt_rate="82.5",
    )
    assert result.effective_lwlt_rate == Decimal("82.5")
    assert result.rate_source == "ANNOUNCEMENT"


# --------------------------------------------------------------------------- #
# 3. '2억미만 1억이상' 은 매칭하지 않는다 (공고마다 기준이 다름)
# --------------------------------------------------------------------------- #


def test_mixed_band_has_no_mois_rule() -> None:
    """'2억미만 1억이상' 은 어느 학술연구 열로도 확정하지 않는다."""
    assert select_mois_academic_band_rule(METHOD_MIXED) is None
    assert select_mois_academic_band_rule(f"{METHOD_MIXED} - 지역업체참여") is None


def test_mixed_band_keeps_previous_judgment() -> None:
    """'2억미만 1억이상' 표기의 판정은 바뀌지 않는다(차단 유지)."""
    localized = _resolve(METHOD_MIXED, sido=SIDO_CHUNGNAM, contract_regime="LOCAL")
    assert localized.rule is None
    assert localized.is_blocked is True
    assert localized.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND

    unknown = _resolve(METHOD_MIXED, contract_regime=None)
    assert unknown.rule is None
    assert unknown.is_blocked is True
    assert unknown.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


# --------------------------------------------------------------------------- #
# 4. 시·도 규칙으로 계산되던 공고의 판정은 바뀌지 않는다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", [METHOD_UNDER_1E, METHOD_OVER_2E, METHOD_UNDER_1E_LOCAL])
def test_gyeongnam_rule_is_not_overridden_by_mois(method: str) -> None:
    """경남은 일반 띠 규칙으로 확정되므로 행안부 규칙이 끼어들지 않는다."""
    result = _resolve(method, sido=SIDO_GYEONGNAM, contract_regime="LOCAL")
    assert result.rule is not None
    assert result.rule.rule_id == GYEONGNAM_GENERAL_RULE_ID
    assert result.scope_stage != RULE_SCOPE_ALL
    assert MOIS_ACADEMIC_BAND_WARNING not in result.warnings


def test_gyeonggi_rule_is_not_overridden_by_mois() -> None:
    result = _resolve(METHOD_UNDER_1E, sido=SIDO_GYEONGGI, contract_regime="LOCAL")
    assert result.rule is not None
    assert result.rule.rule_id == GYEONGGI_GENERAL_RULE_ID
    assert MOIS_ACADEMIC_BAND_WARNING not in result.warnings


def test_daegu_regime_mismatch_is_preserved() -> None:
    """시·도 별표가 매칭돼 시행일 대조로 막히던 공고는 그 차단을 그대로 둔다."""
    result = _resolve(
        METHOD_UNDER_1E,
        sido=SIDO_DAEGU,
        contract_regime="LOCAL",
        bid_ntce_dt="2022-09-29",
    )
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH
    assert result.rule is not None
    assert result.rule.rule_id == DAEGU_SIMPLE_LABOR_RULE_ID
