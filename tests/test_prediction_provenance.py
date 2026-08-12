"""예측 응답이 실제로 답한 모델을 정확히 가리키는지 검증합니다.

후보 순회는 요청 모델이 실패해도 다른 모델로 값을 냅니다. 종전 구현은 값만
돌려주었기 때문에 모델명, 예측 구간, 로그가 전부 답하지 않은 모델을 가리켰고
조용한 대체가 100% 은폐되었습니다. 여기서 고정하는 계약입니다.

 - 응답의 모델명과 model_id 는 실제로 답한 모델이다
 - 예측 구간도 같은 모델에서 나온다
 - 대체가 일어나면 응답에 드러난다
 - 후보가 전부 실패하면 조용한 성공이 아니라 오류다
 - 응답에 난수가 없다 (같은 입력은 같은 응답)

실제 모델 파일에 의존하지 않습니다. 격리 트리에는 model.bin 이 없습니다.
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.ml.model_registry import (
    ModelRegistry,
    predict_optimal_price,
    predict_optimal_price_with_provenance,
)

REQUESTED = "servc_institution_v1"
FALLBACK = "v25"


class _FakeWrapper:
    """run_preprocess 가 프레임을 돌려주므로 특징 준비 경로를 타지 않습니다."""

    def __init__(self, model_id: str, rate: float | None = None, error: Exception | None = None):
        self.model_id = model_id
        self.rate = rate
        self.error = error

    def run_preprocess(self, features_dict):
        return pd.DataFrame([{"x": 1.0}])

    def predict(self, frame):
        if self.error is not None:
            raise self.error
        return self.rate

    def get_display_name(self):
        return f"{self.model_id} 표시명"


def _registry(mapping: dict[str, _FakeWrapper | None]):
    """ModelRegistry.get_model 을 사전 조회로 대체합니다."""

    def _get_model(model_id):
        return mapping.get(model_id)

    return _get_model


def _create_bid(db, **overrides):
    defaults = {
        "bid_ntce_nm": "테스트 용역 공고",
        "bid_ntce_no": "BID-PROV-001",
        "bid_ntce_ord": "000",
        "ntce_instt_nm": "테스트 공고기관",
        "dminstt_nm": "테스트 수요기관",
        "base_amount": 110000000,
        "presmpt_prce": 100000000,
        "bid_ntce_dt": utcnow(),
        "bid_clse_dt": utcnow(),
        "openg_dt": utcnow(),
        "category": "Servc",
        "raw_data": None,
    }
    defaults.update(overrides)
    bid = BidAnnouncement(**defaults)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


# --------------------------------------------------------------------------- #
# 레지스트리 계층
# --------------------------------------------------------------------------- #


def test_provenance_reports_requested_model_when_it_succeeds(monkeypatch):
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.88)}),
    )

    outcome = predict_optimal_price_with_provenance(REQUESTED, {"category": "Servc"})

    assert outcome.actual_model == REQUESTED
    assert outcome.requested_model == REQUESTED
    assert outcome.fallback_used is False
    assert outcome.fallback_reason is None
    assert outcome.predicted_rate == pytest.approx(0.88)


def test_provenance_reports_actual_model_on_fallback(monkeypatch):
    """요청 모델이 실패하면 실제로 답한 모델과 사유가 드러나야 한다."""
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry(
            {
                REQUESTED: _FakeWrapper(REQUESTED, error=RuntimeError("가중치 손상")),
                FALLBACK: _FakeWrapper(FALLBACK, rate=0.91),
            }
        ),
    )

    outcome = predict_optimal_price_with_provenance(REQUESTED, {"category": "Servc"})

    assert outcome.actual_model == FALLBACK
    assert outcome.requested_model == REQUESTED
    assert outcome.fallback_used is True
    assert REQUESTED in outcome.fallback_reason
    assert "가중치 손상" in outcome.fallback_reason
    assert outcome.predicted_rate == pytest.approx(0.91)


def test_provenance_logs_warning_on_fallback(monkeypatch, caplog):
    """대체는 print 가 아니라 logger.warning 으로 남아야 한다."""
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry(
            {
                REQUESTED: _FakeWrapper(REQUESTED, error=RuntimeError("가중치 손상")),
                FALLBACK: _FakeWrapper(FALLBACK, rate=0.91),
            }
        ),
    )

    with caplog.at_level("WARNING", logger="src.ml.model_registry"):
        predict_optimal_price_with_provenance(REQUESTED, {"category": "Servc"})

    messages = " ".join(record.getMessage() for record in caplog.records)
    assert REQUESTED in messages
    assert FALLBACK in messages


def test_all_candidates_failing_raises(monkeypatch):
    """조용한 성공이 아니라 오류여야 한다."""
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry(
            {
                REQUESTED: _FakeWrapper(REQUESTED, error=RuntimeError("가중치 손상")),
                FALLBACK: _FakeWrapper(FALLBACK, error=RuntimeError("가중치 손상")),
            }
        ),
    )

    with pytest.raises(RuntimeError):
        predict_optimal_price_with_provenance(REQUESTED, {"category": "Servc"})


def test_no_registered_candidate_raises(monkeypatch):
    monkeypatch.setattr(ModelRegistry, "get_model", _registry({}))

    with pytest.raises(ValueError):
        predict_optimal_price_with_provenance(REQUESTED, {"category": "Servc"})


def test_legacy_float_contract_is_preserved(monkeypatch):
    """소유 파일 밖 호출부가 그대로 쓰는 float 계약이 유지돼야 한다."""
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.88)}),
    )

    rate = predict_optimal_price(REQUESTED, {"category": "Servc"})

    assert type(rate) is float
    assert rate == pytest.approx(0.88)
    assert f"{rate:.4f}" == "0.8800"


# --------------------------------------------------------------------------- #
# API 계층
# --------------------------------------------------------------------------- #


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_model_name_points_to_actual_model(mock_interval, client, isolated_db, monkeypatch):
    """대체가 일어나면 응답의 모델명이 실제로 답한 모델을 가리켜야 한다."""
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry(
            {
                REQUESTED: _FakeWrapper(REQUESTED, error=RuntimeError("가중치 손상")),
                FALLBACK: _FakeWrapper(FALLBACK, rate=0.91),
            }
        ),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["model_id"] == FALLBACK
    assert body["requested_model"] == REQUESTED
    assert body["fallback_used"] is True
    assert body["model_name"].startswith(f"{FALLBACK} 표시명")
    assert REQUESTED not in body["model_name"]


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_interval_uses_actual_model(mock_interval, client, isolated_db, monkeypatch):
    """점 추정과 구간이 서로 다른 모델에서 나오면 안 된다."""
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry(
            {
                REQUESTED: _FakeWrapper(REQUESTED, error=RuntimeError("가중치 손상")),
                FALLBACK: _FakeWrapper(FALLBACK, rate=0.91),
            }
        ),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200, response.text
    interval_model_id = mock_interval.call_args.args[0]
    assert interval_model_id == FALLBACK


@patch("src.app.api.v1.predictions.predict_interval", return_value=(87.0, 93.0, 0.8))
def test_api_exposes_interval_from_actual_model(mock_interval, client, isolated_db, monkeypatch):
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    body = response.json()
    assert body["fallback_used"] is False
    assert body["rate_low"] == pytest.approx(87.0)
    assert body["rate_high"] == pytest.approx(93.0)
    assert body["interval_coverage"] == pytest.approx(0.8)


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_handles_model_without_interval(mock_interval, client, isolated_db, monkeypatch):
    """구간 아티팩트가 없는 구 모델도 정상 응답이어야 한다."""
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200, response.text
    body = response.json()
    for field in ("rate_low", "rate_high", "price_low", "price_high", "interval_coverage"):
        assert body[field] is None
    assert body["optimal_price"] > 0


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_errors_when_every_candidate_fails(mock_interval, client, isolated_db, monkeypatch):
    """후보 전량 실패는 조용한 성공이 아니라 오류다."""
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry(
            {
                REQUESTED: _FakeWrapper(REQUESTED, error=RuntimeError("가중치 손상")),
                FALLBACK: _FakeWrapper(FALLBACK, error=RuntimeError("가중치 손상")),
            }
        ),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 503, response.text


# --------------------------------------------------------------------------- #
# confidence 계약
# --------------------------------------------------------------------------- #


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_response_has_no_randomness(mock_interval, client, isolated_db, monkeypatch):
    """같은 입력을 두 번 호출하면 같은 응답이어야 한다.

    종전 구현은 근접도가 5 미만이면 35~65 난수로 갈아끼웠습니다.
    """
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )
    # 추천가에서 크게 벗어난 투찰가여야 종전 난수 분기 조건에 들어갑니다.
    payload = {"bid_id": bid.id, "user_price": "10000000", "selected_model": REQUESTED}

    first = client.post("/api/v1/predictions/predict-price", json=payload).json()
    second = client.post("/api/v1/predictions/predict-price", json=payload).json()

    assert first == second
    assert first["user_bid_similarity"] == 0


def test_response_schema_dropped_confidence_key():
    """confidence 는 모델 신뢰도가 아니었으므로 계약에서 제거했습니다."""
    from src.app.schemas.predictions import PredictPriceResponse

    assert "confidence" not in PredictPriceResponse.model_fields
    assert "user_bid_similarity" in PredictPriceResponse.model_fields


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_similarity_is_null_without_user_price(mock_interval, client, isolated_db, monkeypatch):
    """투찰가를 넣지 않으면 근접도는 계산할 값이 없어 null 이어야 한다."""
    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "0", "selected_model": REQUESTED},
    )

    assert response.status_code == 200, response.text
    assert response.json()["user_bid_similarity"] is None
