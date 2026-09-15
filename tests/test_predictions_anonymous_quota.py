"""
tests/test_predictions_anonymous_quota.py

예측 API (POST /api/v1/predictions/predict-price, POST /api/v1/predictions/predict)의
익명 요청 쿼터 제한 및 벤치마크 429 차단 동작을 검증합니다.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from scripts.benchmark_latency import benchmark_predict
from src.app.api.v1.accounts import get_current_user
from src.app.core.security import anonymous_api_rate_limiter
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.ml.model_registry import PredictionOutcome


class FakeRedis:
    """익명 쿼터 검증용 인메모리 Redis 시뮬레이터."""

    def __init__(self, count: int = 0):
        self.count = count

    def get(self, _key):
        return str(self.count)

    def pipeline(self):
        outer = self

        class Pipe:
            def incr(self, _key):
                outer.count += 1
                return self

            def expire(self, _key, _ttl):
                return self

            def execute(self):
                return True

        return Pipe()


def _create_bid(db, **overrides):
    base_amt = overrides.get("base_amount", 100_000_000)
    defaults = {
        "bid_ntce_nm": "쿼터 테스트 공고",
        "bid_ntce_no": "QUOTA-BID-001",
        "bid_ntce_ord": "000",
        "ntce_instt_nm": "테스트 공고기관",
        "dminstt_nm": "테스트 수요기관",
        "base_amount": base_amt,
        "presmpt_prce": 100_000_000,
        "bid_ntce_dt": utcnow(),
        "bid_clse_dt": utcnow(),
        "openg_dt": utcnow(),
        "category": "Thng",
        "raw_data": {"prearngPrceDcsnMthdNm": "복수예가", "bdgtAmt": base_amt},
    }
    defaults.update(overrides)
    bid = BidAnnouncement(**defaults)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


def _outcome(rate: float = 0.95, model_id: str = "quantum_leap_v25_pro"):
    return PredictionOutcome(
        predicted_rate=rate,
        requested_model=model_id,
        actual_model=model_id,
        fallback_used=False,
        fallback_reason=None,
    )


def test_anonymous_quota_exceeded_returns_429_on_predict_price(client, isolated_db, monkeypatch):
    """익명 쿼터 한도 초과 시 POST /api/v1/predictions/predict-price 가 429 를 반환한다."""
    fake = FakeRedis(count=2)
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake)
    monkeypatch.setattr(
        type(anonymous_api_rate_limiter),
        "max_requests",
        property(lambda _self: 2),
    )

    bid = _create_bid(isolated_db)

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "95000000"},
    )
    assert response.status_code == 429
    assert "초" not in response.json()["detail"]
    assert "분" not in response.json()["detail"]


@patch("src.app.api.v1.predictions.predictor.predict")
def test_anonymous_quota_exceeded_returns_429_on_predict(mock_predict, client, monkeypatch):
    """익명 쿼터 한도 초과 시 POST /api/v1/predictions/predict 가 429 를 반환한다."""
    fake = FakeRedis(count=2)
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake)
    monkeypatch.setattr(
        type(anonymous_api_rate_limiter),
        "max_requests",
        property(lambda _self: 2),
    )

    response = client.post(
        "/api/v1/predictions/predict",
        json={
            "presumed_price": 500_000_000,
            "base_price": 495_000_000,
            "category_code": "Thng",
        },
    )
    assert response.status_code == 429
    assert "초" not in response.json()["detail"]
    mock_predict.assert_not_called()


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
@patch("src.app.api.v1.predictions.predictor.predict")
def test_authenticated_user_bypasses_quota_on_both_routes(
    mock_predict_feature,
    mock_predict_price,
    mock_get_model,
    client,
    isolated_db,
    monkeypatch,
):
    """인증 사용자는 익명 쿼터 한도 초과 상태에서도 제한 없이 통과한다."""
    fake = FakeRedis(count=100)
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake)
    monkeypatch.setattr(
        type(anonymous_api_rate_limiter),
        "max_requests",
        property(lambda _self: 2),
    )

    mock_user = CustomUser(
        id=42,
        username="auth_user",
        email="auth_user@example.com",
        is_active=True,
    )
    app.dependency_overrides[get_current_user] = lambda: mock_user

    mock_predict_price.return_value = _outcome(0.951)
    mock_wrapper = MagicMock()
    mock_wrapper.get_display_name.return_value = "Quantum Leap V25 Pro"
    mock_get_model.return_value = mock_wrapper

    mock_predict_feature.return_value = {
        "predicted_price": 475_000_000,
        "predicted_rate": 95.0,
        "model_version": "v1",
        "features_used": {"presumed_price": 500_000_000.0},
    }

    try:
        bid = _create_bid(isolated_db)

        # 1. predict-price 검증
        res_price = client.post(
            "/api/v1/predictions/predict-price",
            json={"bid_id": bid.id, "user_price": "95000000"},
        )
        assert res_price.status_code == 200

        # 2. predict 검증
        res_feature = client.post(
            "/api/v1/predictions/predict",
            json={
                "presumed_price": 500_000_000,
                "base_price": 495_000_000,
                "category_code": "Thng",
            },
        )
        assert res_feature.status_code == 200
    finally:
        app.dependency_overrides.pop(get_current_user, None)


def test_list_models_is_not_rate_limited(client, monkeypatch):
    """GET /api/v1/predictions/list-models 는 쿼터 제한 없이 공개 호출이 가능하다."""
    fake = FakeRedis(count=100)
    monkeypatch.setattr(anonymous_api_rate_limiter._conn, "client", lambda: fake)
    monkeypatch.setattr(
        type(anonymous_api_rate_limiter),
        "max_requests",
        property(lambda _self: 2),
    )

    response = client.get("/api/v1/predictions/list-models")
    assert response.status_code == 200
    assert response.json()["status"] == "success"


def test_benchmark_predict_aborts_immediately_on_429_without_cookie(monkeypatch):
    """벤치마크가 세션 쿠키 없이 429 응답을 받으면 샘플로 세지 않고 즉시 중단한다."""

    class MockResponse:
        status_code = 429
        text = "Too Many Requests"

    monkeypatch.delenv("BENCHMARK_SESSION_COOKIE", raising=False)
    monkeypatch.setattr(
        "scripts.benchmark_latency.httpx.post",
        lambda *args, **kwargs: MockResponse(),
    )

    with pytest.raises(RuntimeError, match="익명 쿼터로 차단됨, --session-cookie 필요"):
        benchmark_predict("http://test", rounds=5, concurrency=2)


def test_benchmark_predict_passes_session_cookie_argument(monkeypatch):
    """선택 인자 --session-cookie 로 전달된 bidbox_session 쿠키가 요청에 포함된다."""
    captured_cookies: list[dict | None] = []

    class MockResponse:
        status_code = 200

    def mock_post(_url, **kwargs):
        captured_cookies.append(kwargs.get("cookies"))
        return MockResponse()

    monkeypatch.delenv("BENCHMARK_SESSION_COOKIE", raising=False)
    monkeypatch.setattr("scripts.benchmark_latency.httpx.post", mock_post)

    samples = benchmark_predict(
        "http://test",
        rounds=3,
        concurrency=1,
        session_cookie="token_abc_123",
    )
    assert len(samples.values) == 3
    assert samples.errors == 0
    assert all(c == {"bidbox_session": "token_abc_123"} for c in captured_cookies)


def test_benchmark_predict_uses_env_session_cookie(monkeypatch):
    """환경변수 BENCHMARK_SESSION_COOKIE 로 지정된 쿠키가 요청에 반영된다."""
    captured_cookies: list[dict | None] = []

    class MockResponse:
        status_code = 200

    def mock_post(_url, **kwargs):
        captured_cookies.append(kwargs.get("cookies"))
        return MockResponse()

    monkeypatch.setenv("BENCHMARK_SESSION_COOKIE", "env_token_456")
    monkeypatch.setattr("scripts.benchmark_latency.httpx.post", mock_post)

    samples = benchmark_predict("http://test", rounds=2, concurrency=1)
    assert len(samples.values) == 2
    assert samples.errors == 0
    assert all(c == {"bidbox_session": "env_token_456"} for c in captured_cookies)
