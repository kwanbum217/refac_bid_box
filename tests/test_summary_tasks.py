"""
tests/test_summary_tasks.py

요약 재집계 Arq 태스크의 무거운 동기 DB 작업이 이벤트 루프 스레드가 아니라 worker
thread(asyncio.to_thread)로 오프로드되는지 검증합니다. 호출 성공만 보는 테스트는
증명이 아니므로, 동기 작업과 세션 생성/종료가 실제로 실행된 스레드를 단언합니다.
"""

from __future__ import annotations

import asyncio
import threading
from datetime import datetime
from types import SimpleNamespace
from typing import Any

import pytest

from src.tasks import summary_tasks
from src.tasks.summary_tasks import (
    rebuild_dataset_summary_task,
    refresh_institution_catalog_task,
)


def _assert_no_running_loop() -> None:
    """오프로드된 스레드에서는 asyncio.get_running_loop() 가 RuntimeError 를 발생시켜야 합니다."""
    try:
        asyncio.get_running_loop()
        in_loop = True
    except RuntimeError:
        in_loop = False
    assert not in_loop, (
        "동기 DB 작업이 이벤트 루프 스레드에서 직접 실행되었습니다 (to_thread 미적용)."
    )


class _ThreadRecordingSession:
    """세션 생성과 종료가 일어난 스레드를 기록하는 컨텍스트 매니저 대역."""

    def __init__(self, events: list[tuple[str, threading.Thread]]) -> None:
        self._events = events

    def __enter__(self) -> _ThreadRecordingSession:
        self._events.append(("session_enter", threading.current_thread()))
        return self

    def __exit__(self, *exc_info: object) -> bool:
        self._events.append(("session_exit", threading.current_thread()))
        return False


def _assert_single_worker_thread(
    events: list[tuple[str, threading.Thread]], expected_order: list[str]
) -> None:
    """기록된 모든 단계가 메인 스레드가 아닌 하나의 동일 스레드에서 실행됐는지 단언합니다."""
    assert [name for name, _ in events] == expected_order
    threads = {thread for _, thread in events}
    assert threads, "동기 DB 작업이 전혀 실행되지 않았습니다."
    assert threading.main_thread() not in threads, (
        "동기 DB 작업과 세션 수명주기가 이벤트 루프(메인) 스레드에서 실행되었습니다."
    )
    assert len(threads) == 1, "세션과 동기 호출이 서로 다른 스레드에서 실행되었습니다."


@pytest.mark.asyncio
async def test_rebuild_dataset_summary_task_offloads_db_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """재집계 태스크의 세션 수명주기와 동기 호출이 단일 worker thread 에서 실행되는지 검증."""
    events: list[tuple[str, threading.Thread]] = []
    rebuilt_at = datetime(2026, 9, 20, 1, 2, 3)

    def fake_rebuild(db: Any, dataset: str) -> SimpleNamespace:
        _assert_no_running_loop()
        events.append(("rebuild", threading.current_thread()))
        return SimpleNamespace(
            dataset=dataset,
            total_count=42,
            total_amount=1500,
            aggregation_version=3,
            rebuilt_at=rebuilt_at,
        )

    monkeypatch.setattr(summary_tasks, "SessionLocal", lambda: _ThreadRecordingSession(events))
    monkeypatch.setattr(summary_tasks, "rebuild_bid_dataset_summary", fake_rebuild)

    result = await rebuild_dataset_summary_task({}, "announcement")

    assert result == {
        "dataset": "announcement",
        "total_count": 42,
        "total_amount": 1500,
        "aggregation_version": 3,
        "rebuilt_at": "2026-09-20T01:02:03",
    }
    _assert_single_worker_thread(events, ["session_enter", "rebuild", "session_exit"])


@pytest.mark.asyncio
async def test_refresh_institution_catalog_task_offloads_db_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """기관명 캐시 갱신 태스크의 세션 수명주기와 동기 호출이 worker thread 에서 실행되는지 검증."""
    events: list[tuple[str, threading.Thread]] = []
    expected = {"bid_announcements": 7, "bid_results": 5}

    def fake_refresh(db: Any) -> dict[str, int]:
        _assert_no_running_loop()
        events.append(("refresh", threading.current_thread()))
        return expected

    monkeypatch.setattr(summary_tasks, "SessionLocal", lambda: _ThreadRecordingSession(events))
    monkeypatch.setattr(summary_tasks, "refresh_institution_name_catalogs", fake_refresh)

    result = await refresh_institution_catalog_task({})

    assert result == expected
    _assert_single_worker_thread(events, ["session_enter", "refresh", "session_exit"])
