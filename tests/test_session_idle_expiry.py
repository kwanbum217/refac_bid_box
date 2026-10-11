"""
tests/test_session_idle_expiry.py

보안 검토 L11 보강 검증:
  - 세션에 유휴 만료 7일을 추가한다. 7일 넘게 활동이 없으면 세션을 파기한다.
  - 활동이 있으면 마지막 활동 시각을 갱신하되, 쓰기 부담을 줄이려 일정 간격
    (SESSION_ACTIVITY_REFRESH_SECONDS) 이상 지났을 때만 쓴다.
  - 절대 수명 14일은 그대로다. 갱신은 남은 TTL 을 유지한다.
  - 마지막 활동 시각이 없는 기존 세션은 배포 직후 일괄 로그아웃되지 않는다.

시간은 security 모듈의 time 을 가짜 시계로 monkeypatch 해 제어한다.
Redis 는 인메모리 대역을 써 실제 서버에 붙지 않는다.
"""

from __future__ import annotations

import pytest

from src.app.core import security

DAY = 60 * 60 * 24


class _Clock:
    def __init__(self, now: float):
        self.now = now

    def time(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class _FakeRedis:
    """SessionStore 가 쓰는 setex/get/delete/ttl 만 구현한 Redis 대역.

    TTL 을 절대 만료 시각으로 들고 가짜 시계로 감소시킵니다. 그래야 남은 TTL 을
    다시 쓰는 갱신이 절대 만료를 연장하지 않는지 검증할 수 있습니다.
    """

    def __init__(self, now_fn) -> None:
        self._now = now_fn
        self.store: dict[str, str] = {}
        self.deadlines: dict[str, float] = {}

    def setex(self, key: str, ttl: int, value: str) -> None:
        self.store[key] = value
        self.deadlines[key] = self._now() + int(ttl)

    def get(self, key: str) -> str | None:
        deadline = self.deadlines.get(key)
        if deadline is not None and deadline <= self._now():
            self.delete(key)
            return None
        return self.store.get(key)

    def delete(self, key: str) -> None:
        self.store.pop(key, None)
        self.deadlines.pop(key, None)

    def ttl(self, key: str) -> int:
        deadline = self.deadlines.get(key)
        if deadline is None:
            return -2
        return int(deadline - self._now())


@pytest.fixture
def clock(monkeypatch):
    c = _Clock(1_700_000_000.0)
    monkeypatch.setattr(security, "time", c)
    return c


@pytest.fixture
def local_session_store(monkeypatch):
    store = security.session_store
    monkeypatch.setattr(store, "_local", {})
    monkeypatch.setattr(store, "_allow_local_fallback", True)
    monkeypatch.setattr(store._conn, "client", lambda: None)
    return store


@pytest.fixture
def redis_session_store(monkeypatch, clock):
    fake = _FakeRedis(lambda: clock.now)
    store = security.session_store
    monkeypatch.setattr(store, "_local", {})
    monkeypatch.setattr(store._conn, "client", lambda: fake)
    return store, fake


# --------------------------------------------------------------------------- #
# local 저장소
# --------------------------------------------------------------------------- #


def test_local_session_survives_within_idle_window(local_session_store, clock):
    token = security.create_session(1, "idle-user")
    clock.advance(6 * DAY)
    assert security.read_session(token) is not None


def test_local_session_expires_after_idle_timeout(local_session_store, clock):
    token = security.create_session(1, "idle-user")
    clock.advance(7 * DAY + 1)
    assert security.read_session(token) is None
    assert token not in local_session_store._local


def test_read_hides_internal_activity_key(local_session_store, clock):
    token = security.create_session(7, "leak-user")
    payload = security.read_session(token)
    assert payload == {"user_id": 7, "username": "leak-user"}
    assert security.SESSION_ACTIVITY_KEY not in payload


def test_local_activity_refresh_extends_idle_window(local_session_store, clock):
    token = security.create_session(1, "long-user")
    clock.advance(6 * DAY)
    assert security.read_session(token) is not None  # 활동 시각 갱신

    clock.advance(6 * DAY)  # 마지막 활동 후 6일, 생성 후 12일
    assert security.read_session(token) is not None

    clock.advance(3 * DAY)  # 생성 후 15일 > 절대 수명 14일
    assert security.read_session(token) is None


def test_local_activity_refresh_is_throttled(local_session_store, clock):
    token = security.create_session(1, "throttle-user")
    key = security.SESSION_ACTIVITY_KEY
    created = local_session_store._local[token][1][key]

    clock.advance(60)
    security.read_session(token)
    assert local_session_store._local[token][1][key] == created

    clock.advance(security.SESSION_ACTIVITY_REFRESH_SECONDS)
    security.read_session(token)
    assert local_session_store._local[token][1][key] == clock.now


def test_legacy_session_without_activity_is_not_invalidated(local_session_store, clock):
    legacy_session_id = "legacy-session"
    local_session_store._local[legacy_session_id] = (
        clock.now + security.SESSION_TTL_SECONDS,
        {"user_id": 1, "username": "legacy"},
    )
    clock.advance(10 * DAY)
    assert security.read_session(legacy_session_id) == {"user_id": 1, "username": "legacy"}
    assert legacy_session_id in local_session_store._local


# --------------------------------------------------------------------------- #
# Redis 저장소
# --------------------------------------------------------------------------- #


def test_redis_activity_refresh_preserves_absolute_expiry(redis_session_store, clock):
    store, fake = redis_session_store
    token = security.create_session(1, "redis-user")
    key = store._key(token)
    absolute = fake.deadlines[key]
    assert fake.ttl(key) == security.SESSION_TTL_SECONDS

    clock.advance(6 * DAY)
    assert security.read_session(token) is not None
    # 활동 시각은 갱신하되 절대 만료(14일)는 연장되지 않는다.
    assert fake.deadlines[key] == absolute
    assert fake.ttl(key) == security.SESSION_TTL_SECONDS - 6 * DAY


def test_redis_session_expires_after_idle_timeout(redis_session_store, clock):
    store, fake = redis_session_store
    token = security.create_session(1, "redis-user")
    clock.advance(7 * DAY + 1)
    assert security.read_session(token) is None
    assert store._key(token) not in fake.store
