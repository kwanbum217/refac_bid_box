"""
src/tasks/summary_tasks.py

대시보드 데이터셋 요약 백그라운드 재집계 Arq 태스크.
읽기 경로에서 분리된 재집계 쓰기 작업을 비동기 워커가 전담합니다.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from src.app.core.db import SessionLocal
from src.app.core.observability import traced_worker_task
from src.app.services.dashboard import rebuild_bid_dataset_summary
from src.rag.structured_data import refresh_institution_name_catalogs

logger = logging.getLogger(__name__)


def _rebuild_bid_dataset_summary(dataset: str) -> dict[str, Any]:
    """동기 DB 세션을 열어 데이터셋 요약을 재집계합니다. 워커 스레드 전용입니다."""
    with SessionLocal() as db:
        summary = rebuild_bid_dataset_summary(db, dataset)
        return {
            "dataset": summary.dataset,
            "total_count": summary.total_count,
            "total_amount": int(summary.total_amount or 0),
            "aggregation_version": summary.aggregation_version,
            "rebuilt_at": summary.rebuilt_at.isoformat() if summary.rebuilt_at else None,
        }


def _refresh_institution_catalogs() -> dict[str, int]:
    """동기 DB 세션을 열어 기관명 목록 캐시를 갱신합니다. 워커 스레드 전용입니다."""
    with SessionLocal() as db:
        return refresh_institution_name_catalogs(db)


@traced_worker_task
async def rebuild_dataset_summary_task(ctx: dict[str, Any], dataset: str) -> dict[str, Any]:
    """데이터셋 요약 통계를 전체 재집계하는 Arq 백그라운드 태스크."""
    logger.info("데이터셋 요약 재집계 작업 시작: dataset=%s", dataset)
    result = await asyncio.to_thread(_rebuild_bid_dataset_summary, dataset)
    logger.info("데이터셋 요약 재집계 작업 완료: dataset=%s, result=%s", dataset, result)
    return result


@traced_worker_task
async def refresh_institution_catalog_task(ctx: dict[str, Any]) -> dict[str, int]:
    """RAG 기관명 해석이 쓰는 고유 기관명 목록 캐시를 매시 갱신합니다."""
    counts = await asyncio.to_thread(_refresh_institution_catalogs)
    logger.info("기관명 목록 캐시 갱신 완료: %s", counts)
    return counts


__all__ = ["rebuild_dataset_summary_task", "refresh_institution_catalog_task"]
