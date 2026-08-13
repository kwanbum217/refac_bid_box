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
# Fixtures
# ---------------------------------------------------------------------------


def _make_db(ann_min_of_max: datetime | None, res_min_of_max: datetime | None):
    """scalar() 를 fetch_type 당 한 번씩 호출하는 모의 세션을 반환합니다.

    ann_min_of_max: MIN(MAX(bid_ntce_dt) GROUP BY category) 에 해당하는 값
    res_min_of_max: MIN(MAX(rl_openg_dt)  GROUP BY category) 에 해당하는 값
    fetch_type='announce' 면 첫 번째만, 'result' 면 두 번째만, 'both' 면 순서대로 호출됩니다.
    실제 쿼리 구조(subquery + func.min)는 무시하며 반환값만 시뮬레이션합니다.
    """

    class FakeSession:
        def __init__(self):
            self._queue: list[datetime | None] = [ann_min_of_max, res_min_of_max]

        def scalar(self, _stmt):
            return self._queue.pop(0) if self._queue else None

    return FakeSession()


def _utcnow_fixed(fake_today: datetime):
    """utcnow() 를 고정 값으로 교체하는 컨텍스트를 반환하는 헬퍼."""
    return patch("src.app.services.collector_service.utcnow", return_value=fake_today)


# ---------------------------------------------------------------------------
# resolve_collection_window 단위 테스트
# ---------------------------------------------------------------------------


class TestResolveCollectionWindow:
    """날짜 창 결정 로직 단위 테스트."""

    def test_explicit_start_date_bypasses_gap_detection(self):
        """start_date 명시 시 DB 를 쿼리하지 않고 그대로 사용합니다."""
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        db = _make_db(None, None)  # DB에 아무것도 없어도

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
        """DB 가 비어 있으면 MAX_CATCHUP_DAYS 일 창으로 시작합니다."""
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
        """하루 공백: 최신 날짜가 이틀 전이면 어제 하루를 회수합니다."""
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
        """나흘 공백: 최신 날짜가 5일 전이면 4일 창을 반환합니다."""
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
        """최대 회수 기간을 초과하는 공백은 최근 MAX_CATCHUP_DAYS 일로 잘립니다."""
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
        """공백 없음: 최신 날짜가 어제이면 어제 하루를 정상 창으로 반환합니다."""
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
        """fetch_type='announce' 시 낙찰 컬럼은 쿼리하지 않습니다."""
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        two_days_ago = datetime(2026, 8, 11, 12, 0, 0)
        db = _make_db(two_days_ago, None)

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db, start_date=None, end_date=None, fetch_type="announce"
            )

        assert start == "20260812"
        assert is_catchup is True

    def test_custom_max_catchup_days(self):
        """max_catchup_days 를 낮추면 더 짧은 창으로 잘립니다."""
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        ten_days_ago = datetime(2026, 8, 3, 12, 0, 0)
        db = _make_db(ten_days_ago, ten_days_ago)

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
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


# ---------------------------------------------------------------------------
# resolve_collection_window — per-category min checkpoint 직접 DB 검증
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_slow_category_gap_not_skipped(isolated_db, monkeypatch):
    """느린 카테고리 공백이 전역 MAX 로 건너뛰어지지 않음을 DB 레벨에서 검증합니다.

    시나리오: Frgcpt 개찰 최신일 8/7, 나머지 카테고리 8/13.
    전역 MAX = 8/13 → 잘못된 창 8/14~ 로 Frgcpt 8/8~8/12 영구 누락.
    수정 후: MIN(MAX per category) = 8/7 → 올바른 창 8/8~8/12.
    """
    from datetime import datetime

    import src.app.services.collector_service as svc
    from src.app.models.bids import BidResult

    fake_today = datetime(2026, 8, 13, 10, 0, 0)

    # Thng: 결과 최신일 2026-08-13
    isolated_db.add(
        BidResult(
            bid_ntce_no="RES-THNG-0813",
            bid_ntce_ord="001",
            category="Thng",
            rl_openg_dt=datetime(2026, 8, 13, 10, 0, 0),
            collected_at=fake_today,
        )
    )
    # Frgcpt: 결과 최신일 2026-08-07 (6일 뒤처짐)
    isolated_db.add(
        BidResult(
            bid_ntce_no="RES-FRGCPT-0807",
            bid_ntce_ord="001",
            category="Frgcpt",
            rl_openg_dt=datetime(2026, 8, 7, 10, 0, 0),
            collected_at=fake_today,
        )
    )
    isolated_db.commit()

    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)

    with _utcnow_fixed(fake_today):
        start, end, is_catchup = svc.resolve_collection_window(
            isolated_db,
            start_date=None,
            end_date=None,
            fetch_type="result",
        )

    # 전역 MAX(8/13+1=8/14) 가 아닌 MIN(MAX per cat)(8/7+1=8/8) 을 기준으로 합니다
    assert start == "20260808", f"Frgcpt 공백이 건너뛰어졌습니다: start={start}"
    assert end == "20260812"
    assert is_catchup is True


@pytest.mark.asyncio
async def test_partial_failure_retry_uses_per_category_min(isolated_db, monkeypatch):
    """부분 실패 뒤 재시도 시 느린 카테고리 체크포인트에서 창을 다시 계산합니다.

    1차 실행: Frgcpt 개찰 수집 실패, Thng 성공(8/12까지 적재).
    2차 실행(재시도): 날짜 미지정 시 Frgcpt 공백(8/8~)부터 시작해야 합니다.
    """
    from datetime import datetime

    import src.app.services.collector_service as svc
    from src.app.models.bids import BidResult

    fake_today = datetime(2026, 8, 13, 10, 0, 0)

    # 1차 실행 후 DB 상태: Thng는 8/12까지, Frgcpt는 8/7까지 적재됨
    isolated_db.add(
        BidResult(
            bid_ntce_no="RES-THNG-RETRY",
            bid_ntce_ord="001",
            category="Thng",
            rl_openg_dt=datetime(2026, 8, 12, 10, 0, 0),
            collected_at=fake_today,
        )
    )
    isolated_db.add(
        BidResult(
            bid_ntce_no="RES-FRGCPT-RETRY",
            bid_ntce_ord="001",
            category="Frgcpt",
            rl_openg_dt=datetime(2026, 8, 7, 10, 0, 0),
            collected_at=fake_today,
        )
    )
    isolated_db.commit()

    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")

    captured_starts: list[str] = []

    async def capture_stream_res(start, end, flush_fn, *, category):
        captured_starts.append(start)
        return 0

    async def noop_stream_ann(start, end, flush_fn, *, category):
        return 0

    monkeypatch.setattr(svc, "stream_bid_announcements", noop_stream_ann)
    monkeypatch.setattr(svc, "stream_bid_data", capture_stream_res)

    result = await svc.collect_bids(isolated_db, fetch_type="result", refresh_aggregates=False)

    # Frgcpt 8/7 이 MIN → window 8/8~8/12
    assert result["start_date"] == "20260808", (
        f"재시도 창이 Frgcpt 공백을 건너뛰었습니다: start={result['start_date']}"
    )
    assert result["end_date"] == "20260812"
    assert result["catchup"] is True
    # 모든 카테고리 스트림이 8/8 부터 시작해야 합니다
    assert all(s == "20260808" for s in captured_starts), captured_starts


# ---------------------------------------------------------------------------
# collect_bids 통합 테스트 (API 호출 없음)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_one_day_interruption_recovers(isolated_db, monkeypatch):
    """하루 중단 시나리오: 이틀 전까지 수집됐고 어제가 빠진 경우 어제만 회수합니다."""
    from datetime import datetime

    import src.app.services.collector_service as svc
    from src.app.models.bids import BidAnnouncement

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    two_days_ago = datetime(2026, 8, 11, 12, 0, 0)

    # 이틀 전 공고일 레코드를 심어 checkpoint 를 2026-08-11 로 만듭니다
    row = BidAnnouncement(
        bid_ntce_no="ANN-1DAY-GAP",
        bid_ntce_ord="001",
        category="Thng",
        bid_ntce_dt=two_days_ago,
        collected_at=fake_today,
    )
    isolated_db.add(row)
    isolated_db.commit()

    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")

    async def fake_stream_ann(start, end, flush_fn, *, category):
        return 0

    async def fake_stream_res(start, end, flush_fn, *, category):
        return 0

    monkeypatch.setattr(svc, "stream_bid_announcements", fake_stream_ann)
    monkeypatch.setattr(svc, "stream_bid_data", fake_stream_res)

    result = await svc.collect_bids(isolated_db, refresh_aggregates=False)

    assert result["start_date"] == "20260812"
    assert result["end_date"] == "20260812"
    assert result["catchup"] is True
    assert result["status"] in ("success", "partial_success", "failed")


@pytest.mark.asyncio
async def test_four_day_interruption_recovers(isolated_db, monkeypatch):
    """나흘 중단 시나리오: DB 최신 날짜가 5일 전이면 4일 창을 회수합니다."""
    from datetime import datetime

    import src.app.services.collector_service as svc
    from src.app.models.bids import BidAnnouncement

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    five_days_ago = datetime(2026, 8, 8, 12, 0, 0)

    # DB 에 5일 전 공고일을 가진 레코드를 심습니다
    row = BidAnnouncement(
        bid_ntce_no="TEST001",
        bid_ntce_ord="001",
        category="Thng",
        bid_ntce_dt=five_days_ago,
        collected_at=fake_today,
    )
    isolated_db.add(row)
    isolated_db.commit()

    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")

    captured: list[tuple] = []

    async def fake_stream_ann(start, end, flush_fn, *, category):
        captured.append(("ann", start, end))
        return 0

    async def fake_stream_res(start, end, flush_fn, *, category):
        captured.append(("res", start, end))
        return 0

    monkeypatch.setattr(svc, "stream_bid_announcements", fake_stream_ann)
    monkeypatch.setattr(svc, "stream_bid_data", fake_stream_res)

    result = await svc.collect_bids(isolated_db, refresh_aggregates=False)

    assert result["start_date"] == "20260809"
    assert result["end_date"] == "20260812"
    assert result["catchup"] is True


@pytest.mark.asyncio
async def test_same_range_rerun_is_idempotent(isolated_db, monkeypatch):
    """동일 범위 재실행 멱등성: 같은 날짜로 두 번 실행해도 상태가 같습니다."""
    from datetime import datetime

    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")

    async def fake_stream_ann(start, end, flush_fn, *, category):
        return 0

    async def fake_stream_res(start, end, flush_fn, *, category):
        return 0

    monkeypatch.setattr(svc, "stream_bid_announcements", fake_stream_ann)
    monkeypatch.setattr(svc, "stream_bid_data", fake_stream_res)

    result1 = await svc.collect_bids(
        isolated_db,
        start_date="20260810",
        end_date="20260812",
        refresh_aggregates=False,
    )
    result2 = await svc.collect_bids(
        isolated_db,
        start_date="20260810",
        end_date="20260812",
        refresh_aggregates=False,
    )

    assert result1["start_date"] == result2["start_date"]
    assert result1["end_date"] == result2["end_date"]
    assert result1["catchup"] is False
    assert result2["catchup"] is False
    assert result1["status"] == result2["status"]


@pytest.mark.asyncio
async def test_partial_failure_visible_in_metrics(isolated_db, monkeypatch):
    """부분 실패 가시성: 일부 카테고리 실패 시 categories 에 오류가 기록됩니다."""
    from datetime import datetime

    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")

    async def ok_stream_ann(start, end, flush_fn, *, category):
        if category == "Thng":
            return 5
        raise RuntimeError("API timeout")

    async def ok_stream_res(start, end, flush_fn, *, category):
        return 0

    monkeypatch.setattr(svc, "stream_bid_announcements", ok_stream_ann)
    monkeypatch.setattr(svc, "stream_bid_data", ok_stream_res)

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
    servc_cat = result["categories"].get("Servc", {})
    assert "announcement_error" in servc_cat
    thng_cat = result["categories"].get("Thng", {})
    assert thng_cat["announcement_count"] == 5


@pytest.mark.asyncio
async def test_catchup_flag_false_when_explicit_dates(isolated_db, monkeypatch):
    """명시적 날짜 지정 시 catchup=False 이며 그 날짜가 그대로 사용됩니다."""
    from datetime import datetime

    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")

    async def fake_stream_ann(start, end, flush_fn, *, category):
        return 0

    async def fake_stream_res(start, end, flush_fn, *, category):
        return 0

    monkeypatch.setattr(svc, "stream_bid_announcements", fake_stream_ann)
    monkeypatch.setattr(svc, "stream_bid_data", fake_stream_res)

    result = await svc.collect_bids(
        isolated_db,
        start_date="20260801",
        end_date="20260810",
        refresh_aggregates=False,
    )

    assert result["start_date"] == "20260801"
    assert result["end_date"] == "20260810"
    assert result["catchup"] is False
