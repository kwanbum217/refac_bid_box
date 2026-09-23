"""
src/app/services/home_context.py

홈 화면 컨텍스트 (원본 apps/bids/home_context.py 1:1 이식).
표본 확대(50/200/1000건)와 수집일 윈도우(1/3/7일) 폴백 판정은 그대로 두고,
전역 정렬 접두를 표본 크기 순서로 필요할 때만 늘려 읽어 윈도우별 후보를 메모리에서
거릅니다. 흔한 경우 질의 한 번(50행)으로 끝나고, 데이터가 희소해도 세 번을 넘지 않습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.cache import cache
from src.app.models.bids import (
    CATEGORY_LABELS,
    DATASET_ANNOUNCEMENT,
    DATASET_RESULT,
    BidAnnouncement,
    BidDatasetSummary,
    BidResult,
)
from src.app.services.bid_queries import qualification_analyzable_ids

DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES = ("Cnstwk", "Servc", "Thng", "Frgcpt")
HOME_CONTEXT_CACHE_TTL = 60 * 60 * 24
HOME_RECENT_SAMPLE_SIZES = (50, 200, 1000)
HOME_RECENT_DAY_WINDOWS = (1, 3, 7)


def _marker_value(value: datetime | None) -> str:
    if value is None:
        return "empty"
    return value.isoformat()


def _home_cache_key(
    categories: tuple[str, ...],
    announcement_latest_collected_at: datetime | None,
    result_latest_collected_at: datetime | None,
) -> str:
    category_marker = ",".join(categories)
    return (
        "bids:index:"
        f"{category_marker}:"
        f"{_marker_value(announcement_latest_collected_at)}:"
        f"{_marker_value(result_latest_collected_at)}"
    )


def _latest_collected_at(db: Session, model) -> datetime | None:
    return db.scalar(select(func.max(model.collected_at)))


def _summary_or_none(
    db: Session, dataset: str, latest_collected_at: datetime | None
) -> BidDatasetSummary | None:
    summary = db.get(BidDatasetSummary, dataset)
    if summary is None:
        return None
    if summary.source_latest_collected_at != latest_collected_at:
        return None
    return summary


def _dedupe_announcements(candidates: list[BidAnnouncement], limit: int) -> list[BidAnnouncement]:
    seen: set[tuple[str, str]] = set()
    selected: list[BidAnnouncement] = []

    for announcement in candidates:
        key = (announcement.category, announcement.bid_ntce_no)
        if key in seen:
            continue

        seen.add(key)
        selected.append(announcement)
        if len(selected) >= limit:
            break

    return selected


def _recent_unique_announcements(
    db: Session,
    base_stmt,
    limit: int,
    latest_collected_at: datetime | None,
) -> list[BidAnnouncement]:
    ordered_stmt = base_stmt.order_by(
        BidAnnouncement.collected_at.desc(),
        BidAnnouncement.bid_ntce_dt.desc(),
        BidAnnouncement.id.desc(),
    )
    # 정렬 첫 키가 collected_at 이므로 어떤 윈도우에 걸린 행 집합도 전역 정렬의
    # 접두입니다. 그래서 윈도우 후보는 전역 접두에서 메모리로 걸러 만들면 되고,
    # 접두는 표본 크기 순서로 필요할 때만 늘려 읽습니다. 흔한 경우 첫 표본 50행에서
    # limit 이 차 질의 한 번으로 끝나고, 데이터가 희소해도 세 번을 넘지 않습니다.
    prefix: list[BidAnnouncement] = []
    prefix_exhausted = False

    def ordered_prefix(sample_size: int) -> list[BidAnnouncement]:
        nonlocal prefix, prefix_exhausted

        if not prefix_exhausted and len(prefix) < sample_size:
            prefix = list(db.execute(ordered_stmt.limit(sample_size)).scalars().all())
            if len(prefix) < sample_size:
                prefix_exhausted = True
        return prefix[:sample_size]

    best_effort: list[BidAnnouncement] = []

    def collect_from(window_start: datetime | None) -> list[BidAnnouncement]:
        nonlocal best_effort

        for sample_size in HOME_RECENT_SAMPLE_SIZES:
            sample = [
                row
                for row in ordered_prefix(sample_size)
                if window_start is None or row.collected_at >= window_start
            ]
            if not sample:
                return best_effort

            selected = _dedupe_announcements(sample, limit)
            if len(selected) > len(best_effort):
                best_effort = selected

            if len(selected) >= limit or len(sample) < sample_size:
                return selected

        return best_effort

    if latest_collected_at is not None:
        for day_window in HOME_RECENT_DAY_WINDOWS:
            window_start = latest_collected_at - timedelta(days=day_window)
            selected = collect_from(window_start)
            if len(selected) >= limit:
                return selected[:limit]

    return collect_from(None)[:limit]


def _build_home_payload(
    db: Session,
    categories: tuple[str, ...],
    announcement_latest_collected_at: datetime | None,
    result_latest_collected_at: datetime | None,
) -> dict[str, Any]:
    announcement_summary = _summary_or_none(
        db, DATASET_ANNOUNCEMENT, announcement_latest_collected_at
    )
    result_summary = _summary_or_none(db, DATASET_RESULT, result_latest_collected_at)

    recent_bids = _recent_unique_announcements(
        db,
        select(BidAnnouncement),
        limit=8,
        latest_collected_at=announcement_latest_collected_at,
    )
    recent_bid_sections = {}
    for category_code in categories:
        recent_bid_sections[category_code] = _recent_unique_announcements(
            db,
            select(BidAnnouncement).where(BidAnnouncement.category == category_code),
            limit=6,
            latest_collected_at=announcement_latest_collected_at,
        )

    recent_results = list(
        db.execute(select(BidResult).order_by(BidResult.rl_openg_dt.desc()).limit(6))
        .scalars()
        .all()
    )
    latest_result = db.execute(
        select(BidResult)
        .where(BidResult.sucsf_bid_rate.is_not(None))
        .order_by(BidResult.rl_openg_dt.desc())
        .limit(1)
    ).scalar_one_or_none()

    return {
        "recent_bid_ids": [announcement.id for announcement in recent_bids],
        "recent_bid_section_ids": {
            category_code: [announcement.id for announcement in announcements]
            for category_code, announcements in recent_bid_sections.items()
        },
        "recent_result_ids": [result.id for result in recent_results],
        "announcement_total": (
            announcement_summary.total_count
            if announcement_summary is not None
            else db.scalar(select(func.count(BidAnnouncement.id)))
        ),
        "result_total": (
            result_summary.total_count
            if result_summary is not None
            else db.scalar(select(func.count(BidResult.id)))
        ),
        "latest_result_rate": (
            float(latest_result.sucsf_bid_rate)
            if latest_result is not None and latest_result.sucsf_bid_rate is not None
            else None
        ),
        "latest_collected_at": announcement_latest_collected_at,
    }


def _ordered_in_bulk(db: Session, model, ids: list[int]) -> list[Any]:
    if not ids:
        return []
    rows = db.execute(select(model).where(model.id.in_(ids))).scalars().all()
    by_id = {row.id: row for row in rows}
    return [by_id[item_id] for item_id in ids if item_id in by_id]


def get_home_page_context(
    db: Session, categories: tuple[str, ...] = DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES
) -> dict[str, Any]:
    categories = tuple(categories)
    announcement_latest_collected_at = _latest_collected_at(db, BidAnnouncement)
    result_latest_collected_at = _latest_collected_at(db, BidResult)
    cache_key = _home_cache_key(
        categories, announcement_latest_collected_at, result_latest_collected_at
    )
    payload = cache.get(cache_key)

    if payload is None:
        payload = _build_home_payload(
            db, categories, announcement_latest_collected_at, result_latest_collected_at
        )
        cache.set(cache_key, payload, HOME_CONTEXT_CACHE_TTL)

    announcement_ids = list(payload["recent_bid_ids"])
    for category_code in categories:
        announcement_ids.extend(payload["recent_bid_section_ids"].get(category_code, []))

    announcement_map = {
        row.id: row for row in _ordered_in_bulk(db, BidAnnouncement, announcement_ids)
    }
    recent_results = _ordered_in_bulk(db, BidResult, payload["recent_result_ids"])

    recent_bid_sections = [
        {
            "code": category_code,
            "label": CATEGORY_LABELS.get(category_code, category_code),
            "entries": [
                announcement_map[item_id]
                for item_id in payload["recent_bid_section_ids"].get(category_code, [])
                if item_id in announcement_map
            ],
        }
        for category_code in categories
    ]

    return {
        "recent_bids": [
            announcement_map[item_id]
            for item_id in payload["recent_bid_ids"]
            if item_id in announcement_map
        ],
        "recent_results": recent_results,
        "recent_bid_sections": recent_bid_sections,
        "qualification_ids": qualification_analyzable_ids(announcement_map.values()),
        "announcement_total": payload["announcement_total"],
        "result_total": payload["result_total"],
        "latest_result_rate": payload["latest_result_rate"],
        "latest_collected_at": payload["latest_collected_at"],
    }


def warm_home_page_cache(
    db: Session, categories: tuple[str, ...] = DEFAULT_HOME_ANNOUNCEMENT_CATEGORIES
) -> dict[str, Any]:
    return get_home_page_context(db, categories)
