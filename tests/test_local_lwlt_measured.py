"""LOCAL GENERAL 규칙 6개의 공고 실측 구간 하한율 시험.

정본:
 - docs/analysis/local_lwlt_announcement_measure_20261005.md 6.1절 (공고 실측 최빈값)
 - .orca/capsules/task_g1_lwlt_measured/capsule.yaml (대상 rule_id·구간 값)
 - src/app/services/evaluation_rules.py 의 PriceBand.lwlt_rate 와 _apply_rule_lwlt

공고 실측값은 자치법규 원문이 인쇄한 값이 아니므로 규칙 대표값은 바꾸지 않는다. 서울 01
만 10억원 이상을 30억원 경계로 나눠 77.995%·72.995% 를 쓴다. 평가 API 끝단은 mock 없이
TestClient 로 호출하고, 이 워크트리에 모델 파일이 없어 예측 모델만 시험 대역으로 대체한다.
규칙 판별·구간 하한율·최저 투찰금액은 실제 코드다.
"""

from __future__ import annotations

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

INCHEON_ID = "SERVC_LOCAL_INCHEON_20251224_ATTACH_01"
JEJU_ID = "SERVC_LOCAL_JEJU_20240101_ATTACH_01"
GANGWON_ID = "SERVC_LOCAL_GANGWON_20230611_ATTACH_01"
GB_GENERAL_ID = "SERVC_LOCAL_GB_20260108_ATTACH_04"
GN_GENERAL_ID = "SERVC_LOCAL_GN_20230105_ATTACH_01"
SEOUL_GENERAL_ID = "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"

TARGET_RULE_IDS = (
    INCHEON_ID,
    JEJU_ID,
    GANGWON_ID,
    GB_GENERAL_ID,
    GN_GENERAL_ID,
    SEOUL_GENERAL_ID,
)

REGION_BY_RULE: dict[str, tuple[str, str]] = {
    INCHEON_ID: ("28", "인천광역시"),
    JEJU_ID: ("50", "제주특별자치도"),
    GANGWON_ID: ("51", "강원특별자치도"),
    GB_GENERAL_ID: ("47", "경상북도"),
    GN_GENERAL_ID: ("48", "경상남도"),
    SEOUL_GENERAL_ID: ("11", "서울특별시"),
}

# 시설분야 별표가 없는 6곳이라 시설분야 표기는 일반 별표로 내려간다(다른 시험과 같은 경로).
GENERAL_METHOD = "시설분야용역 적격심사 추정가격 5억원 이상"
SIMPLE_LABOR_METHOD = "단순노무용역 적격심사 추정가격 5억원 미만"
SW_METHOD = "소프트웨어용역 적격심사 추정가격 5억원 미만"
INSURANCE_METHOD = "보험용역 적격심사 추정가격 5억원 미만"

# (상한, 공고 실측 하한율, 구간 라벨). 보고서 6.1절 10억원 미만 3개 구간.
MEASURED_UNDER_1B = (
    ("200000000", "87.745", "추정가격 2억원 미만"),
    ("500000000", "86.745", "5억원 미만 2억원 이상"),
    ("1000000000", "85.495", "10억원 미만 5억원 이상"),
)
MEASURED_SOURCE_DOC = "docs/analysis/local_lwlt_announcement_measure_20261005.md"


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
    announcement_rate: str | None = None,
) -> RuleResolutionResult:
    return resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm=method,
        sucsfbid_lwlt_rate=announcement_rate,
        contract_regime="LOCAL",
        bid_ntce_dt="2026-08-01",
        region_code=region_code,
        region_name=region_name,
        raw_data={"sucsfbidMthdNm": method},
        estimated_price=estimated_price,
    )


# --------------------------------------------------------------------------- #
# 1. 10억원 미만 3개 구간 하한율과 10억원 이상 대표값 유지
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule_id", TARGET_RULE_IDS)
def test_under_1b_bands_carry_measured_lwlt(rule_id: str) -> None:
    """대상 규칙의 10억원 미만 3개 구간이 보고서 6.1절 실측값과 일치한다.

    서울 01 은 10억원 이상이 30억원 경계로 갈려 5구간이다.
    """
    rule = _rule(rule_id)
    bands = rule.price_bands or ()
    assert len(bands) == (5 if rule_id == SEOUL_GENERAL_ID else 4), rule_id
    for band, (upper, rate, label) in zip(bands, MEASURED_UNDER_1B, strict=False):
        assert band.upper_bound == Decimal(upper), (rule_id, upper)
        assert band.lwlt_rate == Decimal(rate), (rule_id, upper)
        assert band.label == label, (rule_id, upper)
        assert MEASURED_SOURCE_DOC in (band.source or ""), rule_id
        assert "원문 미확인" in (band.source or ""), rule_id


NON_SEOUL_RULE_IDS = tuple(rule_id for rule_id in TARGET_RULE_IDS if rule_id != SEOUL_GENERAL_ID)


@pytest.mark.parametrize("rule_id", NON_SEOUL_RULE_IDS)
def test_ten_eok_and_above_keeps_rule_default(rule_id: str) -> None:
    """서울을 뺀 5개 규칙의 10억원 이상 구간은 하한율을 비워 규칙 대표값 87.995%를 쓴다."""
    rule = _rule(rule_id)
    assert rule.lwlt_rate == Decimal("87.995"), rule_id
    assert rule.price_bands is not None
    assert rule.price_bands[-1].upper_bound is None
    assert rule.price_bands[-1].lwlt_rate is None, rule_id
    code, name = REGION_BY_RULE[rule_id]
    for price in ("1000000000", "1500000000", "4000000000"):
        result = _resolve(
            region_code=code,
            region_name=name,
            method=GENERAL_METHOD,
            estimated_price=price,
        )
        assert result.rule is not None
        assert result.rule.rule_id == rule_id
        assert result.effective_lwlt_rate == Decimal("87.995"), (rule_id, price)
        assert result.rate_source == "RULE_DEFAULT"
        assert any("별표 기본값(87.995%)" in warning for warning in result.warnings)
        assert not any("구간 하한율" in warning for warning in result.warnings)


def test_seoul_ten_eok_and_above_splits_at_30eok() -> None:
    """서울 01 은 10억원 이상을 30억원 경계로 나눠 실측 하한율 77.995/72.995 를 쓴다.

    30억원 경계값은 상위 구간(이상 쪽)에 속한다.
    """
    rule = _rule(SEOUL_GENERAL_ID)
    assert rule.lwlt_rate == Decimal("87.995")
    assert rule.price_bands is not None
    assert [band.lwlt_rate for band in rule.price_bands[-2:]] == [
        Decimal("77.995"),
        Decimal("72.995"),
    ]
    assert rule.price_bands[-1].upper_bound is None
    for price, expected_rate in (
        ("1000000000", "77.995"),
        ("1500000000", "77.995"),
        ("3000000000", "72.995"),
        ("4000000000", "72.995"),
    ):
        result = _resolve(
            region_code="11",
            region_name="서울특별시",
            method=GENERAL_METHOD,
            estimated_price=price,
        )
        assert result.rule is not None
        assert result.rule.rule_id == SEOUL_GENERAL_ID
        assert result.effective_lwlt_rate == Decimal(expected_rate), price
        assert result.rate_source == "RULE_DEFAULT"
        assert any("별표 구간 하한율" in warning for warning in result.warnings), price


# (rule_id, 추정가격, 기대 하한율, 구간 라벨)
PRICE_CASES = tuple(
    (rule_id, price, rate, label)
    for rule_id in TARGET_RULE_IDS
    for price, rate, label in (
        ("150000000", "87.745", "추정가격 2억원 미만"),
        ("300000000", "86.745", "5억원 미만 2억원 이상"),
        ("700000000", "85.495", "10억원 미만 5억원 이상"),
    )
)


@pytest.mark.parametrize(("rule_id", "price", "expected_rate", "band_label"), PRICE_CASES)
def test_measured_band_rate_selected_by_price(
    rule_id: str, price: str, expected_rate: str, band_label: str
) -> None:
    """공고 하한율이 없으면 추정가격이 고른 구간의 공고 실측 하한율을 쓴다."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price=price,
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal(expected_rate), (rule_id, price)
    assert result.rate_source == "RULE_DEFAULT"
    assert any(
        f"별표 구간 하한율({expected_rate}%" in warning and band_label in warning
        for warning in result.warnings
    ), (rule_id, price)


BOUNDARY_CASES = (
    ("199999999", "87.745"),
    ("200000000", "86.745"),
    ("499999999", "86.745"),
    ("500000000", "85.495"),
)


@pytest.mark.parametrize(("price", "expected_rate"), BOUNDARY_CASES)
def test_band_boundaries_follow_upper_band(price: str, expected_rate: str) -> None:
    """경계값(2억·5억)은 이상 쪽 구간에 속한다. 경북 04 의 분할 경계도 같다."""
    code, name = REGION_BY_RULE[GB_GENERAL_ID]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price=price,
    )
    assert result.rule is not None
    assert result.rule.rule_id == GB_GENERAL_ID
    assert result.effective_lwlt_rate == Decimal(expected_rate), price


# --------------------------------------------------------------------------- #
# 2. 추정가격 미상 차단과 공고 하한율 우선
# --------------------------------------------------------------------------- #


@pytest.mark.parametrize("rule_id", TARGET_RULE_IDS)
def test_unknown_price_is_not_guessed(rule_id: str) -> None:
    """구간별 하한율이 서로 다른데 추정가격이 없으면 대표값으로 추측하지 않는다."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price=None,
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.is_blocked is False
    assert result.effective_lwlt_rate is None, rule_id
    assert result.rate_source is None
    assert any("추정가격을 입력해야" in warning for warning in result.warnings)


@pytest.mark.parametrize("rule_id", TARGET_RULE_IDS)
def test_announcement_rate_wins_over_measured_band(rule_id: str) -> None:
    """공고 하한율이 있으면 공고 실측 구간값보다 우선한다(종전 동작)."""
    code, name = REGION_BY_RULE[rule_id]
    result = _resolve(
        region_code=code,
        region_name=name,
        method=GENERAL_METHOD,
        estimated_price="150000000",
        announcement_rate="89.745",
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal("89.745")
    assert result.rate_source == "ANNOUNCEMENT"
    assert not any("구간 하한율" in warning for warning in result.warnings)


# --------------------------------------------------------------------------- #
# 3. 다른 규칙 불변 (공유 헬퍼 누수 없음)
# --------------------------------------------------------------------------- #

INCHEON_SIMPLE_ID = "SERVC_LOCAL_INCHEON_20251224_SIMPLE_LABOR"
JEJU_SIMPLE_ID = "SERVC_LOCAL_JEJU_20240101_SIMPLE_LABOR"
GANGWON_SIMPLE_ID = "SERVC_LOCAL_GANGWON_20230611_SIMPLE_LABOR"
SEOUL_SIMPLE_ID = "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR"
GB_SW_ID = "SERVC_LOCAL_GB_20260108_ATTACH_02"
GG_INSURANCE_ID = "SERVC_LOCAL_GG_20250808_ATTACH_1_5"

# (rule_id, 지역코드, 지역명, 낙찰방법명, 규칙 대표값). 모두 구간 하한율이 없어야 한다.
UNCHANGED_CASES = (
    (INCHEON_SIMPLE_ID, "28", "인천광역시", SIMPLE_LABOR_METHOD, "87.995"),
    (JEJU_SIMPLE_ID, "50", "제주특별자치도", SIMPLE_LABOR_METHOD, "87.995"),
    (GANGWON_SIMPLE_ID, "51", "강원특별자치도", SIMPLE_LABOR_METHOD, "87.995"),
    (SEOUL_SIMPLE_ID, "11", "서울특별시", SIMPLE_LABOR_METHOD, "87.995"),
    (GB_SW_ID, "47", "경상북도", SW_METHOD, "87.995"),
    (GG_INSURANCE_ID, "41", "경기도", INSURANCE_METHOD, "47.995"),
)


@pytest.mark.parametrize(("rule_id", "code", "name", "method", "expected_rate"), UNCHANGED_CASES)
def test_unrelated_rules_keep_rule_default(
    rule_id: str, code: str, name: str, method: str, expected_rate: str
) -> None:
    """같은 구간 구조를 쓰는 다른 규칙은 구간 하한율이 생기지 않고 대표값 경로 그대로다."""
    rule = _rule(rule_id)
    bands = rule.price_bands or ()
    assert bands, rule_id
    assert all(band.lwlt_rate is None for band in bands), rule_id
    result = _resolve(
        region_code=code,
        region_name=name,
        method=method,
        estimated_price="300000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == rule_id
    assert result.effective_lwlt_rate == Decimal(expected_rate)
    assert result.rate_source == "RULE_DEFAULT"
    assert any("별표 기본값" in warning for warning in result.warnings)
    assert not any("구간 하한율" in warning for warning in result.warnings)


def test_national_facility_rule_unchanged() -> None:
    """조달청 규칙은 이번 변경 밖이라 대표값 89.995% 그대로다."""
    result = resolve_evaluation_rule(
        category="Servc",
        prearng_prce_dcsn_mthd_nm="복수예가",
        sucsfbid_mthd_nm="적격심사제-시설분야용역 적격심사 추정가격 5억원 미만",
        bid_ntce_dt="2026-08-01",
        estimated_price="600000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == "SERVC_QUAL_POST_20260526_ATTACH_01"
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


API_INSTITUTION_CODE = "7000009"


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
    presmpt_prce: int | None,
) -> BidAnnouncement:
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": institution_code,
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    bid = BidAnnouncement(
        bid_ntce_nm="공고 실측 구간 하한율 끝단 시험 공고",
        bid_ntce_no="EVAL-MEASURED-LWLT-001",
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


def _analyze(client, bid_id: int, bid_amount: int) -> dict:
    response = client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid_id,
            "selected_model": "requested-evaluation-model",
            "candidate_bid_amount": bid_amount,
            "qualification_input": {"disqualification": False, "manual_non_price_score": 40.0},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# (지역명, 규칙 ID, 추정가격, 기대 하한율, 기대 최저투찰금액). 10억원 이상은 규칙 대표값이고,
# 서울 01 만 30억원 경계 분할값(15억원 77.995%, 30억원 이상 72.995%)을 쓴다.
DEFAULT_TOP_PRICE_CASE = (1_500_000_000, 87.995, 1_319_925_000)
SEOUL_TOP_PRICE_CASE = (1_500_000_000, 77.995, 1_169_925_000)
API_CASES = tuple(
    (REGION_BY_RULE[rule_id][1], rule_id, presmpt_prce, expected_rate, expected_min_bid)
    for rule_id in TARGET_RULE_IDS
    for presmpt_prce, expected_rate, expected_min_bid in (
        (150_000_000, 87.745, 131_617_500),
        (300_000_000, 86.745, 260_235_000),
        (700_000_000, 85.495, 598_465_000),
        SEOUL_TOP_PRICE_CASE if rule_id == SEOUL_GENERAL_ID else DEFAULT_TOP_PRICE_CASE,
    )
)


@pytest.mark.parametrize(
    (
        "region_name",
        "expected_rule_id",
        "presmpt_prce",
        "expected_rate",
        "expected_min_bid",
    ),
    API_CASES,
)
def test_measured_lwlt_through_analyze_api(
    client,
    isolated_db,
    as_user,
    region_name: str,
    expected_rule_id: str,
    presmpt_prce: int,
    expected_rate: float,
    expected_min_bid: int,
) -> None:
    """6개 규칙이 실제 평가 API 에서 공고 실측 구간 하한율과 최저투찰금액을 그대로 쓴다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name=region_name,
        method=GENERAL_METHOD,
        presmpt_prce=presmpt_prce,
    )

    payload = _analyze(client, bid.id, expected_min_bid)

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["blocked"] is False
    assert payload["rule_id"] == expected_rule_id
    assert payload["lower_bound_rate"] == pytest.approx(expected_rate)
    assert any(
        f"낙찰하한율 {expected_rate}% 적용 최저 투찰금액: {expected_min_bid:,}원" in warning
        for warning in payload["warnings"]
    ), (expected_rule_id, presmpt_prce)


UNKNOWN_PRICE_API_CASES = tuple(
    (REGION_BY_RULE[rule_id][1], rule_id) for rule_id in TARGET_RULE_IDS
)


@pytest.mark.parametrize(("region_name", "expected_rule_id"), UNKNOWN_PRICE_API_CASES)
def test_unknown_price_blocks_through_analyze_api(
    client, isolated_db, as_user, region_name: str, expected_rule_id: str
) -> None:
    """추정가격이 없는 공고는 규칙까지 확정되지만 하한율 미확정으로 계산이 막힌다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        institution_name=region_name,
        method=GENERAL_METHOD,
        presmpt_prce=None,
    )

    payload = _analyze(client, bid.id, 130_000_000)

    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert "LWLT_RATE_UNRESOLVED" in payload["blocked_reason"]
    assert payload["rule_id"] == expected_rule_id
    assert "추정가격을 입력" in payload["blocked_reason"]
