"""
src/tasks/automation_tasks.py

Arq 자동화 태스크 (원본 apps/pipelines/services/local_automation.py 대체 이식).
run_mode 별 스텝 순서를 원본 matrix 그대로 따르며, 각 스텝 결과를
apply_callback_payload 계약으로 automation_requests 에 누적합니다.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
from collections.abc import Callable
from datetime import timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.core.db import SessionLocal
from src.app.core.timeutil import utcnow
from src.app.models.chatbot import PipelineExecution
from src.app.services.api_collector import mask_credentials
from src.app.services.automation_orchestrator import (
    STATUS_FAILED,
    STATUS_RUNNING,
    STATUS_SUCCESS,
    apply_callback_payload,
    get_automation_request,
)
from src.tasks.automation_steps import (
    _check_chroma_vectors,
    _step_collect,
    _step_inspect,
    _step_predict,
    _step_rag,
    _step_retrain,
    _step_search,
)
from src.tasks.run_mode_matrix import get_run_mode_steps

# fmt: off
__all__ = [
    "STEP_RUNNERS",
    "_check_chroma_vectors",
    "_invoke_sync_runner",
    "_post_callback",
    "_report",
    "_step_collect",
    "_step_inspect",
    "_step_predict",
    "_step_rag",
    "_step_retrain",
    "_step_search",
    "collect_bids_task",
    "manual_full_task",
    "manual_retrain_task",
    "preflight_check_task",
    "refresh_data_task",
    "run_automation_pipeline",
    "update_kb_task",
    "validate_model_task",
]
# fmt: on

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
    db: Session | str | None = None,
    automation_request_id: str = "",
    step: str = "",
    status: str = "",
    summary: str = "",
    metrics: dict | None = None,
    final: bool = False,
    callback_url: str = "",
    callback_token: str = "",
):
    """단계 결과를 요청 레코드로 되돌립니다.

    callback_url 이 있으면 API 로 보냅니다 (워커가 DB 를 공유하지 않는 배포).
    없거나 전송에 실패하면 같은 페이로드를 DB 에 직접 기록합니다.
    """
    caller_db = None
    if isinstance(db, Session):
        caller_db = db
        req_id = automation_request_id
        st = step
        sta = status
        summ = summary
        met = metrics if isinstance(metrics, dict) else {}
        fin = final
        cb_url = callback_url
        cb_token = callback_token
    else:
        req_id = str(db or automation_request_id or "")
        st = step
        sta = status
        summ = summary
        met = metrics if isinstance(metrics, dict) else {}
        fin = final
        cb_url = callback_url
        cb_token = callback_token

    if not req_id:
        return

    payload = {
        "step": st,
        "status": sta,
        "summary": summ,
        "metrics": met,
        "final": fin,
    }

    if cb_url and _post_callback(cb_url, cb_token, payload):
        return

    own_session = caller_db is None
    session = SessionLocal() if own_session else caller_db
    try:
        request_obj = get_automation_request(session, req_id)
        if request_obj is None:
            return
        apply_callback_payload(session, request_obj, payload)
    except Exception as exc:
        logger.warning("자동화 요청 결과 보고 DB 반영 실패 (%s): %s", req_id, exc)
        try:
            session.rollback()
        except Exception as rb_exc:
            logger.debug("요청 보고 롤백 실패: %s", rb_exc)
    finally:
        if own_session:
            session.close()


def _invoke_sync_runner(runner_fn: Callable[..., object], kwargs: dict[str, object]) -> object:
    sig = inspect.signature(runner_fn)
    if "db" in sig.parameters:
        runner_db = SessionLocal()
        try:
            return runner_fn(runner_db, **kwargs)
        finally:
            runner_db.close()
    return runner_fn(**kwargs)


STEP_RUNNERS: dict[str, Callable[..., object]] = {
    "collect": _step_collect,
    "search": _step_search,
    "rag": _step_rag,
    "predict": _step_predict,
    "retrain": _step_retrain,
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

        # 알 수 없는 run_mode 를 빈 스텝으로 대체하면 아무 일도 하지 않고
        # SUCCESS 로 보고됩니다. 큐 인자 오타나 API-워커 버전 불일치가 조용한
        # 성공으로 바뀌므로 바깥 예외 처리로 넘겨 실패로 보고합니다.
        steps = get_run_mode_steps(run_mode)

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
            runner_fn = runner
            kwargs: dict[str, object] = {}
            if "execution_id" in inspect.signature(runner_fn).parameters:
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
            if inspect.iscoroutinefunction(runner_fn):
                res = await runner_fn(db, **kwargs)
            else:
                outcome: object = await asyncio.to_thread(_invoke_sync_runner, runner_fn, kwargs)
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
            await asyncio.to_thread(
                _report,
                None,
                automation_request_id,
                step,
                step_status,
                summary,
                metrics,
                callback_url=callback_url,
                callback_token=callback_token,
            )

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
            await asyncio.to_thread(
                _report,
                None,
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
            await asyncio.to_thread(
                _report,
                None,
                automation_request_id,
                "final",
                STATUS_FAILED,
                final_summary,
                {
                    "completed_steps": completed,
                    "run_mode": run_mode,
                    "step_statuses": step_statuses,
                },
                final=True,
                **delivery,
            )

            if execution is not None:
                execution.status = STATUS_FAILED
                if execution.stage_status != "error":
                    execution.stage_status = STATUS_FAILED
                execution.ended_at = utcnow()
                execution.logs_summary = final_summary
                execution.metrics_json = {
                    "completed_steps": completed,
                    "step_statuses": step_statuses,
                }
                db.commit()

            return {
                "status": STATUS_FAILED,
                "run_mode": run_mode,
                "completed_steps": completed,
                "error": pipeline_error or final_summary,
            }
    except Exception as exc:
        logger.exception("자동화 파이프라인 실패 (%s)", run_mode)
        try:
            db.rollback()
        except Exception as rb_err:
            logger.warning("파이프라인 실패 후 세션 rollback 실패: %s", rb_err)

        try:
            await asyncio.to_thread(
                _report,
                None,
                automation_request_id,
                "final",
                "failed",
                f"실행 중 오류가 발생했습니다: {mask_credentials(exc)}",
                {"completed_steps": completed},
                final=True,
                **delivery,
            )
        except Exception as rep_err:
            logger.error("파이프라인 실패 보고 기록 실패: %s", rep_err)
            logger.error("파이프라인 실패 보고 기록 실패: %s", rep_err)

        try:
            execution = db.execute(
                select(PipelineExecution).where(PipelineExecution.execution_id == execution_id)
            ).scalar_one_or_none()
            if execution is not None:
                execution.status = STATUS_FAILED
                execution.ended_at = utcnow()
                execution.logs_summary = mask_credentials(exc)
                db.commit()
        except Exception as exec_err:
            logger.error("PipelineExecution 상태 갱신 실패: %s", exec_err)
            try:
                db.rollback()
            except Exception as rb_exc:
                logger.debug("실행 상태 갱신 롤백 실패: %s", rb_exc)

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


async def manual_retrain_task(ctx, **kwargs):
    kwargs.pop("run_mode", None)
    return await run_automation_pipeline(ctx, run_mode="retrain_only", **kwargs)
