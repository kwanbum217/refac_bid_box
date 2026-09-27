"""
tests/test_collector_exists_check.py

resolve_collection_window 무데이터 검사 회귀 테스트.
카테고리마다 COUNT 로 전체 행을 세던 존재 확인이 LIMIT 1 질의로 바뀌었음을
검증합니다. 판정 동작(경고 로그, 반환 값, 체크포인트 계산)은 바뀌지 않습니다.
외부 G2B API 호출은 없습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from sqlalchemy import event

from src.app.services.collector_service import (
    MAX_CATCHUP_DAYS,
    resolve_collection_window,
)

UTCNOW_FIXED = datetime(2026, 8, 13, 10, 0, 0)


def _utcnow_fixed(fake_today: datetime):
    from unittest.mock import patch

    return patch("src.app.services.collector_service.utcnow", return_value=fake_today)


def _seed_ann(db, cat: str, dt: datetime) -> None:
    from src.app.models.bids import BidAnnouncement

    db.add(
        BidAnnouncement(
            bid_ntce_no=f"ANN-{cat}",
            bid_ntce_ord="001",
            category=cat,
            bid_ntce_dt=dt,
            collected_at=dt,
        )
    )


def _seed_res(db, cat: str, dt: datetime) -> None:
    from src.app.models.bids import BidResult

    db.add(
        BidResult(
            bid_ntce_no=f"RES-{cat}",
            bid_ntce_ord="001",
            category=cat,
            rl_openg_dt=dt,
            collected_at=dt,
        )
    )


class _SQLCapture:
    """실행된 SQL 문장을 수집합니다."""

    def __init__(self, engine):
        self.statements: list[str] = []
        event.listen(engine, "before_cursor_execute", self._record)

    def _record(self, conn, cursor, statement, parameters, context, executemany):
        self.statements.append(statement)

    def detach(self, engine):
        event.remove(engine, "before_cursor_execute", self._record)

    def existence_statements(self) -> list[str]:
        return [
            s
            for s in self.statements
            if "bid_announcements" in s.lower() or "bid_results" in s.lower()
        ]


def _assert_no_count_in_existence_check(db) -> None:
    """무데이터 검사에 COUNT 질의가 쓰이지 않음을 SQL 레벨에서 확인합니다."""
    engine = db.get_bind()
    capture = _SQLCapture(engine)
    try:
        with _utcnow_fixed(UTCNOW_FIXED):
            resolve_collection_window(
                db,
                start_date=None,
                end_date=None,
                fetch_type="both",
                categories=("Thng",),
            )
        db.commit()
        for stmt in capture.existence_statements():
            assert "count(" not in stmt.lower(), (
                f"무데이터 검사에 COUNT 질의가 남아 있습니다: {stmt}"
            )
    finally:
        capture.detach(engine)


@pytest.mark.asyncio
async def test_missing_announcement_category_returns_max_catchup_window(isolated_db):
    """(a) 한 분류에 공고가 한 건도 없으면 max_catchup_days 창과 is_catchup True."""
    fake_today = UTCNOW_FIXED
    _seed_res(isolated_db, "Thng", datetime(2026, 8, 12, 10, 0, 0))
    isolated_db.commit()

    with _utcnow_fixed(fake_today):
        start, end, is_catchup = resolve_collection_window(
            isolated_db,
            start_date=None,
            end_date=None,
            fetch_type="both",
            categories=("Thng",),
        )

    yesterday = (fake_today - timedelta(days=1)).date()
    expected_start = (yesterday - timedelta(days=MAX_CATCHUP_DAYS - 1)).strftime("%Y%m%d")
    assert start == expected_start
    assert end == yesterday.strftime("%Y%m%d")
    assert is_catchup is True


@pytest.mark.asyncio
async def test_missing_result_category_returns_max_catchup_window(isolated_db):
    """(b) 한 분류에 결과가 한 건도 없으면 max_catchup_days 창과 is_catchup True."""
    fake_today = UTCNOW_FIXED
    _seed_ann(isolated_db, "Thng", datetime(2026, 8, 12, 10, 0, 0))
    isolated_db.commit()

    with _utcnow_fixed(fake_today):
        start, end, is_catchup = resolve_collection_window(
            isolated_db,
            start_date=None,
            end_date=None,
            fetch_type="both",
            categories=("Thng",),
        )

    yesterday = (fake_today - timedelta(days=1)).date()
    expected_start = (yesterday - timedelta(days=MAX_CATCHUP_DAYS - 1)).strftime("%Y%m%d")
    assert start == expected_start
    assert end == yesterday.strftime("%Y%m%d")
    assert is_catchup is True


@pytest.mark.asyncio
async def test_all_categories_present_returns_checkpoint_window(isolated_db):
    """(c) 모든 분류에 행이 있으면 체크포인트 기반 창을 반환합니다(기존 동작 유지)."""
    fake_today = UTCNOW_FIXED
    _seed_ann(isolated_db, "Thng", datetime(2026, 8, 12, 10, 0, 0))
    _seed_res(isolated_db, "Thng", datetime(2026, 8, 12, 10, 0, 0))
    isolated_db.commit()

    with _utcnow_fixed(fake_today):
        start, end, is_catchup = resolve_collection_window(
            isolated_db,
            start_date=None,
            end_date=None,
            fetch_type="both",
            categories=("Thng",),
        )

    assert start == "20260812"
    assert end == "20260812"
    assert is_catchup is False


@pytest.mark.asyncio
async def test_existence_check_does_not_use_count(isolated_db):
    """(d) 무데이터 검사 질의에 COUNT 가 쓰이지 않습니다(LIMIT 1 존재 확인)."""
    _assert_no_count_in_existence_check(isolated_db)


@pytest.mark.asyncio
async def test_existence_check_without_data_does_not_use_count(isolated_db):
    """데이터가 없는 분류의 무데이터 검사에서도 COUNT 가 쓰이지 않습니다."""
    _assert_no_count_in_existence_check(isolated_db)
