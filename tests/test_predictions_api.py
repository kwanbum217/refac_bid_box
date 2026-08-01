"""
tests/test_predictions_api.py

원본 apps/predictions/tests.py 중 이식 가능한 검증을 FastAPI 환경으로 변환.
 - _normalize_prediction_rate 단위 테스트
 - predict-price API: 카테고리별 기본 모델 선택 (Thng→quantum_leap, Servc→ssh_hist_premium)
 - predict-price API: base_amount None 일 때 presmpt_prce fallback
 - predict-price API: selected_model 명시 전달
"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from src.app.models.bids import BidAnnouncement
from src.ml.model_registry import _normalize_prediction_rate


def test_normalize_prediction_rate_converts_percent_to_ratio():
    assert _normalize_prediction_rate(86.5) == pytest.approx(0.865)


def test_normalize_prediction_rate_keeps_ratio_bounds():
    assert _normalize_prediction_rate(1.01) == pytest.approx(1.01)


def test_normalize_prediction_rate_rejects_zero():
    with pytest.raises(ValueError):
        _normalize_prediction_rate(0)


def test_normalize_prediction_rate_clamps_to_max():
    assert _normalize_prediction_rate(1.5) == pytest.approx(1.05)


def test_normalize_prediction_rate_clamps_to_min():
    assert _normalize_prediction_rate(70.0) == pytest.approx(0.75)


def _create_bid(db, **overrides):
    defaults = dict(
        bid_ntce_nm="테스트 공고",
        bid_ntce_no="BID-001",
        bid_ntce_ord="000",
        ntce_instt_nm="테스트 공고기관",
        dminstt_nm="테스트 수요기관",
        base_amount=110000000,
        presmpt_prce=100000000,
        bid_ntce_dt=datetime.utcnow(),
        bid_clse_dt=datetime.utcnow(),
        openg_dt=datetime.utcnow(),
        category="Thng",
        raw_data=None,
    )
    defaults.update(overrides)
    bid = BidAnnouncement(**defaults)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _mock_wrapper(display_name):
    w = MagicMock()
    w.get_display_name.return_value = display_name
    return w


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price")
def test_predict_price_defaults_to_quantum_leap_for_goods(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db)
    mock_predict.return_value = 0.951
    mock_get_model.return_value = _mock_wrapper("Quantum Leap V25 Pro")

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000"},
    )

    assert response.status_code == 200, response.text
    called_model_id, called_features = mock_predict.call_args.args
    assert called_model_id == "quantum_leap_v25_pro"
    assert called_features["presmpt_prce"] == 110000000.0
    assert called_features["real_budget"] == 110000000.0
    assert called_features["scenario_mode"] == "2"


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price")
def test_predict_price_defaults_to_ssh_hist_premium_for_services(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db, category="Servc")
    mock_predict.return_value = 0.951
    mock_get_model.return_value = _mock_wrapper("SSH Hist Premium Ensemble")

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000"},
    )

    assert response.status_code == 200
    called_model_id, _ = mock_predict.call_args.args
    assert called_model_id == "ssh_hist_premium"


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price")
def test_predict_price_passes_selected_model(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db)
    mock_predict.return_value = 0.97
    mock_get_model.return_value = _mock_wrapper("Dummy Model")

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "98000000", "selected_model": "v25"},
    )

    assert response.status_code == 200
    assert response.json()["model_name"] == "Dummy Model"
    called_model_id, _ = mock_predict.call_args.args
    assert called_model_id == "v25"


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price")
def test_predict_price_falls_back_to_presmpt_prce_when_base_amount_none(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db, base_amount=None)
    mock_predict.return_value = 0.951
    mock_get_model.return_value = _mock_wrapper("Quantum Leap V25 Pro")

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000"},
    )

    assert response.status_code == 200
    _, called_features = mock_predict.call_args.args
    assert called_features["presmpt_prce"] == 100000000.0
    assert called_features["real_budget"] == 100000000.0


def test_predict_price_returns_404_for_unknown_bid(client, isolated_db):
    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": 99999, "user_price": "97000000"},
    )
    assert response.status_code == 404
