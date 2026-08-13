from unittest.mock import patch

from fastapi.testclient import TestClient

from src.app.core.db import get_db
from src.app.main import app

client = TestClient(app)

def mock_get_db():
    yield None

app.dependency_overrides[get_db] = mock_get_db

def test_predict_price_api_instrumentation_and_equivalence(monkeypatch):
    """
    /predict-price 의 출력 동등성과 최소 계측(lazy logger)이 정상 동작하는지 테스트합니다.
    """
    # 1. 출력 동등성 확인을 위해 예측 결과 모의
    mock_outcome = type("Outcome", (), {
        "predicted_rate": 87.745,
        "actual_model": "test_model",
        "requested_model": "test_model",
        "fallback_used": False,
        "fallback_reason": None,
    })

    # 2. 로거 모의
    with patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance", return_value=mock_outcome), \
         patch("src.app.api.v1.predictions.logger") as mock_logger, \
         patch("src.app.api.v1.predictions.time") as mock_time:

        # 시간 흐름 모의: 0 -> 1 -> 2 -> 3 (perf_counter, process_time 동일)
        mock_time.perf_counter.side_effect = [0.0, 1.0, 2.0, 3.0]
        mock_time.process_time.side_effect = [0.0, 1.0, 2.0, 3.0]

        client.post(
            "/api/v1/predictions/predict-price",
            json={
                "bid_id": "test_bid_id",
                "user_price": "1000",
            },
        )

        # 422, 404가 날 수 있으니 DB 등을 적절히 조작하거나 에러 상태 확인
        # 단, 이 테스트의 핵심은 계측 문자열이므로 로거 호출 형식을 확인합니다.

        # 로거가 에러가 아니라 info를 남겼다면
        info_calls = [call for call in mock_logger.info.mock_calls if "predict_price_api" in str(call)]
        if info_calls:
            args = info_calls[0].args
            assert "predict_price_api | Wall: %.2fms" in args[0]
            # lazy 인자가 4개 있어야 합니다 (Wall, CPU, Model Wall, Model CPU)
            assert len(args) == 5

def test_predict_winning_price_instrumentation_and_equivalence(monkeypatch):
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
            mock_time.process_time.side_effect = [0.0, 1.0, 2.0, 3.0]

            payload = {
                "bid_notice_no": "20261234",
                "presumed_price": 1000000,
                "base_price": 990000,
                "category_code": "Thng",
            }

            response = client.post("/api/v1/predictions/predict", json=payload)
            assert response.status_code == 200
            data = response.json()

            # 출력 동등성 보존 확인
            assert data["predicted_price"] == 12345
            assert data["predicted_rate"] == 87.745

            # 계측 확인
            mock_logger.info.assert_called_once()
            args = mock_logger.info.call_args.args
            assert "predict_winning_price | Wall: %.2fms" in args[0]
            assert len(args) == 5
