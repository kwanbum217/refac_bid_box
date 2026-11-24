"""
tests/test_kb_collected_count_perf_20261124.py

수집일 폴백 건수 질의를 상한에서 끊어 세는 변경의 결과 동일성 시험.
인메모리 SQLite 만 쓰고 운영 .env 에 기대지 않습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.db import Base
from src.app.models.bids import BidAnnouncement
from src.app.services import kb_document_builder
from src.app.services.kb_document_builder import (
    PagedQuerySequence,
    _count_announcements_capped,
    _latest_announcement_scope,
    _resolve_announcements,
)

# test_kb_builder 와 같은 고정 기준 시각입니다. 실행 날짜가 지나며 창이 밀리지
# 않도록 공고일은 1년 이전, 수집일은 기준 시각 근처로 둡니다.
NOW = datetime(2026, 6, 2, 12, 0, 0)
ONE_YEAR_AGO = datetime(2025, 6, 2, 12, 0, 0)


def _create_sqlite_session() -> Session:
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)()


def _add_announcement(
    db: Session,
    *,
    bid_ntce_no: str,
    ord: str = "000",
    category: str = "용역",
    notice_dt: datetime | None = None,
    collected_at: datetime,
    ntce_kind_nm: str | None = None,
) -> BidAnnouncement:
    announcement = BidAnnouncement(
        bid_ntce_no=bid_ntce_no,
        bid_ntce_ord=ord,
        bid_ntce_nm=f"공고_{bid_ntce_no}_{ord}",
        category=category,
        bid_ntce_dt=datetime(2024, 1, 1) if notice_dt is None else notice_dt,
        collected_at=collected_at,
        ntce_kind_nm=ntce_kind_nm,
    )
    db.add(announcement)
    return announcement


def _seed_collected_only(db: Session, count: int) -> list[BidAnnouncement]:
    """공고일 창 밖, 수집일 창 안의 공고를 최신 수집 순으로 넣습니다."""
    rows = [
        _add_announcement(
            db,
            bid_ntce_no=f"COLL_{i:06d}",
            collected_at=NOW - timedelta(hours=i),
        )
        for i in range(count)
    ]
    db.commit()
    return rows


def _capture_sql(db: Session) -> list[str]:
    statements: list[str] = []
    engine = db.get_bind()

    def _record(conn: object, cursor: object, statement: str, *args: object) -> None:
        statements.append(statement)

    event.listen(engine, "before_cursor_execute", _record)
    return statements


def _count_statements(statements: list[str], *, derived: bool) -> list[str]:
    """건수 질의만 고릅니다. 상한 집계는 파생 테이블(FROM (SELECT ...))을 씁니다."""
    counts = [sql for sql in statements if "count(" in sql.lower()]
    if derived:
        return [sql for sql in counts if "from (select" in sql.lower()]
    return [sql for sql in counts if "from (select" not in sql.lower()]


def test_capped_count_returns_min_of_count_and_limit() -> None:
    db = _create_sqlite_session()
    _seed_collected_only(db, 6)
    stmt = _latest_announcement_scope(select(BidAnnouncement.id))

    assert _count_announcements_capped(db, stmt, 100) == 6
    assert _count_announcements_capped(db, stmt, 6) == 6
    assert _count_announcements_capped(db, stmt, 5) == 5
    assert _count_announcements_capped(db, stmt, 1) == 1


def test_collected_fallback_total_matches_exact_count_below_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _create_sqlite_session()
    _seed_collected_only(db, 8)
    monkeypatch.setattr(kb_document_builder, "_max_documents", lambda: 100)

    statements = _capture_sql(db)
    seq, mode = _resolve_announcements(db, ONE_YEAR_AGO, ONE_YEAR_AGO)

    exact_count = db.scalar(
        _latest_announcement_scope(
            select(func.count(BidAnnouncement.id)).where(
                BidAnnouncement.collected_at >= ONE_YEAR_AGO
            )
        )
    )
    assert mode == "announcements_by_collected_at"
    assert isinstance(seq, PagedQuerySequence)
    assert exact_count == 8
    assert len(seq) == exact_count
    assert len(list(seq)) == exact_count

    count_sql = _count_statements(statements, derived=True)
    assert count_sql, "폴백 건수 질의가 실행되지 않았습니다."
    assert all("LIMIT" in sql.upper() for sql in count_sql)


def test_collected_fallback_total_caps_at_limit_and_keeps_newest_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _create_sqlite_session()
    rows = _seed_collected_only(db, 8)
    monkeypatch.setattr(kb_document_builder, "_max_documents", lambda: 3)

    statements = _capture_sql(db)
    seq, mode = _resolve_announcements(db, ONE_YEAR_AGO, ONE_YEAR_AGO)

    assert mode == "announcements_by_collected_at"
    assert isinstance(seq, PagedQuerySequence)
    # total 은 min(8, 3) = 3 이고, 선택되는 행은 최신 수집 3건 그대로입니다.
    assert len(seq) == 3
    got_ids = [announcement.id for announcement in seq]
    expected_ids = [
        row.id for row in sorted(rows, key=lambda row: (row.collected_at, row.id), reverse=True)[:3]
    ]
    assert got_ids == expected_ids

    count_sql = _count_statements(statements, derived=True)
    assert count_sql, "폴백 건수 질의가 실행되지 않았습니다."
    assert all("LIMIT" in sql.upper() for sql in count_sql), (
        "폴백 건수 질의가 상한 없이 전량 집계로 실행됐습니다."
    )


def test_collected_fallback_latest_ord_and_cancelled_semantics_unchanged(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _create_sqlite_session()
    # A: 같은 공고의 두 차수 -> 최신 차수 1건만 남습니다.
    _add_announcement(db, bid_ntce_no="GROUP_A", ord="000", collected_at=NOW - timedelta(hours=5))
    latest_a = _add_announcement(
        db, bid_ntce_no="GROUP_A", ord="001", collected_at=NOW - timedelta(hours=4)
    )
    # B: 최신 차수가 취소공고 -> 이전 차수가 대신 들어가지 않습니다.
    _add_announcement(db, bid_ntce_no="GROUP_B", ord="001", collected_at=NOW - timedelta(hours=3))
    _add_announcement(
        db,
        bid_ntce_no="GROUP_B",
        ord="002",
        collected_at=NOW - timedelta(hours=2),
        ntce_kind_nm="취소공고",
    )
    # C: 단일 유효 공고.
    single_c = _add_announcement(
        db, bid_ntce_no="GROUP_C", ord="000", collected_at=NOW - timedelta(hours=1)
    )
    db.commit()
    monkeypatch.setattr(kb_document_builder, "_max_documents", lambda: 100)

    seq, mode = _resolve_announcements(db, ONE_YEAR_AGO, ONE_YEAR_AGO)

    assert mode == "announcements_by_collected_at"
    assert isinstance(seq, PagedQuerySequence)
    assert len(seq) == 2
    assert [announcement.id for announcement in seq] == [single_c.id, latest_a.id]


def test_notice_path_count_query_stays_exact_and_uncapped(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _create_sqlite_session()
    for i in range(5):
        _add_announcement(
            db,
            bid_ntce_no=f"NOTICE_{i:06d}",
            notice_dt=NOW - timedelta(hours=i),
            collected_at=datetime(2024, 1, 1),
        )
    db.commit()
    monkeypatch.setattr(kb_document_builder, "_max_documents", lambda: 3)

    statements = _capture_sql(db)
    seq, mode = _resolve_announcements(db, ONE_YEAR_AGO, ONE_YEAR_AGO)

    assert mode == "announcements_by_notice_date"
    assert isinstance(seq, PagedQuerySequence)
    assert len(seq) == 3

    count_sql = _count_statements(statements, derived=False)
    assert count_sql, "공고일 건수 질의가 실행되지 않았습니다."
    # 공고일 경로는 후보가 창 크기로 제한되므로 기존 전량 집계를 그대로 둡니다.
    assert all("LIMIT" not in sql.upper() for sql in count_sql)


def test_collected_fallback_unavailable_when_no_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = _create_sqlite_session()
    monkeypatch.setattr(kb_document_builder, "_max_documents", lambda: 3)

    seq, mode = _resolve_announcements(db, ONE_YEAR_AGO, ONE_YEAR_AGO)

    assert mode == "announcements_unavailable"
    assert seq == []
