"""
src/app/services/kb_document_builder.py

지식베이스 문서 생성 및 공고/낙찰 해석 모듈.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from typing import Any, TypeVar, overload

from sqlalchemy import and_, func, or_, select
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
CursorKey = tuple[Any, int]


class PagedQuerySequence(Sequence[T]):
    """지식베이스 구축을 위한 keyset(seek) 기반 페이지 지연 조회 시퀀스.

    [설계 근거: Keyset 페이징과 O(1) 메모리 상주]
    1. Keyset(Seek) 페이징:
       기존 OFFSET 방식은 뒤쪽 페이지로 갈수록 앞선 행들을 스캔하여 버리는 O(N^2) 누적 비용이
       발생합니다. 본 시퀀스는 (dt desc, id desc) 튜플을 커서로 사용하는 keyset 페이징을 적용하여,
       인덱스 seek(O(log N))로 다음 페이지를 즉시 조회합니다.
    2. Session Identity Map 해제:
       조회된 ORM 객체는 조회 직후 세션에서 expunge 되어 세션의 identity_map 에 누적되지 않고,
       청크 단위 처리가 끝나면 Python GC 가 메모리를 즉시 회수합니다.
    3. 스냅샷 일관성 (G1 데이터 무손실):
       Pass 1 첫 페이지 조회 시점의 최신 커서(first_dt, first_id)를 상한 앵커로 고정하여,
       Pass 2 에서도 동일한 상한 조건을 적용합니다. 순회 도중 DB 에 신규 행이 추가되어도
       Pass 1 과 Pass 2 가 정확히 동일한 레코드 집합을 보게 되므로, Pass 2 에서 upsert 된 문서가
       Pass 1 기준 removed_ids 로 잘못 삭제되는 G1 데이터 손실을 원천 차단합니다.
    """

    def __init__(
        self,
        total_count: int,
        fetch_page: Callable[[int, int, CursorKey | None, CursorKey | None, bool], list[T]],
        extract_cursor: Callable[[T], CursorKey] | None = None,
    ) -> None:
        self._total_count = max(0, total_count)
        self._fetch_page = fetch_page
        self._extract_cursor = extract_cursor
        self._current_offset = 0
        self._last_cursor: CursorKey | None = None
        self._snapshot_cursor: CursorKey | None = None

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
            length = stop - start

            # 순차적 순회인지 판별:
            # 1. start == 0: 새로운 패스(Pass 1 또는 Pass 2)의 시작
            if start == 0:
                self._current_offset = 0
                self._last_cursor = None
                items = self._fetch_page(0, length, None, self._snapshot_cursor, False)
                if items and self._extract_cursor is not None:
                    if self._snapshot_cursor is None:
                        # Pass 1 첫 페이지의 첫 번째 항목을 스냅샷 상한 앵커로 고정
                        self._snapshot_cursor = self._extract_cursor(items[0])
                    self._last_cursor = self._extract_cursor(items[-1])
                self._current_offset = len(items)
                return items

            # 2. start == self._current_offset: 이전 페이지에 이은 순차적 keyset seek 순회
            if start == self._current_offset and self._last_cursor is not None:
                items = self._fetch_page(
                    start, length, self._last_cursor, self._snapshot_cursor, False
                )
                if items and self._extract_cursor is not None:
                    self._last_cursor = self._extract_cursor(items[-1])
                self._current_offset += len(items)
                return items

            # 3. 비순차 접근 (테스트/랜덤 액세스 등): fallback offset 모드로 조회
            items = self._fetch_page(start, length, None, self._snapshot_cursor, True)
            self._current_offset = start + len(items)
            if items and self._extract_cursor is not None:
                self._last_cursor = self._extract_cursor(items[-1])
            return items
        else:
            if index < 0:
                index += self._total_count
            if index < 0 or index >= self._total_count:
                raise IndexError("list index out of range")
            items = self._fetch_page(index, 1, None, self._snapshot_cursor, True)
            if not items:
                raise IndexError("list index out of range")
            return items[0]

    def __iter__(self) -> Iterator[T]:
        page_size = 1_000
        for offset in range(0, self._total_count, page_size):
            yield from self[offset : min(offset + page_size, self._total_count)]


def _fetch_keyset_page(
    db: Session,
    base_select: Any,
    col_dt: Any,
    col_id: Any,
    offset: int,
    limit: int,
    cursor: CursorKey | None,
    snapshot_cursor: CursorKey | None,
    use_offset: bool,
    initial_objs: set[Any] | None = None,
) -> list[BidAnnouncement]:
    """Keyset seek 기반으로 페이지를 조회하고 세션에서 expunge 합니다.

    [설계 근거: ORM Session Identity Map 누적 방지 및 호출자 객체 보존]
    SQLAlchemy Session 은 조회된 모든 ORM 객체를 identity map 에 강한 참조로 유지합니다.
    수십만 건을 조회할 때 expunge 하지 않으면 세션이 유지되는 동안 O(N) 객체가 메모리에 누적됩니다.
    각 페이지를 읽은 즉시 이번 조회로 새로 로드된 객체만 db.expunge(obj) 로 분리(detach)하여
    세션에 누적되지 않고 GC 로 즉시 회수되도록 보장합니다.
    조회 시작 전 세션에 이미 존재하던 호출자의 객체(initial_objs)는 detach 하지 않고 온전히 보존합니다.
    """
    stmt = base_select

    # 1. 스냅샷 상한 조건: Pass 1 시작 시점의 최신 행 이하로 제한 (Pass 1/Pass 2 집합 동일성 보장)
    if snapshot_cursor is not None:
        snap_dt, snap_id = snapshot_cursor
        stmt = stmt.where(
            or_(
                col_dt < snap_dt,
                and_(col_dt == snap_dt, col_id <= snap_id),
            )
        )

    # 2. Keyset Seek 조건 또는 Offset 조건
    if not use_offset and cursor is not None:
        last_dt, last_id = cursor
        stmt = stmt.where(
            or_(
                col_dt < last_dt,
                and_(col_dt == last_dt, col_id < last_id),
            )
        )
    elif use_offset and offset > 0:
        stmt = stmt.offset(offset)

    stmt = stmt.limit(limit)

    rows = list(db.execute(stmt).scalars().all())
    for row in rows:
        if hasattr(db, "expunge") and (initial_objs is None or row not in initial_objs):
            db.expunge(row)
    return rows


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
    """공고일 기준 -> 수집일 기준 순으로 폴백합니다.

    .scalars().all() 로 전량을 한 번에 로드하지 않고,
    Keyset seek 페이징과 ORM 객체 expunge 가 적용된 PagedQuerySequence 를 반환합니다.
    """
    limit = _max_documents()
    initial_objs = set(db.identity_map.values()) if hasattr(db, "identity_map") else set()

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
        base_query = (
            select(BidAnnouncement)
            .where(BidAnnouncement.bid_ntce_dt >= one_year_ago)
            .order_by(BidAnnouncement.bid_ntce_dt.desc(), BidAnnouncement.id.desc())
        )

        def fetch_notice_page(
            offset: int,
            page_limit: int,
            cursor: CursorKey | None,
            snapshot_cursor: CursorKey | None,
            use_offset: bool,
        ) -> list[BidAnnouncement]:
            return _fetch_keyset_page(
                db,
                base_query,
                BidAnnouncement.bid_ntce_dt,
                BidAnnouncement.id,
                offset,
                page_limit,
                cursor,
                snapshot_cursor,
                use_offset,
                initial_objs,
            )

        return (
            PagedQuerySequence(
                total,
                fetch_notice_page,
                extract_cursor=lambda ann: (ann.bid_ntce_dt, ann.id),
            ),
            "announcements_by_notice_date",
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
        base_query = (
            select(BidAnnouncement)
            .where(BidAnnouncement.collected_at >= one_year_ago)
            .order_by(BidAnnouncement.collected_at.desc(), BidAnnouncement.id.desc())
        )

        def fetch_collected_page(
            offset: int,
            page_limit: int,
            cursor: CursorKey | None,
            snapshot_cursor: CursorKey | None,
            use_offset: bool,
        ) -> list[BidAnnouncement]:
            return _fetch_keyset_page(
                db,
                base_query,
                BidAnnouncement.collected_at,
                BidAnnouncement.id,
                offset,
                page_limit,
                cursor,
                snapshot_cursor,
                use_offset,
                initial_objs,
            )

        return (
            PagedQuerySequence(
                total,
                fetch_collected_page,
                extract_cursor=lambda ann: (ann.collected_at, ann.id),
            ),
            "announcements_by_collected_at",
        )

    return [], "announcements_unavailable"


def _resolve_delta_announcements(
    db: Session, collected_since: datetime
) -> tuple[Sequence[BidAnnouncement], str]:
    """이번 수집분과 새 낙찰 결과가 참조하는 공고만 KB에 반영합니다.

    전량 리스트를 만들지 않고 Keyset seek 페이징과 ORM 객체 expunge 가 적용된
    PagedQuerySequence 를 반환하여 페이지 단위로 읽습니다.
    """
    initial_objs = set(db.identity_map.values()) if hasattr(db, "identity_map") else set()
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

    base_query = (
        select(BidAnnouncement)
        .where(delta_filter)
        .order_by(BidAnnouncement.collected_at.desc(), BidAnnouncement.id.desc())
    )

    def fetch_delta_page(
        offset: int,
        page_limit: int,
        cursor: CursorKey | None,
        snapshot_cursor: CursorKey | None,
        use_offset: bool,
    ) -> list[BidAnnouncement]:
        return _fetch_keyset_page(
            db,
            base_query,
            BidAnnouncement.collected_at,
            BidAnnouncement.id,
            offset,
            page_limit,
            cursor,
            snapshot_cursor,
            use_offset,
            initial_objs,
        )

    return (
        PagedQuerySequence(
            delta_count,
            fetch_delta_page,
            extract_cursor=lambda ann: (ann.collected_at, ann.id),
        ),
        "announcements_by_collected_delta",
    )


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
