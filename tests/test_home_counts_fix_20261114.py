"""
tests/test_home_counts_fix_20261114.py

메인 화면(/) 무응답 결함 수정 계약을 고정합니다.

막으려는 사고:
  - 요청 경로가 365일·입찰 중 건수를 동기 집계해 응답이 수 분 멈추는 것
  - 집계 질의가 bid_announcements 전체에 row_number() 를 계산하는 것
  - 범위를 좁힌 최신 차수 판정이 기존 정의와 다른 건수를 내는 것
  - worker 정기 작업이 캐시를 미리 채우지 않아 화면이 계속 '집계 중' 인 것

실제 MySQL·Redis 에 연결하지 않고 SQLite 와 가짜 캐시를 씁니다.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import event, func, select

from src.app.core.security import SESSION_COOKIE_NAME, create_session
from src.app.core.timeutil import utcnow
from src.app.main import app
from src.app.models.accounts import CustomUser
from src.app.models.bids import BidAnnouncement
from src.app.services import home_summary
from src.app.services.bid_queries import latest_announcement_filter
from src.tasks import scheduled_tasks
from src.tasks.worker import WorkerSettings

BASE_TIME = datetime(2026, 11, 14, 12, 0, 0)

# 예열 주기(10분)의 12배. 요청 경로가 캐시를 읽는 동안 예열이 한두 번 실패해도
# 화면이 비지 않아야 합니다.
EXPECTED_CACHE_TTL = 7200


class FakeCache:
    """조회 캐시 대역. Redis 와 프로세스 로컬 저장소를 쓰지 않습니다."""

    def __init__(self, initial: dict[str, Any] | None = None) -> None:
        self._store: dict[str, Any] = dict(initial or {})
        self.sets: list[tuple[str, Any, int]] = []

    def get(self, key: str) -> Any:
        return self._store.get(key)

    def set(self, key: str, value: Any, ttl: int) -> None:
        self._store[key] = value
        self.sets.append((key, value, ttl))

    def delete(self, key: str) -> None:
        self._store.pop(key, None)


@pytest.fixture
def fake_cache(monkeypatch):
    cache = FakeCache()
    monkeypatch.setattr(home_summary, "cache", cache)
    return cache


def _add(db, **overrides) -> BidAnnouncement:
    payload: dict[str, Any] = {
        "bid_ntce_no": "ANN-BASE",
        "bid_ntce_ord": "000",
        "bid_ntce_nm": "기준 공고",
        "dminstt_nm": "테스트발주기관",
        "category": "Servc",
        "bid_ntce_dt": BASE_TIME - timedelta(days=1),
        "bid_clse_dt": BASE_TIME + timedelta(days=1),
        "collected_at": BASE_TIME,
    }
    payload.update(overrides)
    row = BidAnnouncement(**payload)
    db.add(row)
    db.commit()
    return row


def _legacy_count(db, *conditions) -> int:
    stmt = select(func.count()).select_from(BidAnnouncement).where(*conditions)
    return int(db.scalar(latest_announcement_filter(stmt)) or 0)


# --------------------------------------------------------------------------- #
# (1) 건수 정의 동일성
# --------------------------------------------------------------------------- #


@pytest.fixture
def mixed_announcements(isolated_db):
    """차수·업무구분·기간이 섞인 픽스처를 만들고 두 기준 건수를 돌려줍니다."""
    # 최신 차수가 365일 안쪽인 공고: 2개 차수 중 최신만 1건
    _add(
        isolated_db,
        bid_ntce_no="MIX-OPEN",
        bid_ntce_ord="000",
        bid_ntce_dt=BASE_TIME - timedelta(days=30),
        bid_clse_dt=BASE_TIME + timedelta(days=3),
    )
    _add(
        isolated_db,
        bid_ntce_no="MIX-OPEN",
        bid_ntce_ord="001",
        bid_ntce_dt=BASE_TIME - timedelta(days=10),
        bid_clse_dt=BASE_TIME + timedelta(days=5),
    )
    # 최신 차수가 365일 밖이면 이전 차수가 안쪽이어도 세지 않는다
    _add(
        isolated_db,
        bid_ntce_no="MIX-LATEST-OLD",
        bid_ntce_ord="000",
        bid_ntce_dt=BASE_TIME - timedelta(days=300),
        bid_clse_dt=BASE_TIME + timedelta(days=1),
    )
    _add(
        isolated_db,
        bid_ntce_no="MIX-LATEST-OLD",
        bid_ntce_ord="001",
        bid_ntce_dt=BASE_TIME - timedelta(days=400),
        bid_clse_dt=BASE_TIME + timedelta(days=1),
    )
    # 최신 차수만 마감된 공고: 365일에는 들고 입찰 중에는 들지 않는다
    _add(
        isolated_db,
        bid_ntce_no="MIX-CLOSED",
        bid_ntce_ord="001",
        bid_ntce_dt=BASE_TIME - timedelta(days=20),
        bid_clse_dt=BASE_TIME - timedelta(days=1),
    )
    # 같은 공고번호의 다른 업무구분은 독립 그룹이다
    _add(
        isolated_db,
        bid_ntce_no="MIX-CATEGORY",
        category="Thng",
        bid_ntce_ord="001",
        bid_ntce_dt=BASE_TIME - timedelta(days=5),
        bid_clse_dt=BASE_TIME + timedelta(days=4),
    )
    _add(
        isolated_db,
        bid_ntce_no="MIX-CATEGORY",
        category="Servc",
        bid_ntce_ord="000",
        bid_ntce_dt=BASE_TIME - timedelta(days=30),
        bid_clse_dt=BASE_TIME + timedelta(days=4),
    )
    # 공고일시가 비어 있는 행: 기간 조건에서 빠진다
    _add(
        isolated_db,
        bid_ntce_no="MIX-NULL-DT",
        bid_ntce_dt=None,
        bid_clse_dt=BASE_TIME + timedelta(days=2),
    )

    recent_condition = (
        BidAnnouncement.category == home_summary.SERVC_CATEGORY,
        BidAnnouncement.bid_ntce_dt >= BASE_TIME - timedelta(days=home_summary.RECENT_YEAR_DAYS),
    )
    open_condition = (
        BidAnnouncement.category == home_summary.SERVC_CATEGORY,
        BidAnnouncement.bid_clse_dt >= BASE_TIME,
        BidAnnouncement.bid_ntce_dt
        >= BASE_TIME - timedelta(days=home_summary.OPEN_BID_LOOKBACK_DAYS),
    )
    return {
        "legacy_recent_year": _legacy_count(isolated_db, *recent_condition),
        "legacy_open": _legacy_count(isolated_db, *open_condition),
    }


def test_counts_match_latest_announcement_filter_definitions(isolated_db, mixed_announcements):
    recent_year = home_summary._count_recent_year_servc(isolated_db, BASE_TIME)
    open_count = home_summary._count_open_servc(isolated_db, BASE_TIME)

    assert recent_year == mixed_announcements["legacy_recent_year"]
    assert open_count == mixed_announcements["legacy_open"]
    # 픽스처가 공허하지 않음: MIX-OPEN(최신), MIX-CLOSED, MIX-CATEGORY(Servc)
    assert recent_year == 3
    # 입찰 중: MIX-OPEN(최신) + MIX-CATEGORY(Servc)
    assert open_count == 2


def test_count_queries_do_not_use_window_function(isolated_db, mixed_announcements):
    statements: list[str] = []

    def record(conn, cursor, statement, parameters, context, executemany) -> None:
        statements.append(statement)

    connection = isolated_db.get_bind()
    event.listen(connection, "before_cursor_execute", record)
    try:
        home_summary._count_recent_year_servc(isolated_db, BASE_TIME)
        home_summary._count_open_servc(isolated_db, BASE_TIME)
    finally:
        event.remove(connection, "before_cursor_execute", record)

    assert statements
    assert all("row_number" not in statement.lower() for statement in statements)


# --------------------------------------------------------------------------- #
# (2) 요청 경로는 집계하지 않는다
# --------------------------------------------------------------------------- #


def test_request_path_does_not_aggregate_without_cache(isolated_db, fake_cache, monkeypatch):
    def _fail(*args: Any, **kwargs: Any):
        raise AssertionError("요청 경로에서 대형 건수 집계를 실행했습니다")

    monkeypatch.setattr(home_summary, "_count_recent_year_servc", _fail)
    monkeypatch.setattr(home_summary, "_count_open_servc", _fail)

    summary = home_summary.get_home_summary(isolated_db, None)

    assert summary["recent_year_count"] is None
    assert summary["open_count"] is None
    assert fake_cache.sets == []


# --------------------------------------------------------------------------- #
# (3) 캐시가 있으면 그 값을 쓴다
# --------------------------------------------------------------------------- #


def test_request_path_reads_cached_counts(isolated_db, fake_cache, monkeypatch):
    fake_cache.set(
        home_summary.SERVIC_COUNTS_CACHE_KEY,
        {"recent_year_count": 4321, "open_count": 87},
        EXPECTED_CACHE_TTL,
    )

    def _fail(*args: Any, **kwargs: Any):
        raise AssertionError("캐시가 있는데 집계를 실행했습니다")

    monkeypatch.setattr(home_summary, "_count_recent_year_servc", _fail)
    monkeypatch.setattr(home_summary, "_count_open_servc", _fail)

    summary = home_summary.get_home_summary(isolated_db, None)

    assert summary["recent_year_count"] == 4321
    assert summary["open_count"] == 87


# --------------------------------------------------------------------------- #
# (4) 예열 작업이 긴 수명 캐시를 채운다
# --------------------------------------------------------------------------- #


def test_warm_task_fills_cache_with_long_ttl(isolated_db, fake_cache):
    _add(isolated_db, bid_ntce_no="WARM-OPEN")

    counts = home_summary.warm_home_summary_cache(isolated_db)

    assert counts == {"recent_year_count": 1, "open_count": 1}
    assert home_summary.SERVIC_COUNTS_CACHE_TTL == EXPECTED_CACHE_TTL
    key, value, ttl = fake_cache.sets[-1]
    assert key == home_summary.SERVIC_COUNTS_CACHE_KEY
    assert value == {"recent_year_count": 1, "open_count": 1}
    assert ttl == EXPECTED_CACHE_TTL


def test_warm_schedule_task_returns_counts(isolated_db, fake_cache, monkeypatch):
    _add(isolated_db, bid_ntce_no="WARM-TASK")
    monkeypatch.setattr(scheduled_tasks, "SessionLocal", lambda: isolated_db)
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", lambda owner, **kwargs: _claim())

    outcome = asyncio.run(scheduled_tasks.warm_home_summary_task({}))

    assert outcome == {"status": "success", "recent_year_count": 1, "open_count": 1}
    assert fake_cache.sets[-1][2] == EXPECTED_CACHE_TTL


def _claim(**overrides) -> Any:
    payload: dict[str, Any] = {
        "status": scheduled_tasks.ScheduleClaimStatus.ACQUIRED,
        "key": scheduled_tasks.HOME_SUMMARY_WARM_CLAIM_KEY,
        "owner": "home_summary_warm",
        "ttl": scheduled_tasks.HOME_SUMMARY_WARM_JOB_TIMEOUT_SECONDS,
        "token": "test-token",
    }
    payload.update(overrides)
    return scheduled_tasks.ScheduleClaimResult(**payload)


def test_warm_task_skips_when_previous_run_is_in_progress(isolated_db, fake_cache, monkeypatch):
    """잡 타임아웃(3600초)이 10분 주기보다 길어 앞 실행이 남아 있을 수 있습니다."""
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        scheduled_tasks,
        "acquire_schedule_claim",
        lambda owner, **kwargs: _claim(
            status=scheduled_tasks.ScheduleClaimStatus.ALREADY_CLAIMED,
            token=None,
        ),
    )

    def _fail() -> dict[str, int]:
        raise AssertionError("선점을 얻지 못했는데 집계를 실행했습니다")

    monkeypatch.setattr(scheduled_tasks, "_warm_home_summary_thread", _fail)

    outcome = asyncio.run(scheduled_tasks.warm_home_summary_task({}))

    assert outcome == {"status": "skipped", "reason": "already_running"}
    assert fake_cache.sets == []


# --------------------------------------------------------------------------- #
# (5) worker cron 등록
# --------------------------------------------------------------------------- #


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


def test_warm_task_registered_in_worker_cron() -> None:
    job = _cron_job_for("warm_home_summary_task")

    assert job is not None
    assert {0, 10, 20, 30, 40, 50} <= set(job.minute)
    assert job.run_at_startup is True
    assert job.timeout_s == scheduled_tasks.HOME_SUMMARY_WARM_JOB_TIMEOUT_SECONDS
    assert "warm_home_summary_task" in {
        getattr(function, "__name__", "") for function in WorkerSettings.functions
    }


# --------------------------------------------------------------------------- #
# (6) 값이 없으면 화면은 '집계 중'
# --------------------------------------------------------------------------- #


@pytest.fixture
def home_client(isolated_db, fake_cache, monkeypatch, tmp_path):
    monkeypatch.setattr(home_summary, "SERVING_ROOT", tmp_path)
    user = CustomUser(
        username="home_counts_tester",
        password="pbkdf2_sha256$1$salt$hash",
        email="home-counts@example.com",
        nickname="건수 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(user)
    isolated_db.commit()
    isolated_db.refresh(user)
    token = create_session(user.id, user.username)
    return TestClient(app, cookies={SESSION_COOKIE_NAME: token})


def test_home_shows_pending_label_when_cache_is_empty(home_client):
    body = home_client.get("/").text

    assert body.count("집계 중") == 2
    assert "최근 365일 공고" in body
    assert "입찰 중 공고" in body


def test_home_shows_cached_counts(home_client, fake_cache):
    fake_cache.set(
        home_summary.SERVIC_COUNTS_CACHE_KEY,
        {"recent_year_count": 1234, "open_count": 56},
        EXPECTED_CACHE_TTL,
    )

    body = home_client.get("/").text

    assert "집계 중" not in body
    assert "1,234" in body
    assert "56" in body
