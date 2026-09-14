"""
tests/test_backfill_bid_restrictions.py

제한정보 백필 스크립트의 구간 분할과 실패 보고.
"""

from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock, MagicMock

import pytest

from scripts import backfill_bid_restrictions as backfill
from src.app.services.api_collector import RangeCollectionError


def test_month_windows_split_on_calendar_months():
    assert backfill.month_windows(date(2025, 12, 20), date(2026, 2, 3)) == [
        ("20251220", "20251231"),
        ("20260101", "20260131"),
        ("20260201", "20260203"),
    ]


def test_month_windows_single_day():
    assert backfill.month_windows(date(2026, 9, 11), date(2026, 9, 11)) == [
        ("20260911", "20260911")
    ]


def test_month_windows_rejects_reversed_range():
    with pytest.raises(ValueError, match="늦습니다"):
        backfill.month_windows(date(2026, 9, 2), date(2026, 9, 1))


@pytest.mark.asyncio
async def test_backfill_records_partial_failure_and_totals(monkeypatch):
    db = MagicMock()
    db.scalar.return_value = 0
    monkeypatch.setattr(backfill, "SessionLocal", lambda: db)
    monkeypatch.setattr(backfill, "stream_bid_license_limits", AsyncMock(return_value=5))
    monkeypatch.setattr(
        backfill,
        "stream_bid_participation_regions",
        AsyncMock(side_effect=RangeCollectionError("참가가능지역", 2, [("20260901", "20260915")])),
    )

    report = await backfill.backfill(date(2026, 9, 1), date(2026, 9, 30))

    assert report["windows"][0]["license_limit"] == 5
    assert report["windows"][0]["participation_region"] == 2
    assert report["windows"][0]["participation_region_failed_ranges"] == [("20260901", "20260915")]


def test_main_exits_without_service_key(monkeypatch, capsys):
    monkeypatch.setattr(backfill, "load_dotenv", lambda *args, **kwargs: False)
    monkeypatch.setattr(backfill, "get_service_key", lambda: "")

    assert backfill.main(["--start", "20260901"]) == 2
    assert "serviceKey" in capsys.readouterr().err
