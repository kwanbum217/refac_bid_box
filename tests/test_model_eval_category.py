import numpy as np

from scripts.compare_servc_models_paired import paired_stats
from scripts.eval_servc_api_path import collect
from scripts.measure_serving_model import _request_from_row
from src.ml import predictor as predictor_module


class _CaptureSession:
    def __init__(self):
        self.statement = None

    def execute(self, statement):
        self.statement = statement
        return _EmptyResult()


class _EmptyResult:
    def all(self):
        return []


def test_collect_filters_requested_category():
    session = _CaptureSession()

    frame = collect(session, year=2026, samples=10, seed=42, category="Thng")

    params = session.statement.compile().params
    assert "Thng" in params.values()
    assert frame.empty


def test_paired_stats_reports_unavailable_without_comparable_rows():
    result = paired_stats(np.array([]), "구간 폭")

    assert result["판정"] == "측정 불가"
    assert np.isnan(result["평균 차이"])


def test_measurement_request_preserves_full_training_row():
    row = {
        "bid_ntce_nm": "물품 공고",
        "dminstt_nm": "수요기관",
        "presmpt_prce": 100_000_000,
        "bid_ntce_dt": "2026-01-01",
        "openg_dt": "2026-01-10",
    }

    request = _request_from_row(row, "Thng")

    assert request["title"] == "물품 공고"
    assert request["bid_ntce_dt"] == "2026-01-01"
    assert request["openg_dt"] == "2026-01-10"
    assert request["category"] == "Thng"


def test_predictor_honors_explicit_model_id(monkeypatch):
    selected = []
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    monkeypatch.setattr(predictor_module, "build_feature_dict", lambda data, session: data)

    from src.ml import model_registry

    monkeypatch.setattr(model_registry.ModelRegistry, "available_models", lambda: ["chosen"])
    monkeypatch.setattr(
        model_registry,
        "_preferred_model_for_features",
        lambda features: "category_default",
    )
    monkeypatch.setattr(
        model_registry,
        "predict_optimal_price",
        lambda model_id, features, full_map=None: selected.append(model_id) or 0.9,
    )

    instance = object.__new__(predictor_module.SingletonPredictor)
    result = instance.predict(
        {"category": "Thng", "presmpt_prce": 1000},
        model_id="chosen",
    )

    assert selected == ["chosen"]
    assert result["model_version"] == "chosen"
