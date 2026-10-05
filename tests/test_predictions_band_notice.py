"""규모 구간 대체 안내와 구간별 낙찰하한율 정합 시험.

정본:
 - src/app/api/v1/predictions.py 의 _band_price_from_prediction_reference 와
   _band_specific_lwlt_rate
 - src/app/services/evaluation_rules.py 의 PriceBand.lwlt_rate, _apply_rule_lwlt
 - 종전 구간별 하한율 시험: tests/test_local_band_lwlt.py

평가 API 끝단은 mock 없이 TestClient 로 호출합니다. 예측 모델만 이 워크트리에 모델 파일이
없어 시험 대역으로 대체하며, 규칙 판별·구간 선택·구간 하한율 경로는 실제 코드입니다.
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
from src.app.services.evaluation_scoring import calculate_min_bid_amount
from src.ml.model_registry import PredictionOutcome

PREDICT_URL = "/api/v1/predictions/predict-price"
ANALYZE_URL = "/api/v1/evaluations/analyze"

API_INSTITUTION_CODE = "7000044"
CHUNGNAM_FISHERY_METHOD = "적격심사제-어장정화·정비용역"
FACILITY_METHOD = "시설분야용역 적격심사 추정가격 5억원 미만"
BUSAN_METHOD = "시설분야용역 적격심사 추정가격 5억원 이상"

# B=70, k=2, T=40, Q=10 -> N=30, 허용차 (70-30)/200 = 0.2.
# 점수 통과 하한이 구간 하한율보다 낮아 하한율이 실질 하한으로 드러난다.
SCORE_TABLE = {
    "max_price_score": 70.0,
    "multiplier": 2.0,
    "pass_threshold": 40.0,
    "non_price_score": 10.0,
}

SUBSTITUTION_PHRASE = "예측 기준금액으로 규모 구간을 판정"


@pytest.fixture(autouse=True)
def stub_prediction_models(monkeypatch):
    """예측 모델만 대역으로 바꾸고 규칙 판별·구간 하한율 경로는 실제 코드를 쓴다."""
    outcome = PredictionOutcome(
        predicted_rate=0.88,
        requested_model="test-model",
        actual_model="test-model",
        fallback_used=False,
        fallback_reason=None,
    )
    wrapper = SimpleNamespace(get_display_name=lambda: "테스트 모델")
    monkeypatch.setattr(
        "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
        lambda *args, **kwargs: outcome,
    )
    monkeypatch.setattr(
        "src.app.api.v1.predictions.predict_interval",
        lambda *args, **kwargs: (80.0, 85.0, 0.9),
    )
    monkeypatch.setattr(
        "src.app.api.v1.predictions.ModelRegistry.get_model",
        lambda *args, **kwargs: wrapper,
    )

    def _fake_predict(payload, request, db):
        return PredictPriceResponse(
            status="success",
            optimal_price=440_000_000,
            prediction_rate=88.0,
            model_name="테스트 모델",
            model_id=payload.selected_model or "test-model",
            requested_model=payload.selected_model or "test-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


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
    base_amount: int | None = None,
    business_budget: str | None = None,
    region_name: str = "충청남도",
    announced_rate: str | None = None,
    bid_no: str = "PRED-BAND-001",
) -> BidAnnouncement:
    raw_data: dict[str, str] = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "srvceDivNm": "일반용역",
        "cntrctCnclsMthdNm": "지방자치단체 제한경쟁",
        "dminsttCd": institution_code,
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    if business_budget is not None:
        raw_data["asignBdgtAmt"] = business_budget
    if announced_rate is not None:
        raw_data["sucsfbidLwltRate"] = announced_rate
    bid = BidAnnouncement(
        bid_ntce_nm="구간 하한율 예측 끝단 시험 공고",
        bid_ntce_no=bid_no,
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm=f"{region_name} 본청",
        base_amount=base_amount if base_amount is not None else presmpt_prce,
        presmpt_prce=presmpt_prce,
        bid_ntce_dt=utcnow(),
        bid_clse_dt=utcnow(),
        openg_dt=utcnow(),
        category="Servc",
        raw_data=raw_data,
    )
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _predict(client, bid_id: int, **extra):
    payload = {"bid_id": bid_id, "user_price": "0"}
    payload.update(extra)
    return client.post(PREDICT_URL, json=payload)


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
            "selected_model": "requested-model",
            "candidate_bid_amount": bid_amount,
            "qualification_input": qualification,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


# --------------------------------------------------------------------------- #
# 1. 규모 구간 대체 안내 (추정가격 없이 예측 기준금액 사용)
# --------------------------------------------------------------------------- #


def test_substitution_notice_present_when_estimated_price_missing(
    client, isolated_db, as_user
) -> None:
    """추정가격이 없어 예측 기준금액으로 구간을 대체하면 안내와 구간 하한율이 함께 온다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        method=CHUNGNAM_FISHERY_METHOD,
        presmpt_prce=None,
        business_budget="400000000",
    )

    response = _predict(client, bid.id, **SCORE_TABLE)

    assert response.status_code == 200, response.text
    data = response.json()
    assert SUBSTITUTION_PHRASE in (data["uncertainty_warning"] or "")
    # 대체된 기준금액으로 고른 구간 하한율(87.995%)이 유효 하한으로 반영된다.
    verdict = data["score_verdict"]
    expected = calculate_min_bid_amount(Decimal("400000000"), Decimal("87.995")).min_bid_amount
    assert verdict["effective_amount_low"] == int(expected)
    # 같은 입력을 /evaluations 는 사용자 입력 추정가격으로 같은 구간 하한율을 쓴다.
    payload = _analyze(client, bid.id, 350_000_000, estimated_price=400_000_000)
    assert payload["lower_bound_rate"] == pytest.approx(87.995)


def test_no_substitution_notice_when_estimated_price_present(client, isolated_db) -> None:
    """추정가격이 있으면 구간 대체 안내가 붙지 않는다."""
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        method=CHUNGNAM_FISHERY_METHOD,
        presmpt_prce=400_000_000,
    )

    response = _predict(client, bid.id, **SCORE_TABLE)

    assert response.status_code == 200, response.text
    assert SUBSTITUTION_PHRASE not in (response.json()["uncertainty_warning"] or "")


# --------------------------------------------------------------------------- #
# 2. 구간별 낙찰하한율이 /evaluations 와 같은지 (충남 별표 5, 부산 일반 띠)
# --------------------------------------------------------------------------- #

BAND_LWLT_CASES = (
    ("충청남도", CHUNGNAM_FISHERY_METHOD, 400_000_000, "87.995"),
    ("충청남도", CHUNGNAM_FISHERY_METHOD, 1_000_000_000, "80.495"),
    ("부산광역시", BUSAN_METHOD, 2_000_000_000, "77.995"),
    ("부산광역시", BUSAN_METHOD, 4_000_000_000, "72.995"),
)


@pytest.mark.parametrize(
    ("region_name", "method", "presmpt_prce", "expected_rate"), BAND_LWLT_CASES
)
def test_predictions_lwlt_matches_evaluations(
    client,
    isolated_db,
    as_user,
    region_name: str,
    method: str,
    presmpt_prce: int,
    expected_rate: str,
) -> None:
    """/predictions 의 유효 하한율이 /evaluations 와 같은 구간값으로 계산된다."""
    as_user(10)
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm=region_name)
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        region_name=region_name,
        method=method,
        presmpt_prce=presmpt_prce,
        bid_no=f"PRED-BAND-{presmpt_prce}",
    )

    response = _predict(client, bid.id, **SCORE_TABLE)

    assert response.status_code == 200, response.text
    verdict = response.json()["score_verdict"]
    assert verdict["verifiable"] is True
    assert verdict["pass_range_status"] == "feasible"  # noqa: S105 - 판정 상태값
    expected_lwlt = calculate_min_bid_amount(
        Decimal(str(presmpt_prce)), Decimal(expected_rate)
    ).min_bid_amount
    assert verdict["effective_amount_low"] == int(expected_lwlt)
    # 하한율이 실제로 범위를 좁혔는지 확인한다(미반영이면 점수 하한과 같아진다).
    assert verdict["effective_amount_low"] > verdict["pass_amount_low"]

    payload = _analyze(client, bid.id, presmpt_prce * 4 // 5)
    assert payload["lower_bound_rate"] == pytest.approx(float(expected_rate))


# --------------------------------------------------------------------------- #
# 3. 구간 하한율이 없는 규칙은 종전과 같이 점수 구간 그대로 (불변)
# --------------------------------------------------------------------------- #


def test_rule_without_band_rate_keeps_score_range(client, isolated_db) -> None:
    """구간 하한율이 없는 규칙은 규칙 대표값을 끌어오지 않아 유효 구간이 점수 구간과 같다."""
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        method=FACILITY_METHOD,
        presmpt_prce=600_000_000,
    )

    response = _predict(client, bid.id, **SCORE_TABLE)

    assert response.status_code == 200, response.text
    data = response.json()
    assert SUBSTITUTION_PHRASE not in (data["uncertainty_warning"] or "")
    verdict = data["score_verdict"]
    assert verdict["verifiable"] is True
    assert verdict["pass_range_status"] == "feasible"  # noqa: S105 - 판정 상태값
    assert verdict["effective_amount_low"] == verdict["pass_amount_low"]
    assert verdict["effective_amount_high"] == verdict["pass_amount_high"]


def test_announcement_rate_wins_over_band_rate(client, isolated_db) -> None:
    """공고 하한율이 있으면 구간 하한율보다 우선한다(종전 동작 불변)."""
    _create_institution(isolated_db, code=API_INSTITUTION_CODE, toplvl_nm="충청남도")
    bid = _create_local_bid(
        isolated_db,
        institution_code=API_INSTITUTION_CODE,
        method=CHUNGNAM_FISHERY_METHOD,
        presmpt_prce=1_000_000_000,
        announced_rate="87.995",
    )

    response = _predict(client, bid.id, **SCORE_TABLE)

    assert response.status_code == 200, response.text
    verdict = response.json()["score_verdict"]
    expected = calculate_min_bid_amount(Decimal("1000000000"), Decimal("87.995")).min_bid_amount
    assert verdict["effective_amount_low"] == int(expected)
