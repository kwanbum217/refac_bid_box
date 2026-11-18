"""띠 표기 학술연구 공고의 LOCAL_RULE_NOT_FOUND 구제 정합화 시험.

정본: `.orca/capsules/task_academic_band_local_nf_20261118/capsule.yaml`

낙찰방법명이 '추정가격 2억미만 1억이상' 띠만 적은 학술연구 공고는 조달분류가
학술연구서비스 계열일 때만 행안부 예규 제2장의2 [별표 4] 학술연구용역 2억미만
1억이상 열로 확정합니다(D25). 이 구제가 조달청 기본 경로의 RULE_NOT_FOUND 에서만
실행되고 시·도 별표가 없는 LOCAL_RULE_NOT_FOUND 에서는 빠지던 비대칭을 없앱니다.

경계: 국가계약, 단순노무 단독·세부유형 미확정 차단, 학술이 아닌 띠 표기 공고,
전남 일반 띠(D24) 경로, 2025-07-01 이전 공고는 판정이 바뀌지 않습니다.

DB·.env·운영 Redis 를 쓰지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
    BLOCK_CODE_RULE_NOT_FOUND,
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    LOCAL_SIMPLE_LABOR_ONLY_REASON,
    MOIS_ACADEMIC_BAND_ATTACHMENT_ONLY_RULES,
    MOIS_ACADEMIC_BAND_WARNING,
    RULE_SCOPE_ALL,
    resolve_evaluation_rule_from_raw_data,
    select_mois_academic_band_rule,
)

RULE_ID_1E_2E = "SERVC_LOCAL_MOIS_ACADEMIC_20250701_1E_2E"
METHOD_MIXED = "적격심사제-추정가격 2억미만 1억이상"
METHOD_MIXED_REGIONAL = f"{METHOD_MIXED} - 지역업체참여"
METHOD_UNDER_1E = "적격심사제-추정가격 1억미만"

ACADEMIC_CLASSES = ("연구조사서비스", "학술연구서비스", "기타연구조사서비스")
EDUCATION_CLASSES = ("교육 및 전문직종/기술서비스", "교육서비스", "")
GENERAL_CLASSES = ("일반용역", "기타일반용역", "")

CHUNGNAM = ("44", "충청남도")
CHUNGBUK = ("43", "충청북도")
JNGJ = ("12", "전남광주통합특별시")
SEJONG = ("36", "세종특별자치시")
DAEGU = ("27", "대구광역시")
GYEONGGI = ("41", "경기도")
GYEONGBUK = ("47", "경상북도")
GYEONGNAM = ("48", "경상남도")
JEONNAM = ("46", "전라남도")

GYEONGGI_RULE_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_6"
GYEONGBUK_RULE_ID = "SERVC_LOCAL_GB_20241212_ATTACH_01"
GYEONGNAM_RULE_ID = "SERVC_LOCAL_GN_20230105_ATTACH_01"

# 대표 공고 4건. 공고일·수요기관·추정가격·공고 하한율은 공고 원문 값입니다.
REPRESENTATIVE = (
    (
        "R25BK00936613",
        "2025-07-01 19:14:44",
        JNGJ,
        "전남광주통합특별시 광주청사",
        "6130768",
        "143636364",
    ),
    (
        "R25BK01004727",
        "2025-08-11 17:56:26",
        JNGJ,
        "전남광주통합특별시 광주청사",
        "6130768",
        "181818182",
    ),
    ("R25BK01111217", "2025-10-23 17:24:48", CHUNGNAM, "충청남도 홍성군", "4600000", "153636364"),
    (
        "R25BK01130396",
        "2025-11-03 17:43:26",
        JNGJ,
        "전남광주통합특별시 광양시",
        "5800000",
        "153727273",
    ),
)


def _resolve(
    *,
    method: str = METHOD_MIXED,
    announced: str = "2025-09-10 10:00:00",
    sido: tuple[str | None, str | None] = CHUNGNAM,
    institution_name: str = "충청남도 보령시",
    institution_code: str = "4510000",
    classes: tuple[str, str, str] = ACADEMIC_CLASSES,
    regime: str | None = "LOCAL",
    price: str = "150000000",
    lwlt_rate: str | None = "80.495",
    app_std: str | None = "학술연구용역 적격심사 세부기준",
    bid_no: str = "R25BKTEST",
    contract_method: str | None = "지방계약",
):
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
    if lwlt_rate is not None:
        raw_data["sucsfbidLwltRate"] = lwlt_rate
    if app_std is not None:
        raw_data["sucsfbidMthdAppStd"] = app_std
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw_data,
        institution_regime=regime,
        region_code=sido[0],
        region_name=sido[1],
        estimated_price=Decimal(price),
    )


def _new_rule():
    rules = MOIS_ACADEMIC_BAND_ATTACHMENT_ONLY_RULES
    assert len(rules) == 1
    return rules[0]


# --------------------------------------------------------------------------- #
# 1. 대표 공고: 시·도 별표가 없는 LOCAL 띠 표기 학술 공고가 행안부 띠로 계산된다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("bid_no", "announced", "sido", "institution_name", "institution_code", "price"),
    REPRESENTATIVE,
)
def test_local_rule_not_found_band_academic_resolves_to_mois_rule(
    bid_no: str,
    announced: str,
    sido: tuple[str, str],
    institution_name: str,
    institution_code: str,
    price: str,
) -> None:
    result = _resolve(
        announced=announced,
        sido=sido,
        institution_name=institution_name,
        institution_code=institution_code,
        price=price,
        bid_no=bid_no,
    )

    assert result.is_blocked is False
    assert result.block_reason_code is None
    assert result.rule is not None
    assert result.rule.rule_id == RULE_ID_1E_2E
    assert result.rule.max_price_score == Decimal("60")
    assert result.rule.multiplier == Decimal("2")
    assert result.rule.base_rate == Decimal("0.88")
    assert result.rule.pass_threshold == Decimal("85")
    assert result.effective_lwlt_rate == Decimal("80.495")
    assert result.scope_stage == RULE_SCOPE_ALL
    assert MOIS_ACADEMIC_BAND_WARNING in result.warnings


def test_regional_participation_suffix_is_also_resolved() -> None:
    result = _resolve(
        method=METHOD_MIXED_REGIONAL, sido=JNGJ, institution_name="전남광주통합특별시 광주청사"
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == RULE_ID_1E_2E


def test_select_helper_still_requires_academic_classification() -> None:
    """D25 는 그대로다. 띠 표기만으로는 확정하지 않고 조달분류가 학술일 때만 돌려준다."""
    assert select_mois_academic_band_rule(METHOD_MIXED, None) is None
    assert (
        select_mois_academic_band_rule(
            METHOD_MIXED,
            {"pubPrcrmntMidClsfcNm": "일반용역"},
        )
        is None
    )
    rule = select_mois_academic_band_rule(
        METHOD_MIXED,
        {"pubPrcrmntMidClsfcNm": "학술연구서비스"},
    )
    assert rule is not None
    assert rule.rule_id == RULE_ID_1E_2E


# --------------------------------------------------------------------------- #
# 2. 경계: 2025-07-01 이전 공고는 종전 LOCAL_RULE_NOT_FOUND 를 유지한다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("sido", "institution_name", "institution_code", "announced"),
    [
        (CHUNGNAM, "충청남도 보령시", "4510000", "2025-01-31 17:52:37"),
        (JNGJ, "전남광주통합특별시 광주청사", "6130768", "2025-03-25 18:11:08"),
        (SEJONG, "세종특별자치시", "5690000", "2025-02-21 18:04:28"),
    ],
)
def test_before_mois_effective_date_keeps_local_rule_not_found(
    sido: tuple[str, str],
    institution_name: str,
    institution_code: str,
    announced: str,
) -> None:
    result = _resolve(
        announced=announced,
        sido=sido,
        institution_name=institution_name,
        institution_code=institution_code,
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert result.block_reason_code != BLOCK_CODE_RULE_REGIME_MISMATCH
    assert result.rule is None


def test_effective_date_boundary_is_inclusive() -> None:
    result = _resolve(
        announced="2025-07-01 00:00:00", sido=JNGJ, institution_name="전남광주통합특별시 광주청사"
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == RULE_ID_1E_2E


# --------------------------------------------------------------------------- #
# 3. 경계: 국가계약·단순노무·세부유형 미확정 차단은 그대로다
# --------------------------------------------------------------------------- #


def test_national_regime_is_not_rescued() -> None:
    result = _resolve(regime="NATIONAL", contract_method=None)

    assert result.block_reason_code in (BLOCK_CODE_RULE_NOT_FOUND, BLOCK_CODE_LOCAL_RULE_NOT_FOUND)
    assert result.rule is None


def test_daegu_simple_labor_only_block_is_unchanged() -> None:
    """대구 띠 표기 학술 공고는 단순노무 단독 후보 차단을 그대로 유지한다."""
    result = _resolve(sido=DAEGU, institution_name="대구광역시 중구", institution_code="3410000")

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.block_reason_message == LOCAL_SIMPLE_LABOR_ONLY_REASON
    assert result.rule is None


def test_local_service_type_unresolved_is_unchanged() -> None:
    """비학술 띠 표기의 세부유형 미확정 차단도 그대로다."""
    result = _resolve(
        classes=GENERAL_CLASSES,
        sido=CHUNGBUK,
        institution_name="충청북도 청주시",
        institution_code="5710000",
    )

    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert result.block_reason_message != LOCAL_SIMPLE_LABOR_ONLY_REASON
    assert result.rule is None


# --------------------------------------------------------------------------- #
# 4. 경계: 학술이 아닌 띠 표기 공고는 바뀌지 않는다
# --------------------------------------------------------------------------- #


def test_non_academic_band_keeps_previous_block() -> None:
    chungnam = _resolve(classes=GENERAL_CLASSES)
    assert chungnam.is_blocked is True
    assert chungnam.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert chungnam.rule is None

    education = _resolve(
        classes=EDUCATION_CLASSES,
        announced="2025-07-10 11:27:50",
        institution_name="충청남도 아산시",
        institution_code="4520000",
    )
    assert education.is_blocked is True
    assert education.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND
    assert education.rule is None


def test_jeonnam_general_band_path_is_unchanged() -> None:
    """전남 일반 띠(D24) 경로는 비학술 공고만 대상이라 학술 띠 구제와 겹치지 않는다."""
    result = _resolve(
        classes=GENERAL_CLASSES,
        sido=JEONNAM,
        institution_name="전라남도 무안군",
        institution_code="4960000",
    )

    assert result.rule is None or result.rule.rule_id != RULE_ID_1E_2E
    assert result.block_reason_code in (
        BLOCK_CODE_RULE_NOT_FOUND,
        BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
        BLOCK_CODE_RULE_REGIME_MISMATCH,
    )


# --------------------------------------------------------------------------- #
# 5. 경계: 시·도 자체 별표로 계산되던 공고는 그대로다
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize(
    ("sido", "institution_name", "institution_code", "rule_id"),
    [
        (GYEONGGI, "경기도 성남시", "3780000", GYEONGGI_RULE_ID),
        (GYEONGBUK, "경상북도 안동시", "5070000", GYEONGBUK_RULE_ID),
        (GYEONGNAM, "경상남도 창원시", "5670000", GYEONGNAM_RULE_ID),
    ],
)
def test_region_rule_is_not_overridden_by_mois_band(
    sido: tuple[str, str], institution_name: str, institution_code: str, rule_id: str
) -> None:
    result = _resolve(
        sido=sido, institution_name=institution_name, institution_code=institution_code
    )

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert MOIS_ACADEMIC_BAND_WARNING not in result.warnings


# --------------------------------------------------------------------------- #
# 6. 경계: RULE_NOT_FOUND 경로와 띠가 아닌 표기의 종전 동작은 그대로다
# --------------------------------------------------------------------------- #


def test_rule_not_found_path_still_resolves() -> None:
    result = _resolve(regime=None, contract_method=None)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == RULE_ID_1E_2E


def test_non_band_method_is_unchanged() -> None:
    result = _resolve(method=METHOD_UNDER_1E, classes=GENERAL_CLASSES)

    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_MOIS_ACADEMIC_20250701_UNDER_1E"


def test_rule_value_is_unchanged() -> None:
    rule = _new_rule()
    assert rule.rule_id == RULE_ID_1E_2E
    assert rule.effective_date == "2025-07-01"
    assert rule.superseded_date is None
    assert rule.max_price_score == Decimal("60")
    assert rule.lwlt_rate == Decimal("80.495")
    assert rule.pass_threshold == Decimal("85")
