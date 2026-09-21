"""
tests/test_automation_steps_offload.py

_step_collect 의 error 분기에서 실행되는 동기 DB 집계(오늘 적재분 COUNT)가
이벤트 루프 스레드가 아니라 asyncio.to_thread 로 오프로드된 워커 스레드에서
실행되는지 검증합니다. 호출 성공만 보는 테스트가 아니라, 집계가 실제로 실행된
스레드와 이벤트 루프 유무를 세션 대역으로 기록해 단언합니다.
"""

from __future__ import annotations

import asyncio
import threading
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from src.tasks.automation_steps import _step_collect


def _is_in_event_loop() -> bool:
    """오프로드된 스레드에서는 asyncio.get_running_loop() 가 RuntimeError 를 던집니다."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


class _ThreadRecordingDB:
    """error 분기 집계(scalar)가 실행된 스레드와 이벤트 루프 유무를 기록하는 세션 대역."""

    def __init__(self, today_rows: int) -> None:
        self._today_rows = today_rows
        self.calls: list[tuple[bool, threading.Thread]] = []

    def scalar(self, statement: Any) -> int:
        self.calls.append((_is_in_event_loop(), threading.current_thread()))
        return self._today_rows


def _error_metrics(**overrides: Any) -> dict[str, Any]:
    metrics: dict[str, Any] = {
        "status": "error",
        "message": "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다.",
        "announcement_count": 0,
        "result_count": 0,
        "total_records": 0,
        "attempted": 0,
        "failed_count": 0,
    }
    metrics.update(overrides)
    return metrics


@pytest.mark.asyncio
async def test_collect_error_branch_offloads_count_to_thread() -> None:
    """error 분기 집계가 이벤트 루프 밖 워커 스레드에서 정확히 한 번 실행됨을 검증."""
    db = _ThreadRecordingDB(today_rows=7)

    with patch(
        "src.app.services.collector_service.collect_bids",
        new_callable=AsyncMock,
        return_value=_error_metrics(),
    ):
        status, summary, metrics = await _step_collect(db)

    assert status == "error"
    assert summary == "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다. 오늘 적재분 7건."
    assert metrics["today_rows"] == 7

    assert len(db.calls) == 1, "error 분기 집계는 한 번만 실행되어야 합니다."
    in_event_loop, thread = db.calls[0]
    assert in_event_loop is False, (
        "동기 DB 집계가 이벤트 루프 스레드에서 직접 실행되었습니다 (to_thread 미적용)."
    )
    assert thread is not threading.main_thread(), (
        "동기 DB 집계가 이벤트 루프(메인) 스레드에서 실행되었습니다."
    )


@pytest.mark.asyncio
async def test_collect_error_branch_keeps_return_contract() -> None:
    """오프로드 후에도 status, summary 문구, res_metrics 키와 값이 그대로 유지됨을 검증."""
    db = _ThreadRecordingDB(today_rows=0)

    with patch(
        "src.app.services.collector_service.collect_bids",
        new_callable=AsyncMock,
        return_value=_error_metrics(
            announcement_count=3,
            result_count=1,
            attempted=4,
            failed_count=2,
            categories={"servc": {"announcement_count": 3}},
        ),
    ):
        status, summary, metrics = await _step_collect(db)

    assert status == "error"
    assert summary == "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다. 오늘 적재분 0건."
    assert set(metrics) == {
        "today_rows",
        "announcement_count",
        "result_count",
        "collector_available",
        "attempted",
        "failed_count",
        "categories",
        "status",
        "message",
    }
    assert metrics == {
        "today_rows": 0,
        "announcement_count": 3,
        "result_count": 1,
        "collector_available": False,
        "attempted": 4,
        "failed_count": 2,
        "categories": {"servc": {"announcement_count": 3}},
        "status": "error",
        "message": "G2B serviceKey 가 설정되지 않아 수집을 수행할 수 없습니다.",
    }
