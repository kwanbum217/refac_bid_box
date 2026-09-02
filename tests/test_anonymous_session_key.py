"""
tests/test_anonymous_session_key.py

익명 대화 세션 키의 서버 발급 서명 식별자 제한 및 격리 검증 테스트.
임의 문자열 세션 키 거부, 충돌 차단, 위조 서명 거부, 정상 복원,
인증 사용자 레거시 평문 키 복원 유지 등을 검증합니다.
"""

import pytest

from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser
from src.app.models.chatbot import ChatSessionState
from src.app.services.conversation_state import (
    _get_state_by_key,
    _resolve_user_memory_key,
    ensure_session_key,
    generate_signed_session_key,
    load_conversation_context,
    remember_chat_interaction,
    sign_session_key,
    verify_session_key,
)


@pytest.fixture
def auth_user1(isolated_db):
    row = CustomUser(
        username="auth_user1_test",
        password="x",
        email="auth1@example.com",
        nickname="인증사용자1",
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
def auth_user2(isolated_db):
    row = CustomUser(
        username="auth_user2_test",
        password="x",
        email="auth2@example.com",
        nickname="인증사용자2",
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    isolated_db.add(row)
    isolated_db.commit()
    isolated_db.refresh(row)
    return row


def test_sign_and_verify_session_key_roundtrip():
    """서버가 발급한 서명 키는 정상 검증되고 만료 없이 유효합니다."""
    key = generate_signed_session_key()
    assert verify_session_key(key) is True

    custom_raw = "12345678-1234-4321-abcd-1234567890ab"
    signed_custom = sign_session_key(custom_raw)
    assert verify_session_key(signed_custom) is True
    assert signed_custom.startswith(f"{custom_raw}:")


def test_verify_session_key_rejects_invalid_and_forged_keys():
    """임의 문자열, 형식 오류, 위조/변조된 서명은 모두 검증에서 거부됩니다."""
    # 평문 문자열
    assert verify_session_key("raw-arbitrary-key") is False
    assert verify_session_key("") is False
    assert verify_session_key(None) is False
    assert verify_session_key(":") is False
    assert verify_session_key("raw_id:") is False
    assert verify_session_key(":signature") is False

    # 위조 서명
    valid_key = generate_signed_session_key()
    raw_id, _ = valid_key.rsplit(":", 1)
    forged_key = f"{raw_id}:invalid_signature_abc123"
    assert verify_session_key(forged_key) is False

    # raw_id 변조
    _, signature = valid_key.rsplit(":", 1)
    tampered_id_key = f"tampered_id_{raw_id}:{signature}"
    assert verify_session_key(tampered_id_key) is False


def test_ensure_session_key_anonymous_rejects_raw_string_and_issues_signed_key():
    """익명 요청(user_id=None)에서 임의 문자열을 보내면 원본이 쓰이지 않고 새 서명 키가 발급됩니다."""
    raw_key = "client-chosen-session-key"
    issued = ensure_session_key(raw_key, user_id=None)

    assert issued != raw_key
    assert verify_session_key(issued) is True


def test_ensure_session_key_anonymous_preserves_valid_signed_key():
    """익명 요청(user_id=None)에서 유효한 서명 키를 보내면 해당 키가 그대로 유지됩니다."""
    valid_key = generate_signed_session_key()
    issued = ensure_session_key(valid_key, user_id=None)

    assert issued == valid_key


def test_ensure_session_key_sanitizes_user_memory_prefix_for_both():
    """user: 접두사 세션 키는 익명 및 인증 사용자 모두에게서 새 서명 키로 대체됩니다."""
    anon_sanitized = ensure_session_key("user:1", user_id=None)
    assert not anon_sanitized.startswith("user:")
    assert verify_session_key(anon_sanitized) is True

    auth_sanitized = ensure_session_key("user:1", user_id=1)
    assert not auth_sanitized.startswith("user:")
    assert verify_session_key(auth_sanitized) is True


def test_anonymous_collision_blocked_between_two_clients(isolated_db):
    """두 익명 클라이언트가 동일한 임의 세션 키를 지정해도 서로의 대화 상태에 도달하지 못합니다."""
    same_raw_key = "shared-attack-session-key"

    # 클라이언트 A (익명)
    key_a = ensure_session_key(same_raw_key, user_id=None)
    assert key_a != same_raw_key
    remember_chat_interaction(
        isolated_db,
        key_a,
        user_id=None,
        message="클라이언트 A 의 비밀 질문",
        answer_text="클라이언트 A 의 답변",
    )

    # 클라이언트 B (익명) - 동일한 raw 문자열 전송
    key_b = ensure_session_key(same_raw_key, user_id=None)
    assert key_b != same_raw_key
    assert key_a != key_b

    # 클라이언트 B 가 컨텍스트를 로드했을 때 클라이언트 A 의 내용이 노출되지 않음
    context_b = load_conversation_context(isolated_db, key_b, user_id=None)
    assert context_b.get("last_query") == ""
    assert context_b.get("last_result_summary") == ""
    assert context_b.get("chat_history") == []

    # 클라이언트 A 는 자신의 서명 키로 정상 조회
    context_a = load_conversation_context(isolated_db, key_a, user_id=None)
    assert context_a.get("last_query") == "클라이언트 A 의 비밀 질문"
    assert context_a.get("last_result_summary") == "클라이언트 A 의 답변"


def test_anonymous_valid_signed_key_resume_succeeds(isolated_db):
    """익명 요청이 서버 발급 서명 키를 되돌려 보내면 이전 대화 상태가 정상 복원됩니다."""
    valid_session_key = generate_signed_session_key()

    # 첫 턴 기록
    remember_chat_interaction(
        isolated_db,
        valid_session_key,
        user_id=None,
        message="첫 번째 질문",
        answer_text="첫 번째 답변",
    )

    # 복원 조회
    resolved_key = ensure_session_key(valid_session_key, user_id=None)
    assert resolved_key == valid_session_key

    context = load_conversation_context(isolated_db, resolved_key, user_id=None)
    assert context.get("last_query") == "첫 번째 질문"
    assert context.get("last_result_summary") == "첫 번째 답변"
    assert len(context.get("chat_history", [])) == 2


def test_authenticated_user_legacy_plain_key_resume_succeeds(isolated_db, auth_user1):
    """인증 사용자가 레거시 평문 키를 보내면 자기 소유일 때 정상 복원됩니다."""
    legacy_key = "legacy-plain-sess-user1-001"
    isolated_db.add(
        ChatSessionState(
            session_key=legacy_key,
            user_id=auth_user1.id,
            last_query="인증 사용자 레거시 질문",
            last_result_summary="인증 사용자 레거시 답변",
        )
    )
    isolated_db.commit()

    # ensure_session_key 는 인증 사용자에게 레거시 키를 보존
    resolved_key = ensure_session_key(legacy_key, user_id=auth_user1.id)
    assert resolved_key == legacy_key

    # 정상 복원
    state = _get_state_by_key(isolated_db, resolved_key, user_id=auth_user1.id, create=False)
    assert state is not None
    assert state.last_query == "인증 사용자 레거시 질문"


def test_authenticated_user_legacy_plain_key_cross_access_blocked(
    isolated_db, auth_user1, auth_user2
):
    """인증 사용자가 타인의 레거시 평문 키를 보내면 조회가 차단됩니다."""
    legacy_key = "legacy-plain-sess-user1-secret"
    isolated_db.add(
        ChatSessionState(
            session_key=legacy_key,
            user_id=auth_user1.id,
            last_query="사용자1 비밀 질문",
            last_result_summary="사용자1 비밀 답변",
        )
    )
    isolated_db.commit()

    # 사용자2 가 사용자1 의 레거시 키 조회 시도 -> 차단
    state = _get_state_by_key(isolated_db, legacy_key, user_id=auth_user2.id, create=False)
    assert state is None


def test_post_session_new_api_returns_signed_key(client):
    """POST /api/v1/chatbot/session/new 가 서명된 키를 반환합니다."""
    response = client.post("/api/v1/chatbot/session/new")
    assert response.status_code == 200
    data = response.json()
    assert data.get("status") == "success"
    session_key = data.get("session_key")
    assert session_key is not None
    assert verify_session_key(session_key) is True


def test_resolve_user_memory_key_format_preserved():
    """_resolve_user_memory_key 의 반환 형식이 user:{user_id} 로 불변 보존됩니다."""
    assert _resolve_user_memory_key(1) == "user:1"
    assert _resolve_user_memory_key(42) == "user:42"
    assert _resolve_user_memory_key(None) == ""


def test_chat_api_anonymous_switch_and_isolation_e2e(client, isolated_db):
    """POST /api/v1/chatbot/chat 엔드포인트에서 익명 세션의 서명 키 복원 및 임의 키 차단 E2E."""
    # 1. 서버 발급 서명 키로 세션 생성 및 대화 기록
    valid_key = generate_signed_session_key()
    isolated_db.add(
        ChatSessionState(
            session_key=valid_key,
            user_id=None,
            last_query="익명 공고 검색",
            last_result_summary="익명 공고 검색 요약",
            chat_history_json=[
                {"role": "user", "text": "익명 공고 검색"},
                {"role": "model", "text": "익명 공고 검색 요약"},
            ],
        )
    )
    isolated_db.commit()

    # 2. 유효한 서명 키로 세션 전환 요청 (메시지 빈 문자열)
    resp_valid = client.post(
        "/api/v1/chatbot/chat",
        json={"session_key": valid_key, "message": ""},
    )
    assert resp_valid.status_code == 200
    data_valid = resp_valid.json()
    assert data_valid["session_key"] == valid_key
    assert data_valid["last_query"] == "익명 공고 검색"
    assert len(data_valid["history"]) == 2

    # 3. 임의 문자열 세션 키로 세션 전환 시도 -> 새 서명 키가 발급되고 빈 상태 반환
    resp_tamper = client.post(
        "/api/v1/chatbot/chat",
        json={"session_key": "arbitrary_attacker_key", "message": ""},
    )
    assert resp_tamper.status_code == 200
    data_tamper = resp_tamper.json()
    assert data_tamper["session_key"] != "arbitrary_attacker_key"
    assert verify_session_key(data_tamper["session_key"]) is True
    assert data_tamper["last_query"] == ""
    assert data_tamper["history"] == []
