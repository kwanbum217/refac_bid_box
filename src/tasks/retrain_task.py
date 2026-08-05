"""
src/tasks/retrain_task.py

Arq 비동기 재학습 태스크.

AGENTS.md 의 비협상 원칙 "신규 모델은 champion 을 성능으로 압도할 때만 승격,
즉시 롤백 가능" 을 이 파일이 집행합니다. 판정 자체는 기존 모듈
(`validate_model.compare_champion_vs_challenger`)에 위임하고, 여기서는 순서와
이력 기록을 담당합니다.

**승격은 자동으로 이뤄지지 않습니다.** 챌린저를 registry 에 남기고 권고만
기록합니다. champion 교체는 담당자가 결과를 보고 판단합니다.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from src.app.core.db import SessionLocal
from src.app.models.predictions import RetrainLog
from src.ml.dataset import build_training_dataset
from src.ml.trainer import ModelTrainer, trainer
from src.ml.validate_model import compare_champion_vs_challenger
from src.tasks.notifier import (
    notify_empty_training_data,
    notify_retrain_result,
    notify_task_failure,
)

logger = logging.getLogger(__name__)

# 데이터셋 parquet 캐시 위치. build_training_dataset 의 기본값과 같습니다.
DEFAULT_FEATURE_STORE_DIR = "data/feature_store"

# champion 이 없을 때 쓰는 비교 기준. 첫 학습이 무조건 승격되지 않도록
# 의도적으로 낮은 난이도가 아닌 값을 둡니다. 담당자가 조정합니다.
COLD_START_CHAMPION_METRICS = {"rmse": float("inf"), "mape": float("inf"), "r2": float("-inf")}


def _load_champion_metrics(model_name: str, registry_dir: str = "ml_registry") -> tuple[str, dict]:
    """registry 에서 현재 champion 의 지표를 읽습니다.

    champion 표시가 없으면 가장 최근 버전을 기준으로 삼습니다. 없으면 cold start.
    """
    base = Path(registry_dir) / model_name
    if not base.exists():
        return "", dict(COLD_START_CHAMPION_METRICS)

    versions = sorted((p for p in base.iterdir() if p.is_dir()), reverse=True)
    for version_dir in versions:
        meta_path = version_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if meta.get("status") == "champion" and meta.get("metrics"):
            return str(meta.get("version") or version_dir.name), meta["metrics"]

    # champion 표시가 없으면 지표를 가진 최신 버전을 비교 대상으로 씁니다.
    for version_dir in versions:
        meta_path = version_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
        if meta.get("metrics"):
            return str(meta.get("version") or version_dir.name), meta["metrics"]

    return "", dict(COLD_START_CHAMPION_METRICS)


def _record(db, *, trigger_source: str, champion: str, challenger: str, status: str, summary: dict):
    """재학습 이력을 남깁니다. 지금까지 retrain_logs 는 비어 있었습니다."""
    db.add(
        RetrainLog(
            trigger_source=trigger_source,
            champion_version=champion or "-",
            challenger_version=challenger or "-",
            status=status,
            metrics_summary=summary,
        )
    )
    db.commit()


async def run_retrain_pipeline_task(
    ctx: dict[str, Any],
    trigger_source: str = "manual",
    category_code: str | None = None,
    require_announcement: bool = True,
    output_dir: str = DEFAULT_FEATURE_STORE_DIR,
) -> dict[str, Any]:
    """재학습 전 주기: 데이터셋 빌드 -> 학습 -> 홀드아웃 평가 -> 승격 판정 -> 이력 기록.

    output_dir 을 노출하는 이유는 테스트 때문입니다. 기본값으로 두면 테스트가
    소량 픽스처로 만든 프레임이 운영 feature store 의 parquet 을 덮어씁니다.
    """
    db = SessionLocal()
    try:
        df_train = build_training_dataset(
            db,
            category_code=category_code,
            output_dir=output_dir,
            require_announcement=require_announcement,
        )
        if df_train.empty:
            _record(
                db,
                trigger_source=trigger_source,
                champion="",
                challenger="",
                status="skipped",
                summary={"reason": "학습 데이터가 비었습니다.", "category": category_code},
            )
            await notify_empty_training_data(trigger_source, category_code)
            return {"status": "skipped", "reason": "no_training_data", "category": category_code}

        # 카테고리 전용 학습기를 씁니다. 분기가 없으면 용역 재학습이 물품
        # 디렉터리에 저장되고 물품 champion 과 비교됩니다.
        category_trainer = ModelTrainer.for_category(
            category_code, registry_dir=str(trainer.registry_dir)
        )

        # champion 지표는 학습 **전에** 읽습니다. 학습 후에 읽으면 방금 저장한
        # 챌린저가 최신 버전으로 잡혀 자기 자신과 비교하게 됩니다.
        # 레지스트리 경로는 학습기와 반드시 같아야 합니다. 다르면 엉뚱한 모델과 비교합니다.
        champion_version, champion_metrics = _load_champion_metrics(
            category_trainer.model_name, registry_dir=str(category_trainer.registry_dir)
        )

        metadata = category_trainer.train_and_register(df_train)
        challenger_metrics = metadata["metrics"]

        verdict = compare_champion_vs_challenger(champion_metrics, challenger_metrics)

        # 홀드아웃을 뗄 수 없었던 학습의 지표는 학습 구간을 그대로 잰 값이라
        # 항상 좋게 나옵니다. 그 값으로 승격시키면 게이트가 무의미해집니다.
        if metadata.get("holdout_is_overfit"):
            verdict["recommendation"] = "REJECT_CHALLENGER"
            verdict["rejected_reason"] = "표본이 적어 홀드아웃 분리 실패. 지표를 신뢰할 수 없습니다."

        _record(
            db,
            trigger_source=trigger_source,
            champion=champion_version,
            challenger=metadata["version"],
            status=verdict["recommendation"],
            summary=verdict,
        )

        logger.info(
            "재학습 완료 (%s) 표본 %d, 판정 %s",
            metadata["version"],
            metadata["samples_count"],
            verdict["recommendation"],
        )
        # 승격이 수동이므로 권고가 사람에게 닿아야 고리가 이어집니다.
        await notify_retrain_result(
            trigger_source=trigger_source,
            recommendation=verdict["recommendation"],
            champion_version=champion_version,
            challenger_version=metadata["version"],
            champion_metrics=champion_metrics,
            challenger_metrics=challenger_metrics,
            samples=metadata["samples_count"],
            category=category_code,
            holdout_is_overfit=bool(metadata.get("holdout_is_overfit")),
        )
        return {
            "status": "success",
            "trigger_source": trigger_source,
            "category": category_code,
            "version": metadata["version"],
            "champion_version": champion_version,
            "samples": metadata["samples_count"],
            "metrics": challenger_metrics,
            "recommendation": verdict["recommendation"],
        }
    except Exception as exc:
        # 알리기만 하고 그대로 올립니다. 여기서 삼키면 호출부가 성공으로 오인합니다.
        await notify_task_failure(
            "재학습 파이프라인",
            str(exc),
            detail=f"대상 {category_code or '전체'} / 트리거 {trigger_source}",
        )
        raise
    finally:
        db.close()
