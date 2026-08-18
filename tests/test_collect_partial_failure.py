"""
tests/test_collect_partial_failure.py

부분 구간 수집 실패가 성공으로 위장되지 않는지 검증합니다.

체크포인트가 MAX(date) 기준이므로 중간 구간이 조용히 비면 다음 실행이 그
구멍을 되돌아보지 않아 영구 누락이 됩니다(G1 위반). 따라서 실패 구간은
반드시 상태와 재수집 근거로 남아야 합니다. 외부 G2B API 호출은 없습니다.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock

import pytest

import src.app.services.api_collector as ac
import src.app.services.collector_service as svc
from src.app.services.api_collector import RangeCollectionError


@pytest.mark.asyncio
async def test_run_ranges_raises_when_one_range_fails(monkeypatch):
    """구간 하나가 실패하면 성공 건수를 담은 RangeCollectionError 로 올라옵니다."""
    ranges = ac.split_date_range("20260101", "20260131")
    assert len(ranges) >= 2, ranges
    doomed_start = ranges[1][0]

    async def fake_fetch_paged(
        client, api_url, step_start, step_end, num_of_rows, mapper, error_label, sem
    ):
        if step_start == doomed_start:
            raise RuntimeError("G2B 502")
        return [{"row": step_start}]

    monkeypatch.setattr(ac, "_fetch_paged", fake_fetch_paged)

    with pytest.raises(RangeCollectionError) as excinfo:
        await ac._run_ranges(
            "https://example.invalid/api",
            "20260101",
            "20260131",
            999,
            lambda item, ns: {},
            "입찰공고",
            len,
        )

    exc = excinfo.value
    assert exc.failed_ranges == [ranges[1]]
    assert exc.saved == len(ranges) - 1
    assert doomed_start in str(exc)


@pytest.mark.asyncio
async def test_run_ranges_returns_total_when_all_succeed(monkeypatch):
    """모든 구간이 성공하면 기존과 동일하게 합계를 반환합니다."""

    async def fake_fetch_paged(
        client, api_url, step_start, step_end, num_of_rows, mapper, error_label, sem
    ):
        return [{"row": step_start}]

    monkeypatch.setattr(ac, "_fetch_paged", fake_fetch_paged)
    ranges = ac.split_date_range("20260101", "20260131")

    total = await ac._run_ranges(
        "https://example.invalid/api",
        "20260101",
        "20260131",
        999,
        lambda item, ns: {},
        "입찰공고",
        len,
    )

    assert total == len(ranges)


@pytest.mark.asyncio
async def test_collect_bids_reports_partial_failure(isolated_db, monkeypatch):
    """카테고리 하나가 부분 실패하면 success 가 아니라 partial_success 입니다."""
    monkeypatch.setattr(svc, "utcnow", lambda: datetime(2026, 8, 13, 10, 0, 0))
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))

    async def fake_stream_announcements(start_date, end_date, sink, category="Thng"):
        if category == "Thng":
            raise RangeCollectionError("입찰공고", 120, [("20260601", "20260615")])
        return 40

    monkeypatch.setattr(svc, "stream_bid_announcements", fake_stream_announcements)

    result = await svc.collect_bids(
        isolated_db,
        start_date="20260601",
        end_date="20260630",
        fetch_type="announce",
        categories=("Thng", "Frgcpt"),
        refresh_aggregates=False,
    )

    assert result["status"] == "partial_success", result["status"]
    assert result["failed_count"] == 1
    # 실패 구간 이전에 적재된 120건은 유실이 아니므로 건수에 남아야 합니다.
    assert result["announcement_count"] == 160
    assert result["categories"]["Thng"]["announcement_count"] == 120
    assert result["failed_ranges"] == [
        {
            "category": "Thng",
            "kind": "announcement",
            "start_date": "20260601",
            "end_date": "20260615",
        }
    ]


@pytest.mark.asyncio
async def test_collect_bids_stays_success_without_failure(isolated_db, monkeypatch):
    """실패 구간이 없으면 기존과 동일하게 success 이고 failed_ranges 는 빕니다."""
    monkeypatch.setattr(svc, "utcnow", lambda: datetime(2026, 8, 13, 10, 0, 0))
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=10))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))

    result = await svc.collect_bids(
        isolated_db,
        start_date="20260601",
        end_date="20260630",
        fetch_type="announce",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["status"] == "success"
    assert result["failed_ranges"] == []
