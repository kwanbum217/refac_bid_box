"""A5 회귀 시험: 수집 부분 실패 알림과 _bulk_insert 실제 적재 건수.

- failed_ranges 가 있으면 알림을 한 번 보내고, 없으면 보내지 않는다.
- 알림 발신이 실패해도 수집 결과와 반환값은 바뀌지 않는다.
- INSERT IGNORE 중복 무시 시 _bulk_insert 는 시도 건수가 아니라 실제 삽입
  건수를 돌려준다.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker

from src.app.models.bids import BidAnnouncement
from src.app.services import collector_service
from src.app.services.api_collector import RangeCollectionError
from src.tasks import notifier as notifier_module


@pytest.fixture
def sqlite_session():
    engine = create_engine("sqlite://")
    BidAnnouncement.__table__.create(engine)
    session = sessionmaker(bind=engine)()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


def _patch_collection_streams(
    monkeypatch: pytest.MonkeyPatch,
    *,
    announcement_error: RangeCollectionError | None = None,
) -> None:
    monkeypatch.setattr(collector_service, "get_service_key", lambda: "test-service-key")
    monkeypatch.setattr(
        collector_service,
        "_resolve_collection_window_thread",
        lambda **kwargs: ("20260101", "20260102", False),
    )

    async def stream_bid_announcements(start, end, on_rows, *, category):
        if announcement_error is not None:
            raise announcement_error
        return 0

    async def stream_empty(start, end, on_rows):
        return 0

    monkeypatch.setattr(collector_service, "stream_bid_announcements", stream_bid_announcements)
    monkeypatch.setattr(collector_service, "stream_bid_license_limits", stream_empty)
    monkeypatch.setattr(collector_service, "stream_bid_participation_regions", stream_empty)


def _collect(db, **overrides: Any) -> dict[str, Any]:
    options: dict[str, Any] = {
        "fetch_type": "announce",
        "categories": ("Thng",),
        "refresh_aggregates": False,
    }
    options.update(overrides)
    return asyncio.run(collector_service.collect_bids(db, **options))


def test_partial_failure_sends_one_alert(monkeypatch, sqlite_session):
    error = RangeCollectionError("test", 7, [("20260101", "20260103")])
    _patch_collection_streams(monkeypatch, announcement_error=error)
    calls: list[list[dict[str, Any]]] = []

    async def fake_notify(failed_ranges):
        calls.append(failed_ranges)

    monkeypatch.setattr(notifier_module, "notify_collection_partial_failure", fake_notify)

    result = _collect(sqlite_session)

    assert result["status"] == "partial_success"
    assert result["announcement_count"] == 7
    assert len(result["failed_ranges"]) == 1
    assert result["failed_ranges"][0] == {
        "category": "Thng",
        "kind": "announcement",
        "start_date": "20260101",
        "end_date": "20260103",
    }
    assert len(calls) == 1
    assert calls[0] == result["failed_ranges"]


def test_success_sends_no_alert(monkeypatch, sqlite_session):
    _patch_collection_streams(monkeypatch)
    calls: list[list[dict[str, Any]]] = []

    async def fake_notify(failed_ranges):
        calls.append(failed_ranges)

    monkeypatch.setattr(notifier_module, "notify_collection_partial_failure", fake_notify)

    result = _collect(sqlite_session)

    assert result["status"] == "success"
    assert result["failed_ranges"] == []
    assert calls == []


def test_alert_failure_does_not_change_collection_result(monkeypatch, sqlite_session):
    error = RangeCollectionError("test", 7, [("20260101", "20260103")])
    _patch_collection_streams(monkeypatch, announcement_error=error)

    async def broken_notify(failed_ranges):
        raise RuntimeError("webhook unavailable")

    monkeypatch.setattr(notifier_module, "notify_collection_partial_failure", broken_notify)

    result = _collect(sqlite_session)

    assert result["status"] == "partial_success"
    assert result["announcement_count"] == 7
    assert len(result["failed_ranges"]) == 1


def test_bulk_insert_reports_actual_rowcount(sqlite_session):
    rows = [
        {"bid_ntce_no": "A1", "bid_ntce_ord": "000", "category": "Thng"},
        {"bid_ntce_no": "A1", "bid_ntce_ord": "000", "category": "Thng"},
        {"bid_ntce_no": "A2", "bid_ntce_ord": "000", "category": "Thng"},
    ]

    assert collector_service._bulk_insert(sqlite_session, BidAnnouncement, rows) == 2
    assert sqlite_session.scalar(select(func.count()).select_from(BidAnnouncement)) == 2

    # 같은 행을 다시 넣으면 중복은 모두 무시되어 실제 적재는 0건입니다.
    assert collector_service._bulk_insert(sqlite_session, BidAnnouncement, rows) == 0
    assert sqlite_session.scalar(select(func.count()).select_from(BidAnnouncement)) == 2
