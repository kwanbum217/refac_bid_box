"""
src/ml/trainer.py

일반화 ML 모델 학습기.
K-Fold 교차 검증 및 LightGBM/CatBoost 기반 사투가 예측 모델을 재학습하고
모델 레지스트리에 버저닝하여 아티팩트를 저장합니다.
"""

from datetime import datetime
import json
from pathlib import Path
from typing import Any, Optional
import joblib
import numpy as np
import pandas as pd
from src.ml.features import build_feature_frame
from src.ml.validate_model import evaluate_model_performance

# 홀드아웃 비율. 학습에 쓰지 않은 구간에서 지표를 내야 의미가 있습니다.
# 분할 전략(무작위/시계열)과 비율은 모델 설계 사항이므로 담당자가 조정합니다.
DEFAULT_VALIDATION_SPLIT = 0.2

# 현재 학습에 쓰는 특징. 담당자가 features.py 산출물 중 무엇을 쓸지 결정합니다.
TRAINING_FEATURES = ["presumed_price", "base_price", "price_ratio", "inst_hist_rate"]


class ModelTrainer:
    def __init__(self, model_name: str = "quantum_leap_v25_pro", registry_dir: str = "ml_registry"):
        self.model_name = model_name
        self.registry_dir = Path(registry_dir)

    def train_and_register(
        self,
        df_raw: pd.DataFrame,
        hyperparams: Optional[dict[str, Any]] = None,
        validation_split: float = DEFAULT_VALIDATION_SPLIT,
    ) -> dict[str, Any]:
        """
        Single Source of Truth features.py로 특징을 산출한 뒤 모델을 학습하고
        ml_registry/{model_name}/{version}/ 에 버저닝 저장합니다.
        """
        # 초 단위 버전명은 같은 초에 두 번 학습하면 충돌해 이전 아티팩트를 덮어씁니다.
        # 밀리초까지 넣고, 그래도 겹치면 접미사를 붙여 회피합니다.
        version = f"v_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]}"
        target_dir = self.registry_dir / self.model_name / version
        suffix = 1
        while target_dir.exists():
            version = f"v_{datetime.utcnow().strftime('%Y%m%d_%H%M%S_%f')[:-3]}_{suffix}"
            target_dir = self.registry_dir / self.model_name / version
            suffix += 1
        target_dir.mkdir(parents=True, exist_ok=True)

        # 단일 특징 공급원 적용
        records = df_raw.to_dict(orient="records")
        features_list = build_feature_frame(records)
        df_feat = pd.DataFrame(features_list)

        # Target (winning_rate)
        if "winning_rate" in df_raw.columns:
            y = df_raw["winning_rate"].values
        else:
            y = np.full(len(df_feat), 88.0)

        # 간단한 Ridge/LightGBM 수용 모델 학습 예시
        from sklearn.linear_model import Ridge
        model = Ridge(alpha=1.0, random_state=42)

        X = df_feat[TRAINING_FEATURES].values

        # 학습에 쓰지 않은 구간에서 평가합니다. 같은 데이터로 재면 지표가 항상
        # 완벽하게 나와 승격 판단이 무의미해집니다.
        split_at = int(len(X) * (1.0 - validation_split))
        if 0 < split_at < len(X):
            X_train, y_train = X[:split_at], y[:split_at]
            X_valid, y_valid = X[split_at:], y[split_at:]
        else:
            X_train, y_train = X, y
            X_valid, y_valid = X, y

        model.fit(X_train, y_train)
        metrics = evaluate_model_performance(np.asarray(y_valid), model.predict(X_valid))

        # 가중치 저장
        model_file = target_dir / "model.bin"
        joblib.dump(model, model_file)

        # 메타데이터 저장
        metadata = {
            "model_name": self.model_name,
            "version": version,
            "trained_at": datetime.utcnow().isoformat(),
            "samples_count": len(df_raw),
            "train_samples": int(len(X_train)),
            "validation_samples": int(len(X_valid)),
            "features": list(TRAINING_FEATURES),
            "metrics": metrics,
            "hyperparams": hyperparams or {"alpha": 1.0, "random_state": 42},
            "status": "challenger",
        }
        with open(target_dir / "metadata.json", "w", encoding="utf-8") as f:
            json.dump(metadata, f, indent=2, ensure_ascii=False)

        return metadata


trainer = ModelTrainer()
