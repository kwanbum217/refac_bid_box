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
    /predict-price 의 출력 동등성과 세부 구간 계측이 정상 동작하는지 테스트합니다.
    """
    mock_outcome = type(
        "Outcome",
        (),
        {
            "predicted_rate": 0.87745,
            "actual_model": "test_model",
            "requested_model": "test_model",
            "fallback_used": False,
            "fallback_reason": None,
        },
    )

    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=mock_outcome,
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=(87.0, 88.0, 95.0)),
        patch("src.app.api.v1.predictions.latency_logger") as mock_logger,
        patch("src.app.api.v1.predictions.build_feature_dict", return_value={}),
    ):
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
        assert data["prediction_rate"] == 87.745
        assert data["model_id"] == "test_model"

        # logger 호출 검증
        assert mock_logger.info.called, "logger.info가 호출되어야 합니다."
        info_calls = [
            call
            for call in mock_logger.info.mock_calls
            if call.args and call.args[0].startswith("endpoint=predict_price_api, wall_ms=")
        ]
        assert len(info_calls) == 1, "predict_price_api 계측 로그가 정확히 1회 호출되어야 합니다."

        args = info_calls[0].args
        assert (
            args[0]
            == "endpoint=predict_price_api, wall_ms=%.2f, thread_cpu_ms=%.2f, model_wall_ms=%.2f, model_thread_cpu_ms=%.2f, db_lookup_ms=%.2f, feature_build_ms=%.2f, point_infer_ms=%.2f, interval_infer_ms=%.2f"
        )
        assert len(args) == 9
        (
            wall_ms,
            thread_cpu_ms,
            model_wall_ms,
            model_thread_cpu_ms,
            db_lookup_ms,
            feature_build_ms,
            point_infer_ms,
            interval_infer_ms,
        ) = args[1:]
        # 모든 구간 시간은 0 이상이어야 함
        assert wall_ms >= 0.0
        assert thread_cpu_ms >= 0.0
        assert model_wall_ms >= 0.0
        assert model_thread_cpu_ms >= 0.0
        assert db_lookup_ms >= 0.0
        assert feature_build_ms >= 0.0
        assert point_infer_ms >= 0.0
        assert interval_infer_ms >= 0.0
        # 모델 시간 = 점추론 + 구간추론
        assert pytest.approx(model_wall_ms, rel=1e-3, abs=1e-3) == (
            point_infer_ms + interval_infer_ms
        )

        assert any(
            call.args and call.args[0] == "endpoint=predict_price_api, executor_queue_wait_ms=%.2f"
            for call in mock_logger.info.mock_calls
        )


def test_predict_winning_price_instrumentation_and_equivalence(mock_db_session, monkeypatch):
    """
    /predict 의 출력 동등성과 세부 구간 계측이 정상 동작하는지 테스트합니다.
    """
    with patch("src.app.api.v1.predictions.predictor") as mock_predictor:
        mock_predictor.predict.return_value = {
            "predicted_price": 12345,
            "predicted_rate": 87.745,
            "model_version": "test_model",
            "features_used": {"test": "feature"},
        }
        with patch("src.app.api.v1.predictions.latency_logger") as mock_logger:
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
            info_calls = [
                call
                for call in mock_logger.info.mock_calls
                if call.args and call.args[0].startswith("endpoint=predict_winning_price, wall_ms=")
            ]
            assert len(info_calls) == 1, (
                "predict_winning_price 계측 로그가 정확히 1회 호출되어야 합니다."
            )

            args = info_calls[0].args
            assert (
                args[0]
                == "endpoint=predict_winning_price, wall_ms=%.2f, thread_cpu_ms=%.2f, model_wall_ms=%.2f, model_thread_cpu_ms=%.2f, payload_dump_ms=%.2f"
            )
            assert len(args) == 6
            wall_ms, thread_cpu_ms, model_wall_ms, model_thread_cpu_ms, payload_dump_ms = args[1:]
            assert wall_ms >= 0.0
            assert thread_cpu_ms >= 0.0
            assert model_wall_ms >= 0.0
            assert model_thread_cpu_ms >= 0.0
            assert payload_dump_ms >= 0.0

            assert any(
                call.args
                and call.args[0] == "endpoint=predict_winning_price, executor_queue_wait_ms=%.2f"
                for call in mock_logger.info.mock_calls
            )


def test_predict_price_api_fallback_and_interval(mock_db_session):
    """
    /predict-price 에서 fallback 이 발생했을 때도 계측 및 응답이 정상인지 검증합니다.
    """
    mock_outcome = type(
        "Outcome",
        (),
        {
            "predicted_rate": 0.88,
            "actual_model": "fallback_model",
            "requested_model": "requested_model",
            "fallback_used": True,
            "fallback_reason": "Requested model missing",
        },
    )

    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            return_value=mock_outcome,
        ),
        patch("src.app.api.v1.predictions.predict_interval", return_value=None),
        patch("src.app.api.v1.predictions.latency_logger") as mock_logger,
        patch("src.app.api.v1.predictions.build_feature_dict", return_value={}),
    ):
        response = client.post(
            "/api/v1/predictions/predict-price",
            json={
                "bid_id": 12345,
                "user_price": "880000",
                "selected_model": "requested_model",
            },
        )

        assert response.status_code == 200, response.json()
        data = response.json()
        assert data["fallback_used"] is True
        assert data["requested_model"] == "requested_model"
        assert data["model_id"] == "fallback_model"
        assert data["rate_low"] is None
        assert data["price_low"] is None

        info_calls = [
            call
            for call in mock_logger.info.mock_calls
            if call.args and call.args[0].startswith("endpoint=predict_price_api, wall_ms=")
        ]
        assert len(info_calls) == 1
        args = info_calls[0].args
        assert len(args) == 9
        (
            wall_ms,
            thread_cpu_ms,
            model_wall_ms,
            model_thread_cpu_ms,
            db_lookup_ms,
            feature_build_ms,
            point_infer_ms,
            interval_infer_ms,
        ) = args[1:]
        assert wall_ms >= 0.0
        assert thread_cpu_ms >= 0.0
        assert model_wall_ms >= 0.0
        assert model_thread_cpu_ms >= 0.0
        assert db_lookup_ms >= 0.0
        assert feature_build_ms >= 0.0
        assert point_infer_ms >= 0.0
        assert interval_infer_ms >= 0.0


def test_predict_price_api_missing_reference_amount_422(mock_db_session):
    """
    기초금액/예정가격이 없는 공고는 422를 반환해야 합니다.
    """
    mock_db_session.get.return_value.prediction_reference_amount = 0
    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": 12345},
    )
    assert response.status_code == 422


def test_predict_price_api_model_failure_503(mock_db_session):
    """
    모든 모델 후보 실패 시 503을 반환해야 합니다.
    """
    with (
        patch(
            "src.app.api.v1.predictions.predict_optimal_price_with_provenance",
            side_effect=RuntimeError("Model inference failed"),
        ),
        patch("src.app.api.v1.predictions.build_feature_dict", return_value={}),
    ):
        response = client.post(
            "/api/v1/predictions/predict-price",
            json={"bid_id": 12345},
        )
        assert response.status_code == 503
