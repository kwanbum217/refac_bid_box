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

import asyncio
import json
import logging
from pathlib import Path
from typing import Any

from src.app.core.db import SessionLocal
from src.app.models.predictions import RetrainLog
from src.ml.dataset import build_training_dataset
from src.ml.trainer import ModelTrainer, trainer
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.ml.validate_model import compare_champion_vs_challenger
from src.tasks.notifier import (
    notify_empty_training_data,
    notify_retrain_result,
    notify_task_failure,
)

logger = logging.getLogger(__name__)

# 데이터셋 parquet 캐시 위치. build_training_dataset 의 기본값과 같습니다.
DEFAULT_FEATURE_STORE_DIR = "data/feature_store"

# 비교 대상을 찾지 못했을 때의 표시입니다. 예전에는 여기에 rmse=inf 를 두어
# **어떤 챌린저든 자동으로 이기게** 되어 있었습니다. 주석은 "무조건 승격되지
# 않도록" 이라 적혀 있었으나 동작은 정반대였습니다. 비교할 대상이 없으면
# 승격을 권할 근거도 없으므로, 자동 승격이 아니라 기각으로 처리합니다.
NO_CHAMPION = "__no_champion__"


def _serving_metrics(model_name: str) -> tuple[str, dict] | None:
    """실제 서빙 중인 모델의 버전과 지표를 읽습니다.

    **레지스트리가 아니라 서빙 슬롯을 봅니다.** 재학습이 레지스트리의 최신
    버전을 champion 으로 삼으면, 승격된 적 없는 실험 아티팩트와 비교하게
    됩니다. 2026-08-06 에 quantum_leap_v25_pro 가 실제로 그 상태였습니다.
    서빙본은 25.1 인데 비교 대상은 표본 2개짜리 R2 -35999 버전이었고,
    그 결과 어떤 챌린저든 승격 권고를 받았습니다.
    """
    from src.ml.promotion import load_serving_metrics

    version, metrics = load_serving_metrics(model_name)
    if not version and not metrics:
        return None
    return version, metrics


def _load_champion_metrics(model_name: str, registry_dir: str = "ml_registry") -> tuple[str, dict]:
    """현재 서빙 중인 모델의 지표를 읽습니다.

    서빙본에 지표가 없으면 비교가 불가능하다는 뜻이며, 레지스트리의 다른
    버전으로 대체하지 않습니다. 대체하면 서빙본과 무관한 근거로 승격을
    권하게 됩니다.
    """
    serving = _serving_metrics(model_name)
    if serving is not None:
        version, metrics = serving
        if metrics:
            return version, metrics
        # 서빙본은 있는데 지표가 없습니다. 원본에서 이식한 가중치가 이렇습니다.
        return version or NO_CHAMPION, {}

    base = Path(registry_dir) / model_name
    if not base.exists():
        return NO_CHAMPION, {}

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

    # champion 표시가 명시된 버전만 씁니다. "지표를 가진 최신 버전" 으로
    # 대체하면 승격된 적 없는 실험 아티팩트가 비교 대상이 됩니다.
    for version_dir in versions:
        meta_path = version_dir / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            continue
    return NO_CHAMPION, {}


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
    code = (category_code or "").strip()
    if not code or code not in CATEGORY_MODEL_NAMES:
        registered = sorted(CATEGORY_MODEL_NAMES.keys())
        raise ValueError(
            f"재학습 파이프라인에는 유효한 카테고리 코드가 필수입니다: {category_code!r}. "
            f"CATEGORY_MODEL_NAMES 에 등록된 카테고리를 지정하십시오 (등록됨: {registered})"
        )

    db = SessionLocal()
    try:
        df_train = await asyncio.to_thread(
            build_training_dataset,
            db,
            category_code=code,
            output_dir=output_dir,
            require_announcement=require_announcement,
        )
        if df_train.empty:
            await asyncio.to_thread(
                _record,
                db,
                trigger_source=trigger_source,
                champion="",
                challenger="",
                status="skipped",
                summary={"reason": "학습 데이터가 비었습니다.", "category": code},
            )
            await notify_empty_training_data(trigger_source, code)
            return {"status": "skipped", "reason": "no_training_data", "category": code}

        # 카테고리 전용 학습기를 씁니다. 분기가 없으면 용역 재학습이 물품
        # 디렉터리에 저장되고 물품 champion 과 비교됩니다.
        category_trainer = ModelTrainer.for_category(code, registry_dir=str(trainer.registry_dir))

        # champion 지표는 학습 **전에** 읽습니다. 학습 후에 읽으면 방금 저장한
        # 챌린저가 최신 버전으로 잡혀 자기 자신과 비교하게 됩니다.
        # 레지스트리 경로는 학습기와 반드시 같아야 합니다. 다르면 엉뚱한 모델과 비교합니다.
        champion_version, champion_metrics = await asyncio.to_thread(
            _load_champion_metrics,
            category_trainer.model_name,
            registry_dir=str(category_trainer.registry_dir),
        )

        metadata = await asyncio.to_thread(
            category_trainer.train_and_register,
            df_train,
        )
        challenger_metrics = metadata["metrics"]

        if champion_metrics:
            verdict = compare_champion_vs_challenger(champion_metrics, challenger_metrics)
        else:
            # 비교 대상이 없으면 승격을 권할 근거도 없습니다. 최초 승격은
            # 담당자가 지표를 확인하고 명시적으로 수행합니다.
            verdict = {
                "champion_metrics": {},
                "challenger_metrics": challenger_metrics,
                "recommendation": "REJECT_CHALLENGER",
                "rejected_reason": (
                    "서빙 중인 모델에 지표가 없어 비교할 수 없습니다. "
                    "최초 승격은 담당자가 직접 판단하십시오."
                ),
                "champion_comparable": False,
            }

        # 홀드아웃을 뗄 수 없었던 학습의 지표는 학습 구간을 그대로 잰 값이라
        # 항상 좋게 나옵니다. 그 값으로 승격시키면 게이트가 무의미해집니다.
        if metadata.get("holdout_is_overfit"):
            verdict["recommendation"] = "REJECT_CHALLENGER"
            verdict["rejected_reason"] = (
                "표본이 적어 홀드아웃 분리 실패. 지표를 신뢰할 수 없습니다."
            )

        await asyncio.to_thread(
            _record,
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
            category=code,
            holdout_is_overfit=bool(metadata.get("holdout_is_overfit")),
            champion_comparable=verdict.get("champion_comparable", True),
        )
        return {
            "status": "success",
            "trigger_source": trigger_source,
            "category": code,
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
            detail=f"대상 {category_code or '미지정'} / 트리거 {trigger_source}",
        )
        raise
    finally:
        db.close()
