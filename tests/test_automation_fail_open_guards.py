"""
tests/test_automation_fail_open_guards.py

자동화 제어 경계에서 실패나 미지정 상태가 성공으로 승격되지 않는지 검증합니다.
  - 알 수 없는 run_mode 는 0개 스텝 성공이 아니라 실패로 보고됩니다
  - 종료된 요청은 늦게 도착한 final 콜백으로 상태가 뒤집히지 않습니다
  - 콜백 토큰은 만료됩니다
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from src.app.models.chatbot import AutomationRequest
from src.app.services import automation_tokens
from src.app.services.automation_orchestrator import apply_callback_payload
from src.tasks import automation_tasks


@pytest.mark.asyncio
async def test_unknown_run_mode_is_reported_as_failure():
    """존재하지 않는 run_mode 가 아무 일도 하지 않고 성공으로 끝나면 안 됩니다."""
    with (
        patch.object(automation_tasks, "_report") as mock_report,
        patch.object(automation_tasks, "SessionLocal", return_value=MagicMock()),
    ):
        res = await automation_tasks.run_automation_pipeline(
            {},
            run_mode="typo_only",
            automation_request_id="req_unknown_mode",
        )

    assert res["status"] == "failed", res
    final_calls = [c for c in mock_report.call_args_list if c.kwargs.get("final")]
    assert final_calls, mock_report.call_args_list
    assert final_calls[-1].args[3] == "failed"


@pytest.mark.asyncio
async def test_known_run_mode_still_succeeds():
    """정상 run_mode 는 기존과 동일하게 성공합니다 (수정의 부작용 확인)."""

    def dummy_runner(db, **kwargs):
        return "success", "ok", {}

    with (
        patch.dict(automation_tasks.STEP_RUNNERS, {"predict": dummy_runner}),
        patch.object(automation_tasks, "_report"),
        patch.object(automation_tasks, "SessionLocal", return_value=MagicMock()),
    ):
        res = await automation_tasks.run_automation_pipeline(
            {},
            run_mode="predict_only",
            automation_request_id="req_ok",
        )

    assert res["status"] == "success"


def _seed_request(db, *, status: str) -> AutomationRequest:
    user = CustomUser(
        username=f"guard_tester_{status}",
        password="x",
        email=f"guard_{status}@example.com",
        nickname="가드 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()

    request_obj = AutomationRequest(
        request_id=f"req-{status}-guard",
        user_id=user.id,
        intent_type="automation",
        requested_text="전체 점검",
        action_key="full_validation",
        status=status,
    )
    db.add(request_obj)
    db.commit()
    db.refresh(request_obj)
    return request_obj


@pytest.mark.parametrize("terminal_status", ["success", "failed", "canceled"])
def test_late_final_callback_does_not_flip_terminal_status(isolated_db, terminal_status):
    """이미 종료된 요청은 늦은 final 콜백으로 되살아나지 않습니다."""
    request_obj = _seed_request(isolated_db, status=terminal_status)
    opposite = "failed" if terminal_status == "success" else "success"

    apply_callback_payload(
        isolated_db,
        request_obj,
        {"step": "final", "status": opposite, "summary": "늦게 도착한 보고", "final": True},
    )

    assert request_obj.status == terminal_status
    # 단계 기록 자체는 감사 근거로 남아야 합니다.
    assert request_obj.result_payload["steps"]["final"]["status"] == opposite


def test_running_request_still_accepts_final_callback(isolated_db):
    """진행 중인 요청의 final 콜백은 기존과 동일하게 종결 처리됩니다."""
    request_obj = _seed_request(isolated_db, status="running")

    apply_callback_payload(
        isolated_db,
        request_obj,
        {"step": "final", "status": "success", "summary": "완료", "final": True},
    )

    assert request_obj.status == "success"
    assert request_obj.completed_at is not None


def test_callback_token_expires(monkeypatch):
    """콜백 토큰은 서명이 맞아도 유효 기간을 넘기면 거절됩니다."""
    base_time = 1_700_000_000.0
    monkeypatch.setattr(automation_tokens.time, "time", lambda: base_time)
    token = automation_tokens.make_callback_token("job-1")

    assert automation_tokens.verify_callback_token("job-1", token) is True

    monkeypatch.setattr(
        automation_tokens.time,
        "time",
        lambda: base_time + automation_tokens.CALLBACK_MAX_AGE + 1,
    )
    assert automation_tokens.verify_callback_token("job-1", token) is False
