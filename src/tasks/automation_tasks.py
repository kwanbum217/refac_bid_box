"""
src/tasks/automation_tasks.py

Arq 자동화 태스크 (원본 apps/pipelines/services/local_automation.py 대체 이식).
run_mode 별 스텝 순서를 원본 matrix 그대로 따르며, 각 스텝 결과를
apply_callback_payload 계약으로 automation_requests 에 누적합니다.
"""

from __future__ import annotations

import inspect
import logging
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from src.app.core.config import settings
from src.app.core.db import SessionLocal
from src.app.core.timeutil import utcnow
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


def _post_callback(callback_url: str, callback_token: str, payload: dict) -> bool:
    """DB 를 공유하지 않는 워커가 API 로 결과를 되돌려 보냅니다."""
    import httpx

    try:
        response = httpx.post(
            callback_url,
            json=payload,
            headers={"X-BIDBOX-CALLBACK-TOKEN": callback_token},
            timeout=10,
        )
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.warning("콜백 전송 실패 (%s): %s", callback_url, exc)
        return False


# 비밀번호가 아니라 확인 토큰 기본값입니다
def _report(  # nosec B107
    db,
    automation_request_id: str,
    step: str,
    status: str,
    summary: str,
    metrics: dict,
    final: bool = False,
    callback_url: str = "",
    callback_token: str = "",
):
    """단계 결과를 요청 레코드로 되돌립니다.

    callback_url 이 있으면 API 로 보냅니다 (워커가 DB 를 공유하지 않는 배포).
    없거나 전송에 실패하면 같은 페이로드를 DB 에 직접 기록합니다.
    """
    if not automation_request_id:
        return

    payload = {
        "step": step,
        "status": status,
        "summary": summary,
        "metrics": metrics,
        "final": final,
    }

    if callback_url and _post_callback(callback_url, callback_token, payload):
        return

    request_obj = get_automation_request(db, automation_request_id)
    if request_obj is None:
        return
    apply_callback_payload(db, request_obj, payload)


async def _step_collect(db, *, refresh_aggregates: bool = True) -> tuple[str, str, dict[str, Any]]:
    """G2B 수집 스텝 (원본 collect_bids 명령 대응)."""
    from src.app.services.collector_service import collect_bids

    metrics = await collect_bids(db, refresh_aggregates=refresh_aggregates)
    status = str(metrics.get("status") or "error")
    if status not in ("success", "partial_success", "failed", "error"):
        status = "failed"

    if status == "error":
        today_rows = db.scalar(
            select(func.count(BidAnnouncement.id)).where(
                BidAnnouncement.collected_at
                >= datetime.combine(utcnow().date(), datetime.min.time())
            )
        )
        msg = str(metrics.get("message") or "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다.")
        summary = f"{msg} 오늘 적재분 {today_rows or 0}건."
        res_metrics = {
            "today_rows": int(today_rows or 0),
            "announcement_count": metrics.get("announcement_count", 0),
            "result_count": metrics.get("result_count", 0),
            "collector_available": False,
            "attempted": metrics.get("attempted", 0),
            "failed_count": metrics.get("failed_count", 0),
            "categories": metrics.get("categories", {}),
            "status": "error",
            "message": msg,
        }
        return "error", summary, res_metrics

    res_metrics = {
        "today_rows": metrics.get("total_records", 0),
        "announcement_count": metrics.get("announcement_count", 0),
        "result_count": metrics.get("result_count", 0),
        "collector_available": status in ("success", "partial_success"),
        "attempted": metrics.get("attempted", 0),
        "failed_count": metrics.get("failed_count", 0),
        "categories": metrics.get("categories", {}),
        "start_date": metrics.get("start_date", ""),
        "end_date": metrics.get("end_date", ""),
        "status": status,
    }

    if status == "success":
        summary = (
            f"수집 완료 (공고 {metrics['announcement_count']}건, 낙찰 {metrics['result_count']}건, "
            f"기간 {metrics['start_date']}~{metrics['end_date']})."
        )
    elif status == "partial_success":
        summary = (
            f"수집 부분 성공 (공고 {metrics['announcement_count']}건, 낙찰 {metrics['result_count']}건, "
            f"시도 {metrics['attempted']}건 중 실패 {metrics['failed_count']}건, "
            f"기간 {metrics['start_date']}~{metrics['end_date']})."
        )
    else:  # failed
        summary = (
            f"수집 실패 (공고 {metrics.get('announcement_count', 0)}건, 낙찰 {metrics.get('result_count', 0)}건, "
            f"시도 {metrics.get('attempted', 0)}건 중 실패 {metrics.get('failed_count', 0)}건, "
            f"기간 {metrics.get('start_date', '')}~{metrics.get('end_date', '')})."
        )

    return status, summary, res_metrics


def _step_rag(
    db, execution_id: str = "", collected_since: datetime | None = None
) -> tuple[str, dict[str, Any]]:
    """ChromaDB 지식베이스 재구축 (원본 update_hybrid_kb 명령 대응)."""
    from src.app.services.kb_builder import rebuild_knowledge_base

    outcome = rebuild_knowledge_base(
        db, pipeline_run_id=execution_id, collected_since=collected_since
    )
    metrics = dict(outcome.get("metrics") or {})
    metrics.setdefault("vector_count", metrics.get("source_bid_count", 0))
    return outcome["summary"], metrics


def _step_search(db, collected_since: datetime | None = None) -> tuple[str, dict[str, Any]]:
    """수집 성공 뒤 검색 읽기 모델을 최근 적재분만 멱등 upsert 합니다."""
    if not settings.MEILI_ENABLED:
        return "Meilisearch가 비활성화되어 검색 인덱스 동기화를 건너뜁니다.", {"skipped": True}

    from src.app.services.search_index import sync_search_index

    counts = sync_search_index(db, collected_since=collected_since)
    return (
        f"검색 인덱스 동기화 완료 (공고 {counts['announcements']}건, 낙찰 {counts['results']}건).",
        counts,
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
            # 불리언 플래그 키이며 비밀번호가 아닙니다
            {"pass_all": False, "model_count": len(available)},  # nosec B105
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
        # 불리언 플래그 키이며 비밀번호가 아닙니다
        {"pass_all": True, "model_count": len(available), "model_name": ", ".join(available)},  # nosec B105
    )


def _check_chroma_vectors() -> int | None:
    """chroma_db/chroma.sqlite3 에서 임베딩 수를 반환한다 (원본 _check_chroma 대응)."""
    import sqlite3
    from pathlib import Path

    from src.app.core.config import settings

    # 워커의 작업 디렉토리와 무관하게 동일한 경로를 보도록 설정값을 사용한다.
    chroma_path = Path(settings.CHROMA_DB_PATH) / "chroma.sqlite3"
    if not chroma_path.exists():
        return None
    try:
        conn = sqlite3.connect(f"file:{chroma_path}?mode=ro", uri=True)
        try:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM embeddings")
            return cursor.fetchone()[0]
        finally:
            conn.close()
    except Exception:
        return None


def _step_inspect(db) -> tuple[str, dict[str, Any]]:
    """데이터 최신성 점검 (원본 final_inspect 지표 대응)."""
    now = utcnow()
    week_ago = now - timedelta(days=7)
    today_start = datetime.combine(now.date(), datetime.min.time())

    recent_bid_announcements = int(
        db.scalar(
            select(func.count(BidAnnouncement.id)).where(BidAnnouncement.bid_ntce_dt >= week_ago)
        )
        or 0
    )
    recent_bid_results = int(
        db.scalar(select(func.count(BidResult.id)).where(BidResult.rl_openg_dt >= week_ago)) or 0
    )
    fresh_ingest_announcements = int(
        db.scalar(
            select(func.count(BidAnnouncement.id)).where(BidAnnouncement.collected_at >= week_ago)
        )
        or 0
    )
    fresh_ingest_results = int(
        db.scalar(select(func.count(BidResult.id)).where(BidResult.collected_at >= week_ago)) or 0
    )

    latest_notice_at = db.scalar(select(func.max(BidAnnouncement.bid_ntce_dt)))
    latest_result_open_at = db.scalar(select(func.max(BidResult.rl_openg_dt)))
    latest_announcement_collected = db.scalar(select(func.max(BidAnnouncement.collected_at)))
    latest_result_collected = db.scalar(select(func.max(BidResult.collected_at)))
    collected_candidates = [
        ts for ts in (latest_announcement_collected, latest_result_collected) if ts is not None
    ]
    latest_collected_at = max(collected_candidates) if collected_candidates else None

    stale_hours: float | None = None
    if latest_collected_at is not None:
        stale_hours = round((now - latest_collected_at).total_seconds() / 3600, 1)

    metrics = {
        "today_rows": int(
            db.scalar(
                select(func.count(BidAnnouncement.id)).where(
                    BidAnnouncement.collected_at >= today_start
                )
            )
            or 0
        ),
        "recent_bid_announcements": recent_bid_announcements,
        "recent_bid_results": recent_bid_results,
        "fresh_ingest_announcements": fresh_ingest_announcements,
        "fresh_ingest_results": fresh_ingest_results,
        "latest_notice_at": latest_notice_at.isoformat() if latest_notice_at else None,
        "latest_result_open_at": latest_result_open_at.isoformat()
        if latest_result_open_at
        else None,
        "latest_collected_at": latest_collected_at.isoformat() if latest_collected_at else None,
        "stale_hours": stale_hours,
    }

    # DB 무결성 점검 (원본 _check_db_integrity 대응)
    missing_tables: set[str] = set()
    try:
        from sqlalchemy import inspect as sa_inspect

        inspector = sa_inspect(db.bind)
        existing_tables = set(inspector.get_table_names())
        essential_tables = {"bid_announcements", "bid_results", "accounts_customuser"}
        missing_tables = essential_tables - existing_tables
        metrics["db_table_count"] = len(existing_tables)
    except Exception:
        metrics["db_table_count"] = None

    # ChromaDB 벡터 수 점검 (원본 _check_chroma 대응)
    metrics["vector_count"] = _check_chroma_vectors()

    warnings: list[str] = []
    if stale_hours is not None and stale_hours > 48:
        warnings.append(f"최근 수집이 {stale_hours:.0f}시간 경과 (48시간 초과).")
    if recent_bid_announcements == 0 and recent_bid_results == 0:
        warnings.append("최근 7일 신규 공고/낙찰 데이터가 없습니다.")
    if missing_tables:
        warnings.append(f"DB 필수 테이블 누락: {', '.join(sorted(missing_tables))}")
    if metrics.get("vector_count") == 0:
        warnings.append("ChromaDB 임베딩이 비어 있습니다.")

    summary = f"최근 7일 공고 {recent_bid_announcements}건, 낙찰 {recent_bid_results}건 점검 완료."
    if warnings:
        summary += " " + " ".join(warnings)
    return summary, metrics


STEP_RUNNERS = {
    "collect": _step_collect,
    "search": _step_search,
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
    callback_url: str = "",
    callback_token: str = "",
) -> dict[str, Any]:
    """run_mode 에 정의된 스텝을 순서대로 실행하고 결과를 누적 보고합니다."""
    delivery = {"callback_url": callback_url, "callback_token": callback_token}
    db = SessionLocal()
    completed: list[str] = []
    try:
        execution = db.execute(
            select(PipelineExecution).where(PipelineExecution.execution_id == execution_id)
        ).scalar_one_or_none()
        if execution is not None:
            execution.status = STATUS_RUNNING
            execution.started_at = execution.started_at or utcnow()
            db.commit()

        try:
            steps = get_run_mode_steps(run_mode)
        except ValueError:
            steps = ()

        pipeline_status = STATUS_SUCCESS
        pipeline_error = ""
        step_statuses: dict[str, str] = {}

        for step in steps:
            runner = STEP_RUNNERS.get(step)
            if runner is None:
                continue
            if execution is not None:
                execution.stage_name = step
                execution.stage_status = STATUS_RUNNING
                db.commit()
            kwargs = {}
            if "execution_id" in inspect.signature(runner).parameters:
                kwargs["execution_id"] = execution_id
            # 개발 최신화는 수집 직후 500만 행 대시보드 전수 집계를 하지 않습니다.
            # 이후 스냅샷·기관 통계 갱신으로 추론 경로의 최신성은 유지합니다.
            if step == "collect" and run_mode == "refresh_data":
                kwargs["refresh_aggregates"] = False
            if step == "rag" and run_mode == "refresh_data":
                # 직전 실패·재기동 뒤에도 적재분을 놓치지 않도록 24시간 겹침 구간을
                # 다시 upsert 합니다. 문서 ID가 안정적이므로 중복 벡터는 생기지 않습니다.
                kwargs["collected_since"] = utcnow() - timedelta(days=1)
            if step == "search" and run_mode == "refresh_data":
                # 수집 API 재시도와 워커 재기동을 고려해 24시간을 겹쳐 upsert 합니다.
                kwargs["collected_since"] = utcnow() - timedelta(days=1)
            outcome = runner(db, **kwargs)
            res = await outcome if inspect.isawaitable(outcome) else outcome

            if isinstance(res, tuple) and len(res) == 3:
                step_status, summary, metrics = res
            elif isinstance(res, tuple) and len(res) == 2:
                summary, metrics = res
                step_status = (
                    str(metrics.get("status"))
                    if isinstance(metrics, dict) and metrics.get("status")
                    else STATUS_SUCCESS
                )
            else:
                step_status = STATUS_SUCCESS
                summary = str(res)
                metrics = {}

            completed.append(step)
            step_statuses[step] = step_status
            _report(db, automation_request_id, step, step_status, summary, metrics, **delivery)

            if execution is not None:
                execution.stage_status = step_status
                db.commit()

            if step_status == STATUS_SUCCESS:
                pass
            elif step_status == "partial_success":
                pipeline_status = STATUS_FAILED
                pipeline_error = summary
            elif step_status in (STATUS_FAILED, "error"):
                pipeline_status = STATUS_FAILED
                pipeline_error = summary
                break
            else:
                pipeline_status = STATUS_FAILED
                pipeline_error = summary
                break

        if pipeline_status == STATUS_SUCCESS:
            final_summary = (
                f"실행 모드 `{run_mode}` 스텝 {len(completed)}개 완료: {', '.join(completed)}"
                if completed
                else f"실행 모드 `{run_mode}` 에 수행할 스텝이 없습니다."
            )
            _report(
                db,
                automation_request_id,
                "final",
                STATUS_SUCCESS,
                final_summary,
                {"completed_steps": completed, "run_mode": run_mode},
                final=True,
                **delivery,
            )

            if execution is not None:
                execution.status = STATUS_SUCCESS
                execution.stage_status = STATUS_SUCCESS
                execution.ended_at = utcnow()
                execution.logs_summary = final_summary
                execution.metrics_json = {"completed_steps": completed}
                db.commit()

            return {"status": STATUS_SUCCESS, "run_mode": run_mode, "completed_steps": completed}
        else:
            final_summary = (
                f"실행 모드 `{run_mode}` 스텝 완료 중 이상 발생: {pipeline_error}"
                if pipeline_error
                else f"실행 모드 `{run_mode}` 실패"
            )
            _report(
                db,
                automation_request_id,
                "final",
                STATUS_FAILED,
                final_summary,
                {"completed_steps": completed, "run_mode": run_mode, "step_statuses": step_statuses},
                final=True,
                **delivery,
            )

            if execution is not None:
                execution.status = STATUS_FAILED
                if execution.stage_status != "error":
                    execution.stage_status = STATUS_FAILED
                execution.ended_at = utcnow()
                execution.logs_summary = final_summary
                execution.metrics_json = {"completed_steps": completed, "step_statuses": step_statuses}
                db.commit()

            return {
                "status": STATUS_FAILED,
                "run_mode": run_mode,
                "completed_steps": completed,
                "error": pipeline_error or final_summary,
            }
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
            **delivery,
        )
        execution = db.execute(
            select(PipelineExecution).where(PipelineExecution.execution_id == execution_id)
        ).scalar_one_or_none()
        if execution is not None:
            execution.status = STATUS_FAILED
            execution.ended_at = utcnow()
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
