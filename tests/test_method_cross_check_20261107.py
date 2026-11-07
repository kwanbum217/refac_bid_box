"""낙찰방법명·조달분류 교차 확인과 띠 표기 규칙 선택 시험 (2026-11-07 결정).

정본:
 - `.orca/capsules/task_method_cross_check_20261107/capsule.yaml`
 - `docs/analysis/decision_backlog_20261107.md` D16·D17·D18·D19·D21·D24·D25
 - `docs/analysis/method_name_mismatch_trace_20261107.md` 1.1·3.2절
 - `docs/analysis/not_computable_9_trace_20261107.md` 2.2·3.7절

고정하는 결정:
 (a) 조달청 경로에서 낙찰방법명이 화물인데 조달분류가 여객이면 여객 규칙으로 교정한다(D16 B).
 (b) 교정 결과 여객 '고시금액미만' 띠로 떨어지면 다른 구간 규칙으로 근사하지 않고
     차단한다(D17 A).
 (c) 여객 낙찰방법명 + 화물 조달분류는 교정하지 않는다(D19 A). 시·도 경로도 교정하지
     않는다(D21 A).
 (d) 시·도 세부유형 UNRESOLVED 에서 GENERAL 후보가 없어 SIMPLE_LABOR 단독 후보만 남으면
     자동 확정하지 않고 차단한다(D18 B).
 (e) 전남 일반용역 2억미만 띠 표기 공고는 조달청 '추정가격 2억원 미만인 용역' 규칙으로
     준용한다(D24).
 (f) '2억미만 1억이상' 띠는 조달분류가 학술연구 계열이면 attachment_regime 없이도 행안부
     [별표 4] 학술연구용역 해당 열로 확정한다(D25).

DB·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
    BLOCK_CODE_RULE_NOT_FOUND,
    JEONNAM_PPS_FALLBACK_WARNING,
    LOCAL_SIMPLE_LABOR_ONLY_REASON,
    MOIS_ACADEMIC_BAND_WARNING,
    PASSENGER_METHOD_CORRECTION_WARNING,
    RULE_SCOPE_ALL,
    RULE_SCOPE_REGION,
    correct_passenger_method_name,
    resolve_evaluation_rule,
)

CATEGORY = "Servc"
PREARNG = "복수예가"

METHOD_FREIGHT_UNDER_5E = "적격심사제-화물 육상운송용역 적격심사 추정가격 5억원미만"
METHOD_FREIGHT_ABOVE_5E = "적격심사제-화물 육상운송용역 적격심사 추정가격 5억원이상"
METHOD_FREIGHT_NOTICE_UNDER = "적격심사제-화물 육상운송용역 적격심사 추정가격 고시금액미만"
METHOD_FREIGHT_5E_UNDER_NOTICE_ABOVE = (
    "적격심사제-화물 육상운송용역 적격심사 추정가격 5억원미만-추정가격 고시금액이상"
)
METHOD_PASSENGER_UNDER_5E = "적격심사제-여객 육상운송용역 적격심사 추정가격 5억원미만"
METHOD_PASSENGER_NOTICE_UNDER = "적격심사제-여객 육상운송용역 적격심사 추정가격 고시금액미만"
METHOD_BAND_1E_2E = "적격심사제-추정가격 2억미만 1억이상"
METHOD_UNDER_1E = "적격심사제-추정가격 1억미만"

CLASS_PASSENGER = {"pubPrcrmntClsfcNm": "도로여객운송서비스"}
CLASS_FREIGHT = {"pubPrcrmntClsfcNm": "도로화물운송서비스"}
CLASS_ACADEMIC = {
    "pubPrcrmntLrgClsfcNm": "연구조사서비스",
    "pubPrcrmntMidClsfcNm": "학술연구서비스",
    "pubPrcrmntClsfcNm": "교통연구조사서비스",
}
CLASS_LAUNDRY = {
    "pubPrcrmntLrgClsfcNm": "행사관리 및 기타 사업 지원서비스",
    "pubPrcrmntMidClsfcNm": "기타",
    "pubPrcrmntClsfcNm": "세탁서비스",
}

PASSENGER_RULE_20260727 = "SERVC_QUAL_POST_20260727_ATTACH_03"
PASSENGER_RULE_20260727_HIGH = "SERVC_QUAL_POST_20260727_ATTACH_03_HIGH"
PASSENGER_RULE_20250901 = "SERVC_QUAL_PRE_20250901_ATTACH_03"
FREIGHT_RULE_20260526 = "SERVC_QUAL_POST_20260526_ATTACH_11"
FREIGHT_RULE_20250901 = "SERVC_QUAL_PRE_20250901_ATTACH_10"
MOIS_ACADEMIC_1E_2E = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E"
PPS_GENERAL_UNDER_2E = "SERVC_QUAL_POST_20260526_ATTACH_12"

DAEGU = ("27", "대구광역시")
JEONNAM_LEGACY = ("46", "전라남도")
MERGED = ("12", "전남광주통합특별시")


def _resolve(
    method: str,
    *,
    raw_data: dict[str, object] | None = None,
    contract_regime: str | None = None,
    region_code: str | None = None,
    region_name: str | None = None,
    bid_ntce_dt: str = "2026-09-01",
    institution_name: str | None = None,
    estimated_price: str | None = None,
    attachment_regime: str | None = None,
):
    return resolve_evaluation_rule(
        category=CATEGORY,
        prearng_prce_dcsn_mthd_nm=PREARNG,
        sucsfbid_mthd_nm=method,
        contract_regime=contract_regime,
        region_code=region_code,
        region_name=region_name,
        bid_ntce_dt=bid_ntce_dt,
        institution_name=institution_name,
        estimated_price=estimated_price,
        attachment_regime=attachment_regime,
        raw_data=raw_data,
    )


# --------------------------------------------------------------------------- #
# (a) 화물 낙찰방법명 + 여객 조달분류 -> 여객 규칙 (D16 B, D19 A, D21 A)
# --------------------------------------------------------------------------- #


def test_correct_passenger_method_name_rewrites_freight_to_passenger() -> None:
    corrected, changed = correct_passenger_method_name(METHOD_FREIGHT_ABOVE_5E, CLASS_PASSENGER)
    assert changed is True
    assert corrected == ("적격심사제-여객 육상운송용역 적격심사 추정가격 5억원이상")


@pytest.mark.parametrize(
    ("method", "raw_data", "expected_changed"),
    [
        # 여객 낙찰방법명 + 화물 조달분류는 역방향이라 교정하지 않는다(D19 A).
        (METHOD_PASSENGER_UNDER_5E, CLASS_FREIGHT, False),
        # 조달분류가 여객 표기를 담지 않으면 교정하지 않는다.
        (METHOD_FREIGHT_UNDER_5E, CLASS_FREIGHT, False),
        (METHOD_FREIGHT_UNDER_5E, None, False),
        # 낙찰방법명에 여객이 이미 있으면 교정하지 않는다.
        (METHOD_PASSENGER_NOTICE_UNDER, CLASS_PASSENGER, False),
    ],
)
def test_correct_passenger_method_name_leaves_other_cases(
    method: str, raw_data: dict[str, object] | None, expected_changed: bool
) -> None:
    _, changed = correct_passenger_method_name(method, raw_data)
    assert changed is expected_changed


@pytest.mark.parametrize(
    ("method", "bid_ntce_dt", "expected_rule"),
    [
        # 2026-07-27 이후 공고는 제2026-390호 벌의 여객 규칙으로 간다.
        (METHOD_FREIGHT_ABOVE_5E, "2026-10-07", PASSENGER_RULE_20260727_HIGH),
        (METHOD_FREIGHT_UNDER_5E, "2026-10-07", PASSENGER_RULE_20260727),
        (
            METHOD_FREIGHT_5E_UNDER_NOTICE_ABOVE,
            "2026-10-07",
            PASSENGER_RULE_20260727,
        ),
        # 그 이전 공고는 개정 전 여객 규칙으로 간다.
        (METHOD_FREIGHT_5E_UNDER_NOTICE_ABOVE, "2026-02-09", PASSENGER_RULE_20250901),
    ],
)
def test_freight_method_with_passenger_class_uses_passenger_rule(
    method: str, bid_ntce_dt: str, expected_rule: str
) -> None:
    result = _resolve(method, raw_data=CLASS_PASSENGER, bid_ntce_dt=bid_ntce_dt)
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == expected_rule
    assert result.rule.service_type == "PASSENGER_TRANSPORT"
    assert result.scope_stage == RULE_SCOPE_ALL
    assert PASSENGER_METHOD_CORRECTION_WARNING in result.warnings


def test_freight_method_without_passenger_class_keeps_freight_rule() -> None:
    result = _resolve(METHOD_FREIGHT_ABOVE_5E, raw_data=CLASS_FREIGHT, bid_ntce_dt="2026-10-07")
    assert result.rule is not None
    assert result.rule.rule_id == FREIGHT_RULE_20260526
    assert PASSENGER_METHOD_CORRECTION_WARNING not in result.warnings


def test_passenger_method_with_freight_class_is_not_corrected() -> None:
    """역방향(여객->화물)은 교정하지 않는다(D19 A)."""
    result = _resolve(
        METHOD_PASSENGER_NOTICE_UNDER, raw_data=CLASS_FREIGHT, bid_ntce_dt="2026-10-07"
    )
    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert PASSENGER_METHOD_CORRECTION_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (b) 여객 고시금액미만 규칙 공백 -> 차단 유지 (D17 A)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("bid_ntce_dt", ["2026-02-20", "2026-10-07"])
def test_passenger_notice_under_band_stays_blocked(bid_ntce_dt: str) -> None:
    """여객 별표에는 '고시금액 미만' 구간이 없어 다른 구간으로 근사하지 않는다."""
    result = _resolve(
        METHOD_FREIGHT_NOTICE_UNDER, raw_data=CLASS_PASSENGER, bid_ntce_dt=bid_ntce_dt
    )
    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND
    assert result.effective_lwlt_rate is None


def test_passenger_notice_under_band_block_message_names_the_gap() -> None:
    """교정 사실과 여객 두 구간만 있다는 사실을 사유에 남긴다."""
    result = _resolve(
        METHOD_FREIGHT_NOTICE_UNDER, raw_data=CLASS_PASSENGER, bid_ntce_dt="2026-02-20"
    )
    message = result.block_reason_message or ""
    assert "여객" in message
    assert "5억원" in message
    assert "근사하지 않습니다" in message


def test_passenger_rule_has_no_notice_amount_band() -> None:
    """여객 규칙 표에 고시금액 구간이 없다는 전제를 함께 고정한다."""
    from src.app.services.evaluation_rules import (
        PASSENGER_NOTICE_ABOVE_RULES,
        POST_20260526_RULES,
        POST_20260727_RULES,
    )

    passenger_rules = [
        rule
        for rule in (*POST_20260526_RULES, *POST_20260727_RULES, *PASSENGER_NOTICE_ABOVE_RULES)
        if rule.service_type == "PASSENGER_TRANSPORT"
    ]
    assert passenger_rules
    for rule in passenger_rules:
        assert "고시금액" not in rule.table_name, rule.rule_id


# --------------------------------------------------------------------------- #
# (c) 시·도 경로는 교차 확인 대상이 아니다 (D21 A)
# --------------------------------------------------------------------------- #


def test_local_path_is_not_crossed_checked() -> None:
    """시·도 경로는 화물/여객을 같은 LAND_TRANSPORT 로 매핑하므로 교정하지 않는다."""
    result = _resolve(
        METHOD_FREIGHT_ABOVE_5E,
        raw_data=CLASS_PASSENGER,
        contract_regime="LOCAL",
        region_code="41",
        region_name="경기도",
        bid_ntce_dt="2026-09-01",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_GG_20250808_ATTACH_1_4"
    assert result.rule.service_type == "LAND_TRANSPORT"
    assert PASSENGER_METHOD_CORRECTION_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (d) 시·도 UNRESOLVED + SIMPLE_LABOR 단독 -> 차단 (D18 B)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("method", [METHOD_UNDER_1E, METHOD_BAND_1E_2E])
def test_daegu_simple_labor_only_candidate_blocks(method: str) -> None:
    """대구는 GENERAL 별표가 없어 SIMPLE_LABOR 단독 후보가 남는다. 자동 확정하지 않는다."""
    result = _resolve(
        method,
        raw_data=CLASS_ACADEMIC,
        contract_regime="LOCAL",
        region_code=DAEGU[0],
        region_name=DAEGU[1],
        bid_ntce_dt="2026-09-11",
    )
    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.block_reason_message == LOCAL_SIMPLE_LABOR_ONLY_REASON
    joined = " ".join(result.warnings)
    assert "SERVC_LOCAL_DAEGU_" in joined
    assert "local_service_type" in (result.block_reason_message or "")


def test_daegu_simple_labor_marker_still_selects_simple_labor() -> None:
    """낙찰방법명에 '단순노무' 가 있으면 종전처럼 단순노무 별표로 확정한다."""
    result = _resolve(
        "단순노무용역 적격심사 추정가격 5억원 이상",
        contract_regime="LOCAL",
        region_code=DAEGU[0],
        region_name=DAEGU[1],
        bid_ntce_dt="2026-09-11",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_DAEGU_20260511_ATTACH_01"


def test_daegu_user_selection_still_resolves_simple_labor() -> None:
    """세부유형을 직접 고르면 차단되지 않는다."""
    result = resolve_evaluation_rule(
        category=CATEGORY,
        prearng_prce_dcsn_mthd_nm=PREARNG,
        sucsfbid_mthd_nm=METHOD_UNDER_1E,
        contract_regime="LOCAL",
        region_code=DAEGU[0],
        region_name=DAEGU[1],
        bid_ntce_dt="2026-09-11",
        local_service_type="SIMPLE_LABOR",
        raw_data=CLASS_ACADEMIC,
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_DAEGU_20260511_ATTACH_01"


# --------------------------------------------------------------------------- #
# (e) 전남 일반용역 2억미만 -> 조달청 ATTACH_12 준용 (D24)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("region_code", "region_name", "institution_name"),
    [
        # 통합 전 공고는 지역 코드가 46 으로 잡힌다.
        (JEONNAM_LEGACY[0], JEONNAM_LEGACY[1], "전라남도순천의료원"),
        # 통합 코드로만 잡히는 공고는 수요기관명으로 옛 계열을 확인한다.
        (MERGED[0], MERGED[1], "전라남도순천의료원"),
    ],
)
def test_jeonnam_general_band_uses_pps_under_2e(
    region_code: str, region_name: str, institution_name: str
) -> None:
    result = _resolve(
        METHOD_BAND_1E_2E,
        raw_data=CLASS_LAUNDRY,
        contract_regime="LOCAL",
        region_code=region_code,
        region_name=region_name,
        institution_name=institution_name,
        bid_ntce_dt="2026-06-12",
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == PPS_GENERAL_UNDER_2E
    assert result.rule.service_type == "GENERAL"
    assert result.effective_lwlt_rate == Decimal("87.745")
    assert result.scope_stage == RULE_SCOPE_ALL
    assert JEONNAM_PPS_FALLBACK_WARNING in result.warnings


def test_other_region_general_band_is_not_given_pps_under_2e() -> None:
    """전남만 조달청 준용 결정의 범위를 넘지 않는다(D15·D24)."""
    result = _resolve(
        METHOD_BAND_1E_2E,
        raw_data=CLASS_LAUNDRY,
        contract_regime="LOCAL",
        region_code="44",
        region_name="충청남도",
        institution_name="충청남도 태안군",
        bid_ntce_dt="2026-06-12",
    )
    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


def test_jeonnam_academic_band_is_not_given_pps_under_2e() -> None:
    """조달분류가 학술연구 계열이면 D25 학술 띠 확정이 먼저다."""
    result = _resolve(
        METHOD_BAND_1E_2E,
        raw_data=CLASS_ACADEMIC,
        contract_regime="LOCAL",
        region_code=JEONNAM_LEGACY[0],
        region_name=JEONNAM_LEGACY[1],
        institution_name="전남광주통합특별시 강진군",
        bid_ntce_dt="2026-02-06",
    )
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_ACADEMIC_1E_2E
    assert JEONNAM_PPS_FALLBACK_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# (f) 학술 띠 낙찰방법명 + 학술 조달분류 -> 학술 띠 규칙 (D25)
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("contract_regime", "sido", "institution_name", "blocked_before"),
    [
        # 계약 법령 미상(지방의료원)은 시·도 규칙을 시도하지 않는다.
        (None, (None, None), "강원도원주의료원", BLOCK_CODE_RULE_NOT_FOUND),
        (None, (None, None), "대구의료원", BLOCK_CODE_RULE_NOT_FOUND),
        (None, (None, None), "전북특별자치도 남원의료원", BLOCK_CODE_RULE_NOT_FOUND),
        # 시·도 규칙이 띠를 풀지 못한 LOCAL 공고도 학술 띠로 확정한다.
        ("LOCAL", JEONNAM_LEGACY, "전남광주통합특별시 강진군", BLOCK_CODE_RULE_NOT_FOUND),
    ],
)
def test_academic_class_confirms_band_without_attachment_regime(
    contract_regime: str | None,
    sido: tuple[str | None, str | None],
    institution_name: str,
    blocked_before: str,
) -> None:
    result = _resolve(
        METHOD_BAND_1E_2E,
        raw_data=CLASS_ACADEMIC,
        contract_regime=contract_regime,
        region_code=sido[0],
        region_name=sido[1],
        institution_name=institution_name,
        bid_ntce_dt="2026-02-06",
        attachment_regime=None,
    )
    assert result.is_blocked is False
    assert result.block_reason_code != blocked_before
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_ACADEMIC_1E_2E
    assert result.rule.max_price_score == Decimal("60")
    assert result.rule.pass_threshold == Decimal("85")
    assert result.scope_stage == RULE_SCOPE_ALL
    assert MOIS_ACADEMIC_BAND_WARNING in result.warnings


def test_academic_class_wins_over_jeonnam_pps_fallback() -> None:
    """학술 띠 확정과 전남 준용이 겹치면 학술 띠가 이긴다."""
    result = _resolve(
        METHOD_BAND_1E_2E,
        raw_data=CLASS_ACADEMIC,
        contract_regime="LOCAL",
        region_code=JEONNAM_LEGACY[0],
        region_name=JEONNAM_LEGACY[1],
        institution_name="전남광주통합특별시 강진군",
        bid_ntce_dt="2026-02-06",
    )
    assert result.rule is not None
    assert result.rule.rule_id == MOIS_ACADEMIC_1E_2E
    assert MOIS_ACADEMIC_BAND_WARNING in result.warnings


def test_band_without_academic_class_keeps_previous_judgment() -> None:
    """조달분류가 학술연구 계열이 아니면 종전 차단을 유지한다."""
    result = _resolve(
        METHOD_BAND_1E_2E,
        raw_data={"pubPrcrmntClsfcNm": "인력공급서비스"},
        contract_regime=None,
        bid_ntce_dt="2026-02-06",
    )
    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


def test_national_regime_is_not_given_mois_academic_rule() -> None:
    """행안부 예규는 지방계약 기준이라 국가계약 공고에는 적용하지 않는다."""
    result = _resolve(
        METHOD_BAND_1E_2E,
        raw_data=CLASS_ACADEMIC,
        contract_regime="NATIONAL",
        bid_ntce_dt="2026-02-06",
    )
    assert result.rule is None
    assert result.block_reason_code == BLOCK_CODE_RULE_NOT_FOUND


def test_user_selected_service_type_is_respected_over_academic_band() -> None:
    """사용자가 고른 세부유형이 있으면 시·도 규칙 확정이 먼저다."""
    result = resolve_evaluation_rule(
        category=CATEGORY,
        prearng_prce_dcsn_mthd_nm=PREARNG,
        sucsfbid_mthd_nm=METHOD_BAND_1E_2E,
        contract_regime="LOCAL",
        region_code=DAEGU[0],
        region_name=DAEGU[1],
        bid_ntce_dt="2026-09-11",
        local_service_type="SIMPLE_LABOR",
        raw_data=CLASS_ACADEMIC,
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_DAEGU_20260511_ATTACH_01"
    assert result.scope_stage == RULE_SCOPE_REGION
    assert MOIS_ACADEMIC_BAND_WARNING not in result.warnings
