"""후보 B: 요청당 특징 맵 단일 구축을 검증합니다.

/docs/handoff/2026-08-13_prediction_p95_diagnosis.md 후보 B. /predict 요청
경로(predictor -> predict_optimal_price -> _prepare_full_frame ->
wrapper.predict -> prepare_input_frame)에서 build_default_feature_map 이
3회 재구성되던 것을 1회로 줄였습니다. 이 파일은 그 계약을 고정합니다.

 - 요청당 build_default_feature_map 호출은 정확히 1회다
 - 단일 구축 경로의 예측은 이전 3회 재구성 경로와 값이 같다 (Thng/Servc/fallback)
 - 프레임에 실린 값, category dtype, strict 미서빙 검증은 그대로다
 - full_map 을 안 넘긴 기존 호출부(API/도구/태스크) 경로는 재구축을 유지한다
"""

from __future__ import annotations

import joblib
import numpy as np
import pandas as pd
import pytest
from lightgbm import LGBMRegressor

from src.ml import features as features_mod
from src.ml import model_registry
from src.ml import predictor as predictor_module
from src.ml.features import (
    MISSING_CATEGORY,
    build_default_feature_map,
    prepare_input_frame,
)
from src.ml.model_registry import ModelRegistry

THNG_MODEL = "quantum_leap_v25_pro"
SERVC_MODEL = "servc_institution_v1"

THNG_PAYLOAD = {
    "presumed_price": 500_000_000,
    "base_price": 505_000_000,
    "category_code": "Thng",
}

SERVC_PAYLOAD = {
    "presumed_price": 100_000_000,
    "base_price": 110_000_000,
    "category_code": "Servc",
}


def _fit_tiny_lgbm():
    """동등성 검증용 소형 LGBM. 특징은 전체 맵이 만드는 컬럼만 씁니다."""
    rng = np.random.default_rng(0)
    X = pd.DataFrame(
        {
            "inst_hist_rate": rng.uniform(0.75, 0.95, size=96),
            "month": rng.integers(1, 13, size=96).astype(float),
            "inst_sample_cnt": rng.integers(0, 50, size=96).astype(float),
        }
    )
    y = 0.7 + X["inst_hist_rate"] * 0.2 + rng.normal(scale=0.005, size=96)
    model = LGBMRegressor(
        n_estimators=3,
        max_depth=2,
        min_child_samples=2,
        random_state=0,
        verbose=-1,
    )
    model.fit(X, y)
    return model


class _RecordingWrapper(model_registry.JoblibModelWrapper):
    """받은 프레임을 남기는 래퍼. last_frame 으로 동등성을 비교합니다."""

    def predict(self, df):
        self.last_frame = df
        return super().predict(df)


class _FailingWrapper:
    def run_preprocess(self, features_dict):
        return None

    def predict(self, df):
        raise RuntimeError("가중치 손상")


def _registry(mapping: dict[str, object]):
    def _get_model(model_id):
        return mapping.get(model_id)

    return _get_model


def _freeze_reference_time(monkeypatch):
    monkeypatch.setattr(
        features_mod,
        "_get_reference_timestamp",
        lambda _features_dict: pd.Timestamp("2026-03-10 12:00:00"),
    )


def _count_builds(monkeypatch) -> list:
    calls: list = []
    original = features_mod.build_default_feature_map

    def counted(*args, **kwargs):
        calls.append(args)
        return original(*args, **kwargs)

    # features.py 와 model_registry.py 는 각자 바인딩을 갖습니다.
    monkeypatch.setattr(features_mod, "build_default_feature_map", counted)
    monkeypatch.setattr(model_registry, "build_default_feature_map", counted)
    return calls


@pytest.fixture(scope="module")
def tiny_model_dir(tmp_path_factory):
    """소형 LGBM 을 모듈당 한 번만 학습해 재사용합니다.

    함수 scope 로 두면 이 파일의 테스트 6건이 각각 LightGBM 학습과 joblib 저장을
    반복합니다. Windows CI 에서 이 fixture setup 하나가 18.60초였습니다
    (2026-09-01 CI run 33506224151). 학습 결과는 난수 시드가 고정돼 있어 매번
    같으므로 재사용해도 검증 의미가 바뀌지 않습니다.

    **모델 파일을 수정하는 테스트가 생기면 이 scope 를 되돌리십시오.** 지금은
    읽기만 합니다.
    """
    model = _fit_tiny_lgbm()
    model_dir = tmp_path_factory.mktemp("tiny_model")
    joblib.dump(model, model_dir / "model.bin")
    return str(model_dir)


def test_predict_request_builds_feature_map_once(monkeypatch, tiny_model_dir):
    """/predict 요청 경로에서 build_default_feature_map 은 정확히 1회입니다."""
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry({THNG_MODEL: _RecordingWrapper(tiny_model_dir)}),
    )
    monkeypatch.setattr(ModelRegistry, "available_models", lambda: ["registered"])
    calls = _count_builds(monkeypatch)

    result = predictor_module.predictor.predict(THNG_PAYLOAD)

    assert len(calls) == 1, f"특징 맵을 {len(calls)}회 구축했습니다"
    assert calls[0][0] == THNG_PAYLOAD, "1회 구축은 원본 요청 데이터를 받아야 합니다"
    # 원본 요청 키가 구축 결과에 반영됩니다 (원본 키 병합 보존).
    assert result["features_used"]["presumed_price"] == 500_000_000.0
    assert result["features_used"]["base_price"] == 505_000_000.0
    assert result["features_used"]["category"] == "Thng"
    assert result["model_version"] == THNG_MODEL


@pytest.mark.parametrize(
    ("payload", "model_id"),
    [
        (THNG_PAYLOAD, THNG_MODEL),
        (SERVC_PAYLOAD, SERVC_MODEL),
    ],
)
def test_predict_equivalence_with_previous_chain(monkeypatch, tiny_model_dir, payload, model_id):
    """단일 구축 경로의 예측은 이전 3회 재구성 경로와 같아야 합니다."""
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    wrapper = _RecordingWrapper(tiny_model_dir)
    monkeypatch.setattr(ModelRegistry, "get_model", _registry({model_id: wrapper}))
    monkeypatch.setattr(ModelRegistry, "available_models", lambda: ["registered"])
    _freeze_reference_time(monkeypatch)

    result = predictor_module.predictor.predict(payload)
    new_frame = wrapper.last_frame.copy(deep=True)

    # 이전 경로: 요청으로 1회 구축한 뒤 _prepare_full_frame 이 재구축합니다.
    feature_map = build_default_feature_map(payload)
    old_wrapper = _RecordingWrapper(tiny_model_dir)
    monkeypatch.setattr(ModelRegistry, "get_model", _registry({model_id: old_wrapper}))
    outcome = model_registry.predict_optimal_price_with_provenance(
        model_id, feature_map, full_map=None
    )
    old_frame = old_wrapper.last_frame.copy(deep=True)
    expected_rate = outcome.predicted_rate * 100.0
    expected_price = payload["presumed_price"] * (expected_rate / 100.0)

    assert result["predicted_rate"] == expected_rate
    assert result["predicted_price"] == expected_price
    assert result["model_version"] == model_id
    # 신·구 경로를 별도 래퍼로 기록해 두 프레임을 실제로 비교합니다.
    assert new_frame.iloc[0].to_dict() == old_frame.iloc[0].to_dict()
    assert new_frame.iloc[0].to_dict() == feature_map


def test_predict_fallback_equivalence_with_previous_chain(monkeypatch, tiny_model_dir):
    """요청 모델 실패 시 대체 모델도 같은 단일 맵으로 답해야 합니다."""
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    fallback_wrapper = _RecordingWrapper(tiny_model_dir)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry(
            {
                SERVC_MODEL: _FailingWrapper(),
                "v25": fallback_wrapper,
            }
        ),
    )
    monkeypatch.setattr(ModelRegistry, "available_models", lambda: ["registered"])
    _freeze_reference_time(monkeypatch)

    result = predictor_module.predictor.predict(SERVC_PAYLOAD, model_id=SERVC_MODEL)
    new_fallback_frame = fallback_wrapper.last_frame.copy(deep=True)

    feature_map = build_default_feature_map(SERVC_PAYLOAD)
    old_fallback_wrapper = _RecordingWrapper(tiny_model_dir)
    monkeypatch.setattr(
        ModelRegistry,
        "get_model",
        _registry(
            {
                SERVC_MODEL: _FailingWrapper(),
                "v25": old_fallback_wrapper,
            }
        ),
    )
    outcome = model_registry.predict_optimal_price_with_provenance(
        SERVC_MODEL, feature_map, full_map=None
    )
    old_fallback_frame = old_fallback_wrapper.last_frame.copy(deep=True)
    assert outcome.actual_model == "v25"
    assert outcome.fallback_used is True

    # predictor 는 요청 모델을 model_version 으로 보고합니다 (기존 계약).
    assert result["model_version"] == SERVC_MODEL
    assert result["predicted_rate"] == outcome.predicted_rate * 100.0
    # 대체 모델도 신·구 경로에서 요청 키 병합된 같은 맵을 받아야 합니다.
    assert new_fallback_frame.iloc[0].to_dict() == old_fallback_frame.iloc[0].to_dict()
    assert new_fallback_frame.iloc[0].to_dict() == feature_map


def test_prepare_input_frame_defaults_preserve_values_and_dtypes(monkeypatch):
    """defaults 전달 경로는 재구축 경로와 값·범주 dtype 이 같아야 합니다."""
    _freeze_reference_time(monkeypatch)
    payload = {
        **THNG_PAYLOAD,
        "srvce_div_nm": "일반용역",
        "prearng_mthd": "복수예가",
        "lwlt_rate": 87.745,
    }
    complete = build_default_feature_map(payload)
    columns = ["log_price", "inst_hist_rate", "srvce_div_nm", "prearng_mthd"]
    levels = {
        "srvce_div_nm": [MISSING_CATEGORY, "일반용역", "다른값"],
        "prearng_mthd": [MISSING_CATEGORY, "복수예가", "다른값"],
    }

    rebuilt = model_registry._prepare_input_frame(complete, columns, levels)
    passed = model_registry._prepare_input_frame(complete, columns, levels, defaults=complete)

    assert rebuilt.equals(passed)
    for column in ("srvce_div_nm", "prearng_mthd"):
        assert isinstance(passed[column].dtype, pd.CategoricalDtype)
        assert list(passed[column].cat.categories) == levels[column]
        assert int(passed[column].cat.codes.iloc[0]) == 1
    assert passed["log_price"].iloc[0] == complete["log_price"]
    assert passed["inst_hist_rate"].iloc[0] == complete["inst_hist_rate"]


def test_prepare_input_frame_defaults_keeps_strict_validation(monkeypatch):
    """defaults 를 넘겨도 strict 미서빙 검증은 그대로 동작해야 합니다."""
    _freeze_reference_time(monkeypatch)
    complete = build_default_feature_map(THNG_PAYLOAD)

    with pytest.raises(ValueError, match=r"features\.py 가 만들지 못합니다"):
        prepare_input_frame(complete, ["log_price", "존재하지않는특징"], defaults=complete)

    # 호출부가 직접 실어 보낸 컬럼은 그대로 통과합니다 (원본 키 병합).
    frame = prepare_input_frame({**complete, "참여업체수": 7}, ["참여업체수"], defaults=complete)
    assert frame["참여업체수"].iloc[0] == 7.0


def test_provenance_without_full_map_keeps_rebuild(monkeypatch, tiny_model_dir):
    """full_map 을 안 넘긴 기존 호출부는 재구축 경로를 유지해 값이 같습니다."""
    monkeypatch.setenv("SKIP_MODEL_LOAD", "false")
    wrapper = _RecordingWrapper(tiny_model_dir)
    monkeypatch.setattr(ModelRegistry, "get_model", _registry({THNG_MODEL: wrapper}))
    monkeypatch.setattr(ModelRegistry, "available_models", lambda: ["registered"])
    _freeze_reference_time(monkeypatch)

    feature_map = build_default_feature_map(THNG_PAYLOAD)
    calls = _count_builds(monkeypatch)
    outcome = model_registry.predict_optimal_price_with_provenance(THNG_MODEL, feature_map)

    # full_map 을 안 넘겼으므로 _prepare_full_frame 의 재구축 1회가 유지됩니다.
    assert len(calls) == 1
    assert outcome.predicted_rate > 0
    # 재구축 프레임도 attrs 로 defaults 를 내려보내 값이 같습니다.
    expected = build_default_feature_map(feature_map)
    assert wrapper.last_frame.iloc[0].to_dict() == expected
