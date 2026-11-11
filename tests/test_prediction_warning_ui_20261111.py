"""투찰가 예측 불확실성 경고가 화면까지 도달하는지 고정합니다.

I-ai 검토 F-01 잔여, F-10 시험 공백 대응입니다. predict_price_api 가 만든 경고
(extreme_prediction_warning, wide_interval_warning, lwlt_missing,
uncertainty_warning)를 /evaluations/recommend 응답의 prediction 에 전달하고,
상세 화면이 그 값을 읽어 표시하는지 확인합니다. 실제 모델 추론과 실물 서비스는
호출하지 않습니다.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from src.app.api.v1 import evaluations
from src.app.api.v1.evaluations import require_current_user
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.bids import BidAnnouncement
from src.app.schemas.evaluations import RecommendationPrediction
from src.app.schemas.predictions import PredictPriceResponse

RECOMMEND_URL = "/api/v1/evaluations/recommend"
TEMPLATE = Path(__file__).resolve().parents[1] / "src/app/templates/bids/detail.html"

WARNING_FIELDS = (
    "extreme_prediction_warning",
    "wide_interval_warning",
    "lwlt_missing",
    "uncertainty_warning",
)
UNCERTAINTY_MESSAGE = "낙찰하한율 근거가 없고 예측 구간이 넓어 신뢰도가 낮습니다."
SCORE_TABLE_OVERRIDES = {
    "max_price_score": 60.0,
    "multiplier": 2.0,
    "pass_threshold": 95.0,
    "quant_items": {"performance": 20.0, "labor_plan": 10.0},
}


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


def _create_bid(db) -> BidAnnouncement:
    raw_data = {
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": "시설분야용역 적격심사 추정가격 5억원 이상",
        "sucsfbidLwltRate": "89.995",
        "srvceDivNm": "일반용역",
        "totPrdprcNum": "12",
        "drwtPrdprcNum": "3",
    }
    bid = BidAnnouncement(
        bid_ntce_nm="예측 경고 표시 테스트 공고",
        bid_ntce_no="PRED-WARN-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=500_000_000,
        presmpt_prce=500_000_000,
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


def _recommend(client, bid):
    return client.post(
        RECOMMEND_URL,
        json={"bid_id": bid.id, "overrides": dict(SCORE_TABLE_OVERRIDES)},
    )


def _warning_response() -> PredictPriceResponse:
    return PredictPriceResponse(
        status="success",
        optimal_price=440_000_000,
        prediction_rate=100.0,
        model_name="경고 대역 모델",
        model_id="warning-model",
        requested_model="warning-model",
        fallback_used=False,
        message="테스트용 예측 대역 응답",
        extreme_prediction_warning=True,
        wide_interval_warning=True,
        lwlt_missing=True,
        uncertainty_warning=UNCERTAINTY_MESSAGE,
    )


def test_recommendation_prediction_schema_exposes_warning_fields():
    for field in WARNING_FIELDS:
        assert field in RecommendationPrediction.model_fields, (
            f"RecommendationPrediction 에 {field} 가 없습니다"
        )


def test_recommend_response_carries_prediction_warnings(client, isolated_db, as_user, monkeypatch):
    """/evaluations/recommend 가 예측 경고 4필드를 prediction 으로 전달한다."""
    as_user(10)
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        evaluations, "predict_price_api", lambda *args, **kwargs: _warning_response()
    )

    response = _recommend(client, bid)

    assert response.status_code == 200, response.text
    prediction = response.json()["prediction"]
    assert prediction is not None
    assert prediction["extreme_prediction_warning"] is True
    assert prediction["wide_interval_warning"] is True
    assert prediction["lwlt_missing"] is True
    assert prediction["uncertainty_warning"] == UNCERTAINTY_MESSAGE


def test_recommend_fallback_keeps_warning_defaults(client, isolated_db, as_user, monkeypatch):
    """예측 예외 경로에서는 경고 필드가 기본값으로 남는다."""

    def _raise(*args, **kwargs):
        raise HTTPException(status_code=503, detail="모델 사용 불가")

    as_user(10)
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(evaluations, "predict_price_api", _raise)

    response = _recommend(client, bid)

    assert response.status_code == 200, response.text
    prediction = response.json()["prediction"]
    assert prediction is not None
    assert prediction["fallback_used"] is True
    assert prediction["extreme_prediction_warning"] is False
    assert prediction["wide_interval_warning"] is False
    assert prediction["lwlt_missing"] is False
    assert prediction["uncertainty_warning"] is None


def test_detail_template_reads_prediction_warnings():
    """상세 화면이 경고 영역을 갖고 경고 필드를 textContent 로 표시한다."""
    markup = TEMPLATE.read_text(encoding="utf-8")

    assert 'id="res-prediction-warning"' in markup
    for field in WARNING_FIELDS:
        assert f"prediction.{field}" in markup, f"템플릿이 {field} 를 읽지 않습니다"

    assert "모델 예측이 경계값에 가까워 신뢰도가 낮습니다" in markup
    assert "$('#res-prediction-warning-message').text(uncertainty)" in markup
    # 경고가 하나도 없으면 영역을 숨긴다.
    assert "!(extreme || uncertainty || wide || lwlt)" in markup
    # 경고 문자열을 HTML 로 주입하지 않는다.
    assert ".html(uncertainty" not in markup
    assert "innerHTML" not in markup
