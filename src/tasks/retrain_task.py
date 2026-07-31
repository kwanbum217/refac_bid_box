"""
src/tasks/retrain_task.py

Arq 비동기 재학습 태스크 정의 모듈.
"""

from typing import Any
from src.app.core.db import SessionLocal
from src.ml.dataset import build_training_dataset
from src.ml.trainer import trainer
from src.ml.validate_model import evaluate_model_performance


async def run_retrain_pipeline_task(ctx: dict[str, Any], trigger_source: str = "manual") -> dict[str, Any]:
    """재학습 전 주기 파이프라인 수행 태스크"""
    db = SessionLocal()
    try:
        # 1. dataset 빌드
        df_train = build_training_dataset(db)

        # 2. trainer 학습
        metadata = trainer.train_and_register(df_train)

        # 3. 실시간 평가
        metrics = evaluate_model_performance(df_train["winning_rate"].values, df_train["winning_rate"].values)

        return {
            "status": "success",
            "trigger_source": trigger_source,
            "version": metadata["version"],
            "metrics": metrics,
        }
    finally:
        db.close()
