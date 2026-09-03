"""
tests/test_automation_token_single_consumption.py

자동화 실행 확인 토큰의 Redis 기반 원자적 단일 소비(SET NX EX) 및 멱등성 검증.
 - 동시 요청(스레드 동시 실행) 시 정확히 1회만 소비 성공
 - 동일 토큰으로 연속 호출 시 1회만 200 성공 및 큐잉, 이후 403 거부
 - 이미 소비된 토큰 재사용 거부(403)
 - Redis 장애/미가용 시 fail-closed 거부(403)
 - 조건부 UPDATE(confirmed_at IS NULL)를 통한 DB 레벨 이중 큐잉 방지
 - 실제 Redis/MySQL 서버 없이 FakeRedis 대역 기반 동작
"""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from src.app.core.cache import RedisConnection
from src.app.models.chatbot import AutomationRequest
from src.app.services.automation_orchestrator import (
    STATUS_PENDING_CONFIRMATION,
    confirm_automation_request,
)
from src.app.services.automation_tokens import (
    AutomationError,
    consume_confirmation_token,
    make_confirmation_token,
)


class ThreadSafeFakeRedisClient:
    """SET NX EX 원자적 의미론을 제공하는 스레드 안전 Fake Redis 클라이언트."""

    def __init__(self, store: dict[str, Any] | None = None):
        self._lock = threading.Lock()
        self._store: dict[str, Any] = store if store is not None else {}

    def set(
        self,
        key: str,
        value: Any,
        ex: int | None = None,
        nx: bool = False,
        xx: bool = False,
    ) -> bool | None:
        with self._lock:
            if nx:
                if key in self._store:
                    return None
                self._store[key] = value
                return True
            if xx:
                if key in self._store:
                    self._store[key] = value
                    return True
                return None
            self._store[key] = value
            return True

    def get(self, key: str) -> Any:
        with self._lock:
            return self._store.get(key)

    def delete(self, *keys: str) -> int:
        with self._lock:
            count = 0
            for k in keys:
                if self._store.pop(k, None) is not None:
                    count += 1
            return count

    def ping(self) -> bool:
        return True


class ThreadSafeFakeRedisConnection(RedisConnection):
    def __init__(self, client: Any = None):
        super().__init__(label="fake_automation_tokens")
        self._client = client or ThreadSafeFakeRedisClient()

    def client(self) -> Any:
        return self._client

    def invalidate(self, exc: Exception) -> None:
        pass


@pytest.fixture
def fake_redis_conn():
    return ThreadSafeFakeRedisConnection(ThreadSafeFakeRedisClient())


def test_token_consumed_atomically_with_set_nx(fake_redis_conn):
    """동일 토큰에 대해 첫 번째 소비만 성공하고 이후 소비는 거부된다."""
    job_id = "job-atomic-001"
    token = make_confirmation_token(job_id)

    # 1회차 소비: 성공
    consume_confirmation_token(token, conn=fake_redis_conn)

    # 2회차 소비: 이미 사용된 토큰으로 거부
    with pytest.raises(AutomationError) as exc_info:
        consume_confirmation_token(token, conn=fake_redis_conn)
    assert "이미 사용된 확인 토큰입니다" in str(exc_info.value)


def test_different_tokens_consumed_independently(fake_redis_conn):
    """서로 다른 토큰은 독립적으로 각각 1회씩 소비될 수 있다."""
    token1 = make_confirmation_token("job-001")
    token2 = make_confirmation_token("job-002")

    consume_confirmation_token(token1, conn=fake_redis_conn)
    consume_confirmation_token(token2, conn=fake_redis_conn)

    with pytest.raises(AutomationError):
        consume_confirmation_token(token1, conn=fake_redis_conn)
    with pytest.raises(AutomationError):
        consume_confirmation_token(token2, conn=fake_redis_conn)


def test_concurrent_token_consumption_with_threads(fake_redis_conn):
    """멀티 스레드 환경에서 동일 확인 토큰으로 동시 consume 시도 시 정확히 1개 스레드만 성공한다."""
    token = make_confirmation_token("job-concurrent-thread-001")
    results: list[str] = []
    errors: list[str] = []

    def try_consume():
        try:
            consume_confirmation_token(token, conn=fake_redis_conn)
            results.append("success")
        except AutomationError as exc:
            errors.append(str(exc))

    with ThreadPoolExecutor(max_workers=5) as executor:
        futures = [executor.submit(try_consume) for _ in range(5)]
        for f in futures:
            f.result()

    assert len(results) == 1
    assert len(errors) == 4
    for err in errors:
        assert "이미 사용된 확인 토큰입니다" in err


def test_token_consumption_fails_closed_when_redis_unavailable():
    """Redis 연결이 불가할 때 fail-closed 정책에 따라 예외를 발생시키며 거부한다."""
    token = make_confirmation_token("job-fail-closed-001")

    class UnreachableConnection(RedisConnection):
        def client(self) -> Any:
            return None

    unreachable_conn = UnreachableConnection(label="unreachable")
    with pytest.raises(AutomationError) as exc_info:
        consume_confirmation_token(token, conn=unreachable_conn)
    assert "Redis 연결이 불가능" in str(exc_info.value)


def test_token_consumption_fails_closed_on_redis_exception():
    """Redis 명령 실행 중 예외 발생 시 연결 폐기 후 fail-closed 거부한다."""
    token = make_confirmation_token("job-exc-001")

    mock_client = MagicMock()
    mock_client.set.side_effect = ConnectionResetError("Connection lost")

    class ErrorConnection(RedisConnection):
        def __init__(self):
            super().__init__(label="err_conn")
            self._client = mock_client
            self.invalidated = False

        def client(self) -> Any:
            return self._client

        def invalidate(self, exc: Exception) -> None:
            self.invalidated = True

    err_conn = ErrorConnection()
    with pytest.raises(AutomationError) as exc_info:
        consume_confirmation_token(token, conn=err_conn)
    assert "Redis 오류" in str(exc_info.value)
    assert err_conn.invalidated is True


def test_empty_token_raises_error(fake_redis_conn):
    """빈 토큰 전달 시 AutomationError 가 발생한다."""
    with pytest.raises(AutomationError) as exc_info:
        consume_confirmation_token("", conn=fake_redis_conn)
    assert "확인 토큰이 필요합니다" in str(exc_info.value)


def test_conditional_update_in_orchestrator_prevents_duplicate_execution(isolated_db: Session):
    """DB 조건부 UPDATE(confirmed_at IS NULL)로 동일 요청의 중복 큐잉이 방지된다."""
    request_obj = AutomationRequest(
        request_id="req-cond-update-001",
        user_id=1,
        intent_type="model_retrain",
        action_key="model_retrain",
        requested_text="재학습",
        pipeline_name="BIDBOX_Personal_Pipeline_Staging",
        status=STATUS_PENDING_CONFIRMATION,
        requires_confirmation=True,
    )
    isolated_db.add(request_obj)
    isolated_db.commit()
    isolated_db.refresh(request_obj)

    with patch(
        "src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True
    ) as mock_enqueue:
        # 첫 번째 확인: 조건부 UPDATE 성공 (rowcount=1) -> 큐잉 실행
        confirmed_1 = confirm_automation_request(isolated_db, request_obj)
        assert confirmed_1.confirmed_at is not None
        assert mock_enqueue.call_count == 1

        # 두 번째 확인: 조건부 UPDATE 실패 (rowcount=0) -> 큐잉 생략
        confirmed_2 = confirm_automation_request(isolated_db, request_obj)
        assert confirmed_2.confirmed_at is not None
        assert mock_enqueue.call_count == 1


def test_two_api_confirm_calls_with_same_token_queue_exactly_once(client, isolated_db: Session):
    """동일한 확인 토큰으로 API 연속 호출 시 첫 번째만 성공하고 두 번째는 403 거부되며 큐잉은 1회만 일어난다."""
    VALID_SIGNUP = {
        "username": "api-confirm-user",
        "password1": "StrongPass123!!",
        "password2": "StrongPass123!!",
        "nickname": "토큰테스터",
        "email": "apiconfirm@example.com",
        "birth_date": "1999-05-17",
        "gender": "M",
        "agree_terms": True,
        "agree_privacy": True,
    }
    client.post("/api/v1/accounts/signup", json=VALID_SIGNUP)
    client.post(
        "/api/v1/accounts/login",
        json={"username": "api-confirm-user", "password": "StrongPass123!!"},
    )
    import sqlalchemy

    from src.app.models.accounts import CustomUser

    user = isolated_db.execute(
        sqlalchemy.select(CustomUser).where(CustomUser.username == "api-confirm-user")
    ).scalar_one()
    user.is_staff = True
    isolated_db.commit()

    create_resp = client.post("/api/v1/automation/run/retrain", json={"reason": "단일 소비 검증"})
    assert create_resp.status_code == 200
    job_id = create_resp.json()["job"]["job_id"]
    token = create_resp.json()["confirmation_token"]

    shared_fake_conn = ThreadSafeFakeRedisConnection(ThreadSafeFakeRedisClient())

    with (
        patch("src.app.services.automation_tokens._confirmation_redis_conn", shared_fake_conn),
        patch(
            "src.app.services.automation_orchestrator._enqueue_arq_job", return_value=True
        ) as mock_enqueue,
    ):
        resp1 = client.post(
            f"/api/v1/automation/job/{job_id}/confirm",
            json={"confirmation_token": token},
        )
        resp2 = client.post(
            f"/api/v1/automation/job/{job_id}/confirm",
            json={"confirmation_token": token},
        )

        assert resp1.status_code == 200
        assert resp2.status_code == 403
        assert "이미 사용된 확인 토큰입니다" in resp2.json()["detail"]
        assert mock_enqueue.call_count == 1
