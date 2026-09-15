"""
tests/test_session_key_column_length.py

익명 대화 세션 키 길이의 DB 컬럼(VARCHAR(64)) 정합성 검증 테스트.
(a) generate_signed_session_key 결과 길이가 ChatSessionState 컬럼 길이 이하
(b) 이전 76자 형식 키의 verify_session_key 검증 실패
(c) 64자 초과 평문 키가 ensure_session_key 에서 새 서명 키로 교체됨
"""

import base64
import hashlib
import hmac
import uuid

from src.app.core.config import settings
from src.app.models.chatbot import ChatSessionState
from src.app.services.conversation_state import (
    SESSION_KEY_MAX_LENGTH,
    SESSION_KEY_SALT,
    SESSION_KEY_SIGNATURE_LENGTH,
    ensure_session_key,
    generate_signed_session_key,
    verify_session_key,
)


def test_generated_signed_session_key_fits_column_length():
    """발급된 서명 세션 키의 길이가 DB 컬럼(VARCHAR(64)) 이하임을 검증합니다."""
    column_length = ChatSessionState.__table__.c.session_key.type.length
    assert column_length == 64
    assert SESSION_KEY_MAX_LENGTH == 64
    assert SESSION_KEY_SIGNATURE_LENGTH == 31

    for _ in range(50):
        key = generate_signed_session_key()
        assert len(key) <= column_length
        assert len(key) == SESSION_KEY_MAX_LENGTH
        assert verify_session_key(key) is True


def test_legacy_76_char_session_key_verification_fails():
    """이전 76자 형식(43자 서명) 세션 키는 verify_session_key 에서 거부됩니다."""
    raw_id = uuid.uuid4().hex
    assert len(raw_id) == 32

    digest = hmac.new(
        f"{settings.SECRET_KEY}:{SESSION_KEY_SALT}".encode(),
        raw_id.encode(),
        hashlib.sha256,
    ).digest()
    legacy_full_sig = base64.urlsafe_b64encode(digest).decode().rstrip("=")
    assert len(legacy_full_sig) == 43

    legacy_76_key = f"{raw_id}:{legacy_full_sig}"
    assert len(legacy_76_key) == 76

    # 1. 검증 실패 확인
    assert verify_session_key(legacy_76_key) is False

    # 2. ensure_session_key 에서 새 키로 재발급 확인
    reissued = ensure_session_key(legacy_76_key, user_id=None)
    assert reissued != legacy_76_key
    assert len(reissued) <= ChatSessionState.__table__.c.session_key.type.length
    assert len(reissued) == SESSION_KEY_MAX_LENGTH
    assert verify_session_key(reissued) is True


def test_ensure_session_key_replaces_overlength_plain_keys():
    """64자를 초과하는 평문 키는 익명 및 인증 사용자 모두에게서 새 서명 키로 교체됩니다."""
    column_length = ChatSessionState.__table__.c.session_key.type.length
    overlength_plain_key = "a" * 65

    # 1. 익명 사용자(user_id=None)
    issued_anon = ensure_session_key(overlength_plain_key, user_id=None)
    assert issued_anon != overlength_plain_key
    assert len(issued_anon) <= column_length
    assert len(issued_anon) == SESSION_KEY_MAX_LENGTH
    assert verify_session_key(issued_anon) is True

    # 2. 인증 사용자(user_id=1)
    issued_auth = ensure_session_key(overlength_plain_key, user_id=1)
    assert issued_auth != overlength_plain_key
    assert len(issued_auth) <= column_length
    assert len(issued_auth) == SESSION_KEY_MAX_LENGTH
    assert verify_session_key(issued_auth) is True

    # 3. 미지정 사용자(user_id=_UNSET)
    issued_unset = ensure_session_key(overlength_plain_key)
    assert issued_unset != overlength_plain_key
    assert len(issued_unset) <= column_length
    assert len(issued_unset) == SESSION_KEY_MAX_LENGTH
    assert verify_session_key(issued_unset) is True

    # 4. 정상 길이(64자 이하) 평문 키는 인증 사용자에게 유지됨
    valid_plain_key = "valid-legacy-key-under-64"
    assert len(valid_plain_key) <= column_length
    preserved_auth = ensure_session_key(valid_plain_key, user_id=1)
    assert preserved_auth == valid_plain_key


def test_signed_session_key_persists_in_database(isolated_db):
    """새로 발급된 64자 세션 키가 ChatSessionState 테이블에 정상 저장됩니다."""
    key = generate_signed_session_key()
    state = ChatSessionState(
        session_key=key,
        user_id=None,
        last_query="테스트 질의",
        last_result_summary="테스트 요약",
    )
    isolated_db.add(state)
    isolated_db.commit()
    isolated_db.refresh(state)

    assert state.id is not None
    assert state.session_key == key
