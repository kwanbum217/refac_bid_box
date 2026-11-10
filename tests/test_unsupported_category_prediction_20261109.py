"""전용 예측 모델이 없는 분야의 투찰가 추천 차단 시험 (2026-11-09).

배경: 공사(Cnstwk)·외자(Frgcpt)는 CATEGORY_DEFAULT_MODELS 에 전용 모델이 없어
예측 낙찰률이 실측과 크게 어긋난다. 모델을 새로 학습하는 대신, 공용 예측 지점에서
분야를 거부하고 화면·REST API·챗봇 도구·자동화 단계가 같은 안내 문구만 내보내게 한다.
"""

from __future__ import annotations

from datetime import timedelta
from typing import ClassVar

import pytest
from fastapi.testclient import TestClient

from src.app.core.security import SESSION_COOKIE_NAME, create_session, make_password
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.services.tools import bid_prediction_tool
from src.ml.model_registry import (
    UNSUPPORTED_CATEGORY_PREDICTION_MESSAGE,
    ModelRegistry,
    UnsupportedPredictionCategoryError,
    predict_optimal_price_with_provenance,
)

PREDICT_PRICE_URL = "/api/v1/predictions/predict-price"


class _FixedRateWrapper:
    """모델 파일 없이 점 추정 경로만 검증하는 대역."""

    metadata: ClassVar[dict] = {}

    def run_preprocess(self, features):
        return None

    def predict(self, df):
        return 0.92


class _FailingWrapper(_FixedRateWrapper):
    def predict(self, df):
        raise ValueError("강제 실패")


def _make_bid(session, *, category: str, bid_ntce_no: str, **overrides) -> BidAnnouncement:
    now = utcnow()
    values = {
        "bid_ntce_no": bid_ntce_no,
        "bid_ntce_ord": "00",
        "bid_ntce_nm": f"{category} 투찰가 추천 차단 시험 공고",
        "dminstt_nm": "테스트발주기관",
        "category": category,
        "presmpt_prce": 1_000_000_000,
        "base_amount": 990_000_000,
        "bid_ntce_dt": now,
        "bid_clse_dt": now + timedelta(days=7),
        "collected_at": now,
    }
    values.update(overrides)
    bid = BidAnnouncement(**values)
    session.add(bid)
    session.commit()
    session.refresh(bid)
    return bid


@pytest.fixture
def seeded_user(isolated_db):
    user = CustomUser(
        username="guard_tester",
        password=make_password("pw-test-1234"),
        email="guard@example.com",
        nickname="가드 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    return user


@pytest.fixture
def auth_client(seeded_user):
    token = create_session(seeded_user.id, seeded_user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


# ---------------------------------------------------------------------------
# (1) 공용 지점이 전용 모델 없는 분야를 거부한다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", ["Cnstwk", "Frgcpt"])
def test_common_point_rejects_unsupported_category(category):
    with pytest.raises(UnsupportedPredictionCategoryError) as excinfo:
        predict_optimal_price_with_provenance(
            None, {"category": category, "presmpt_prce": 1_000_000_000}
        )

    assert str(excinfo.value) == UNSUPPORTED_CATEGORY_PREDICTION_MESSAGE


# ---------------------------------------------------------------------------
# (2) 물품·용역은 기존대로 동작한다
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("category", ["Thng", "Servc"])
def test_supported_categories_still_predict(monkeypatch, category):
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        classmethod(lambda cls, model_id: _FixedRateWrapper()),
    )

    outcome = predict_optimal_price_with_provenance(
        None, {"category": category, "presmpt_prce": 1_000_000_000}
    )

    assert outcome.predicted_rate == pytest.approx(0.92)


# ---------------------------------------------------------------------------
# (3) 대체 후보 목록에 v25 가 남아 있지 않다
# ---------------------------------------------------------------------------


def test_v25_is_not_a_fallback_candidate(monkeypatch):
    seen: list[str] = []

    def fake_get_model(cls, model_id):
        seen.append(model_id)
        return _FailingWrapper()

    monkeypatch.setattr(ModelRegistry, "get_model", classmethod(fake_get_model))

    with pytest.raises(ValueError):
        predict_optimal_price_with_provenance(
            "quantum_leap_v25_pro", {"category": "Thng", "presmpt_prce": 1_000_000_000}
        )

    assert "v25" not in seen
    assert "v13_hybrid" in seen


# ---------------------------------------------------------------------------
# (4) REST API 는 422 와 안내 문구를 돌려준다
# ---------------------------------------------------------------------------


def test_predict_price_api_rejects_unsupported_category(client, isolated_db):
    bid = _make_bid(isolated_db, category="Cnstwk", bid_ntce_no="GUARD-CNSTWK-API")

    response = client.post(PREDICT_PRICE_URL, json={"bid_id": bid.id})

    assert response.status_code == 422
    assert response.json()["detail"] == UNSUPPORTED_CATEGORY_PREDICTION_MESSAGE


# ---------------------------------------------------------------------------
# (5) 챗봇 도구는 예외 없이 안내 문구를 돌려준다
# ---------------------------------------------------------------------------


def test_chatbot_tool_reports_notice_instead_of_values(isolated_db):
    _make_bid(isolated_db, category="Cnstwk", bid_ntce_no="GUARD-CNSTWK-CHAT")

    result = bid_prediction_tool.execute(db=isolated_db, category="Cnstwk", limit=1)

    assert result["status"] == "success"
    assert result["skipped"] is True
    assert result["skip_reason"] == UNSUPPORTED_CATEGORY_PREDICTION_MESSAGE
    assert result["optimal_price"] == 0
    assert result["prediction_rate"] == 0


# ---------------------------------------------------------------------------
# (6) 상세 화면은 안내를 렌더하고 추천 카드를 숨긴다
# ---------------------------------------------------------------------------


def test_bid_detail_shows_notice_for_unsupported_category(auth_client, isolated_db):
    bid = _make_bid(isolated_db, category="Cnstwk", bid_ntce_no="GUARD-CNSTWK-UI")

    body = auth_client.get(f"/bids/{bid.id}/").text

    assert 'id="recommend-unsupported"' in body
    assert UNSUPPORTED_CATEGORY_PREDICTION_MESSAGE in body
    assert 'id="prediction-result"' not in body
    assert 'id="res-optimal-price"' not in body
