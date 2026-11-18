"""대구광역시 학술연구 공고의 시·도 예규 적용범위 배제와 행안부 [별표 4] 구제 시험.

정본: `.orca/capsules/task_daegu_academic_scope_20261118/capsule.yaml`
- 대구광역시 일반용역 적격심사 세부기준 제2조 제1호는 "일반용역"을 "기술용역과 학술용역
  이외의 용역"으로 정의합니다. 학술연구 공고는 대구 예규의 적용 대상이 아닙니다.
  원문: `data/sources/qualification/files/daegu/d876df81b09d_elis_daegu_008.txt:156`,
  같은 조문의 예규 제223호 판
  `data/sources/qualification/files/daegu/856673076d70_elis_daegu_main.txt:158`.
- 그래서 조달분류가 학술연구인 대구 공고를 ACADEMIC 에서 GENERAL/UNRESOLVED 로 되돌려
  단순노무 단독 차단(D18)으로 보내지 않고, 행안부 예규 제2장의2 [별표 4] 학술연구용역
  띠로 계산합니다.
- 대구 이외 지역, 학술이 아닌 대구 공고, 단순노무 표기·선택 공고, 대구 폐기물 공고,
  국가계약 공고의 판정은 바뀌지 않습니다.

DB·Redis·.env 를 쓰지 않습니다.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
    LOCAL_ACADEMIC_SCOPE_EXCLUDED_REASON,
    LOCAL_SIMPLE_LABOR_ONLY_REASON,
    MOIS_ACADEMIC_BAND_WARNING,
    RULE_SCOPE_ALL,
    RuleResolutionResult,
    _select_local_rule,
    resolve_evaluation_rule_from_raw_data,
)

UNDER_1E_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E"
OVER_2E_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_OVER_2E"
OLD_OVER_2E_RULE_ID = "SERVC_LOCAL_MOIS_ACADEMIC_20240701_OVER_2E"
DAEGU_20260511_SIMPLE_LABOR_RULE_ID = "SERVC_LOCAL_DAEGU_20260511_ATTACH_01"
DAEGU_20260511_WASTE_RULE_ID = "SERVC_LOCAL_DAEGU_20260511_ATTACH_04"

METHOD_UNDER_1E = "적격심사제-추정가격 1억미만"
METHOD_OVER_2E = "적격심사제-추정가격 2억이상"
METHOD_MIXED = "적격심사제-추정가격 2억미만 1억이상"
METHOD_SIMPLE_LABOR = "적격심사제-단순노무용역 적격심사 추정가격 1억미만"
METHOD_WASTE = "적격심사제-폐기물처리용역 적격심사 추정가격 1억미만"
ACADEMIC_APP_STD = "학술연구용역 적격심사 세부기준"

DAEGU = ("27", "대구광역시")
INCHEON = ("28", "인천광역시")
CHUNGNAM = ("44", "충청남도")

NO_CLASS = ("", "", "")


def _resolve(
    method: str,
    *,
    announced: str = "2026-09-11 17:30:10",
    sido: tuple[str | None, str | None] = DAEGU,
    institution_name: str = "대구광역시 북구",
    institution_code: str = "3450000",
    classes: tuple[str, str, str] = ("연구조사서비스", "학술연구서비스", "기타연구조사서비스"),
    app_std: str | None = ACADEMIC_APP_STD,
    price: str = "61716364",
    lwlt_rate: str | None = "80.495",
    regime: str | None = "LOCAL",
    local_service_type: str | None = None,
    bid_no: str = "R26BK01724914",
    contract_method: str | None = "지방계약",
) -> RuleResolutionResult:
    raw_data: dict[str, Any] = {
        "bidNtceNo": bid_no,
        "bidNtceDt": announced,
        "sucsfbidMthdNm": method,
        "dminsttNm": institution_name,
        "dminsttCd": institution_code,
        "pubPrcrmntLrgClsfcNm": classes[0],
        "pubPrcrmntMidClsfcNm": classes[1],
        "pubPrcrmntClsfcNm": classes[2],
        "presmptPrce": price,
    }
    if contract_method is not None:
        raw_data["cntrctCnclsMthdNm"] = contract_method
    if app_std is not None:
        raw_data["sucsfbidMthdAppStd"] = app_std
    if lwlt_rate is not None:
        raw_data["sucsfbidLwltRate"] = lwlt_rate
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw_data,
        institution_regime=regime,
        region_code=sido[0],
        region_name=sido[1],
        local_service_type=local_service_type,
        estimated_price=Decimal(price),
    )


def _select_local(
    method: str,
    *,
    sido: tuple[str | None, str | None] = DAEGU,
    classes: tuple[str, str, str] = ("연구조사서비스", "학술연구서비스", "기타연구조사서비스"),
    announced: str = "2026-09-11 17:30:10",
):
    raw_data = {
        "bidNtceDt": announced,
        "sucsfbidMthdNm": method,
        "pubPrcrmntLrgClsfcNm": classes[0],
        "pubPrcrmntMidClsfcNm": classes[1],
        "pubPrcrmntClsfcNm": classes[2],
    }
    return _select_local_rule(
        method,
        raw_data,
        sido_code=sido[0],
        sido_name=sido[1],
        announced=date.fromisoformat(announced[:10]),
    )


# --------------------------------------------------------------------------- #
# 1. 대표 사례 2건: 대구 + 조달분류 학술연구 -> 행안부 [별표 4] 1억미만
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    (
        "bid_no",
        "institution_name",
        "institution_code",
        "announced",
        "price",
        "class_name",
    ),
    [
        (
            "R26BK01270603",
            "대구광역시 중구",
            "3410000",
            "2026-01-15 15:58:31",
            "45454545",
            "인력개발및교육연구조사서비스",
        ),
        (
            "R26BK01724914",
            "대구광역시 북구",
            "3450000",
            "2026-09-11 17:30:10",
            "61716364",
            "건설및지역개발연구조사서비스",
        ),
    ],
)
def test_daegu_academic_under_1e_resolves_to_mois_band(
    bid_no: str,
    institution_name: str,
    institution_code: str,
    announced: str,
    price: str,
    class_name: str,
) -> None:
    """대구 예규가 학술용역을 제외하므로 단순노무 단독 차단 대신 행안부 띠로 계산한다."""
    result = _resolve(
        METHOD_UNDER_1E,
        announced=announced,
        institution_name=institution_name,
        institution_code=institution_code,
        classes=("연구조사서비스", "학술연구서비스", class_name),
        price=price,
        bid_no=bid_no,
    )

    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == UNDER_1E_RULE_ID
    assert result.rule.max_price_score == Decimal("65")
    assert result.rule.multiplier == Decimal("2")
    assert result.rule.base_rate == Decimal("0.88")
    assert result.rule.pass_threshold == Decimal("85")
    assert result.effective_lwlt_rate == Decimal("80.495")
    assert result.scope_stage == RULE_SCOPE_ALL
    assert MOIS_ACADEMIC_BAND_WARNING in result.warnings


def test_daegu_academic_over_2e_uses_over_2e_column() -> None:
    """같은 조건의 2억이상 공고는 [별표 4] 2억이상 열(B=30)로 계산한다."""
    result = _resolve(
        METHOD_OVER_2E,
        classes=("연구조사서비스", "학술연구서비스", "수자원연구조사서비스"),
        price="363635455",
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == OVER_2E_RULE_ID
    assert result.rule.max_price_score == Decimal("30")


def test_daegu_academic_283_rule_resolves_before_20250701() -> None:
    """제283호 시행 이후 공고는 제283호 [별표 4] 규칙으로 계산한다.

    대표 사례 R25BK00801493(대구광역시, 2025-04-22, 추정가격 2억이상)이 이 형태입니다.
    """
    result = _resolve(
        METHOD_OVER_2E,
        announced="2025-04-22 10:05:26",
        institution_name="대구광역시",
        institution_code="6270000",
        classes=("연구조사서비스", "학술연구서비스", "수자원연구조사서비스"),
        price="363635455",
        bid_no="R25BK00801493",
    )

    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == OLD_OVER_2E_RULE_ID


# --------------------------------------------------------------------------- #
# 2. 경계: 대구 이외 지역은 새 경로를 타지 않는다
# --------------------------------------------------------------------------- #


def test_other_region_academic_keeps_previous_local_decision() -> None:
    """대구가 아닌 지역은 ACADEMIC 을 GENERAL/UNRESOLVED 로 되돌리는 종전 판정을 유지한다."""
    incheon_selected, incheon_code, incheon_reason, _ = _select_local(METHOD_UNDER_1E, sido=INCHEON)
    assert incheon_selected is None
    assert incheon_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert incheon_reason != LOCAL_ACADEMIC_SCOPE_EXCLUDED_REASON

    chungnam_selected, chungnam_code, chungnam_reason, _ = _select_local(
        METHOD_UNDER_1E, sido=CHUNGNAM
    )
    assert chungnam_selected is None
    assert chungnam_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert chungnam_reason != LOCAL_ACADEMIC_SCOPE_EXCLUDED_REASON

    for sido in (INCHEON, CHUNGNAM):
        result = _resolve(
            METHOD_UNDER_1E,
            sido=sido,
            institution_name=f"{sido[1]} 수요기관",
        )
        assert result.is_blocked is False
        assert result.rule is not None
        assert result.rule.rule_id == UNDER_1E_RULE_ID


def test_daegu_selection_returns_scope_excluded_reason() -> None:
    """대구 학술 공고의 시·도 선택은 적용범위 배제 사유로 LOCAL_RULE_NOT_FOUND 를 돌려준다."""
    selected, code, reason, warnings = _select_local(METHOD_UNDER_1E)

    assert selected is None
    assert code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert reason == LOCAL_ACADEMIC_SCOPE_EXCLUDED_REASON
    assert reason != LOCAL_SIMPLE_LABOR_ONLY_REASON
    assert warnings == []


# --------------------------------------------------------------------------- #
# 3. 경계: 단순노무 표기·선택, 폐기물, 학술이 아닌 대구 공고는 그대로다
# --------------------------------------------------------------------------- #


def test_daegu_simple_labor_method_is_unchanged() -> None:
    """낙찰방법명에 '단순노무' 가 있으면 종전처럼 단순노무 별표로 확정한다."""
    result = _resolve(METHOD_SIMPLE_LABOR)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == DAEGU_20260511_SIMPLE_LABOR_RULE_ID


def test_daegu_user_selected_simple_labor_is_unchanged() -> None:
    """사용자가 SIMPLE_LABOR 를 고르면 조달분류 학술 표지보다 사용자 선택이 우선한다."""
    result = _resolve(METHOD_UNDER_1E, local_service_type="SIMPLE_LABOR")

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == DAEGU_20260511_SIMPLE_LABOR_RULE_ID


def test_daegu_waste_is_unchanged() -> None:
    """폐기물 표기는 종전처럼 대구 폐기물 별표로 계산한다."""
    result = _resolve(
        METHOD_WASTE,
        classes=("폐기물관리서비스", "폐기물처리서비스", "생활폐기물처리서비스"),
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == DAEGU_20260511_WASTE_RULE_ID


def test_daegu_non_academic_general_keeps_simple_labor_only_block() -> None:
    """조달분류가 학술이 아닌 대구 일반 공고의 D18 차단은 그대로다."""
    result = _resolve(
        METHOD_UNDER_1E,
        classes=NO_CLASS,
        app_std=None,
        lwlt_rate=None,
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.block_reason_message == LOCAL_SIMPLE_LABOR_ONLY_REASON
    assert result.rule is None


def test_daegu_academic_band_only_method_keeps_simple_labor_only_block() -> None:
    """'2억미만 1억이상' 띠 표기는 기준 문서가 갈려 종전 D18 차단을 유지한다."""
    result = _resolve(METHOD_MIXED)

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.block_reason_message == LOCAL_SIMPLE_LABOR_ONLY_REASON


# --------------------------------------------------------------------------- #
# 4. 경계: 국가계약 공고는 행안부 학술 띠 구제 대상이 아니다
# --------------------------------------------------------------------------- #


def test_daegu_academic_national_regime_is_not_rescued() -> None:
    """국가계약 공고는 시·도 경로도 행안부 학술 띠 구제도 타지 않는다."""
    result = _resolve(METHOD_UNDER_1E, regime="NATIONAL", contract_method=None)

    assert result.contract_regime == "NATIONAL"
    assert result.rule is None or result.rule.rule_id not in (
        UNDER_1E_RULE_ID,
        OVER_2E_RULE_ID,
    )
