"""
src/app/services/kb_document_builder.py

지식베이스 문서 생성 및 공고/낙찰 해석 모듈.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from typing import TypeVar, overload

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from src.app.models.bids import (
    CATEGORY_LABELS,
    BidAnnouncement,
    BidResult,
    extract_business_budget,
    normalize_bid_ntce_ord,
)

DEFAULT_MAX_DOCUMENTS = 500_000

T = TypeVar("T")


class PagedQuerySequence(Sequence[T]):
    """지식베이스 구축을 위한 페이지 단위 지연 조회 시퀀스.

    수십만 건의 레코드를 메모리에 한 번에 올리지 않고, 슬라이스나 순회 시점에
    페이지 단위(chunk_size)로만 데이터베이스에서 조회하여 반환합니다.
    _sync_stream 의 2단계 순회(Pass 1: removed_ids 소거, Pass 2: 임베딩 및 upsert)를
    모두 지원하며, 각 단계에서 한 번에 1개 페이지만 메모리에 상주하도록 보장하여
    O(N) 메모리 폭주를 근본적으로 차단합니다.
    """

    def __init__(self, total_count: int, fetch_page: Callable[[int, int], list[T]]) -> None:
        self._total_count = max(0, total_count)
        self._fetch_page = fetch_page

    def __len__(self) -> int:
        return self._total_count

    def __bool__(self) -> bool:
        return self._total_count > 0

    @overload
    def __getitem__(self, index: int) -> T: ...

    @overload
    def __getitem__(self, index: slice) -> list[T]: ...

    def __getitem__(self, index: int | slice) -> T | list[T]:
        if isinstance(index, slice):
            start, stop, step = index.indices(self._total_count)
            if step != 1:
                raise NotImplementedError("PagedQuerySequence only supports step=1 slices")
            if start >= stop:
                return []
            return self._fetch_page(start, stop - start)
        else:
            if index < 0:
                index += self._total_count
            if index < 0 or index >= self._total_count:
                raise IndexError("list index out of range")
            items = self._fetch_page(index, 1)
            if not items:
                raise IndexError("list index out of range")
            return items[0]

    def __iter__(self) -> Iterator[T]:
        page_size = 1_000
        for offset in range(0, self._total_count, page_size):
            yield from self._fetch_page(offset, min(page_size, self._total_count - offset))


def _max_documents() -> int:
    raw = os.getenv("KB_MAX_DOCUMENTS", "").strip()
    if not raw:
        return DEFAULT_MAX_DOCUMENTS
    try:
        value = int(raw)
    except ValueError:
        return DEFAULT_MAX_DOCUMENTS
    return value if value > 0 else DEFAULT_MAX_DOCUMENTS


def _resolve_announcements(
    db: Session, one_year_ago: datetime
) -> tuple[Sequence[BidAnnouncement], str]:
    """공고일 기준 → 수집일 기준 순으로 폴백합니다 (원본 _resolve_announcement_queryset).

    .scalars().all() 로 전량을 한 번에 로드하지 않고, 건수 확인 후
    PagedQuerySequence 를 반환하여 chunk_size 단위로 지연 조회합니다.
    """
    limit = _max_documents()

    notice_query = (
        select(BidAnnouncement)
        .where(BidAnnouncement.bid_ntce_dt >= one_year_ago)
        .order_by(BidAnnouncement.bid_ntce_dt.desc(), BidAnnouncement.id.desc())
    )
    notice_count = (
        db.scalar(
            select(func.count(BidAnnouncement.id)).where(
                BidAnnouncement.bid_ntce_dt >= one_year_ago
            )
        )
        or 0
    )

    if notice_count > 0:
        total = min(notice_count, limit)

        def fetch_notice_page(offset: int, page_limit: int) -> list[BidAnnouncement]:
            return list(db.execute(notice_query.offset(offset).limit(page_limit)).scalars().all())

        return PagedQuerySequence(total, fetch_notice_page), "announcements_by_notice_date"

    collected_query = (
        select(BidAnnouncement)
        .where(BidAnnouncement.collected_at >= one_year_ago)
        .order_by(BidAnnouncement.collected_at.desc(), BidAnnouncement.id.desc())
    )
    collected_count = (
        db.scalar(
            select(func.count(BidAnnouncement.id)).where(
                BidAnnouncement.collected_at >= one_year_ago
            )
        )
        or 0
    )

    if collected_count > 0:
        total = min(collected_count, limit)

        def fetch_collected_page(offset: int, page_limit: int) -> list[BidAnnouncement]:
            return list(
                db.execute(collected_query.offset(offset).limit(page_limit)).scalars().all()
            )

        return PagedQuerySequence(total, fetch_collected_page), "announcements_by_collected_at"

    return [], "announcements_unavailable"


def _resolve_delta_announcements(
    db: Session, collected_since: datetime
) -> tuple[Sequence[BidAnnouncement], str]:
    """이번 수집분과 새 낙찰 결과가 참조하는 공고만 KB에 반영합니다.

    전량 리스트를 만들지 않고 PagedQuerySequence 를 반환하여 페이지 단위로 읽습니다.
    """
    result_notice_numbers = list(
        db.scalars(
            select(BidResult.bid_ntce_no)
            .where(BidResult.collected_at >= collected_since)
            .distinct()
        ).all()
    )
    if result_notice_numbers:
        delta_filter = or_(
            BidAnnouncement.collected_at >= collected_since,
            BidAnnouncement.bid_ntce_no.in_(result_notice_numbers),
        )
    else:
        delta_filter = BidAnnouncement.collected_at >= collected_since

    delta_count = db.scalar(select(func.count(BidAnnouncement.id)).where(delta_filter)) or 0
    if delta_count == 0:
        return [], "announcements_by_collected_delta"

    delta_query = (
        select(BidAnnouncement)
        .where(delta_filter)
        .order_by(BidAnnouncement.collected_at.desc(), BidAnnouncement.id.desc())
    )

    def fetch_delta_page(offset: int, page_limit: int) -> list[BidAnnouncement]:
        return list(db.execute(delta_query.offset(offset).limit(page_limit)).scalars().all())

    return PagedQuerySequence(delta_count, fetch_delta_page), "announcements_by_collected_delta"


def _join_key(row: BidAnnouncement | BidResult) -> str:
    """공고와 낙찰을 잇는 키. 차수 자리수를 맞추지 않으면 거의 이어지지 않습니다."""
    return f"{row.bid_ntce_no}-{normalize_bid_ntce_ord(row.bid_ntce_ord)}-{row.category}"


def _build_announcement_document(ann: BidAnnouncement, result: BidResult | None) -> str:
    resolved_base_amount = extract_business_budget(ann.raw_data)
    if resolved_base_amount is None and ann.raw_data is None:
        resolved_base_amount = ann.base_amount

    content = f"[공고명] {ann.bid_ntce_nm}\n"
    content += f"[공고번호] {ann.bid_ntce_no}-{ann.bid_ntce_ord}\n"
    content += f"[수요기관] {ann.dminstt_nm}\n"
    if resolved_base_amount is not None:
        content += f"[기초금액] {resolved_base_amount}원\n"
    if ann.presmpt_prce is not None:
        content += f"[추정가격] {ann.presmpt_prce}원\n"
    content += f"[분류] {CATEGORY_LABELS.get(ann.category, ann.category)}\n"
    content += f"[공고일시] {ann.bid_ntce_dt}\n"

    if result is not None:
        content += f"[낙찰업체] {result.bidwinnr_nm}\n"
        content += f"[낙찰금액] {result.sucsf_bid_amt}원\n"
        content += f"[낙찰률] {result.sucsf_bid_rate}%\n"
        content += f"[개찰일시] {result.rl_openg_dt}\n"
    else:
        content += "[낙찰상태] 진행 중 또는 결과 미수집\n"
    return content


def _build_result_document(result: BidResult) -> str:
    content = f"[낙찰공고번호] {result.bid_ntce_no}-{result.bid_ntce_ord}\n"
    content += f"[수요기관] {result.dminstt_nm}\n"
    content += f"[분류] {CATEGORY_LABELS.get(result.category, result.category)}\n"
    content += f"[낙찰업체] {result.bidwinnr_nm}\n"
    content += f"[낙찰금액] {result.sucsf_bid_amt}원\n"
    content += f"[낙찰률] {result.sucsf_bid_rate}%\n"
    content += f"[개찰일시] {result.rl_openg_dt}\n"
    return content
