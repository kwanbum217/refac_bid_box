"""
tests/test_evaluations_quota.py

평가 API(/analyze, /recommend, 스냅샷 쓰기)에 챗봇·예측과 같은 인증 사용자 쿼터가
걸렸는지 검증합니다.

 - 한도를 넘으면 429 와 인증 쿼터 문구를 돌려주며, 비용이 큰 계산·DB 조회 전에 막습니다.
 - 쿼터 버킷은 api:ratelimit:user:<user_id> 로 챗봇·예측과 같습니다.
 - 한도 안에서는 쿼터를 쓰지 않던 종전 응답과 같습니다.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.app.api.v1 import evaluations
from src.app.api.v1.accounts import require_current_user
from src.app.core.security import (
    AUTHENTICATED_API_RATE_LIMIT_EXCEEDED_DETAIL,
    AUTHENTICATED_API_RATE_LIMIT_PREFIX,
    authenticated_api_rate_limiter,
)
from src.app.main import app
from src.app.schemas.predictions import PredictPriceResponse
from tests.test_evaluations_api import SCORE_TABLE, _analysis_payload, _create_bid

ANALYZE_URL = "/api/v1/evaluations/analyze"
RECOMMEND_URL = "/api/v1/evaluations/recommend"
SNAPSHOTS_URL = "/api/v1/evaluations/snapshots"
USER_ID = 7


class _OverLimitRedis:
    """한도 초과 상태를 흉내내는 최소 대역 (get/pipeline)."""

    def __init__(self) -> None:
        self.keys: list[str] = []

    def get(self, key: str) -> str:
        self.keys.append(key)
        return "999"

    def pipeline(self):
        outer = self

        class _Pipe:
            def incr(self, key: str):
                outer.keys.append(key)
                return self

            def expire(self, key: str, ttl: int):
                return self

            def execute(self):
                return [999, 1]

        return _Pipe()


class _UnderLimitRedis:
    """한도 안 상태를 흉내내며 접근 키를 기록하는 최소 대역."""

    def __init__(self) -> None:
        self.keys: list[str] = []

    def get(self, key: str) -> None:
        self.keys.append(key)
        return None

    def pipeline(self):
        outer = self

        class _Pipe:
            def incr(self, key: str):
                outer.keys.append(key)
                return self

            def expire(self, key: str, ttl: int):
                return self

            def execute(self):
                return [1, 1]

        return _Pipe()


@pytest.fixture
def as_user():
    """실제 인증·Redis 없이 요청 사용자만 바꾸는 대역."""

    def _set_user(user_id: int) -> None:
        app.dependency_overrides[require_current_user] = lambda: SimpleNamespace(id=user_id)

    yield _set_user
    app.dependency_overrides.pop(require_current_user, None)


@pytest.fixture(autouse=True)
def _stub_prediction(monkeypatch):
    """실제 모델 가중치를 로드하지 않도록 예측 API 를 대역으로 덮습니다."""

    def _fake_predict(payload, request, db, user=None):
        return PredictPriceResponse(
            status="success",
            optimal_price=440_000_000,
            prediction_rate=88.0,
            model_name="쿼터 시험 대역 모델",
            model_id=payload.selected_model or "default-model",
            requested_model=payload.selected_model or "default-model",
            fallback_used=False,
            fallback_reason=None,
            message="테스트용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _recommend_payload(bid_id: int) -> dict:
    return {
        "bid_id": bid_id,
        "selected_model": "quota-test-model",
        "overrides": {
            "quant_items": {"performance": 20, "labor_plan": 10},
            "management_grade": "AAA ~ A-",
            "max_price_score": 60,
            "multiplier": 2,
            "pass_threshold": 95,
        },
    }


def _snapshot_payload(bid_id: int) -> dict:
    return {
        "bid_id": bid_id,
        "rule_id": "SERVC_QUOTA_TEST",
        "model_id": "quota-test-model",
        "model_version": "1.0",
        "input_json": {"bid_id": bid_id},
        "result_json": {"status": "success"},
    }


@pytest.mark.parametrize(
    ("url", "payload_factory"),
    [
        (ANALYZE_URL, lambda bid_id: _analysis_payload(bid_id, score_table=SCORE_TABLE)),
        (RECOMMEND_URL, _recommend_payload),
        (SNAPSHOTS_URL, _snapshot_payload),
    ],
)
def test_over_limit_evaluation_route_returns_429(
    client, as_user, monkeypatch, url, payload_factory
):
    """한도를 넘으면 비용이 큰 작업 전에 429 로 막고 인증 버킷을 쓴다."""
    as_user(USER_ID)
    fake = _OverLimitRedis()
    monkeypatch.setattr(authenticated_api_rate_limiter._conn, "client", lambda: fake)

    # 공고가 없는 bid_id 를 써서 쿼터가 조회보다 먼저 실행되는지도 함께 본다.
    response = client.post(url, json=payload_factory(987_654))

    assert response.status_code == 429, response.text
    assert response.json()["detail"] == AUTHENTICATED_API_RATE_LIMIT_EXCEEDED_DETAIL
    assert fake.keys == [f"{AUTHENTICATED_API_RATE_LIMIT_PREFIX}{USER_ID}"]


def _comparable(payload: dict) -> dict:
    """스냅샷 저장처럼 호출마다 달라지는 식별자·시각을 뺀 응답 본문."""
    return {key: value for key, value in payload.items() if key not in ("id", "created_at")}


def test_allowed_requests_keep_previous_response(client, isolated_db, as_user, monkeypatch):
    """한도 안의 요청은 쿼터 도입 전(제한기 비활성) 응답과 같다."""
    as_user(USER_ID)
    bid = _create_bid(isolated_db)
    cases = [
        (ANALYZE_URL, _analysis_payload(bid.id, score_table=SCORE_TABLE)),
        (RECOMMEND_URL, _recommend_payload(bid.id)),
        (SNAPSHOTS_URL, _snapshot_payload(bid.id)),
    ]

    for url, payload in cases:
        monkeypatch.setattr(authenticated_api_rate_limiter._conn, "client", lambda: None)
        baseline = client.post(url, json=payload)

        fake = _UnderLimitRedis()
        monkeypatch.setattr(authenticated_api_rate_limiter._conn, "client", lambda fake=fake: fake)
        allowed = client.post(url, json=payload)

        assert allowed.status_code == baseline.status_code, url
        assert _comparable(allowed.json()) == _comparable(baseline.json()), url
        assert f"{AUTHENTICATED_API_RATE_LIMIT_PREFIX}{USER_ID}" in fake.keys
