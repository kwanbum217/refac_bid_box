"""
src/ml/predictor.py

ML 모델 추론 싱글톤 로더.
서버 시동 시 ModelRegistry가 4종 Champion 가중치를 프리로딩합니다.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any

from src.ml.features import build_feature_dict


class _BatchItem:
    def __init__(self, features: dict[str, Any]):
        self.features = features
        self.event = threading.Event()
        self.result = None
        self.error: BaseException | None = None


class _PredictionBatcher:
    """동일 모델 요청을 짧게 모아 단일 모델 호출로 합칩니다."""

    MAX_BATCH_SIZE = 10
    BATCH_WINDOW_SECONDS = 0.005
    BATCH_WORKERS = 1

    def __init__(self, predict_one, predict_batch):
        self._predict_one = predict_one
        self._predict_batch = predict_batch
        self._items: queue.Queue[_BatchItem] = queue.Queue()
        self._workers = []
        for index in range(self.BATCH_WORKERS):
            worker = threading.Thread(
                target=self._run,
                name=f"prediction-microbatch-{index + 1}",
                daemon=True,
            )
            worker.start()
            self._workers.append(worker)

    def submit(self, features: dict[str, Any]):
        item = _BatchItem(features)
        self._items.put(item)
        item.event.wait()
        if item.error is not None:
            raise item.error
        return item.result

    def _collect(self) -> list[_BatchItem]:
        first = self._items.get()
        batch = [first]
        # 단일 요청은 즉시 처리해 c1 지연을 늘리지 않습니다. 이미 대기 중인
        # 요청이 보이면 짧은 창을 열어 c10 burst 를 하나의 배치로 모읍니다.
        window = self.BATCH_WINDOW_SECONDS if not self._items.empty() else 0.0
        deadline = time.monotonic() + window
        while len(batch) < self.MAX_BATCH_SIZE:
            timeout = deadline - time.monotonic()
            if timeout <= 0:
                break
            try:
                batch.append(self._items.get(timeout=timeout))
            except queue.Empty:
                break
        return batch

    def _run(self):
        while True:
            batch = self._collect()
            try:
                results = self._predict_batch(batch)
            except Exception:
                results = []
                for item in batch:
                    try:
                        results.append(self._predict_one(item.features))
                    except BaseException as exc:
                        item.error = exc
                        results.append(None)
            for item, result in zip(batch, results, strict=True):
                item.result = result
                item.event.set()


class SingletonPredictor:
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._initialized = True
        if os.getenv("SKIP_MODEL_LOAD", "false").lower() != "true":
            from src.ml.model_registry import ModelRegistry

            ModelRegistry.load_all_models()
        self._batcher = _PredictionBatcher(
            self._predict_from_features,
            self._predict_batch,
        )

    def _predict_from_features(
        self,
        features: dict[str, Any],
        model_id: str | None = None,
    ) -> dict[str, Any]:
        if os.getenv("SKIP_MODEL_LOAD", "false").lower() == "true":
            inst_rate = float(features.get("inst_hist_rate", 0.925))
            predicted_rate = inst_rate * 100.0
            model_version = "fallback"
        else:
            from src.ml.model_registry import (
                ModelRegistry,
                _preferred_model_for_features,
                predict_optimal_price,
            )

            preferred = _preferred_model_for_features(features)
            selected = model_id or preferred
            if not ModelRegistry.available_models():
                ModelRegistry.load_all_models()
            predicted_rate = (
                float(predict_optimal_price(selected, features, full_map=features)) * 100.0
            )
            model_version = selected

        presumed = float(features.get("presumed_price") or features.get("presmpt_prce") or 0.0)
        predicted_price = presumed * (predicted_rate / 100.0)
        return {
            "predicted_price": predicted_price,
            "predicted_rate": predicted_rate,
            "model_version": model_version,
            "features_used": features,
        }

    def _predict_batch(self, items: list[_BatchItem]) -> list[dict[str, Any]]:
        from src.ml.model_registry import (
            predict_optimal_price_batch,
        )

        if any(str(item.features.get("category") or "").strip() != "Thng" for item in items):
            raise ValueError("배치 대상이 물품 모델이 아닙니다.")
        outcomes = predict_optimal_price_batch(
            None,
            [item.features for item in items],
            [item.features for item in items],
        )
        results = []
        for item, outcome in zip(items, outcomes, strict=True):
            predicted_rate = float(outcome.predicted_rate) * 100.0
            presumed = float(
                item.features.get("presumed_price")
                or item.features.get("presmpt_prce")
                or 0.0
            )
            results.append(
                {
                    "predicted_price": presumed * (predicted_rate / 100.0),
                    "predicted_rate": predicted_rate,
                    "model_version": outcome.actual_model,
                    "features_used": item.features,
                }
            )
        return results

    def predict(
        self,
        request_data: dict[str, Any],
        model_id: str | None = None,
        session: Any = None,
    ) -> dict[str, Any]:
        """session 을 넘기면 inst_hist_rate 를 실제 기관 이력으로 채웁니다.

        학습은 `attach_institution_history` 로 같은 정의를 씁니다. session 을
        빼면 상수로 떨어져 train/serve skew 가 생기므로 호출부는 반드시 넘기십시오.
        """
        features = build_feature_dict(request_data, session)
        if model_id is not None or os.getenv("SKIP_MODEL_LOAD", "false").lower() == "true":
            return self._predict_from_features(features, model_id=model_id)
        return self._batcher.submit(features)


predictor = SingletonPredictor()
