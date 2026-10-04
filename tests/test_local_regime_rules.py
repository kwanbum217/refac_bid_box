"""지방계약(LOCAL) 시·도 자체 별표 레지스트리 1단계 도메인 시험.

정본:
 - docs/design/local_regime_rules_design_20261005.md 0절(사용자 결정 확정)·4~8·10절
 - docs/analysis/servc_formula_collection_local_20261004.md 4.2~4.12절 (수치 원문)

기대값은 수집 문서가 인쇄한 B·k·T 와 그 대입 검산값이며, 테스트 안에서 계수를 역산하지 않는다.
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

import pytest

from src.app.services.demand_institutions import institution_sido
from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
    LOCAL_RULES,
    POST_20260727_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
    QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
    QUANT_BASIS_REGISTRY,
    RULE_SCOPE_ALL,
    RULE_SCOPE_REGION,
    EvaluationRule,
    PriceBand,
    ThresholdBand,
    quant_score_table_for_rule,
    resolve_evaluation_rule,
    resolve_local_service_type,
    resolve_score_params,
    select_price_band,
    select_threshold_band,
)

METHOD_FACILITY = "시설분야용역 적격심사 추정가격 5억원 이상"
METHOD_GENERIC = "추정가격 2억원 미만인 용역"


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def _resolve(**kwargs: object):
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        contract_regime="LOCAL",
        bid_ntce_dt="2026-06-01",
        **kwargs,
    )


def _resolve_jngj(**kwargs: object):
    """전남광주 별표는 시행일(2026-07-16) 이후 공고일로 판별한다."""
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        contract_regime="LOCAL",
        bid_ntce_dt="2026-07-16",
        region_code="12",
        region_name="전남광주통합특별시",
        **kwargs,
    )


# --------------------------------------------------------------------------- #
# 1. 신규 구간 필드와 선택기
# --------------------------------------------------------------------------- #


def test_price_band_selection_by_estimated_price() -> None:
    """4구간에서 경계값(2억/5억/10억)이 원문 구간 표기대로 선택된다."""
    rule = _rule("SERVC_LOCAL_INCHEON_20251224_ATTACH_01")
    cases = (
        ("150000000", "90", "20", "추정가격 2억원 미만"),
        ("200000000", "70", "4", "5억원 미만 2억원 이상"),
        ("500000000", "50", "2", "10억원 미만 5억원 이상"),
        ("1000000000", "30", "1", "추정가격 10억원 이상"),
    )
    for price, b_value, k_value, label in cases:
        result = resolve_score_params(rule, Decimal(price), None, None)
        assert result.max_price_score == Decimal(b_value), price
        assert result.multiplier == Decimal(k_value), price
        assert result.price_band_label == label, price


def test_threshold_band_uses_its_own_boundaries() -> None:
    """B·k 경계(2억/5억/10억)와 다른 T 경계(10억/30억)에서 올바른 T 를 고른다."""
    rule = _rule("SERVC_LOCAL_INCHEON_20251224_ATTACH_01")
    assert resolve_score_params(rule, Decimal("500000000"), None, None).pass_threshold == Decimal(
        "95"
    )
    assert resolve_score_params(rule, Decimal("1000000000"), None, None).pass_threshold == Decimal(
        "90"
    )
    assert resolve_score_params(rule, Decimal("3000000000"), None, None).pass_threshold == Decimal(
        "85"
    )
    # 경계값 30억은 30억원 이상 구간(T=85)
    assert resolve_score_params(rule, Decimal("3000000000"), None, None).threshold_band_label == (
        "추정가격 30억원 이상"
    )


def test_price_band_requires_estimated_price() -> None:
    """추정가격이 없으면 밴드를 임의 선택하지 않고 미확정으로 돌려준다."""
    rule = _rule("SERVC_LOCAL_INCHEON_20251224_ATTACH_01")
    result = resolve_score_params(rule, None, None, None)
    assert result.max_price_score is None
    assert result.multiplier is None
    assert result.pass_threshold is None
    assert result.warnings
    band, index, reason = select_price_band(rule.price_bands or (), None)
    assert band is None
    assert index is None
    assert reason


def test_threshold_selector_returns_none_without_price() -> None:
    rule = _rule("SERVC_LOCAL_CB_20231020_ATTACH_01")
    band, _, reason = select_threshold_band(rule.threshold_bands or (), None)
    assert band is None
    assert reason


def test_price_bands_and_flat_fields_cannot_coexist() -> None:
    """price_bands 와 기존 B/k 동시 선언, threshold_bands 와 pass_threshold 동시 선언이 ValueError."""
    rule = _rule("SERVC_LOCAL_INCHEON_20251224_ATTACH_01")
    with pytest.raises(ValueError):
        replace(rule, max_price_score=Decimal("30"))
    with pytest.raises(ValueError):
        replace(rule, multiplier=Decimal("1"))
    with pytest.raises(ValueError):
        replace(rule, pass_threshold=Decimal("95"))


def test_band_lists_are_sorted_and_single_open_upper() -> None:
    """정렬 위반·상한 없는 밴드 2개·상한 없는 마지막 아님을 ValueError 로 막는다."""
    base = _rule("SERVC_LOCAL_INCHEON_20251224_ATTACH_01")
    with pytest.raises(ValueError):
        replace(
            base,
            price_bands=(
                PriceBand(Decimal("500000000"), Decimal("70"), Decimal("4")),
                PriceBand(Decimal("200000000"), Decimal("90"), Decimal("20")),
                PriceBand(None, Decimal("30"), Decimal("1")),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            base,
            price_bands=(
                PriceBand(None, Decimal("70"), Decimal("4")),
                PriceBand(None, Decimal("30"), Decimal("1")),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            base,
            threshold_bands=(
                ThresholdBand(Decimal("1000000000"), Decimal("95")),
                ThresholdBand(Decimal("3000000000"), Decimal("90")),
            ),
        )
    with pytest.raises(ValueError):
        replace(
            base,
            price_bands=(PriceBand(None, Decimal("30"), Decimal("0")),),
        )


# --------------------------------------------------------------------------- #
# 2. LOCAL 규칙 선택
# --------------------------------------------------------------------------- #


def test_local_registry_has_regional_rules_only_without_mois_default() -> None:
    """D8: LOCAL_RULES 에 ALL(행안부 기본) 규칙이 없고 모두 REGION 이다."""
    assert LOCAL_RULES
    assert all(rule.institution_scope == RULE_SCOPE_REGION for rule in LOCAL_RULES)
    assert all(rule.contract_regime == "LOCAL" for rule in LOCAL_RULES)
    assert all(rule.quant_basis == QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED for rule in LOCAL_RULES)
    assert not any(rule.institution_scope == RULE_SCOPE_ALL for rule in LOCAL_RULES)
    assert not any("MOIS" in rule.rule_id for rule in LOCAL_RULES)


def test_local_regime_uses_sido_rule() -> None:
    """LOCAL + 인천 → 인천 규칙, 시·도 규칙 없는 시·도 → LOCAL_RULE_NOT_FOUND."""
    incheon = _resolve(sucsfbid_mthd_nm=METHOD_FACILITY, region_code="28", region_name="인천광역시")
    assert incheon.rule is not None
    assert incheon.rule.rule_id == "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
    assert incheon.is_blocked is False

    # 서울은 별표 미수집이라 시·도 규칙이 없다(D8, 행안부 기본 없음).
    seoul = _resolve(sucsfbid_mthd_nm=METHOD_FACILITY, region_code="11", region_name="서울특별시")
    assert seoul.rule is None
    assert seoul.is_blocked is True
    assert seoul.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert "B" in (seoul.block_reason_message or "")


def test_local_regime_never_matches_traffic_rules() -> None:
    """LOCAL 공고에서 조달청 규칙(PRE_*/POST_*)이 선택되지 않는다."""
    result = _resolve(sucsfbid_mthd_nm=METHOD_FACILITY, region_code="28", region_name="인천광역시")
    assert result.rule is not None
    traffic_ids = {
        rule.rule_id for rule in (*PRE_20230501_RULES, *PRE_20250901_RULES, *POST_20260727_RULES)
    }
    assert result.rule.rule_id not in traffic_ids
    assert result.rule.rule_id.startswith("SERVC_LOCAL_")


def test_national_regime_keeps_traffic_rules() -> None:
    """NATIONAL 공고는 기존 조달청 규칙 그대로 선택된다(회귀)."""
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=METHOD_FACILITY,
        contract_regime="NATIONAL",
        bid_ntce_dt="2026-06-01",
    )
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_QUAL_")


def test_unknown_regime_keeps_traffic_rules() -> None:
    """미상(None) 공고는 현행 조달청 규칙 적용을 유지한다(D6)."""
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=METHOD_FACILITY,
        contract_regime=None,
        bid_ntce_dt="2026-06-01",
    )
    assert result.rule is not None
    assert result.rule.rule_id.startswith("SERVC_QUAL_")


@pytest.mark.parametrize(
    ("method", "expected_block"),
    [
        ("적격심사제-관리규정외 수기심사(총점입력)", "MANUAL_EVALUATION"),
        ("협상에의한계약", "NEGOTIATION_CONTRACT"),
    ],
)
def test_manual_and_negotiation_blocks_survive_local(method: str, expected_block: str) -> None:
    """LOCAL 이어도 수기·협상 차단은 유지된다(일반 띠 아님)."""
    result = _resolve(sucsfbid_mthd_nm=method, region_code="28", region_name="인천광역시")
    assert result.is_blocked is True
    assert result.block_reason_code == expected_block


def test_local_tech_service_keeps_announcement_lwlt() -> None:
    """LOCAL 기술용역은 공고 하한율 경로를 유지한다(2.2절)."""
    result = _resolve(
        sucsfbid_mthd_nm="기술용역 적격심사",
        srvce_div_nm="기술용역",
        sucsfbid_lwlt_rate="89.9",
        region_code="28",
        region_name="인천광역시",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_TECH_QUAL_ANNOUNCEMENT_LWLT"
    assert result.effective_lwlt_rate == Decimal("89.9")


def test_local_service_type_unresolved_blocks_with_reason() -> None:
    """인천 일반 띠는 GENERAL/SIMPLE_LABOR 가 갈려 사용자 선택 안내와 함께 차단한다(D5)."""
    result = _resolve(sucsfbid_mthd_nm=METHOD_GENERIC, region_code="28", region_name="인천광역시")
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    joined = " ".join(result.warnings)
    assert "SERVC_LOCAL_INCHEON_20251224_ATTACH_01" in joined
    assert "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR" in joined
    assert "local_service_type" in (result.block_reason_message or "")


def test_local_user_selection_applies_chosen_rule() -> None:
    """사용자가 고른 세부유형으로 별표를 확정한다."""
    result = _resolve(
        sucsfbid_mthd_nm=METHOD_GENERIC,
        region_code="28",
        region_name="인천광역시",
        local_service_type="SIMPLE_LABOR",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR"


def test_simple_labor_marker_selects_simple_labor_rule() -> None:
    """낙찰방법명에 '단순노무' 가 있으면 자동으로 그 별표를 쓴다(D5)."""
    result = _resolve(
        sucsfbid_mthd_nm="단순노무용역 적격심사 추정가격 5억원 이상",
        region_code="28",
        region_name="인천광역시",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR"


def test_local_general_band_uses_procurement_class() -> None:
    """일반 띠 + 폐기물 조달분류 → 세종 폐기물 별표."""
    result = _resolve(
        sucsfbid_mthd_nm=METHOD_GENERIC,
        region_code="36",
        region_name="세종특별자치시",
        raw_data={"pubPrcrmntLrgClsfcNm": "폐기물 처리 및 재활용서비스"},
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_SEJONG_20251201_ATTACH_04"
    assert (
        resolve_local_service_type(
            {"pubPrcrmntLrgClsfcNm": "폐기물 처리 및 재활용서비스"}, METHOD_GENERIC
        )[0]
        == "WASTE"
    )


def test_quant_score_table_none_for_local_rules() -> None:
    """LOCAL 규칙은 quant_score_table_for_rule 이 조달청 배점표를 돌려주지 않는다."""
    for rule in LOCAL_RULES:
        assert quant_score_table_for_rule(rule) is None


def test_traffic_rules_keep_single_axis_and_registry_basis() -> None:
    """기존 조달청 규칙 45개는 구간 필드·quant_basis 가 그대로다."""
    traffic_rules = (*PRE_20230501_RULES, *PRE_20250901_RULES, *POST_20260727_RULES)
    assert all(rule.price_bands is None for rule in traffic_rules)
    assert all(rule.threshold_bands is None for rule in traffic_rules)
    assert all(rule.quant_basis == QUANT_BASIS_REGISTRY for rule in traffic_rules)


def test_traffic_resolve_score_params_unchanged() -> None:
    """기존 규칙의 resolve_score_params 결과·basis 가 그대로다(회귀)."""
    rule = next(rule for rule in POST_20260727_RULES if rule.rule_id.endswith("ATTACH_01"))
    below = resolve_score_params(rule, Decimal("499999999"), None, "추정가격 5억원 미만")
    assert below.max_price_score == Decimal("70")
    assert below.max_price_score_basis == "METHOD_NAME"
    above = resolve_score_params(rule, Decimal("500000000"), None, None)
    assert above.max_price_score == Decimal("60")
    assert above.max_price_score_basis == "ESTIMATED_PRICE"


# --------------------------------------------------------------------------- #
# 3. institution_sido 정규화
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("toplvl", "expected"),
    [
        ("강원도", ("51", "강원특별자치도")),
        ("전라북도", ("52", "전북특별자치도")),
        ("제주도", ("50", "제주특별자치도")),
        ("전라남도", ("12", "전남광주통합특별시")),
        ("광주광역시", ("12", "전남광주통합특별시")),
        ("인천광역시", ("28", "인천광역시")),
    ],
)
def test_institution_sido_normalizes_legacy_province_names(
    toplvl: str, expected: tuple[str, str]
) -> None:
    assert institution_sido({"toplvlInsttNm": toplvl}) == expected


@pytest.mark.parametrize("toplvl", ["경기도교육청", "서울물재생시설공단", "(없음)", ""])
def test_institution_sido_rejects_non_sido_toplvl(toplvl: str) -> None:
    assert institution_sido({"toplvlInsttNm": toplvl}) == (None, None)


def test_institution_sido_falls_back_to_region_first_token() -> None:
    assert institution_sido({"rgnNm": "대구광역시 중구"}) == ("27", "대구광역시")
    assert institution_sido(None) == (None, None)


# --------------------------------------------------------------------------- #
# 4. 시·도별 원문 인쇄 점수 검산 (평탄 구간 대입값)
# --------------------------------------------------------------------------- #

# (rule_id, 추정가격, 원문 평탄 투찰률(%), 원문 인쇄 점수)
PRINTED_SCORE_CASES = (
    ("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", "1000000000", "98", "20"),
    ("SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR", "1000000000", "88.25", "25"),
    ("SERVC_LOCAL_JEJU_20240101_ATTACH_01", "1000000000", "98", "20"),
    ("SERVC_LOCAL_GANGWON_20230611_ATTACH_01", "1000000000", "98", "20"),
    ("SERVC_LOCAL_GB_20260108_ATTACH_01", "500000000", "88.25", "45"),
    ("SERVC_LOCAL_GB_20260108_ATTACH_03", "500000000", "89.25", "45"),
    ("SERVC_LOCAL_GB_20260108_ATTACH_04", "500000000", "89.25", "45"),
    ("SERVC_LOCAL_ULSAN_20220810_ATTACH_01", "1000000000", "98", "20"),
    ("SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1", "3000000000", "88.25", "20"),
    ("SERVC_LOCAL_ULSAN_20220810_ATTACH_02", "1000000000", "98", "20"),
    ("SERVC_LOCAL_CB_20231020_ATTACH_01", "1000000000", "98", "20"),
    ("SERVC_LOCAL_JNGJ_20260716_ATTACH_01", "500000000", "88.25", "45"),
    ("SERVC_LOCAL_JNGJ_20260716_ATTACH_02", "500000000", "90.5", "45"),
    ("SERVC_LOCAL_JNGJ_20260716_ATTACH_03", "500000000", "93", "25"),
    ("SERVC_LOCAL_JNGJ_20260716_ATTACH_04", "3000000000", "88.25", "15"),
    ("SERVC_LOCAL_JNGJ_20260716_ATTACH_05", "500000000", "90.5", "55"),
    ("SERVC_LOCAL_JNGJ_20260716_ATTACH_06", "1000000000", "98", "20"),
    ("SERVC_LOCAL_GN_20230105_ATTACH_01", "1000000000", "98", "20"),
    ("SERVC_LOCAL_GG_20250808_ATTACH_1_2", "1000000000", "98", "20"),
    ("SERVC_LOCAL_GG_20250808_ATTACH_1_3", "300000000", "89.25", "55"),
    ("SERVC_LOCAL_GG_20250808_ATTACH_1_4", "1000000000", "90.5", "20"),
    ("SERVC_LOCAL_GG_20250808_ATTACH_1_6", "1000000000", "98", "20"),
)


@pytest.mark.parametrize(
    ("rule_id", "price", "flat_percent", "expected_score"), PRINTED_SCORE_CASES
)
def test_local_rule_printed_score_matches_source(
    rule_id: str, price: str, flat_percent: str, expected_score: str
) -> None:
    """원문이 인쇄한 평탄 점수와 규칙의 B·k·기준비율(88) 대입값이 일치한다."""
    rule = _rule(rule_id)
    resolution = resolve_score_params(rule, Decimal(price), None, None)
    assert resolution.max_price_score is not None
    assert resolution.multiplier is not None
    base_rate = resolution.base_rate or rule.base_rate
    difference = abs(base_rate - Decimal(flat_percent) / Decimal("100")) * Decimal("100")
    computed = resolution.max_price_score - resolution.multiplier * difference
    assert computed == Decimal(expected_score), rule_id


# 시·도마다 대표 규칙 하나의 대표 구간 B·k·T 를 원문과 대조한다.
REPRESENTATIVE_VALUES = (
    ("SERVC_LOCAL_INCHEON_20251224_ATTACH_01", "150000000", "90", "20", "95"),
    ("SERVC_LOCAL_JEJU_20240101_ATTACH_01", "200000000", "70", "4", "95"),
    ("SERVC_LOCAL_GANGWON_20230611_ATTACH_01", "3000000000", "30", "1", "85"),
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_02", "600000000", "60", "60", "85"),
    ("SERVC_LOCAL_GB_20260108_ATTACH_02", "600000000", "60", "4", "88"),
    ("SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1", "20000000000", "30", "40", "85"),
    ("SERVC_LOCAL_CB_20231020_ATTACH_01", "600000000", "50", "2", "95"),
    ("SERVC_LOCAL_JNGJ_20260716_ATTACH_03", "600000000", "30", "1", "95"),
    ("SERVC_LOCAL_GN_20230105_ATTACH_01", "1500000000", "30", "1", "90"),
    ("SERVC_LOCAL_DAEGU_20260511_ATTACH_01", "300000000", "60", "60", "85"),
    ("SERVC_LOCAL_GG_20250808_ATTACH_1_5", "600000000", "60", "0.375", "85"),
)


@pytest.mark.parametrize(
    ("rule_id", "price", "expected_b", "expected_k", "expected_t"), REPRESENTATIVE_VALUES
)
def test_local_rule_representative_values(
    rule_id: str, price: str, expected_b: str, expected_k: str, expected_t: str
) -> None:
    result = resolve_score_params(_rule(rule_id), Decimal(price), None, None)
    assert result.max_price_score == Decimal(expected_b)
    assert result.multiplier == Decimal(expected_k)
    assert result.pass_threshold == Decimal(expected_t)


# --------------------------------------------------------------------------- #
# 5. 전남광주 별표 6 분리와 세종·대구 통과점수 조건
# --------------------------------------------------------------------------- #


def test_jngj_fishery_cleanup_rule_is_not_general() -> None:
    """전남광주 별표 6 은 어장정화·정비 전용이라 GENERAL 로 등록되지 않는다."""
    fishery = _rule("SERVC_LOCAL_JNGJ_20260716_ATTACH_06")
    assert fishery.service_type == "FISHERY_CLEANUP"
    assert not any(
        rule.region_code == "12" and rule.service_type == "GENERAL" for rule in LOCAL_RULES
    )


def test_jngj_general_service_has_no_sido_rule() -> None:
    """전남광주 일반용역(어장정화·정비 아님)은 시·도 규칙 없음 경로로 차단된다."""
    result = _resolve_jngj(sucsfbid_mthd_nm=METHOD_GENERIC)
    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND


def test_jngj_fishery_method_name_confirms_attach_06() -> None:
    """낙찰방법명에 '어장' 이 있으면 별표 6 을 확정한다."""
    method = "적격심사제-어장정화·정비용역"
    assert resolve_local_service_type(None, method)[0] == "FISHERY_CLEANUP"
    result = _resolve_jngj(sucsfbid_mthd_nm=method)
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_JNGJ_20260716_ATTACH_06"


def test_jngj_fishery_announcement_name_only_recommends() -> None:
    """공고명의 어장 신호만으로는 확정하지 않고 추천 경고만 남긴다."""
    result = _resolve_jngj(
        sucsfbid_mthd_nm=METHOD_GENERIC,
        raw_data={"bidNtceNm": "어장정화·정비 용역"},
    )
    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert any("FISHERY_CLEANUP 추천" in warning for warning in result.warnings)


SEJONG_SW_NON_TARGET_ID = "SERVC_LOCAL_SEJONG_20251201_ATTACH_03"
SEJONG_SW_TARGET_ID = "SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME"
SEJONG_LT_NON_TARGET_ID = "SERVC_LOCAL_SEJONG_20251201_ATTACH_05"
SEJONG_LT_TARGET_ID = "SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME"


def test_jngj_land_transport_accepts_passenger_and_freight() -> None:
    """전남광주 별표 5 육상운송은 여객·화물 구분이 없어 두 표기 모두 같은 별표로 간다(B2)."""
    for marker in ("여객", "화물", "육상운송"):
        result = _resolve_jngj(
            sucsfbid_mthd_nm=f"{marker} 육상운송용역 적격심사 추정가격 5억원 미만"
        )
        assert result.rule is not None, marker
        assert result.rule.rule_id == "SERVC_LOCAL_JNGJ_20260716_ATTACH_05", marker
        assert result.rule.service_type == "LAND_TRANSPORT", marker


def test_gg_land_transport_accepts_passenger_and_freight() -> None:
    """경기 별표 1-4 육상운송이 여객·화물 모두 이 별표로 가고 일반 별표로 넘어가지 않는다(B2)."""
    for marker in ("여객", "화물"):
        result = _resolve(
            sucsfbid_mthd_nm=f"{marker} 육상운송용역 적격심사 추정가격 5억원 미만",
            region_code="41",
            region_name="경기도",
        )
        assert result.rule is not None, marker
        assert result.rule.rule_id == "SERVC_LOCAL_GG_20250808_ATTACH_1_4", marker
        assert all("일반 별표를 적용했습니다" not in warning for warning in result.warnings), marker


def test_sejong_land_transport_accepts_passenger_and_freight() -> None:
    """세종 별표 5 육상운송이 여객·화물 모두 대상/비대상 별표로 도달한다(B3)."""
    cases = (
        (
            "여객 육상운송용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 미만",
            SEJONG_LT_NON_TARGET_ID,
        ),
        (
            "화물 육상운송용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 미만",
            SEJONG_LT_NON_TARGET_ID,
        ),
        (
            "여객 육상운송용역(중소기업자간 경쟁제품) 적격심사 추정가격 5억원 미만",
            SEJONG_LT_TARGET_ID,
        ),
        (
            "화물 육상운송용역(중소기업자간 경쟁제품) 적격심사 추정가격 5억원 미만",
            SEJONG_LT_TARGET_ID,
        ),
    )
    for method, rule_id in cases:
        result = _resolve(sucsfbid_mthd_nm=method, region_code="36", region_name="세종특별자치시")
        assert result.rule is not None, method
        assert result.rule.rule_id == rule_id, method


def test_sejong_sme_pair_registry_values_match_source() -> None:
    """세종 SW·육상운송 비대상/대상 두 규칙의 B·k·하한율·T 가 원문 행과 일치한다(B4)."""
    expected = {
        SEJONG_SW_NON_TARGET_ID: ("80.495", "85", "2"),
        SEJONG_SW_TARGET_ID: ("84.995", "88", "4"),
        SEJONG_LT_NON_TARGET_ID: ("80.495", "85", "2"),
        SEJONG_LT_TARGET_ID: ("84.995", "88", "4"),
    }
    for rule_id, (lwlt, threshold, k) in expected.items():
        rule = _rule(rule_id)
        assert rule.lwlt_rate == Decimal(lwlt), rule_id
        below = resolve_score_params(rule, Decimal("400000000"), None, None)
        above = resolve_score_params(rule, Decimal("600000000"), None, None)
        assert below.max_price_score == Decimal("70"), rule_id
        assert above.max_price_score == Decimal("60"), rule_id
        assert below.multiplier == Decimal(k), rule_id
        assert above.multiplier == Decimal(k), rule_id
        assert below.pass_threshold == Decimal(threshold), rule_id
        assert "byp3_sw_2025" in rule.source or "byp5_2025" in rule.source, rule_id
        assert "sejong_body_2025.txt:108" in rule.source, rule_id


def test_sejong_sme_non_target_marker_keeps_non_target_rule() -> None:
    """B1: '중소기업자간 경쟁제품 비대상' 표기에 대상 규칙(k 4·T 88)이 붙지 않는다."""
    cases = (
        (
            "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 미만",
            SEJONG_SW_NON_TARGET_ID,
        ),
        (
            "화물 육상운송용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 미만",
            SEJONG_LT_NON_TARGET_ID,
        ),
    )
    for method, rule_id in cases:
        result = _resolve(sucsfbid_mthd_nm=method, region_code="36", region_name="세종특별자치시")
        assert result.rule is not None, method
        assert result.rule.rule_id == rule_id, method
        resolution = resolve_score_params(result.rule, Decimal("400000000"), None, None)
        assert resolution.multiplier == Decimal("2"), method
        assert resolution.pass_threshold == Decimal("85"), method
        assert resolution.pass_threshold != Decimal("88"), method


def test_sejong_sme_target_marker_selects_target_rule() -> None:
    """'중소기업자간' 대상 표기는 대상 규칙(k 4·T 88)을 고른다(B4)."""
    cases = (
        (
            "소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
            SEJONG_SW_TARGET_ID,
        ),
        (
            "여객 육상운송용역(중소기업자간 경쟁제품) 적격심사 추정가격 5억원 미만",
            SEJONG_LT_TARGET_ID,
        ),
    )
    for method, rule_id in cases:
        result = _resolve(sucsfbid_mthd_nm=method, region_code="36", region_name="세종특별자치시")
        assert result.rule is not None, method
        assert result.rule.rule_id == rule_id, method
        resolution = resolve_score_params(result.rule, Decimal("400000000"), None, None)
        assert resolution.multiplier == Decimal("4"), method
        assert resolution.pass_threshold == Decimal("88"), method


def test_sejong_sme_unmarked_blocks_with_both_candidates() -> None:
    """표기가 없으면 자동 확정하지 않고 두 후보를 안내하며 사용자 선택을 요구한다(B4)."""
    cases = (
        (
            "소프트웨어용역 적격심사 추정가격 5억원 미만",
            SEJONG_SW_NON_TARGET_ID,
            SEJONG_SW_TARGET_ID,
        ),
        (
            "화물 육상운송용역 적격심사 추정가격 5억원 미만",
            SEJONG_LT_NON_TARGET_ID,
            SEJONG_LT_TARGET_ID,
        ),
    )
    for method, non_target_id, target_id in cases:
        result = _resolve(sucsfbid_mthd_nm=method, region_code="36", region_name="세종특별자치시")
        assert result.rule is None, method
        assert result.is_blocked is True, method
        assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED, method
        joined = " ".join(result.warnings)
        assert non_target_id in joined, method
        assert target_id in joined, method
        assert "local_service_type" in (result.block_reason_message or ""), method


def test_sejong_sme_marker_in_announcement_name_selects_target() -> None:
    """낙찰방법명에 표기가 없어도 공고명의 '중소기업자간' 이 대상 규칙을 고른다(B4)."""
    result = _resolve(
        sucsfbid_mthd_nm="화물 육상운송용역 적격심사 추정가격 5억원 미만",
        region_code="36",
        region_name="세종특별자치시",
        raw_data={"bidNtceNm": "2026년 중소기업자간 경쟁제품 육상운송 용역"},
    )
    assert result.rule is not None
    assert result.rule.rule_id == SEJONG_LT_TARGET_ID


def test_sejong_sme_non_target_in_announcement_name_beats_method_target() -> None:
    """공고명의 '비대상' 이 낙찰방법명의 대상 표기보다 우선한다(B1)."""
    result = _resolve(
        sucsfbid_mthd_nm=(
            "화물 육상운송용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만"
        ),
        region_code="36",
        region_name="세종특별자치시",
        raw_data={"bidNtceNm": "중소기업자간 경쟁제품 비대상 육상운송 용역"},
    )
    assert result.rule is not None
    assert result.rule.rule_id == SEJONG_LT_NON_TARGET_ID


def test_sejong_sme_user_selection_overrides_marker() -> None:
    """사용자가 고른 세부유형은 표기와 무관하게 그 규칙을 쓴다(D5)."""
    target = _resolve(
        sucsfbid_mthd_nm="소프트웨어용역 적격심사 추정가격 5억원 미만",
        region_code="36",
        region_name="세종특별자치시",
        local_service_type="SW_SME",
    )
    assert target.rule is not None
    assert target.rule.rule_id == SEJONG_SW_TARGET_ID
    non_target = _resolve(
        sucsfbid_mthd_nm="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
        region_code="36",
        region_name="세종특별자치시",
        local_service_type="SW",
    )
    assert non_target.rule is not None
    assert non_target.rule.rule_id == SEJONG_SW_NON_TARGET_ID


def test_daegu_simple_labor_threshold_stays_85() -> None:
    """대구 단순노무 별표 통과점수는 조건 없이 85 그대로다."""
    result = _resolve(
        sucsfbid_mthd_nm="단순노무용역 적격심사 추정가격 5억원 이상",
        region_code="27",
        region_name="대구광역시",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_DAEGU_20260511_ATTACH_01"
    assert resolve_score_params(result.rule, Decimal("300000000"), None, None).pass_threshold == (
        Decimal("85")
    )
