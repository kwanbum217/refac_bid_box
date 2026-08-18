"""
tests/test_collector_catchup.py

누락일 자동 회복 계약 테스트.
  - resolve_collection_window: 공백 탐지와 날짜 창 결정 로직
  - collect_bids: 하루/나흘 중단 회수, 동일 범위 재실행(멱등성), 부분 실패 가시성
외부 G2B API 호출은 없습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from src.app.services.collector_service import (
    MAX_CATCHUP_DAYS,
    resolve_collection_window,
)

# ---------------------------------------------------------------------------
# 공통 헬퍼
# ---------------------------------------------------------------------------


def _make_db(ann_min_of_max: datetime | None, res_min_of_max: datetime | None):
    """categories=None 경로 전용 모의 세션.

    카테고리별 존재 확인은 건너뛰므로(if categories: 블록) scalar() 큐가
    MIN(MAX per cat) 결과만 반환해도 충분합니다.
    ann_min_of_max: 공고 타입의 MIN(MAX) 값
    res_min_of_max: 결과 타입의 MIN(MAX) 값
    """

    class FakeSession:
        def __init__(self):
            self._queue: list[datetime | None] = [ann_min_of_max, res_min_of_max]

        def scalar(self, _stmt):
            return self._queue.pop(0) if self._queue else None

    return FakeSession()


def _utcnow_fixed(fake_today: datetime):
    return patch("src.app.services.collector_service.utcnow", return_value=fake_today)


def _seed_ann(db, cat: str, dt: datetime, suffix: str = "") -> None:
    from src.app.models.bids import BidAnnouncement

    db.add(
        BidAnnouncement(
            bid_ntce_no=f"ANN-{cat}-{suffix or dt.strftime('%m%d')}",
            bid_ntce_ord="001",
            category=cat,
            bid_ntce_dt=dt,
            collected_at=dt,
        )
    )


def _seed_res(db, cat: str, dt: datetime, suffix: str = "") -> None:
    from src.app.models.bids import BidResult

    db.add(
        BidResult(
            bid_ntce_no=f"RES-{cat}-{suffix or dt.strftime('%m%d')}",
            bid_ntce_ord="001",
            category=cat,
            rl_openg_dt=dt,
            collected_at=dt,
        )
    )


# ---------------------------------------------------------------------------
# resolve_collection_window 단위 테스트 (categories=None, mock DB)
# ---------------------------------------------------------------------------


class TestResolveCollectionWindow:
    """날짜 창 결정 핵심 로직 단위 테스트. categories=None 경로를 검증합니다."""

    def test_explicit_start_date_bypasses_gap_detection(self):
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        db = _make_db(None, None)

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db,
                start_date="20260810",
                end_date="20260812",
                fetch_type="both",
            )

        assert start == "20260810"
        assert end == "20260812"
        assert is_catchup is False

    def test_empty_db_returns_max_catchup_window(self):
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        db = _make_db(None, None)

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db, start_date=None, end_date=None, fetch_type="both"
            )

        yesterday = (fake_today - timedelta(days=1)).date()
        expected_start = (yesterday - timedelta(days=MAX_CATCHUP_DAYS - 1)).strftime("%Y%m%d")
        assert start == expected_start
        assert end == yesterday.strftime("%Y%m%d")
        assert is_catchup is True

    def test_one_day_gap_returns_exact_window(self):
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        two_days_ago = datetime(2026, 8, 11, 12, 0, 0)
        db = _make_db(two_days_ago, two_days_ago)

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db, start_date=None, end_date=None, fetch_type="both"
            )

        assert start == "20260812"
        assert end == "20260812"
        assert is_catchup is True

    def test_four_day_gap_returns_four_day_window(self):
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        five_days_ago = datetime(2026, 8, 8, 12, 0, 0)
        db = _make_db(five_days_ago, five_days_ago)

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db, start_date=None, end_date=None, fetch_type="both"
            )

        assert start == "20260809"
        assert end == "20260812"
        assert is_catchup is True

    def test_gap_exceeding_limit_is_capped(self):
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        thirty_days_ago = datetime(2026, 7, 14, 12, 0, 0)
        db = _make_db(thirty_days_ago, thirty_days_ago)

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db, start_date=None, end_date=None, fetch_type="both"
            )

        yesterday = (fake_today - timedelta(days=1)).date()
        expected_start = (yesterday - timedelta(days=MAX_CATCHUP_DAYS - 1)).strftime("%Y%m%d")
        assert start == expected_start
        assert end == yesterday.strftime("%Y%m%d")
        assert is_catchup is True

    def test_no_gap_returns_yesterday_not_catchup(self):
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        yesterday_dt = datetime(2026, 8, 12, 12, 0, 0)
        db = _make_db(yesterday_dt, yesterday_dt)

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db, start_date=None, end_date=None, fetch_type="both"
            )

        assert start == "20260812"
        assert end == "20260812"
        assert is_catchup is False

    def test_announce_only_uses_ann_column(self):
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        two_days_ago = datetime(2026, 8, 11, 12, 0, 0)
        db = _make_db(two_days_ago, None)

        with _utcnow_fixed(fake_today):
            start, _end, is_catchup = resolve_collection_window(
                db, start_date=None, end_date=None, fetch_type="announce"
            )

        assert start == "20260812"
        assert is_catchup is True

    def test_custom_max_catchup_days(self):
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        ten_days_ago = datetime(2026, 8, 3, 12, 0, 0)
        db = _make_db(ten_days_ago, ten_days_ago)

        with _utcnow_fixed(fake_today):
            start, _end, is_catchup = resolve_collection_window(
                db,
                start_date=None,
                end_date=None,
                fetch_type="both",
                max_catchup_days=3,
            )

        yesterday = (fake_today - timedelta(days=1)).date()
        expected_start = (yesterday - timedelta(days=2)).strftime("%Y%m%d")
        assert start == expected_start
        assert is_catchup is True

    def test_older_checkpoint_wins_across_types(self):
        """announce 체크포인트보다 result 체크포인트가 오래됐을 때 result 쪽이 채택됩니다."""
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        ann_checkpoint = datetime(2026, 8, 12, 12, 0, 0)  # 어제
        res_checkpoint = datetime(2026, 8, 7, 12, 0, 0)  # 5일 전
        db = _make_db(ann_checkpoint, res_checkpoint)

        with _utcnow_fixed(fake_today):
            start, _end, is_catchup = resolve_collection_window(
                db, start_date=None, end_date=None, fetch_type="both"
            )

        # result 8/7 이 오래됐으므로 다음 날 8/8 부터 시작해야 합니다
        assert start == "20260808", f"더 오래된 result 체크포인트를 무시했습니다: start={start}"
        assert is_catchup is True


# ---------------------------------------------------------------------------
# resolve_collection_window — DB 기반 검증 (categories 필터 포함)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_category_gap_not_skipped(isolated_db, monkeypatch):
    """느린 범주 공백이 전역 MAX 로 건너뛰어지지 않음을 DB 레벨에서 검증합니다.

    Frgcpt 개찰 최신일 8/7, Thng 8/13 → MIN(MAX per cat)=8/7 → 창 8/8~8/12.
    """
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    _seed_res(isolated_db, "Thng", datetime(2026, 8, 13, 10, 0, 0))
    _seed_res(isolated_db, "Frgcpt", datetime(2026, 8, 7, 10, 0, 0))
    isolated_db.commit()

    with _utcnow_fixed(fake_today):
        start, end, is_catchup = svc.resolve_collection_window(
            isolated_db, start_date=None, end_date=None, fetch_type="result"
        )

    assert start == "20260808", f"Frgcpt 공백이 건너뛰어졌습니다: start={start}"
    assert end == "20260812"
    assert is_catchup is True


@pytest.mark.asyncio
async def test_cross_type_min_chooses_older(isolated_db):
    """공고/결과 두 타입 중 더 오래된 쪽이 체크포인트로 채택됩니다.

    공고 최신일 8/12, 결과 최신일 8/7 → 결과 8/7 이 오래됐으므로 창은 8/8~8/12.
    `d > latest` 버그에서는 8/12 가 채택돼 창이 8/13~ 이 됩니다.
    """
    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    _seed_ann(isolated_db, "Thng", datetime(2026, 8, 12, 10, 0, 0))
    _seed_res(isolated_db, "Thng", datetime(2026, 8, 7, 10, 0, 0))
    isolated_db.commit()

    with _utcnow_fixed(fake_today):
        start, end, is_catchup = resolve_collection_window(
            isolated_db,
            start_date=None,
            end_date=None,
            fetch_type="both",
            categories=("Thng",),
        )

    assert start == "20260808", (
        f"결과 체크포인트(8/7)를 무시하고 공고(8/12)를 택했습니다: start={start}"
    )
    assert end == "20260812"
    assert is_catchup is True


@pytest.mark.asyncio
async def test_subset_categories_excludes_others(isolated_db):
    """categories 부분 집합 지정 시 나머지 범주는 체크포인트 계산에서 제외됩니다.

    Thng 결과 8/12, Frgcpt 결과 8/7 존재. categories=('Thng',) 로 한정하면
    Frgcpt 8/7 은 무시되고 Thng 8/12 만 기준이 됩니다 → 공백 없음(is_catchup=False).
    """
    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    _seed_res(isolated_db, "Thng", datetime(2026, 8, 12, 10, 0, 0))
    _seed_res(isolated_db, "Frgcpt", datetime(2026, 8, 7, 10, 0, 0))
    isolated_db.commit()

    with _utcnow_fixed(fake_today):
        start, _end, is_catchup = resolve_collection_window(
            isolated_db,
            start_date=None,
            end_date=None,
            fetch_type="result",
            categories=("Thng",),
        )

    # Thng 만 봤으므로 최신일 8/12, gap_start=8/13 > yesterday=8/12 → 공백 없음
    assert start == "20260812"
    assert is_catchup is False


@pytest.mark.asyncio
async def test_missing_category_triggers_max_catchup(isolated_db):
    """요청 범주 중 DB 에 데이터 없는 범주가 있으면 max_catchup_days 창을 사용합니다.

    Thng 결과 8/12 존재, Servc 결과 없음. categories=('Thng','Servc') → fallback.
    """
    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    _seed_res(isolated_db, "Thng", datetime(2026, 8, 12, 10, 0, 0))
    isolated_db.commit()

    with _utcnow_fixed(fake_today):
        start, _end, is_catchup = resolve_collection_window(
            isolated_db,
            start_date=None,
            end_date=None,
            fetch_type="result",
            categories=("Thng", "Servc"),
        )

    yesterday = (fake_today - timedelta(days=1)).date()
    expected_start = (yesterday - timedelta(days=MAX_CATCHUP_DAYS - 1)).strftime("%Y%m%d")
    assert start == expected_start, f"Servc 누락인데 fallback 이 발동되지 않았습니다: start={start}"
    assert is_catchup is True


# ---------------------------------------------------------------------------
# collect_bids 통합 테스트 (API 호출 없음)
# ---------------------------------------------------------------------------


def _patch_svc(monkeypatch, svc, fake_today):
    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")


@pytest.mark.asyncio
async def test_one_day_interruption_recovers(isolated_db, monkeypatch):
    """하루 중단 시나리오: Thng 공고/결과가 이틀 전까지 있고 어제가 빠진 경우."""
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    two_days_ago = datetime(2026, 8, 11, 12, 0, 0)

    _seed_ann(isolated_db, "Thng", two_days_ago)
    _seed_res(isolated_db, "Thng", two_days_ago)
    isolated_db.commit()

    _patch_svc(monkeypatch, svc, fake_today)
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=0))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))

    result = await svc.collect_bids(
        isolated_db,
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["start_date"] == "20260812"
    assert result["end_date"] == "20260812"
    assert result["catchup"] is True
    assert result["status"] in ("success", "partial_success", "failed")


@pytest.mark.asyncio
async def test_four_day_interruption_recovers(isolated_db, monkeypatch):
    """나흘 중단 시나리오: Thng 공고/결과가 5일 전까지 있으면 4일 창을 회수합니다."""
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    five_days_ago = datetime(2026, 8, 8, 12, 0, 0)

    _seed_ann(isolated_db, "Thng", five_days_ago)
    _seed_res(isolated_db, "Thng", five_days_ago)
    isolated_db.commit()

    _patch_svc(monkeypatch, svc, fake_today)
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=0))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))

    result = await svc.collect_bids(
        isolated_db,
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["start_date"] == "20260809"
    assert result["end_date"] == "20260812"
    assert result["catchup"] is True


@pytest.mark.asyncio
async def test_same_range_rerun_is_idempotent(isolated_db, monkeypatch):
    """동일 범위 재실행 멱등성: 명시적 날짜로 두 번 실행해도 결과가 동일합니다."""
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    _patch_svc(monkeypatch, svc, fake_today)
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=0))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))

    kwargs = {
        "start_date": "20260810",
        "end_date": "20260812",
        "refresh_aggregates": False,
    }
    r1 = await svc.collect_bids(isolated_db, **kwargs)
    r2 = await svc.collect_bids(isolated_db, **kwargs)

    assert r1["start_date"] == r2["start_date"] == "20260810"
    assert r1["end_date"] == r2["end_date"] == "20260812"
    assert r1["catchup"] is False
    assert r2["catchup"] is False
    assert r1["status"] == r2["status"]


@pytest.mark.asyncio
async def test_partial_failure_visible_in_metrics(isolated_db, monkeypatch):
    """부분 실패 가시성: 일부 카테고리 실패 시 categories 에 오류가 기록됩니다."""
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    _patch_svc(monkeypatch, svc, fake_today)

    async def ok_then_fail(start, end, flush_fn, *, category):
        if category == "Thng":
            return 5
        raise RuntimeError("API timeout")

    monkeypatch.setattr(svc, "stream_bid_announcements", ok_then_fail)
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))

    result = await svc.collect_bids(
        isolated_db,
        start_date="20260812",
        end_date="20260812",
        categories=("Thng", "Servc"),
        refresh_aggregates=False,
    )

    assert result["status"] == "partial_success"
    assert result["failed_count"] > 0
    assert result["announcement_count"] == 5
    assert "announcement_error" in result["categories"].get("Servc", {})
    assert result["categories"]["Thng"]["announcement_count"] == 5


@pytest.mark.asyncio
async def test_partial_failure_retry_uses_per_category_min(isolated_db, monkeypatch):
    """부분 실패 뒤 재시도 시 느린 카테고리 체크포인트에서 창을 다시 계산합니다.

    Thng 결과 8/12, Frgcpt 결과 8/7 → MIN=8/7 → 다음 창 8/8~8/12.
    """
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)

    _seed_res(isolated_db, "Thng", datetime(2026, 8, 12, 10, 0, 0))
    _seed_res(isolated_db, "Frgcpt", datetime(2026, 8, 7, 10, 0, 0))
    isolated_db.commit()

    _patch_svc(monkeypatch, svc, fake_today)
    captured: list[str] = []

    async def capture_res(start, end, flush_fn, *, category):
        captured.append(start)
        return 0

    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=0))
    monkeypatch.setattr(svc, "stream_bid_data", capture_res)

    result = await svc.collect_bids(
        isolated_db,
        fetch_type="result",
        categories=("Thng", "Frgcpt"),
        refresh_aggregates=False,
    )

    assert result["start_date"] == "20260808", (
        f"Frgcpt 공백이 건너뛰어졌습니다: start={result['start_date']}"
    )
    assert result["end_date"] == "20260812"
    assert result["catchup"] is True
    assert all(s == "20260808" for s in captured), captured


@pytest.mark.asyncio
async def test_catchup_flag_false_when_explicit_dates(isolated_db, monkeypatch):
    """명시적 날짜 지정 시 catchup=False 이며 그 날짜가 그대로 사용됩니다."""
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    _patch_svc(monkeypatch, svc, fake_today)
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=0))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))

    result = await svc.collect_bids(
        isolated_db,
        start_date="20260801",
        end_date="20260810",
        refresh_aggregates=False,
    )

    assert result["start_date"] == "20260801"
    assert result["end_date"] == "20260810"
    assert result["catchup"] is False


@pytest.mark.asyncio
async def test_sync_db_work_runs_off_event_loop_thread(isolated_db, monkeypatch):
    """동기 DB 집계와 체크포인트 조회가 이벤트 루프 스레드를 점유하지 않습니다.

    collect_bids 는 ASGI 요청 경로(POST /api/v1/bids/collect)에서 호출됩니다.
    수백만 행 집계를 루프 스레드에서 돌리면 그 시간 동안 모든 요청이 멈춥니다.
    """
    import threading

    import src.app.services.collector_service as svc

    loop_thread = threading.get_ident()
    observed: dict[str, int] = {}

    def _record(name):
        def _inner(*args, **kwargs):
            observed[name] = threading.get_ident()
            if name == "resolve":
                return "20260801", "20260801", False
            return {}

        return _inner

    _patch_svc(monkeypatch, svc, datetime(2026, 8, 13, 10, 0, 0))
    monkeypatch.setattr(svc, "resolve_collection_window", _record("resolve"))
    monkeypatch.setattr(svc, "rebuild_bid_dataset_summaries", _record("rebuild"))
    monkeypatch.setattr(svc, "warm_dashboard_stats_cache", _record("dashboard"))
    monkeypatch.setattr(svc, "warm_home_page_cache", _record("home"))
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=1))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=1))

    await svc.collect_bids(isolated_db, categories=("Thng",), refresh_aggregates=True)

    assert set(observed) == {"resolve", "rebuild", "dashboard", "home"}, observed
    for name, thread_id in observed.items():
        assert thread_id != loop_thread, f"{name} 이 이벤트 루프 스레드에서 실행되었습니다"
