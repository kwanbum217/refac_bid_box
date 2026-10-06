"""LOCAL 규칙 별표 원문 낙찰하한율 전수 대조 시험.

정본:
 - src/app/services/evaluation_rules.py 의 규칙 대표값과 PriceBand.lwlt_rate
 - docs/analysis/local_lwlt_audit_20261005.md (규칙별 대조표)
 - EXT/ulsan/ulsan_general_20220810.tbl.txt:671-713 (별표 1 참고 입찰가격 평점 산식)
 - EXT/cb/cb_cjuc.txt:1454-1659 (별표 1 3. 입찰가격 평가)
 - EXT/jn_gj/jngj_att001~006.hwp.tbl.txt (별표 1~6 입찰가격 평가)
 - EXT/gg/gg_g2b_20251210_coord.txt:337-455,456-572,573-672,733-843 (별표 1-2~1-4·1-6)
 - EXT/sejong/byp2_2025.txt:31, byp4_2025.txt:18, byp4_2_2025.txt:11
 - EXT/daegu/tbl1_daegu.txt:150, EXT/supplement/daegu/R25BK01157938_f1.txt:47

평가 API 끝단은 mock 없이 TestClient 로 호출합니다. 예측 모델만 이 워크트리에 모델 파일이
없어 시험 대역으로 대체하며, 규칙 판별·구간 하한율·최저 투찰금액 경로는 실제 코드입니다.
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
from src.app.services.evaluation_rules import (
    LOCAL_RULES,
    EvaluationRule,
    RuleResolutionResult,
    resolve_evaluation_rule,
)

ANALYZE_URL = "/api/v1/evaluations/analyze"

SEJONG_FACILITY_ID = "SERVC_LOCAL_SEJONG_20251201_ATTACH_02"
SEJONG_WASTE_ID = "SERVC_LOCAL_SEJONG_20251201_ATTACH_04"
SEJONG_WASTE_HOUSEHOLD_ID = "SERVC_LOCAL_SEJONG_20251201_ATTACH_4_2"
ULSAN_GENERAL_ID = "SERVC_LOCAL_ULSAN_20220810_ATTACH_01"
ULSAN_SIMPLE_ID = "SERVC_LOCAL_ULSAN_20220810_SIMPLE_LABOR"
ULSAN_WASTE_HOUSEHOLD_ID = "SERVC_LOCAL_ULSAN_20220810_ATTACH_1_1"
ULSAN_WASTE_ID = "SERVC_LOCAL_ULSAN_20220810_ATTACH_02"
CB_GENERAL_ID = "SERVC_LOCAL_CB_20231020_ATTACH_01"
CB_SIMPLE_ID = "SERVC_LOCAL_CB_20231020_SIMPLE_LABOR"
JNGJ_FACILITY_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_01"
JNGJ_SW_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_02"
JNGJ_WASTE_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_03"
JNGJ_WASTE_HOUSEHOLD_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_04"
JNGJ_LAND_TRANSPORT_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_05"
JNGJ_FISHERY_ID = "SERVC_LOCAL_JNGJ_20260716_ATTACH_06"
DAEGU_ID = "SERVC_LOCAL_DAEGU_20260511_ATTACH_01"
GG_SW_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_2"
GG_WASTE_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_3"
GG_LAND_TRANSPORT_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_4"
GG_GENERAL_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_6"

GENERAL_METHOD = "일반용역 적격심사 추정가격 5억원 이상"
SIMPLE_LABOR_METHOD = "단순노무용역 적격심사 추정가격 5억원 미만"
FACILITY_METHOD = "시설분야용역 적격심사 추정가격 5억원 이상"
SW_METHOD = "소프트웨어용역 적격심사 추정가격 5억원 이상"
WASTE_METHOD = "폐기물 처리용역 적격심사 추정가격 5억원 이상"
WASTE_HOUSEHOLD_METHOD = "생활폐기물 처리용역 적격심사 추정가격 5억원 이상"
LAND_TRANSPORT_METHOD = "화물 육상운송용역 적격심사 추정가격 5억원 이상"
FISHERY_METHOD = "적격심사제-어장정화·정비용역"


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def _resolve(
    *,
    region_code: str,
    region_name: str,
    method: str,
    estimated_price: str | None = None,
    local_service_type: str | None = None,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        contract_regime="LOCAL",
        bid_ntce_dt="2026-08-01",
        region_code=region_code,
        region_name=region_name,
        raw_data={"sucsfbidMthdNm": method},
        estimated_price=estimated_price,
        local_service_type=local_service_type,
    )


def _signature(rule: EvaluationRule) -> dict[str, object]:
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


# --------------------------------------------------------------------------- #
# 1. 전 구간 단일 하한율 정정 (규칙 대표값)
# --------------------------------------------------------------------------- #

# (rule_id, 원문 단일 하한율, 규칙 source 에 있어야 하는 EXT 근거 조각)
UNIFORM_RATE_CASES = (
    (SEJONG_FACILITY_ID, "87.745", "EXT/sejong/byp2_2025.txt:31"),
    (SEJONG_WASTE_ID, "87.745", "EXT/sejong/byp4_2025.txt:18"),
    (SEJONG_WASTE_HOUSEHOLD_ID, "87.745", "EXT/sejong/byp4_2_2025.txt:11"),
    (ULSAN_SIMPLE_ID, "87.745", "EXT/ulsan/ulsan_general_20220810.tbl.txt:671-713"),
    (ULSAN_WASTE_HOUSEHOLD_ID, "87.745", "EXT/ulsan/ulsan_general_20220810.tbl.txt:671-713"),
    (CB_SIMPLE_ID, "87.745", "EXT/cb/cb_cjuc.txt:1454-1659"),
    (JNGJ_FACILITY_ID, "87.745", "EXT/jn_gj/jngj_att001.hwp.tbl.txt:47-69"),
    (JNGJ_WASTE_HOUSEHOLD_ID, "87.745", "EXT/jn_gj/jngj_att004.hwp.tbl.txt:46-60"),
    (DAEGU_ID, "87.745", "EXT/daegu/tbl1_daegu.txt:150"),
)


@pytest.mark.parametrize(("rule_id", "expected_rate", "ext_token"), UNIFORM_RATE_CASES)
def test_uniform_rate_rules_match_ext_source(
    rule_id: str, expected_rate: str, ext_token: str
) -> None:
    """전 구간 단일 하한율 별표는 규칙 대표값이 원문 인쇄값과 같고 구간값은 두지 않는다."""
    rule = _rule(rule_id)
    assert rule.lwlt_rate == Decimal(expected_rate), rule_id
    assert [band.lwlt_rate for band in rule.price_bands or ()] == [None] * len(
        rule.price_bands or ()
    ), rule_id
    assert ext_token in rule.source, rule_id


# --------------------------------------------------------------------------- #
# 2. 구간별 하한율 (PriceBand.lwlt_rate) 과 10억/30억 분할
# --------------------------------------------------------------------------- #

# (rule_id, 구간 순서(2억 미만 → 마지막), 규칙 source 에 있어야 하는 EXT 근거 조각)
BAND_RATE_CASES = (
    (
        ULSAN_GENERAL_ID,
        ("87.745", "86.745", "85.495", "77.995", "72.995"),
        "EXT/ulsan/ulsan_general_20220810.tbl.txt:671-713",
    ),
    (
        ULSAN_WASTE_ID,
        ("87.745", "86.745", "85.495", "77.995", "72.995"),
        "EXT/ulsan/ulsan_general_20220810.tbl.txt:671-713",
    ),
    (
        CB_GENERAL_ID,
        ("87.745", "86.745", "85.495", "77.995", "72.995"),
        "EXT/cb/cb_cjuc.txt:1454-1659",
    ),
    (
        JNGJ_SW_ID,
        ("87.745", "86.745", "85.495", "82.995", "80.495"),
        "EXT/jn_gj/jngj_att002.hwp.tbl.txt:52-74",
    ),
    (
        JNGJ_WASTE_ID,
        ("87.745", "87.745", "82.995", "77.995", "72.995"),
        "EXT/jn_gj/jngj_att003.hwp.tbl.txt:53-75",
    ),
    (
        JNGJ_LAND_TRANSPORT_ID,
        ("85.495", "85.495", "85.495", "82.995", "80.495"),
        "EXT/jn_gj/jngj_att005.hwp.tbl.txt:48-70",
    ),
    (
        JNGJ_FISHERY_ID,
        ("87.745", "86.745", "85.495", "77.995", "72.995"),
        "EXT/jn_gj/jngj_att006.hwp.tbl.txt:9-93",
    ),
    (
        GG_SW_ID,
        ("87.745", "86.745", "85.495", "77.995"),
        "EXT/gg/gg_g2b_20251210_coord.txt:337-455",
    ),
    (
        GG_WASTE_ID,
        ("87.745", "86.745", "85.495", "77.995"),
        "EXT/gg/gg_g2b_20251210_coord.txt:456-572",
    ),
    (
        GG_LAND_TRANSPORT_ID,
        ("87.745", "87.745", "86.745", "85.495"),
        "EXT/gg/gg_g2b_20251210_coord.txt:573-672",
    ),
    (
        GG_GENERAL_ID,
        ("87.745", "86.745", "85.495", "77.995"),
        "EXT/gg/gg_g2b_20251210_coord.txt:733-843",
    ),
)


@pytest.mark.parametrize(("rule_id", "expected_rates", "ext_token"), BAND_RATE_CASES)
def test_band_rates_match_ext_source(
    rule_id: str, expected_rates: tuple[str, ...], ext_token: str
) -> None:
    """구간별 하한율이 원문 인쇄값과 순서대로 같고 근거가 규칙 source 에 있다."""
    rule = _rule(rule_id)
    assert [band.lwlt_rate for band in rule.price_bands or ()] == [
        Decimal(rate) for rate in expected_rates
    ], rule_id
    assert ext_token in rule.source, rule_id


# (rule_id, 지역코드, 지역명, 낙찰방법명, 선택값, 추정가격, 기대 하한율)
BAND_EFFECTIVE_CASES = (
    (ULSAN_GENERAL_ID, "31", "울산광역시", GENERAL_METHOD, "GENERAL", "150000000", "87.745"),
    (ULSAN_GENERAL_ID, "31", "울산광역시", GENERAL_METHOD, "GENERAL", "700000000", "85.495"),
    # 30억 경계값은 이상 쪽(30억원 이상) 구간에 속한다.
    (ULSAN_GENERAL_ID, "31", "울산광역시", GENERAL_METHOD, "GENERAL", "2999999999", "77.995"),
    (ULSAN_GENERAL_ID, "31", "울산광역시", GENERAL_METHOD, "GENERAL", "3000000000", "72.995"),
    (ULSAN_GENERAL_ID, "31", "울산광역시", GENERAL_METHOD, "GENERAL", "4000000000", "72.995"),
    (ULSAN_WASTE_ID, "31", "울산광역시", WASTE_METHOD, None, "4000000000", "72.995"),
    (CB_GENERAL_ID, "43", "충청북도", GENERAL_METHOD, "GENERAL", "2000000000", "77.995"),
    (CB_GENERAL_ID, "43", "충청북도", GENERAL_METHOD, "GENERAL", "4000000000", "72.995"),
    (JNGJ_SW_ID, "12", "전남광주통합특별시", SW_METHOD, None, "700000000", "85.495"),
    (JNGJ_SW_ID, "12", "전남광주통합특별시", SW_METHOD, None, "2000000000", "82.995"),
    (JNGJ_SW_ID, "12", "전남광주통합특별시", SW_METHOD, None, "4000000000", "80.495"),
    (JNGJ_WASTE_ID, "12", "전남광주통합특별시", WASTE_METHOD, None, "700000000", "82.995"),
    (JNGJ_WASTE_ID, "12", "전남광주통합특별시", WASTE_METHOD, None, "4000000000", "72.995"),
    (
        JNGJ_LAND_TRANSPORT_ID,
        "12",
        "전남광주통합특별시",
        LAND_TRANSPORT_METHOD,
        None,
        "700000000",
        "85.495",
    ),
    (
        JNGJ_LAND_TRANSPORT_ID,
        "12",
        "전남광주통합특별시",
        LAND_TRANSPORT_METHOD,
        None,
        "2000000000",
        "82.995",
    ),
    (JNGJ_FISHERY_ID, "12", "전남광주통합특별시", FISHERY_METHOD, None, "4000000000", "72.995"),
    (GG_SW_ID, "41", "경기도", SW_METHOD, None, "300000000", "86.745"),
    (GG_SW_ID, "41", "경기도", SW_METHOD, None, "1500000000", "77.995"),
    (GG_WASTE_ID, "41", "경기도", WASTE_METHOD, None, "600000000", "85.495"),
    (GG_LAND_TRANSPORT_ID, "41", "경기도", LAND_TRANSPORT_METHOD, None, "600000000", "86.745"),
    (GG_GENERAL_ID, "41", "경기도", GENERAL_METHOD, "GENERAL", "700000000", "85.495"),
    (GG_GENERAL_ID, "41", "경기도", GENERAL_METHOD, "GENERAL", "1500000000", "77.995"),
)


@pytest.mark.parametrize(
    ("rule_id", "code", "name", "method", "local_type", "price", "expected_rate"),
    BAND_EFFECTIVE_CASES,
)
def test_band_rate_applied_without_announcement_rate(
    rule_id: str,
    code: str,
    name: str,
    method: str,
    local_type: str | None,
    price: str,
    expected_rate: str,
) -> None:
    """공고 하한율이 없으면 추정가격으로 고른 구간의 원문 하한율을 쓴다."""
    result = _resolve(
        region_code=code,
        region_name=name,
        method=method,
        estimated_price=price,
        local_service_type=local_type,
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal(expected_rate), (rule_id, price)
    assert result.rate_source == "RULE_DEFAULT"


def test_band_rate_not_guessed_when_price_missing() -> None:
    """구간별 하한율이 서로 다른데 추정가격이 없으면 대표값으로 추측하지 않는다."""
    result = _resolve(
        region_code="31",
        region_name="울산광역시",
        method=GENERAL_METHOD,
        estimated_price=None,
        local_service_type="GENERAL",
    )
    assert result.rule is not None
    assert result.rule.rule_id == ULSAN_GENERAL_ID
    assert result.effective_lwlt_rate is None
    assert any("추정가격" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 3. 비정정 규칙 불변 (원문 미기재 규칙과 보험·조달청 규칙)
# --------------------------------------------------------------------------- #

# 정정 대상이 아닌 규칙의 동작 필드 스냅샷 해시. main 기준 값이며, 규칙 값을 의도적으로
# 바꾸면 위 _signature 로 재생성해 교체합니다. 2026-10-06 인천·제주·강원·경남·경북 04 는
# 이번 정정 대상이라 아래 목록에서 제외했습니다.
UNCHANGED_RULE_IDS = (
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_03",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_03_SME",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_05",
    "SERVC_LOCAL_SEJONG_20251201_ATTACH_05_SME",
    "SERVC_LOCAL_GB_20260108_ATTACH_01",
    "SERVC_LOCAL_GB_20260108_ATTACH_02",
    "SERVC_LOCAL_GB_20260108_ATTACH_03",
    "SERVC_LOCAL_GG_20250808_ATTACH_1_5",
)
UNCHANGED_RULES_DIGEST = "ebddc2e99e2533b4ac884d51676fadbfa06c70737c4f705fbb10df0d4feb05fe"


def test_uncorrected_rules_keep_behavior_fields() -> None:
    """정정 대상이 아닌 규칙은 main 과 같은 동작 필드(대표값·구간·통과점수)를 유지한다."""
    rules = {rule.rule_id: rule for rule in LOCAL_RULES}
    payload = json.dumps(
        [_signature(rules[rule_id]) for rule_id in UNCHANGED_RULE_IDS],
        ensure_ascii=False,
        sort_keys=True,
    )
    assert hashlib.sha256(payload.encode("utf-8")).hexdigest() == UNCHANGED_RULES_DIGEST


def test_uncorrected_local_rules_keep_rule_default() -> None:
    """구간 하한율이 생기지 않은 규칙은 종전 대표값과 구간값 없음 경로를 그대로 쓴다.

    인천·제주·강원 일반·단순노무와 경북 04 는 이번 정정 대상이라 이 목록에서 제외합니다
    (tests/test_local_10eok_lwlt.py 가 새 동작을 고정합니다).
    """
    cases = (
        ("SERVC_LOCAL_GB_20260108_ATTACH_02", "87.995"),
        ("SERVC_LOCAL_GG_20250808_ATTACH_1_5", "47.995"),
    )
    for rule_id, expected_rate in cases:
        rule = _rule(rule_id)
        assert rule.lwlt_rate == Decimal(expected_rate), rule_id
        assert all(band.lwlt_rate is None for band in rule.price_bands or ()), rule_id


def test_national_rule_unaffected() -> None:
    """조달청 규칙은 이번 정정 밖이라 하한율과 구간값이 그대로다."""
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm="적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        bid_ntce_dt="2026-08-01",
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_POST_20260526_ATTACH_01"
    assert result.rule.lwlt_rate == Decimal("89.995")
    assert result.effective_lwlt_rate == Decimal("89.995")
    assert result.rate_source == "RULE_DEFAULT"


# --------------------------------------------------------------------------- #
# 4. 실제 평가 API 끝단 (mock 없음, 예측 모델만 대역)
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
    data: dict[str, str] = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": institution_code,
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    bid = BidAnnouncement(
        bid_ntce_nm="구간 하한율 정정 끝단 시험 공고",
        bid_ntce_no="EVAL-LWLT-AUDIT-001",
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
    return bid


def _analyze(
    client,
    bid_id: int,
    bid_amount: int,
    local_service_type: str | None = None,
) -> dict:
    qualification: dict[str, object] = {
        "disqualification": False,
        "manual_non_price_score": 40.0,
    }
    if local_service_type is not None:
        qualification["local_service_type"] = local_service_type
    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid_id,
            "selected_model": "requested-evaluation-model",
            "candidate_bid_amount": bid_amount,
            "qualification_input": qualification,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


API_INSTITUTION_CODE = "7000044"

# (지역명, 낙찰방법명, 선택값, 규칙 ID, 추정가격, 기대 하한율, 기대 최저투찰금액)
# 최저투찰금액은 추정가격 x 하한율을 1원 단위로 계산한 값입니다.
CORRECTED_RULES_E2E_CASES = (
    ("세종특별자치시", FACILITY_METHOD, None, SEJONG_FACILITY_ID, 800_000_000, 87.745, 701_960_000),
    ("세종특별자치시", WASTE_METHOD, None, SEJONG_WASTE_ID, 800_000_000, 87.745, 701_960_000),
    (
        "세종특별자치시",
        WASTE_HOUSEHOLD_METHOD,
        None,
        SEJONG_WASTE_HOUSEHOLD_ID,
        800_000_000,
        87.745,
        701_960_000,
    ),
    (
        "울산광역시",
        GENERAL_METHOD,
        "GENERAL",
        ULSAN_GENERAL_ID,
        2_000_000_000,
        77.995,
        1_559_900_000,
    ),
    ("울산광역시", SIMPLE_LABOR_METHOD, None, ULSAN_SIMPLE_ID, 300_000_000, 87.745, 263_235_000),
    (
        "울산광역시",
        WASTE_HOUSEHOLD_METHOD,
        None,
        ULSAN_WASTE_HOUSEHOLD_ID,
        2_000_000_000,
        87.745,
        1_754_900_000,
    ),
    ("울산광역시", WASTE_METHOD, None, ULSAN_WASTE_ID, 4_000_000_000, 72.995, 2_919_800_000),
    ("충청북도", GENERAL_METHOD, "GENERAL", CB_GENERAL_ID, 4_000_000_000, 72.995, 2_919_800_000),
    ("충청북도", SIMPLE_LABOR_METHOD, None, CB_SIMPLE_ID, 300_000_000, 87.745, 263_235_000),
    (
        "전남광주통합특별시",
        FACILITY_METHOD,
        None,
        JNGJ_FACILITY_ID,
        1_500_000_000,
        87.745,
        1_316_175_000,
    ),
    ("전남광주통합특별시", SW_METHOD, None, JNGJ_SW_ID, 700_000_000, 85.495, 598_465_000),
    ("전남광주통합특별시", WASTE_METHOD, None, JNGJ_WASTE_ID, 2_000_000_000, 77.995, 1_559_900_000),
    (
        "전남광주통합특별시",
        WASTE_HOUSEHOLD_METHOD,
        None,
        JNGJ_WASTE_HOUSEHOLD_ID,
        4_000_000_000,
        87.745,
        3_509_800_000,
    ),
    (
        "전남광주통합특별시",
        LAND_TRANSPORT_METHOD,
        None,
        JNGJ_LAND_TRANSPORT_ID,
        2_000_000_000,
        82.995,
        1_659_900_000,
    ),
    (
        "전남광주통합특별시",
        FISHERY_METHOD,
        None,
        JNGJ_FISHERY_ID,
        4_000_000_000,
        72.995,
        2_919_800_000,
    ),
    ("대구광역시", SIMPLE_LABOR_METHOD, None, DAEGU_ID, 100_000_000, 87.745, 87_745_000),
    ("경기도", SW_METHOD, None, GG_SW_ID, 300_000_000, 86.745, 260_235_000),
    ("경기도", WASTE_METHOD, None, GG_WASTE_ID, 600_000_000, 85.495, 512_970_000),
    ("경기도", LAND_TRANSPORT_METHOD, None, GG_LAND_TRANSPORT_ID, 600_000_000, 86.745, 520_470_000),
    ("경기도", GENERAL_METHOD, "GENERAL", GG_GENERAL_ID, 700_000_000, 85.495, 598_465_000),
)


@pytest.mark.parametrize(
    (
        "region_name",
        "method",
        "local_service_type",
        "expected_rule_id",
        "presmpt_prce",
        "expected_rate",
        "expected_min_bid",
    ),
    CORRECTED_RULES_E2E_CASES,
)
def test_corrected_rules_through_analyze_api(
    client,
    isolated_db,
    as_user,
    region_name: str,
    method: str,
    local_service_type: str | None,
    expected_rule_id: str,
    presmpt_prce: int,
    expected_rate: float,
    expected_min_bid: int,
) -> None:
    """공고 하한율 없는 공고가 정정된 effective 하한율과 최저투찰금액을 그대로 쓴다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name=region_name,
        method=method,
        presmpt_prce=presmpt_prce,
    )

    payload = _analyze(client, bid.id, presmpt_prce // 2, local_service_type)

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["blocked"] is False
    assert payload["rule_id"] == expected_rule_id
    assert payload["lower_bound_rate"] == pytest.approx(expected_rate)
    assert any(
        f"낙찰하한율 {expected_rate}% 적용 최저 투찰금액: {expected_min_bid:,}원" in warning
        for warning in payload["warnings"]
    ), (expected_rule_id, payload["warnings"])


def test_incheon_general_min_bid_through_analyze_api(client, isolated_db, as_user) -> None:
    """정정된 인천 GENERAL 은 10억~30억 구간 하한율 77.995% 로 최저투찰금액을 계산한다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="인천광역시")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name="인천광역시",
        method=GENERAL_METHOD,
        presmpt_prce=2_000_000_000,
    )

    payload = _analyze(client, bid.id, 1_000_000_000, "GENERAL")

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["rule_id"] == "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
    assert payload["lower_bound_rate"] == pytest.approx(77.995)
    assert any(
        "낙찰하한율 77.995% 적용 최저 투찰금액: 1,559,900,000원" in warning
        for warning in payload["warnings"]
    )
