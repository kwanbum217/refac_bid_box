"""
tests/test_intraday_collect_20261116.py

낮 시간 증분 수집 계약 테스트.

  (a) 비활성화면 skipped
  (b) 무거운 잠금이 잡혀 있으면 collect_bids 를 부르지 않고 skipped
  (c) claim 실패면 skipped
  (d) 정상 경로: 오늘 날짜·announce·refresh_aggregates=False 수집, collected_since 색인, claim 해제
  (e) cron_jobs 에 평일·주말 두 항목
  (f) 날짜 범위 해석이 오늘 공고를 체크포인트에서 제외
  (g) get_latest_collection_time 이 오늘 공고의 collected_at 을 무시

실제 DB·Redis·G2B API·Meilisearch 에 연결하지 않습니다. 시각은 고정 주입합니다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.app.core.config import settings
from src.app.models.bids import BidAnnouncement
from src.app.services.collector_service import resolve_collection_window
from src.tasks import scheduled_tasks, worker
from src.tasks.scheduled_tasks import ScheduleClaimResult, ScheduleClaimStatus
from src.tasks.worker import WorkerSettings

# KST 2026-11-16 12:00. 오늘 날짜가 20261116 이 되도록 고정합니다.
FIXED_UTC = datetime(2026, 11, 16, 3, 0, 0)
TODAY = "20261116"
# claim 소유 토큰 대역. 값 자체를 비밀번호로 오인하지 않도록 이름을 달리 둡니다.
_CLAIM_OWNER = "intraday-owner"


@pytest.fixture(autouse=True)
def _silence_schedule_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *a, **k: None)


def _claim(
    status: ScheduleClaimStatus = ScheduleClaimStatus.ACQUIRED,
    marker: str | None = _CLAIM_OWNER,
) -> ScheduleClaimResult:
    return ScheduleClaimResult(
        status=status,
        key=scheduled_tasks.SCHEDULE_COLLECTION_CLAIM_KEY,
        owner=scheduled_tasks.INTRADAY_COLLECT_SCHEDULE_NAME,
        ttl=scheduled_tasks.INTRADAY_COLLECT_CLAIM_TTL_SECONDS,
        token=marker,
    )


@pytest.mark.asyncio
async def test_disabled_skips_without_acquiring_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    """(a) 플래그가 꺼져 있으면 claim 도 잡지 않고 건너뜁니다."""
    monkeypatch.setattr(settings, "INTRADAY_COLLECT_ENABLED", False)
    acquire = MagicMock()
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", acquire)

    outcome = await scheduled_tasks.intraday_collect_task({})

    assert outcome == {"status": "skipped", "reason": "disabled"}
    acquire.assert_not_called()


@pytest.mark.asyncio
async def test_heavy_task_running_skips_without_waiting(monkeypatch: pytest.MonkeyPatch) -> None:
    """(b) 무거운 잠금이 잡혀 있으면 대기하지 않고 수집도 부르지 않습니다."""
    monkeypatch.setattr(settings, "INTRADAY_COLLECT_ENABLED", True)
    lock = asyncio.Lock()
    await lock.acquire()
    monkeypatch.setattr(worker, "get_heavy_task_lock", lambda: lock)
    acquire = MagicMock()
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", acquire)
    collect = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "collect_bids", collect)

    try:
        outcome = await scheduled_tasks.intraday_collect_task({})
    finally:
        lock.release()

    assert outcome == {"status": "skipped", "reason": "heavy_task_running"}
    acquire.assert_not_called()
    collect.assert_not_called()


@pytest.mark.asyncio
async def test_claim_failure_skips(monkeypatch: pytest.MonkeyPatch) -> None:
    """(c) 야간 수집·따라잡기가 같은 claim 키를 잡고 있으면 skipped 입니다."""
    monkeypatch.setattr(settings, "INTRADAY_COLLECT_ENABLED", True)
    monkeypatch.setattr(worker, "get_heavy_task_lock", lambda: asyncio.Lock())
    acquire = MagicMock(return_value=_claim(ScheduleClaimStatus.ALREADY_CLAIMED, marker=None))
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", acquire)
    collect = AsyncMock()
    monkeypatch.setattr(scheduled_tasks, "collect_bids", collect)

    outcome = await scheduled_tasks.intraday_collect_task({})

    assert outcome["status"] == "skipped"
    assert outcome["reason"] == "already_claimed"
    assert acquire.call_args.kwargs["key"] == scheduled_tasks.SCHEDULE_COLLECTION_CLAIM_KEY
    assert acquire.call_args.kwargs["ttl_seconds"] == 1800
    collect.assert_not_called()


@pytest.mark.asyncio
async def test_success_collects_today_and_indexes_this_round(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """(d) 오늘 공고만 수집하고 이번 회차 적재분만 색인한 뒤 claim 을 해제합니다."""
    monkeypatch.setattr(settings, "INTRADAY_COLLECT_ENABLED", True)
    monkeypatch.setattr(settings, "MEILI_ENABLED", True)
    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: FIXED_UTC)
    monkeypatch.setattr(worker, "get_heavy_task_lock", lambda: asyncio.Lock())

    acquire = MagicMock(return_value=_claim())
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", acquire)
    release = MagicMock()
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", release)
    fake_session = SimpleNamespace(close=lambda: None)
    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: fake_session)

    collect = AsyncMock(
        return_value={
            "status": "success",
            "announcement_count": 931,
            "license_limit_count": 3,
            "participation_region_count": 4,
        }
    )
    monkeypatch.setattr(scheduled_tasks, "collect_bids", collect)
    sync = MagicMock(return_value={"announcements": 931, "results": 0})
    monkeypatch.setattr("src.app.services.search_index.sync_search_index", sync)

    outcome = await scheduled_tasks.intraday_collect_task({})

    assert outcome["status"] == "success"
    assert outcome["start_date"] == TODAY
    assert outcome["announcement_count"] == 931
    assert outcome["indexed"] == {"announcements": 931, "results": 0}

    collect.assert_awaited_once()
    collect_kwargs = collect.await_args.kwargs
    assert collect_kwargs["start_date"] == TODAY
    assert collect_kwargs["end_date"] == TODAY
    assert collect_kwargs["fetch_type"] == "announce"
    assert collect_kwargs["refresh_aggregates"] is False

    sync.assert_called_once()
    assert sync.call_args.kwargs["collected_since"] == FIXED_UTC

    release.assert_called_once()
    assert release.call_args.args[0] == scheduled_tasks.SCHEDULE_COLLECTION_CLAIM_KEY
    assert release.call_args.kwargs["token"] == _CLAIM_OWNER


@pytest.mark.asyncio
async def test_failure_still_releases_claim(monkeypatch: pytest.MonkeyPatch) -> None:
    """수집 예외가 나도 claim 은 finally 에서 해제됩니다."""
    monkeypatch.setattr(settings, "INTRADAY_COLLECT_ENABLED", True)
    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: FIXED_UTC)
    monkeypatch.setattr(worker, "get_heavy_task_lock", lambda: asyncio.Lock())
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", MagicMock(return_value=_claim()))
    release = MagicMock()
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", release)
    monkeypatch.setattr(
        scheduled_tasks, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )
    monkeypatch.setattr(
        scheduled_tasks,
        "collect_bids",
        AsyncMock(side_effect=RuntimeError("G2B 응답 없음")),
    )

    outcome = await scheduled_tasks.intraday_collect_task({})

    assert outcome["status"] == "failed"
    assert "G2B 응답 없음" in str(outcome.get("error"))
    release.assert_called_once()


def _intraday_crons() -> list:
    return [job for job in WorkerSettings.cron_jobs if job.name.endswith("intraday_collect_task")]


def test_cron_jobs_register_weekday_and_weekend_rounds() -> None:
    """(e) 평일 07~20시 매시 10분, 주말 12시 10분 두 항목이 3600초로 등록됩니다."""
    jobs = _intraday_crons()
    assert len(jobs) == 2

    weekday_job = next(job for job in jobs if job.weekday == {0, 1, 2, 3, 4})
    assert weekday_job.hour == set(range(7, 21))
    assert weekday_job.minute == 10
    assert weekday_job.timeout_s == 3600
    assert weekday_job.run_at_startup is False

    weekend_job = next(job for job in jobs if job.weekday == {5, 6})
    assert weekend_job.hour == 12
    assert weekend_job.minute == 10
    assert weekend_job.timeout_s == 3600
    assert weekend_job.run_at_startup is False

    assert scheduled_tasks.intraday_collect_task in WorkerSettings.functions


def test_resolve_window_ignores_today_from_checkpoint(isolated_db) -> None:
    """(f) 오늘 낮 수집분이 체크포인트를 올려 빠진 날을 건너뛰게 하지 않습니다."""
    isolated_db.add_all(
        [
            BidAnnouncement(
                bid_ntce_no="ANN-OLD",
                bid_ntce_ord="001",
                category="Thng",
                bid_ntce_dt=datetime(2026, 11, 13, 12, 0, 0),
                collected_at=datetime(2026, 11, 13, 3, 0, 0),
            ),
            BidAnnouncement(
                bid_ntce_no="ANN-TODAY",
                bid_ntce_ord="001",
                category="Thng",
                bid_ntce_dt=datetime(2026, 11, 16, 9, 0, 0),
                collected_at=datetime(2026, 11, 16, 0, 30, 0),
            ),
        ]
    )
    isolated_db.commit()

    with patch("src.app.services.collector_service.utcnow", return_value=FIXED_UTC):
        start, end, is_catchup = resolve_collection_window(
            isolated_db,
            start_date=None,
            end_date=None,
            fetch_type="announce",
        )

    # 오늘 행을 세면 latest=11-16 이 되어 11-14, 11-15 가 영영 빠집니다.
    assert (start, end, is_catchup) == ("20261114", "20261115", True)


def test_latest_collection_time_ignores_today(isolated_db, monkeypatch: pytest.MonkeyPatch) -> None:
    """(g) 오늘 공고의 collected_at 은 야간 슬롯 누락 판정에 쓰이지 않습니다."""
    old_collected = datetime(2026, 11, 15, 23, 0, 0)
    isolated_db.add_all(
        [
            BidAnnouncement(
                bid_ntce_no="ANN-OLD",
                bid_ntce_ord="001",
                category="Thng",
                bid_ntce_dt=datetime(2026, 11, 15, 12, 0, 0),
                collected_at=old_collected,
            ),
            BidAnnouncement(
                bid_ntce_no="ANN-TODAY",
                bid_ntce_ord="001",
                category="Thng",
                bid_ntce_dt=datetime(2026, 11, 16, 9, 0, 0),
                collected_at=datetime(2026, 11, 16, 0, 30, 0),
            ),
        ]
    )
    isolated_db.commit()

    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: FIXED_UTC)

    assert scheduled_tasks.get_latest_collection_time(isolated_db) == old_collected


def test_latest_collection_time_is_none_when_only_today(
    isolated_db, monkeypatch: pytest.MonkeyPatch
) -> None:
    """오늘 공고만 있으면 야간 체크포인트는 없는 것으로 봅니다."""
    isolated_db.add(
        BidAnnouncement(
            bid_ntce_no="ANN-TODAY",
            bid_ntce_ord="001",
            category="Thng",
            bid_ntce_dt=datetime(2026, 11, 16, 9, 0, 0),
            collected_at=datetime(2026, 11, 16, 0, 30, 0),
        )
    )
    isolated_db.commit()

    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: FIXED_UTC)

    assert scheduled_tasks.get_latest_collection_time(isolated_db) is None
