"""
src/app/services/collector_service.py

수집 실행 서비스 (원본 apps/bids/management/commands/collect_bids.py 이식).
카테고리 4종을 순회 수집하고, 유니크 제약으로 중복을 무시하며 적재한 뒤
대시보드 집계와 캐시를 예열합니다.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from sqlalchemy import insert
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.bids import DATASET_ANNOUNCEMENT, DATASET_RESULT, BidAnnouncement, BidResult
from src.app.services.api_collector import (
    BID_CATEGORIES,
    get_service_key,
    stream_bid_announcements,
    stream_bid_data,
)
from src.app.services.dashboard import rebuild_bid_dataset_summaries, warm_dashboard_stats_cache
from src.app.services.home_context import warm_home_page_cache

logger = logging.getLogger(__name__)

BATCH_ROWS = 2_000


def _ignore_prefix(db: Session) -> str:
    return "OR IGNORE" if db.get_bind().dialect.name == "sqlite" else "IGNORE"


def _bulk_insert(db: Session, model, rows: list[dict[str, Any]]) -> int:
    """유니크 제약 위반은 무시하고 적재합니다 (원본 bulk_create ignore_conflicts 대응)."""
    if not rows:
        return 0
    stmt = insert(model.__table__).prefix_with(_ignore_prefix(db))
    inserted = 0
    for start in range(0, len(rows), BATCH_ROWS):
        chunk = [row for row in rows[start : start + BATCH_ROWS] if row.get("bid_ntce_no")]
        if not chunk:
            continue
        for row in chunk:
            row.setdefault("collected_at", utcnow())
        db.execute(stmt, chunk)
        db.commit()
        inserted += len(chunk)
    return inserted


async def collect_bids(
    db: Session,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    fetch_type: str = "both",
    categories: tuple[str, ...] | None = None,
    refresh_aggregates: bool = True,
) -> dict[str, Any]:
    """조달청 입찰공고/낙찰 데이터를 수집해 적재합니다."""
    if not get_service_key():
        return {
            "status": "error",
            "message": "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다.",
            "announcement_count": 0,
            "result_count": 0,
            "total_records": 0,
            "attempted": 0,
            "failed_count": 0,
        }

    yesterday = (utcnow() - timedelta(days=1)).strftime("%Y%m%d")
    start_date = start_date or yesterday
    end_date = end_date or yesterday
    target_categories = categories or tuple(BID_CATEGORIES.keys())

    metrics: dict[str, Any] = {
        "start_date": start_date,
        "end_date": end_date,
        "fetch_type": fetch_type,
        "announcement_count": 0,
        "result_count": 0,
        "attempted": 0,
        "failed_count": 0,
        "categories": {},
    }

    for cat_code in target_categories:
        cat_info = BID_CATEGORIES.get(cat_code)
        if cat_info is None:
            continue
        cat_name = cat_info["name"]
        metrics["categories"].setdefault(cat_code, {"announcement_count": 0, "result_count": 0})

        if fetch_type in ("both", "announce"):
            metrics["attempted"] += 1
            try:
                # 15일 구간이 끝나는 즉시 적재하고 버립니다. 전 구간을 모으면
                # raw_data JSON 때문에 장기 백필에서 메모리가 터집니다.
                saved = await stream_bid_announcements(
                    start_date,
                    end_date,
                    lambda rows: _bulk_insert(db, BidAnnouncement, rows),
                    category=cat_code,
                )
                metrics["announcement_count"] += saved
                metrics["categories"][cat_code]["announcement_count"] += saved
                logger.info("[%s] 입찰공고 %s건 적재", cat_name, saved)
            except Exception as exc:
                logger.exception("[%s] 입찰공고 수집 실패", cat_name)
                metrics["categories"][cat_code]["announcement_error"] = str(exc)

        if fetch_type in ("both", "result"):
            metrics["attempted"] += 1
            try:
                saved = await stream_bid_data(
                    start_date,
                    end_date,
                    lambda rows: _bulk_insert(db, BidResult, rows),
                    category=cat_code,
                )
                metrics["result_count"] += saved
                metrics["categories"][cat_code]["result_count"] += saved
                logger.info("[%s] 낙찰정보 %s건 적재", cat_name, saved)
            except Exception as exc:
                logger.exception("[%s] 낙찰정보 수집 실패", cat_name)
                metrics["categories"][cat_code]["result_error"] = str(exc)

    metrics["total_records"] = metrics["announcement_count"] + metrics["result_count"]

    # 장기 백필은 이 함수를 수십 번 호출합니다. 매번 300만 행을 훑어
    # 집계를 다시 만들면 수집보다 집계에 시간을 더 씁니다. 호출부가 끄고
    # 마지막에 한 번만 수행하도록 합니다.
    if metrics["total_records"] > 0 and refresh_aggregates:
        datasets = []
        if fetch_type in ("both", "announce"):
            datasets.append(DATASET_ANNOUNCEMENT)
        if fetch_type in ("both", "result"):
            datasets.append(DATASET_RESULT)
        try:
            rebuild_bid_dataset_summaries(db, datasets)
            warm_dashboard_stats_cache(db)
            warm_home_page_cache(db)
            metrics["cache_warmed"] = True
        except Exception as exc:
            logger.warning("대시보드 집계 또는 캐시 예열 실패: %s", exc)
            metrics["cache_warmed"] = False

    metrics["failed_count"] = sum(
        error_key in category_metrics
        for category_metrics in metrics["categories"].values()
        for error_key in ("announcement_error", "result_error")
    )
    if metrics["failed_count"] == 0:
        metrics["status"] = "success"
    elif metrics["failed_count"] == metrics["attempted"]:
        metrics["status"] = "failed"
    else:
        metrics["status"] = "partial_success"
    return metrics
