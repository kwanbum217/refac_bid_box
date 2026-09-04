"""
src/tasks/summary_tasks.py

대시보드 데이터셋 요약 백그라운드 재집계 Arq 태스크.
읽기 경로에서 분리된 재집계 쓰기 작업을 비동기 워커가 전담합니다.
"""

from __future__ import annotations

import logging
from typing import Any

from src.app.core.db import SessionLocal
from src.app.services.dashboard import rebuild_bid_dataset_summary

logger = logging.getLogger(__name__)


async def rebuild_dataset_summary_task(ctx: dict[str, Any], dataset: str) -> dict[str, Any]:
    """데이터셋 요약 통계를 전체 재집계하는 Arq 백그라운드 태스크."""
    logger.info("데이터셋 요약 재집계 작업 시작: dataset=%s", dataset)
    with SessionLocal() as db:
        summary = rebuild_bid_dataset_summary(db, dataset)
        result = {
            "dataset": summary.dataset,
            "total_count": summary.total_count,
            "total_amount": int(summary.total_amount or 0),
            "aggregation_version": summary.aggregation_version,
            "rebuilt_at": summary.rebuilt_at.isoformat() if summary.rebuilt_at else None,
        }
    logger.info("데이터셋 요약 재집계 작업 완료: dataset=%s, result=%s", dataset, result)
    return result


__all__ = ["rebuild_dataset_summary_task"]
