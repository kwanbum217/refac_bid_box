"""가격 구간별 낙찰하한율(PriceBand.lwlt_rate) 시험.

정본:
 - src/app/services/evaluation_rules.py 의 PriceBand.lwlt_rate 와 _apply_rule_lwlt
 - EXT/chungnam/chungnam_2026_1235.txt:2334-2366
   (충남 별표 5, 5억원 미만 87.995% / 5억원 이상 80.495%)
 - EXT/busan/busan_general_2025_1981.txt:149
   (부산 별표 1, 10억원 이상 30억원 미만 77.995% / 30억원 이상 72.995%)
 - EXT/daejeon/daejeon_2025_9528.txt:262
   (대전 별표 6, 소프트웨어·폐기물·기타 일반용역 10억원 이상 30억원 경계)
 - EXT/jeonbuk/jb_general_2024_10.tbl.txt:127-145,357-366,583-592,792-799
 - docs/analysis/servc_formula_recover_c_20261005.md 4.1~4.5절

평가 API 끝단은 mock 없이 TestClient 로 호출합니다. 예측 모델만 이 워크트리에 모델 파일이
없어 시험 대역으로 대체하며, 규칙 판별·구간 하한율·최저 투찰금액 경로는 실제 코드입니다.
"""

from __future__ import annotations

from dataclasses import replace
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
from src.app.services import evaluation_rules as rules_module
from src.app.services.evaluation_rules import (
    LOCAL_RULES,
    EvaluationRule,
    RuleResolutionResult,
    resolve_evaluation_rule,
)

ANALYZE_URL = "/api/v1/evaluations/analyze"

CHUNGNAM_FISHERY_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_05"
CHUNGNAM_FISHERY_METHOD = "적격심사제-어장정화·정비용역"
CHUNGNAM_FACILITY_ID = "SERVC_LOCAL_CHUNGNAM_20260713_ATTACH_01"
BUSAN_GENERAL_ID = "SERVC_LOCAL_BUSAN_20250626_ATTACH_01"
BUSAN_SIMPLE_ID = "SERVC_LOCAL_BUSAN_20250626_SIMPLE_LABOR"
DAEJEON_GENERAL_ID = "SERVC_LOCAL_DAEJEON_20260101_ATTACH_01"
DAEJEON_SIMPLE_ID = "SERVC_LOCAL_DAEJEON_20260101_SIMPLE_LABOR"
JEONBUK_GENERAL_ID = "SERVC_LOCAL_JEONBUK_20240118_ATTACH_01"
JEONBUK_SIMPLE_ID = "SERVC_LOCAL_JEONBUK_20240118_SIMPLE_LABOR"
SEOUL_GENERAL_ID = "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"
SEOUL_SIMPLE_ID = "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR"
NATIONAL_FACILITY_ID = "SERVC_QUAL_POST_20260526_ATTACH_01"
NATIONAL_FACILITY_METHOD = "적격심사제-시설분야용역 적격심사 추정가격 5억원 미만"

API_INSTITUTION_CODE = "7000044"


def _rule(rule_id: str) -> EvaluationRule:
    match = next((rule for rule in LOCAL_RULES if rule.rule_id == rule_id), None)
    assert match is not None, rule_id
    return match


def _resolve(
    *,
    method: str,
    region_code: str | None = None,
    region_name: str | None = None,
    estimated_price: str | int | None = None,
    announcement_rate: str | None = None,
    contract_regime: str | None = "LOCAL",
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        sucsfbid_lwlt_rate=announcement_rate,
        contract_regime=contract_regime,
        bid_ntce_dt="2026-08-01",
        region_code=region_code,
        region_name=region_name,
        raw_data={"sucsfbidMthdNm": method},
        estimated_price=estimated_price,
    )


# --------------------------------------------------------------------------- #
# 1. 구간 하한율 원문 대조
# --------------------------------------------------------------------------- #


def test_chungnam_fishery_band_rates_are_sourced() -> None:
    """충남 별표 5 는 5억원 미만 87.995%, 5억원 이상 80.495% 를 인쇄한다."""
    rule = _rule(CHUNGNAM_FISHERY_ID)
    assert rule.price_bands is not None
    assert [band.lwlt_rate for band in rule.price_bands] == [
        Decimal("87.995"),
        Decimal("80.495"),
    ]
    for band in rule.price_bands:
        assert "chungnam_2026_1235.txt" in (band.source or "")
        assert "2334-2366" in (band.source or "")
    # 규칙 대표값은 종전과 같아 구간 하한율이 없는 경로의 결과가 바뀌지 않는다.
    assert rule.lwlt_rate == Decimal("87.995")


REGION_GENERAL_CASES = (
    (BUSAN_GENERAL_ID, "busan_general_2025_1981.txt:57,82-84,149-150"),
    (DAEJEON_GENERAL_ID, "daejeon_2025_9528.txt:39,68-71,260-265"),
    (
        JEONBUK_GENERAL_ID,
        "jb_general_2024_10.tbl.txt:35-37,44-49,127-145,357-366,583-592,792-799",
    ),
)


@pytest.mark.parametrize(("rule_id", "source_token"), REGION_GENERAL_CASES)
def test_region_general_band_rates_are_sourced(rule_id: str, source_token: str) -> None:
    """부산·대전·전북 단순노무 외 별표는 5구간 하한율을 인쇄한다.

    10억원 이상은 30억원 경계로 30억원 미만 77.995%, 30억원 이상 72.995% 로 갈린다.
    """
    rule = _rule(rule_id)
    assert rule.price_bands is not None
    assert [band.lwlt_rate for band in rule.price_bands] == [
        Decimal("87.745"),
        Decimal("86.745"),
        Decimal("85.495"),
        Decimal("77.995"),
        Decimal("72.995"),
    ]
    for band in rule.price_bands:
        assert source_token in (band.source or "")
    # 규칙 대표값은 분할 전과 같은 87.995 로 두어 대표값 경로 자체는 바뀌지 않는다.
    assert rule.lwlt_rate == Decimal("87.995")


# --------------------------------------------------------------------------- #
# 2. 구간 선택과 경계값 (공고 하한율 없음)
# --------------------------------------------------------------------------- #

BAND_BOUNDARY_CASES = (
    ("499999999", "87.995", "추정가격 5억원 미만"),
    ("500000000", "80.495", "추정가격 5억원 이상"),
    ("1000000000", "80.495", "추정가격 5억원 이상"),
)


@pytest.mark.parametrize(("price", "expected_rate", "band_label"), BAND_BOUNDARY_CASES)
def test_chungnam_band_boundary_uses_upper_band(
    price: str, expected_rate: str, band_label: str
) -> None:
    """5억원 경계값은 이상 쪽 구간에 속하고, 하한율은 그 구간 인쇄값이다."""
    result = _resolve(
        method=CHUNGNAM_FISHERY_METHOD,
        region_code="44",
        region_name="충청남도",
        estimated_price=price,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    assert result.rule.rule_id == CHUNGNAM_FISHERY_ID
    assert result.effective_lwlt_rate == Decimal(expected_rate)
    assert result.rate_source == "RULE_DEFAULT"
    assert any(
        f"별표 구간 하한율({expected_rate}%" in warning and band_label in warning
        for warning in result.warnings
    )


REGION_PRICE_CASES = (
    (BUSAN_GENERAL_ID, "26", "부산광역시", "150000000", "87.745"),
    (BUSAN_GENERAL_ID, "26", "부산광역시", "300000000", "86.745"),
    (BUSAN_GENERAL_ID, "26", "부산광역시", "700000000", "85.495"),
    (BUSAN_GENERAL_ID, "26", "부산광역시", "2000000000", "77.995"),
    (BUSAN_GENERAL_ID, "26", "부산광역시", "3000000000", "72.995"),
    (BUSAN_GENERAL_ID, "26", "부산광역시", "4000000000", "72.995"),
    (DAEJEON_GENERAL_ID, "30", "대전광역시", "150000000", "87.745"),
    (DAEJEON_GENERAL_ID, "30", "대전광역시", "700000000", "85.495"),
    (DAEJEON_GENERAL_ID, "30", "대전광역시", "2000000000", "77.995"),
    (DAEJEON_GENERAL_ID, "30", "대전광역시", "3000000000", "72.995"),
    (DAEJEON_GENERAL_ID, "30", "대전광역시", "4000000000", "72.995"),
    (JEONBUK_GENERAL_ID, "52", "전북특별자치도", "300000000", "86.745"),
    (JEONBUK_GENERAL_ID, "52", "전북특별자치도", "700000000", "85.495"),
    (JEONBUK_GENERAL_ID, "52", "전북특별자치도", "2000000000", "77.995"),
    (JEONBUK_GENERAL_ID, "52", "전북특별자치도", "3000000000", "72.995"),
    (JEONBUK_GENERAL_ID, "52", "전북특별자치도", "4000000000", "72.995"),
)


@pytest.mark.parametrize(("rule_id", "code", "name", "price", "expected_rate"), REGION_PRICE_CASES)
def test_region_general_band_rate_applied(
    rule_id: str, code: str, name: str, price: str, expected_rate: str
) -> None:
    method = "시설분야용역 적격심사 추정가격 5억원 이상"
    result = _resolve(method=method, region_code=code, region_name=name, estimated_price=price)
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal(expected_rate)
    assert result.rate_source == "RULE_DEFAULT"


SPLIT_LABEL_CASES = (
    (BUSAN_GENERAL_ID, "26", "부산광역시", "2000000000", "77.995", "30억원 미만 10억원 이상"),
    (BUSAN_GENERAL_ID, "26", "부산광역시", "3000000000", "72.995", "추정가격 30억원 이상"),
    (DAEJEON_GENERAL_ID, "30", "대전광역시", "2000000000", "77.995", "30억원 미만 10억원 이상"),
    (DAEJEON_GENERAL_ID, "30", "대전광역시", "4000000000", "72.995", "추정가격 30억원 이상"),
    (JEONBUK_GENERAL_ID, "52", "전북특별자치도", "2000000000", "77.995", "30억원 미만 10억원 이상"),
    (JEONBUK_GENERAL_ID, "52", "전북특별자치도", "3000000000", "72.995", "추정가격 30억원 이상"),
)


@pytest.mark.parametrize(
    ("rule_id", "code", "name", "price", "expected_rate", "band_label"), SPLIT_LABEL_CASES
)
def test_region_general_30eok_split_names_printed_band(
    rule_id: str, code: str, name: str, price: str, expected_rate: str, band_label: str
) -> None:
    """30억원 경계 분할값은 경고에서도 원문 구간 라벨과 함께 확인된다.

    경계값(정확히 30억원)은 상위 구간(이상 쪽)에 속한다.
    """
    result = _resolve(
        method="시설분야용역 적격심사 추정가격 5억원 이상",
        region_code=code,
        region_name=name,
        estimated_price=price,
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal(expected_rate)
    assert any(
        f"별표 구간 하한율({expected_rate}%" in warning and band_label in warning
        for warning in result.warnings
    )


REGION_SIMPLE_LABOR_CASES = (
    (BUSAN_SIMPLE_ID, "26", "부산광역시"),
    (DAEJEON_SIMPLE_ID, "30", "대전광역시"),
    (JEONBUK_SIMPLE_ID, "52", "전북특별자치도"),
)


@pytest.mark.parametrize(("rule_id", "code", "name"), REGION_SIMPLE_LABOR_CASES)
def test_region_simple_labor_rule_rate_is_source_value(rule_id: str, code: str, name: str) -> None:
    """부산·대전·전북 단순노무 별표의 규칙 단위 하한율은 원문 87.745% 다.

    단순노무 행은 구간 하한율을 따로 인쇄하지 않아 구간 선택 없이 규칙 대표값을 쓴다.
    """
    rule = _rule(rule_id)
    assert rule.lwlt_rate == Decimal("87.745")
    assert all(band.lwlt_rate is None for band in rule.price_bands or ())
    result = _resolve(
        method="단순노무용역 적격심사 추정가격 5억원 미만",
        region_code=code,
        region_name=name,
        estimated_price="300000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal("87.745")
    assert result.rate_source == "RULE_DEFAULT"
    assert any("별표 기본값(87.745%)" in warning for warning in result.warnings)


def test_region_simple_labor_rate_same_at_30eok_and_above() -> None:
    """단순노무 행은 30억원 경계 분할 없이 추정가격 40억원도 87.745% 다."""
    result = _resolve(
        method="단순노무용역 적격심사 추정가격 5억원 미만",
        region_code="26",
        region_name="부산광역시",
        estimated_price="4000000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == BUSAN_SIMPLE_ID
    assert result.effective_lwlt_rate == Decimal("87.745")


def test_seoul_general_keeps_four_bands_and_rule_default() -> None:
    """서울은 30억 분할 대상이 아니어서 20억·40억 모두 규칙 대표값과 기본값 경고를 쓴다."""
    rule = _rule(SEOUL_GENERAL_ID)
    assert rule.price_bands is not None
    assert len(rule.price_bands) == 4
    assert [band.lwlt_rate for band in rule.price_bands] == [None, None, None, None]
    for price in ("2000000000", "4000000000"):
        result = _resolve(
            method="시설분야용역 적격심사 추정가격 5억원 이상",
            region_code="11",
            region_name="서울특별시",
            estimated_price=price,
        )
        assert result.rule is not None
        assert result.rule.rule_id == SEOUL_GENERAL_ID
        assert result.effective_lwlt_rate == Decimal("87.995")
        assert result.rate_source == "RULE_DEFAULT"
        assert any("별표 기본값" in warning for warning in result.warnings)
        assert not any("구간 하한율" in warning for warning in result.warnings)


def test_seoul_simple_labor_rate_unchanged() -> None:
    """서울 단순노무 별표 대표값은 이번 변경 대상이 아니어서 87.995% 그대로다."""
    rule = _rule(SEOUL_SIMPLE_ID)
    assert rule.lwlt_rate == Decimal("87.995")


# --------------------------------------------------------------------------- #
# 3. 공고 하한율 우선
# --------------------------------------------------------------------------- #


def test_announcement_rate_wins_over_band_rate() -> None:
    """공고 하한율이 있으면 구간 하한율보다 우선한다(경고 없음, 종전 동작)."""
    result = _resolve(
        method=CHUNGNAM_FISHERY_METHOD,
        region_code="44",
        region_name="충청남도",
        estimated_price="1000000000",
        announcement_rate="87.995",
    )
    assert result.effective_lwlt_rate == Decimal("87.995")
    assert result.rate_source == "ANNOUNCEMENT"
    assert not any("구간 하한율" in warning for warning in result.warnings)


def test_announcement_rate_mismatch_warns_and_wins() -> None:
    result = _resolve(
        method=CHUNGNAM_FISHERY_METHOD,
        region_code="44",
        region_name="충청남도",
        estimated_price="400000000",
        announcement_rate="92.5",
    )
    assert result.effective_lwlt_rate == Decimal("92.5")
    assert result.rate_source == "ANNOUNCEMENT"
    assert any("공고 하한율(92.5%)" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 4. 추정가격 미상
# --------------------------------------------------------------------------- #


def test_unknown_price_with_differing_bands_is_not_guessed() -> None:
    """해석 단계는 규칙을 유지하고 하한율만 미확정으로 남긴다(대표값 추측 금지)."""
    result = _resolve(
        method=CHUNGNAM_FISHERY_METHOD,
        region_code="44",
        region_name="충청남도",
        estimated_price=None,
    )
    assert result.rule is not None
    assert result.rule.rule_id == CHUNGNAM_FISHERY_ID
    assert result.is_blocked is False
    assert result.effective_lwlt_rate is None
    assert result.rate_source is None
    assert any("추정가격을 입력해야" in warning for warning in result.warnings)


def test_unknown_price_with_uniform_band_rates_uses_shared_value(monkeypatch) -> None:
    """구간 하한율이 전 구간 같으면 추정가격이 없어도 구간을 고른 것과 같은 값을 쓴다."""
    base = _rule(CHUNGNAM_FISHERY_ID)
    uniform = replace(
        base,
        rule_id="SERVC_LOCAL_TEST_UNIFORM_BANDS",
        price_bands=tuple(
            replace(band, lwlt_rate=Decimal("80.495")) for band in base.price_bands or ()
        ),
    )
    monkeypatch.setattr(rules_module, "LOCAL_RULES", (uniform,))
    result = _resolve(
        method=CHUNGNAM_FISHERY_METHOD,
        region_code="44",
        region_name="충청남도",
        estimated_price=None,
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_LOCAL_TEST_UNIFORM_BANDS"
    assert result.effective_lwlt_rate == Decimal("80.495")
    assert result.rate_source == "RULE_DEFAULT"
    assert any("별표 구간 하한율(80.495%)" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 5. 구간 하한율이 없는 규칙 불변
# --------------------------------------------------------------------------- #

UNCHANGED_CASES = (
    (CHUNGNAM_FACILITY_ID, "44", "충청남도", "시설분야용역 적격심사 추정가격 5억원 이상", "87.995"),
    (SEOUL_GENERAL_ID, "11", "서울특별시", "시설분야용역 적격심사 추정가격 5억원 이상", "87.995"),
    (
        None,
        None,
        None,
        NATIONAL_FACILITY_METHOD,
        "89.995",
    ),
)


@pytest.mark.parametrize(("rule_id", "code", "name", "method", "expected_rate"), UNCHANGED_CASES)
def test_rules_without_band_rates_keep_rule_default(
    rule_id: str | None,
    code: str | None,
    name: str | None,
    method: str,
    expected_rate: str,
) -> None:
    """구간 하한율이 없는 규칙은 main 과 같이 규칙 대표값과 '기본값' 경고를 쓴다."""
    contract_regime = "LOCAL" if rule_id is not None else None
    result = _resolve(
        method=method,
        region_code=code,
        region_name=name,
        estimated_price="600000000",
        contract_regime=contract_regime,
    )
    assert result.is_blocked is False
    assert result.rule is not None
    if rule_id is not None:
        assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal(expected_rate)
    assert result.rate_source == "RULE_DEFAULT"
    assert any("별표 기본값" in warning for warning in result.warnings)
    assert not any("구간 하한율" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 6. 실제 평가 API 끝단 (mock 없음, 예측 모델만 대역)
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
    method: str,
    presmpt_prce: int | None,
    announced_rate: str | None = None,
    business_budget: str | None = None,
    institution_name: str = "충청남도",
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
    if announced_rate is not None:
        data["sucsfbidLwltRate"] = announced_rate
    if business_budget is not None:
        data["asignBdgtAmt"] = business_budget
    bid = BidAnnouncement(
        bid_ntce_nm="구간 하한율 끝단 시험 공고",
        bid_ntce_no="EVAL-BAND-LWLT-001",
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


def _analyze(client, bid_id: int, bid_amount: int, estimated_price: int | None = None) -> dict:
    qualification: dict[str, object] = {
        "disqualification": False,
        "manual_non_price_score": 40.0,
    }
    if estimated_price is not None:
        qualification["estimated_price"] = estimated_price
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


E2E_CASES = (
    (400_000_000, 350_000_000, 87.995, 351_980_000),
    (500_000_000, 450_000_000, 80.495, 402_475_000),
    (1_000_000_000, 850_000_000, 80.495, 804_950_000),
)


@pytest.mark.parametrize(
    ("presmpt_prce", "bid_amount", "expected_rate", "expected_min_bid"), E2E_CASES
)
def test_chungnam_band_lwlt_through_analyze_api(
    client,
    isolated_db,
    as_user,
    presmpt_prce: int,
    bid_amount: int,
    expected_rate: float,
    expected_min_bid: int,
) -> None:
    """공고 하한율 없는 충남 별표 5 공고가 구간 하한율과 최저투찰금액을 그대로 쓴다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        method=CHUNGNAM_FISHERY_METHOD,
        presmpt_prce=presmpt_prce,
    )

    payload = _analyze(client, bid.id, bid_amount)

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["rule_id"] == CHUNGNAM_FISHERY_ID
    assert payload["lower_bound_rate"] == pytest.approx(expected_rate)
    assert any(
        f"낙찰하한율 {expected_rate}% 적용 최저 투찰금액: {expected_min_bid:,}원" in warning
        for warning in payload["warnings"]
    )


# (지역명, 낙찰방법명, 규칙 ID, 추정가격, 투찰금액, 기대 하한율, 기대 최저투찰금액)
# 부산·대전·전북 일반 띠 10억원 이상은 30억원 경계로 77.995/72.995% 이고,
# 단순노무 띠는 규칙 대표값 87.745% 다. 최저투찰금액은 추정가격 x 하한율 그대로다.
REGION_SPLIT_E2E_CASES = (
    (
        "부산광역시",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        BUSAN_GENERAL_ID,
        2_000_000_000,
        1_700_000_000,
        77.995,
        1_559_900_000,
    ),
    (
        "부산광역시",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        BUSAN_GENERAL_ID,
        3_000_000_000,
        2_600_000_000,
        72.995,
        2_189_850_000,
    ),
    (
        "부산광역시",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        BUSAN_GENERAL_ID,
        4_000_000_000,
        3_500_000_000,
        72.995,
        2_919_800_000,
    ),
    (
        "부산광역시",
        "단순노무용역 적격심사 추정가격 5억원 미만",
        BUSAN_SIMPLE_ID,
        2_000_000_000,
        1_800_000_000,
        87.745,
        1_754_900_000,
    ),
    (
        "대전광역시",
        "소프트웨어용역 적격심사 추정가격 5억원 이상",
        DAEJEON_GENERAL_ID,
        2_000_000_000,
        1_700_000_000,
        77.995,
        1_559_900_000,
    ),
    (
        "대전광역시",
        "소프트웨어용역 적격심사 추정가격 5억원 이상",
        DAEJEON_GENERAL_ID,
        3_000_000_000,
        2_600_000_000,
        72.995,
        2_189_850_000,
    ),
    (
        "대전광역시",
        "소프트웨어용역 적격심사 추정가격 5억원 이상",
        DAEJEON_GENERAL_ID,
        4_000_000_000,
        3_500_000_000,
        72.995,
        2_919_800_000,
    ),
    (
        "대전광역시",
        "단순노무용역 적격심사 추정가격 5억원 미만",
        DAEJEON_SIMPLE_ID,
        2_000_000_000,
        1_800_000_000,
        87.745,
        1_754_900_000,
    ),
    (
        "전북특별자치도",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        JEONBUK_GENERAL_ID,
        2_000_000_000,
        1_700_000_000,
        77.995,
        1_559_900_000,
    ),
    (
        "전북특별자치도",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        JEONBUK_GENERAL_ID,
        3_000_000_000,
        2_600_000_000,
        72.995,
        2_189_850_000,
    ),
    (
        "전북특별자치도",
        "시설분야용역 적격심사 추정가격 5억원 이상",
        JEONBUK_GENERAL_ID,
        4_000_000_000,
        3_500_000_000,
        72.995,
        2_919_800_000,
    ),
    (
        "전북특별자치도",
        "단순노무용역 적격심사 추정가격 5억원 미만",
        JEONBUK_SIMPLE_ID,
        2_000_000_000,
        1_800_000_000,
        87.745,
        1_754_900_000,
    ),
)


@pytest.mark.parametrize(
    (
        "region_name",
        "method",
        "expected_rule_id",
        "presmpt_prce",
        "bid_amount",
        "expected_rate",
        "expected_min_bid",
    ),
    REGION_SPLIT_E2E_CASES,
)
def test_region_split_lwlt_through_analyze_api(
    client,
    isolated_db,
    as_user,
    region_name: str,
    method: str,
    expected_rule_id: str,
    presmpt_prce: int,
    bid_amount: int,
    expected_rate: float,
    expected_min_bid: int,
) -> None:
    """부산·대전·전북 공고가 30억 분할·단순노무 하한율로 최저투찰금액까지 계산한다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name=region_name,
        method=method,
        presmpt_prce=presmpt_prce,
    )

    payload = _analyze(client, bid.id, bid_amount)

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["rule_id"] == expected_rule_id
    assert payload["lower_bound_rate"] == pytest.approx(expected_rate)
    assert any(
        f"낙찰하한율 {expected_rate}% 적용 최저 투찰금액: {expected_min_bid:,}원" in warning
        for warning in payload["warnings"]
    )


def test_chungnam_unknown_price_blocks_with_estimated_price_request(
    client, isolated_db, as_user
) -> None:
    """추정가격을 모르면 대표값으로 추측하지 않고 추정가격 입력을 요구하며 막는다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        method=CHUNGNAM_FISHERY_METHOD,
        presmpt_prce=None,
    )

    payload = _analyze(client, bid.id, 350_000_000)

    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert "LWLT_RATE_UNRESOLVED" in payload["blocked_reason"]
    assert payload["rule_id"] == CHUNGNAM_FISHERY_ID
    assert "추정가격을 입력" in payload["blocked_reason"]


def test_chungnam_user_estimated_price_selects_band(client, isolated_db, as_user) -> None:
    """공고에 추정가격이 없어도 사용자 입력 추정가격으로 구간 하한율을 고른다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        method=CHUNGNAM_FISHERY_METHOD,
        presmpt_prce=None,
        business_budget="900000000",
    )

    payload = _analyze(client, bid.id, 450_000_000, estimated_price=600_000_000)

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["rule_id"] == CHUNGNAM_FISHERY_ID
    assert payload["lower_bound_rate"] == pytest.approx(80.495)


def test_announcement_rate_still_wins_through_analyze_api(client, isolated_db, as_user) -> None:
    """공고 하한율이 있으면 충남 별표 5 도 공고값 그대로 계산한다(종전 동작)."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        method=CHUNGNAM_FISHERY_METHOD,
        presmpt_prce=1_000_000_000,
        announced_rate="87.995",
    )

    payload = _analyze(client, bid.id, 850_000_000)

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["lower_bound_rate"] == pytest.approx(87.995)
    assert not any("구간 하한율" in warning for warning in payload["warnings"])
