"""A1. predict-price API 의 금액 특징 기준과 추천 투찰가 곱셈 기준을 고정합니다.

학습은 추정가격(presmpt_prce)으로 금액 특징을 만들지만 API 는 기초금액을
넣어 같은 공고를 다른 금액으로 예측했습니다. 특징은 추정가격 기준으로 바꾸고,
추천 투찰가 곱셈은 기초금액(reference_amount) 그대로 둡니다.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.app.models.bids import BidAnnouncement
from src.ml.prediction_api import PredictionOutcome

PRESMPT_PRCE = 100_000_000.0
REFERENCE_AMOUNT = 110_000_000.0
PREDICTED_RATE = 0.9


def _create_bid(db, **overrides) -> BidAnnouncement:
    defaults = {
        "bid_ntce_nm": "2026년 공공데이터 클라우드 전환 용역",
        "bid_ntce_no": "BID-A1",
        "bid_ntce_ord": "000",
        "ntce_instt_nm": "한국도로공사",
        "dminstt_nm": "한국도로공사",
        "category": "Servc",
        "cntrct_mthd_nm": "일반경쟁",
        "bid_methd_nm": "전자입찰",
        "base_amount": int(REFERENCE_AMOUNT),
        "presmpt_prce": int(PRESMPT_PRCE),
        "bid_ntce_dt": datetime(2026, 9, 1, 10, 0),
        "bid_clse_dt": datetime(2026, 9, 15, 18, 0),
        "openg_dt": datetime(2026, 9, 16, 10, 0),
        "raw_data": {
            "bdgtAmt": str(int(REFERENCE_AMOUNT)),
            "prearngPrceDcsnMthdNm": "복수예가",
            "sucsfbidLwltRate": "87.745",
        },
    }
    defaults.update(overrides)
    bid = BidAnnouncement(**defaults)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _outcome() -> PredictionOutcome:
    return PredictionOutcome(
        predicted_rate=PREDICTED_RATE,
        requested_model="servc_institution_v1",
        actual_model="servc_institution_v1",
        fallback_used=False,
    )


def _wrapper() -> MagicMock:
    wrapper = MagicMock()
    wrapper.get_display_name.return_value = "용역 전용 모델"
    return wrapper


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_uses_presmpt_features_and_multiplies_reference_amount(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db)
    mock_predict.return_value = _outcome()
    mock_get_model.return_value = _wrapper()

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id},
    )

    assert response.status_code == 200, response.text
    _, features = mock_predict.call_args.args
    # 금액 특징은 학습과 같은 추정가격 기준입니다.
    assert features["presmpt_prce"] == pytest.approx(PRESMPT_PRCE)
    assert features["presmptPrce"] == pytest.approx(PRESMPT_PRCE)
    assert features["real_budget"] == pytest.approx(PRESMPT_PRCE)
    assert features["log_price"] == pytest.approx(np.log1p(PRESMPT_PRCE))
    assert features["base_price"] == pytest.approx(REFERENCE_AMOUNT)
    assert features["price_ratio"] == pytest.approx(REFERENCE_AMOUNT / PRESMPT_PRCE)
    assert "_feature_amount_fallback" not in features

    # 추천 투찰가 곱셈은 기초금액 그대로입니다.
    payload = response.json()
    assert payload["optimal_price"] == int(REFERENCE_AMOUNT * PREDICTED_RATE)
    assert payload["optimal_price"] == 99_000_000
    assert payload["optimal_price"] != int(PRESMPT_PRCE * PREDICTED_RATE)


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_falls_back_to_reference_when_presmpt_missing(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db, presmpt_prce=None)
    mock_predict.return_value = _outcome()
    mock_get_model.return_value = _wrapper()

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id},
    )

    assert response.status_code == 200, response.text
    _, features = mock_predict.call_args.args
    assert features["presmpt_prce"] == pytest.approx(REFERENCE_AMOUNT)
    assert features["real_budget"] == pytest.approx(REFERENCE_AMOUNT)
    assert features["_feature_amount_fallback"] is True
    assert response.json()["optimal_price"] == 99_000_000
