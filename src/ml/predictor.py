"""
src/ml/predictor.py

ML 모델 추론 싱글톤 로더.
서버 시동 시 ModelRegistry가 4종 Champion 가중치를 프리로딩합니다.
"""

from __future__ import annotations

import os
from typing import Any

from src.ml.features import build_feature_dict


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
            # 전체 맵을 이미 구축했으므로 후보 순회에서 다시 구축하지 않게
            # 내려보냅니다. 요청당 build_default_feature_map 은 1회가 됩니다.
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


predictor = SingletonPredictor()
