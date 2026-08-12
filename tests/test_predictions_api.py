"""
tests/test_predictions_api.py

원본 apps/predictions/tests.py 중 이식 가능한 검증을 FastAPI 환경으로 변환.
 - _normalize_prediction_rate 단위 테스트
 - predict-price API: 카테고리별 기본 모델 선택 (CATEGORY_DEFAULT_MODELS 정본 참조)
 - predict-price API: base_amount None 일 때 presmpt_prce fallback
 - predict-price API: selected_model 명시 전달

원본 테스트 대응표입니다. 이름이 다른 것은 이식본 라우트명(predict-price)에
맞췄기 때문이며 검증 내용은 같습니다.

| 원본 | 이식본 |
| --- | --- |
| test_predict_api_defaults_to_quantum_leap_for_goods | test_predict_price_defaults_to_quantum_leap_for_goods |
| test_predict_api_defaults_to_ssh_hist_premium_for_services | test_predict_price_defaults_to_category_model_for_services |
| test_predict_api_passes_selected_model_to_backend | test_predict_price_passes_selected_model |
| test_predict_api_falls_back_to_estimated_price_only_for_prediction_input | test_predict_price_falls_back_to_presmpt_prce_when_base_amount_none |
| test_quantum_leap_bundle_is_discoverable | test_list_models_api_returns_registered_bundles (정본 상수 대조) |
| test_ssh_hist_bundle_is_discoverable | test_list_models_api_returns_registered_bundles (정본 상수 대조) |

용역 기본 모델은 원본이 ssh_hist_premium 로 고정돼 있었지만, 이식본은
CATEGORY_DEFAULT_MODELS 를 정본으로 삼아 재학습 승격을 따라갑니다. 그래서
모델 ID 를 문자열로 박지 않고 정본 상수와 대조합니다.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.ml.model_registry import (
    CATEGORY_DEFAULT_MODELS,
    MODEL_FILES_ROOT,
    PredictionOutcome,
    _normalize_prediction_rate,
)


def _outcome(rate, model_id="quantum_leap_v25_pro"):
    """대체 없이 요청 모델이 그대로 답한 정상 경로 산출물."""
    return PredictionOutcome(
        predicted_rate=rate,
        requested_model=model_id,
        actual_model=model_id,
        fallback_used=False,
        fallback_reason=None,
    )


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


@pytest.mark.skipif(
    not any(MODEL_FILES_ROOT.glob("*/model.bin")),
    reason="모델 가중치가 없는 환경입니다",
)
def test_list_models_api_returns_registered_bundles(client, isolated_db, monkeypatch):
    """원본 test_list_models_api_returns_registered_bundles 대응.

    화면의 모델 선택 드롭다운과 성능 배지가 이 응답만 보고 그려집니다.
    키가 하나라도 빠지면 배지가 통째로 비므로 계약을 고정합니다.

    원본은 training_rows=22893 처럼 특정 번들의 값을 그대로 박아 두었습니다.
    이식본은 재학습 승격으로 그 값이 바뀌는 것이 정상이므로, 값 대신 구조와
    카테고리 정본 등록 여부를 봅니다. 값까지 박으면 승격할 때마다 테스트가
    깨지고 결국 실제 계약을 못 지키게 됩니다.
    """
    from src.ml.model_registry import ModelRegistry

    # conftest 가 SKIP_MODEL_LOAD 로 로드를 막으므로 이 검사만 풀어 줍니다.
    # 목록이 비어 있으면 검증할 대상 자체가 없습니다.
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    try:
        response = client.get("/api/v1/predictions/list-models")
    finally:
        ModelRegistry._models = {}

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "success"
    assert payload["models"], "등록된 모델이 하나도 없습니다"

    for model in payload["models"]:
        for key in (
            "id",
            "name",
            "description",
            "version",
            "specialization",
            "specialized_categories",
            "required_features",
            "metrics",
        ):
            assert key in model, f"{model.get('id')} 에 {key} 누락"

    model_ids = {model["id"] for model in payload["models"]}
    # 카테고리 기본 모델은 정본 상수에 등록된 것이 실제로 조회 가능해야 합니다.
    # 여기가 어긋나면 해당 업무구분 예측이 통째로 fallback 으로 떨어집니다.
    for category, default_model in CATEGORY_DEFAULT_MODELS.items():
        assert default_model in model_ids, f"{category} 기본 모델 {default_model} 미등록"


def _create_bid(db, **overrides):
    base_amt = overrides.get("base_amount", 110000000)
    defaults = {
        "bid_ntce_nm": "테스트 공고",
        "bid_ntce_no": "BID-001",
        "bid_ntce_ord": "000",
        "ntce_instt_nm": "테스트 공고기관",
        "dminstt_nm": "테스트 수요기관",
        "base_amount": base_amt,
        "presmpt_prce": 100000000,
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


def _mock_wrapper(display_name):
    w = MagicMock()
    w.get_display_name.return_value = display_name
    return w


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_defaults_to_quantum_leap_for_goods(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db)
    mock_predict.return_value = _outcome(0.951)
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
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_defaults_to_category_model_for_services(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db, category="Servc")
    mock_predict.return_value = _outcome(0.951)
    mock_get_model.return_value = _mock_wrapper("용역 전용 모델")

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "97000000"},
    )

    assert response.status_code == 200
    called_model_id, _ = mock_predict.call_args.args
    # 모델명을 다시 적으면 교체 때 한쪽만 바뀝니다. 정본을 그대로 봅니다.
    assert called_model_id == CATEGORY_DEFAULT_MODELS["Servc"]


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_passes_selected_model(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db)
    mock_predict.return_value = _outcome(0.97)
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
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_falls_back_to_presmpt_prce_when_base_amount_none(
    mock_predict, mock_get_model, client, isolated_db
):
    bid = _create_bid(isolated_db, base_amount=None)
    mock_predict.return_value = _outcome(0.951)
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


# --------------------------------------------------------------------------- #
# train/serve skew 방어
# --------------------------------------------------------------------------- #


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_passes_institution_features_from_raw_data(
    mock_predict, mock_get_model, client, isolated_db
):
    """API 가 raw_data 의 제도 특징을 추론 입력에 실어야 한다.

    이 경로가 빠지면 학습이 쓰는 제도 특징이 전부 기본값으로 떨어져
    같은 모델이 학습 때와 다른 입력을 보게 됩니다(train/serve skew).
    실측에서 하한율 87.995% 인 건이 100.776% 로 예측된 원인입니다.
    """
    from src.ml.dataset import INSTITUTION_FIELDS

    raw = {
        "sucsfbidLwltRate": "87.995",
        "prearngPrceDcsnMthdNm": "복수예가",
        "sucsfbidMthdNm": "적격심사",
        "srvceDivNm": "일반용역",
    }
    bid = _create_bid(isolated_db, category="Servc", bid_ntce_no="BID-INST", raw_data=raw)
    mock_predict.return_value = _outcome(0.88)
    mock_get_model.return_value = _mock_wrapper("용역 전용 모델")

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "0"},
    )

    assert response.status_code == 200
    _, features = mock_predict.call_args.args
    assert float(features["lwlt_rate"]) == pytest.approx(87.995)
    assert features["prearng_mthd"] == "복수예가"
    assert features["sucsfbid_mthd_nm"] == "적격심사"
    assert features["srvce_div_nm"] == "일반용역"
    # 매핑 키 전체가 입력에 존재해야 합니다. 하나라도 빠지면 기본값으로 떨어집니다.
    for column in INSTITUTION_FIELDS:
        assert column in features, column


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_keeps_legacy_rule_model_keys(
    mock_predict, mock_get_model, client, isolated_db
):
    """제도 특징을 병합해도 규칙 기반 구 모델이 쓰는 키가 남아야 한다."""
    bid = _create_bid(isolated_db, category="Thng", bid_ntce_no="BID-LEGACY")
    mock_predict.return_value = _outcome(0.9)
    mock_get_model.return_value = _mock_wrapper("Quantum Leap V25 Pro")

    client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "0"},
    )

    _, features = mock_predict.call_args.args
    for key in ("title", "agency_name", "scenario_mode", "presmpt_prce"):
        assert key in features, key


@patch("src.app.api.v1.predictions.ModelRegistry.get_model")
@patch("src.app.api.v1.predictions.predict_optimal_price_with_provenance")
def test_predict_price_fills_history_features_requiring_db(
    mock_predict, mock_get_model, client, isolated_db
):
    """기관 이력과 재발주 이력은 DB 조회로 채워야 한다.

    session 을 넘기지 않으면 상수로 떨어져 학습과 다른 값을 보게 됩니다.
    """
    bid = _create_bid(isolated_db, category="Servc", bid_ntce_no="BID-HIST")
    mock_predict.return_value = _outcome(0.88)
    mock_get_model.return_value = _mock_wrapper("용역 전용 모델")

    client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "0"},
    )

    _, features = mock_predict.call_args.args
    for key in ("inst_sample_cnt", "is_repeat", "repeat_cnt"):
        assert key in features, key


# --------------------------------------------------------------------------- #
# 금액을 확정할 수 없는 공고
# --------------------------------------------------------------------------- #


def test_predict_price_rejects_bid_without_any_amount(client, isolated_db):
    """기초금액과 예정가격이 모두 없으면 예측을 거부해야 한다.

    원본은 그대로 진행해 추천 투찰가 0 원을 돌려줍니다. 0 원은 답이 아니라
    오답입니다. 해당 공고가 10만 건 이상이고 외자는 절반 가까이가 이 상태입니다.
    """
    bid = _create_bid(
        isolated_db,
        bid_ntce_no="BID-NO-AMOUNT",
        category="Frgcpt",
        base_amount=None,
        presmpt_prce=0,
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "0"},
    )

    assert response.status_code == 422
    assert "산출할 수 없습니다" in response.json()["detail"]


def test_predict_price_rejects_bid_with_zero_budget_in_raw_data(client, isolated_db):
    """raw_data 의 예산이 0 이어도 거부한다 (SQL 필터만으로는 못 걸러짐)."""
    bid = _create_bid(
        isolated_db,
        bid_ntce_no="BID-ZERO-BUDGET",
        category="Thng",
        base_amount=110000000,
        presmpt_prce=100000000,
        raw_data={"bdgtAmt": "0"},
    )

    response = client.post(
        "/api/v1/predictions/predict-price",
        json={"bid_id": bid.id, "user_price": "0"},
    )

    assert response.status_code == 422
