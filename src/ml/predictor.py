"""
src/ml/predictor.py

ML 모델 추론 싱글톤 로더.
요청 마다 모델 가중치를 동적으로 불러오는 오버헤드를 차단하기 위해
서버 시동 시 인메모리에 가중치를 프리로딩(Pre-loading)합니다.
"""

import json
from pathlib import Path
from typing import Any
import joblib
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

        self.model_name = "quantum_leap_v25_pro"
        self.version = "v25_pro_latest"
        self.model = None
        self.metadata = {}
        self._initialized = True
        self._load_model()

    def _load_model(self):
        """가중치 파일 프리로딩"""
        # 레지스트리 및 모델 가중치 파일 경로
        registry_path = Path("ml_registry") / self.model_name / self.version / "model.bin"
        if registry_path.exists():
            try:
                self.model = joblib.load(registry_path)
                meta_path = registry_path.parent / "metadata.json"
                if meta_path.exists():
                    with open(meta_path, encoding="utf-8") as f:
                        self.metadata = json.load(f)
            except Exception as e:
                print(f"[Predictor] 가중치 로딩 경고: {e}")

    def predict(self, request_data: dict[str, Any]) -> dict[str, Any]:
        """
        Single Source of Truth features.py를 이용하여 단일 특징 dict를 추출한 뒤
        인메모리 상주 모델로 사투가를 예측합니다.
        """
        features = build_feature_dict(request_data)
        presumed = features["presumed_price"]
        inst_rate = features.get("inst_hist_rate", 0.925)

        # 모델 객체가 상주 시 실제 predict, 없을 경우 계산 로직 적용
        if self.model is not None and hasattr(self.model, "predict"):
            try:
                # 1D feature array
                feature_vals = [list(features.values())[:4]]
                predicted_rate = float(self.model.predict(feature_vals)[0])
            except Exception:
                predicted_rate = inst_rate * 100.0
        else:
            predicted_rate = inst_rate * 100.0

        predicted_price = presumed * (predicted_rate / 100.0)

        return {
            "predicted_price": predicted_price,
            "predicted_rate": predicted_rate,
            "model_version": self.version,
            "features_used": features,
        }


predictor = SingletonPredictor()
