"""
src/ml/predictor.py

ML 모델 추론 싱글톤 로더.
서버 시동 시 ModelRegistry가 4종 Champion 가중치를 프리로딩합니다.
"""

from __future__ import annotations

import gc
import logging
import os
import queue
import threading
import time
from typing import Any

from src.ml.features import build_feature_dict

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# GC 모드 설정 — 모듈 임포트 시 한 번만 실행됩니다.
# PREDICTION_GC_MODE 가 빈 문자열이거나 설정되지 않으면 아무것도 변경하지
# 않으므로 기본 경로는 완전히 무비용입니다.
# ---------------------------------------------------------------------------
_GC_MODE = os.environ.get("PREDICTION_GC_MODE", "")

# threshold 모드의 임계값:
# CPython 기본값은 (700, 10, 10) 입니다.
# gen1 을 20, gen2 를 30 으로 올리면 generation-2 순회 빈도를 약 1/3 로 줄이면서
# 메모리 누증 위험은 gc.disable() 보다 현저히 낮습니다.
# gen0 는 그대로 두어 단기 객체 회수를 유지합니다.
_GC_THRESHOLD_GEN0 = 700
_GC_THRESHOLD_GEN1 = 20
_GC_THRESHOLD_GEN2 = 30

if _GC_MODE == "threshold":
    gc.set_threshold(_GC_THRESHOLD_GEN0, _GC_THRESHOLD_GEN1, _GC_THRESHOLD_GEN2)

# batch-disable 모드: 마이크로배치 스레드 안에서만 GC 를 끕니다.
# _run() 루프가 이 카운터를 보고 일정 배치마다 수동 collect 를 수행합니다.
_BATCH_DISABLE_COLLECT_EVERY = 50  # N 배치마다 gc.collect() 호출


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
    # 배치 스레드가 죽거나 멈추면 대기 중인 요청은 아무 응답도 받지 못합니다.
    # 오류가 아니라 무응답이라 상위 계층이 감지할 수 없으므로, 대기에 상한을
    # 두고 만료 시 호출 스레드가 단건 경로로 직접 처리합니다.
    SUBMIT_TIMEOUT_SECONDS = 5.0

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
        if not item.event.wait(self.SUBMIT_TIMEOUT_SECONDS):
            logger.warning(
                "마이크로배치 응답이 %.1f초 안에 오지 않아 단건 경로로 처리합니다.",
                self.SUBMIT_TIMEOUT_SECONDS,
            )
            return self._predict_one(item.features)
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
        if _GC_MODE == "batch-disable":
            gc.disable()
            batch_count = 0
        while True:
            batch = self._collect()
            # 어떤 실패도 스레드를 끝내지 못하게 합니다. 이 스레드가 죽으면
            # 이후 모든 요청이 응답 없이 대기하다 타임아웃으로 떨어집니다.
            try:
                self._dispatch(batch)
            except BaseException as exc:
                logger.exception("마이크로배치 처리가 실패했습니다.")
                self._release(batch, exc)
            if _GC_MODE == "batch-disable":
                batch_count += 1
                if batch_count % _BATCH_DISABLE_COLLECT_EVERY == 0:
                    gc.collect()


    def _dispatch(self, batch: list[_BatchItem]) -> None:
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
        if len(results) != len(batch):
            raise ValueError(
                f"배치 결과 수({len(results)})가 요청 수({len(batch)})와 다릅니다."
            )
        for item, result in zip(batch, results, strict=True):
            item.result = result
            item.event.set()

    @staticmethod
    def _release(batch: list[_BatchItem], error: BaseException) -> None:
        """대기 중인 항목을 남기지 않고 모두 깨웁니다."""
        for item in batch:
            if not item.event.is_set():
                if item.error is None:
                    item.error = error
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
            if _GC_MODE == "freeze":
                gc.freeze()
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
