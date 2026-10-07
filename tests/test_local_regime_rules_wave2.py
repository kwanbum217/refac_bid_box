"""지방계약(LOCAL) 2단계 5곳(서울·부산·대전·충남·전북) 규칙과 평탄 구간 시험.

정본:
 - docs/analysis/servc_formula_recover_c_20261005.md 4.1~4.5절 (5곳 원문 수치·평탄 문장)
 - EXT/seoul, EXT/busan, EXT/daejeon, EXT/chungnam, EXT/jeonbuk, EXT/sejong 추출물
 - docs/design/local_regime_rules_design_20261005.md 0절(D5·D8)·6.4절

충남(별표 1·2의1·5)과 세종 SW·육상운송은 원문이 평탄 비율만 인쇄하고 점수는 미인쇄라
기대 점수는 산식 대입값입니다. 충남 별표 2·3·4 는 B(5억 축)·k(고시금액 축)가 결합
인쇄되지 않아 짝짓기를 추론하지 않고 등록하지 않았으며, 그 사용자 입력 경로도 고정합니다.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_flat_zones import flat_zone_for
from src.app.services.evaluation_rules import (
    BLOCK_CODE_LOCAL_RULE_NOT_FOUND,
    BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED,
    LOCAL_RULES,
    QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED,
    RULE_SCOPE_REGION,
    EvaluationRule,
    RuleResolutionResult,
    resolve_evaluation_rule,
    resolve_score_params,
)
from src.app.services.evaluation_scoring import calculate_price_score

ANALYZE_URL = "/api/v1/evaluations/analyze"

SEOUL_GENERAL_ID = "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"
SEOUL_SIMPLE_ID = "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR"
BUSAN_GENERAL_ID = "SERVC_LOCAL_BUSAN_20250626_ATTACH_01"
BUSAN_SIMPLE_ID = "SERVC_LOCAL_BUSAN_20250626_SIMPLE_LABOR"
DAEJEON_GENERAL_ID = "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01"
DAEJEON_SIMPLE_ID = "SERVC_LOCAL_DAEJEON_20260101_SIMPLE_LABOR"
CHUNGNAM_FACILITY_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_01"
CHUNGNAM_SW_SME_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_2_1"
CHUNGNAM_FISHERY_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_05"
JEONBUK_GENERAL_ID = "SERVC_LOCAL_JEONBUK_20240118_ATTACH_01"
JEONBUK_SIMPLE_ID = "SERVC_LOCAL_JEONBUK_20240118_SIMPLE_LABOR"

NEW_RULE_IDS = (
    SEOUL_GENERAL_ID,
    SEOUL_SIMPLE_ID,
    BUSAN_GENERAL_ID,
    BUSAN_SIMPLE_ID,
    DAEJEON_GENERAL_ID,
    DAEJEON_SIMPLE_ID,
    CHUNGNAM_FACILITY_ID,
    CHUNGNAM_SW_SME_ID,
    CHUNGNAM_FISHERY_ID,
    JEONBUK_GENERAL_ID,
    JEONBUK_SIMPLE_ID,
)


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def _resolve(
    *,
    region_code: str,
    region_name: str,
    method: str,
    local_service_type: str | None = None,
    raw_data: dict | None = None,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        contract_regime="LOCAL",
        bid_ntce_dt="2026-08-01",
        region_code=region_code,
        region_name=region_name,
        raw_data=raw_data if raw_data is not None else {"sucsfbidMthdNm": method},
        local_service_type=local_service_type,
    )


# --------------------------------------------------------------------------- #
# 1. 5곳 구간별 B·k·기준비율·통과점수 원문 대조
# --------------------------------------------------------------------------- #

# (rule_id, 추정가격, B, k, T, 기준비율). 원문 인쇄값 또는 산식 그대로.
REGION_BAND_CASES = (
    (SEOUL_GENERAL_ID, "150000000", "90", "20", "95", "0.88"),
    (SEOUL_GENERAL_ID, "1000000000", "30", "1", "90", "0.88"),
    (SEOUL_GENERAL_ID, "3000000000", "30", "1", "85", "0.88"),
    (SEOUL_SIMPLE_ID, "150000000", "90", "20", "95", "0.88"),
    (BUSAN_GENERAL_ID, "300000000", "70", "4", "95", "0.88"),
    (BUSAN_GENERAL_ID, "500000000", "50", "2", "95", "0.88"),
    (BUSAN_GENERAL_ID, "3000000000", "30", "1", "85", "0.88"),
    (BUSAN_GENERAL_ID, "4000000000", "30", "1", "85", "0.88"),
    (BUSAN_SIMPLE_ID, "300000000", "70", "20", "95", "0.88"),
    (DAEJEON_GENERAL_ID, "300000000", "70", "4", "95", "0.88"),
    (DAEJEON_GENERAL_ID, "1500000000", "30", "1", "90", "0.88"),
    (DAEJEON_GENERAL_ID, "4000000000", "30", "1", "85", "0.88"),
    (DAEJEON_SIMPLE_ID, "300000000", "70", "20", "95", "0.88"),
    (CHUNGNAM_FACILITY_ID, "300000000", "70", "5", "85", "0.91"),
    (CHUNGNAM_FACILITY_ID, "600000000", "60", "5", "85", "0.91"),
    (CHUNGNAM_SW_SME_ID, "300000000", "70", "4", "88", "0.91"),
    (CHUNGNAM_SW_SME_ID, "600000000", "60", "4", "88", "0.91"),
    (CHUNGNAM_FISHERY_ID, "300000000", "70", "5", "85", "0.91"),
    (CHUNGNAM_FISHERY_ID, "600000000", "60", "2", "85", "0.88"),
    (JEONBUK_GENERAL_ID, "300000000", "70", "4", "95", "0.88"),
    (JEONBUK_GENERAL_ID, "1000000000", "30", "1", "90", "0.88"),
    (JEONBUK_GENERAL_ID, "4000000000", "30", "1", "85", "0.88"),
    (JEONBUK_SIMPLE_ID, "300000000", "70", "20", "95", "0.88"),
)


@pytest.mark.parametrize(
    ("rule_id", "price", "expected_b", "expected_k", "expected_t", "expected_base"),
    REGION_BAND_CASES,
)
def test_region_band_values_match_ext_source(
    rule_id: str, price: str, expected_b: str, expected_k: str, expected_t: str, expected_base: str
) -> None:
    """신규 5곳의 구간별 B·k·T·기준비율이 EXT 원문 인쇄값과 일치한다(시·도마다 2구간 이상)."""
    rule = _rule(rule_id)
    result = resolve_score_params(rule, Decimal(price), None, None)
    assert result.max_price_score == Decimal(expected_b), rule_id
    assert result.multiplier == Decimal(expected_k), rule_id
    assert result.pass_threshold == Decimal(expected_t), rule_id
    assert (result.base_rate or rule.base_rate) == Decimal(expected_base), rule_id
    assert rule.institution_scope == RULE_SCOPE_REGION
    assert rule.contract_regime == "LOCAL"
    assert rule.quant_basis == QUANT_BASIS_AGENCY_DOCUMENT_NOT_LOADED
    assert rule.source


# (rule_id, 규칙 source 에 있어야 하는 EXT 원문 경로 조각)
SOURCE_TOKEN_CASES = (
    (SEOUL_GENERAL_ID, "EXT/seoul/seoul_general_2024_08_12.tbl.txt"),
    (SEOUL_SIMPLE_ID, "EXT/seoul/seoul_general_2024_08_12.tbl.txt"),
    (BUSAN_GENERAL_ID, "EXT/busan/busan_general_2025_1981.txt"),
    (BUSAN_SIMPLE_ID, "EXT/busan/busan_general_2025_1981.txt"),
    (DAEJEON_GENERAL_ID, "EXT/daejeon/daejeon_2025_9528.txt"),
    (DAEJEON_SIMPLE_ID, "EXT/daejeon/daejeon_2025_9528.txt"),
    (CHUNGNAM_FACILITY_ID, "EXT/chungnam/"),
    (CHUNGNAM_SW_SME_ID, "EXT/chungnam/"),
    (CHUNGNAM_FISHERY_ID, "EXT/chungnam/"),
    (JEONBUK_GENERAL_ID, "EXT/jeonbuk/jb_general_2024_10.tbl.txt"),
    (JEONBUK_SIMPLE_ID, "EXT/jeonbuk/jb_general_2024_10.tbl.txt"),
)


@pytest.mark.parametrize(("rule_id", "source_token"), SOURCE_TOKEN_CASES)
def test_new_region_rule_source_cites_ext_original(rule_id: str, source_token: str) -> None:
    assert source_token in _rule(rule_id).source


# --------------------------------------------------------------------------- #
# 2. 신규 5곳 평탄 구간 값과 고정 동작
# --------------------------------------------------------------------------- #

# (rule_id, PriceBand.upper_bound, 평탄 비율, 평탄 점수)
FLAT_ZONE_CASES = (
    (SEOUL_GENERAL_ID, "200000000", "0.8825", "85"),
    (SEOUL_GENERAL_ID, None, "0.98", "20"),
    (SEOUL_SIMPLE_ID, "200000000", "0.8825", "85"),
    (BUSAN_GENERAL_ID, "500000000", "0.8925", "65"),
    (BUSAN_GENERAL_ID, "3000000000", "0.98", "20"),
    (BUSAN_SIMPLE_ID, None, "0.8825", "25"),
    (DAEJEON_GENERAL_ID, "3000000000", "0.98", "20"),
    (DAEJEON_GENERAL_ID, None, "0.98", "20"),
    (CHUNGNAM_FACILITY_ID, "500000000", "0.94", "55"),
    (CHUNGNAM_FACILITY_ID, None, "0.94", "45"),
    (CHUNGNAM_SW_SME_ID, "500000000", "0.94", "58"),
    (CHUNGNAM_SW_SME_ID, None, "0.94", "48"),
    (CHUNGNAM_FISHERY_ID, "500000000", "0.94", "55"),
    (CHUNGNAM_FISHERY_ID, None, "0.955", "45"),
    (JEONBUK_GENERAL_ID, "1000000000", "0.905", "45"),
    (JEONBUK_GENERAL_ID, "3000000000", "0.98", "20"),
    (JEONBUK_SIMPLE_ID, "1000000000", "0.8825", "45"),
)


@pytest.mark.parametrize(("rule_id", "upper_bound", "ratio", "score"), FLAT_ZONE_CASES)
def test_flat_zone_values_match_source(
    rule_id: str, upper_bound: str | None, ratio: str, score: str
) -> None:
    zone = flat_zone_for(rule_id, upper_bound)
    assert zone is not None, rule_id
    assert zone.flat_ratio == Decimal(ratio), rule_id
    assert zone.flat_score == Decimal(score), rule_id
    assert "EXT/" in zone.source, rule_id


# (rule_id, 구간 선택용 추정가격, 평탄 비율, 평탄 점수)
FLAT_PIN_CASES = (
    (SEOUL_SIMPLE_ID, "150000000", "0.8825", "85"),
    (SEOUL_GENERAL_ID, "1500000000", "0.98", "20"),
    (BUSAN_SIMPLE_ID, "300000000", "0.8825", "65"),
    (DAEJEON_GENERAL_ID, "1500000000", "0.98", "20"),
    (CHUNGNAM_FACILITY_ID, "600000000", "0.94", "45"),
    (CHUNGNAM_SW_SME_ID, "600000000", "0.94", "48"),
    (CHUNGNAM_FISHERY_ID, "600000000", "0.955", "45"),
    (JEONBUK_GENERAL_ID, "600000000", "0.905", "45"),
    (JEONBUK_SIMPLE_ID, "300000000", "0.8825", "65"),
)


@pytest.mark.parametrize(("rule_id", "price", "ratio", "score"), FLAT_PIN_CASES)
def test_flat_zone_pins_score_for_ratio_and_above(
    rule_id: str, price: str, ratio: str, score: str
) -> None:
    """비율 도달 시 산식값이 평탄 점수와 같고, 그 위 구간에서는 점수가 고정된다."""
    rule = _rule(rule_id)
    result = resolve_score_params(rule, Decimal(price), None, None)
    assert result.price_band_index is not None
    band = rule.price_bands[result.price_band_index]
    zone = flat_zone_for(rule_id, band.upper_bound)
    assert zone is not None, rule_id
    assert zone.flat_ratio == Decimal(ratio)
    assert zone.flat_score == Decimal(score)

    base_rate = result.base_rate or rule.base_rate
    pred_price = Decimal("100")
    at_ratio = calculate_price_score(
        pred_price * zone.flat_ratio,
        pred_price,
        base_rate,
        result.max_price_score,
        result.multiplier,
        zone.flat_ratio,
        zone.flat_score,
    )
    assert at_ratio.raw_score == zone.flat_score, rule_id
    assert at_ratio.score == zone.flat_score, rule_id
    assert at_ratio.flat_ratio == zone.flat_ratio

    above_ratio = zone.flat_ratio + Decimal("0.01")
    above = calculate_price_score(
        pred_price * above_ratio,
        pred_price,
        base_rate,
        result.max_price_score,
        result.multiplier,
        zone.flat_ratio,
        zone.flat_score,
    )
    assert above.raw_score < zone.flat_score, rule_id
    assert above.score == zone.flat_score, rule_id


def test_daejeon_other_bands_have_no_flat_zone() -> None:
    """대전 별표 6 은 10억원 이상 소프트웨어류에만 평탄 문장이 있어 다른 구간은 평탄이 없다."""
    for upper_bound in ("200000000", "500000000", "1000000000"):
        assert flat_zone_for(DAEJEON_GENERAL_ID, upper_bound) is None
    for upper_bound in ("200000000", "500000000", "1000000000", None):
        assert flat_zone_for(DAEJEON_SIMPLE_ID, upper_bound) is None


# --------------------------------------------------------------------------- #
# 3. 세종 SW·육상운송 평탄 구간 (비대상 95.5%, 대상 91%, 점수 미인쇄 대입값)
# --------------------------------------------------------------------------- #

# (rule_id, 추정가격, 평탄 비율, 평탄 점수, 원문 파일 토큰)
SEJONG_FLAT_CASES = (
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_03", "400000000", "0.955", "55", "byp3_sw_2025.txt"),
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_03", "600000000", "0.955", "45", "byp3_sw_2025.txt"),
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME", "400000000", "0.91", "58", "byp3_sw_2025.txt"),
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME", "600000000", "0.91", "48", "byp3_sw_2025.txt"),
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_05", "400000000", "0.955", "55", "byp5_2025.txt"),
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_05", "600000000", "0.955", "45", "byp5_2025.txt"),
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME", "400000000", "0.91", "58", "byp5_2025.txt"),
    ("SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME", "600000000", "0.91", "48", "byp5_2025.txt"),
)


@pytest.mark.parametrize(("rule_id", "price", "ratio", "score", "source_token"), SEJONG_FLAT_CASES)
def test_sejong_sw_and_land_transport_flat_zones(
    rule_id: str, price: str, ratio: str, score: str, source_token: str
) -> None:
    """세종 SW·육상운송 평탄 점수는 B·k·기준비율 88 산식에 평탄 비율을 대입한 값이다."""
    rule = _rule(rule_id)
    result = resolve_score_params(rule, Decimal(price), None, None)
    assert result.price_band_index is not None
    band = rule.price_bands[result.price_band_index]
    zone = flat_zone_for(rule_id, band.upper_bound)
    assert zone is not None, rule_id
    assert zone.flat_ratio == Decimal(ratio), rule_id
    assert zone.flat_score == Decimal(score), rule_id
    assert source_token in zone.source, rule_id

    computed = (
        result.max_price_score
        - result.multiplier * abs((result.base_rate or rule.base_rate) - Decimal(ratio)) * 100
    )
    assert computed == zone.flat_score, rule_id


# --------------------------------------------------------------------------- #
# 4. 5곳 규칙 선택과 사용자 선택 경로
# --------------------------------------------------------------------------- #

SELECTION_CASES = (
    ("11", "서울특별시", "시설분야용역 적격심사 추정가격 5억원 이상", SEOUL_GENERAL_ID),
    ("11", "서울특별시", "단순노무용역 적격심사 추정가격 5억원 미만", SEOUL_SIMPLE_ID),
    ("26", "부산광역시", "시설분야용역 적격심사 추정가격 5억원 이상", BUSAN_GENERAL_ID),
    ("26", "부산광역시", "단순노무용역 적격심사 추정가격 5억원 미만", BUSAN_SIMPLE_ID),
    ("30", "대전광역시", "소프트웨어용역 적격심사 추정가격 5억원 이상", DAEJEON_GENERAL_ID),
    ("30", "대전광역시", "단순노무용역 적격심사 추정가격 5억원 미만", DAEJEON_SIMPLE_ID),
    ("44", "충청남도", "시설분야용역 적격심사 추정가격 5억원 이상", CHUNGNAM_FACILITY_ID),
    ("44", "충청남도", "적격심사제-어장정화·정비용역", CHUNGNAM_FISHERY_ID),
    ("52", "전북특별자치도", "시설분야용역 적격심사 추정가격 5억원 이상", JEONBUK_GENERAL_ID),
    ("52", "전북특별자치도", "단순노무용역 적격심사 추정가격 5억원 미만", JEONBUK_SIMPLE_ID),
)


@pytest.mark.parametrize(("code", "name", "method", "expected_rule_id"), SELECTION_CASES)
def test_new_region_rule_selection(
    code: str, name: str, method: str, expected_rule_id: str
) -> None:
    result = _resolve(region_code=code, region_name=name, method=method)
    assert result.rule is not None, expected_rule_id
    assert result.rule.rule_id == expected_rule_id
    assert result.is_blocked is False


AMBIGUOUS_GENERAL_CASES = (
    ("11", "서울특별시"),
    ("26", "부산광역시"),
    ("30", "대전광역시"),
    ("52", "전북특별자치도"),
)


@pytest.mark.parametrize(("code", "name"), AMBIGUOUS_GENERAL_CASES)
def test_general_band_requires_user_selection(code: str, name: str) -> None:
    """단순노무 외/단순노무가 갈리는 4곳은 표기 없이 자동 확정하지 않는다(D5)."""
    method = "추정가격 2억원 미만인 용역"
    result = _resolve(region_code=code, region_name=name, method=method)
    assert result.rule is None
    assert result.is_blocked is True
    assert result.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    joined = " ".join(result.warnings)
    assert "SIMPLE_LABOR" in joined
    assert "local_service_type" in (result.block_reason_message or "")

    selected = _resolve(
        region_code=code, region_name=name, method=method, local_service_type="SIMPLE_LABOR"
    )
    assert selected.rule is not None
    assert selected.rule.service_type == "SIMPLE_LABOR"


def test_chungnam_sw_requires_sme_marker_or_user_selection() -> None:
    """충남은 비대상 별표 미등록이라 표기 없이는 확정하지 않고, 대상 표기·선택은 별표 2의1로 간다."""
    unmarked = _resolve(
        region_code="44",
        region_name="충청남도",
        method="소프트웨어용역 적격심사 추정가격 5억원 미만",
    )
    assert unmarked.rule is None
    assert unmarked.block_reason_code == BLOCK_CODE_LOCAL_SERVICE_TYPE_UNRESOLVED
    assert CHUNGNAM_SW_SME_ID in " ".join(unmarked.warnings)

    targeted = _resolve(
        region_code="44",
        region_name="충청남도",
        method="소프트웨어용역(중소기업자간 경쟁제품 대상) 적격심사 추정가격 5억원 미만",
    )
    assert targeted.rule is not None
    assert targeted.rule.rule_id == CHUNGNAM_SW_SME_ID

    selected = _resolve(
        region_code="44",
        region_name="충청남도",
        method="소프트웨어용역 적격심사 추정가격 5억원 미만",
        local_service_type="SW_SME",
    )
    assert selected.rule is not None
    assert selected.rule.rule_id == CHUNGNAM_SW_SME_ID


def test_chungnam_unregistered_attachments_keep_user_input_path() -> None:
    """충남 별표 2·3·4(정보통신 비대상·폐기물·육상운송)는 미등록이라 규칙 없음으로 차단한다."""
    for method in (
        "소프트웨어용역(중소기업자간 경쟁제품 비대상) 적격심사 추정가격 5억원 미만",
        "폐기물 처리용역 적격심사 추정가격 5억원 미만",
        "화물 육상운송용역 적격심사 추정가격 5억원 미만",
    ):
        result = _resolve(region_code="44", region_name="충청남도", method=method)
        assert result.rule is None, method
        assert result.block_reason_code == BLOCK_CODE_LOCAL_RULE_NOT_FOUND, method


# --------------------------------------------------------------------------- #
# 5. 기존 36개 규칙 불변
# --------------------------------------------------------------------------- #

EXISTING_RULE_IDS = (
    "SERVC_LOCAL_INCHEON_20251224_ATTACH_01",
    "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR",
    "SERVC_LOCAL_JEJU_20240101_ATTACH_01",
    "SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR",
    "SERVC_LOCAL_GANGWON_20230611_ATTACH_01",
    "SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_02",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_03",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_04",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_05",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME",
    "SERVC_LOCAL_GB_20260108_ATTACH_01",
    "SERVC_LOCAL_GB_20260108_ATTACH_02",
    "SERVC_LOCAL_GB_20260108_ATTACH_03",
    "SERVC_LOCAL_GB_20260108_ATTACH_04",
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_01",
    "SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR",
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1",
    "SERVC_LOCAL_ULSAN_20220810_ATTACH_02",
    "SERVC_LOCAL_CB_20231020_ATTACH_01",
    "SERVC_LOCAL_CB_20231020_SIMPLE_LABOR",
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_01",
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_02",
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_03",
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_04",
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_05",
    "SERVC_LOCAL_JNGJ_20260716_ATTACH_06",
    "SERVC_LOCAL_GN_20230105_ATTACH_01",
    "SERVC_LOCAL_DAEGU_20260511_ATTACH_01",
    "SERVC_LOCAL_GG_20250808_ATTACH_1_2",
    "SERVC_LOCAL_GG_20250808_ATTACH_1_3",
    "SERVC_LOCAL_GG_20250808_ATTACH_1_4",
    "SERVC_LOCAL_GG_20250808_ATTACH_1_5",
    "SERVC_LOCAL_GG_20250808_ATTACH_1_6",
)

# main(f8d5660e 계열) 기준 36개 규칙의 동작 필드 스냅샷 해시. 규칙 값을 의도적으로 바꾸면
# 아래 명령으로 재생성해 교체합니다(시험 안에서 값을 만들지 않고 고정값과 대조합니다).
#   uv run python -c "import hashlib,json; from src.app.services.evaluation_rules import LOCAL_RULES; ..."
# 2026-10-06: 인천·제주·강원·경남 GENERAL 의 10억원 이상 30억원 분할과 인천·제주·강원
# 단순노무 대표값(87.745) 반영으로 재생성했습니다.
# 2026-10-07: 경북 단순노무(GB ATTACH_01) 대표값을 원문 산식 역산값 87.745 로 정정하며
# 재생성했습니다(서울 단순노무는 이 스냅샷 범위 밖입니다).
EXISTING_RULES_DIGEST = "c35b64538285f2fe7e8e27ffa8a2c4bc03a652b0276de217e70d0c78066cdd78"


def _rule_signature(rule: EvaluationRule) -> dict[str, object]:
    """동작에 영향을 주는 필드만 정규화합니다(설명·source 문자열은 제외)."""
    return {
        "rule_id": rule.rule_id,
        "service_type": rule.service_type,
        "effective_date": rule.effective_date,
        "lwlt_rate": str(rule.lwlt_rate),
        "base_rate": str(rule.base_rate),
        "price_bands": [
            [
                str(band.upper_bound),
                str(band.max_price_score),
                str(band.multiplier),
                str(band.base_rate),
                str(band.flat_score),
            ]
            for band in rule.price_bands or ()
        ],
        "threshold_bands": [
            [str(band.upper_bound), str(band.pass_threshold)] for band in rule.threshold_bands or ()
        ],
    }


def test_existing_36_local_rules_unchanged() -> None:
    """기존 36개 규칙은 순서와 동작 필드가 그대로이고 신규 11개는 뒤에 추가된다."""
    assert len(LOCAL_RULES) == len(EXISTING_RULE_IDS) + len(NEW_RULE_IDS)
    assert tuple(rule.rule_id for rule in LOCAL_RULES) == EXISTING_RULE_IDS + NEW_RULE_IDS
    payload = json.dumps(
        [_rule_signature(rule) for rule in LOCAL_RULES[: len(EXISTING_RULE_IDS)]],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == EXISTING_RULES_DIGEST


# --------------------------------------------------------------------------- #
# 6. 실제 평가 API 끝단 검증 (mock 없이 TestClient)
# --------------------------------------------------------------------------- #


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    def _fake_predict(payload, request, db):
        return PredictPriceResponse(
            status="success",
            optimal_price=440_000_000,
            prediction_rate=88.0,
            model_name="기본 대역 모델",
            model_id=payload.selected_model or "default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _create_institution(db, *, code: str, toplvl_nm: str) -> None:
    db.add(
        G2BDemandInstitution(
            dminstt_cd=code,
            dminstt_nm=f"{toplvl_nm} 본청",
            jrsdctn_div_nm="지방자치단체",
            rgn_cd="00000",
            rgn_nm=toplvl_nm,
            toplvl_instt_cd="0000000",
            toplvl_instt_nm=toplvl_nm,
            raw_json={},
        )
    )
    db.commit()


def _create_local_bid(
    db,
    *,
    institution_code: str,
    institution_name: str,
    method: str,
    presmpt_prce: int,
) -> BidAnnouncement:
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "sucsfbidLwltRate": "87.995",
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": institution_code,
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    bid = BidAnnouncement(
        bid_ntce_nm="지방계약 2단계 적격심사 테스트 공고",
        bid_ntce_no="EVAL-LOCAL-W2-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm=f"{institution_name} 본청",
        base_amount=presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data=data,
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


# (지역명, 낙찰방법명, 추정가격, 투찰금액, 기대 규칙 ID, 가격구간 표기, B, k, T,
#  평탄 비율, 평탄 점수, 기대 가격점수)
API_CASES = (
    (
        "서울특별시",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        1_500_000_000,
        1_470_000_000,
        SEOUL_GENERAL_ID,
        "30억원 미만 10억원 이상",
        "30",
        "1",
        "90",
        "0.98",
        "20",
        20.0,
    ),
    (
        "서울특별시",
        "단순노무용역 적격심사 추정가격 5억원 미만",
        300_000_000,
        264_750_000,
        SEOUL_SIMPLE_ID,
        "5억원 미만 2억원 이상",
        "70",
        "20",
        "95",
        "0.8825",
        "65",
        65.0,
    ),
    (
        "부산광역시",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        1_500_000_000,
        1_470_000_000,
        BUSAN_GENERAL_ID,
        "30억원 미만 10억원 이상",
        "30",
        "1",
        "90",
        "0.98",
        "20",
        20.0,
    ),
    (
        "부산광역시",
        "단순노무용역 적격심사 추정가격 5억원 미만",
        300_000_000,
        264_750_000,
        BUSAN_SIMPLE_ID,
        "5억원 미만 2억원 이상",
        "70",
        "20",
        "95",
        "0.8825",
        "65",
        65.0,
    ),
    (
        "대전광역시",
        "소프트웨어용역 적격심사 추정가격 5억원 이상",
        1_500_000_000,
        1_470_000_000,
        DAEJEON_GENERAL_ID,
        "30억원 미만 10억원 이상",
        "30",
        "1",
        "90",
        "0.98",
        "20",
        20.0,
    ),
    (
        "대전광역시",
        "단순노무용역 적격심사 추정가격 5억원 미만",
        300_000_000,
        264_000_000,
        DAEJEON_SIMPLE_ID,
        "5억원 미만 2억원 이상",
        "70",
        "20",
        "95",
        None,
        None,
        70.0,
    ),
    (
        "충청남도",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        600_000_000,
        564_000_000,
        CHUNGNAM_FACILITY_ID,
        "추정가격 5억원 이상",
        "60",
        "5",
        "85",
        "0.94",
        "45",
        45.0,
    ),
    (
        "충청남도",
        "적격심사제-어장정화·정비용역",
        600_000_000,
        573_000_000,
        CHUNGNAM_FISHERY_ID,
        "추정가격 5억원 이상",
        "60",
        "2",
        "85",
        "0.955",
        "45",
        45.0,
    ),
    (
        "전북특별자치도",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        1_500_000_000,
        1_470_000_000,
        JEONBUK_GENERAL_ID,
        "30억원 미만 10억원 이상",
        "30",
        "1",
        "90",
        "0.98",
        "20",
        20.0,
    ),
    (
        "전북특별자치도",
        "단순노무용역 적격심사 추정가격 5억원 미만",
        300_000_000,
        264_750_000,
        JEONBUK_SIMPLE_ID,
        "5억원 미만 2억원 이상",
        "70",
        "20",
        "95",
        "0.8825",
        "65",
        65.0,
    ),
)

API_INSTITUTION_CODE = "7000001"


@pytest.mark.parametrize(
    (
        "region_name",
        "method",
        "presmpt_prce",
        "bid_amount",
        "expected_rule_id",
        "band_label",
        "expected_b",
        "expected_k",
        "expected_t",
        "flat_ratio",
        "flat_score",
        "expected_price_score",
    ),
    API_CASES,
)
def test_new_region_rules_through_analyze_api(
    client,
    isolated_db,
    as_user,
    region_name: str,
    method: str,
    presmpt_prce: int,
    bid_amount: int,
    expected_rule_id: str,
    band_label: str,
    expected_b: str,
    expected_k: str,
    expected_t: str,
    flat_ratio: str | None,
    flat_score: str | None,
    expected_price_score: float,
) -> None:
    """5곳 규칙이 실제 평가 API 에서 mock 없이 확정되고 차단 없이 점수를 낸다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name=region_name,
        method=method,
        presmpt_prce=presmpt_prce,
    )

    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid.id,
            "selected_model": "requested-evaluation-model",
            "candidate_bid_amount": bid_amount,
            "qualification_input": {"disqualification": False, "manual_non_price_score": 40.0},
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["blocked"] is False
    assert payload["rule_id"] == expected_rule_id
    table = payload["score_table"]
    assert table is not None
    assert table["price_band_label"] == band_label
    assert table["max_price_score"] == expected_b
    assert table["multiplier"] == expected_k
    assert table["pass_threshold"] == expected_t
    assert table["flat_ratio"] == flat_ratio
    assert table["flat_score"] == flat_score
    assert table["source"]

    base = next(
        scenario for scenario in payload["scenario_results"] if scenario["scenario_name"] == "기준"
    )
    assert base["price_score"] == pytest.approx(expected_price_score)


def test_chungnam_sw_sme_selection_through_analyze_api(client, isolated_db, as_user) -> None:
    """충남 SW 는 표기 없이 막히고, local_service_type=SW_SME 선택 시 별표 2의1 로 계산된다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name="충청남도",
        method="소프트웨어용역 적격심사 추정가격 5억원 미만",
        presmpt_prce=400_000_000,
    )
    payload = {
        "bid_id": bid.id,
        "selected_model": "requested-evaluation-model",
        "candidate_bid_amount": 376_000_000,
        "qualification_input": {"disqualification": False, "manual_non_price_score": 40.0},
    }

    unresolved = client.post(ANALYZE_URL, json=payload).json()
    assert unresolved["status"] == "blocked"
    assert "LOCAL_SERVICE_TYPE_UNRESOLVED" in unresolved["blocked_reason"]

    payload["qualification_input"]["local_service_type"] = "SW_SME"
    selected = client.post(ANALYZE_URL, json=payload).json()
    assert selected["status"] == "success", selected.get("blocked_reason")
    assert selected["blocked"] is False
    assert selected["rule_id"] == CHUNGNAM_SW_SME_ID
    assert selected["score_table"]["flat_ratio"] == "0.94"
    assert selected["score_table"]["flat_score"] == "58"
    base = next(
        scenario for scenario in selected["scenario_results"] if scenario["scenario_name"] == "기준"
    )
    assert base["price_score"] == pytest.approx(58.0)
