"""서울특별시 GENERAL 규칙 10억원 이상 30억원 분할(77.995/72.995) 시험.

정본:
 - .orca/capsules/task_d7afb4a5cee5/capsule.yaml (서울 전용 5구간, 단위·끝단 시험 지시)
 - docs/analysis/local_lwlt_announcement_measure_20261005.md 1장 2번·3장 서울 행
   (10~30억 77.995, 74건 / 30억 이상 72.995, 24건)
 - src/app/services/evaluation_rules.py 의 _measured_lwlt_seoul_five_band_price,
   src/app/services/evaluation_flat_zones.py 의 서울 전용 평탄 매핑

10억원 이상 두 구간값은 공고 실측 최빈값이라 band.source 에 자치법규 원문이 아니라
공고 실측임을 밝힌다. 평가 API 끝단은 mock 없이 TestClient 로 호출하고, 이 워크트리에
모델 파일이 없어 예측 모델만 시험 대역으로 대체한다. 규칙 판별·구간 하한율·최저
투찰금액·점수는 실제 코드가 계산한다.
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
    LOCAL_RULES,
    POST_20260526_RULES,
    POST_20260727_RULES,
    PRE_20230501_RULES,
    PRE_20250901_RULES,
    EvaluationRule,
    RuleResolutionResult,
    resolve_evaluation_rule,
    resolve_score_params,
)

ANALYZE_URL = "/api/v1/evaluations/analyze"

SEOUL_GENERAL_ID = "SERVC_LOCAL_SEOUL_20240812_ATTACH_01"
SEOUL_SIMPLE_ID = "SERVC_LOCAL_SEOUL_20240812_SIMPLE_LABOR"
GENERAL_METHOD = "시설분야용역 적격심사 추정가격 5억원 이상"
SIMPLE_LABOR_METHOD = "단순노무용역 적격심사 추정가격 5억원 미만"
MEASURED_SOURCE_DOC = "docs/analysis/local_lwlt_announcement_measure_20261005.md"

# (상한, 공고 실측 하한율, 구간 라벨). 마지막 두 행이 30억원 경계 분할 구간이다.
SEOUL_BANDS = (
    ("200000000", "87.745", "추정가격 2억원 미만"),
    ("500000000", "86.745", "5억원 미만 2억원 이상"),
    ("1000000000", "85.495", "10억원 미만 5억원 이상"),
    ("3000000000", "77.995", "30억원 미만 10억원 이상"),
    (None, "72.995", "추정가격 30억원 이상"),
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
# 1. 서울 5구간 값과 분할 전 B·k·기준비율 유지
# --------------------------------------------------------------------------- #


def test_seoul_general_has_five_measured_bands() -> None:
    """서울 GENERAL 은 10억원 이상을 30억원 경계로 나눈 5구간이고 값은 공고 실측이다."""
    rule = _rule(SEOUL_GENERAL_ID)
    assert rule.price_bands is not None
    assert len(rule.price_bands) == len(SEOUL_BANDS)
    for band, (upper, rate, label) in zip(rule.price_bands, SEOUL_BANDS, strict=True):
        expected_upper = Decimal(upper) if upper is not None else None
        assert band.upper_bound == expected_upper, upper
        assert band.lwlt_rate == Decimal(rate), upper
        assert band.label == label, upper
        assert MEASURED_SOURCE_DOC in (band.source or ""), upper
        assert "원문 미확인" in (band.source or ""), upper
    # 규칙 대표값은 분할 전과 같은 87.995 로 두어 구간 하한율 없는 경로가 바뀌지 않는다.
    assert rule.lwlt_rate == Decimal("87.995")


def test_seoul_split_bands_keep_pre_split_b_k_base() -> None:
    """분할한 두 구간의 B·k·기준비율은 분할 전 10억원 이상 구간 값(B 30·k 1·0.88) 그대로다."""
    rule = _rule(SEOUL_GENERAL_ID)
    assert rule.price_bands is not None
    for band in rule.price_bands[-2:]:
        assert band.max_price_score == Decimal("30"), band.label
        assert band.multiplier == Decimal("1"), band.label
        assert band.base_rate == Decimal("0.88"), band.label


# (추정가격, 기대 B, 기대 k, 기대 T, 기대 구간 라벨). 30억원 경계값은 이상 쪽 구간이다.
SCORE_PARAM_CASES = (
    ("1000000000", "30", "1", "90", "30억원 미만 10억원 이상"),
    ("1500000000", "30", "1", "90", "30억원 미만 10억원 이상"),
    ("2999999999", "30", "1", "90", "30억원 미만 10억원 이상"),
    ("3000000000", "30", "1", "85", "추정가격 30억원 이상"),
    ("4000000000", "30", "1", "85", "추정가격 30억원 이상"),
    ("50000000000", "30", "1", "85", "추정가격 30억원 이상"),
)


@pytest.mark.parametrize(
    ("price", "expected_b", "expected_k", "expected_t", "band_label"), SCORE_PARAM_CASES
)
def test_seoul_split_keeps_pre_split_score_params(
    price: str, expected_b: str, expected_k: str, expected_t: str, band_label: str
) -> None:
    """30억원 분할 뒤에도 서울의 B·k·기준비율·통과점수는 분할 전과 같다."""
    rule = _rule(SEOUL_GENERAL_ID)
    result = resolve_score_params(rule, Decimal(price), None, None)
    assert result.max_price_score == Decimal(expected_b), price
    assert result.multiplier == Decimal(expected_k), price
    assert result.pass_threshold == Decimal(expected_t), price
    assert (result.base_rate or rule.base_rate) == Decimal("0.88"), price
    assert result.price_band_label == band_label, price


def test_seoul_split_flat_zones_unchanged() -> None:
    """새 상한 키 3000000000 의 평탄은 분할 전 10억원 이상(None)과 같은 값이다."""
    under_30 = flat_zone_for(SEOUL_GENERAL_ID, "3000000000")
    over_30 = flat_zone_for(SEOUL_GENERAL_ID, None)
    assert under_30 is not None
    assert over_30 is not None
    assert under_30.flat_ratio == Decimal("0.98")
    assert under_30.flat_score == Decimal("20")
    assert under_30 == over_30

    # 15억원은 새 30억원 미만 구간을 골라야 분할 전 평탄과 같은 값에 닿는다.
    rule = _rule(SEOUL_GENERAL_ID)
    result = resolve_score_params(rule, Decimal("1500000000"), None, None)
    assert result.price_band_index is not None
    band = rule.price_bands[result.price_band_index]
    assert band.upper_bound == Decimal("3000000000")
    zone = flat_zone_for(SEOUL_GENERAL_ID, band.upper_bound)
    assert zone is not None
    assert zone.flat_ratio == Decimal("0.98")
    assert zone.flat_score == Decimal("20")


# --------------------------------------------------------------------------- #
# 2. 구간 하한율 선택과 경계값 (공고 하한율 없음)
# --------------------------------------------------------------------------- #

# (추정가격, 기대 하한율, 기대 구간 라벨)
BAND_RATE_CASES = (
    ("150000000", "87.745", "추정가격 2억원 미만"),
    ("300000000", "86.745", "5억원 미만 2억원 이상"),
    ("700000000", "85.495", "10억원 미만 5억원 이상"),
    ("1000000000", "77.995", "30억원 미만 10억원 이상"),
    ("1500000000", "77.995", "30억원 미만 10억원 이상"),
    ("2999999999", "77.995", "30억원 미만 10억원 이상"),
    ("3000000000", "72.995", "추정가격 30억원 이상"),
    ("4000000000", "72.995", "추정가격 30억원 이상"),
)


@pytest.mark.parametrize(("price", "expected_rate", "band_label"), BAND_RATE_CASES)
def test_seoul_band_rate_selected_by_price(price: str, expected_rate: str, band_label: str) -> None:
    """공고 하한율이 없으면 추정가격이 고른 구간의 실측 하한율을 쓴다."""
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
    assert any(
        f"별표 구간 하한율({expected_rate}%" in warning and band_label in warning
        for warning in result.warnings
    ), price


def test_seoul_unknown_price_is_not_guessed() -> None:
    """서울은 5개 구간 하한율이 서로 달라 추정가격이 없으면 대표값으로 추측하지 않는다."""
    result = _resolve(
        region_code="11",
        region_name="서울특별시",
        method=GENERAL_METHOD,
        estimated_price=None,
    )
    assert result.rule is not None
    assert result.rule.rule_id == SEOUL_GENERAL_ID
    assert result.is_blocked is False
    assert result.effective_lwlt_rate is None
    assert result.rate_source is None
    assert any("추정가격을 입력해야" in warning for warning in result.warnings)


def test_seoul_announcement_rate_still_wins() -> None:
    """공고 하한율이 있으면 30억원 분할 구간값보다 우선한다(종전 동작)."""
    result = _resolve(
        region_code="11",
        region_name="서울특별시",
        method=GENERAL_METHOD,
        estimated_price="1500000000",
        announcement_rate="89.745",
    )
    assert result.rule is not None
    assert result.effective_lwlt_rate == Decimal("89.745")
    assert result.rate_source == "ANNOUNCEMENT"
    assert not any("구간 하한율" in warning for warning in result.warnings)


def test_seoul_simple_labor_unchanged() -> None:
    """서울 단순노무 규칙은 이번 분할 밖이라 4구간·대표값 87.995% 그대로다."""
    rule = _rule(SEOUL_SIMPLE_ID)
    assert rule.price_bands is not None
    assert len(rule.price_bands) == 4
    assert all(band.lwlt_rate is None for band in rule.price_bands)
    result = _resolve(
        region_code="11",
        region_name="서울특별시",
        method=SIMPLE_LABOR_METHOD,
        estimated_price="4000000000",
    )
    assert result.rule is not None
    assert result.rule.rule_id == SEOUL_SIMPLE_ID
    assert result.effective_lwlt_rate == Decimal("87.995")
    assert result.rate_source == "RULE_DEFAULT"


# --------------------------------------------------------------------------- #
# 3. 다른 규칙 불변 (공유 헬퍼 누수 없음)
# --------------------------------------------------------------------------- #

# main 기준 스냅샷 해시. 서울 GENERAL 만 분할 대상이라 이 목록에서 제외한다.
# 2026-10-06: 인천·제주·강원·경남·경북 04 정정으로 서울 외 LOCAL 규칙 값이 바뀌어 재생성했다.
LOCAL_RULES_EXCLUDING_SEOUL_DIGEST = (
    "8994d3da08bb4c9a0eb52f666a843ca76b51cba05b8f8da211c2f8aa302dfccd"
)
NATIONAL_RULES_DIGEST = "3436d7f5bfa896ec4b4d4f95e1367add414424ab746143fcae364005f8e00e3f"


def _signature(rule: EvaluationRule) -> dict[str, object]:
    """동작에 영향을 주는 필드만 정규화합니다(설명·source 문자열은 제외)."""

    def dec(value: object) -> str | None:
        return None if value is None else str(value)

    return {
        "rule_id": rule.rule_id,
        "lwlt_rate": dec(rule.lwlt_rate),
        "base_rate": dec(rule.base_rate),
        "price_bands": [
            [
                dec(band.upper_bound),
                dec(band.max_price_score),
                dec(band.multiplier),
                dec(band.base_rate),
                dec(band.lwlt_rate),
            ]
            for band in (rule.price_bands or ())
        ],
        "threshold_bands": [
            [dec(band.upper_bound), dec(band.pass_threshold)]
            for band in (rule.threshold_bands or ())
        ],
    }


def _digest(rules: tuple[EvaluationRule, ...]) -> str:
    payload = json.dumps([_signature(rule) for rule in rules], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def test_other_local_rules_unchanged() -> None:
    """서울 GENERAL 을 뺀 46개 LOCAL 규칙은 main 과 같은 동작 필드를 유지한다."""
    rules = tuple(rule for rule in LOCAL_RULES if rule.rule_id != SEOUL_GENERAL_ID)
    assert _digest(rules) == LOCAL_RULES_EXCLUDING_SEOUL_DIGEST


def test_national_rules_unchanged() -> None:
    """조달청 개정 전·후 규칙은 main 과 같은 동작 필드를 유지한다."""
    rules = (
        *PRE_20230501_RULES,
        *PRE_20250901_RULES,
        *POST_20260526_RULES,
        *POST_20260727_RULES,
    )
    assert _digest(rules) == NATIONAL_RULES_DIGEST


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


API_INSTITUTION_CODE = "7000021"


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


def _create_local_bid(db, *, institution_code: str, presmpt_prce: int | None) -> BidAnnouncement:
    """서울 공고(하한율 미기재). sucsfbidLwltRate 키를 넣지 않아 구간 하한율 경로를 탄다."""
    data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": GENERAL_METHOD,
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": institution_code,
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    bid = BidAnnouncement(
        bid_ntce_nm="서울 30억 분할 끝단 시험 공고",
        bid_ntce_no="EVAL-SEOUL-10EOK-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="서울특별시 본청",
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


# (추정가격, 기대 하한율, 기대 최저투찰금액, 구간 라벨, 기대 B, 기대 k, 기대 T,
#  평탄 비율, 평탄 점수, 기대 가격점수). 30억원 경계값은 이상 쪽 구간(72.995%)이다.
# 후보가는 비율 99% 로 두어 산식값이 평탄 점수보다 낮아지게 하고, 30억 분할 뒤에도 평탄이
# 분할 전과 같은 점수로 고정되는지 본다.
API_CASES = (
    (
        700_000_000,
        85.495,
        598_465_000,
        "10억원 미만 5억원 이상",
        "50",
        "2",
        "95",
        "0.905",
        "45",
        45.0,
    ),
    (
        1_500_000_000,
        77.995,
        1_169_925_000,
        "30억원 미만 10억원 이상",
        "30",
        "1",
        "90",
        "0.98",
        "20",
        20.0,
    ),
    (
        3_000_000_000,
        72.995,
        2_189_850_000,
        "추정가격 30억원 이상",
        "30",
        "1",
        "85",
        "0.98",
        "20",
        20.0,
    ),
    (
        4_000_000_000,
        72.995,
        2_919_800_000,
        "추정가격 30억원 이상",
        "30",
        "1",
        "85",
        "0.98",
        "20",
        20.0,
    ),
)


@pytest.mark.parametrize(
    (
        "presmpt_prce",
        "expected_rate",
        "expected_min_bid",
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
def test_seoul_split_lwlt_through_analyze_api(
    client,
    isolated_db,
    as_user,
    presmpt_prce: int,
    expected_rate: float,
    expected_min_bid: int,
    band_label: str,
    expected_b: str,
    expected_k: str,
    expected_t: str,
    flat_ratio: str,
    flat_score: str,
    expected_price_score: float,
) -> None:
    """서울 공고가 구간 하한율·최저투찰금액·평탄 점수를 실제 코드로 계산한다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="서울특별시")
    bid = _create_local_bid(
        isolated_db, institution_code=API_INSTITUTION_CODE, presmpt_prce=presmpt_prce
    )

    payload = _analyze(client, bid.id, int(presmpt_prce * 0.99))

    assert payload["status"] == "success", payload.get("blocked_reason")
    assert payload["blocked"] is False
    assert payload["rule_id"] == SEOUL_GENERAL_ID
    assert payload["lower_bound_rate"] == pytest.approx(expected_rate)
    assert any(
        f"낙찰하한율 {expected_rate}% 적용 최저 투찰금액: {expected_min_bid:,}원" in warning
        for warning in payload["warnings"]
    ), presmpt_prce

    table = payload["score_table"]
    assert table is not None
    assert table["price_band_label"] == band_label
    assert table["max_price_score"] == expected_b
    assert table["multiplier"] == expected_k
    assert table["pass_threshold"] == expected_t
    assert table["flat_ratio"] == flat_ratio
    assert table["flat_score"] == flat_score

    base = next(
        scenario for scenario in payload["scenario_results"] if scenario["scenario_name"] == "기준"
    )
    assert base["price_score"] == pytest.approx(expected_price_score)


def test_seoul_unknown_price_blocks_through_analyze_api(client, isolated_db, as_user) -> None:
    """추정가격이 없는 서울 공고는 규칙까지 확정되지만 하한율 미확정으로 계산이 막힌다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="서울특별시")
    bid = _create_local_bid(isolated_db, institution_code=API_INSTITUTION_CODE, presmpt_prce=None)

    payload = _analyze(client, bid.id, 130_000_000)

    assert payload["status"] == "blocked"
    assert payload["blocked"] is True
    assert "LWLT_RATE_UNRESOLVED" in payload["blocked_reason"]
    assert payload["rule_id"] == SEOUL_GENERAL_ID
    assert "추정가격을 입력" in payload["blocked_reason"]
