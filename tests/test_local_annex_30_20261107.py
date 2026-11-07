"""D34(A) 시·도 세부유형 별표 규칙 회귀 시험.

정본: docs/analysis/local_general_fallback_source_check_20261107.md 1.2·1.3·2.2·3절.
값 출처는 같은 문서가 인용한 data/sources/qualification/files/ 아래 시·도 원문입니다.

- 서울 보험용역(별표 1 5절)과 전북 폐기물처리용역(별표 3)의 낙찰하한율은 원문에
  인쇄되지 않아 별표 인쇄값(B·k·기준비율·통과점수)을 원문 산식에 대입해 산출했습니다.
- 대전 폐기물처리용역과 강원 폐기물처리용역의 낙찰하한율은 원문 인쇄값입니다.
- 경남 정보통신용역(별표 3)은 복사된 원문에 본문이 없어 등록하지 않았습니다.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from src.app.services.evaluation_rules import (
    LOCAL_RULES,
    EvaluationRule,
    _select_local_rule,
    resolve_evaluation_rule_from_raw_data,
    resolve_score_params,
    select_price_band,
)

SEOUL_INSURANCE_ID = "SERVC_LOCAL_SEOUL_20240812_ATTACH_01_5"
SEOUL_GENERAL_ID = "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"
SEOUL_SIMPLE_LABOR_ID = "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR"
DAEJEON_WASTE_ID = "SERVC_LOCAL_DAEJEON_20260101_ATTACH_1_3"
DAEJEON_SIMPLE_LABOR_ID = "SERVC_LOCAL_DAEJEON_20260101_SIMPLE_LABOR"
GANGWON_WASTE_ID = "SERVC_LOCAL_GANGWON_20230611_ATTACH_02"
GANGWON_SIMPLE_LABOR_ID = "SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR"
JEONBUK_WASTE_ID = "SERVC_LOCAL_JEONBUK_20240118_ATTACH_03"
JEONBUK_SIMPLE_LABOR_ID = "SERVC_LOCAL_JEONBUK_20240118_SIMPLE_LABOR"
GYEONGNAM_GENERAL_ID = "SERVC_LOCAL_GN_20230105_ATTACH_01"

WASTE_BANDS: tuple[tuple[str, str, str], ...] = (
    ("90", "20", "87.745"),
    ("70", "4", "86.745"),
    ("50", "2", "85.495"),
    ("30", "1", "77.995"),
    ("30", "1", "72.995"),
)


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def _resolve(region_code: str, region_name: str, raw: dict[str, str]):
    return resolve_evaluation_rule_from_raw_data(
        "Servc",
        raw,
        institution_regime="LOCAL",
        region_code=region_code,
        region_name=region_name,
        estimated_price=Decimal(raw["presmptPrce"]),
    )


# --------------------------------------------------------------------------- #
# 1. 새 세부유형 공고가 새 규칙으로 간다
# --------------------------------------------------------------------------- #

NEW_RULE_CASES = (
    (
        "11",
        "서울특별시",
        {
            "dminsttNm": "서울특별시 용산구",
            "dminsttCd": "3010000",
            "bidNtceDt": "2025-11-19 13:38:20",
            "sucsfbidMthdNm": "적격심사제-보험용역 적격심사 추정가격 5억원이상",
            "presmptPrce": "778762380",
            "pubPrcrmntMidClsfcNm": "보험서비스",
            "pubPrcrmntClsfcNm": "단체보험",
            "sucsfbidLwltRate": "47.995",
        },
        SEOUL_INSURANCE_ID,
    ),
    (
        "30",
        "대전광역시",
        {
            "dminsttNm": "대전광역시 건설관리본부",
            "dminsttCd": "6300207",
            "bidNtceDt": "2026-03-04 17:20:29",
            "sucsfbidMthdNm": "적격심사제-추정가격 2억원 미만인 용역",
            "presmptPrce": "177652727",
            "pubPrcrmntMidClsfcNm": "폐기물 처리",
            "pubPrcrmntClsfcNm": "건설폐기물처리서비스",
            "sucsfbidLwltRate": "87.745",
        },
        DAEJEON_WASTE_ID,
    ),
    (
        "51",
        "강원특별자치도",
        {
            "dminsttNm": "강원특별자치도 평창군",
            "dminsttCd": "5270000",
            "bidNtceDt": "2025-12-09 18:04:36",
            "sucsfbidMthdNm": "적격심사제-추정가격 15억원 미만 5억원 이상인 용역",
            "presmptPrce": "786394000",
            "pubPrcrmntMidClsfcNm": "폐기물 처리",
            "pubPrcrmntClsfcNm": "생활폐기물처리서비스",
            "sucsfbidLwltRate": "87.745",
        },
        GANGWON_WASTE_ID,
    ),
    (
        "52",
        "전북특별자치도",
        {
            "dminsttNm": "전북특별자치도 고창군",
            "dminsttCd": "4781000",
            "bidNtceDt": "2026-08-24 13:08:23",
            "sucsfbidMthdNm": "적격심사제-추정가격 30억원 미만 15억원 이상인 용역",
            "presmptPrce": "2949481818",
            "pubPrcrmntMidClsfcNm": "폐기물 처리",
            "pubPrcrmntClsfcNm": "건설폐기물처리서비스",
            "sucsfbidLwltRate": "82.995",
        },
        JEONBUK_WASTE_ID,
    ),
)


@pytest.mark.parametrize(("region_code", "region_name", "raw", "rule_id"), NEW_RULE_CASES)
def test_new_service_type_uses_new_rule(
    region_code: str, region_name: str, raw: dict[str, str], rule_id: str
) -> None:
    """새 세부유형 공고는 GENERAL 폴백이 아니라 새 별표 규칙으로 판정한다."""
    result = _resolve(region_code, region_name, raw)
    assert result.rule is not None, result.block_reason_code
    assert result.rule.rule_id == rule_id
    assert result.is_blocked is False
    assert not any("일반 별표를 적용했습니다" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 2. 같은 시·도의 다른 세부유형은 기존 규칙 그대로다
# --------------------------------------------------------------------------- #

UNCHANGED_SERVICE_CASES = (
    (
        "11",
        "서울특별시",
        {
            "dminsttNm": "서울특별시",
            "bidNtceDt": "2025-12-03 10:00:00",
            "sucsfbidMthdNm": "적격심사제-단순노무 일반용역 적격심사 추정가격 5억원미만",
            "presmptPrce": "400000000",
            "sucsfbidLwltRate": "87.745",
        },
        SEOUL_SIMPLE_LABOR_ID,
    ),
    (
        "30",
        "대전광역시",
        {
            "dminsttNm": "대전광역시",
            "bidNtceDt": "2026-03-03 10:00:00",
            "sucsfbidMthdNm": "적격심사제-단순노무 일반용역 적격심사 추정가격 5억원미만",
            "presmptPrce": "400000000",
            "sucsfbidLwltRate": "87.745",
        },
        DAEJEON_SIMPLE_LABOR_ID,
    ),
    (
        "51",
        "강원특별자치도",
        {
            "dminsttNm": "강원특별자치도",
            "bidNtceDt": "2025-12-03 10:00:00",
            "sucsfbidMthdNm": "적격심사제-단순노무 일반용역 적격심사 추정가격 5억원미만",
            "presmptPrce": "400000000",
            "sucsfbidLwltRate": "87.745",
        },
        GANGWON_SIMPLE_LABOR_ID,
    ),
    (
        "52",
        "전북특별자치도",
        {
            "dminsttNm": "전북특별자치도",
            "bidNtceDt": "2025-12-03 10:00:00",
            "sucsfbidMthdNm": "적격심사제-단순노무 일반용역 적격심사 추정가격 5억원미만",
            "presmptPrce": "400000000",
            "sucsfbidLwltRate": "87.745",
        },
        JEONBUK_SIMPLE_LABOR_ID,
    ),
)


@pytest.mark.parametrize(("region_code", "region_name", "raw", "rule_id"), UNCHANGED_SERVICE_CASES)
def test_other_service_type_keeps_existing_rule(
    region_code: str, region_name: str, raw: dict[str, str], rule_id: str
) -> None:
    """같은 시·도의 단순노무 판정은 새 규칙 추가 전과 같다."""
    result = _resolve(region_code, region_name, raw)
    assert result.rule is not None, result.block_reason_code
    assert result.rule.rule_id == rule_id


def test_seoul_general_rule_is_not_replaced() -> None:
    """서울 GENERAL 규칙은 그대로 남아 있고 새 보험 규칙과 별개다."""
    general = _rule(SEOUL_GENERAL_ID)
    insurance = _rule(SEOUL_INSURANCE_ID)
    assert general.service_type == "GENERAL"
    assert insurance.service_type == "INSURANCE"
    assert general.lwlt_rate != insurance.lwlt_rate


# --------------------------------------------------------------------------- #
# 3. 새 규칙의 값과 구간 경계
# --------------------------------------------------------------------------- #


def test_waste_rules_carry_printed_and_derived_values() -> None:
    """세 시·도 폐기물 규칙의 B·k·기준비율·통과점수·구간 하한율을 고정한다."""
    for rule_id in (DAEJEON_WASTE_ID, GANGWON_WASTE_ID, JEONBUK_WASTE_ID):
        rule = _rule(rule_id)
        assert rule.service_type == "WASTE", rule_id
        assert rule.lwlt_rate == Decimal("87.745"), rule_id
        assert [
            (band.max_price_score, band.multiplier, band.base_rate, band.lwlt_rate)
            for band in rule.price_bands
        ] == [
            (Decimal(b), Decimal(k), Decimal("0.88"), Decimal(rate)) for b, k, rate in WASTE_BANDS
        ], rule_id
        assert [(band.upper_bound, band.pass_threshold) for band in rule.threshold_bands] == [
            (Decimal("1000000000"), Decimal("95")),
            (Decimal("3000000000"), Decimal("90")),
            (None, Decimal("85")),
        ], rule_id


def test_seoul_insurance_rule_carries_printed_and_derived_values() -> None:
    """서울 보험 규칙은 B 60/70, 계수 0.375, 기준비율 88, 통과점수 85, 하한율 47.995 다."""
    rule = _rule(SEOUL_INSURANCE_ID)
    assert rule.service_type == "INSURANCE"
    assert rule.lwlt_rate == Decimal("47.995")
    assert [
        (band.upper_bound, band.max_price_score, band.multiplier, band.base_rate, band.lwlt_rate)
        for band in rule.price_bands
    ] == [
        (
            Decimal("500000000"),
            Decimal("70"),
            Decimal("0.375"),
            Decimal("0.88"),
            Decimal("47.995"),
        ),
        (None, Decimal("60"), Decimal("0.375"), Decimal("0.88"), Decimal("47.995")),
    ]
    assert [(band.upper_bound, band.pass_threshold) for band in rule.threshold_bands] == [
        (None, Decimal("85"))
    ]


def test_new_waste_rules_do_not_declare_cdw_exclusion() -> None:
    """건설폐기물 처리는 별도 Task 가 다루므로 새 폐기물 규칙에 cdw_exclusion 을 두지 않는다."""
    for rule_id in (DAEJEON_WASTE_ID, GANGWON_WASTE_ID, JEONBUK_WASTE_ID):
        assert _rule(rule_id).cdw_exclusion is None, rule_id


@pytest.mark.parametrize(
    ("rule_id", "price", "expected_b", "expected_k", "expected_t", "expected_lwlt"),
    [
        (SEOUL_INSURANCE_ID, "499999999", "70", "0.375", "85", "47.995"),
        (SEOUL_INSURANCE_ID, "500000000", "60", "0.375", "85", "47.995"),
        (DAEJEON_WASTE_ID, "199999999", "90", "20", "95", "87.745"),
        (DAEJEON_WASTE_ID, "200000000", "70", "4", "95", "86.745"),
        (DAEJEON_WASTE_ID, "499999999", "70", "4", "95", "86.745"),
        (DAEJEON_WASTE_ID, "500000000", "50", "2", "95", "85.495"),
        (DAEJEON_WASTE_ID, "999999999", "50", "2", "95", "85.495"),
        (DAEJEON_WASTE_ID, "1000000000", "30", "1", "90", "77.995"),
        (DAEJEON_WASTE_ID, "2999999999", "30", "1", "90", "77.995"),
        (DAEJEON_WASTE_ID, "3000000000", "30", "1", "85", "72.995"),
        (GANGWON_WASTE_ID, "199999999", "90", "20", "95", "87.745"),
        (GANGWON_WASTE_ID, "3000000000", "30", "1", "85", "72.995"),
        (JEONBUK_WASTE_ID, "199999999", "90", "20", "95", "87.745"),
        (JEONBUK_WASTE_ID, "3000000000", "30", "1", "85", "72.995"),
    ],
)
def test_band_boundary_selection(
    rule_id: str,
    price: str,
    expected_b: str,
    expected_k: str,
    expected_t: str,
    expected_lwlt: str,
) -> None:
    """경계 금액은 상위 구간(이상)에 속하고 B·k·T·하한율이 그 구간 값이다."""
    rule = _rule(rule_id)
    params = resolve_score_params(rule, Decimal(price), None, None)
    assert params.max_price_score == Decimal(expected_b)
    assert params.multiplier == Decimal(expected_k)
    assert params.pass_threshold == Decimal(expected_t)
    band, _, reason = select_price_band(rule.price_bands, Decimal(price))
    assert reason is None
    assert band is not None
    assert band.lwlt_rate == Decimal(expected_lwlt)


# --------------------------------------------------------------------------- #
# 4. 경남 정보통신용역은 원문 본문 미확보로 등록하지 않는다
# --------------------------------------------------------------------------- #


def test_gyeongnam_sw_remains_unregistered() -> None:
    """경남 SW 는 별표 3 본문이 없어 GENERAL 폴백을 유지한다."""
    raw = {
        "dminsttNm": "경상남도 통영시",
        "bidNtceDt": "2026-02-10 18:03:25",
        "sucsfbidMthdNm": (
            "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 "
            "추정가격 5억원 미만-추정가격 고시금액이상"
        ),
        "presmptPrce": "272727273",
        "sucsfbidLwltRate": "80.495",
    }
    rule, block_code, _, warnings = _select_local_rule(
        raw["sucsfbidMthdNm"], raw, sido_code="48", sido_name="경상남도"
    )
    assert block_code is None
    assert rule is not None
    assert rule.rule_id == GYEONGNAM_GENERAL_ID
    assert any("일반 별표를 적용했습니다" in warning for warning in warnings)
