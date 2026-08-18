"""비예가 라우팅 단일화와 챗봇 도구 출처 계약을 검증한다.

API 와 챗봇 도구에서 비예가/복수예가를 쌍대로 검증하고,
fallback 시 실제 모델 출처와 구간 일치, 후보 전량 실패,
기존 float 계약을 검증한다. 격리 트리는 model.bin 을 로드하지 않고
monkeypatch 한다.

검증 범위:
- classify_price_decision_method 단일 판정 함수의 입력 패턴
- API 비예가 422 응답
- 챗봇 도구 비예가 skip_reason 반환
- 챗봇 도구 provenance: actual_model, fallback_used, fallback_reason
- 챗봇 도구 후보 전량 실패
- 복수예가/단일예가 정상 통과
- 기존 float 계약 보존
"""

from __future__ import annotations

from unittest.mock import patch

import pandas as pd
import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.ml.model_registry import (
    ModelRegistry,
    classify_price_decision_method,
    predict_optimal_price,
)

# --------------------------------------------------------------------------- #
# classify_price_decision_method 단일 판정 함수
# --------------------------------------------------------------------------- #


class TestClassifyPriceDecisionMethod:
    """prearngPrceDcsnMthdNm 판정 로직의 전수 입력 패턴을 검증한다."""

    @pytest.mark.parametrize(
        "value,expected",
        [
            ("복수예가", "복수예가"),
            ("단일예가", "단일예가"),
            ("없음", "비예가"),
            ("", "Missing"),
            (None, "Missing"),
        ],
    )
    def test_standard_values(self, value, expected):
        """표준 세 유형이 올바르게 분류된다."""
        raw = {"prearngPrceDcsnMthdNm": value} if value is not None else {}
        assert classify_price_decision_method(raw) == expected

    def test_key_absent_is_missing(self):
        """키 자체가 없으면 Missing이다."""
        assert classify_price_decision_method({}) == "Missing"

    def test_both_keys_absent(self):
        """두 키 모두 없으면 Missing이다."""
        assert classify_price_decision_method({"unrelated": "value"}) == "Missing"

    def test_prearng_mthd_fallback_key(self):
        """학습 프레임 키(prearng_mthd)로도 판정할 수 있다."""
        assert classify_price_decision_method({"prearng_mthd": "복수예가"}) == "복수예가"

    def test_json_key_takes_precedence(self):
        """prearngPrceDcsnMthdNm 이 있으면 prearng_mthd 보다 우선한다."""
        raw = {
            "prearngPrceDcsnMthdNm": "단일예가",
            "prearng_mthd": "복수예가",
        }
        assert classify_price_decision_method(raw) == "단일예가"

    def test_whitespace_stripped(self):
        """앞뒤 공백은 무시한다."""
        assert (
            classify_price_decision_method({"prearngPrceDcsnMthdNm": "  복수예가  "}) == "복수예가"
        )

    def test_unrecognized_value_is_unknown(self):
        """인식 불가 값은 Unknown으로 안전하게 분류한다."""
        assert classify_price_decision_method({"prearngPrceDcsnMthdNm": "알수없는값"}) == "Unknown"

    def test_numeric_value_coerced(self):
        """숫자가 들어와도 파싱 실패 없이 Unknown으로 분류한다."""
        assert classify_price_decision_method({"prearngPrceDcsnMthdNm": 12345}) == "Unknown"

    def test_partial_match_복수(self):
        """'복수예가' 가 포함된 문자열은 복수예가이다."""
        assert (
            classify_price_decision_method({"prearngPrceDcsnMthdNm": "복수예가(15개중4개)"})
            == "복수예가"
        )


# --------------------------------------------------------------------------- #
# 헬퍼
# --------------------------------------------------------------------------- #


class _FakeWrapper:
    """모델 로드 없이 예측을 흉내내는 래퍼."""

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
    def _get_model(model_id):
        return mapping.get(model_id)

    return _get_model


def _create_bid(db, **overrides) -> BidAnnouncement:
    defaults = {
        "bid_ntce_nm": "테스트 용역 공고",
        "bid_ntce_no": "BID-A4-001",
        "bid_ntce_ord": "000",
        "ntce_instt_nm": "테스트 공고기관",
        "dminstt_nm": "테스트 수요기관",
        "base_amount": 110000000,
        "presmpt_prce": 100000000,
        "bid_ntce_dt": utcnow(),
        "bid_clse_dt": utcnow(),
        "openg_dt": utcnow(),
        "category": "Servc",
        "raw_data": {"prearngPrceDcsnMthdNm": "복수예가"},
    }
    defaults.update(overrides)
    bid = BidAnnouncement(**defaults)
    db.add(bid)
    db.commit()
    db.refresh(bid)
    return bid


REQUESTED = "servc_institution_v1"
FALLBACK = "v25"


# --------------------------------------------------------------------------- #
# API 비예가 422 검증
# --------------------------------------------------------------------------- #


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_rejects_nonprearranged_with_422(mock_interval, client, isolated_db, monkeypatch):
    """비예가 공고에 대해 API 가 HTTP 422 를 반환한다."""
    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": "없음"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 422
    assert "비예가" in response.json()["detail"]


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_accepts_empty_prearng(mock_interval, client, isolated_db, monkeypatch):
    """prearngPrceDcsnMthdNm 이 빈 문자열이면 Missing 이므로 API 가 통과시킨다."""
    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": ""},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_accepts_absent_prearng(mock_interval, client, isolated_db, monkeypatch):
    """raw_data 에 prearngPrceDcsnMthdNm 키가 없으면 Missing 이므로 API 가 통과시킨다."""
    bid = _create_bid(
        isolated_db,
        raw_data={"otherKey": "value"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_accepts_plural_prearranged(mock_interval, client, isolated_db, monkeypatch):
    """복수예가 공고는 정상적으로 예측된다."""
    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_accepts_single_prearranged(mock_interval, client, isolated_db, monkeypatch):
    """단일예가 공고는 정상적으로 예측된다."""
    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": "단일예가"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_null_raw_data_passes_through(mock_interval, client, isolated_db, monkeypatch):
    """raw_data 가 None 이면 Missing 이므로 API 가 통과시킨다."""
    bid = _create_bid(
        isolated_db,
        raw_data=None,
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200


# --------------------------------------------------------------------------- #
# 챗봇 도구 비예가 검증
# --------------------------------------------------------------------------- #


def test_tool_skips_nonprearranged_bid(isolated_db, monkeypatch):
    """챗봇 도구에서 비예가 공고는 예측하지 않고 사유를 반환한다."""
    from src.app.services.tools.bid_prediction_tool import _predict_bid

    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": "없음"},
    )

    result = _predict_bid(bid, REQUESTED)

    assert result["skipped"] is True
    assert "비예가" in result["skip_reason"]
    assert result["optimal_price"] == 0
    assert result["model_id"] == ""


def test_tool_predicts_plural_prearranged(isolated_db, monkeypatch):
    """챗봇 도구에서 복수예가 공고는 정상적으로 예측된다."""
    from src.app.services.tools.bid_prediction_tool import _predict_bid

    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    result = _predict_bid(bid, REQUESTED)

    assert "skipped" not in result
    assert result["optimal_price"] > 0
    assert result["model_id"] == REQUESTED


def test_tool_predicts_single_prearranged(isolated_db, monkeypatch):
    """챗봇 도구에서 단일예가 공고도 정상적으로 예측된다."""
    from src.app.services.tools.bid_prediction_tool import _predict_bid

    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": "단일예가"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.88)}),
    )

    result = _predict_bid(bid, REQUESTED)

    assert "skipped" not in result
    assert result["optimal_price"] > 0


# --------------------------------------------------------------------------- #
# 챗봇 도구 출처(provenance) 검증
# --------------------------------------------------------------------------- #


def test_tool_provenance_actual_model_on_success(isolated_db, monkeypatch):
    """요청 모델이 성공하면 actual_model 이 요청 모델과 같다."""
    from src.app.services.tools.bid_prediction_tool import _predict_bid

    bid = _create_bid(isolated_db)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    result = _predict_bid(bid, REQUESTED)

    assert result["model_id"] == REQUESTED
    assert result["requested_model"] == REQUESTED
    assert result["fallback_used"] is False


def test_tool_provenance_actual_model_on_fallback(isolated_db, monkeypatch):
    """요청 모델이 실패하면 실제 답한 모델과 사유가 드러난다."""
    from src.app.services.tools.bid_prediction_tool import _predict_bid

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

    result = _predict_bid(bid, REQUESTED)

    assert result["model_id"] == FALLBACK
    assert result["requested_model"] == REQUESTED
    assert result["fallback_used"] is True
    assert "가중치 손상" in result["fallback_reason"]
    assert "(Fallback)" in result["model_name"]


def test_tool_all_candidates_failing_returns_skip(isolated_db, monkeypatch):
    """후보 전량 실패 시 챗봇 도구는 예외 대신 사유를 반환한다."""
    from src.app.services.tools.bid_prediction_tool import _predict_bid

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

    result = _predict_bid(bid, REQUESTED)

    assert result["skipped"] is True
    assert result["optimal_price"] == 0


# --------------------------------------------------------------------------- #
# 기존 float 계약 보존
# --------------------------------------------------------------------------- #


def test_legacy_float_contract_preserved_after_a4(monkeypatch):
    """predict_optimal_price 의 float 반환 계약이 A4 변경 후에도 유지된다."""
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.88)}),
    )

    rate = predict_optimal_price(REQUESTED, {"category": "Servc"})

    assert type(rate) is float
    assert rate == pytest.approx(0.88)


# --------------------------------------------------------------------------- #
# 쌍대 비예가/복수예가 API-챗봇 일관성
# --------------------------------------------------------------------------- #


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_and_tool_agree_on_nonprearranged(mock_interval, client, isolated_db, monkeypatch):
    """API 와 챗봇 도구가 비예가에 대해 동일하게 거부한다."""
    from src.app.services.tools.bid_prediction_tool import _predict_bid

    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": "없음"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    # API 는 422
    api_response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )
    assert api_response.status_code == 422

    # 챗봇 도구는 skip_reason
    tool_result = _predict_bid(bid, REQUESTED)
    assert tool_result["skipped"] is True
    assert "비예가" in tool_result["skip_reason"]


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_and_tool_agree_on_plural_prearranged(mock_interval, client, isolated_db, monkeypatch):
    """API 와 챗봇 도구가 복수예가에 대해 동일하게 통과한다."""
    from src.app.services.tools.bid_prediction_tool import _predict_bid

    bid = _create_bid(
        isolated_db,
        raw_data={"prearngPrceDcsnMthdNm": "복수예가"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    # API 통과
    api_response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )
    assert api_response.status_code == 200

    # 챗봇 도구 통과
    tool_result = _predict_bid(bid, REQUESTED)
    assert "skipped" not in tool_result
    assert tool_result["optimal_price"] > 0


@patch("src.app.api.v1.predictions.predict_interval", return_value=None)
def test_api_accepts_non_servc_nonprearranged(mock_interval, client, isolated_db, monkeypatch):
    """Servc 가 아닌 비예가 공고는 API 가 통과시킨다."""
    bid = _create_bid(
        isolated_db,
        category="Thng",
        raw_data={"prearngPrceDcsnMthdNm": "없음"},
    )
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({REQUESTED: _FakeWrapper(REQUESTED, rate=0.90)}),
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000", "selected_model": REQUESTED},
    )

    assert response.status_code == 200
