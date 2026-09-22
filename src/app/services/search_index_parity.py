"""Meilisearch 읽기 모델과 MySQL 원본의 공고·낙찰 건수 대조 점검 (단일 원천).

야간 스케줄에서 Meilisearch bid_records 인덱스가 담은 공고·낙찰 문서 건수와
MySQL 원본의 기대 건수를 읽기 전용으로 대조한다.

읽기 전용 보장:
- 색인 동기화, 인덱스 설정 변경, 문서 upsert, 하류 재구축 오케스트레이션 등 어떤
  쓰기도 실행하지 않는다.
- 오직 COUNT 집계 질의와 검색 총 건수 조회만 수행한다.
- 불일치 감지만 자동화하고 재구축은 운영자/사람의 승인에 맡긴다.
"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.models.bids import BidAnnouncement, BidResult
from src.app.services.search_index import MeiliSearchClient, SearchBackendUnavailable

logger = logging.getLogger(__name__)

STATUS_OK = "ok"
STATUS_MISMATCH = "mismatch"
STATUS_SKIPPED = "skipped"
STATUS_UNAVAILABLE = "unavailable"

DATASET_ANNOUNCEMENT = "announcement"
DATASET_RESULT = "result"


def _empty_counts() -> dict[str, int | None]:
    """조회하지 않은 상태를 나타내는 빈 건수 자리입니다."""
    return {"db": None, "meili": None, "diff": None}


def build_parity_entry(db_count: int, meili_count: int) -> dict[str, int]:
    """한 데이터셋의 원본·색인 건수와 차이(meili - db)를 만듭니다."""
    return {"db": db_count, "meili": meili_count, "diff": meili_count - db_count}


def count_db_announcements(db: Session) -> int:
    """색인 대상과 같은 정의의 공고 기대 건수를 COUNT 집계로 셉니다.

    공고번호+카테고리 파티션마다 최신 차수 1행만 색인되므로 서로 다른 조합 수를 셉니다.
    행을 파이썬으로 내려받아 세지 않습니다.
    """
    from src.app.services.bid_queries import latest_announcement_filter

    latest = latest_announcement_filter(select(BidAnnouncement.id)).subquery()
    return int(db.scalar(select(func.count()).select_from(latest)) or 0)


def count_db_results(db: Session) -> int:
    """낙찰 기대 건수를 COUNT 집계로 셉니다."""
    return int(db.scalar(select(func.count()).select_from(BidResult)) or 0)


def check_search_index_parity(
    db: Session,
    client: MeiliSearchClient | None = None,
) -> dict[str, Any]:
    """Meilisearch 읽기 모델과 MySQL 원본 건수를 읽기 전용으로 대조합니다.

    반환하는 dict 의 키는 status, announcements, results 입니다.
    announcements 와 results 는 각각 {'db': int, 'meili': int, 'diff': int} 이고
    diff 는 meili - db 입니다. status 는 두 diff 가 모두 0 이면 'ok', 하나라도
    0 이 아니면 'mismatch' 입니다. settings.MEILI_ENABLED 가 거짓이면 조회 없이
    'skipped', Meilisearch 에 연결하지 못하면 'unavailable' 입니다. 조회하지 않은
    상태의 건수 값은 None 입니다.

    어떤 색인 쓰기나 재구축도 실행하지 않습니다.
    """
    if not settings.MEILI_ENABLED:
        logger.info("MEILI_ENABLED 가 꺼져 있어 건수 대조를 건너뜁니다.")
        return {
            "status": STATUS_SKIPPED,
            "announcements": _empty_counts(),
            "results": _empty_counts(),
        }

    search_client = client or MeiliSearchClient()
    try:
        meili_announcements = search_client.count(dataset=DATASET_ANNOUNCEMENT)
        meili_results = search_client.count(dataset=DATASET_RESULT)
    except SearchBackendUnavailable:
        logger.warning("Meilisearch 건수 조회에 실패해 대조할 수 없습니다.")
        return {
            "status": STATUS_UNAVAILABLE,
            "announcements": _empty_counts(),
            "results": _empty_counts(),
        }

    announcements = build_parity_entry(count_db_announcements(db), meili_announcements)
    results = build_parity_entry(count_db_results(db), meili_results)
    status = STATUS_OK if announcements["diff"] == 0 and results["diff"] == 0 else STATUS_MISMATCH
    return {"status": status, "announcements": announcements, "results": results}


__all__ = [
    "DATASET_ANNOUNCEMENT",
    "DATASET_RESULT",
    "STATUS_MISMATCH",
    "STATUS_OK",
    "STATUS_SKIPPED",
    "STATUS_UNAVAILABLE",
    "build_parity_entry",
    "check_search_index_parity",
    "count_db_announcements",
    "count_db_results",
]
