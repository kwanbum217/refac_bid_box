"""서빙 추정기의 스레드 예산(n_jobs=1) 적용과 예측값 동등성을 검증합니다.

학습 아티팩트의 n_jobs=-1 또는 None은 predict 시점에 가용 코어를 쓰는 OpenMP
스레드 팀을 만듭니다. 단건 추론 오버헤드와 동시성 oversubscription 이 P95 를
붕괴시키므로, 로드 직후 n_jobs=1 로 고정합니다. 학습 기본값·아티팩트·예측값은
바꾸지 않습니다. 근거: docs/handoff/2026-08-13_prediction_p95_diagnosis.md
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
import pytest
from lightgbm import LGBMRegressor

from src.ml import model_registry


def _fit_tiny_lgbm(**overrides):
    """단건 예측 동등성 검증용 소형 LGBM 을 학습합니다."""
    rng = np.random.default_rng(0)
    X = rng.normal(size=(64, 3))
    y = X[:, 0] * 2.0 + X[:, 1] + rng.normal(scale=0.1, size=64)
    params = {
        "n_estimators": 3,
        "max_depth": 2,
        "min_child_samples": 2,
        "random_state": 0,
        "verbose": -1,
    }
    params.update(overrides)
    model = LGBMRegressor(**params)
    model.fit(X, y)
    return model, X


def test_apply_inference_thread_budget_supported_estimator():
    model, _ = _fit_tiny_lgbm()
    assert model.get_params()["n_jobs"] is None
    model_registry._apply_inference_thread_budget(model)
    assert model.get_params()["n_jobs"] == 1


def test_apply_inference_thread_budget_skips_unsupported_estimator():
    class _NoNJobsEstimator:
        def get_params(self):
            return {"alpha": 1.0}

    estimator = _NoNJobsEstimator()
    model_registry._apply_inference_thread_budget(estimator)
    assert estimator.get_params() == {"alpha": 1.0}
    model_registry._apply_inference_thread_budget(object())


def test_set_params_n_jobs_one_keeps_predictions():
    model, X = _fit_tiny_lgbm()
    before = model.predict(X[:1])
    model.set_params(n_jobs=1)
    after = model.predict(X[:1])
    np.testing.assert_array_equal(after, before)


def test_joblib_wrapper_applies_thread_budget_to_point_model(tmp_path):
    model, X = _fit_tiny_lgbm()
    artifact_path = tmp_path / "model.bin"
    joblib.dump(model, artifact_path)
    columns = list(model.feature_name_)
    frame = pd.DataFrame(X[:1], columns=columns)
    input_df = model_registry._prepare_input_frame(frame.iloc[0].to_dict(), columns, None)
    reference = float(np.asarray(model.predict(input_df)).reshape(-1)[0])

    wrapper = model_registry.JoblibModelWrapper(str(tmp_path))
    assert wrapper.model.get_params()["n_jobs"] == 1
    assert wrapper.predict(frame) == pytest.approx(reference, rel=1e-12)
    assert joblib.load(artifact_path).get_params()["n_jobs"] is None


def test_joblib_wrapper_applies_thread_budget_to_quantile_models(tmp_path):
    model, X = _fit_tiny_lgbm()
    q10, _ = _fit_tiny_lgbm(objective="quantile", alpha=0.1)
    q90, _ = _fit_tiny_lgbm(objective="quantile", alpha=0.9)
    joblib.dump(model, tmp_path / "model.bin")
    joblib.dump(q10, tmp_path / "model_q10.bin")
    joblib.dump(q90, tmp_path / "model_q90.bin")

    wrapper = model_registry.JoblibModelWrapper(str(tmp_path))
    quantile_models = wrapper._load_quantile_models()
    assert sorted(quantile_models) == [0.1, 0.9]
    for quantile_model in quantile_models.values():
        assert quantile_model.get_params()["n_jobs"] == 1

    columns = list(model.feature_name_)
    frame = pd.DataFrame(X[:1], columns=columns)
    input_df = model_registry._prepare_input_frame(frame.iloc[0].to_dict(), columns, None)
    reference = sorted(
        float(np.asarray(quantile_model.predict(input_df)).reshape(-1)[0])
        for quantile_model in (q10, q90)
    )
    low, high = wrapper.predict_interval(frame)
    assert low == pytest.approx(reference[0], rel=1e-12)
    assert high == pytest.approx(reference[1], rel=1e-12)


def test_joblib_wrapper_leaves_unsupported_estimator_untouched(tmp_path):
    bundle = {"models": [1.0, 2.0]}
    joblib.dump(bundle, tmp_path / "model.bin")
    wrapper = model_registry.JoblibModelWrapper(str(tmp_path))
    assert wrapper.model == bundle
