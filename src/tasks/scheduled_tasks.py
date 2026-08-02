"""
src/tasks/scheduled_tasks.py

정기 실행 태스크. 원본의 두 스케줄을 Arq 크론으로 이식합니다.

| 원본 | 주기 | 이식본 |
| --- | --- | --- |
| Harness `BIDBOX_Personal_Nightly_Schedule` | 매일 02:00 | `nightly_schedule_task` |
| Airflow `narabid_weekly_retrain` | 매주 월요일 03:00 | `weekly_retrain_task` |

두 스케줄 모두 원본과 같은 시각을 유지하며, 환경 변수로 개별적으로 끌 수 있습니다.
개발 장비에서 새벽에 수집이 도는 것을 막기 위한 장치입니다.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any

from src.app.core.config import settings
from src.app.core.db import SessionLocal
from src.app.models.chatbot import PipelineExecution
from src.app.services.automation_orchestrator import STATUS_RUNNING
from src.tasks.automation_tasks import run_automation_pipeline
from src.tasks.retrain_task import run_retrain_pipeline_task

logger = logging.getLogger(__name__)

# 원본 run_local_automation_bundle 의 기본 source 라벨과 동일하게 맞춥니다.
SCHEDULER_SOURCE = "local_scheduler"


def _create_scheduled_execution(db, run_mode: str, trigger_name: str) -> str:
    """스케줄 실행도 챗봇 실행과 같은 이력 테이블에 남깁니다."""
    execution_id = f"{run_mode}-{uuid.uuid4().hex[:12]}"
    db.add(
        PipelineExecution(
            execution_id=execution_id,
            pipeline_name="refac_bid_box_pipeline",
            run_mode=run_mode,
            status=STATUS_RUNNING,
            source=SCHEDULER_SOURCE,
            started_at=datetime.utcnow(),
            raw_status_payload={
                "action_key": run_mode,
                "trigger_name": trigger_name,
                "scheduled": True,
            },
        )
    )
    db.commit()
    return execution_id


async def nightly_schedule_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """매일 02:00 수집-KB-예측-점검 번들. 원본 Harness 야간 트리거 대체."""
    if not settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED:
        logger.info("야간 스케줄이 비활성화되어 있어 건너뜁니다.")
        return {"status": "skipped", "reason": "disabled"}

    db = SessionLocal()
    try:
        execution_id = _create_scheduled_execution(db, "nightly_schedule", "nightly")
    finally:
        db.close()

    logger.info("야간 스케줄 실행 시작 (execution_id=%s)", execution_id)
    outcome = await run_automation_pipeline(
        ctx,
        execution_id=execution_id,
        action_key="nightly_schedule",
        run_mode="nightly_schedule",
        original_query="정기 야간 스케줄",
    )

    # 수집으로 원본 데이터가 바뀌었으니 상위 N 스냅샷을 다시 만듭니다.
    # 원본 스텝 구성(run_mode_matrix)을 건드리지 않으려고 파이프라인 밖에 둡니다.
    outcome["ranking_snapshots"] = _rebuild_ranking_snapshots()
    return outcome


def _rebuild_ranking_snapshots() -> dict[str, Any]:
    """실패해도 야간 스케줄 전체를 실패로 만들지 않습니다."""
    from src.app.services.ranking_snapshots import rebuild_ranking_snapshots

    db = SessionLocal()
    try:
        return rebuild_ranking_snapshots(db)
    except Exception as exc:
        logger.exception("상위 N 스냅샷 재집계 실패")
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


async def weekly_retrain_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """매주 월요일 03:00 재학습. 원본 Airflow narabid_weekly_retrain 대체."""
    if not settings.ML_WEEKLY_RETRAIN_ENABLED:
        logger.info("주간 재학습이 비활성화되어 있어 건너뜁니다.")
        return {"status": "skipped", "reason": "disabled"}

    logger.info("주간 재학습 실행 시작")
    try:
        return await run_retrain_pipeline_task(ctx, trigger_source="weekly_schedule")
    except Exception as exc:
        # 스케줄 실패로 워커가 죽으면 이후 크론까지 함께 멈춥니다.
        logger.exception("주간 재학습 실패")
        return {"status": "failed", "trigger_source": "weekly_schedule", "error": str(exc)}
