"""
tests/test_intraday_observability_20261117.py

낮 시간 증분 수집 관측 계약 테스트.

  (a) 계수기 밖에서는 요청해도 오류 없이 계수하지 않는다
  (b) 계수기 안에서 200 응답 두 번이면 requests=2
  (c) 429 한 번 뒤 200 이면 requests=2, rate_limited=1
  (d) 계수기 두 개를 동시에 돌려도 서로 섞이지 않는다
  (e) intraday_collect_task 정상 경로 반환에 네 키가 있고 로그 한 줄이 나온다

실제 나라장터·DB·Redis·Meilisearch 에 연결하지 않습니다. HTTP 는 MockTransport 로
대체하고, 재시도 대기 sleep 은 0 으로 만듭니다.
"""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import httpx
import pytest

from src.app.core.config import settings
from src.app.services import api_collector
from src.app.services.api_collector import _make_request_with_retry, api_call_counter
from src.tasks import scheduled_tasks, worker
from src.tasks.scheduled_tasks import ScheduleClaimResult, ScheduleClaimStatus

FIXED_UTC = datetime(2026, 11, 17, 3, 0, 0)
TODAY = "20261117"
_CLAIM_OWNER = "intraday-observability-owner"
_API_URL = "https://example.test/api/announce"


class _AsyncioShim:
    """api_collector 안에서만 sleep 을 0 으로 바꾸고 나머지는 원래 모듈에 위임합니다."""

    def __getattr__(self, name: str) -> Any:
        return getattr(asyncio, name)

    async def sleep(self, *_args: Any, **_kwargs: Any) -> None:
        return None


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(api_collector, "asyncio", _AsyncioShim())


@pytest.fixture(autouse=True)
def _silence_schedule_log(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("src.tasks.worker.record_schedule_result", lambda *a, **k: None)


def _client(statuses: list[int]) -> tuple[httpx.AsyncClient, list[str]]:
    calls: list[str] = []

    async def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        index = min(len(calls) - 1, len(statuses) - 1)
        return httpx.Response(statuses[index], text="<root/>")

    return httpx.AsyncClient(transport=httpx.MockTransport(handler)), calls


def _claim() -> ScheduleClaimResult:
    return ScheduleClaimResult(
        status=ScheduleClaimStatus.ACQUIRED,
        key=scheduled_tasks.SCHEDULE_COLLECTION_CLAIM_KEY,
        owner=scheduled_tasks.INTRADAY_COLLECT_SCHEDULE_NAME,
        ttl=scheduled_tasks.INTRADAY_COLLECT_CLAIM_TTL_SECONDS,
        token=_CLAIM_OWNER,
    )


@pytest.mark.asyncio
async def test_requests_outside_counter_are_inert() -> None:
    """(a) 계수기를 열지 않은 컨텍스트에서는 세지 않고 요청도 정상입니다."""
    client, calls = _client([200])
    async with client:
        resp = await _make_request_with_retry(client, _API_URL, {})

    assert resp.status_code == 200
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_counter_counts_each_http_attempt() -> None:
    """(b) 200 응답 두 번이면 요청 시도 수는 2 입니다."""
    client, calls = _client([200])
    async with client:
        with api_call_counter() as counter:
            await _make_request_with_retry(client, _API_URL, {})
            await _make_request_with_retry(client, _API_URL, {})

    assert len(calls) == 2
    assert counter.requests == 2
    assert counter.rate_limited == 0


@pytest.mark.asyncio
async def test_counter_counts_429_retry() -> None:
    """(c) 429 한 번 뒤 200 이면 시도 2회, 429 재시도 1회입니다."""
    client, calls = _client([429, 200])
    async with client:
        with api_call_counter() as counter:
            await _make_request_with_retry(client, _API_URL, {})

    assert len(calls) == 2
    assert counter.requests == 2
    assert counter.rate_limited == 1


@pytest.mark.asyncio
async def test_gather_subtasks_share_counter() -> None:
    """(d-1) asyncio.gather 로 띄운 하위 작업은 같은 계수기를 물려받습니다."""
    client, _ = _client([200])
    async with client:
        with api_call_counter() as counter:
            await asyncio.gather(
                *(_make_request_with_retry(client, _API_URL, {}) for _ in range(3))
            )

    assert counter.requests == 3
    assert counter.rate_limited == 0


@pytest.mark.asyncio
async def test_concurrent_counters_do_not_mix() -> None:
    """(d) 동시에 도는 두 회차의 요청 수가 서로 섞이지 않습니다."""

    async def _run(count: int):
        client, _ = _client([200])
        async with client:
            with api_call_counter() as counter:
                for _ in range(count):
                    await _make_request_with_retry(client, _API_URL, {})
        return counter

    first, second = await asyncio.gather(_run(2), _run(5))

    assert first.requests == 2
    assert second.requests == 5
    assert first is not second


@pytest.mark.asyncio
async def test_intraday_task_reports_counts_and_timings(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """(e) 정상 경로 반환에 네 키가 있고 완료 로그 한 줄이 남습니다."""
    monkeypatch.setattr(settings, "INTRADAY_COLLECT_ENABLED", True)
    monkeypatch.setattr(settings, "MEILI_ENABLED", True)
    monkeypatch.setattr(scheduled_tasks, "utcnow", lambda: FIXED_UTC)
    monkeypatch.setattr(worker, "get_heavy_task_lock", lambda: asyncio.Lock())
    monkeypatch.setattr(scheduled_tasks, "acquire_schedule_claim", MagicMock(return_value=_claim()))
    release = MagicMock()
    monkeypatch.setattr(scheduled_tasks, "release_schedule_claim", release)
    monkeypatch.setattr(
        scheduled_tasks, "SessionLocal", lambda: SimpleNamespace(close=lambda: None)
    )

    async def fake_collect(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        client, _ = _client([200])
        async with client:
            await _make_request_with_retry(client, _API_URL, {})
        return {
            "status": "success",
            "announcement_count": 7,
            "license_limit_count": 1,
            "participation_region_count": 2,
        }

    monkeypatch.setattr(scheduled_tasks, "collect_bids", fake_collect)
    sync = MagicMock(return_value={"announcements": 7, "results": 0})
    monkeypatch.setattr("src.app.services.search_index.sync_search_index", sync)

    caplog.set_level(logging.INFO, logger="src.tasks.scheduled_tasks")
    outcome = await scheduled_tasks.intraday_collect_task({})

    assert outcome["status"] == "success"
    assert outcome["api_requests"] == 1
    assert outcome["api_rate_limited"] == 0
    assert isinstance(outcome["collect_seconds"], float)
    assert isinstance(outcome["sync_seconds"], float)
    assert outcome["collect_seconds"] >= 0.0
    assert outcome["sync_seconds"] >= 0.0

    sync.assert_called_once()
    release.assert_called_once()
    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.tasks.scheduled_tasks"
    ]
    completed = [message for message in messages if message.startswith("낮 시간 증분 수집 완료")]
    assert len(completed) == 1
    assert "API 요청 1회(429 0회)" in completed[0]
    assert "수집 " in completed[0]
    assert "색인 " in completed[0]
