"""Meilisearch 검색 읽기 모델.

원본 MySQL의 공고·낙찰 테이블은 변경하지 않습니다. 활성화 시 검색어 유무와 관계없이
목록 요청을 처리하고, 장애는 API의 HTTP 503 계약으로 전파할 수 있게 호출자에게 알립니다.
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.app.core.config import settings
from src.app.models.bids import BidAnnouncement, BidResult

logger = logging.getLogger(__name__)

INDEX_UID = "bid_records"
SYNC_BATCH_SIZE = 1_000
INDEX_MAX_TOTAL_HITS = 10_000_000


class SearchBackendUnavailable(RuntimeError):
    """검색 인덱스를 사용할 수 없을 때 API 경계까지 전달하는 오류입니다."""


@dataclass(frozen=True)
class SearchPage:
    ids: list[int]
    has_next: bool


def _region_codes(*values: str | None) -> list[str]:
    from src.app.services.bid_queries import BID_REGION_CHOICES

    text = " ".join(value or "" for value in values)
    return [
        item["code"]
        for item in BID_REGION_CHOICES
        if any(alias in text for alias in item["aliases"])
    ]


def _region_rank(codes: list[str]) -> int:
    from src.app.services.bid_queries import BID_REGION_CHOICES

    return min(
        (index + 1 for index, item in enumerate(BID_REGION_CHOICES) if item["code"] in codes),
        default=999,
    )


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def announcement_document(row: BidAnnouncement) -> dict[str, Any]:
    region_codes = _region_codes(row.dminstt_nm, row.ntce_instt_nm)
    return {
        # 차수가 새로 수집돼도 기존 문서를 교체해야 하므로 DB PK가 아니라 공고의
        # 업무구분+번호를 읽기 모델의 안정 ID로 씁니다.
        "id": f"announcement_{row.category}_{row.bid_ntce_no}",
        "source_id": row.id,
        "dataset": "announcement",
        "bid_ntce_no": row.bid_ntce_no,
        "bid_ntce_nm": row.bid_ntce_nm or "",
        "dminstt_nm": row.dminstt_nm or "",
        "ntce_instt_nm": row.ntce_instt_nm or "",
        "category": row.category,
        "region_codes": region_codes,
        "region_rank": _region_rank(region_codes),
        "bid_ntce_dt": _iso(row.bid_ntce_dt),
        "bid_clse_dt": _iso(row.bid_clse_dt),
        "base_amount": row.resolved_base_amount,
        "collected_at": _iso(row.collected_at),
    }


def result_document(row: BidResult) -> dict[str, Any]:
    region_codes = _region_codes(row.dminstt_nm)
    return {
        "id": f"result_{row.id}",
        "source_id": row.id,
        "dataset": "result",
        "bid_ntce_no": row.bid_ntce_no,
        "bid_ntce_nm": row.bid_ntce_nm or "",
        "dminstt_nm": row.dminstt_nm or "",
        "bidwinnr_nm": row.bidwinnr_nm or "",
        "category": row.category,
        "region_codes": region_codes,
        "region_rank": _region_rank(region_codes),
        "rl_openg_dt": _iso(row.rl_openg_dt),
        "sucsf_bid_amt": row.sucsf_bid_amt,
        "sucsf_bid_rate": float(row.sucsf_bid_rate) if row.sucsf_bid_rate is not None else None,
        "collected_at": _iso(row.collected_at),
    }


class MeiliSearchClient:
    def __init__(self, *, base_url: str | None = None, master_key: str | None = None):
        self.base_url = (base_url or settings.MEILI_URL).rstrip("/")
        self.master_key = settings.MEILI_MASTER_KEY if master_key is None else master_key

    @property
    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self.master_key}"} if self.master_key else {}

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            response = httpx.request(
                method,
                f"{self.base_url}{path}",
                headers=self._headers,
                timeout=settings.MEILI_TIMEOUT_SECONDS,
                **kwargs,
            )
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise SearchBackendUnavailable("Meilisearch에 연결할 수 없습니다.") from exc
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError as exc:
            raise SearchBackendUnavailable("Meilisearch 응답을 해석할 수 없습니다.") from exc

    def configure_index(self) -> None:
        try:
            self._request("POST", "/indexes", json={"uid": INDEX_UID, "primaryKey": "id"})
        except SearchBackendUnavailable:
            # 이미 존재하는 인덱스는 409을 돌려도 이후 설정·upsert는 정상입니다.
            # 연결 실패와 구별하려고 먼저 상태를 확인합니다.
            self._request("GET", f"/indexes/{INDEX_UID}")
        self._request(
            "PATCH",
            f"/indexes/{INDEX_UID}/settings",
            json={
                "searchableAttributes": [
                    "bid_ntce_nm",
                    "bid_ntce_no",
                    "dminstt_nm",
                    "ntce_instt_nm",
                    "bidwinnr_nm",
                ],
                "filterableAttributes": [
                    "dataset",
                    "category",
                    "region_codes",
                    "sucsf_bid_rate",
                ],
                "sortableAttributes": [
                    "bid_ntce_dt",
                    "bid_clse_dt",
                    "base_amount",
                    "rl_openg_dt",
                    "sucsf_bid_amt",
                    "sucsf_bid_rate",
                    "region_rank",
                    "source_id",
                ],
                "pagination": {"maxTotalHits": INDEX_MAX_TOTAL_HITS},
            },
        )

    def upsert(self, documents: list[dict[str, Any]]) -> None:
        if documents:
            self._request("POST", f"/indexes/{INDEX_UID}/documents", json=documents)

    def search(
        self,
        *,
        query: str,
        dataset: str,
        category: str | None,
        region: str | None,
        sort: list[str],
        offset: int,
        limit: int,
    ) -> SearchPage:
        filters = [f"dataset = {json.dumps(dataset, ensure_ascii=False)}"]
        if category:
            filters.append(f"category = {json.dumps(category, ensure_ascii=False)}")
        if region:
            filters.append(f"region_codes = {json.dumps(region, ensure_ascii=False)}")
        if dataset == "result" and any(
            item in {"sucsf_bid_rate:asc", "sucsf_bid_rate:desc"} for item in sort
        ):
            filters.append("sucsf_bid_rate IS NOT NULL")
        payload = self._request(
            "POST",
            f"/indexes/{INDEX_UID}/search",
            json={
                "q": query,
                "filter": " AND ".join(filters),
                "sort": sort,
                "offset": offset,
                "limit": limit,
                "attributesToRetrieve": ["source_id"],
            },
        )
        try:
            ids = [int(hit["source_id"]) for hit in payload.get("hits", [])]
        except (KeyError, TypeError, ValueError) as exc:
            raise SearchBackendUnavailable("Meilisearch 응답에 원본 PK가 없습니다.") from exc
        estimated_total = payload.get("estimatedTotalHits")
        has_next = (
            estimated_total > offset + len(ids)
            if isinstance(estimated_total, int)
            else len(ids) == limit
        )
        return SearchPage(ids=ids, has_next=has_next)


def _latest_announcements(db: Session, collected_since: datetime | None):
    from src.app.services.bid_queries import latest_announcement_filter

    stmt = latest_announcement_filter(select(BidAnnouncement))
    if collected_since:
        stmt = stmt.where(BidAnnouncement.collected_at >= collected_since)
    return (
        db.execute(stmt.execution_options(stream_results=True)).scalars().yield_per(SYNC_BATCH_SIZE)
    )


def _rows_to_batches(rows: Iterable[Any], mapper):
    batch: list[dict[str, Any]] = []
    for row in rows:
        batch.append(mapper(row))
        if len(batch) == SYNC_BATCH_SIZE:
            yield batch
            batch = []
    if batch:
        yield batch


def sync_search_index(db: Session, *, collected_since: datetime | None = None) -> dict[str, int]:
    """초기 전체 또는 최근 수집분을 Meilisearch 읽기 모델로 upsert 합니다."""
    client = MeiliSearchClient()
    client.configure_index()
    counts = {"announcements": 0, "results": 0}
    for batch in _rows_to_batches(
        _latest_announcements(db, collected_since), announcement_document
    ):
        client.upsert(batch)
        counts["announcements"] += len(batch)

    result_stmt = select(BidResult)
    if collected_since:
        result_stmt = result_stmt.where(BidResult.collected_at >= collected_since)
    results = (
        db.execute(result_stmt.execution_options(stream_results=True))
        .scalars()
        .yield_per(SYNC_BATCH_SIZE)
    )
    for batch in _rows_to_batches(results, result_document):
        client.upsert(batch)
        counts["results"] += len(batch)
    logger.info(
        "Meilisearch 동기화 완료: 공고 %s, 낙찰 %s", counts["announcements"], counts["results"]
    )
    return counts
