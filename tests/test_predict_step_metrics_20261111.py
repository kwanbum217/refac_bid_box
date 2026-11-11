"""_step_predict 가 서빙 홀드아웃 지표를 avg_r2 로 전달하는지 검증합니다.

I-ai F-13: 예측 검증 스텝이 avg_r2 를 만들지 않아 metric_interpreter 와
advisory_engine 의 모델 성능 분기가 한 번도 발화하지 않았습니다. 새 학습·평가
없이 승격 metadata 의 source_metrics 만 읽어 지표를 채웁니다.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from src.app.services.metric_interpreter import MetricInterpreter
from src.ml import model_registry, promotion
from src.tasks.automation_steps import _step_predict

THNG_MODEL = model_registry.CATEGORY_DEFAULT_MODELS["Thng"]
SERVC_MODEL = model_registry.CATEGORY_DEFAULT_MODELS["Servc"]


@pytest.fixture
def sample_db():
    db = MagicMock()
    db.execute.return_value.scalar_one_or_none.return_value = SimpleNamespace(
        category="Thng",
        presmpt_prce=1_000_000,
        prediction_reference_amount=1_000_000,
        bid_ntce_nm="표본 공고",
        dminstt_nm="표본 기관",
        bid_ntce_dt=None,
        openg_dt=None,
    )
    return db


@pytest.fixture
def predict_ready(monkeypatch):
    monkeypatch.setattr(
        model_registry.ModelRegistry,
        "available_models",
        lambda: [THNG_MODEL, SERVC_MODEL],
    )
    monkeypatch.setattr(model_registry, "prediction_supported_for_category", lambda _category: True)
    monkeypatch.setattr(model_registry, "predict_optimal_price", lambda _db, _features: 0.93)


def _serving_reader(by_model):
    def reader(model_name, *, serving_dir=None, metrics_dir=None):
        return by_model.get(model_name, ("", {}))

    return reader


def test_predict_averages_serving_holdout_r2(sample_db, predict_ready, monkeypatch):
    """두 서빙 모델의 홀드아웃 r2 가 단순 평균으로 avg_r2 에 실립니다."""
    monkeypatch.setattr(
        promotion,
        "load_serving_metrics",
        _serving_reader(
            {
                THNG_MODEL: ("25.1", {"r2": 0.9, "rmse": 1.2}),
                SERVC_MODEL: ("1.0", {"r2": 0.7, "rmse": 2.0}),
            }
        ),
    )

    result = _step_predict(sample_db)

    assert len(result) == 2
    metrics = result[1]
    assert metrics["pass_all"] is True
    assert metrics["model_count"] == 2
    assert metrics["metrics_source"] == "serving_holdout"
    assert metrics["avg_r2"] == pytest.approx(0.8)
    assert metrics["serving_metrics"] == {
        "Thng": {"model_name": THNG_MODEL, "version": "25.1", "r2": 0.9, "rmse": 1.2},
        "Servc": {"model_name": SERVC_MODEL, "version": "1.0", "r2": 0.7, "rmse": 2.0},
    }


def test_predict_averages_only_models_with_metrics(sample_db, predict_ready, monkeypatch):
    """지표가 없는 모델은 건너뛰고 남은 모델의 r2 만 평균 냅니다."""
    monkeypatch.setattr(
        promotion,
        "load_serving_metrics",
        _serving_reader({SERVC_MODEL: ("1.0", {"r2": 0.6839, "rmse": 2.6937})}),
    )

    metrics = _step_predict(sample_db)[1]

    assert metrics["avg_r2"] == pytest.approx(0.6839)
    assert set(metrics["serving_metrics"]) == {"Servc"}
    assert metrics["serving_metrics"]["Servc"]["r2"] == pytest.approx(0.6839)
    assert metrics["serving_metrics"]["Servc"]["rmse"] == pytest.approx(2.6937)


def test_predict_omits_avg_r2_without_serving_metrics(sample_db, predict_ready, monkeypatch):
    """서빙 지표가 하나도 없으면 avg_r2 키를 만들지 않습니다."""
    monkeypatch.setattr(promotion, "load_serving_metrics", _serving_reader({}))

    metrics = _step_predict(sample_db)[1]

    assert "avg_r2" not in metrics
    assert metrics["serving_metrics"] == {}
    assert metrics["pass_all"] is True


def test_metric_interpreter_reads_predict_avg_r2(sample_db, predict_ready, monkeypatch):
    """예측 스텝 결과를 지표 해석기가 받아 모델 성능 문구를 냅니다."""
    monkeypatch.setattr(
        promotion,
        "load_serving_metrics",
        _serving_reader(
            {
                THNG_MODEL: ("25.1", {"r2": 0.9, "rmse": 1.2}),
                SERVC_MODEL: ("1.0", {"r2": 0.7, "rmse": 2.0}),
            }
        ),
    )
    metrics = _step_predict(sample_db)[1]

    interpreted = MetricInterpreter().interpret({"steps": {"predict": {"metrics": metrics}}})

    assert any("avg_r2=0.800" in insight for insight in interpreted["insights"])
