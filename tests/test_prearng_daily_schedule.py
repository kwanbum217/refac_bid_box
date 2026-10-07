"""
tests/test_prearng_daily_schedule.py

용역 예비가격 일일 증분 수집(핸드오프 17번) 검증.

막으려는 사고:
  - 신규 용역 공고가 아닌 과거 공고를 증분 경로로 끌어와 소급 수집이 되는 것
  - 이미 적재된 공고를 다시 조회해 같은 공고를 반복 수집하는 것
  - 일일 증분 태스크가 worker cron 에 등록되지 않아 영영 돌지 않는 것
  - 부분 실패를 성공으로 보고해 실패 공고가 조용히 누락되는 것

나라장터 API 와 DB 는 대역(double)으로 대체하며 실호출과 운영 DB 쓰기를 하지 않습니다.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import timedelta
from typing import Any

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from src.app.core.db import Base
from src.app.core.timeutil import utcnow
from src.app.models.bids import BidAnnouncement
from src.app.models.prearng_prices import BidPrearngPrice
from src.app.services.api_collector import RangeCollectionError
from src.tasks import scheduled_tasks
from src.tasks.scheduled_tasks import (
    PREARNG_DAILY_HOUR,
    PREARNG_DAILY_JOB_TIMEOUT_SECONDS,
    PREARNG_DAILY_MINUTE,
    PREARNG_DAILY_SCHEDULE_NAME,
    prearng_daily_task,
    select_new_servc_notices,
)
from src.tasks.worker import WorkerSettings


class _FakeSession:
    """close 만 있는 DB 세션 대역."""

    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


@pytest.fixture
def fake_env(monkeypatch):
    """세션과 스케줄 기록을 대역으로 바꾼 환경을 돌려줍니다."""
    session = _FakeSession()
    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: session)
    recorded: dict[str, Any] = {"inserted": [], "records": []}

    def _record(schedule_name: str, outcome: Any, success: bool) -> None:
        recorded["records"].append((schedule_name, outcome, success))

    monkeypatch.setattr("src.tasks.worker.record_schedule_result", _record)
    return session, recorded


# ============================================================================
# 1. 신규 공고 선택 (DB 대역: SQLite 인메모리)
# ============================================================================


@pytest.fixture
def announcement_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(
        engine,
        tables=[BidAnnouncement.__table__, BidPrearngPrice.__table__],
    )
    factory = sessionmaker(bind=engine)
    session = factory()
    try:
        yield session
    finally:
        session.close()
        engine.dispose()


_UNSET = object()


def _add_announcement(
    session,
    notice_no: str,
    *,
    category: str = "Servc",
    openg_dt=_UNSET,
) -> None:
    session.add(
        BidAnnouncement(
            bid_ntce_no=notice_no,
            category=category,
            openg_dt=utcnow() if openg_dt is _UNSET else openg_dt,
        )
    )


def _add_prearng(session, notice_no: str) -> None:
    session.add(
        BidPrearngPrice(
            bid_ntce_no=notice_no,
            bid_ntce_ord="000",
            bid_clsfc_no="0",
            rbid_no="000",
            category="Servc",
            collected_at=utcnow(),
        )
    )


def test_select_new_servc_notices_filters_and_excludes_collected(announcement_session) -> None:
    session = announcement_session
    now = utcnow()
    recent = now - timedelta(days=1)
    _add_announcement(session, "R-NEW", openg_dt=recent)
    _add_announcement(session, "R-COLLECTED", openg_dt=recent)
    _add_announcement(session, "R-OLD", openg_dt=now - timedelta(days=30))
    _add_announcement(session, "T-NEW", category="Thng", openg_dt=recent)
    _add_announcement(session, "R-NO-OPEN", openg_dt=None)
    _add_prearng(session, "R-COLLECTED")
    session.commit()

    result = select_new_servc_notices(session, now=now)

    assert result == ["R-NEW"]


def test_select_new_servc_notices_respects_limit(announcement_session) -> None:
    session = announcement_session
    now = utcnow()
    for index in range(5):
        _add_announcement(session, f"R-{index:03d}", openg_dt=now - timedelta(days=1))
    session.commit()

    result = select_new_servc_notices(session, now=now, limit=2)

    assert len(result) == 2
    assert result == sorted(result)


# ============================================================================
# 2. 일일 증분 태스크 (API·DB 대역)
# ============================================================================


@pytest.mark.asyncio
async def test_daily_task_forwards_selected_notices_and_persists(monkeypatch, fake_env) -> None:
    session, recorded = fake_env
    notices = ["R25BK000001", "R25BK000002"]
    monkeypatch.setattr(scheduled_tasks, "select_new_servc_notices", lambda db: notices)

    calls: dict[str, Any] = {}

    async def _fake_stream(notice_list, sink, num_of_rows=500):
        calls["notices"] = list(notice_list)
        rows = [{"bid_ntce_no": "R25BK000001", "category": "Servc"}]
        return sink(rows)

    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _fake_stream)

    def _fake_bulk_insert(db, model, rows):
        recorded["inserted"].append((db, model, rows))
        return len(rows)

    monkeypatch.setattr(scheduled_tasks, "_bulk_insert", _fake_bulk_insert)

    outcome = await prearng_daily_task({})

    assert outcome == {"status": "success", "notice_count": 2, "saved": 1}
    assert calls["notices"] == notices
    db, model, rows = recorded["inserted"][0]
    assert db is session
    assert model is BidPrearngPrice
    assert rows[0]["bid_ntce_no"] == "R25BK000001"
    assert session.closed is True
    assert recorded["records"][0][0] == PREARNG_DAILY_SCHEDULE_NAME
    assert recorded["records"][0][2] is True


@pytest.mark.asyncio
async def test_daily_task_creates_sessions_inside_worker_threads(monkeypatch) -> None:
    """조회·적재 세션이 이벤트 루프가 아니라 to_thread 작업 스레드에서 만들어지는지 검증한다."""
    loop_thread = threading.get_ident()
    created_in: list[int] = []

    class _Session:
        def close(self) -> None:
            pass

    def _session_factory():
        created_in.append(threading.get_ident())
        return _Session()

    monkeypatch.setattr(scheduled_tasks, "SessionLocal", _session_factory)
    monkeypatch.setattr(scheduled_tasks, "select_new_servc_notices", lambda db: ["R1"])
    monkeypatch.setattr(scheduled_tasks, "_bulk_insert", lambda db, model, rows: len(rows))
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *args, **kwargs: None)

    async def _fake_stream(notice_list, sink, num_of_rows=500):
        rows = [{"bid_ntce_no": "R1", "category": "Servc"}]
        return await asyncio.to_thread(sink, rows)

    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _fake_stream)

    outcome = await prearng_daily_task({})

    assert outcome == {"status": "success", "notice_count": 1, "saved": 1}
    assert len(created_in) == 2
    assert all(thread_id != loop_thread for thread_id in created_in)


@pytest.mark.asyncio
async def test_daily_task_skips_when_no_new_notices(monkeypatch, fake_env) -> None:
    _session, recorded = fake_env
    monkeypatch.setattr(scheduled_tasks, "select_new_servc_notices", lambda db: [])

    async def _fail(*args, **kwargs):
        raise AssertionError("신규 공고가 없으면 나라장터를 호출하지 않아야 합니다")

    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _fail)

    outcome = await prearng_daily_task({})

    assert outcome == {"status": "skipped", "reason": "no_new_notices", "notice_count": 0}
    assert recorded["records"][0][2] is True


@pytest.mark.asyncio
async def test_daily_task_reports_partial_failure(monkeypatch, fake_env) -> None:
    _session, recorded = fake_env
    monkeypatch.setattr(scheduled_tasks, "select_new_servc_notices", lambda db: ["R1", "R2"])

    async def _fake_stream(notice_list, sink, num_of_rows=500):
        raise RangeCollectionError("예비가격상세", 1, [("R2", "R2")])

    monkeypatch.setattr(scheduled_tasks, "stream_servc_prearng_by_notices", _fake_stream)

    outcome = await prearng_daily_task({})

    assert outcome["status"] == "partial_failure"
    assert outcome["notice_count"] == 2
    assert outcome["saved"] == 1
    assert outcome["failed_notices"] == ["R2"]
    assert recorded["records"][0][2] is False


# ============================================================================
# 3. worker cron 등록
# ============================================================================


def _contains(value: Any, expected: int) -> bool:
    if isinstance(value, (set, frozenset, list, tuple)):
        return expected in value
    return value == expected


def _cron_job_for(name: str):
    for job in WorkerSettings.cron_jobs:
        target = getattr(job, "coroutine", job)
        if getattr(target, "__name__", "") == name:
            return job
    return None


def test_prearng_daily_task_registered_in_worker_cron() -> None:
    job = _cron_job_for("prearng_daily_task")

    assert job is not None
    assert _contains(job.hour, PREARNG_DAILY_HOUR)
    assert _contains(job.minute, PREARNG_DAILY_MINUTE)
    assert job.timeout_s == PREARNG_DAILY_JOB_TIMEOUT_SECONDS
