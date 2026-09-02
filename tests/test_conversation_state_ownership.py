"""
tests/test_conversation_state_ownership.py

대화 상태의 교차 사용자 접근(IDOR) 차단 검증 테스트.
조회와 갱신 모두 소유자 대조(user_id)를 강제하고, 클라이언트가 임의 session_key
또는 user: 접두사 메모리 키로 타 사용자의 메모리를 읽거나 오염시킬 수 없음을 검증합니다.
"""

import pytest
from sqlalchemy import select

from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from src.app.models.chatbot import ChatSessionState
from src.app.schemas.chat import ChatPlan
from src.app.services.conversation_state import (
    _get_state_by_key,
    ensure_session_key,
    load_conversation_context,
    remember_chat_interaction,
)


@pytest.fixture
def user1(isolated_db):
    row = CustomUser(
        username="user1_idor",
        password="x",
        email="user1@example.com",
        nickname="사용자1",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(row)
    isolated_db.commit()
    isolated_db.refresh(row)
    return row


@pytest.fixture
def user2(isolated_db):
    row = CustomUser(
        username="user2_idor",
        password="x",
        email="user2@example.com",
        nickname="사용자2",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(row)
    isolated_db.commit()
    isolated_db.refresh(row)
    return row


def test_get_state_by_key_cross_user_read_rejected(isolated_db, user1, user2):
    """소유자가 다른 세션 키로 조회 시 None 을 반환하여 조회를 거부합니다."""
    session_key = "sess-user1-secret"
    isolated_db.add(
        ChatSessionState(
            session_key=session_key,
            user_id=user1.id,
            last_query="사용자1 비밀 질의",
            last_result_summary="사용자1 비밀 요약",
        )
    )
    isolated_db.commit()

    # 정상 소유자 조회
    owner_state = _get_state_by_key(isolated_db, session_key, user_id=user1.id, create=False)
    assert owner_state is not None
    assert owner_state.last_query == "사용자1 비밀 질의"

    # 타 사용자 조회 시도 (거부)
    cross_state = _get_state_by_key(isolated_db, session_key, user_id=user2.id, create=False)
    assert cross_state is None


def test_get_state_by_key_cross_user_update_rejected(isolated_db, user1, user2):
    """소유자가 다른 세션 키에 대해 생성 또는 갱신 시도 시 fail-closed 로 거부합니다."""
    session_key = "sess-user1-protected"
    isolated_db.add(
        ChatSessionState(
            session_key=session_key,
            user_id=user1.id,
            last_query="사용자1 원본 질의",
            last_result_summary="사용자1 원본 요약",
        )
    )
    isolated_db.commit()

    # 타 사용자가 create=True 로 덮어쓰기/재생성 시도 -> 거부 (None)
    cross_state = _get_state_by_key(isolated_db, session_key, user_id=user2.id, create=True)
    assert cross_state is None

    # 타 사용자가 remember_chat_interaction 호출 -> 거부 (None)
    result = remember_chat_interaction(
        isolated_db,
        session_key,
        user_id=user2.id,
        message="공격자 오염 질의",
        answer_text="공격자 오염 답변",
    )
    assert result is None

    # 사용자1 의 원본 데이터 보존 확인
    db_state = isolated_db.execute(
        select(ChatSessionState).where(ChatSessionState.session_key == session_key)
    ).scalar_one()
    assert db_state.user_id == user1.id
    assert db_state.last_query == "사용자1 원본 질의"
    assert db_state.last_result_summary == "사용자1 원본 요약"


def test_load_conversation_context_cross_user_memory_access_blocked(isolated_db, user1, user2):
    """타 사용자의 user: 메모리 키나 세션 키를 session_key 로 지정해도 타인의 컨텍스트가 노출되지 않습니다."""
    user1_memory_key = f"user:{user1.id}"
    user1_session_key = "sess-user1-data"

    isolated_db.add_all(
        [
            ChatSessionState(
                session_key=user1_memory_key,
                user_id=user1.id,
                last_query="사용자1 고유 질의",
                last_filters_json={"institution_name": "서울지사", "category": "Servc"},
                last_result_summary="사용자1 고유 요약",
            ),
            ChatSessionState(
                session_key=user1_session_key,
                user_id=user1.id,
                last_query="사용자1 세션 질의",
                last_result_summary="사용자1 세션 요약",
            ),
        ]
    )
    isolated_db.commit()

    # 사용자2 가 session_key="user:1" 로 컨텍스트 로드 시도
    context_probe_memory = load_conversation_context(
        isolated_db, session_key=user1_memory_key, user_id=user2.id
    )
    assert context_probe_memory.get("last_query") == ""
    assert context_probe_memory.get("last_result_summary") == ""
    assert context_probe_memory.get("last_filters_json") == {}
    assert context_probe_memory.get("session_memory") == {}

    # 사용자2 가 session_key="sess-user1-data" 로 컨텍스트 로드 시도
    context_probe_session = load_conversation_context(
        isolated_db, session_key=user1_session_key, user_id=user2.id
    )
    assert context_probe_session.get("last_query") == ""
    assert context_probe_session.get("last_result_summary") == ""
    assert context_probe_session.get("session_memory") == {}


def test_remember_chat_interaction_cross_user_memory_pollution_blocked(isolated_db, user1, user2):
    """사용자2 가 사용자1 의 user: 메모리 키로 상호작용 기록을 시도해도 사용자1 의 메모리가 오염되지 않습니다."""
    user1_memory_key = f"user:{user1.id}"
    isolated_db.add(
        ChatSessionState(
            session_key=user1_memory_key,
            user_id=user1.id,
            last_query="사용자1 정품 질의",
            last_filters_json={"category": "Cnstwk"},
            last_result_summary="사용자1 정품 요약",
        )
    )
    isolated_db.commit()

    # 사용자2 가 session_key="user:1" 로 remember_chat_interaction 호출
    pollute_result = remember_chat_interaction(
        isolated_db,
        session_key=user1_memory_key,
        user_id=user2.id,
        message="사용자2 주입 악성 질의",
        plan=ChatPlan(intent_type="bid_search", mode="answer"),
        answer_text="사용자2 악성 답변",
    )
    assert pollute_result is None

    # 사용자1 이 새 세션에서 컨텍스트 로드 시 사용자 메모리가 보존되어 있는지 확인
    user1_new_context = load_conversation_context(
        isolated_db, session_key="sess-user1-fresh", user_id=user1.id
    )
    assert user1_new_context["last_query"] == "사용자1 정품 질의"
    assert user1_new_context["last_filters_json"] == {"category": "Cnstwk"}
    assert user1_new_context["last_result_summary"] == "사용자1 정품 요약"


def test_anonymous_user_cannot_access_or_pollute_authenticated_user_state(isolated_db, user1):
    """user_id 가 None 인 익명 요청도 인증된 사용자의 세션 및 사용자 메모리에 접근하거나 오염시킬 수 없습니다."""
    session_key = "sess-auth-user1"
    user_memory_key = f"user:{user1.id}"

    isolated_db.add_all(
        [
            ChatSessionState(
                session_key=session_key,
                user_id=user1.id,
                last_query="인증 사용자 질의",
                last_result_summary="인증 사용자 요약",
            ),
            ChatSessionState(
                session_key=user_memory_key,
                user_id=user1.id,
                last_query="인증 사용자 메모리 질의",
            ),
        ]
    )
    isolated_db.commit()

    # 익명 조회 거부
    assert _get_state_by_key(isolated_db, session_key, user_id=None, create=False) is None
    assert _get_state_by_key(isolated_db, user_memory_key, user_id=None, create=False) is None

    # 익명 갱신 시도 거부
    assert (
        remember_chat_interaction(isolated_db, session_key, user_id=None, message="익명 공격 질의")
        is None
    )
    assert (
        remember_chat_interaction(
            isolated_db, user_memory_key, user_id=None, message="익명 공격 질의"
        )
        is None
    )

    # 익명 컨텍스트 로드 시 타 사용자 정보 누출 없음 확인
    anon_context = load_conversation_context(isolated_db, session_key, user_id=None)
    assert anon_context.get("last_query") == ""
    assert anon_context.get("session_memory") == {}
    assert anon_context.get("user_memory") == {}


def test_authenticated_user_cannot_access_anonymous_session(isolated_db, user1):
    """인증된 사용자가 익명 사용자 세션(user_id=None)에 접근하거나 덮어쓸 수 없습니다."""
    anon_session_key = "sess-anon-1234"
    isolated_db.add(
        ChatSessionState(
            session_key=anon_session_key,
            user_id=None,
            last_query="익명 사용자 원본 질의",
            last_result_summary="익명 사용자 원본 요약",
        )
    )
    isolated_db.commit()

    # 인증 사용자 조회 거부
    assert _get_state_by_key(isolated_db, anon_session_key, user_id=user1.id, create=False) is None

    # 인증 사용자 갱신 거부
    assert (
        remember_chat_interaction(
            isolated_db, anon_session_key, user_id=user1.id, message="인증 사용자 오염 시도"
        )
        is None
    )

    # 익명 세션 상태 보존 확인
    db_state = isolated_db.execute(
        select(ChatSessionState).where(ChatSessionState.session_key == anon_session_key)
    ).scalar_one()
    assert db_state.user_id is None
    assert db_state.last_query == "익명 사용자 원본 질의"


def test_user_memory_key_creation_prevented_for_mismatched_user(isolated_db, user1, user2):
    """미생성 상태의 user: 키를 타 사용자 또는 익명 사용자가 선점 생성할 수 없습니다."""
    uncreated_user1_key = f"user:{user1.id}"

    # 사용자2 가 user:1 생성 시도 -> None
    state_u2 = _get_state_by_key(isolated_db, uncreated_user1_key, user_id=user2.id, create=True)
    assert state_u2 is None

    # 익명 사용자가 user:1 생성 시도 -> None
    state_anon = _get_state_by_key(isolated_db, uncreated_user1_key, user_id=None, create=True)
    assert state_anon is None

    # 익명 사용자가 user:None 또는 user: 임의 키 생성 시도 -> None
    state_anon_random = _get_state_by_key(isolated_db, "user:9999", user_id=None, create=True)
    assert state_anon_random is None

    # DB 에 행이 생성되지 않았음을 검증
    created_row = isolated_db.execute(
        select(ChatSessionState).where(ChatSessionState.session_key == uncreated_user1_key)
    ).scalar_one_or_none()
    assert created_row is None


def test_ensure_session_key_sanitizes_user_memory_prefix():
    """ensure_session_key 는 user: 접두사 세션 키를 감지하여 새로운 고유 UUID 로 대체합니다."""
    generated = ensure_session_key("user:1")
    assert generated != "user:1"
    assert not generated.startswith("user:")
    assert len(generated) >= 32

    # 정상 세션 키는 그대로 유지
    normal_key = "sess-normal-123"
    assert ensure_session_key(normal_key) == normal_key


def test_chat_api_cross_user_idor_isolation_e2e(client, isolated_db, user1, user2):
    """POST /api/v1/chatbot/chat 엔드포인트에서 타 사용자 세션 키 지정 시 IDOR 격리가 유지됩니다."""
    from src.app.api.v1.accounts import get_current_user
    from src.app.main import app

    u1_id = user1.id
    u2_id = user2.id

    # 1. 사용자1 로 세션 전환 확인
    app.dependency_overrides[get_current_user] = lambda: isolated_db.get(CustomUser, u1_id)
    try:
        u1_session = "sess-u1-api-test"
        isolated_db.add(
            ChatSessionState(
                session_key=u1_session,
                user_id=u1_id,
                last_query="사용자1 공고 분석 요청",
                last_result_summary="사용자1 공고 분석 결과 요약",
                chat_history_json=[
                    {"role": "user", "text": "사용자1 공고 분석 요청"},
                    {"role": "model", "text": "사용자1 공고 분석 결과 요약"},
                ],
            )
        )
        isolated_db.commit()

        resp_u1 = client.post(
            "/api/v1/chatbot/chat",
            json={"session_key": u1_session, "message": ""},
        )
        assert resp_u1.status_code == 200
        data_u1 = resp_u1.json()
        assert data_u1["last_query"] == "사용자1 공고 분석 요청"
        assert len(data_u1["history"]) == 2
    finally:
        app.dependency_overrides.pop(get_current_user, None)

    # 2. 사용자2 로 사용자1 의 session_key 전환 시도 -> 빈 컨텍스트 반환
    app.dependency_overrides[get_current_user] = lambda: isolated_db.get(CustomUser, u2_id)
    try:
        resp_u2_switch = client.post(
            "/api/v1/chatbot/chat",
            json={"session_key": u1_session, "message": ""},
        )
        assert resp_u2_switch.status_code == 200
        data_u2 = resp_u2_switch.json()
        assert data_u2.get("last_query") == ""
        assert data_u2.get("history") == []
        assert data_u2.get("answer") == ""
    finally:
        app.dependency_overrides.pop(get_current_user, None)
