"""
src/app/services/collector_service.py

수집 실행 서비스 (원본 apps/bids/management/commands/collect_bids.py 이식).
카테고리 4종을 순회 수집하고, 유니크 제약으로 중복을 무시하며 적재한 뒤
대시보드 집계와 캐시를 예열합니다.

누락일 자동 회복:
  날짜를 명시하지 않으면 DB의 최신 공고일/개찰일을 체크포인트로 삼아
  어제까지의 공백을 자동으로 회수합니다.
  MAX_CATCHUP_DAYS 를 초과하는 공백은 자동 회수하지 않으며
  scripts/backfill_from_g2b.py 를 사용해 수동으로 채웁니다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.orm import Session

from src.app.core.timeutil import utcnow
from src.app.models.bids import DATASET_ANNOUNCEMENT, DATASET_RESULT, BidAnnouncement, BidResult
from src.app.services.api_collector import (
    BID_CATEGORIES,
    RangeCollectionError,
    get_service_key,
    mask_credentials,
    stream_bid_announcements,
    stream_bid_data,
)
from src.app.services.dashboard import rebuild_bid_dataset_summaries, warm_dashboard_stats_cache
from src.app.services.home_context import warm_home_page_cache

logger = logging.getLogger(__name__)

BATCH_ROWS = 2_000

# 날짜 미지정 시 자동으로 회수하는 최대 일 수.
# API 과부하와 수집 시간 예산을 고려한 상한입니다. 이보다 오래된 공백은
# scripts/backfill_from_g2b.py 로 수동 채우기가 필요합니다.
MAX_CATCHUP_DAYS = 7


def resolve_collection_window(
    db: Session,
    *,
    start_date: str | None,
    end_date: str | None,
    fetch_type: str,
    categories: tuple[str, ...] | None = None,
    max_catchup_days: int = MAX_CATCHUP_DAYS,
) -> tuple[str, str, bool]:
    """수집 날짜 창을 결정합니다.

    start_date 가 명시되면 그대로 사용합니다 (수동 백필 경로).
    명시되지 않으면 DB 최신 날짜를 체크포인트로 삼아 공백을 계산합니다.

    체크포인트 선택 규칙:
    - 요청 카테고리만 대상으로 MIN(MAX(date) per category) 를 계산합니다.
    - 공고/결과 두 타입 중 더 오래된 쪽을 전체 체크포인트로 사용합니다.
    - 요청 카테고리 중 DB 에 행이 없는 카테고리가 하나라도 있으면 영구 누락을
      막기 위해 max_catchup_days 창으로 처리합니다.
    - 공백이 max_catchup_days 를 초과하면 최근 max_catchup_days 일만 회수합니다.

    Returns:
        (resolved_start, resolved_end, is_catchup)
    """
    yesterday: date = (utcnow() - timedelta(days=1)).date()
    yesterday_str = yesterday.strftime("%Y%m%d")

    if start_date is not None:
        return start_date, end_date or yesterday_str, False

    # 요청 카테고리 전부에 데이터가 있는지 먼저 확인합니다.
    # 한 카테고리라도 없으면 영구 누락이 발생하므로 max_catchup_days 창을 씁니다.
    if categories:
        for cat in categories:
            if fetch_type in ("both", "announce"):
                has_ann = db.scalar(
                    select(func.count(BidAnnouncement.id)).where(BidAnnouncement.category == cat)
                )
                if not has_ann:
                    gap_start = yesterday - timedelta(days=max_catchup_days - 1)
                    logger.warning(
                        "카테고리 '%s' 공고 데이터 없음: max_catchup_days(%d일) 창으로 시작합니다.",
                        cat,
                        max_catchup_days,
                    )
                    return gap_start.strftime("%Y%m%d"), yesterday_str, True
            if fetch_type in ("both", "result"):
                has_res = db.scalar(
                    select(func.count(BidResult.id)).where(BidResult.category == cat)
                )
                if not has_res:
                    gap_start = yesterday - timedelta(days=max_catchup_days - 1)
                    logger.warning(
                        "카테고리 '%s' 결과 데이터 없음: max_catchup_days(%d일) 창으로 시작합니다.",
                        cat,
                        max_catchup_days,
                    )
                    return gap_start.strftime("%Y%m%d"), yesterday_str, True

    # 요청 카테고리별 최신일 중 가장 오래된 것(MIN of MAX per category) 을 계산합니다.
    # d < latest 로 비교해 최솟값(가장 오래된 날짜)을 유지합니다.
    # 전역 MAX 는 느린 카테고리의 공백을 건너뜁니다.
    # 공고/결과 두 타입 중에서도 더 오래된 쪽이 전체 체크포인트가 됩니다.
    latest: date | None = None

    if fetch_type in ("both", "announce"):
        ann_q = select(func.max(BidAnnouncement.bid_ntce_dt).label("max_dt"))
        if categories:
            ann_q = ann_q.where(BidAnnouncement.category.in_(categories))
        per_cat = ann_q.group_by(BidAnnouncement.category).subquery()
        row = db.scalar(select(func.min(per_cat.c.max_dt)))
        if row is not None:
            d = row.date() if hasattr(row, "date") else row
            if latest is None or d < latest:
                latest = d

    if fetch_type in ("both", "result"):
        res_q = select(func.max(BidResult.rl_openg_dt).label("max_dt"))
        if categories:
            res_q = res_q.where(BidResult.category.in_(categories))
        per_cat = res_q.group_by(BidResult.category).subquery()
        row = db.scalar(select(func.min(per_cat.c.max_dt)))
        if row is not None:
            d = row.date() if hasattr(row, "date") else row
            if latest is None or d < latest:
                latest = d

    if latest is None:
        gap_start = yesterday - timedelta(days=max_catchup_days - 1)
        return gap_start.strftime("%Y%m%d"), yesterday_str, True

    gap_start = latest + timedelta(days=1)

    if gap_start > yesterday:
        return yesterday_str, yesterday_str, False

    days_missing = (yesterday - latest).days
    earliest_recoverable = yesterday - timedelta(days=max_catchup_days - 1)
    if gap_start < earliest_recoverable:
        logger.warning(
            "수집 공백 %d일이 자동 회수 상한(%d일)을 초과합니다. "
            "%s부터 회수합니다. 이전 구간(%s~%s)은 backfill_from_g2b.py 로 채우십시오.",
            days_missing,
            max_catchup_days,
            earliest_recoverable.strftime("%Y%m%d"),
            gap_start.strftime("%Y%m%d"),
            (earliest_recoverable - timedelta(days=1)).strftime("%Y%m%d"),
        )
        gap_start = earliest_recoverable

    return gap_start.strftime("%Y%m%d"), yesterday_str, True


def _ignore_prefix(db: Session) -> str:
    return "OR IGNORE" if db.get_bind().dialect.name == "sqlite" else "IGNORE"


def _bulk_insert(db: Session, model, rows: list[dict[str, Any]]) -> int:
    """유니크 제약 위반은 무시하고 적재합니다 (원본 bulk_create ignore_conflicts 대응)."""
    if not rows:
        return 0
    stmt = insert(model.__table__).prefix_with(_ignore_prefix(db))
    inserted = 0
    try:
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
    except Exception:
        try:
            db.rollback()
        except Exception as rb_exc:
            logger.debug("대량 삽입 실패 후 롤백 실패: %s", rb_exc)
        raise


def _record_partial_failure(
    metrics: dict[str, Any],
    cat_code: str,
    kind: str,
    exc: RangeCollectionError,
) -> None:
    """부분 실패를 적재 건수와 재수집 대상 구간으로 함께 기록합니다.

    체크포인트는 MAX(date) 라 실패 구간을 자동으로 되돌아보지 않습니다.
    failed_ranges 는 운영자가 그 구간만 수동 백필하기 위한 근거입니다.
    """
    count_key = "announcement_count" if kind == "announcement" else "result_count"
    metrics[count_key] += exc.saved
    metrics["categories"][cat_code][count_key] += exc.saved
    metrics["categories"][cat_code][f"{kind}_error"] = mask_credentials(exc)
    metrics["failed_ranges"].extend(
        {"category": cat_code, "kind": kind, "start_date": s, "end_date": e}
        for s, e in exc.failed_ranges
    )


async def collect_bids(
    db: Session,
    *,
    start_date: str | None = None,
    end_date: str | None = None,
    fetch_type: str = "both",
    categories: tuple[str, ...] | None = None,
    refresh_aggregates: bool = True,
    max_catchup_days: int = MAX_CATCHUP_DAYS,
) -> dict[str, Any]:
    """조달청 입찰공고/낙찰 데이터를 수집해 적재합니다.

    날짜 미지정 시 DB 체크포인트에서 공백을 계산해 최대 max_catchup_days 일을
    자동 회수합니다. INSERT IGNORE 기반이므로 동일 범위 재실행은 멱등입니다.
    """
    if not get_service_key():
        return {
            "status": "error",
            "message": "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다.",
            "announcement_count": 0,
            "result_count": 0,
            "total_records": 0,
            "attempted": 0,
            "failed_count": 0,
            "failed_ranges": [],
        }

    target_categories = categories or tuple(BID_CATEGORIES.keys())
    # 체크포인트 조회는 동기 DB 질의입니다. 이 함수는 ASGI 요청 경로에서도
    # 호출되므로 스레드로 넘겨 이벤트 루프를 비웁니다.
    resolved_start, resolved_end, is_catchup = await asyncio.to_thread(
        resolve_collection_window,
        db,
        start_date=start_date,
        end_date=end_date,
        fetch_type=fetch_type,
        categories=target_categories,
        max_catchup_days=max_catchup_days,
    )
    if is_catchup:
        logger.info("누락일 회수 모드: %s ~ %s", resolved_start, resolved_end)

    metrics: dict[str, Any] = {
        "start_date": resolved_start,
        "end_date": resolved_end,
        "fetch_type": fetch_type,
        "catchup": is_catchup,
        "announcement_count": 0,
        "result_count": 0,
        "attempted": 0,
        "failed_count": 0,
        "failed_ranges": [],
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
                    resolved_start,
                    resolved_end,
                    lambda rows: _bulk_insert(db, BidAnnouncement, rows),
                    category=cat_code,
                )
                metrics["announcement_count"] += saved
                metrics["categories"][cat_code]["announcement_count"] += saved
                logger.info("[%s] 입찰공고 %s건 적재", cat_name, saved)
            except RangeCollectionError as exc:
                # 성공 구간은 이미 적재되었으므로 건수는 반영하되 실패로 표시합니다.
                # 이것을 성공으로 두면 체크포인트가 실패 구간을 건너뛴 채 전진합니다.
                logger.error("[%s] 입찰공고 부분 실패: %s", cat_name, mask_credentials(exc))
                _record_partial_failure(metrics, cat_code, "announcement", exc)
            except Exception as exc:
                logger.exception("[%s] 입찰공고 수집 실패", cat_name)
                try:
                    db.rollback()
                except Exception as rb_exc:
                    logger.debug("입찰공고 롤백 실패: %s", rb_exc)
                metrics["categories"][cat_code]["announcement_error"] = mask_credentials(exc)

        if fetch_type in ("both", "result"):
            metrics["attempted"] += 1
            try:
                saved = await stream_bid_data(
                    resolved_start,
                    resolved_end,
                    lambda rows: _bulk_insert(db, BidResult, rows),
                    category=cat_code,
                )
                metrics["result_count"] += saved
                metrics["categories"][cat_code]["result_count"] += saved
                logger.info("[%s] 낙찰정보 %s건 적재", cat_name, saved)
            except RangeCollectionError as exc:
                logger.error("[%s] 낙찰정보 부분 실패: %s", cat_name, mask_credentials(exc))
                _record_partial_failure(metrics, cat_code, "result", exc)
            except Exception as exc:
                logger.exception("[%s] 낙찰정보 수집 실패", cat_name)
                try:
                    db.rollback()
                except Exception as rb_exc:
                    logger.debug("낙찰정보 롤백 실패: %s", rb_exc)
                metrics["categories"][cat_code]["result_error"] = mask_credentials(exc)

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
            # 300만 행 집계와 캐시 예열은 수 초에서 수십 초가 걸립니다.
            # 같은 Session 을 쓰므로 순차로, 그러나 스레드에서 수행합니다.
            await asyncio.to_thread(rebuild_bid_dataset_summaries, db, datasets)
            await asyncio.to_thread(warm_dashboard_stats_cache, db)
            await asyncio.to_thread(warm_home_page_cache, db)
            metrics["cache_warmed"] = True
        except Exception as exc:
            logger.warning("대시보드 집계 또는 캐시 예열 실패: %s", mask_credentials(exc))
            try:
                db.rollback()
            except Exception as rb_exc:
                logger.debug("대시보드 예열 롤백 실패: %s", rb_exc)
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
