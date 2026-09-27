import numpy as np
import pytest

from src.ml.predictor_v25_helper import (
    DEFAULT_META_FEATURE_ORDER,
    _blend_meta_predictions,
    _build_v25_meta_feature_map,
    predict_v25_logic,
)


class _FixedModel:
    def __init__(self, value):
        self._value = value

    def predict(self, x):
        return np.array([self._value], dtype=float)


class _RecordingModel:
    def __init__(self, value):
        self._value = value
        self.received = None

    def predict(self, x):
        self.received = np.array(x, dtype=float)
        return np.array([self._value], dtype=float)


class _ExplodingModel:
    def predict(self, x):
        raise RuntimeError("메타 모델 실패")


def _assert_meta_feature_map(feature_map, base_avg):
    assert set(feature_map.keys()) == set(DEFAULT_META_FEATURE_ORDER)
    assert len(feature_map) == 12
    assert feature_map["p_v17"] == pytest.approx(base_avg)
    assert feature_map["p_v18"] == pytest.approx(base_avg)
    assert feature_map["p_v19"] == pytest.approx(base_avg)
    assert feature_map["p_v20"] == pytest.approx(base_avg)
    assert feature_map["meta_delta_lgbm_cat"] == pytest.approx(
        feature_map["p_lgbm_meta"] - feature_map["p_cat_meta"]
    )
    assert feature_map["pairwise_abs_diff_mean"] == pytest.approx(0.0)
    stack = np.array(
        [
            base_avg,
            base_avg,
            base_avg,
            base_avg,
            feature_map["p_lgbm_meta"],
            feature_map["p_cat_meta"],
        ],
        dtype=float,
    )
    assert feature_map["meta_mean"] == pytest.approx(float(np.mean(stack)))
    assert feature_map["meta_std"] == pytest.approx(float(np.std(stack)))
    assert feature_map["meta_range"] == pytest.approx(float(np.max(stack) - np.min(stack)))


def test_build_meta_feature_map_keys_and_values():
    feature_map, base_avg = _build_v25_meta_feature_map(0.9, 0.8)

    assert base_avg == pytest.approx(0.85)
    assert feature_map["p_lgbm_meta"] == pytest.approx(0.9)
    assert feature_map["p_cat_meta"] == pytest.approx(0.8)
    assert feature_map["meta_delta_lgbm_cat"] == pytest.approx(0.1)
    assert feature_map["meta_range"] == pytest.approx(0.1)
    _assert_meta_feature_map(feature_map, base_avg)


def test_build_meta_feature_map_reversed_inputs():
    feature_map, base_avg = _build_v25_meta_feature_map(0.8, 0.9)

    assert base_avg == pytest.approx(0.85)
    assert feature_map["p_lgbm_meta"] == pytest.approx(0.8)
    assert feature_map["p_cat_meta"] == pytest.approx(0.9)
    assert feature_map["meta_delta_lgbm_cat"] == pytest.approx(-0.1)
    _assert_meta_feature_map(feature_map, base_avg)


def test_blend_meta_predictions_weighted_average():
    meta = {
        "ridge": _FixedModel(1.2),
        "mlp": _FixedModel(0.8),
        "blend_w": 0.7,
        "mlp_weight": 0.3,
    }
    x_meta = np.zeros((1, 12), dtype=float)

    result = _blend_meta_predictions(meta, x_meta)

    assert result == pytest.approx(1.2 * 0.7 + 0.8 * 0.3)


def test_blend_meta_predictions_default_weights():
    meta = {
        "ridge": _FixedModel(1.2),
        "mlp": _FixedModel(0.8),
    }
    x_meta = np.zeros((1, 12), dtype=float)

    result = _blend_meta_predictions(meta, x_meta)

    assert result == pytest.approx(1.0)


def test_blend_meta_predictions_zero_total_weight_falls_back_to_mean():
    meta = {
        "ridge": _FixedModel(1.2),
        "mlp": _FixedModel(0.8),
        "blend_w": 0.0,
        "mlp_weight": 0.0,
    }
    x_meta = np.zeros((1, 12), dtype=float)

    result = _blend_meta_predictions(meta, x_meta)

    assert result == pytest.approx(1.0)


def test_predict_v25_logic_cat_none_reuses_lgbm_prediction():
    df = np.zeros((2, 1), dtype=float)
    meta = {
        "ridge": _FixedModel(0.9),
        "mlp": _FixedModel(0.9),
    }

    result = predict_v25_logic(_FixedModel(0.9), None, meta, df)

    assert result == pytest.approx(0.9)


def test_predict_v25_logic_meta_features_order_becomes_columns():
    df = np.zeros((2, 1), dtype=float)
    ridge = _RecordingModel(0.85)
    mlp = _RecordingModel(0.85)
    meta = {
        "ridge": ridge,
        "mlp": mlp,
        "meta_features": ["p_lgbm_meta", "p_cat_meta"],
    }

    result = predict_v25_logic(_FixedModel(0.9), _FixedModel(0.8), meta, df)

    assert ridge.received.shape == (1, 2)
    assert ridge.received[0][0] == pytest.approx(0.9)
    assert ridge.received[0][1] == pytest.approx(0.8)
    assert np.array_equal(ridge.received, mlp.received)
    assert result == pytest.approx(0.85)


def test_predict_v25_logic_unknown_feature_name_uses_base_avg():
    df = np.zeros((2, 1), dtype=float)
    ridge = _RecordingModel(0.85)
    meta = {
        "ridge": ridge,
        "mlp": _FixedModel(0.85),
        "meta_features": ["없는_특징", "p_lgbm_meta"],
    }

    result = predict_v25_logic(_FixedModel(0.9), _FixedModel(0.8), meta, df)

    assert ridge.received[0][0] == pytest.approx(0.85)
    assert result == pytest.approx(0.85)


def test_predict_v25_logic_deviation_over_quarter_returns_base_avg():
    df = np.zeros((2, 1), dtype=float)
    meta = {
        "ridge": _FixedModel(1.5),
        "mlp": _FixedModel(1.5),
    }

    result = predict_v25_logic(_FixedModel(0.9), _FixedModel(0.8), meta, df)

    assert result == pytest.approx(0.85)


def test_predict_v25_logic_nonfinite_blend_returns_base_avg():
    df = np.zeros((2, 1), dtype=float)
    meta = {
        "ridge": _FixedModel(float("nan")),
        "mlp": _FixedModel(0.85),
    }

    result = predict_v25_logic(_FixedModel(0.9), _FixedModel(0.8), meta, df)

    assert result == pytest.approx(0.85)


def test_predict_v25_logic_ridge_exception_returns_base_avg(capsys):
    df = np.zeros((2, 1), dtype=float)
    meta = {
        "ridge": _ExplodingModel(),
        "mlp": _FixedModel(0.85),
    }

    result = predict_v25_logic(_FixedModel(0.9), _FixedModel(0.8), meta, df)

    assert result == pytest.approx(0.85)
    assert "메타 추론 실패" in capsys.readouterr().out
