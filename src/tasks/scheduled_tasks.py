"""
src/tasks/scheduled_tasks.py

정기 실행 태스크. 원본의 두 스케줄을 Arq 크론으로 이식합니다.

| 원본 | 주기 | 이식본 |
| --- | --- | --- |
| 개발 데이터 최신화 | 매일 02:00 | `development_data_refresh_task` |
| Harness `BIDBOX_Personal_Nightly_Schedule` | 매일 02:00 | `nightly_schedule_task` |
| Airflow `narabid_weekly_retrain` | 매주 월요일 03:00 | `weekly_retrain_task` |

두 스케줄 모두 원본과 같은 시각을 유지하며, 환경 변수로 개별적으로 끌 수 있습니다.
개발 장비에서 새벽에 수집이 도는 것을 막기 위한 장치입니다.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from src.app.core.config import settings
from src.app.core.db import SessionLocal
from src.app.core.timeutil import utcnow
from src.app.models.chatbot import PipelineExecution
from src.app.services.automation_orchestrator import STATUS_RUNNING
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks.automation_tasks import run_automation_pipeline
from src.tasks.notifier import notify_task_failure
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
            started_at=utcnow(),
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
        execution_id = await asyncio.to_thread(
            _create_scheduled_execution, db, "nightly_schedule", "nightly"
        )
    finally:
        db.close()

    logger.info("야간 스케줄 실행 시작 (execution_id=%s)", execution_id)
    try:
        outcome = await run_automation_pipeline(
            ctx,
            execution_id=execution_id,
            action_key="nightly_schedule",
            run_mode="nightly_schedule",
            original_query="정기 야간 스케줄",
        )
    except Exception as exc:
        # 02:00 수집이 실패하면 03:00 재학습은 옛 데이터로 돕니다. 조용히
        # 지나가면 두 실패가 겹쳐도 아무도 모릅니다.
        logger.exception("야간 스케줄 실패")
        await notify_task_failure(
            "야간 수집 스케줄",
            str(exc),
            detail=f"execution_id {execution_id}. 다음 재학습이 옛 데이터로 돕니다.",
        )
        raise

    # 수집으로 원본 데이터가 바뀌었으니 상위 N 스냅샷을 다시 만듭니다.
    # 원본 스텝 구성(run_mode_matrix)을 건드리지 않으려고 파이프라인 밖에 둡니다.
    outcome["ranking_snapshots"] = await asyncio.to_thread(_rebuild_ranking_snapshots)

    # 추론 경로가 쓰는 기관 이력 집계도 함께 갱신합니다. 이 표가 낡으면
    # 학습과 추론의 inst_hist_rate 정의가 갈립니다 (AGENTS.md 6항).
    outcome["institution_stats"] = await asyncio.to_thread(_rebuild_institution_stats)
    return _mark_followup_failures(outcome)


async def development_data_refresh_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """개발 DB를 최신화하는 매일 수집·KB·집계 작업입니다."""
    if not settings.AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED:
        logger.info("개발 데이터 최신화 스케줄이 비활성화되어 있어 건너뜁니다.")
        return {"status": "skipped", "reason": "disabled"}
    if settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED:
        logger.info("운영 야간 번들이 활성화되어 개발 데이터 최신화를 건너뜁니다.")
        return {"status": "skipped", "reason": "nightly_schedule_enabled"}

    db = SessionLocal()
    try:
        execution_id = await asyncio.to_thread(
            _create_scheduled_execution,
            db,
            "development_data_refresh",
            "development_data_refresh",
        )
    finally:
        db.close()

    logger.info("개발 데이터 최신화 시작 (execution_id=%s)", execution_id)
    try:
        outcome = await run_automation_pipeline(
            ctx,
            execution_id=execution_id,
            action_key="development_data_refresh",
            run_mode="refresh_data",
            original_query="개발 정기 데이터 최신화",
        )
    except Exception as exc:
        logger.exception("개발 데이터 최신화 실패")
        await notify_task_failure(
            "개발 데이터 최신화", str(exc), detail=f"execution_id {execution_id}"
        )
        raise

    if outcome.get("status") != "success":
        return outcome

    outcome["ranking_snapshots"] = await asyncio.to_thread(_rebuild_ranking_snapshots)
    outcome["institution_stats"] = await asyncio.to_thread(_rebuild_institution_stats)
    return _mark_followup_failures(outcome)


FOLLOWUP_KEYS = ("ranking_snapshots", "institution_stats")


def _mark_followup_failures(outcome: dict[str, Any]) -> dict[str, Any]:
    """후속 집계 실패를 스케줄 최종 상태에 드러냅니다.

    파이프라인이 성공해도 기관 이력 집계가 실패하면 추론 경로의
    inst_hist_rate 가 낡은 채로 남아 학습·추론 정의가 갈립니다. 이를
    success 로 보고하면 그 어긋남을 아무도 보지 못합니다.
    """
    failed = [
        key
        for key in FOLLOWUP_KEYS
        if isinstance(outcome.get(key), dict) and outcome[key].get("status") == "failed"
    ]
    if not failed:
        return outcome

    outcome["failed_followups"] = failed
    if outcome.get("status") == "success":
        outcome["status"] = "partial_success"
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


def _rebuild_institution_stats() -> dict[str, Any]:
    """실패해도 야간 스케줄 전체를 실패로 만들지 않습니다."""
    from src.ml.institution_history import rebuild_institution_stats

    db = SessionLocal()
    try:
        return rebuild_institution_stats(db)
    except Exception as exc:
        logger.exception("기관 이력 집계 실패")
        return {"status": "failed", "error": str(exc)}
    finally:
        db.close()


async def weekly_retrain_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """매주 월요일 03:00 재학습. 원본 Airflow narabid_weekly_retrain 대체.

    CATEGORY_MODEL_NAMES 의 각 카테고리에 대해 독립적으로 재학습을 수행(fan-out)합니다.
    한 카테고리가 실패해도 다른 카테고리는 중단 없이 계속 실행되며 각 결과가 개별 기록됩니다.
    """
    if not settings.ML_WEEKLY_RETRAIN_ENABLED:
        logger.info("주간 재학습이 비활성화되어 있어 건너뜁니다.")
        return {"status": "skipped", "reason": "disabled"}

    logger.info("주간 재학습 실행 시작 (카테고리 fan-out)")
    results: dict[str, Any] = {}
    has_failure = False

    for category in sorted(CATEGORY_MODEL_NAMES.keys()):
        try:
            logger.info("주간 재학습 시작: 카테고리 %s", category)
            cat_result = await run_retrain_pipeline_task(
                ctx,
                trigger_source="weekly_schedule",
                category_code=category,
            )
            results[category] = cat_result
        except Exception as exc:
            logger.exception("주간 재학습 카테고리 %s 실패", category)
            has_failure = True
            results[category] = {
                "status": "failed",
                "category": category,
                "error": str(exc),
            }

    all_succeeded = not has_failure
    any_succeeded = any(
        isinstance(r, dict) and r.get("status") in ("success", "skipped") for r in results.values()
    )
    status = "success" if all_succeeded else ("partial_failure" if any_succeeded else "failed")
    outcome: dict[str, Any] = {
        "status": status,
        "trigger_source": "weekly_schedule",
        "categories": results,
    }
    if has_failure:
        errors = [
            f"{cat}: {res['error']}"
            for cat, res in results.items()
            if isinstance(res, dict) and res.get("status") == "failed"
        ]
        error_msg = "; ".join(errors)
        outcome["error"] = error_msg
        await notify_task_failure("주간 재학습 스케줄", error_msg)

    return outcome
