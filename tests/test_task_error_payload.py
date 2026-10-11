"""
tests/test_task_error_payload.py

작업 결과 payload 의 예외 요약이 원문을 그대로 흘리지 않고 분류 코드(error_type)와
마스킹된 한 줄 요약(error)만 담는지 검증합니다.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest
from sqlalchemy.orm import sessionmaker

from src.tasks import automation_tasks, coverage_tasks, scheduled_tasks
from src.tasks.error_payload import MAX_ERROR_SUMMARY_LENGTH, safe_error, summarize_error


def test_safe_error_masks_service_key_and_file_path():
    exc = RuntimeError(
        "API 오류: https://apis.data.go.kr/1230000/as?serviceKey=SECRET1234&type=x "
        "/opt/app/data/model.pkl"
    )

    payload = safe_error(exc)

    assert payload["error_type"] == "RuntimeError"
    assert "SECRET1234" not in payload["error"]
    assert "apis.data.go.kr" not in payload["error"]
    assert "/opt/app/data/model.pkl" not in payload["error"]


def test_summarize_error_keeps_first_line_only_and_caps_length():
    exc = RuntimeError("첫 줄 요약\n둘째 줄 SQL SELECT * FROM users")

    assert summarize_error(exc) == "첫 줄 요약"

    long_summary = summarize_error(RuntimeError("가" * 500))
    assert len(long_summary) <= MAX_ERROR_SUMMARY_LENGTH
    assert long_summary.endswith("...")


def test_summarize_error_without_message_uses_type_name():
    assert safe_error(RuntimeError()) == {"error_type": "RuntimeError", "error": "RuntimeError"}


@pytest.mark.asyncio
async def test_weekly_retrain_result_carries_error_type_without_raw_text():
    async def fake_run_retrain(ctx, trigger_source="weekly_schedule", category_code=None, **kwargs):
        raise RuntimeError("serviceKey=SECRET1234 /opt/app/data/x.pkl")

    with patch.object(scheduled_tasks, "run_retrain_pipeline_task", side_effect=fake_run_retrain):
        outcome = await scheduled_tasks.weekly_retrain_task({})

    entry = outcome["categories"]["Servc"]
    assert entry["status"] == "failed"
    assert entry["error_type"] == "RuntimeError"
    assert "SECRET1234" not in entry["error"]
    assert "/opt/app/data/x.pkl" not in entry["error"]


@pytest.mark.asyncio
async def test_result_coverage_monitor_error_payload_has_error_type():
    with patch.object(
        coverage_tasks, "_collect_snapshot", side_effect=RuntimeError("DB 오류\nSQL")
    ):
        result = await coverage_tasks._run_result_coverage_monitor()

    assert result["status"] == "error"
    assert result["error_type"] == "RuntimeError"
    assert result["error"] == "DB 오류"


@pytest.fixture
def automation_db(isolated_db, monkeypatch):
    engine = isolated_db.get_bind()
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    monkeypatch.setattr(automation_tasks, "SessionLocal", factory)
    return isolated_db


@pytest.mark.asyncio
async def test_automation_pipeline_error_payload_has_error_type(automation_db):
    result = await automation_tasks.run_automation_pipeline(
        {}, execution_id="u3-error-masking", run_mode="unknown_mode"
    )

    assert result["status"] == "failed"
    assert result["error_type"] == "ValueError"
    assert "unknown_mode" in result["error"]
