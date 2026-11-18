"""야간 낙찰 결과 수집의 최근 14일 재수집 계약 테스트.

등록일시보다 늦게 API 에 노출되는 낙찰 결과를 놓치지 않도록 결과 수집
구간의 시작일만 당기고, 공고 구간·체크포인트 공백 회수·중복 적재는 그대로
유지되는지 확인합니다. 외부 나라장터 API 와 운영 DB 는 호출하지 않습니다.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import func, select

import src.app.services.collector_service as svc
from src.app.models.bids import BidAnnouncement, BidResult

FAKE_TODAY = datetime(2026, 11, 18, 10, 0, 0)
YESTERDAY = "20261117"
RESCAN_START = "20261104"


def _patch_common(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(svc, "utcnow", lambda: FAKE_TODAY)
    monkeypatch.setattr(svc, "get_service_key", lambda: "test-service-key")


def _seed_ann(db, category: str, dt: datetime) -> None:
    db.add(
        BidAnnouncement(
            bid_ntce_no=f"ANN-{category}",
            bid_ntce_ord="000",
            category=category,
            bid_ntce_dt=dt,
            collected_at=dt,
        )
    )
    db.commit()


def _seed_res(db, category: str, dt: datetime) -> None:
    db.add(
        BidResult(
            bid_ntce_no=f"RES-{category}",
            bid_ntce_ord="001",
            category=category,
            rl_openg_dt=dt,
            collected_at=dt,
        )
    )
    db.commit()


def _capture_category(calls: list[tuple[str, str, str]]):
    async def _stream(start, end, on_rows, *, category):
        calls.append((start, end, category))
        return 0

    return _stream


def _capture_plain(calls: list[tuple[str, str]]):
    async def _stream(start, end, on_rows):
        calls.append((start, end))
        return 0

    return _stream


@pytest.mark.asyncio
async def test_result_window_rescans_recent_14_days(isolated_db, monkeypatch):
    """체크포인트가 어제까지 차 있어도 결과 구간은 어제 포함 14일을 다시 받습니다."""
    _seed_ann(isolated_db, "Thng", datetime(2026, 11, 17, 12, 0, 0))
    _seed_res(isolated_db, "Thng", datetime(2026, 11, 17, 12, 0, 0))
    _patch_common(monkeypatch)
    result_calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(svc, "stream_bid_announcements", _capture_category([]))
    monkeypatch.setattr(svc, "stream_bid_data", _capture_category(result_calls))
    monkeypatch.setattr(svc, "stream_bid_license_limits", _capture_plain([]))
    monkeypatch.setattr(svc, "stream_bid_participation_regions", _capture_plain([]))

    result = await svc.collect_bids(
        isolated_db,
        fetch_type="both",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result_calls == [(RESCAN_START, YESTERDAY, "Thng")]
    assert result["result_start_date"] == RESCAN_START
    assert result["start_date"] == YESTERDAY


@pytest.mark.asyncio
async def test_announcement_window_stays_at_checkpoint(isolated_db, monkeypatch):
    """공고·면허제한·참가가능지역 구간은 기존 체크포인트 창을 그대로 씁니다."""
    _seed_ann(isolated_db, "Thng", datetime(2026, 11, 17, 12, 0, 0))
    _seed_res(isolated_db, "Thng", datetime(2026, 11, 17, 12, 0, 0))
    _patch_common(monkeypatch)
    ann_calls: list[tuple[str, str, str]] = []
    license_calls: list[tuple[str, str]] = []
    region_calls: list[tuple[str, str]] = []
    monkeypatch.setattr(svc, "stream_bid_announcements", _capture_category(ann_calls))
    monkeypatch.setattr(svc, "stream_bid_data", _capture_category([]))
    monkeypatch.setattr(svc, "stream_bid_license_limits", _capture_plain(license_calls))
    monkeypatch.setattr(svc, "stream_bid_participation_regions", _capture_plain(region_calls))

    await svc.collect_bids(
        isolated_db,
        fetch_type="both",
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert ann_calls == [(YESTERDAY, YESTERDAY, "Thng")]
    assert license_calls == [(YESTERDAY, YESTERDAY)]
    assert region_calls == [(YESTERDAY, YESTERDAY)]


@pytest.mark.asyncio
async def test_checkpoint_gap_longer_than_rescan_is_preserved(isolated_db, monkeypatch):
    """공백 회수 구간이 14일보다 길면 그 구간을 그대로 씁니다."""
    _seed_res(isolated_db, "Servc", datetime(2026, 10, 28, 12, 0, 0))
    _patch_common(monkeypatch)
    result_calls: list[tuple[str, str, str]] = []
    monkeypatch.setattr(svc, "stream_bid_data", _capture_category(result_calls))

    result = await svc.collect_bids(
        isolated_db,
        fetch_type="result",
        categories=("Servc",),
        refresh_aggregates=False,
        max_catchup_days=30,
    )

    assert result_calls == [("20261029", YESTERDAY, "Servc")]
    start = datetime.strptime(result_calls[0][0], "%Y%m%d")
    end = datetime.strptime(result_calls[0][1], "%Y%m%d")
    assert (end - start).days + 1 == 20
    assert result["result_start_date"] == "20261029"


@pytest.mark.asyncio
async def test_duplicate_result_rows_are_not_inserted_twice(isolated_db, monkeypatch):
    """재수집이 같은 결과를 다시 받아도 INSERT IGNORE 로 행과 지표가 늘지 않습니다."""
    _seed_res(isolated_db, "Servc", datetime(2026, 11, 16, 12, 0, 0))
    _patch_common(monkeypatch)
    monkeypatch.setattr(svc, "_invalidate_rag_cache_sync", lambda: None)

    duplicate_row = {
        "bid_ntce_no": "DUP-RES-1",
        "bid_ntce_ord": "001",
        "category": "Servc",
        "rl_openg_dt": datetime(2026, 11, 16, 12, 0, 0),
        "collected_at": datetime(2026, 11, 16, 12, 0, 0),
    }

    async def _stream(start, end, on_rows, *, category):
        return on_rows([dict(duplicate_row)])

    monkeypatch.setattr(svc, "stream_bid_data", _stream)

    first = await svc.collect_bids(
        isolated_db,
        fetch_type="result",
        categories=("Servc",),
        refresh_aggregates=False,
    )
    second = await svc.collect_bids(
        isolated_db,
        fetch_type="result",
        categories=("Servc",),
        refresh_aggregates=False,
    )

    assert first["result_count"] == 1
    assert second["result_count"] == 0
    assert isolated_db.scalar(select(func.count()).select_from(BidResult)) == 2
