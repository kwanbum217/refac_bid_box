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
import os
from datetime import date, timedelta
from typing import Any

from sqlalchemy import func, insert, select
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.sql.dml import Insert

from src.app.core.db import SessionLocal
from src.app.core.observability import record_collection_metrics
from src.app.core.timeutil import utcnow
from src.app.models.bid_restrictions import (
    BidAnnouncementLicenseLimit,
    BidAnnouncementParticipationRegion,
)
from src.app.models.bids import DATASET_ANNOUNCEMENT, DATASET_RESULT, BidAnnouncement, BidResult
from src.app.models.openg_results import BidOpengResult
from src.app.services.api_collector import (
    BID_CATEGORIES,
    OPENG_RESULT_URLS,
    RangeCollectionError,
    get_service_key,
    mask_credentials,
    stream_bid_announcements,
    stream_bid_data,
    stream_bid_license_limits,
    stream_bid_participation_regions,
    stream_openg_results,
)
from src.app.services.dashboard import rebuild_bid_dataset_summaries, warm_dashboard_stats_cache
from src.app.services.home_context import warm_home_page_cache

logger = logging.getLogger(__name__)

BATCH_ROWS = 2_000

# 체크포인트(MIN of MAX) 계산에서 제외하는 희소 분류.
# 외자(Frgcpt)는 낙찰이 며칠씩 0건인 것이 정상이라 이 분류의 최신일로
# 공백을 판정하면 오탐 경고가 발생합니다.
CHECKPOINT_EXCLUDED_CATEGORIES = ("Frgcpt",)

# 날짜 미지정 시 자동으로 회수하는 최대 일 수.
# API 과부하와 수집 시간 예산을 고려한 상한입니다. 이보다 오래된 공백은
# scripts/backfill_from_g2b.py 로 수동 채우기가 필요합니다.
MAX_CATCHUP_DAYS = 7

# 개찰결과(유찰 상태) 수집 스텝 활성화 플래그. 기본값은 꺼짐입니다.
# 켜면 공고·낙찰 스텝 뒤에 개찰결과를 bid_openg_results 에 upsert 로 적재합니다.
OPENG_RESULT_COLLECTION_ENABLED = os.getenv(
    "OPENG_RESULT_COLLECTION_ENABLED", ""
).strip().lower() in (
    "1",
    "true",
    "yes",
    "on",
)

# 유니크 키 충돌 시 갱신할 컬럼. first_seen_at 은 첫 관측 시각이라 제외합니다.
OPENG_RESULT_UPSERT_UPDATE_COLUMNS = (
    "progrs_div_cd_nm",
    "raw_data",
    "last_seen_at",
    "collected_at",
)


def _checkpoint_categories(
    categories: tuple[str, ...] | None,
) -> tuple[str, ...]:
    """체크포인트 계산에 사용할 분류 목록을 반환합니다.

    categories 가 None 이면 제외 대상을 뺀 전체를, 요청 분류가 전부 제외
    대상이면 그대로 반환하고, 그 외에는 제외 대상을 뺀 요청 분류를
    반환합니다.
    """
    if categories is None:
        return tuple(cat for cat in BID_CATEGORIES if cat not in CHECKPOINT_EXCLUDED_CATEGORIES)
    if set(categories) <= set(CHECKPOINT_EXCLUDED_CATEGORIES):
        return categories
    return tuple(cat for cat in categories if cat not in CHECKPOINT_EXCLUDED_CATEGORIES)


def resolve_collection_window(
    db: Session,
    *,
    start_date: str | None,
    end_date: str | None,
    fetch_type: str,
    categories: tuple[str, ...] | None = None,
    max_catchup_days: int = MAX_CATCHUP_DAYS,
    clamp_events: list[dict[str, Any]] | None = None,
) -> tuple[str, str, bool]:
    """수집 날짜 창을 결정합니다.

    start_date 가 명시되면 그대로 사용합니다 (수동 백필 경로).
    명시되지 않으면 DB 최신 날짜를 체크포인트로 삼아 공백을 계산합니다.

    체크포인트 선택 규칙:
    - 요청 카테고리만 대상으로 MIN(MAX(date) per category) 를 계산합니다.
    - 공고/결과 두 타입 중 더 오래된 쪽을 전체 체크포인트로 사용합니다.
    - 희소 분류(외자 Frgcpt)는 체크포인트 계산에서 제외합니다. 단 요청
      분류가 전부 제외 대상이면 그대로 계산합니다.
    - 요청 카테고리 중 DB 에 행이 없는 카테고리가 하나라도 있으면 영구 누락을
      막기 위해 max_catchup_days 창으로 처리합니다.
    - 공백이 max_catchup_days 를 초과하면 최근 max_catchup_days 일만 회수합니다.

    clamp_events 리스트가 주어지면 클램프 발생 사실을 호출부에 전달합니다.

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
                    select(BidAnnouncement.id).where(BidAnnouncement.category == cat).limit(1)
                )
                if has_ann is None:
                    gap_start = yesterday - timedelta(days=max_catchup_days - 1)
                    logger.warning(
                        "카테고리 '%s' 공고 데이터 없음: max_catchup_days(%d일) 창으로 시작합니다.",
                        cat,
                        max_catchup_days,
                    )
                    return gap_start.strftime("%Y%m%d"), yesterday_str, True
            if fetch_type in ("both", "result"):
                has_res = db.scalar(select(BidResult.id).where(BidResult.category == cat).limit(1))
                if has_res is None:
                    gap_start = yesterday - timedelta(days=max_catchup_days - 1)
                    logger.warning(
                        "카테고리 '%s' 결과 데이터 없음: max_catchup_days(%d일) 창으로 시작합니다.",
                        cat,
                        max_catchup_days,
                    )
                    return gap_start.strftime("%Y%m%d"), yesterday_str, True

    # 체크포인트 계산에는 희소 분류를 제외한 분류 목록을 씁니다.
    # 요청 카테고리별 최신일 중 가장 오래된 것(MIN of MAX per category) 을 계산합니다.
    # d < latest 로 비교해 최솟값(가장 오래된 날짜)을 유지합니다.
    # 전역 MAX 는 느린 카테고리의 공백을 건너뜁니다.
    # 공고/결과 두 타입 중에서도 더 오래된 쪽이 전체 체크포인트가 됩니다.
    ckpt_categories = _checkpoint_categories(categories)
    latest: date | None = None

    if fetch_type in ("both", "announce"):
        ann_q = select(func.max(BidAnnouncement.bid_ntce_dt).label("max_dt"))
        ann_q = ann_q.where(BidAnnouncement.category.in_(ckpt_categories))
        per_cat = ann_q.group_by(BidAnnouncement.category).subquery()
        row = db.scalar(select(func.min(per_cat.c.max_dt)))
        if row is not None:
            d = row.date() if hasattr(row, "date") else row
            if latest is None or d < latest:
                latest = d

    if fetch_type in ("both", "result"):
        res_q = select(func.max(BidResult.rl_openg_dt).label("max_dt"))
        res_q = res_q.where(BidResult.category.in_(ckpt_categories))
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
        if clamp_events is not None:
            clamp_events.append(
                {
                    "days_missing": days_missing,
                    "max_catchup_days": max_catchup_days,
                    "lost_start": gap_start.strftime("%Y%m%d"),
                    "lost_end": (earliest_recoverable - timedelta(days=1)).strftime("%Y%m%d"),
                    "recovered_start": earliest_recoverable.strftime("%Y%m%d"),
                }
            )
        gap_start = earliest_recoverable

    return gap_start.strftime("%Y%m%d"), yesterday_str, True


def _ignore_prefix(db: Session) -> str:
    return "OR IGNORE" if db.get_bind().dialect.name == "sqlite" else "IGNORE"


def _bulk_insert(db: Session, model, rows: list[dict[str, Any]]) -> int:
    """유니크 제약 위반은 무시하고 적재한 뒤 실제 반영 행 수를 돌려줍니다.

    INSERT IGNORE/OR IGNORE 는 중복을 오류 없이 버리므로 시도 건수를 그대로
    세면 재실행·중복 구간에서 적재 건수가 과대 보고됩니다. 이 함수가 돌려주는
    값은 따라서 시도 건수가 아니라 실제 삽입된 행 수이며, announcement_count
    같은 수집 지표도 이 의미로 기록됩니다. 드라이버가 rowcount 를 -1 로 돌리면
    (지원하지 않는 경우) 시도 건수로 대체합니다.
    """
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
            result = db.execute(stmt, chunk)
            rowcount = getattr(result, "rowcount", -1)
            db.commit()
            inserted += rowcount if rowcount is not None and rowcount >= 0 else len(chunk)
        return inserted
    except Exception:
        try:
            db.rollback()
        except Exception as rb_exc:
            logger.debug("대량 삽입 실패 후 롤백 실패: %s", rb_exc)
        raise


def _openg_result_upsert_statement(db: Session) -> Insert:
    """개찰결과 upsert 문을 방언에 맞게 만듭니다.

    기존 테이블의 INSERT IGNORE 는 첫 관측값을 고정하지만, 개찰 상태는 늦게
    확정되므로(유찰 -> 개찰완료) 이 테이블만 충돌 시 상태를 갱신합니다. 첫 관측
    시각인 first_seen_at 은 갱신 대상에서 빼 이력 추적 근거로 남깁니다.
    """
    if db.get_bind().dialect.name in ("mysql", "mariadb"):
        mysql_stmt = mysql_insert(BidOpengResult)
        return mysql_stmt.on_duplicate_key_update(
            **{name: mysql_stmt.inserted[name] for name in OPENG_RESULT_UPSERT_UPDATE_COLUMNS}
        )
    sqlite_stmt = sqlite_insert(BidOpengResult)
    return sqlite_stmt.on_conflict_do_update(
        index_elements=["bid_ntce_no", "bid_ntce_ord", "rbid_no", "category"],
        set_={name: sqlite_stmt.excluded[name] for name in OPENG_RESULT_UPSERT_UPDATE_COLUMNS},
    )


def _upsert_openg_results(db: Session, rows: list[dict[str, Any]]) -> int:
    """개찰결과를 유니크 키 기준 upsert 로 적재합니다.

    같은 창을 다시 수집해도 행이 늘지 않고, 상태·원문·마지막 관측 시각만
    갱신됩니다.
    """
    if not rows:
        return 0
    stmt = _openg_result_upsert_statement(db)
    now = utcnow()
    saved = 0
    try:
        for start in range(0, len(rows), BATCH_ROWS):
            chunk = [row for row in rows[start : start + BATCH_ROWS] if row.get("bid_ntce_no")]
            if not chunk:
                continue
            for row in chunk:
                row.setdefault("first_seen_at", now)
                row["last_seen_at"] = now
                row["collected_at"] = now
            db.execute(stmt, chunk)
            db.commit()
            saved += len(chunk)
        return saved
    except Exception:
        try:
            db.rollback()
        except Exception as rb_exc:
            logger.debug("개찰결과 upsert 실패 후 롤백 실패: %s", rb_exc)
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
    count_key = f"{kind}_count"
    metrics[count_key] += exc.saved
    metrics["categories"][cat_code][count_key] += exc.saved
    metrics["categories"][cat_code][f"{kind}_error"] = mask_credentials(exc)
    metrics["failed_ranges"].extend(
        {"category": cat_code, "kind": kind, "start_date": s, "end_date": e}
        for s, e in exc.failed_ranges
    )


def _warm_aggregates_and_caches_sync(datasets: list[str], bind=None) -> None:
    """대시보드 집계와 캐시 예열을 스레드 전용 세션에서 수행합니다."""
    session_factory = (
        sessionmaker(bind=bind, autocommit=False, autoflush=False)
        if bind is not None
        else SessionLocal
    )
    db = session_factory()
    try:
        try:
            from src.rag.structured_data import refresh_institution_name_catalogs

            refresh_institution_name_catalogs(db)
        except Exception as exc:
            logger.warning("RAG 기관명 카탈로그 갱신 실패: %s", mask_credentials(exc))
        rebuild_bid_dataset_summaries(db, datasets)
        try:
            from src.app.services.compare_stats_snapshots import (
                rebuild_compare_stats_snapshots,
            )

            rebuild_compare_stats_snapshots(db)
        except Exception as exc:
            logger.warning("비교 통계 스냅샷 재집계 실패: %s", mask_credentials(exc))
        warm_dashboard_stats_cache(db)
        warm_home_page_cache(db)
    finally:
        db.close()


def _resolve_collection_window_thread(
    *,
    bind=None,
    start_date: str | None,
    end_date: str | None,
    fetch_type: str,
    categories: tuple[str, ...] | None = None,
    max_catchup_days: int = MAX_CATCHUP_DAYS,
    clamp_events: list[dict[str, Any]] | None = None,
) -> tuple[str, str, bool]:
    """체크포인트 조회를 스레드 전용 세션에서 수행합니다."""
    session_factory = (
        sessionmaker(bind=bind, autocommit=False, autoflush=False)
        if bind is not None
        else SessionLocal
    )
    db = session_factory()
    try:
        return resolve_collection_window(
            db,
            start_date=start_date,
            end_date=end_date,
            fetch_type=fetch_type,
            categories=categories,
            max_catchup_days=max_catchup_days,
            clamp_events=clamp_events,
        )
    finally:
        db.close()


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
            "openg_result_count": 0,
            "total_records": 0,
            "attempted": 0,
            "failed_count": 0,
            "failed_ranges": [],
        }

    target_categories = categories or tuple(BID_CATEGORIES.keys())
    engine = db.get_bind()
    clamp_events: list[dict[str, Any]] = []
    resolved_start, resolved_end, is_catchup = await asyncio.to_thread(
        _resolve_collection_window_thread,
        bind=engine,
        start_date=start_date,
        end_date=end_date,
        fetch_type=fetch_type,
        categories=target_categories,
        max_catchup_days=max_catchup_days,
        clamp_events=clamp_events,
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
        "openg_result_count": 0,
        "license_limit_count": 0,
        "participation_region_count": 0,
        "attempted": 0,
        "failed_count": 0,
        "failed_ranges": [],
        "categories": {},
    }

    if clamp_events:
        event = clamp_events[0]
        metrics["window_clamp"] = event
        try:
            from src.tasks import notifier

            await notifier.notify_collection_window_clamped(event)
        except Exception as exc:
            logger.warning("수집 창 클램프 알림 발신 실패: %s", exc)

    for cat_code in target_categories:
        cat_info = BID_CATEGORIES.get(cat_code)
        if cat_info is None:
            continue
        cat_name = cat_info["name"]
        metrics["categories"].setdefault(
            cat_code, {"announcement_count": 0, "result_count": 0, "openg_result_count": 0}
        )

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

        # 개찰결과는 유찰 상태의 원천이라 낙찰정보 스텝 바로 뒤에 적재합니다.
        # 외자(Frgcpt)는 개찰결과 오퍼레이션이 없어 건너뜁니다.
        if (
            OPENG_RESULT_COLLECTION_ENABLED
            and fetch_type in ("both", "result")
            and cat_code in OPENG_RESULT_URLS
        ):
            metrics["attempted"] += 1
            try:
                saved = await stream_openg_results(
                    resolved_start,
                    resolved_end,
                    lambda rows: _upsert_openg_results(db, rows),
                    category=cat_code,
                )
                metrics["openg_result_count"] += saved
                metrics["categories"][cat_code]["openg_result_count"] += saved
                logger.info("[%s] 개찰결과 %s건 적재", cat_name, saved)
            except RangeCollectionError as exc:
                logger.error("[%s] 개찰결과 부분 실패: %s", cat_name, mask_credentials(exc))
                _record_partial_failure(metrics, cat_code, "openg_result", exc)
            except Exception as exc:
                logger.exception("[%s] 개찰결과 수집 실패", cat_name)
                try:
                    db.rollback()
                except Exception as rb_exc:
                    logger.debug("개찰결과 롤백 실패: %s", rb_exc)
                metrics["categories"][cat_code]["openg_result_error"] = mask_credentials(exc)

    if fetch_type in ("both", "announce"):
        metrics["attempted"] += 1
        try:
            saved = await stream_bid_license_limits(
                resolved_start,
                resolved_end,
                lambda rows: _bulk_insert(db, BidAnnouncementLicenseLimit, rows),
            )
            metrics["license_limit_count"] += saved
            logger.info("면허제한정보 %s건 적재", saved)
        except RangeCollectionError as exc:
            logger.error("면허제한정보 부분 실패: %s", mask_credentials(exc))
            metrics["license_limit_count"] += exc.saved
            metrics["failed_ranges"].extend(
                {"category": None, "kind": "license_limit", "start_date": start, "end_date": end}
                for start, end in exc.failed_ranges
            )
            metrics.setdefault("restrictions", {})["license_limit_error"] = mask_credentials(exc)
        except Exception as exc:
            logger.exception("면허제한정보 수집 실패")
            try:
                db.rollback()
            except Exception as rb_exc:
                logger.debug("면허제한정보 롤백 실패: %s", rb_exc)
            metrics.setdefault("restrictions", {})["license_limit_error"] = mask_credentials(exc)

        metrics["attempted"] += 1
        try:
            saved = await stream_bid_participation_regions(
                resolved_start,
                resolved_end,
                lambda rows: _bulk_insert(db, BidAnnouncementParticipationRegion, rows),
            )
            metrics["participation_region_count"] += saved
            logger.info("참가가능지역 %s건 적재", saved)
        except RangeCollectionError as exc:
            logger.error("참가가능지역 부분 실패: %s", mask_credentials(exc))
            metrics["participation_region_count"] += exc.saved
            metrics["failed_ranges"].extend(
                {
                    "category": None,
                    "kind": "participation_region",
                    "start_date": start,
                    "end_date": end,
                }
                for start, end in exc.failed_ranges
            )
            metrics.setdefault("restrictions", {})["participation_region_error"] = mask_credentials(
                exc
            )
        except Exception as exc:
            logger.exception("참가가능지역 수집 실패")
            try:
                db.rollback()
            except Exception as rb_exc:
                logger.debug("참가가능지역 롤백 실패: %s", rb_exc)
            metrics.setdefault("restrictions", {})["participation_region_error"] = mask_credentials(
                exc
            )

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
            # 스레드 전용 세션에서 순차 수행합니다.
            await asyncio.to_thread(_warm_aggregates_and_caches_sync, datasets, bind=engine)
            metrics["cache_warmed"] = True
        except Exception as exc:
            logger.warning("대시보드 집계 또는 캐시 예열 실패: %s", mask_credentials(exc))
            try:
                db.rollback()
            except Exception as rb_exc:
                logger.debug("대시보드 예열 롤백 실패: %s", rb_exc)
            metrics["cache_warmed"] = False

    restriction_errors = metrics.get("restrictions", {})
    failed_restrictions = sum(
        1
        for err_key in ("license_limit_error", "participation_region_error")
        if err_key in restriction_errors
    )
    metrics["failed_count"] = (
        sum(
            error_key in category_metrics
            for category_metrics in metrics["categories"].values()
            for error_key in ("announcement_error", "result_error", "openg_result_error")
        )
        + failed_restrictions
    )
    if metrics["failed_count"] == 0:
        metrics["status"] = "success"
    elif metrics["failed_count"] == metrics["attempted"]:
        metrics["status"] = "failed"
    else:
        metrics["status"] = "partial_success"
    # 수집 실행이 끝나는 지점에서 한 번만 지표로 옮깁니다. metrics 딕셔너리는
    # 그대로 반환하므로 기존 수집 동작과 반환값은 바뀌지 않습니다.
    record_collection_metrics(metrics)

    # 실패 구간은 체크포인트가 MAX(date) 라 다음 실행이 다시 보지 않습니다.
    # 로그·반환값만으로는 사람이 모르므로 여기서 한 번 알립니다. 알림 실패가
    # 수집 결과나 체크포인트를 바꾸지 않도록 예외는 삼킵니다.
    if metrics["failed_ranges"]:
        try:
            from src.tasks import notifier

            await notifier.notify_collection_partial_failure(metrics["failed_ranges"])
        except Exception as exc:
            logger.warning("수집 부분 실패 알림 발신 실패: %s", mask_credentials(exc))
    return metrics
