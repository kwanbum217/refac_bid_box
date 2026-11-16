"""내 조건 추천가: AI 예측가를 회원 정량점수 기준 통과 구간 안으로 옮기는 계약 시험."""
# ruff: noqa: F811 - 가져온 픽스처 이름을 시험 인자로 받는다

from __future__ import annotations

import pytest

from src.app.api.v1 import evaluations
from src.app.schemas.predictions import PredictPriceResponse
from src.app.services.evaluation_recommendation import (
    MemberRecommendation,
    member_recommended_price,
)
from tests.test_evaluation_recommend import (  # noqa: F401 - 픽스처는 모듈 이름 그대로 등록돼야 한다
    MEMBER_CREDIT_GRADE,
    _add_member_facts,
    _create_bid,
    _recommend,
    _registry_overrides,
    as_user,
    auto_stub_prediction,
)


@pytest.mark.parametrize(
    ("ai_price", "expected"),
    [
        (99, MemberRecommendation(price=100, basis="raised_to_min")),
        (100, MemberRecommendation(price=100, basis="ai")),
        (150, MemberRecommendation(price=150, basis="ai")),
        (200, MemberRecommendation(price=200, basis="ai")),
        (201, MemberRecommendation(price=200, basis="lowered_to_max")),
    ],
)
def test_ai_price_is_moved_into_pass_range(ai_price, expected):
    assert member_recommended_price(ai_price, 100, 200) == expected


@pytest.mark.parametrize(
    ("ai_price", "low", "high"),
    [(None, 100, 200), (150, None, 200), (150, 100, None)],
)
def test_missing_input_gives_no_recommendation(ai_price, low, high):
    assert member_recommended_price(ai_price, low, high) is None


def _stub_price(monkeypatch, price: int) -> None:
    def _fake_predict(payload, request, db, user=None):
        return PredictPriceResponse(
            status="success",
            optimal_price=price,
            prediction_rate=88.0,
            model_name="대역 모델",
            model_id="stub-model",
            requested_model=payload.selected_model or "stub-model",
            fallback_used=False,
            fallback_reason=None,
            message="시험용 예측 대역 응답",
        )

    monkeypatch.setattr(evaluations, "predict_price_api", _fake_predict)


def _bounds(client, isolated_db, as_user):
    as_user(10)
    _add_member_facts(isolated_db, 10, credit_grade=MEMBER_CREDIT_GRADE)
    bid = _create_bid(isolated_db)
    payload = _recommend(client, bid, overrides=_registry_overrides()).json()
    assert payload["status"] == "success", payload
    return bid, payload["price_bounds"]


def test_response_raises_ai_price_below_member_minimum(client, isolated_db, as_user, monkeypatch):
    bid, bounds = _bounds(client, isolated_db, as_user)
    _stub_price(monkeypatch, bounds["min_bid_amount"] - 1)

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["prediction"]["optimal_price"] == bounds["min_bid_amount"] - 1
    assert payload["member_recommended_price"] == bounds["min_bid_amount"]
    assert payload["member_recommendation_basis"] == "raised_to_min"


def test_response_keeps_ai_price_inside_member_range(client, isolated_db, as_user, monkeypatch):
    bid, bounds = _bounds(client, isolated_db, as_user)
    inside = (bounds["min_bid_amount"] + bounds["max_bid_amount"]) // 2
    _stub_price(monkeypatch, inside)

    payload = _recommend(client, bid, overrides=_registry_overrides()).json()

    assert payload["member_recommended_price"] == inside
    assert payload["member_recommendation_basis"] == "ai"


def test_lower_quant_score_moves_member_price_not_ai_price(
    client, isolated_db, as_user, monkeypatch
):
    """정량점수를 낮추면 AI 예측가는 그대로이고 내 조건 추천가만 최저가를 따라 오른다."""
    bid, full_bounds = _bounds(client, isolated_db, as_user)
    _stub_price(monkeypatch, full_bounds["min_bid_amount"])

    lowered = _recommend(
        client,
        bid,
        overrides=_registry_overrides(quant_items={"performance": 15.0, "labor_plan": 10.0}),
    ).json()

    assert lowered["status"] == "success", lowered
    assert lowered["prediction"]["optimal_price"] == full_bounds["min_bid_amount"]
    assert lowered["price_bounds"]["min_bid_amount"] > full_bounds["min_bid_amount"]
    assert lowered["member_recommended_price"] == lowered["price_bounds"]["min_bid_amount"]
    assert lowered["member_recommendation_basis"] == "raised_to_min"


def test_blocked_response_has_no_member_recommendation(client, isolated_db, as_user):
    as_user(10)
    bid = _create_bid(isolated_db, category="Thng")

    payload = _recommend(client, bid).json()

    assert payload["blocked"] is True
    assert payload["member_recommended_price"] is None
    assert payload["member_recommendation_basis"] is None
