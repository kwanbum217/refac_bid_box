"""적격심사 사용자 입력 경로의 배점 상한과 낙찰하한율 미상 처리 계약 시험.

코디네이터 확인 사실(2026-10-20):
  - 가격 배점한도(B)·평점계수(k)·통과점수(T) 는 100 을 넘으면 422 로 거부한다.
  - 두 사용자 입력 경로(LOCAL_RULE_NOT_FOUND·MANUAL_EVALUATION)에서 공고에 낙찰하한율이
    없으면 하한율 0 으로 최저 투찰금액을 만들지 않고 '낙찰하한율 미상' 경고를 남긴다.
  - 공고에 낙찰하한율이 있으면 기존과 같은 값으로 계산한다.

실물 모델·Redis·MySQL 은 호출하지 않는다. conftest 의 isolated_db(SQLite) 위에서 동작한다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.models.demand_institutions import G2BDemandInstitution
from src.app.schemas.evaluations import QualificationInput, RecommendationOverrides
from src.app.schemas.predictions import PredictPriceResponse

ANALYZE_URL = "/api/v1/evaluations/analyze"
RECOMMEND_URL = "/api/v1/evaluations/recommend"
MANUAL_METHOD = "적격심사제-관리규정외 수기심사"
MANUAL_RULE_ID = "SERVC_MANUAL_USER_INPUT"
LOCAL_USER_INPUT_RULE_ID = "SERVC_LOCAL_USER_INPUT"
LWLT_UNKNOWN_WARNING = "낙찰하한율 미상"
PRICE_INPUTS = {
    "max_price_score": 60.0,
    "multiplier": 2.0,
    "pass_threshold": 95.0,
    "base_rate": 0.88,
}
ANNOUNCED_LWLT_RATE = "88.0"


@pytest.fixture
def as_user():
    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def auto_stub_prediction(monkeypatch):
    def _fake_predict(payload, request, db, *args, **kwargs):
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


def _create_institution(db, *, code: str = "1234", toplvl_nm: str = "(없음)") -> None:
    """시·도 규칙이 없는 기관을 만듭니다(코드 1234, (없음) 으로 판별 경로를 엽니다)."""
    db.add(
        G2BDemandInstitution(
            dminstt_cd=code,
            dminstt_nm=f"{toplvl_nm} 본청",
            jrsdctn_div_nm="지방자치단체",
            rgn_cd="28000",
            rgn_nm=f"{toplvl_nm} 남구",
            toplvl_instt_cd="6270000",
            toplvl_instt_nm=toplvl_nm,
            raw_json={},
        )
    )
    db.commit()


def _create_bid(
    db,
    *,
    method: str,
    announced_rate: str | None,
    presmpt_prce: int = 500_000_000,
    notice_no: str = "EVAL-BOUNDS-001",
    local: bool = False,
) -> BidAnnouncement:
    """공고 하나를 만듭니다. announced_rate 가 None 이면 공고에 낙찰하한율이 없습니다."""
    data: dict[str, str] = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": method,
        "srvceDivNm": "일반용역",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    if local:
        # 지방계약(제한경쟁) 판별을 위한 계약방법·수요기관 코드입니다.
        data["cntrctCnlsMthdNm"] = "지방자치단체 제한경쟁"
        data["dminsttCd"] = "1234"
    if announced_rate is not None:
        data["sucsfbidLwltRate"] = announced_rate
    bid = BidAnnouncement(
        bid_ntce_nm="입력 경계 시험 공고",
        bid_ntce_no=notice_no,
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="(없음) 본청",
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


def _create_manual_bid(db, *, announced_rate: str | None = None) -> BidAnnouncement:
    """관리규정외 수기심사 공고. 수요기관 기준정보는 두지 않습니다."""
    return _create_bid(
        db,
        method=MANUAL_METHOD,
        announced_rate=announced_rate,
        notice_no="EVAL-BOUNDS-MANUAL-001",
    )


def _create_local_bid(db, *, announced_rate: str | None = None) -> BidAnnouncement:
    """시·도 규칙이 없는 지방계약 공고(LOCAL_RULE_NOT_FOUND 경로)."""
    return _create_bid(
        db,
        method="일반용역 적격심사 추정가격 5억원 미만",
        announced_rate=announced_rate,
        notice_no="EVAL-BOUNDS-LOCAL-001",
        local=True,
    )


def _analyze(client, bid_id: int, qualification: dict | None = None, amount: int = 440_000_000):
    qualification_input: dict = {"disqualification": False}
    qualification_input.update(qualification or {})
    return client.post(
        ANALYZE_URL,
        json={
            "bid_id": bid_id,
            "selected_model": "requested-evaluation-model",
            "candidate_bid_amount": amount,
            "qualification_input": qualification_input,
        },
    )


def _recommend(client, bid_id: int, overrides: dict | None = None):
    return client.post(
        RECOMMEND_URL,
        json={
            "bid_id": bid_id,
            "selected_model": "requested-evaluation-model",
            "overrides": overrides or {},
        },
    )


# ============================================================================
# (a) B·k·T 위쪽 한도
# ============================================================================


@pytest.mark.parametrize("field_name", ["max_price_score", "multiplier", "pass_threshold"])
def test_score_params_above_100_are_rejected(field_name):
    """B·k·T 는 100 을 넘으면 스키마 단계에서 거부합니다."""
    with pytest.raises(ValidationError):
        QualificationInput(**{field_name: 101.0})


@pytest.mark.parametrize("field_name", ["max_price_score", "multiplier", "pass_threshold"])
def test_score_params_at_100_are_accepted(field_name):
    """B·k·T 의 100 은 허용됩니다(실측 범위 B 20~90·k 0.375~60·T 85~95 를 덮습니다)."""
    qualification = QualificationInput(**{field_name: 100.0})
    assert getattr(qualification, field_name) == 100.0


@pytest.mark.parametrize("field_name", ["max_price_score", "multiplier", "pass_threshold"])
def test_recommend_overrides_above_100_are_rejected(field_name):
    """추천 경로의 수정값도 같은 한도를 둡니다."""
    with pytest.raises(ValidationError):
        RecommendationOverrides(**{field_name: 101.0})


@pytest.mark.parametrize("field_name", ["max_price_score", "multiplier", "pass_threshold"])
def test_analyze_rejects_score_params_above_100(client, isolated_db, as_user, field_name):
    """API 는 한도를 넘는 배점 입력을 422 로 거절합니다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db, announced_rate=ANNOUNCED_LWLT_RATE)

    response = _analyze(
        client,
        bid.id,
        {**PRICE_INPUTS, "manual_non_price_score": 40.0, field_name: 101.0},
    )

    assert response.status_code == 422, response.text


# ============================================================================
# (b) 공고 낙찰하한율이 없을 때
# ============================================================================


def test_manual_without_announcement_rate_hides_min_bid_amount(client, isolated_db, as_user):
    """수기심사 경로: 공고 하한율이 없으면 최저 투찰금액을 비우고 경고를 남깁니다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db, announced_rate=None)

    response = _analyze(client, bid.id, {**PRICE_INPUTS, "manual_non_price_score": 40.0})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["blocked"] is False
    assert payload["rule_id"] == MANUAL_RULE_ID
    # 하한율이 0 으로 남지 않습니다.
    assert payload["lower_bound_rate"] is None
    assert payload["min_bid_amount_with_a"] is None
    assert payload["price_compensation"] is None
    assert any(LWLT_UNKNOWN_WARNING in warning for warning in payload["warnings"])
    # 하한율 0 으로 계산한 최저 투찰금액 경고가 남지 않습니다.
    assert not any("적용 최저 투찰금액" in warning for warning in payload["warnings"])
    # 가격점수·적격 판정은 그대로 계산됩니다.
    base = next(row for row in payload["scenario_results"] if row["scenario_name"] == "기준")
    assert base["price_score"] == pytest.approx(60.0)
    assert base["total_score"] == pytest.approx(100.0)
    assert base["is_qualified"] is True


def test_local_without_announcement_rate_hides_min_bid_amount(client, isolated_db, as_user):
    """LOCAL_RULE_NOT_FOUND 경로도 같은 규칙을 적용합니다."""
    as_user(10)
    _create_institution(isolated_db)
    bid = _create_local_bid(isolated_db, announced_rate=None)

    response = _analyze(client, bid.id, {**PRICE_INPUTS, "manual_non_price_score": 40.0})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["rule_id"] == LOCAL_USER_INPUT_RULE_ID
    assert payload["lower_bound_rate"] is None
    assert payload["min_bid_amount_with_a"] is None
    assert payload["price_compensation"] is None
    assert any(LWLT_UNKNOWN_WARNING in warning for warning in payload["warnings"])
    assert not any("적용 최저 투찰금액" in warning for warning in payload["warnings"])


def test_manual_recommend_without_announcement_rate_hides_min_bid_amount(
    client, isolated_db, as_user
):
    """추천 경로도 최저가를 비우고 하한율 미상을 알립니다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db, announced_rate=None)

    response = _recommend(client, bid.id, {**PRICE_INPUTS, "manual_non_price_score": 40.0})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rule_id"] == MANUAL_RULE_ID
    assert payload["lower_bound_rate"] is None
    bounds = payload["price_bounds"]
    assert bounds is not None
    assert bounds["min_bid_amount"] is None
    assert any(LWLT_UNKNOWN_WARNING in warning for warning in payload["warnings"])


def test_local_recommend_without_announcement_rate_hides_min_bid_amount(
    client, isolated_db, as_user
):
    """LOCAL_RULE_NOT_FOUND 경로의 추천 응답도 최저가를 비웁니다."""
    as_user(10)
    _create_institution(isolated_db)
    bid = _create_local_bid(isolated_db, announced_rate=None)

    response = _recommend(client, bid.id, {**PRICE_INPUTS, "manual_non_price_score": 40.0})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["rule_id"] == LOCAL_USER_INPUT_RULE_ID
    assert payload["lower_bound_rate"] is None
    bounds = payload["price_bounds"]
    assert bounds is not None
    assert bounds["min_bid_amount"] is None
    assert any(LWLT_UNKNOWN_WARNING in warning for warning in payload["warnings"])


# ============================================================================
# (c) 공고 낙찰하한율이 있을 때 기존 동작 유지
# ============================================================================


def test_manual_with_announcement_rate_keeps_min_bid_amount(client, isolated_db, as_user):
    """공고 하한율이 있으면 기존과 같은 최저 투찰금액을 계산합니다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db, announced_rate=ANNOUNCED_LWLT_RATE)

    response = _analyze(client, bid.id, {**PRICE_INPUTS, "manual_non_price_score": 40.0})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["lower_bound_rate"] == pytest.approx(88.0)
    # 예정가격 5억원 * 88% = 4억 4천원.
    assert any("최저 투찰금액: 440,000,000원" in warning for warning in payload["warnings"])
    assert not any(LWLT_UNKNOWN_WARNING in warning for warning in payload["warnings"])
    compensation = payload["price_compensation"]
    assert compensation is not None
    assert compensation["announcement_lwlt_rate"] == "88"


def test_local_with_announcement_rate_keeps_min_bid_amount(client, isolated_db, as_user):
    """LOCAL_RULE_NOT_FOUND 경로도 공고 하한율이 있으면 같은 금액을 계산합니다."""
    as_user(10)
    _create_institution(isolated_db)
    bid = _create_local_bid(isolated_db, announced_rate=ANNOUNCED_LWLT_RATE)

    response = _analyze(client, bid.id, {**PRICE_INPUTS, "manual_non_price_score": 40.0})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["lower_bound_rate"] == pytest.approx(88.0)
    assert any("최저 투찰금액: 440,000,000원" in warning for warning in payload["warnings"])
    assert not any(LWLT_UNKNOWN_WARNING in warning for warning in payload["warnings"])


def test_announced_rate_zero_is_treated_as_unknown(client, isolated_db, as_user):
    """공고 하한율이 0 이면 미상으로 처리하고 0 을 노출하지 않습니다."""
    as_user(10)
    bid = _create_manual_bid(isolated_db, announced_rate="0")

    response = _analyze(client, bid.id, {**PRICE_INPUTS, "manual_non_price_score": 40.0})

    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["lower_bound_rate"] is None
    assert any(LWLT_UNKNOWN_WARNING in warning for warning in payload["warnings"])
