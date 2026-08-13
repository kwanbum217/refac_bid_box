from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient

from src.app.core.db import get_db
from src.app.main import app

client = TestClient(app)

@pytest.fixture
def mock_db_session():
    session = MagicMock()

    mock_bid = MagicMock()
    mock_bid.prediction_reference_amount = 1000000
    mock_bid.category = "Thng"
    mock_bid.bid_ntce_dt = None
    mock_bid.bid_clse_dt = None
    mock_bid.openg_dt = None
    mock_bid.raw_data = {}

    session.get.return_value = mock_bid

    def get_db_override():
        yield session

    original_overrides = dict(app.dependency_overrides)
    try:
        app.dependency_overrides[get_db] = get_db_override
        yield session
    finally:
        app.dependency_overrides = original_overrides

def test_predict_price_api_instrumentation_and_equivalence(mock_db_session, monkeypatch):
    """
    /predict-price 의 출력 동등성과 최소 계측(lazy logger)이 정상 동작하는지 테스트합니다.
    """
    mock_outcome = type("Outcome", (), {
        "predicted_rate": 0.87745,
        "actual_model": "test_model",
        "requested_model": "test_model",
        "fallback_used": False,
        "fallback_reason": None,
    })

    with patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance", return_value=mock_outcome), \
         patch("src.app.api.v1.predictions.predict_interval", return_value=(87.0, 88.0, 95.0)), \
         patch("src.app.api.v1.predictions.logger") as mock_logger, \
         patch("src.app.api.v1.predictions.time") as mock_time, \
         patch("src.app.api.v1.predictions.build_feature_dict", return_value={}):

        mock_time.perf_counter.side_effect = [0.0, 1.0, 2.0, 3.0]
        mock_time.thread_time.side_effect = [0.0, 1.0, 2.0, 3.0]

        response = client.post(
            "/api/v1/predictions/predict-price",
            json={
                "bid_id": 12345,
                "user_price": "1000",
            },
        )

        assert response.status_code == 200, response.json()
        data = response.json()

        # 출력 동등성 보존 확인
        assert data["optimal_price"] == 877450

        # logger 호출 검증
        assert mock_logger.info.called, "logger.info가 호출되어야 합니다."
        info_calls = [call for call in mock_logger.info.mock_calls if "predict_price_api" in str(call)]
        assert len(info_calls) == 1, "predict_price_api 계측 로그가 정확히 1회 호출되어야 합니다."

        args = info_calls[0].args
        assert "endpoint=predict_price_api, wall_ms=%.2f, thread_cpu_ms=%.2f, model_wall_ms=%.2f, model_thread_cpu_ms=%.2f" == args[0]
        assert len(args) == 5

def test_predict_winning_price_instrumentation_and_equivalence(mock_db_session, monkeypatch):
    """
    /predict 의 출력 동등성과 최소 계측(lazy logger)이 정상 동작하는지 테스트합니다.
    """
    with patch("src.app.api.v1.predictions.predictor") as mock_predictor:
        mock_predictor.predict.return_value = {
            "predicted_price": 12345,
            "predicted_rate": 87.745,
            "model_version": "test_model",
            "features_used": {"test": "feature"},
        }
        with patch("src.app.api.v1.predictions.logger") as mock_logger, \
             patch("src.app.api.v1.predictions.time") as mock_time:

            mock_time.perf_counter.side_effect = [0.0, 1.0, 2.0, 3.0]
            mock_time.thread_time.side_effect = [0.0, 1.0, 2.0, 3.0]

            payload = {
                "bid_notice_no": "20261234",
                "presumed_price": 1000000,
                "base_price": 990000,
                "category_code": "Thng",
            }

            response = client.post("/api/v1/predictions/predict", json=payload)
            assert response.status_code == 200, response.json()
            data = response.json()

            # 출력 동등성 보존 확인
            assert data["predicted_price"] == 12345
            assert data["predicted_rate"] == 87.745

            # logger 호출 검증
            assert mock_logger.info.called, "logger.info가 호출되어야 합니다."
            info_calls = [call for call in mock_logger.info.mock_calls if "predict_winning_price" in str(call)]
            assert len(info_calls) == 1, "predict_winning_price 계측 로그가 정확히 1회 호출되어야 합니다."

            args = info_calls[0].args
            assert "endpoint=predict_winning_price, wall_ms=%.2f, thread_cpu_ms=%.2f, model_wall_ms=%.2f, model_thread_cpu_ms=%.2f" == args[0]
            assert len(args) == 5
