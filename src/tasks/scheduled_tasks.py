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
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import StrEnum
from functools import wraps
from pathlib import Path
from typing import Any, cast

import pandas as pd
from sqlalchemy.orm import Session

from scripts.backup_recovery import execute_backup, prune_snapshots
from src.app.core.cache import RedisConnection
from src.app.core.config import settings
from src.app.core.db import SessionLocal
from src.app.core.timeutil import utcnow
from src.app.models.chatbot import PipelineExecution
from src.app.models.predictions import RetrainLog
from src.app.services.automation_orchestrator import STATUS_RUNNING
from src.ml.dataset import build_training_dataset
from src.ml.features import (
    apply_categorical_dtypes,
    build_feature_frame,
    collect_category_levels,
)
from src.ml.institution_history import attach_institution_history
from src.ml.monitoring import (
    check_dataset_drift,
    load_baseline_distributions,
)
from src.ml.repeat_history import attach_repeat_history
from src.ml.training_config import CATEGORY_MODEL_NAMES
from src.tasks.automation_tasks import run_automation_pipeline
from src.tasks.notifier import notify_drift_detected, notify_task_failure
from src.tasks.retrain_task import run_retrain_pipeline_task

logger = logging.getLogger(__name__)

# 원본 run_local_automation_bundle 의 기본 source 라벨과 동일하게 맞춥니다.
SCHEDULER_SOURCE = "local_scheduler"


def _record_schedule(
    schedule_name: str,
) -> Callable[[Callable[..., Awaitable[Any]]], Callable[..., Awaitable[Any]]]:
    """스케줄 결과를 기록하되 기록 실패가 작업을 방해하지 않게 합니다."""

    def decorator(task: Callable[..., Awaitable[Any]]) -> Callable[..., Awaitable[Any]]:
        @wraps(task)
        async def tracked(*args: Any, **kwargs: Any) -> Any:
            from src.tasks.worker import record_schedule_result

            try:
                outcome = await task(*args, **kwargs)
            except Exception:
                record_schedule_result(schedule_name, None, False)
                raise
            success = isinstance(outcome, dict) and outcome.get("status") in {"success", "skipped"}
            record_schedule_result(schedule_name, outcome, success)
            return outcome

        return cast(Any, tracked)

    return decorator


@_record_schedule("backup")
async def backup_schedule_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """매일 03:00 통합 백업을 실행하고 개수 기준 보존 상태를 보고합니다."""
    if not settings.BACKUP_SCHEDULE_ENABLED:
        logger.info("백업 스케줄이 비활성화되어 있어 건너뜁니다.")
        return {"status": "skipped", "reason": "disabled"}
    try:
        manifest = await asyncio.to_thread(execute_backup, execute=True)
        retention = await asyncio.to_thread(
            prune_snapshots,
            retain_count=settings.BACKUP_RETENTION_COUNT,
            delete=False,
        )
        return {"status": "success", "manifest": manifest, "retention": retention}
    except Exception as exc:
        logger.exception("정기 백업 실패")
        await notify_task_failure("통합 백업 스케줄", str(exc))
        return {"status": "failed", "error": str(exc)}


def _create_scheduled_execution(
    db: Session | None = None,
    run_mode: str = "nightly_schedule",
    trigger_name: str = "nightly",
) -> str:
    """스케줄 실행도 챗봇 실행과 같은 이력 테이블에 남깁니다."""
    own_session = db is None
    session = SessionLocal() if own_session else db
    try:
        execution_id = f"{run_mode}-{uuid.uuid4().hex[:12]}"
        session.add(
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
        session.commit()
        return execution_id
    finally:
        if own_session:
            session.close()


@_record_schedule("nightly_schedule")
async def nightly_schedule_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """매일 02:00 수집-KB-예측-점검 번들. 원본 Harness 야간 트리거 대체."""
    if not settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED:
        logger.info("야간 스케줄이 비활성화되어 있어 건너뜁니다.")
        return {"status": "skipped", "reason": "disabled"}

    claim = acquire_schedule_claim("nightly_schedule")
    if not claim.acquired:
        if claim.status == ScheduleClaimStatus.ALREADY_CLAIMED:
            logger.info("야간 스케줄 실행 건너뜀 (이미 claim됨, key=%s)", claim.key)
            return {
                "status": "skipped",
                "reason": "already_claimed",
                "claim": claim.to_dict(),
            }
        logger.error(
            "야간 스케줄 claim 획득 실패 (fail-closed, status=%s): %s",
            claim.status.value,
            claim.detail,
        )
        return {
            "status": "failed",
            "reason": claim.status.value,
            "claim": claim.to_dict(),
        }

    execution_id = await asyncio.to_thread(
        _create_scheduled_execution, None, "nightly_schedule", "nightly"
    )

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

    if outcome.get("status") != "success":
        return outcome

    # 수집으로 원본 데이터가 바뀌었으니 상위 N 스냅샷을 다시 만듭니다.
    # 원본 스텝 구성(run_mode_matrix)을 건드리지 않으려고 파이프라인 밖에 둡니다.
    outcome["ranking_snapshots"] = await asyncio.to_thread(_rebuild_ranking_snapshots)

    # 추론 경로가 쓰는 기관 이력 집계도 함께 갱신합니다. 이 표가 낡으면
    # 학습과 추론의 inst_hist_rate 정의가 갈립니다 (AGENTS.md 6항).
    outcome["institution_stats"] = await asyncio.to_thread(_rebuild_institution_stats)
    final_outcome = _mark_followup_failures(outcome)
    if final_outcome.get("status") == "success":
        release_schedule_claim(claim.key, token=claim.token)
    return final_outcome


@_record_schedule("development_data_refresh")
async def development_data_refresh_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """개발 DB를 최신화하는 매일 수집·KB·집계 작업입니다."""
    if not settings.AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED:
        logger.info("개발 데이터 최신화 스케줄이 비활성화되어 있어 건너뜁니다.")
        return {"status": "skipped", "reason": "disabled"}
    if settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED:
        logger.info("운영 야간 번들이 활성화되어 개발 데이터 최신화를 건너뜁니다.")
        return {"status": "skipped", "reason": "nightly_schedule_enabled"}

    claim = acquire_schedule_claim("development_data_refresh")
    if not claim.acquired:
        if claim.status == ScheduleClaimStatus.ALREADY_CLAIMED:
            logger.info("개발 데이터 최신화 실행 건너뜀 (이미 claim됨, key=%s)", claim.key)
            return {
                "status": "skipped",
                "reason": "already_claimed",
                "claim": claim.to_dict(),
            }
        logger.error(
            "개발 데이터 최신화 claim 획득 실패 (fail-closed, status=%s): %s",
            claim.status.value,
            claim.detail,
        )
        return {
            "status": "failed",
            "reason": claim.status.value,
            "claim": claim.to_dict(),
        }

    execution_id = await asyncio.to_thread(
        _create_scheduled_execution,
        None,
        "development_data_refresh",
        "development_data_refresh",
    )

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
    final_outcome = _mark_followup_failures(outcome)
    if final_outcome.get("status") == "success":
        release_schedule_claim(claim.key, token=claim.token)
    return final_outcome


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


@_record_schedule("weekly_retrain")
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


def _record_drift_log(
    db: Session | None = None,
    *,
    trigger_source: str = "drift_monitor",
    champion_version: str = "-",
    baseline_version: str = "-",
    status: str = "",
    metrics_summary: dict[str, Any] | None = None,
) -> None:
    """드리프트 검사 판정 결과를 retrain_logs 테이블에 기록합니다.

    테이블 스키마 변경 없이 challenger_version 필드를 baseline_version 으로 해석하여 사용합니다.
    """
    own_session = db is None
    session = SessionLocal() if own_session else db
    try:
        session.add(
            RetrainLog(
                trigger_source=trigger_source,
                champion_version=champion_version or "-",
                challenger_version=baseline_version or "-",  # baseline_version 을 의미함
                status=status,
                metrics_summary=metrics_summary or {},
            )
        )
        session.commit()
    finally:
        if own_session:
            session.close()


def _build_training_dataset_thread(
    category_code: str,
    start_at: datetime,
    end_at: datetime,
    persist: bool = False,
) -> pd.DataFrame:
    """스레드 전용 세션에서 학습 데이터셋을 빌드합니다."""
    db = SessionLocal()
    try:
        return build_training_dataset(
            db,
            category_code=category_code,
            start_at=start_at,
            end_at=end_at,
            persist=persist,
        )
    finally:
        db.close()


def is_drift_monitor_enabled() -> bool:
    """PSI 드리프트 모니터링 활성화 여부 확인. (기본값: False)"""
    return bool(settings.ML_DRIFT_MONITOR_ENABLED)


@_record_schedule("drift_monitor")
async def drift_monitor_task(
    ctx: dict[str, Any],
    evaluation_window_days: int = 7,
    registry_dir: str = "ml_registry",
) -> dict[str, Any]:
    """매일 04:00 주기적 PSI 드리프트 검사 태스크.

    - settings/환경변수 ML_DRIFT_MONITOR_ENABLED 플래그로 활성화 제어 (기본값: False)
    - CATEGORY_MODEL_NAMES 의 각 카테고리별 모델에 대해 baseline 아티팩트 조회
    - 평가 윈도우 [now - evaluation_window_days, now) 반열림 구간(개찰일 기준)으로 최근 데이터만 조회
    - persist=False 로 운영 학습 데이터셋 Parquet 덮어쓰기 방지
    - Single Source of Truth features.py 를 통해 최근 N일 평가 데이터의 특징 프레임 산출
    - check_dataset_drift 호출하여 다차원 PSI 계산 및 판정
    - 판정 결과를 retrain_logs 테이블에 기록 (스키마 변경 없이 challenger_version 에 baseline_version 기록)
    - 드리프트 감지(PSI >= 0.2) 시 notify_drift_detected 로 운영 알림 발신
    - 자동 재학습이나 자동 승격은 수행하지 않음 (사람이 수동 개입 판단)
    """
    if not is_drift_monitor_enabled():
        logger.info("PSI 드리프트 모니터링이 비활성화되어 있어 건너뜁니다.")
        return {"status": "skipped", "reason": "disabled"}

    logger.info("PSI 드리프트 모니터링 태스크 시작 (평가 윈도우=%d일)", evaluation_window_days)
    results: dict[str, Any] = {}
    has_failure = False

    try:
        for category in sorted(CATEGORY_MODEL_NAMES.keys()):
            model_name = CATEGORY_MODEL_NAMES[category]
            baseline_dir = Path(registry_dir) / model_name / "baseline"

            baseline_dist = await asyncio.to_thread(load_baseline_distributions, baseline_dir)
            if not baseline_dist:
                logger.info(
                    "카테고리 %s (%s)의 baseline 분포 아티팩트가 없습니다 (%s). 판정 보류.",
                    category,
                    model_name,
                    baseline_dir,
                )
                insufficient_summary: dict[str, Any] = {
                    "reason": f"Baseline 분포 아티팩트가 없습니다 ({baseline_dir}).",
                    "category": category,
                    "model_name": model_name,
                }
                await asyncio.to_thread(
                    _record_drift_log,
                    trigger_source="drift_monitor",
                    champion_version=model_name,
                    baseline_version="-",
                    status="INSUFFICIENT_DATA",
                    metrics_summary=insufficient_summary,
                )
                results[category] = {
                    "status": "skipped",
                    "reason": "no_baseline",
                    "category": category,
                    "model_name": model_name,
                }
                continue

            try:
                # 최근 데이터셋 수집 (Single Source of Truth features.py 사용)
                # 평가 윈도우 [now - evaluation_window_days, now) 반열림 구간 적용 (개찰일 기준 start_at 이상, end_at 미만)
                # 모니터링 경로는 persist=False 로 운영 Parquet 덮어쓰기 방지
                now = utcnow()
                start_at = now - timedelta(days=evaluation_window_days)
                end_at = now

                df_raw = await asyncio.to_thread(
                    _build_training_dataset_thread,
                    category_code=category,
                    start_at=start_at,
                    end_at=end_at,
                    persist=False,
                )

                if df_raw.empty:
                    insufficient_summary = {
                        "reason": (
                            f"카테고리 {category}에 대한 최근 평가 데이터가 없습니다 "
                            f"(평가 윈도우={evaluation_window_days}일, 구간: [{start_at.isoformat()}, {end_at.isoformat()}))."
                        ),
                        "category": category,
                        "model_name": model_name,
                        "recent_samples": 0,
                        "evaluation_window_days": evaluation_window_days,
                    }
                    await asyncio.to_thread(
                        _record_drift_log,
                        trigger_source="drift_monitor",
                        champion_version=model_name,
                        baseline_version=baseline_dist.get("model_version", "-"),
                        status="INSUFFICIENT_DATA",
                        metrics_summary=insufficient_summary,
                    )
                    results[category] = {
                        "status": "INSUFFICIENT_DATA",
                        "category": category,
                        "model_name": model_name,
                        "samples": 0,
                    }
                    continue

                # 단일 특징 공급원(features.py) 거침
                df_raw = attach_institution_history(df_raw)
                df_raw = attach_repeat_history(df_raw)
                records = df_raw.to_dict(orient="records")
                features_list = build_feature_frame(records)
                df_feat = pd.DataFrame(features_list)
                category_levels = collect_category_levels(df_feat)
                df_feat = apply_categorical_dtypes(df_feat, category_levels)

                # 드리프트 판정
                drift_verdict = check_dataset_drift(
                    baseline_dist,
                    df_feat,
                    evaluation_window_days=evaluation_window_days,
                )

                # retrain_logs 에 기록
                await asyncio.to_thread(
                    _record_drift_log,
                    trigger_source="drift_monitor",
                    champion_version=model_name,
                    baseline_version=baseline_dist.get("model_version", "-"),
                    status=drift_verdict["status"],
                    metrics_summary=drift_verdict,
                )

                results[category] = {
                    "status": drift_verdict["status"],
                    "category": category,
                    "model_name": model_name,
                    "baseline_version": baseline_dist.get("model_version", "-"),
                    "samples": drift_verdict["recent_samples"],
                    "drift_feature_count": drift_verdict["drift_feature_count"],
                    "drift_features": drift_verdict["drift_features"],
                    "by_subgroup": drift_verdict.get("by_subgroup"),
                    "drift_subgroup_type": drift_verdict.get("drift_subgroup_type"),
                }

                # 드리프트 감지 시 알림 발신 (자동 재학습·승격은 수행하지 않음)
                if drift_verdict["status"] == "DRIFT_DETECTED":
                    await notify_drift_detected(
                        model_name=model_name,
                        model_version=baseline_dist.get("model_version", "-"),
                        drift_features=drift_verdict["drift_features"],
                        total_features_checked=drift_verdict["total_features_checked"],
                        evaluation_window_days=evaluation_window_days,
                        baseline_version=baseline_dist.get("model_version", "-"),
                        recent_samples=drift_verdict["recent_samples"],
                        drift_by_subgroup=drift_verdict.get("by_subgroup"),
                        drift_subgroup_type=drift_verdict.get("drift_subgroup_type"),
                    )

            except Exception as cat_exc:
                logger.exception("카테고리 %s 드리프트 검사 실패", category)
                has_failure = True
                results[category] = {
                    "status": "failed",
                    "category": category,
                    "error": str(cat_exc),
                }

    except Exception as exc:
        logger.exception("PSI 드리프트 모니터링 스케줄 실패")
        await notify_task_failure("PSI 드리프트 모니터링", str(exc))
        raise

    outcome: dict[str, Any] = {
        "status": (
            "failed"
            if has_failure
            and not any(
                r.get("status") in ("STABLE", "DRIFT_DETECTED", "INSUFFICIENT_DATA", "skipped")
                for r in results.values()
            )
            else ("partial_failure" if has_failure else "success")
        ),
        "trigger_source": "drift_monitor",
        "categories": results,
    }
    return outcome


# --------------------------------------------------------------------------- #
# 수집 스케줄 공통 Redis 원자 claim 및 기동 시 따라잡기 (Startup Catch-up)
# --------------------------------------------------------------------------- #

SCHEDULE_COLLECTION_CLAIM_KEY = "bidbox:schedule:collection_claim"
CATCHUP_LAST_ATTEMPT_KEY = SCHEDULE_COLLECTION_CLAIM_KEY

RELEASE_SCHEDULE_CLAIM_SCRIPT = """
local val = redis.call('GET', KEYS[1])
if not val then
    return 0
end
local ok, data = pcall(cjson.decode, val)
if ok and type(data) == 'table' and data['token'] == ARGV[1] then
    return redis.call('DEL', KEYS[1])
else
    return 0
end
"""


class ScheduleClaimStatus(StrEnum):
    ACQUIRED = "acquired"
    ALREADY_CLAIMED = "already_claimed"
    REDIS_UNAVAILABLE = "redis_unavailable"
    COMMAND_ERROR = "command_error"


@dataclass(frozen=True)
class ScheduleClaimResult:
    status: ScheduleClaimStatus
    key: str
    owner: str
    ttl: int
    token: str | None = None
    detail: str | None = None
    error: str | None = None

    @property
    def acquired(self) -> bool:
        return self.status == ScheduleClaimStatus.ACQUIRED

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "acquired": self.acquired,
            "key": self.key,
            "owner": self.owner,
            "ttl": self.ttl,
            "token": self.token,
            "detail": self.detail,
            "error": self.error,
        }


_schedule_redis_conn: RedisConnection | None = None


def get_schedule_redis_conn() -> RedisConnection:
    global _schedule_redis_conn
    if _schedule_redis_conn is None:
        _schedule_redis_conn = RedisConnection(label="schedule_guard")
    return _schedule_redis_conn


def set_schedule_redis_conn(conn: RedisConnection | None) -> None:
    global _schedule_redis_conn
    _schedule_redis_conn = conn


def get_schedule_claim_ttl() -> int:
    cooldown_hours = getattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS", 6)
    return max(int(cooldown_hours * 3600), 60)


def acquire_schedule_claim(
    owner: str,
    *,
    key: str = SCHEDULE_COLLECTION_CLAIM_KEY,
    ttl_seconds: int | None = None,
    conn: RedisConnection | None = None,
) -> ScheduleClaimResult:
    """수집 스케줄 단일 실행을 위한 Redis SET NX EX 원자적 claim을 수행합니다.

    CacheLayer 의 로컬 fallback을 일절 사용하지 않고 RedisConnection 을 직접 사용합니다.
    Redis 가 연결되지 않거나 명령 실패 시 fail-closed 로 처리하여 작업을 시작하지 않습니다.
    """
    ttl = ttl_seconds if ttl_seconds is not None else get_schedule_claim_ttl()
    redis_conn = conn or get_schedule_redis_conn()
    client = redis_conn.client()
    if client is None:
        logger.warning(
            "[%s] Redis 연결 불가로 스케줄 실행 claim을 획득하지 못했습니다 (fail-closed, key=%s)",
            owner,
            key,
        )
        return ScheduleClaimResult(
            status=ScheduleClaimStatus.REDIS_UNAVAILABLE,
            key=key,
            owner=owner,
            ttl=ttl,
            token=None,
            detail="Redis 연결이 불가능하여 스케줄 실행 claim을 획득할 수 없습니다.",
            error="Redis client unavailable",
        )

    now_iso = utcnow().isoformat()
    token = uuid.uuid4().hex
    payload = json.dumps(
        {"owner": owner, "token": token, "claimed_at": now_iso, "ttl": ttl},
        ensure_ascii=False,
    )
    try:
        acquired = bool(client.set(key, payload, ex=ttl, nx=True))
    except Exception as exc:
        redis_conn.invalidate(exc)
        logger.warning(
            "[%s] Redis claim 명령 실패 (fail-closed, key=%s): %s",
            owner,
            key,
            exc,
        )
        return ScheduleClaimResult(
            status=ScheduleClaimStatus.COMMAND_ERROR,
            key=key,
            owner=owner,
            ttl=ttl,
            token=None,
            detail=f"Redis claim 명령 실행 중 오류가 발생했습니다: {exc}",
            error=str(exc),
        )

    if not acquired:
        logger.info(
            "[%s] 스케줄 실행 claim이 이미 존재하여 건너뜁니다 (key=%s)",
            owner,
            key,
        )
        return ScheduleClaimResult(
            status=ScheduleClaimStatus.ALREADY_CLAIMED,
            key=key,
            owner=owner,
            ttl=ttl,
            token=None,
            detail="이미 다른 스케줄 또는 워커가 실행 claim을 획득했습니다.",
        )

    logger.info(
        "[%s] 스케줄 실행 claim 획득 성공 (key=%s, ttl=%d초, token=%s)",
        owner,
        key,
        ttl,
        token,
    )
    return ScheduleClaimResult(
        status=ScheduleClaimStatus.ACQUIRED,
        key=key,
        owner=owner,
        ttl=ttl,
        token=token,
        detail="스케줄 실행 claim 획득 성공",
    )


def release_schedule_claim(
    key: str = SCHEDULE_COLLECTION_CLAIM_KEY,
    token: str | None = None,
    *,
    conn: RedisConnection | None = None,
) -> bool:
    """소유 토큰이 일치하는 경우에만 Redis Lua 스크립트로 원자적 claim 해제를 수행합니다.

    GET 후 DEL 조합이 아닌 단일 원자 연산으로, 이전 실행이 TTL 경과 후 생성된 후속 실행의
    새 claim을 잘못 삭제하는 경합(stale owner deletion)을 원천 방지합니다.
    토큰이 누락되었거나 일치하지 않으면 해제를 거부하고 후속 claim을 보존합니다.
    """
    if not token:
        logger.warning(
            "스케줄 claim 해제 건너뜀 (소유 토큰이 누락됨, key=%s)",
            key,
        )
        return False

    redis_conn = conn or get_schedule_redis_conn()
    client = redis_conn.client()
    if client is None:
        return False
    try:
        deleted = client.eval(RELEASE_SCHEDULE_CLAIM_SCRIPT, 1, key, token)
        return bool(deleted)
    except Exception as exc:
        redis_conn.invalidate(exc)
        logger.warning("스케줄 claim 해제 중 오류 발생 (key=%s): %s", key, exc)
        return False


def _as_utc(dt: datetime) -> datetime:
    """datetime 객체를 UTC aware datetime 으로 정규화합니다."""
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def get_latest_collection_time(db: Session | None = None) -> datetime | None:
    """bid_announcements 테이블의 최신 collected_at 시각을 조회합니다.

    데이터가 없으면 None 을 반환합니다.
    """
    from sqlalchemy import func, select

    from src.app.models.bids import BidAnnouncement

    own_session = db is None
    session = SessionLocal() if own_session else db
    try:
        return session.execute(select(func.max(BidAnnouncement.collected_at))).scalar()
    finally:
        if own_session:
            session.close()


def record_catchup_attempt(
    attempt_time: datetime | None = None,
    *,
    key: str = SCHEDULE_COLLECTION_CLAIM_KEY,
    ttl_seconds: int | None = None,
    conn: RedisConnection | None = None,
) -> ScheduleClaimResult:
    """하위 호환성을 위한 claim 기록 함수.

    CacheLayer 대신 RedisConnection 을 사용하여 SET NX EX 원자적 claim을 수행합니다.
    예외를 삼키지 않고 명시적 ScheduleClaimResult 를 반환합니다.
    """
    return acquire_schedule_claim(
        "catchup_attempt",
        key=key,
        ttl_seconds=ttl_seconds,
        conn=conn,
    )


def is_catchup_in_cooldown(
    conn: RedisConnection | None = None,
    key: str = SCHEDULE_COLLECTION_CLAIM_KEY,
) -> tuple[bool, str | None]:
    """공통 claim 키를 확인하여 쿨다운 상태 여부와 마지막 시도 시각(ISO 문자열)을 반환합니다.

    CacheLayer 의 로컬 fallback을 사용하지 않고 RedisConnection 으로 직접 확인합니다.
    """
    redis_conn = conn or get_schedule_redis_conn()
    client = redis_conn.client()
    if client is None:
        return False, None
    try:
        raw = client.get(key)
        if not raw:
            return False, None
        data = json.loads(raw)
        if isinstance(data, dict):
            attempted = data.get("claimed_at") or data.get("attempted_at")
            return True, attempted
        return True, str(data)
    except Exception as exc:
        redis_conn.invalidate(exc)
        logger.warning("스케줄 쿨다운 상태 확인 중 오류 발생: %s", exc)
        return False, None


def check_schedule_catchup_needed(
    db: Session | None = None,
) -> tuple[bool, str, dict[str, Any]]:
    """기동 시 스케줄 따라잡기 필요 여부를 판정합니다.

    Returns:
        (needed, reason, details)
    """
    if not settings.AUTOMATION_SCHEDULE_CATCHUP_ENABLED:
        return (
            False,
            "disabled",
            {
                "enabled": False,
                "reason": "AUTOMATION_SCHEDULE_CATCHUP_ENABLED is False",
            },
        )

    # 활성 스케줄 태스크 선택 (운영 nightly_schedule 우선, 없으면 development_data_refresh)
    if settings.AUTOMATION_NIGHTLY_SCHEDULE_ENABLED:
        target_task = "nightly_schedule"
    elif settings.AUTOMATION_DATA_REFRESH_SCHEDULE_ENABLED:
        target_task = "development_data_refresh"
    else:
        return (
            False,
            "no_active_schedule",
            {
                "enabled": True,
                "reason": "모든 자동화 수집 스케줄 태스크가 비활성화되어 있습니다.",
            },
        )

    # 쿨다운 확인 (재시작 루프 방어)
    in_cooldown, last_attempt = is_catchup_in_cooldown()
    if in_cooldown:
        return (
            False,
            "in_cooldown",
            {
                "enabled": True,
                "target_task": target_task,
                "last_attempt": last_attempt,
                "cooldown_hours": settings.AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS,
                "reason": f"최근 시도 쿨다운({settings.AUTOMATION_SCHEDULE_CATCHUP_COOLDOWN_HOURS}시간) 이내입니다.",
            },
        )

    latest_collected_at = get_latest_collection_time(db)
    threshold_hours = settings.AUTOMATION_SCHEDULE_CATCHUP_THRESHOLD_HOURS
    now = utcnow()

    if latest_collected_at is None:
        return (
            True,
            "no_previous_collection",
            {
                "enabled": True,
                "target_task": target_task,
                "latest_collected_at": None,
                "threshold_hours": threshold_hours,
                "reason": "이전 공고 수집 이력이 존재하지 않아 따라잡기를 실행합니다.",
            },
        )

    elapsed = _as_utc(now) - _as_utc(latest_collected_at)
    elapsed_hours = elapsed.total_seconds() / 3600.0

    details: dict[str, Any] = {
        "enabled": True,
        "target_task": target_task,
        "latest_collected_at": latest_collected_at.isoformat(),
        "elapsed_hours": round(elapsed_hours, 2),
        "threshold_hours": threshold_hours,
    }

    if elapsed_hours >= threshold_hours:
        details["reason"] = (
            f"마지막 수집 후 {elapsed_hours:.1f}시간 경과하여 임계치({threshold_hours}시간)를 초과했습니다."
        )
        return True, "threshold_exceeded", details

    details["reason"] = (
        f"마지막 수집 후 {elapsed_hours:.1f}시간 경과하여 임계치({threshold_hours}시간) 이내입니다."
    )
    return False, "threshold_not_exceeded", details


@_record_schedule("schedule_catchup")
async def run_schedule_catchup_task(ctx: dict[str, Any]) -> dict[str, Any]:
    """기동 시 누락된 스케줄 수집을 따라잡는 진입점 태스크입니다."""
    needed, reason, details = check_schedule_catchup_needed()
    logger.info(
        "스케줄 따라잡기 판정: needed=%s, reason=%s, details=%s",
        needed,
        reason,
        details,
    )

    if not needed:
        return {
            "status": "skipped",
            "reason": reason,
            "details": details,
        }

    target_task = details["target_task"]
    logger.info(
        "스케줄 따라잡기 실행 시작 (target_task=%s, details=%s)",
        target_task,
        details,
    )

    # 주의: target_task(nightly_schedule 또는 development_data_refresh) 내부에서
    # 동일한 공통 Redis 원자 claim을 획득하므로, 바깥에서 별도로 claim을 획득하여
    # 자기 충돌(self-collision)을 만들지 않습니다.
    try:
        if target_task == "nightly_schedule":
            outcome = await nightly_schedule_task(ctx)
        else:
            outcome = await development_data_refresh_task(ctx)
        outcome["catchup_details"] = details
        return outcome
    except Exception as exc:
        logger.exception("스케줄 따라잡기 실행 실패: %s", exc)
        return {
            "status": "failed",
            "reason": "execution_failed",
            "error": str(exc),
            "catchup_details": details,
        }
