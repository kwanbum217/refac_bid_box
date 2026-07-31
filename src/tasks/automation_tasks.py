"""
src/tasks/automation_tasks.py

Arq 자동화 태스크 (원본 apps/pipelines/services/local_automation.py 대체 이식).
run_mode 별 스텝 순서를 원본 matrix 그대로 따르며, 각 스텝 결과를
apply_callback_payload 계약으로 automation_requests 에 누적합니다.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from src.app.core.db import SessionLocal
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.models.chatbot import PipelineExecution
from src.app.services.automation_orchestrator import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    apply_callback_payload,
    get_automation_request,
)
from src.tasks.run_mode_matrix import get_run_mode_steps

logger = logging.getLogger(__name__)


def _report(db, automation_request_id: str, step: str, status: str, summary: str, metrics: dict, final: bool = False):
    if not automation_request_id:
        return
    request_obj = get_automation_request(db, automation_request_id)
    if request_obj is None:
        return
    apply_callback_payload(
        db,
        request_obj,
        {
            "step": step,
            "status": status,
            "summary": summary,
            "metrics": metrics,
            "final": final,
        },
    )


def _step_collect(db) -> tuple[str, dict[str, Any]]:
    """G2B 수집 스텝. 수집기가 아직 이식되지 않아 현재 적재 현황만 보고합니다."""
    today = datetime.utcnow().date()
    today_rows = db.scalar(
        select(func.count(BidAnnouncement.id)).where(
            BidAnnouncement.collected_at >= datetime.combine(today, datetime.min.time())
        )
    )
    return (
        f"G2B 수집기 미이식으로 신규 수집은 수행하지 않았습니다. 오늘 적재분 {today_rows or 0}건.",
        {"today_rows": int(today_rows or 0), "collector_available": False},
    )


def _step_rag(db) -> tuple[str, dict[str, Any]]:
    """ChromaDB 벡터 수 점검."""
    from src.app.core.config import settings

    vector_count = 0
    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
        vector_count = client.get_collection("bidding_kb").count()
    except Exception as exc:
        logger.warning("ChromaDB 점검 실패: %s", exc)

    announcement_count = db.scalar(select(func.count(BidAnnouncement.id))) or 0
    return (
        f"KB 벡터 {vector_count}건, 원본 공고 {announcement_count}건 확인.",
        {"vector_count": int(vector_count), "source_bid_count": int(announcement_count)},
    )


def _step_predict(db) -> tuple[str, dict[str, Any]]:
    """Champion 모델 로드 및 추론 가능 여부 검증."""
    from src.ml.model_registry import ModelRegistry, predict_optimal_price

    available = ModelRegistry.available_models()
    sample = db.execute(
        select(BidAnnouncement)
        .where(BidAnnouncement.presmpt_prce.is_not(None))
        .order_by(BidAnnouncement.collected_at.desc())
        .limit(1)
    ).scalar_one_or_none()

    if not available or sample is None:
        return (
            "검증 가능한 모델 또는 공고가 없어 예측 검증을 건너뜁니다.",
            {"pass_all": False, "model_count": len(available)},
        )

    reference = float(sample.prediction_reference_amount or 0)
    features = {
        "title": sample.bid_ntce_nm or "",
        "agency_name": sample.dminstt_nm or "",
        "presmpt_prce": reference,
        "real_budget": reference,
        "category": sample.category or "",
        "bid_ntce_dt": sample.bid_ntce_dt,
        "openg_dt": sample.openg_dt,
    }
    rate = predict_optimal_price(None, features)
    return (
        f"모델 {len(available)}종 로드, 표본 추론 성공 (예측률 {rate:.4f}).",
        {"pass_all": True, "model_count": len(available), "model_name": ", ".join(available)},
    )


def _step_inspect(db) -> tuple[str, dict[str, Any]]:
    """데이터 최신성 점검 (원본 final_inspect 지표 대응)."""
    now = datetime.utcnow()
    week_ago = now - timedelta(days=7)
    today_start = datetime.combine(now.date(), datetime.min.time())

    metrics = {
        "today_rows": int(
            db.scalar(
                select(func.count(BidAnnouncement.id)).where(
                    BidAnnouncement.collected_at >= today_start
                )
            )
            or 0
        ),
        "recent_bid_announcements": int(
            db.scalar(
                select(func.count(BidAnnouncement.id)).where(BidAnnouncement.bid_ntce_dt >= week_ago)
            )
            or 0
        ),
        "recent_bid_results": int(
            db.scalar(select(func.count(BidResult.id)).where(BidResult.rl_openg_dt >= week_ago)) or 0
        ),
        "fresh_ingest_announcements": int(
            db.scalar(
                select(func.count(BidAnnouncement.id)).where(
                    BidAnnouncement.collected_at >= week_ago
                )
            )
            or 0
        ),
        "fresh_ingest_results": int(
            db.scalar(select(func.count(BidResult.id)).where(BidResult.collected_at >= week_ago)) or 0
        ),
    }
    return (
        f"최근 7일 공고 {metrics['recent_bid_announcements']}건, 낙찰 {metrics['recent_bid_results']}건 점검 완료.",
        metrics,
    )


STEP_RUNNERS = {
    "collect": _step_collect,
    "rag": _step_rag,
    "predict": _step_predict,
    "inspect": _step_inspect,
}


async def run_automation_pipeline(
    ctx: dict[str, Any],
    *,
    execution_id: str = "",
    action_key: str = "",
    run_mode: str = "manual_full",
    original_query: str = "",
    automation_request_id: str = "",
) -> dict[str, Any]:
    """run_mode 에 정의된 스텝을 순서대로 실행하고 결과를 누적 보고합니다."""
    db = SessionLocal()
    completed: list[str] = []
    try:
        execution = db.execute(
            select(PipelineExecution).where(PipelineExecution.execution_id == execution_id)
        ).scalar_one_or_none()
        if execution is not None:
            execution.status = STATUS_RUNNING
            execution.started_at = execution.started_at or datetime.utcnow()
            db.commit()

        try:
            steps = get_run_mode_steps(run_mode)
        except ValueError:
            steps = ()

        for step in steps:
            runner = STEP_RUNNERS.get(step)
            if runner is None:
                continue
            if execution is not None:
                execution.stage_name = step
                execution.stage_status = STATUS_RUNNING
                db.commit()
            summary, metrics = runner(db)
            completed.append(step)
            _report(db, automation_request_id, step, "success", summary, metrics)

        final_summary = (
            f"실행 모드 `{run_mode}` 스텝 {len(completed)}개 완료: {', '.join(completed)}"
            if completed
            else f"실행 모드 `{run_mode}` 에 수행할 스텝이 없습니다."
        )
        _report(
            db,
            automation_request_id,
            "final",
            "success",
            final_summary,
            {"completed_steps": completed, "run_mode": run_mode},
            final=True,
        )

        if execution is not None:
            execution.status = STATUS_SUCCESS
            execution.stage_status = STATUS_SUCCESS
            execution.ended_at = datetime.utcnow()
            execution.logs_summary = final_summary
            execution.metrics_json = {"completed_steps": completed}
            db.commit()

        return {"status": "success", "run_mode": run_mode, "completed_steps": completed}
    except Exception as exc:
        logger.exception("자동화 파이프라인 실패 (%s)", run_mode)
        _report(
            db,
            automation_request_id,
            "final",
            "failed",
            f"실행 중 오류가 발생했습니다: {exc}",
            {"completed_steps": completed},
            final=True,
        )
        execution = db.execute(
            select(PipelineExecution).where(PipelineExecution.execution_id == execution_id)
        ).scalar_one_or_none()
        if execution is not None:
            execution.status = STATUS_FAILED
            execution.ended_at = datetime.utcnow()
            execution.logs_summary = str(exc)
            db.commit()
        return {"status": "failed", "run_mode": run_mode, "error": str(exc)}
    finally:
        db.close()


async def preflight_check_task(ctx, **kwargs):
    kwargs.pop("run_mode", None)
    return await run_automation_pipeline(ctx, run_mode="preflight_only", **kwargs)


async def collect_bids_task(ctx, **kwargs):
    kwargs.pop("run_mode", None)
    return await run_automation_pipeline(ctx, run_mode="collect_only", **kwargs)


async def update_kb_task(ctx, **kwargs):
    kwargs.pop("run_mode", None)
    return await run_automation_pipeline(ctx, run_mode="kb_only", **kwargs)


async def validate_model_task(ctx, **kwargs):
    kwargs.pop("run_mode", None)
    return await run_automation_pipeline(ctx, run_mode="predict_only", **kwargs)


async def refresh_data_task(ctx, **kwargs):
    kwargs.pop("run_mode", None)
    return await run_automation_pipeline(ctx, run_mode="refresh_data", **kwargs)


async def manual_full_task(ctx, **kwargs):
    kwargs.pop("run_mode", None)
    return await run_automation_pipeline(ctx, run_mode="manual_full", **kwargs)
