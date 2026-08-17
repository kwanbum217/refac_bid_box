"""
tests/test_task_offload_automation.py

동기 스텝 러너와 _report 가 이벤트 루프 스레드에서 직접 실행되지 않고
asyncio.to_thread 를 통해 워커 스레드로 오프로드되는지 검증합니다.
"""

from __future__ import annotations

import asyncio
import threading
from unittest.mock import MagicMock, patch

import pytest

from src.tasks import automation_tasks


@pytest.mark.asyncio
async def test_sync_runner_offloaded_to_thread():
    """동기 러너 실행 시 이벤트 루프가 없는 스레드에서 동작함을 검증."""
    loop_detected_in_runner = []
    thread_ids = []
    main_thread_id = threading.get_ident()

    def dummy_sync_runner(db, **kwargs):
        thread_ids.append(threading.get_ident())
        try:
            asyncio.get_running_loop()
            loop_detected_in_runner.append(True)
        except RuntimeError:
            loop_detected_in_runner.append(False)
        return "success", "sync step ok", {"key": "val"}

    with (
        patch.dict(automation_tasks.STEP_RUNNERS, {"predict": dummy_sync_runner}),
        patch.object(automation_tasks, "_report"),
        patch.object(automation_tasks, "SessionLocal", return_value=MagicMock()),
    ):
        res = await automation_tasks.run_automation_pipeline(
            {},
            run_mode="predict_only",
            automation_request_id="req_123",
        )

    assert res["status"] == "success"
    assert len(loop_detected_in_runner) == 1
    # 오프로드된 스레드에서는 get_running_loop() 가 RuntimeError 를 던져야 함 (False)
    assert loop_detected_in_runner[0] is False
    assert thread_ids[0] != main_thread_id


@pytest.mark.asyncio
async def test_async_runner_executed_in_loop():
    """비동기 러너(async def)는 이벤트 루프 스레드에서 직접 await 됨을 검증."""
    loop_detected_in_runner = []

    async def dummy_async_runner(db, **kwargs):
        try:
            asyncio.get_running_loop()
            loop_detected_in_runner.append(True)
        except RuntimeError:
            loop_detected_in_runner.append(False)
        return "success", "async step ok", {"key": "val"}

    with (
        patch.dict(automation_tasks.STEP_RUNNERS, {"collect": dummy_async_runner}),
        patch.object(automation_tasks, "_report"),
        patch.object(automation_tasks, "SessionLocal", return_value=MagicMock()),
    ):
        res = await automation_tasks.run_automation_pipeline(
            {},
            run_mode="collect_only",
            automation_request_id="req_123",
        )

    assert res["status"] == "success"
    assert len(loop_detected_in_runner) == 1
    # 비동기 러너는 이벤트 루프 안에서 실행되므로 True
    assert loop_detected_in_runner[0] is True


@pytest.mark.asyncio
async def test_report_offloaded_to_thread():
    """_report 호출이 이벤트 루프가 없는 스레드에서 실행됨을 검증."""
    loop_detected_in_report = []

    def spy_report(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            loop_detected_in_report.append(True)
        except RuntimeError:
            loop_detected_in_report.append(False)
        return None

    def dummy_sync_runner(db, **kwargs):
        return "success", "sync step ok", {}

    with (
        patch.dict(automation_tasks.STEP_RUNNERS, {"predict": dummy_sync_runner}),
        patch.object(automation_tasks, "_report", side_effect=spy_report),
        patch.object(automation_tasks, "SessionLocal", return_value=MagicMock()),
    ):
        res = await automation_tasks.run_automation_pipeline(
            {},
            run_mode="predict_only",
            automation_request_id="req_123",
        )

    assert res["status"] == "success"
    # 스텝 리포트 1회 + final 리포트 1회 = 총 2회 호출
    assert len(loop_detected_in_report) >= 2
    # 모든 _report 호출이 워커 스레드에서 실행되어 RuntimeError 를 일으켜야 함 (False)
    for idx, has_loop in enumerate(loop_detected_in_report):
        assert has_loop is False, f"Report call #{idx} executed inside event loop"


@pytest.mark.asyncio
async def test_report_on_exception_offloaded_to_thread():
    """예외 발생 시 _report 호출도 워커 스레드에서 실행됨을 검증."""
    loop_detected_in_report = []

    def spy_report(*args, **kwargs):
        try:
            asyncio.get_running_loop()
            loop_detected_in_report.append(True)
        except RuntimeError:
            loop_detected_in_report.append(False)
        return None

    def failing_runner(db, **kwargs):
        raise ValueError("Simulated runner crash")

    with (
        patch.dict(automation_tasks.STEP_RUNNERS, {"predict": failing_runner}),
        patch.object(automation_tasks, "_report", side_effect=spy_report),
        patch.object(automation_tasks, "SessionLocal", return_value=MagicMock()),
    ):
        res = await automation_tasks.run_automation_pipeline(
            {},
            run_mode="predict_only",
            automation_request_id="req_123",
        )

    assert res["status"] == "failed"
    assert len(loop_detected_in_report) == 1
    assert loop_detected_in_report[0] is False
