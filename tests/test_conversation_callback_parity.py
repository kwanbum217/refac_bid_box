"""
tests/test_conversation_callback_parity.py

원본 apps/chatbot/tests.py 의 대화 메모리·콜백 경로 테스트 이식입니다.

대응하는 원본 테스트:

- test_load_conversation_context_merges_user_filters_with_session_priority
- test_remember_chat_interaction_keeps_full_result_only_in_session_memory
- test_resolve_callback_delivery_accepts_public_base_url
- test_resolve_callback_delivery_rejects_loopback_base_url

콜백 판정은 원본과 계약이 다릅니다. 원본은 루프백 주소면 무조건 polling 이지만,
이식본은 워커가 앱과 같은 DB 를 쓰면 direct 로 강등합니다(Arq 구조). 그 분기까지
포함해 검증합니다.
"""

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from src.app.models.chatbot import ChatSessionState
from src.app.services.automation_orchestrator import resolve_callback_delivery
from src.app.services.conversation_state import (
    load_conversation_context,
    remember_chat_interaction,
)

JOB_ID = "11111111-1111-1111-1111-111111111111"


@pytest.fixture
def user(isolated_db):
    row = CustomUser(
        username="memory_tester",
        password="x",
        email="memory@example.com",
        nickname="메모리 검증",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(row)
    isolated_db.commit()
    isolated_db.refresh(row)
    return row


# --------------------------------------------------------------------------- #
# 대화 메모리
# --------------------------------------------------------------------------- #


def test_load_conversation_context_merges_user_filters_with_session_priority(isolated_db, user):
    """사용자 메모리와 세션 메모리를 합치되 겹치는 값은 세션이 이깁니다.

    사용자 메모리는 여러 대화에 걸친 고정 필터고, 세션 메모리는 지금 대화의
    맥락입니다. 우선순위가 뒤집히면 방금 바꾼 조건이 옛 값으로 되돌아갑니다.
    """
    session_key = "session-merge-test"
    isolated_db.add_all(
        [
            ChatSessionState(
                session_key=f"user:{user.id}",
                user_id=user.id,
                last_query="사용자 메모리 질의",
                last_filters_json={"institution_name": "서울", "category": "Servc"},
            ),
            ChatSessionState(
                session_key=session_key,
                user_id=user.id,
                last_query="세션 메모리 질의",
                last_filters_json={"category": "Cnstwk", "date_from": "2026-01-01"},
            ),
        ]
    )
    isolated_db.commit()

    context = load_conversation_context(isolated_db, session_key, user_id=user.id)
    filters = context["last_filters_json"]

    assert context["last_query"] == "세션 메모리 질의"
    # 사용자 메모리에만 있는 값은 살아남습니다.
    assert filters["institution_name"] == "서울"
    # 겹치는 키는 세션 값이 이깁니다.
    assert filters["category"] == "Cnstwk"
    assert filters["date_from"] == "2026-01-01"


def test_remember_chat_interaction_keeps_full_result_only_in_session_memory(isolated_db, user):
    """전체 결과 페이로드는 세션 메모리에만 남기고 사용자 메모리에는 넣지 않는다.

    사용자 메모리는 대화를 넘어 계속 따라다니므로, 결과 원본까지 담으면
    계속 부풀어 오릅니다. 사용자 메모리에는 고정 필터와 질의 요약만 둡니다.
    """
    from src.app.services.planner import plan_chat_request

    session_key = "session-remember-test"
    message = "최근 낙찰률 추세 알려줘"
    chart = {
        "type": "chart",
        "chart_type": "line",
        "title": "최근 낙찰률 추세",
        "labels": ["2026-01"],
        "values": [98.1],
    }

    remember_chat_interaction(
        isolated_db,
        session_key,
        user_id=user.id,
        message=message,
        plan=plan_chat_request(message),
        tool_context={
            "tool_results": {
                "bid_query": {
                    "retrieval_plan": {"filters": {"institution_name": "서울"}},
                    "result": {
                        "summary": {"time_series": [{"month": "2026-01", "avg_rate": 98.1}]}
                    },
                }
            },
            "visualizations": [chart],
        },
        answer_text="요약 답변",
        visualizations=[chart],
    )

    session_state = (
        isolated_db.query(ChatSessionState)
        .filter(ChatSessionState.session_key == session_key)
        .one()
    )
    user_state = (
        isolated_db.query(ChatSessionState)
        .filter(ChatSessionState.session_key == f"user:{user.id}")
        .one()
    )

    assert session_state.last_result_payload
    assert "tool_results" in session_state.last_result_payload
    # 사용자 메모리에는 결과 원본이 없어야 합니다.
    assert not (user_state.last_result_payload or {}).get("tool_results")
    assert user_state.last_query == message


# --------------------------------------------------------------------------- #
# 콜백 경로 판정
# --------------------------------------------------------------------------- #


def test_resolve_callback_delivery_accepts_public_base_url(monkeypatch):
    """공개 주소가 설정되면 워커가 HTTP 로 결과를 보고한다."""
    from src.app.core.config import settings

    monkeypatch.setattr(
        settings, "AUTOMATION_CALLBACK_BASE_URL", "https://bidbox.example.com", raising=False
    )
    monkeypatch.setattr(settings, "AUTOMATION_WORKER_SHARES_DB", False, raising=False)

    delivery = resolve_callback_delivery(JOB_ID)

    assert delivery.mode == "callback"
    assert delivery.configured is True
    assert delivery.callback_url.endswith(f"/automation/job/{JOB_ID}/callback")


def test_resolve_callback_delivery_rejects_loopback_base_url(monkeypatch):
    """루프백 주소는 워커가 도달할 수 없으므로 콜백으로 쓰지 않는다."""
    from src.app.core.config import settings

    monkeypatch.setattr(
        settings, "AUTOMATION_CALLBACK_BASE_URL", "http://127.0.0.1:8000", raising=False
    )
    monkeypatch.setattr(settings, "AUTOMATION_WORKER_SHARES_DB", False, raising=False)

    delivery = resolve_callback_delivery(JOB_ID)

    assert delivery.mode == "polling"
    assert delivery.configured is False
    assert delivery.callback_url == ""


def test_resolve_callback_delivery_falls_back_to_direct_when_db_is_shared(monkeypatch):
    """이식본 고유 분기입니다.

    워커가 앱과 같은 DB 를 쓰면 콜백이 없어도 결과를 직접 기록할 수 있어
    polling 으로 떨어뜨리지 않습니다. 원본에는 없던 경로입니다.
    """
    from src.app.core.config import settings

    monkeypatch.setattr(
        settings, "AUTOMATION_CALLBACK_BASE_URL", "http://127.0.0.1:8000", raising=False
    )
    monkeypatch.setattr(settings, "AUTOMATION_WORKER_SHARES_DB", True, raising=False)

    delivery = resolve_callback_delivery(JOB_ID)

    assert delivery.mode == "direct"
    assert delivery.configured is True
    assert delivery.callback_url == ""
