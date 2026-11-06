"""행정안전부 예규 [별표 4] 학술연구용역 '2억미만 1억이상' 열 규칙 시험.

정본:
 - `.orca/capsules/task_mois_academic_1e2e_rule_20261106/capsule.yaml`
 - `src/app/services/evaluation_rules.py` 의 MOIS_ACADEMIC_BAND_ATTACHMENT_ONLY_RULES

이 규칙은 아직 첨부 판별이 없어 어떤 자동 매칭 경로에도 들어가지 않습니다. 규칙 값과 함께
낙찰방법명 매칭·현재 공고 판정이 새 규칙 추가 전(main)과 같음을 고정합니다.
DB·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_RULE_NOT_FOUND,
    INSTITUTION_RULES,
    LOCAL_RULES,
    MOE_CDW_RULES,
    MOIS_ACADEMIC_BAND_ATTACHMENT_ONLY_RULES,
    MOIS_ACADEMIC_BAND_RULES,
    POST_20260526_RULES,
    POST_20260727_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
    QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
    RULE_SCOPE_ALL,
    get_mois_academic_attachment_rule,
    match_rule_by_mthd_nm,
    resolve_evaluation_rule,
    select_mois_academic_band_rule,
)
from src.app.services.evaluation_scoring import calculate_price_score

NEW_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E"
METHOD_MIXED = "적격심사제-추정가격 2억미만 1억이상"
BID_DATE = "2026-06-01"
SIDO_CHUNGNAM = ("44", "충청남도")


def _new_rule():
    rules = MOIS_ACADEMIC_BAND_ATTACHMENT_ONLY_RULES
    assert len(rules) == 1
    return rules[0]


# --------------------------------------------------------------------------- #
# (a) 원문 값 (행안부 예규 [별표 4] 학술연구용역 평가기준 2억미만 1억이상 열)
# --------------------------------------------------------------------------- #


def test_attachment_only_rule_values() -> None:
    rule = _new_rule()
    assert rule.rule_id == NEW_RULE_ID
    assert rule.service_type == "ACADEMIC"
    assert (
        rule.table_name == "행안부 예규 제2장의2 [별표 4] 학술연구용역 (추정가격 2억미만 1억이상)"
    )
    assert rule.max_price_score == Decimal("60")
    assert rule.multiplier == Decimal("2")
    assert rule.base_rate == Decimal("0.88")
    assert rule.pass_threshold == Decimal("85")
    assert rule.lwlt_rate == Decimal("80.495")
    assert rule.effective_date == "2025-07-01"
    assert rule.patterns == ("추정가격 2억미만 1억이상", "추정가격 2억 미만 1억 이상")
    assert "2억미만 1억이상 열" in rule.source
    assert rule.quant_basis == QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED
    assert rule.score_table_source is not None
    assert "별표 4" in rule.score_table_source
    assert rule.institution_scope == RULE_SCOPE_ALL


# --------------------------------------------------------------------------- #
# (b), (c) 낙찰방법명만으로는 선택·매칭되지 않는다
# --------------------------------------------------------------------------- #


def test_mixed_band_is_not_selected_by_method_name() -> None:
    assert select_mois_academic_band_rule(METHOD_MIXED) is None
    assert select_mois_academic_band_rule(f"{METHOD_MIXED} - 지역업체참여") is None


def test_method_name_match_is_unchanged() -> None:
    result = match_rule_by_mthd_nm(METHOD_MIXED)
    assert result is None


# --------------------------------------------------------------------------- #
# (d) 현재 공고 판정은 바뀌지 않는다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("contract_regime", "sido", "expected_block"),
    [
        ("LOCAL", SIDO_CHUNGNAM, BLOCK_CODE_LOCAL_RULE_NOT_FOUND),
        (None, (None, None), BLOCK_CODE_RULE_NOT_FOUND),
    ],
)
def test_resolution_is_unchanged(
    contract_regime: str | None,
    sido: tuple[str | None, str | None],
    expected_block: str,
) -> None:
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=METHOD_MIXED,
        contract_regime=contract_regime,
        region_code=sido[0],
        region_name=sido[1],
        bid_ntce_dt=BID_DATE,
    )
    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == expected_block


# --------------------------------------------------------------------------- #
# (e) 첨부 판별 조회는 1E_2E 만 돌려준다
# --------------------------------------------------------------------------- #


def test_attachment_lookup_returns_rule_only_for_1e_2e() -> None:
    rule = get_mois_academic_attachment_rule("1E_2E")
    assert rule is not None
    assert rule.rule_id == NEW_RULE_ID
    for band in ("UNDER_1E", "OVER_2E", "2E_1E", "1e_2e", ""):
        assert get_mois_academic_attachment_rule(band) is None


# --------------------------------------------------------------------------- #
# (f) 평점 = 배점한도 - k x |기준비율x100 - 투찰률|
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(("bid_rate", "expected_score"), [("88", "60"), ("90", "56")])
def test_price_score_matches_formula(bid_rate: str, expected_score: str) -> None:
    rule = _new_rule()
    assert rule.base_rate is not None
    assert rule.max_price_score is not None
    assert rule.multiplier is not None
    result = calculate_price_score(
        Decimal(bid_rate),
        Decimal("100"),
        rule.base_rate,
        rule.max_price_score,
        rule.multiplier,
    )
    assert result.score == Decimal(expected_score)


# --------------------------------------------------------------------------- #
# 격리: 새 규칙은 어떤 매칭 풀에도 들어가지 않는다
# --------------------------------------------------------------------------- #


def test_attachment_only_rule_is_not_in_any_matching_pool() -> None:
    pools = {
        "POST_20260526_RULES": POST_20260526_RULES,
        "POST_20260727_RULES": POST_20260727_RULES,
        "PRE_20230501_RULES": PRE_20230501_RULES,
        "PRE_20250901_RULES": PRE_20250901_RULES,
        "MOE_CDW_RULES": MOE_CDW_RULES,
        "LOCAL_RULES": LOCAL_RULES,
        "INSTITUTION_RULES": INSTITUTION_RULES,
        "MOIS_ACADEMIC_BAND_RULES": MOIS_ACADEMIC_BAND_RULES,
    }
    for name, pool in pools.items():
        assert all(rule.rule_id != NEW_RULE_ID for rule in pool), name
    assert len(MOIS_ACADEMIC_BAND_RULES) == 2
