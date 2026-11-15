"""광주광역시 일반용역 적격심사 세부기준 별표 1-2 소프트웨어용역 시험.

예규 제377호(시행 2022-11-15, 2026-07-16 폐지) 별표 1-2 의 입찰가격 배점한도와
별표 6 소프트웨어 행의 평점계수·낙찰하한율, 제11조제1항 통과점수를 확인합니다.
DB·Redis 에 연결하지 않습니다.
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.app.services.evaluation_rules import (
    BLOCK_CODE_RULE_REGIME_MISMATCH,
    RULE_SCOPE_REGION,
    resolve_evaluation_rule_from_raw_data,
    select_price_band,
    select_threshold_band,
)

RULE_ID = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2"
METRO_RULE_ID = "SERVC_LOCAL_GWANGJU_20221115_ATTACH_1_2_METRO_SW"
JNGJ_SW_RULE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_02"
MERGED_REGION_CODE = "12"
MERGED_REGION_NAME = "전남광주통합특별시"

# 2026-11-15 원문 확인 보고서 1·2번이 차단됐다고 적은 광주 소프트웨어 공고 2건입니다.
TARGET_1 = {
    "bidNtceNo": "R25BK01171487",
    "bidNtceNm": "2026년도 행정전산장비 및 네트워크장비 유지보수 용역",
    "bidNtceDt": "2025-11-21 19:46:55",
    "dminsttNm": "전남광주통합특별시 서구",
    "sucsfbidMthdNm": "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 추정가격 고시금액미만",
    "pubPrcrmntLrgClsfcNm": "ICT 서비스",
    "pubPrcrmntMidClsfcNm": "운영 및 유지관리",
    "pubPrcrmntClsfcNm": "소프트웨어유지및지원서비스",
    "presmptPrce": 151_083_655,
}
TARGET_2 = {
    "bidNtceNo": "R26BK01454418",
    "bidNtceNm": "(긴급)청사 간(광주↔전남) 전용 정보통신서비스 회선사업자 선정 용역",
    "bidNtceDt": "2026-04-09 15:55:31",
    "dminsttNm": "전남광주통합특별시 광주청사",
    "sucsfbidMthdNm": (
        "적격심사제-소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 "
        "추정가격 5억원 미만-추정가격 고시금액이상"
    ),
    "pubPrcrmntLrgClsfcNm": "정보통신방송서비스",
    "pubPrcrmntMidClsfcNm": "통신서비스",
    "pubPrcrmntClsfcNm": "유선통신서비스",
    "presmptPrce": 324_000_000,
}


def _raw(base: dict[str, Any], **overrides: Any) -> dict[str, Any]:
    data = dict(base)
    data.update(overrides)
    return data


def _resolve(
    raw_data: dict[str, Any],
    *,
    region_code: str = MERGED_REGION_CODE,
    region_name: str = MERGED_REGION_NAME,
):
    return resolve_evaluation_rule_from_raw_data(
        category="Servc",
        raw_data=raw_data,
        institution_regime="LOCAL",
        region_code=region_code,
        region_name=region_name,
        estimated_price=raw_data.get("presmptPrce"),
    )


def test_target_announcements_select_gwangju_software_rule() -> None:
    expected_ids = (RULE_ID, METRO_RULE_ID)
    for raw_data, expected_id in zip((TARGET_1, TARGET_2), expected_ids, strict=True):
        result = _resolve(raw_data)
        assert result.is_blocked is False, result.block_reason_message
        assert result.rule is not None
        assert result.rule.rule_id == expected_id
        assert result.scope_stage == RULE_SCOPE_REGION


def test_annex_bands_match_original_values() -> None:
    for expected_id, raw_data in ((RULE_ID, TARGET_1), (METRO_RULE_ID, TARGET_2)):
        result = _resolve(raw_data)
        rule = result.rule
        assert rule is not None
        assert rule.rule_id == expected_id
        assert rule.price_bands is not None

        expected = (
            (100_000_000, "90", "20", "87.745"),
            (200_000_000, "70", "4", "86.745"),
            (500_000_000, "50", "2", "85.495"),
            (600_000_000, "50", "2", "85.495"),
        )
        for price, max_score, multiplier, lwlt in expected:
            band, _, reason = select_price_band(rule.price_bands, Decimal(price))
            assert reason is None
            assert band is not None
            assert band.max_price_score == Decimal(max_score)
            assert band.multiplier == Decimal(multiplier)
            assert band.base_rate == Decimal("0.88")
            assert band.lwlt_rate == Decimal(lwlt)


def test_band_boundaries_belong_to_higher_band() -> None:
    result = _resolve(TARGET_1)
    rule = result.rule
    assert rule is not None
    assert rule.price_bands is not None

    at_200m, _, _ = select_price_band(rule.price_bands, Decimal("200000000"))
    at_500m, _, _ = select_price_band(rule.price_bands, Decimal("500000000"))
    assert at_200m is not None
    assert at_500m is not None
    assert at_200m.label == "5억원 미만 2억원 이상"
    assert at_200m.lwlt_rate == Decimal("86.745")
    assert at_500m.label == "추정가격 5억원 이상"
    assert at_500m.lwlt_rate == Decimal("85.495")


def test_effective_lwlt_rate_follows_price_band() -> None:
    result_1 = _resolve(TARGET_1)
    result_2 = _resolve(TARGET_2)
    assert result_1.effective_lwlt_rate == Decimal("87.745")
    assert result_2.effective_lwlt_rate == Decimal("86.745")


def test_pass_threshold_is_single_95() -> None:
    result = _resolve(TARGET_1)
    rule = result.rule
    assert rule is not None
    assert rule.threshold_bands is not None
    assert len(rule.threshold_bands) == 1
    band, _, reason = select_threshold_band(rule.threshold_bands, Decimal("151083655"))
    assert reason is None
    assert band is not None
    assert band.pass_threshold == Decimal("95")


def test_announcement_after_abolition_uses_merged_rule() -> None:
    raw_data = _raw(TARGET_2, bidNtceDt="2026-07-16 00:00:00")
    result = _resolve(raw_data)
    assert result.is_blocked is False, result.block_reason_message
    assert result.rule is not None
    assert result.rule.rule_id == JNGJ_SW_RULE_ID
    assert result.rule.rule_id != RULE_ID


def test_announcement_before_effective_date_is_blocked() -> None:
    raw_data = _raw(TARGET_1, bidNtceDt="2022-11-14 23:59:59")
    result = _resolve(raw_data)
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_RULE_REGIME_MISMATCH


def test_other_region_does_not_select_gwangju_rule() -> None:
    raw_data = _raw(
        TARGET_1,
        dminsttNm="전라남도 무안군",
    )
    result = _resolve(raw_data, region_code="46", region_name="전라남도")
    assert result.is_blocked is True
    assert result.rule is None or result.rule.rule_id not in {RULE_ID, METRO_RULE_ID}
