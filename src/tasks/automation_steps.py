"""
src/tasks/automation_steps.py

자동화 파이프라인의 개별 스텝 구현 (_step_* 및 _check_chroma_vectors).
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select

from src.app.core.config import settings
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.automation_orchestrator import (
    STATUS_FAILED,
    STATUS_SUCCESS,
)


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
        msg = str(
            metrics.get("message") or "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다."
        )
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
) -> tuple[str, str, dict[str, Any]]:
    """ChromaDB 지식베이스 재구축 (원본 update_hybrid_kb 명령 대응).

    3요소 튜플로 status 를 그대로 전파합니다. rebuild_knowledge_base 의 status 를
    버리고 2요소 튜플을 돌려주면 디스패치 루프가 성공으로 승격합니다.
    """
    from src.app.services.kb_builder import rebuild_knowledge_base

    outcome = rebuild_knowledge_base(
        db, pipeline_run_id=execution_id, collected_since=collected_since
    )
    metrics = dict(outcome.get("metrics") or {})
    metrics.setdefault("vector_count", metrics.get("source_bid_count", 0))
    status = str(outcome.get("status") or "")
    allowed_statuses = {STATUS_SUCCESS, "partial_success", STATUS_FAILED, "error"}
    if status not in allowed_statuses:
        status = STATUS_FAILED
        summary = (
            f"KB 재구축 상태를 알 수 없어 실패 처리했습니다"
            f" (status={outcome.get('status')!r}). {outcome.get('summary', '')}".strip()
        )
        return status, summary, metrics
    summary = str(outcome.get("summary") or "")
    return status, summary, metrics


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


def _step_predict(db) -> tuple[str, dict[str, Any]] | tuple[str, str, dict[str, Any]]:
    """Champion 모델 로드 및 추론 가능 여부 검증.

    검증할 모델이나 표본이 없으면 성공이 아니라 partial_success 를 돌려줍니다.
    2요소 튜플은 디스패치 루프에서 성공으로 처리되므로, 아무것도 검증하지
    못한 실행이 통과로 승격됩니다.
    """
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
            "partial_success",
            "검증 가능한 모델 또는 공고가 없어 예측 검증을 수행하지 못했습니다.",
            # 불리언 플래그 키이며 비밀번호가 아닙니다
            {  # nosec B105
                "pass_all": False,
                "model_count": len(available),
                "skipped": True,
                "skip_reason": ("등록된 모델 없음" if not available else "검증 대상 공고 없음"),
            },
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


async def _step_retrain(db) -> tuple[str, dict[str, Any]]:
    """기존 재학습 파이프라인을 자동화 실행 이력에 연결합니다."""
    from src.tasks.retrain_task import run_retrain_pipeline_task

    outcome = await run_retrain_pipeline_task({}, trigger_source="manual_api")
    status = outcome.get("status", "unknown")
    if status == "success":
        return (
            f"재학습 완료 (버전 {outcome.get('version', '-')}, 표본 {outcome.get('samples', 0)}건, "
            f"판정 {outcome.get('recommendation', '-')}).",
            outcome,
        )
    if status == "skipped":
        return "재학습을 건너뛰었습니다. 학습 가능 데이터가 없습니다.", outcome
    return f"재학습 결과: {status}", outcome


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
            row = cursor.fetchone()
            return int(row[0]) if row is not None else None
        finally:
            conn.close()
    except Exception:
        return None


def _step_inspect(db) -> tuple[str, dict[str, Any]] | tuple[str, str, dict[str, Any]]:
    """데이터 최신성 점검 (원본 final_inspect 지표 대응).

    필수 테이블 누락이나 벡터DB 공백을 감지하면 partial_success 를 돌려줍니다.
    2요소 튜플은 디스패치 루프에서 성공으로 처리되므로, 치명적 상태가
    경고 문구만 남긴 채 통과로 승격됩니다.
    """
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
    critical: list[str] = []
    if stale_hours is not None and stale_hours > 48:
        warnings.append(f"최근 수집이 {stale_hours:.0f}시간 경과 (48시간 초과).")
    if recent_bid_announcements == 0 and recent_bid_results == 0:
        warnings.append("최근 7일 신규 공고/낙찰 데이터가 없습니다.")
    if missing_tables:
        message = f"DB 필수 테이블 누락: {', '.join(sorted(missing_tables))}"
        warnings.append(message)
        critical.append(message)
    if metrics.get("db_table_count") is None:
        message = "DB 테이블 목록을 확인하지 못했습니다."
        warnings.append(message)
        critical.append(message)
    if metrics.get("vector_count") == 0:
        message = "ChromaDB 임베딩이 비어 있습니다."
        warnings.append(message)
        critical.append(message)
    elif metrics.get("vector_count") is None:
        # None 은 "검사했더니 0건" 이 아니라 "검사하지 못함" 입니다. 0건과
        # 구분되는 치명 경고로 남겨야 점검 목적이 살아납니다.
        message = "ChromaDB 임베딩 수를 확인하지 못했습니다."
        warnings.append(message)
        critical.append(message)

    # 치명 경고를 별도 리스트로 모아 warnings 와 critical 에 함께 넣습니다.
    # 문구 startswith 로 판정하면 문구를 바꿀 때 판정이 조용히 깨집니다.
    metrics["warnings"] = warnings
    metrics["critical_warnings"] = critical

    summary = f"최근 7일 공고 {recent_bid_announcements}건, 낙찰 {recent_bid_results}건 점검 완료."
    if warnings:
        summary += " " + " ".join(warnings)
    if critical:
        return "partial_success", summary, metrics
    return summary, metrics
