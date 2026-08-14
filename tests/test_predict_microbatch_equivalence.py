"""마이크로배칭이 단건 추론과 같은 값을 내는지 고정합니다.

JoblibModelWrapper.predict_batch 는 _prepare_full_frame 이 만든 프레임을
concat 하지 않고 행을 다시 조립합니다. 기본값 규칙이나 결측 판정이 바뀌면
두 경로가 조용히 갈릴 수 있으므로 허용오차 0 으로 단언합니다.
"""

from __future__ import annotations

import os
import threading

import pytest

from src.app.core.db import SessionLocal
from src.ml.features import build_feature_dict
from src.ml.model_registry import ModelRegistry, _prepare_full_frame
from src.ml.predictor import _PredictionBatcher

THNG_MODEL_ID = "quantum_leap_v25_pro"

REQUESTS = [
    {"presmpt_prce": 1.1e8, "real_budget": 1.1e8, "base_amount": 1.0e8, "scenario_mode": "2"},
    {"presmpt_prce": 5.0e7, "real_budget": 5.0e7, "base_amount": 4.8e7, "scenario_mode": "2"},
    {"presmpt_prce": 2.3e8, "real_budget": 2.3e8, "base_amount": 2.2e8, "scenario_mode": "2"},
    {"presmpt_prce": 7.7e6, "real_budget": 7.7e6, "base_amount": 7.5e6, "scenario_mode": "2"},
    {"presmpt_prce": 9.9e8, "real_budget": 9.9e8, "base_amount": 9.5e8, "scenario_mode": "2"},
    {"presmpt_prce": 0, "real_budget": 0, "base_amount": 0},
    {"presmpt_prce": 1.1e8, "real_budget": 1.1e8, "base_amount": 1.0e8, "lwlt_rate": None},
]


@pytest.fixture(scope="module")
def thng_frames():
    # conftest 가 SKIP_MODEL_LOAD=true 를 걸어 두므로 여기서만 실모델을 싣습니다.
    # 이 테스트는 배치와 단건이 같은 가중치로 같은 값을 내는지 보는 것이므로
    # 스텁으로는 목적을 달성할 수 없습니다.
    previous = os.environ.get("SKIP_MODEL_LOAD")
    os.environ["SKIP_MODEL_LOAD"] = "false"
    try:
        ModelRegistry.load_all_models()
        wrapper = ModelRegistry.get_model(THNG_MODEL_ID)
    finally:
        if previous is None:
            os.environ.pop("SKIP_MODEL_LOAD", None)
        else:
            os.environ["SKIP_MODEL_LOAD"] = previous
    if wrapper is None or not hasattr(wrapper, "predict_batch"):
        # 격리 워크트리에는 model.bin 이 없습니다 (gitignore 대상).
        pytest.skip("물품 모델 가중치가 없어 배치 동등성을 확인할 수 없습니다.")
    db = SessionLocal()
    try:
        frames = []
        for request in REQUESTS:
            features = build_feature_dict({"category": "Thng", **request}, db)
            frames.append(_prepare_full_frame(features, full_map=features))
    finally:
        db.close()
    return wrapper, frames


def test_batch_prediction_matches_single_prediction_exactly(thng_frames):
    wrapper, frames = thng_frames

    single = [float(wrapper.predict(frame)) for frame in frames]
    batched = [float(value) for value in wrapper.predict_batch(frames)]

    assert batched == single


def test_batch_prediction_matches_for_every_batch_size(thng_frames):
    """배치 크기가 값을 바꾸지 않아야 합니다. 크기별로 잘라 확인합니다."""
    wrapper, frames = thng_frames
    single = [float(wrapper.predict(frame)) for frame in frames]

    for size in range(1, len(frames) + 1):
        batched = [float(value) for value in wrapper.predict_batch(frames[:size])]
        assert batched == single[:size], f"배치 크기 {size} 에서 값이 달라졌습니다."


def test_submit_falls_back_when_batch_thread_never_answers():
    """배치 스레드가 응답하지 않아도 요청이 영구 대기하지 않아야 합니다."""
    calls: list[dict] = []

    def never_returns(batch):
        threading.Event().wait(timeout=30)
        raise AssertionError("도달하지 않아야 합니다.")

    def predict_one(features):
        calls.append(features)
        return {"predicted_rate": 91.0}

    batcher = _PredictionBatcher(predict_one, never_returns)
    batcher.SUBMIT_TIMEOUT_SECONDS = 0.2

    result = batcher.submit({"category": "Thng"})

    assert result == {"predicted_rate": 91.0}
    assert calls, "단건 폴백이 호출되지 않았습니다."


def test_batch_worker_survives_result_length_mismatch():
    """결과 수가 어긋나도 스레드가 죽지 않고 오류로 반환해야 합니다."""

    def returns_wrong_length(batch):
        return []

    def predict_one(features):
        raise RuntimeError("단건 경로도 실패")

    batcher = _PredictionBatcher(predict_one, returns_wrong_length)
    batcher.SUBMIT_TIMEOUT_SECONDS = 2.0

    with pytest.raises(ValueError):
        batcher.submit({"category": "Thng"})

    # 스레드가 살아 있어야 다음 요청도 같은 방식으로 응답합니다.
    with pytest.raises(ValueError):
        batcher.submit({"category": "Thng"})
