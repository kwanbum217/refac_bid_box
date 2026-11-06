"""
tests/test_automation_status_owner.py

자동화 상태 도구의 소유자 격리 검증.

비로그인 요청은 자동화 요청을 읽거나 확인 토큰을 받을 수 없고, 로그인
사용자는 자기 요청만 조회한다.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy.orm import Session

from src.app.models.chatbot import AutomationRequest
from src.app.services.tools import automation_status_tool

LOGIN_REQUIRED_MESSAGE = "자동화 작업 상태는 로그인한 뒤 확인할 수 있습니다."
SENSITIVE_KEYS = ("job", "confirmation_token", "result_payload")


def _add_request(
    db: Session,
    *,
    user_id: int,
    request_id: str,
    status: str,
    requires_confirmation: bool = False,
) -> AutomationRequest:
    request_obj = AutomationRequest(
        request_id=request_id,
        user_id=user_id,
        intent_type="full_validation",
        action_key="full_validation",
        requested_text="전체 점검해줘",
        pipeline_name="bidbox_staging",
        status=status,
        requires_confirmation=requires_confirmation,
        plan_execution_id=f"plan-{request_id}",
        result_payload={"steps": {"preflight": {"status": "success"}}},
    )
    db.add(request_obj)
    db.commit()
    return request_obj


@pytest.fixture
def seeded_requests(isolated_db: Session) -> tuple[AutomationRequest, AutomationRequest]:
    other = _add_request(
        isolated_db,
        user_id=7,
        request_id="job-owner-7",
        status="pending_confirmation",
        requires_confirmation=True,
    )
    mine = _add_request(
        isolated_db,
        user_id=2,
        request_id="job-owner-2",
        status="running",
    )
    return other, mine


def _assert_anonymous_payload(payload: dict[str, Any], request_ids: list[str]) -> None:
    assert payload["mode"] == "answer"
    assert payload["intent"] == "automation_status"
    assert payload["message"] == LOGIN_REQUIRED_MESSAGE
    for key in SENSITIVE_KEYS:
        assert key not in payload
    serialized = str(payload)
    for request_id in request_ids:
        assert request_id not in serialized


def test_anonymous_context_returns_login_guidance_without_db_access(
    monkeypatch: pytest.MonkeyPatch,
    isolated_db: Session,
    seeded_requests: tuple[AutomationRequest, AutomationRequest],
) -> None:
    """(a) context user_id 가 None 이면 조회·동기화 없이 안내만 돌려준다."""
    other, mine = seeded_requests
    other_id = other.id
    other_status = other.status
    other_summary = other.result_summary

    def _unexpected_call(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("익명 요청이 자동화 요청 저장소에 접근했습니다")

    monkeypatch.setattr(automation_status_tool, "_find_request", _unexpected_call)
    monkeypatch.setattr(automation_status_tool, "sync_automation_status", _unexpected_call)

    payload = automation_status_tool.execute(db=isolated_db, context={"user_id": None})

    _assert_anonymous_payload(payload, [other.request_id, mine.request_id])

    isolated_db.expire_all()
    stored = isolated_db.get(AutomationRequest, other_id)
    assert stored is not None
    assert stored.status == other_status
    assert stored.confirmed_at is None
    assert stored.result_summary == other_summary


def test_missing_context_is_treated_as_anonymous(
    monkeypatch: pytest.MonkeyPatch,
    isolated_db: Session,
    seeded_requests: tuple[AutomationRequest, AutomationRequest],
) -> None:
    """(d) context 자체가 없어도 (a) 와 같은 안내만 돌려준다."""
    other, mine = seeded_requests

    def _unexpected_call(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("익명 요청이 자동화 요청 저장소에 접근했습니다")

    monkeypatch.setattr(automation_status_tool, "_find_request", _unexpected_call)
    monkeypatch.setattr(automation_status_tool, "sync_automation_status", _unexpected_call)

    payload = automation_status_tool.execute(db=isolated_db, context=None)

    _assert_anonymous_payload(payload, [other.request_id, mine.request_id])


def test_find_request_without_owner_returns_none(
    isolated_db: Session,
    seeded_requests: tuple[AutomationRequest, AutomationRequest],
) -> None:
    """이중 방어: _find_request 자체도 소유자 없는 조회를 거부한다."""
    other, _ = seeded_requests
    assert automation_status_tool._find_request(isolated_db) is None
    assert automation_status_tool._find_request(isolated_db, other.request_id) is None


def test_logged_in_user_cannot_read_other_users_job(
    isolated_db: Session,
    seeded_requests: tuple[AutomationRequest, AutomationRequest],
) -> None:
    """(b) user_id=2 가 user_id=7 의 job_id 를 지목해도 조회되지 않는다."""
    other, _ = seeded_requests

    payload = automation_status_tool.execute(
        db=isolated_db, job_id=other.request_id, context={"user_id": 2}
    )

    assert payload["found"] is False
    assert payload["job"] is None
    assert payload["confirmation_token"] == ""
    assert payload["result_payload"] == {}
    assert other.request_id not in str(payload)


def test_owner_reads_own_request(
    isolated_db: Session,
    seeded_requests: tuple[AutomationRequest, AutomationRequest],
) -> None:
    """(c) user_id=7 은 자기 요청을 읽는다. job_id 미지정 시에도 자기 것만 고른다."""
    other, mine = seeded_requests

    explicit = automation_status_tool.execute(
        db=isolated_db, job_id=other.request_id, context={"user_id": 7}
    )
    assert explicit["found"] is True
    assert explicit["job"]["job_id"] == other.request_id
    assert explicit["confirmation_token"]
    assert explicit["mode"] == "confirmation"

    latest = automation_status_tool.execute(db=isolated_db, context={"user_id": 7})
    assert latest["job"]["job_id"] == other.request_id
    assert mine.request_id not in str(latest)


def test_anonymous_chat_api_does_not_leak_automation_status(
    client: Any,
    isolated_db: Session,
    seeded_requests: tuple[AutomationRequest, AutomationRequest],
) -> None:
    """HTTP 익명 요청 응답에 확인 토큰이나 다른 사용자의 job_id 가 없어야 한다."""
    other, mine = seeded_requests
    other_id = other.id
    other_request_id = other.request_id
    mine_request_id = mine.request_id

    response = client.post("/api/v1/chatbot/chat", json={"message": "현재 점검 진행 상황 알려줘"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["intent"] == "automation_status"
    assert LOGIN_REQUIRED_MESSAGE in payload["answer"]
    assert payload["job"] is None
    assert payload["confirmation_token"] == ""
    assert payload["result_payload"] == {}
    assert other_request_id not in response.text
    assert mine_request_id not in response.text

    isolated_db.expire_all()
    stored = isolated_db.get(AutomationRequest, other_id)
    assert stored is not None
    assert stored.status == "pending_confirmation"
    assert stored.confirmed_at is None
