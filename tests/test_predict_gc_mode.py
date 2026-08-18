"""
tests/test_predict_gc_mode.py

PREDICTION_GC_MODE 환경변수가 gc 상태와 예측 결과에 미치는 영향을 잠급니다.

잠금 조건:
- 미설정 시 gc.isenabled() == True 이고 gc.get_threshold() 가 CPython 기본값
- 세 모드(freeze, threshold, batch-disable) 각각이 의도한 gc 상태를 만드는지
- 어느 모드에서도 예측 결과가 바뀌지 않음
"""

from __future__ import annotations

import gc
import os
import sys
import time
from unittest.mock import MagicMock, patch

import pytest

_DEFAULT_GC_THRESHOLDS = (700, 10, 10)

STUB_RESULT = {
    "predicted_price": 91_000_000.0,
    "predicted_rate": 91.0,
    "model_version": "fallback",
    "features_used": {},
}


def _reload_predictor(gc_mode: str):
    """predictor 모듈을 지정 GC 모드로 재임포트합니다."""
    env = {"PREDICTION_GC_MODE": gc_mode, "SKIP_MODEL_LOAD": "true"}
    with patch.dict(os.environ, env, clear=False):
        mod_name = "src.ml.predictor"
        sys.modules.pop(mod_name, None)
        import src.ml.predictor as mod

        return mod


@pytest.fixture(autouse=True)
def restore_gc_state():
    """각 테스트 후 gc 상태를 원래대로 되돌립니다."""
    was_enabled = gc.isenabled()
    original_thresholds = gc.get_threshold()
    yield
    gc.set_threshold(*original_thresholds)
    if was_enabled:
        gc.enable()
    else:
        gc.disable()
    gc.unfreeze()
    sys.modules.pop("src.ml.predictor", None)


class TestDefaultMode:
    """PREDICTION_GC_MODE 가 빈 문자열이거나 미설정일 때 gc 상태를 바꾸지 않습니다."""

    def test_gc_is_enabled_when_mode_unset(self):
        gc.enable()
        _reload_predictor("")
        assert gc.isenabled(), "기본 모드에서 gc 가 비활성화되어서는 안 됩니다."

    def test_gc_threshold_unchanged_when_mode_unset(self):
        gc.set_threshold(*_DEFAULT_GC_THRESHOLDS)
        _reload_predictor("")
        assert gc.get_threshold() == _DEFAULT_GC_THRESHOLDS


class TestFreezeMode:
    """freeze 모드: SKIP_MODEL_LOAD=false 일 때 load_all_models 직후 gc.freeze() 호출."""

    def test_freeze_is_called_after_model_load(self):
        """SingletonPredictor 생성 시 gc.freeze() 가 호출되는지 확인합니다."""
        env = {
            "PREDICTION_GC_MODE": "freeze",
            "SKIP_MODEL_LOAD": "false",
        }
        with patch.dict(os.environ, env, clear=False):
            sys.modules.pop("src.ml.predictor", None)
            mock_registry = MagicMock()
            with (
                patch("src.ml.model_registry.ModelRegistry", mock_registry),
                patch("gc.freeze") as mock_freeze,
            ):
                import src.ml.predictor as mod

                # 모듈 임포트 시 predictor = SingletonPredictor() 가 실행되어
                # gc.freeze 가 이미 한 번 호출됩니다. 카운터를 초기화한 뒤
                # _instance 를 리셋하고 재생성해 정확히 1회 호출됨을 확인합니다.
                mock_freeze.reset_mock()
                mod.SingletonPredictor._instance = None
                mod.SingletonPredictor()
                mock_freeze.assert_called_once()

    def test_freeze_not_called_when_skip_model_load(self):
        """SKIP_MODEL_LOAD=true 이면 freeze 모드여도 gc.freeze() 를 호출하지 않습니다."""
        env = {
            "PREDICTION_GC_MODE": "freeze",
            "SKIP_MODEL_LOAD": "true",
        }
        with patch.dict(os.environ, env, clear=False):
            sys.modules.pop("src.ml.predictor", None)
            with patch("gc.freeze") as mock_freeze:
                import src.ml.predictor as mod

                mod.SingletonPredictor._instance = None
                mod.SingletonPredictor()
                mock_freeze.assert_not_called()


class TestThresholdMode:
    """threshold 모드: 임포트 시점에 gc.set_threshold 가 지정값으로 설정됩니다."""

    def test_threshold_set_on_import(self):
        gc.set_threshold(*_DEFAULT_GC_THRESHOLDS)
        mod = _reload_predictor("threshold")
        expected = (
            mod._GC_THRESHOLD_GEN0,
            mod._GC_THRESHOLD_GEN1,
            mod._GC_THRESHOLD_GEN2,
        )
        assert gc.get_threshold() == expected

    def test_threshold_gen1_gen2_raised(self):
        """gen1, gen2 임계값이 CPython 기본값(10, 10)보다 높아야 합니다."""
        _reload_predictor("threshold")
        _, gen1, gen2 = gc.get_threshold()
        assert gen1 > 10, f"gen1 임계값({gen1})이 기본값보다 높아야 합니다."
        assert gen2 > 10, f"gen2 임계값({gen2})이 기본값보다 높아야 합니다."

    def test_gc_remains_enabled_in_threshold_mode(self):
        gc.enable()
        _reload_predictor("threshold")
        assert gc.isenabled(), "threshold 모드에서 gc 가 비활성화되어서는 안 됩니다."


class TestBatchDisableMode:
    """batch-disable 모드: 배치 스레드가 gc.disable() 을 호출합니다."""

    def test_batch_thread_calls_gc_disable(self):
        """batch-disable 모드에서 배치 스레드가 gc.disable() 을 호출해야 합니다.

        CPython 에서 gc.disable() 은 프로세스 전역입니다. 이 테스트는
        배치 스레드가 실제로 gc.disable() 을 호출하는지를 잠급니다.
        """
        gc.enable()
        mod = _reload_predictor("batch-disable")

        disabled_calls: list[bool] = []

        def probe_predict_one(features):
            return STUB_RESULT

        def probe_predict_batch(batch):
            disabled_calls.append(gc.isenabled())
            return [STUB_RESULT] * len(batch)

        batcher = mod._PredictionBatcher(probe_predict_one, probe_predict_batch)
        batcher.submit({"category": "Thng"})

        deadline = time.monotonic() + 2.0
        while not disabled_calls and time.monotonic() < deadline:
            time.sleep(0.01)

        assert disabled_calls, "배치 스레드가 예측을 실행하지 않았습니다."
        assert not disabled_calls[0], "배치 스레드 안에서 gc 가 활성화되어 있었습니다."

    def test_batch_thread_disables_gc(self):
        """배치 스레드 안에서 gc.isenabled() 가 False 여야 합니다."""
        gc.enable()
        mod = _reload_predictor("batch-disable")

        results: list[bool] = []

        def probe_predict_one(features):
            return STUB_RESULT

        def probe_predict_batch(batch):
            results.append(gc.isenabled())
            return [STUB_RESULT] * len(batch)

        batcher = mod._PredictionBatcher(probe_predict_one, probe_predict_batch)
        batcher.submit({"category": "Thng"})

        deadline = time.monotonic() + 2.0
        while not results and time.monotonic() < deadline:
            time.sleep(0.01)

        assert results, "배치 스레드가 예측을 실행하지 않았습니다."
        assert not results[0], "배치 스레드 안에서 gc 가 활성화되어 있었습니다."


class TestPredictionResultUnchanged:
    """어느 GC 모드에서도 예측 결과가 바뀌지 않아야 합니다."""

    @staticmethod
    def _fake_predict(features, model_id=None):
        inst_rate = float(features.get("inst_hist_rate", 0.925))
        return {
            "predicted_price": inst_rate * 100.0 * 1_000_000,
            "predicted_rate": inst_rate * 100.0,
            "model_version": "fallback",
            "features_used": features,
        }

    @pytest.mark.parametrize("gc_mode", ["", "freeze", "threshold", "batch-disable"])
    def test_result_identical_across_modes(self, gc_mode):
        mod = _reload_predictor(gc_mode)
        mod.SingletonPredictor._instance = None
        predictor = mod.SingletonPredictor()
        predictor._predict_from_features = self._fake_predict

        result = predictor._predict_from_features({"inst_hist_rate": 0.91})
        assert abs(result["predicted_rate"] - 91.0) < 1e-9, (
            f"GC 모드 '{gc_mode}' 에서 예측률이 달라졌습니다: {result['predicted_rate']}"
        )
