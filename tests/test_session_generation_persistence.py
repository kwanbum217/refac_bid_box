"""전체 로그아웃 세대의 DB 정본·Redis 캐시 시험.

정본: .orca/capsules/task_8d27e79d61e4/capsule.yaml.
 - 세대의 정본은 accounts_session_generation 이고 Redis 키
   auth:user_epoch:<user_id> 는 TTL 을 가진 캐시다.
 - Redis 세대 키를 지워도(FLUSH 모사) 이미 무효화한 세션은 되살아나지 않는다.
 - 캐시 적중 시 요청 경로는 DB 를 치지 않는다.
 - 행 없는 사용자는 0 이고 그 0 도 캐시한다.
 - 연속 전체 로그아웃은 세대를 1, 2 로 올린다.
 - 사용자가 삭제되면 세대 행도 CASCADE 로 사라진다.
"""

from __future__ import annotations

from typing import Any

import pytest
from sqlalchemy import create_engine, event, select
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core import security
from src.app.core.db import Base
from src.app.core.security import (
    SESSION_GENERATION_PREFIX,
    SESSION_GENERATION_TTL_SECONDS,
    SessionStoreUnavailable,
    create_session,
    invalidate_all_sessions,
    read_session,
)
from src.app.core.timeutil import utcnow
from src.app.models.accounts import CustomUser, SessionGeneration


def _generation_key(user_id: int) -> str:
    return f"{SESSION_GENERATION_PREFIX}{user_id}"


class _FakeRedis:
    """세션·세대 시험이 쓰는 인메모리 Redis 대역. TTL 도 기록합니다."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def setex(self, key: str, ttl: int, value: Any) -> bool:
        self.store[key] = str(value)
        self.ttls[key] = int(ttl)
        return True

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                deleted += 1
            self.ttls.pop(key, None)
        return deleted

    def ttl(self, key: str) -> int:
        return self.ttls.get(key, -2)

    def flush_generation(self, user_id: int) -> None:
        """Redis FLUSH 로 세대 키만 사라진 상황을 모사합니다."""
        key = _generation_key(user_id)
        self.store.pop(key, None)
        self.ttls.pop(key, None)


class _StubConnection:
    """session_store 가 쓰는 RedisConnection 계약(client/invalidate) 대역."""

    def __init__(self, client: _FakeRedis) -> None:
        self._client = client

    def client(self) -> _FakeRedis:
        return self._client

    def invalidate(self, exc: BaseException | None = None) -> None:
        return None


class _GenerationEnv:
    def __init__(self, session: Session, session_open_count: dict[str, int]) -> None:
        self.session = session
        self.session_open_count = session_open_count


@pytest.fixture(autouse=True)
def _reset_local_sessions(monkeypatch):
    """Redis 대체 저장소(프로세스 로컬 dict)를 시험마다 비웁니다."""
    monkeypatch.setattr(security.session_store, "_local", {})


@pytest.fixture
def fake_redis(monkeypatch):
    """session_store 의 Redis 연결을 인메모리 대역으로 바꿉니다."""
    client = _FakeRedis()
    monkeypatch.setattr(security.session_store, "_conn", _StubConnection(client))
    return client


@pytest.fixture
def generation_env(monkeypatch):
    """FK CASCADE 가 켜진 인메모리 DB 로 SessionLocal 을 바꿔 끼웁니다.

    운영 코드는 src/app/core/security.py 안에서 SessionLocal 로 세션을 직접
    열므로, 같은 엔진을 내주는 팩터로 바꾸고 호출 횟수를 세어 요청 경로가
    DB 를 치는지 확인합니다.
    """
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session_open_count = {"count": 0}

    def counting_factory() -> Session:
        session_open_count["count"] += 1
        return factory()

    monkeypatch.setattr(security, "SessionLocal", counting_factory)
    session = factory()
    yield _GenerationEnv(session, session_open_count)
    session.close()
    Base.metadata.drop_all(engine)
    engine.dispose()


def _create_user(db: Session, username: str) -> CustomUser:
    user = CustomUser(
        username=username,
        password="pbkdf2_sha256$1$testsalt$testhash",
        email=f"{username}@example.com",
        nickname=username,
        is_active=True,
        is_staff=False,
        is_superuser=False,
        date_joined=utcnow(),
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def _stored_generation(db: Session, user_id: int) -> int | None:
    return db.execute(
        select(SessionGeneration.generation).where(SessionGeneration.user_id == user_id)
    ).scalar_one_or_none()


def test_flushed_generation_key_does_not_revive_invalidated_session(generation_env, fake_redis):
    """Redis 세대 키를 지워도 DB 정본에서 복원되어 옛 세션은 파기된다."""
    user = _create_user(generation_env.session, "gen_flush")
    token = create_session(user.id, user.username)

    assert invalidate_all_sessions(user.id) == 1
    fake_redis.flush_generation(user.id)

    assert read_session(token) is None
    assert fake_redis.store[_generation_key(user.id)] == "1"

    fresh_token = create_session(user.id, user.username)
    assert read_session(fresh_token) == {"user_id": user.id, "username": user.username}


def test_generation_key_is_cached_with_ttl(generation_env, fake_redis):
    """전체 로그아웃과 캐시 복원이 세대 키에 TTL 을 건다."""
    user = _create_user(generation_env.session, "gen_ttl")

    invalidate_all_sessions(user.id)
    key = _generation_key(user.id)
    assert fake_redis.ttls[key] == SESSION_GENERATION_TTL_SECONDS

    fake_redis.flush_generation(user.id)
    assert security.session_store.current_generation(user.id) == 1
    assert fake_redis.ttls[key] == SESSION_GENERATION_TTL_SECONDS


def test_missing_row_reads_zero_and_is_cached_without_db(generation_env, fake_redis):
    """행 없는 사용자는 0 이고, 그 0 이 캐시되어 두 번째 조회는 DB 를 치지 않는다."""
    user = _create_user(generation_env.session, "gen_zero")
    opened = generation_env.session_open_count["count"]

    assert security.session_store.current_generation(user.id) == 0
    assert generation_env.session_open_count["count"] == opened + 1
    assert fake_redis.store[_generation_key(user.id)] == "0"

    assert security.session_store.current_generation(user.id) == 0
    assert generation_env.session_open_count["count"] == opened + 1


def test_consecutive_bumps_increment_db_and_cache(generation_env, fake_redis):
    """연속 전체 로그아웃은 세대를 1, 2 로 올리고 캐시에도 같은 값을 쓴다."""
    user = _create_user(generation_env.session, "gen_bump")

    assert invalidate_all_sessions(user.id) == 1
    assert invalidate_all_sessions(user.id) == 2

    assert _stored_generation(generation_env.session, user.id) == 2
    assert fake_redis.store[_generation_key(user.id)] == "2"


def test_deleting_user_cascades_generation_row(generation_env, fake_redis):
    """사용자가 삭제되면 세대 행도 CASCADE 로 함께 사라진다."""
    user = _create_user(generation_env.session, "gen_cascade")
    invalidate_all_sessions(user.id)
    db = generation_env.session
    assert _stored_generation(db, user.id) == 1

    db.delete(user)
    db.commit()

    assert _stored_generation(db, user.id) is None


def test_db_read_failure_returns_zero_without_caching(monkeypatch, fake_redis):
    """DB 조회 실패는 경고 후 0 이며, 그 0 을 캐시에 남기지 않는다."""

    def unavailable_session() -> Session:
        raise OperationalError("SELECT generation", {}, Exception("DB 사용 불가"))

    monkeypatch.setattr(security, "SessionLocal", unavailable_session)

    assert security.session_store.current_generation(777001) == 0
    assert _generation_key(777001) not in fake_redis.store


def test_db_write_failure_is_fail_closed(monkeypatch, fake_redis):
    """DB 저장에 실패하면 무효화를 삼키지 않고 저장소 장애로 실패시킨다."""

    def unavailable_session() -> Session:
        raise OperationalError("INSERT generation", {}, Exception("DB 사용 불가"))

    monkeypatch.setattr(security, "SessionLocal", unavailable_session)

    with pytest.raises(SessionStoreUnavailable):
        invalidate_all_sessions(777002)
