"""
src/app/services/kb_document_builder.py

지식베이스 문서 생성 및 공고/낙찰 해석 모듈.
"""

from __future__ import annotations

import os
from collections.abc import Callable, Iterator, Sequence
from datetime import datetime
from typing import Any, TypeVar, overload

from sqlalchemy import and_, func, or_, select, tuple_
from sqlalchemy.orm import Session

from src.app.models.bids import (
    CATEGORY_LABELS,
    BidAnnouncement,
    BidResult,
    extract_business_budget,
    normalize_bid_ntce_ord,
)
from src.app.services.bid_queries import (
    not_cancelled_clause,
    similar_announcement_latest_filter,
)

# KB 색인 상한의 단일 정의입니다. kb_builder 는 이 값을 import 해 재수출합니다.
# 원본은 10 이었습니다. 그 값이 야간 재색인에 그대로 적용되면 목표 문서가 10건이
# 되고, 기존 색인 전부가 삭제 대상으로 계산됩니다. 2026-08-07 에 KB 를 50만 건으로
# 확대한 뒤로는 운영 규모와 맞는 값이어야 합니다.
#
# 2026-09-09 에 500,000 에서 520,000 으로 올렸습니다. 최근 1년 공고가 505,271건이라
# 상한이 1.04% 를 잘라내 창의 가장 오래된 3.3일치가 색인에서 빠지고 있었습니다.
# "최근 1년" 이라는 창의 의미와 상한이 어긋난 상태였습니다. Wave AP 로 메모리 폭주가
# 해소돼(14GiB 조건 조회 계층 1,027MB) 여유가 생겼고, 데이터 증가분을 흡수할 마진을
# 두어 520,000 으로 정했습니다. 환경변수 KB_MAX_DOCUMENTS 로 덮어쓸 수 있습니다.
DEFAULT_MAX_DOCUMENTS = 520_000

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


def _latest_announcement_scope(stmt: Any) -> Any:
    """공고 원천에 최신 차수 1행과 취소 제외를 적용합니다.

    최신 차수를 먼저 판정하고 취소 제외를 나중에 적용해야, 최신 차수가 취소공고인
    공고에서 이전 차수가 대신 들어가지 않습니다. 최신 차수·취소 정의는 공고 탐색
    목록과 같은 bid_queries 함수를 씁니다.
    """
    return similar_announcement_latest_filter(stmt).where(not_cancelled_clause())


def _count_announcements_capped(db: Session, stmt: Any, limit: int) -> int:
    """건수를 limit 에서 끊어 세어 min(count, limit) 을 반환합니다.

    [설계 근거: 폴백 건수 질의의 비용 상한]
    호출자는 이 값을 총 건수(total)로만 쓰고, total 은 min(count, limit) 입니다.
    최신 차수 판정(NOT EXISTS)은 후보 행마다 같은 공고번호의 인덱스를 다시 읽어야
    해서 전량 집계 비용이 후보 행 수에 비례합니다. 상한을 걸면 limit 건을 찾는
    즉시 스캔이 멈추므로, 결과는 그대로면서 비용이 후보 전체 크기와 분리됩니다.
    """
    capped = db.scalar(select(func.count()).select_from(stmt.limit(limit + 1).subquery()))
    return min(capped or 0, limit)


def _resolve_announcements(
    db: Session,
    one_year_ago: datetime,
    collected_one_year_ago: datetime | None = None,
) -> tuple[Sequence[BidAnnouncement], str]:
    """공고일 기준 -> 수집일 기준 순으로 폴백합니다.

    one_year_ago 는 원문 계열(KST naive) 컬럼인 bid_ntce_dt 용이고,
    collected_one_year_ago 는 앱 계열(UTC naive) 컬럼인 collected_at 용입니다.
    후자를 생략하면 전자를 그대로 씁니다.

    .scalars().all() 로 전량을 한 번에 로드하지 않고,
    Keyset seek 페이징과 ORM 객체 expunge 가 적용된 PagedQuerySequence 를 반환합니다.

    수집일 폴백 건수는 상한에서 끊어 셉니다. collected_at 은 색인 범위가 넓어
    전량 집계가 후보 행 수에 비례해 비싸지만, total 이 min(count, limit) 이므로
    limit 건을 넘는 순간의 정확한 값은 필요하지 않습니다.
    """
    collected_cutoff = one_year_ago if collected_one_year_ago is None else collected_one_year_ago
    limit = _max_documents()
    initial_objs = set(db.identity_map.values()) if hasattr(db, "identity_map") else set()

    notice_count = (
        db.scalar(
            _latest_announcement_scope(
                select(func.count(BidAnnouncement.id)).where(
                    BidAnnouncement.bid_ntce_dt >= one_year_ago
                )
            )
        )
        or 0
    )

    if notice_count > 0:
        total = min(notice_count, limit)
        base_query = _latest_announcement_scope(
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

    collected_count = _count_announcements_capped(
        db,
        _latest_announcement_scope(
            select(BidAnnouncement.id).where(BidAnnouncement.collected_at >= collected_cutoff)
        ),
        limit,
    )

    if collected_count > 0:
        total = min(collected_count, limit)
        base_query = _latest_announcement_scope(
            select(BidAnnouncement)
            .where(BidAnnouncement.collected_at >= collected_cutoff)
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


def _delta_scope_filter(db: Session, collected_since: datetime) -> Any:
    """이번 델타에 반영할 공고 범위를 만듭니다.

    수집분과 새 낙찰 결과가 참조하는 공고번호를 함께 봅니다. 최신 차수·취소
    판정은 이 범위 위에 따로 적용합니다.
    """
    result_notice_numbers = list(
        db.scalars(
            select(BidResult.bid_ntce_no)
            .where(BidResult.collected_at >= collected_since)
            .distinct()
        ).all()
    )
    if result_notice_numbers:
        return or_(
            BidAnnouncement.collected_at >= collected_since,
            BidAnnouncement.bid_ntce_no.in_(result_notice_numbers),
        )
    return BidAnnouncement.collected_at >= collected_since


def _resolve_delta_announcements(
    db: Session, collected_since: datetime
) -> tuple[Sequence[BidAnnouncement], str]:
    """이번 수집분과 새 낙찰 결과가 참조하는 공고 중 최신 차수만 KB에 반영합니다.

    전량 리스트를 만들지 않고 Keyset seek 페이징과 ORM 객체 expunge 가 적용된
    PagedQuerySequence 를 반환하여 페이지 단위로 읽습니다.
    """
    initial_objs = set(db.identity_map.values()) if hasattr(db, "identity_map") else set()
    delta_filter = _delta_scope_filter(db, collected_since)

    delta_count = (
        db.scalar(
            _latest_announcement_scope(select(func.count(BidAnnouncement.id)).where(delta_filter))
        )
        or 0
    )
    if delta_count == 0:
        return [], "announcements_by_collected_delta"

    base_query = _latest_announcement_scope(
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


def _resolve_delta_stale_ids(db: Session, collected_since: datetime) -> list[int]:
    """델타 범위에 걸린 공고 파티션에서 문서로 만들지 않는 행 id 를 찾습니다.

    파티션은 (공고번호, 업무구분)이며, 델타 범위의 행이 속한 파티션 전체를 봅니다.
    파티션마다 최신 차수가 취소공고면 남길 행이 없고, 아니면 최신 차수만 남깁니다.
    남지 않는 행은 이전 차수와 취소된 최신 차수입니다.
    """
    scope = _delta_scope_filter(db, collected_since)
    partitions = [
        (row.bid_ntce_no, row.category)
        for row in db.execute(
            select(BidAnnouncement.bid_ntce_no, BidAnnouncement.category).where(scope).distinct()
        ).all()
    ]
    if not partitions:
        return []

    partition_filter = tuple_(BidAnnouncement.bid_ntce_no, BidAnnouncement.category).in_(partitions)
    all_ids = set(db.scalars(select(BidAnnouncement.id).where(partition_filter)).all())
    kept_ids = set(
        db.scalars(
            _latest_announcement_scope(select(BidAnnouncement.id).where(partition_filter))
        ).all()
    )
    return sorted(all_ids - kept_ids)


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
