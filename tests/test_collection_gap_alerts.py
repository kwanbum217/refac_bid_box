"""
tests/test_collection_gap_alerts.py

수집 공백 알림 계약 테스트.
  - 클램프(공백이 자동 회수 상한 초과) 발생을 clamp_events 로 호출부에 전달
  - collect_bids 가 클램프 발생 시 notify_collection_window_clamped 를 발신
  - run_schedule_catchup_task 가 실행 공백 72시간 이상에서 notify_collection_gap 발신
알림 실패는 수집을 되돌리지 않습니다. 외부 G2B API 호출은 없습니다.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.app.core.cache import RedisConnection
from src.app.core.config import settings
from src.app.services.collector_service import MAX_CATCHUP_DAYS, resolve_collection_window
from src.tasks import notifier, scheduled_tasks
from src.tasks.scheduled_tasks import COLLECTION_GAP_ALERT_HOURS, run_schedule_catchup_task
from tests.fake_redis import FakeRedisClient, FakeRedisConnection


class UnreachableRedisConnection(RedisConnection):
    def __init__(self, label: str = "test_unreachable") -> None:
        super().__init__(label=label)

    def client(self) -> Any:
        return None

    def invalidate(self, exc: Exception) -> None:
        pass


@pytest.fixture(autouse=True)
def isolate_schedule_redis():
    """실제 Redis 와의 결합 및 테스트 순서 의존성을 방지합니다."""
    fake_conn = FakeRedisConnection(FakeRedisClient())
    scheduled_tasks.set_schedule_redis_conn(fake_conn)
    yield fake_conn
    scheduled_tasks.set_schedule_redis_conn(None)


def _make_db(ann_min_of_max: datetime | None, res_min_of_max: datetime | None):
    """categories=None 경로 전용 모의 세션 (test_collector_catchup 과 동일 방식)."""

    class FakeSession:
        def __init__(self):
            self._queue: list[datetime | None] = [ann_min_of_max, res_min_of_max]

        def scalar(self, _stmt):
            return self._queue.pop(0) if self._queue else None

    return FakeSession()


def _utcnow_fixed(fake_today: datetime):
    return patch("src.app.services.collector_service.utcnow", return_value=fake_today)


# ---------------------------------------------------------------------------
# (a)(b) resolve_collection_window clamp_events 기록
# ---------------------------------------------------------------------------


class TestClampEvents:
    def test_gap_exceeding_limit_records_clamp_event(self):
        """(a) 공백이 상한을 넘으면 clamp_events 에 항목 하나가 기록되고
        반환 창은 기존(클램프) 동작과 같습니다."""
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        thirty_days_ago = datetime(2026, 7, 14, 12, 0, 0)
        db = _make_db(thirty_days_ago, thirty_days_ago)
        clamp_events: list[dict[str, Any]] = []

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db,
                start_date=None,
                end_date=None,
                fetch_type="both",
                clamp_events=clamp_events,
            )

        yesterday = (fake_today - timedelta(days=1)).date()
        expected_start = (yesterday - timedelta(days=MAX_CATCHUP_DAYS - 1)).strftime("%Y%m%d")
        assert start == expected_start
        assert end == yesterday.strftime("%Y%m%d")
        assert is_catchup is True

        assert len(clamp_events) == 1
        event = clamp_events[0]
        assert event["days_missing"] == 29
        assert event["max_catchup_days"] == MAX_CATCHUP_DAYS
        assert event["lost_start"] == "20260715"
        assert event["lost_end"] == "20260805"
        assert event["recovered_start"] == "20260806"

    def test_gap_within_limit_records_nothing(self):
        """(b) 상한 이내 공백에서는 clamp_events 가 비어 있습니다."""
        fake_today = datetime(2026, 8, 13, 10, 0, 0)
        five_days_ago = datetime(2026, 8, 8, 12, 0, 0)
        db = _make_db(five_days_ago, five_days_ago)
        clamp_events: list[dict[str, Any]] = []

        with _utcnow_fixed(fake_today):
            start, end, is_catchup = resolve_collection_window(
                db,
                start_date=None,
                end_date=None,
                fetch_type="both",
                clamp_events=clamp_events,
            )

        assert start == "20260809"
        assert end == "20260812"
        assert is_catchup is True
        assert clamp_events == []


# ---------------------------------------------------------------------------
# (c) collect_bids 클램프 알림 발신
# ---------------------------------------------------------------------------


def _seed_ann(db, cat: str, dt: datetime) -> None:
    from src.app.models.bids import BidAnnouncement

    db.add(
        BidAnnouncement(
            bid_ntce_no=f"ANN-{cat}-{dt.strftime('%m%d')}",
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
            bid_ntce_no=f"RES-{cat}-{dt.strftime('%m%d')}",
            bid_ntce_ord="001",
            category=cat,
            rl_openg_dt=dt,
            collected_at=dt,
        )
    )


@pytest.mark.asyncio
async def test_collect_bids_sends_clamp_notification(isolated_db, monkeypatch):
    """(c) collect_bids 경로에서 클램프가 나면 notify_collection_window_clamped 가
    한 번 호출되고 metrics 에 window_clamp 가 기록됩니다."""
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    thirty_days_ago = datetime(2026, 7, 14, 12, 0, 0)
    _seed_ann(isolated_db, "Thng", thirty_days_ago)
    _seed_res(isolated_db, "Thng", thirty_days_ago)
    isolated_db.commit()

    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=0))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))
    mock_notify = AsyncMock()
    monkeypatch.setattr(notifier, "notify_collection_window_clamped", mock_notify)

    result = await svc.collect_bids(
        isolated_db,
        categories=("Thng",),
        refresh_aggregates=False,
    )

    mock_notify.assert_awaited_once()
    event = mock_notify.await_args.args[0]
    assert event["lost_start"] == "20260715"
    assert result["window_clamp"] == event
    assert result["status"] in ("success", "partial_success", "failed")


@pytest.mark.asyncio
async def test_collect_bids_swallows_notification_failure(isolated_db, monkeypatch):
    """알림 발신이 실패해도 수집 결과는 그대로입니다."""
    import src.app.services.collector_service as svc

    fake_today = datetime(2026, 8, 13, 10, 0, 0)
    thirty_days_ago = datetime(2026, 7, 14, 12, 0, 0)
    _seed_ann(isolated_db, "Thng", thirty_days_ago)
    _seed_res(isolated_db, "Thng", thirty_days_ago)
    isolated_db.commit()

    monkeypatch.setattr(svc, "utcnow", lambda: fake_today)
    monkeypatch.setattr(svc, "get_service_key", lambda: "dummy-key")
    monkeypatch.setattr(svc, "stream_bid_announcements", AsyncMock(return_value=0))
    monkeypatch.setattr(svc, "stream_bid_data", AsyncMock(return_value=0))
    monkeypatch.setattr(
        notifier,
        "notify_collection_window_clamped",
        AsyncMock(side_effect=RuntimeError("webhook down")),
    )

    result = await svc.collect_bids(
        isolated_db,
        categories=("Thng",),
        refresh_aggregates=False,
    )

    assert result["status"] in ("success", "partial_success", "failed")
    assert "window_clamp" in result


# ---------------------------------------------------------------------------
# (d)(e) run_schedule_catchup_task 실행 공백 알림
# ---------------------------------------------------------------------------


def _patch_catchup_needed(monkeypatch, elapsed_hours: float) -> None:
    monkeypatch.setattr(
        scheduled_tasks,
        "check_schedule_catchup_needed",
        lambda db=None: (
            True,
            "missed_schedule",
            {
                "target_task": "development_data_refresh",
                "elapsed_hours": elapsed_hours,
                "latest_collected_at": "2026-09-01T12:00:00+00:00",
            },
        ),
    )


@pytest.mark.asyncio
async def test_catchup_task_notifies_collection_gap_at_72h(monkeypatch):
    """(d) elapsed_hours 가 72 이상이면 notify_collection_gap 이 한 번 발신됩니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    _patch_catchup_needed(monkeypatch, 72.0)
    mock_gap = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "notify_collection_gap", mock_gap)
    monkeypatch.setattr(
        scheduled_tasks,
        "development_data_refresh_task",
        AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]}),
    )

    outcome = await run_schedule_catchup_task({})

    assert outcome["status"] == "success"
    mock_gap.assert_awaited_once_with(72.0, "2026-09-01T12:00:00+00:00")


@pytest.mark.asyncio
async def test_catchup_task_skips_collection_gap_below_72h(monkeypatch):
    """(d) elapsed_hours 가 71 이면 notify_collection_gap 이 발신되지 않습니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    _patch_catchup_needed(monkeypatch, 71.0)
    mock_gap = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "notify_collection_gap", mock_gap)
    monkeypatch.setattr(
        scheduled_tasks,
        "development_data_refresh_task",
        AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]}),
    )

    outcome = await run_schedule_catchup_task({})

    assert outcome["status"] == "success"
    mock_gap.assert_not_awaited()


@pytest.mark.asyncio
async def test_catchup_task_survives_notification_failure(monkeypatch):
    """(e) 알림 함수가 예외를 던져도 태스크 결과가 바뀌지 않습니다."""
    monkeypatch.setattr(settings, "AUTOMATION_SCHEDULE_CATCHUP_ENABLED", True)
    _patch_catchup_needed(monkeypatch, 80.0)
    monkeypatch.setattr(
        scheduled_tasks,
        "notify_collection_gap",
        AsyncMock(side_effect=RuntimeError("webhook down")),
    )
    monkeypatch.setattr(
        scheduled_tasks,
        "development_data_refresh_task",
        AsyncMock(return_value={"status": "success", "completed_steps": ["collect"]}),
    )

    outcome = await run_schedule_catchup_task({})

    assert outcome["status"] == "success"


# ---------------------------------------------------------------------------
# 알림 본문 계약
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_clamp_notification_body_carries_lost_range_and_backfill_hint():
    """클램프 알림은 누락 구간과 백필 명령 안내를 level action 으로 담습니다."""
    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    with patch.object(notifier, "notify", fake_notify):
        await notifier.notify_collection_window_clamped(
            {
                "days_missing": 29,
                "max_catchup_days": 7,
                "lost_start": "20260715",
                "lost_end": "20260805",
                "recovered_start": "20260806",
            }
        )

    assert len(sent) == 1
    _title, lines, level = sent[0]
    assert level == "action"
    body = "\n".join(lines)
    assert "20260715" in body
    assert "20260805" in body
    assert "uv run python scripts/backfill_from_g2b.py" in body


@pytest.mark.asyncio
async def test_collection_gap_notification_is_warning_level():
    """실행 공백 알림은 level warning 으로 발신됩니다."""
    sent: list[tuple[str, list[str], str]] = []

    async def fake_notify(title, lines, *, level="info"):
        sent.append((title, lines, level))

    with patch.object(notifier, "notify", fake_notify):
        await notifier.notify_collection_gap(72.5, "2026-09-01T12:00:00+00:00")

    assert len(sent) == 1
    _, lines, level = sent[0]
    assert level == "warning"
    assert "72.5시간" in "\n".join(lines)


def test_collection_gap_alert_threshold_is_72():
    """실행 공백 알림 임계는 3일(72시간)입니다."""
    assert COLLECTION_GAP_ALERT_HOURS == 72
