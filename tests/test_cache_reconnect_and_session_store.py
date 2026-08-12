"""
tests/test_cache_reconnect_and_session_store.py

캐시 재연결과 인증 세션 저장소 분리 검증.

이전 구현은 최초 연결 실패 시 `_connected` 를 True 로 굳혀 그 프로세스가
Redis 복구 후에도 영원히 다시 붙지 않았고, 인증 세션이 같은 캐시 싱글턴을
쓰는 탓에 로그인 상태가 프로세스 로컬 dict 로 조용히 내려갔습니다.

시간 경과가 필요한 검증은 time.time 을 monkeypatch 합니다. sleep 을 쓰면
테스트가 실제로 느려지고 백오프 값 변경에 취약해집니다.
"""

import sys

import pytest

from src.app.core import cache as cache_module
from src.app.core import security as security_module
from src.app.core.cache import CacheLayer, RedisConnection
from src.app.core.security import SessionStore, SessionStoreUnavailable

BACKOFF = 5.0


class FakeClock:
    def __init__(self, now: float = 1_000.0):
        self.now = now

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class FakeRedis:
    """setex/get/delete/ping 만 흉내 내는 최소 대역입니다."""

    def __init__(self):
        self.store: dict[str, str] = {}

    def ping(self):
        return True

    def setex(self, key, _ttl, value):
        self.store[key] = value

    def get(self, key):
        return self.store.get(key)

    def delete(self, key):
        self.store.pop(key, None)


class RecordingConnector:
    """redis 모듈 대신 붙는 연결 시도 기록기입니다."""

    def __init__(self, client=None):
        self.client = client
        self.attempts = 0

    def __call__(self, *_args, **_kwargs):
        self.attempts += 1
        if self.client is None:
            raise ConnectionError("Redis 연결 거부")
        return self.client


@pytest.fixture
def clock(monkeypatch):
    fake = FakeClock()
    # cache_module.time 과 security_module.time 은 같은 time 모듈입니다.
    monkeypatch.setattr(cache_module.time, "time", fake)
    return fake


def _install_connector(monkeypatch, connector) -> None:
    """RedisConnection 안의 `import redis` 가 대역을 잡게 합니다."""

    class FakeRedisModule:
        class Redis:
            from_url = staticmethod(connector)

    monkeypatch.setitem(sys.modules, "redis", FakeRedisModule)


def test_reconnects_after_backoff_elapses(monkeypatch, clock):
    connector = RecordingConnector(client=None)
    _install_connector(monkeypatch, connector)
    conn = RedisConnection(url="redis://unused/0", backoff_seconds=BACKOFF, label="test")

    assert conn.client() is None
    assert connector.attempts == 1

    # Redis 가 복구된 뒤 백오프가 지나면 다시 붙어야 합니다.
    fake_client = FakeRedis()
    connector.client = fake_client
    clock.advance(BACKOFF + 0.1)

    assert conn.client() is fake_client
    assert connector.attempts == 2


def test_does_not_retry_within_backoff_window(monkeypatch, clock):
    """장애 증폭 방지 회귀. 백오프 안에서는 연결 시도가 늘지 않아야 합니다."""
    connector = RecordingConnector(client=None)
    _install_connector(monkeypatch, connector)
    conn = RedisConnection(url="redis://unused/0", backoff_seconds=BACKOFF, label="test")

    assert conn.client() is None
    assert connector.attempts == 1

    clock.advance(BACKOFF - 0.1)
    for _ in range(20):
        assert conn.client() is None
    assert connector.attempts == 1


def test_runtime_failure_drops_client_and_reconnects(monkeypatch, clock):
    """운영 중 끊긴 연결도 폐기되어 백오프 뒤 다시 붙어야 합니다."""
    fake_client = FakeRedis()
    connector = RecordingConnector(client=fake_client)
    _install_connector(monkeypatch, connector)
    conn = RedisConnection(url="redis://unused/0", backoff_seconds=BACKOFF, label="test")

    assert conn.client() is fake_client
    conn.invalidate(ConnectionError("연결 끊김"))

    assert conn.client() is None
    clock.advance(BACKOFF + 0.1)
    assert conn.client() is fake_client
    assert connector.attempts == 2


def test_cache_layer_degrades_to_local_when_redis_down(monkeypatch, clock):
    """조회 캐시는 degrade 가 정상 동작입니다."""
    _install_connector(monkeypatch, RecordingConnector(client=None))
    layer = CacheLayer(connection=RedisConnection(backoff_seconds=BACKOFF, label="test"))

    layer.set("k", {"v": 1}, ttl=60)
    assert layer.get("k") == {"v": 1}

    clock.advance(61)
    assert layer.get("k") is None


def test_session_store_is_independent_of_query_cache(monkeypatch, clock):
    """조회 캐시의 degrade 가 인증 세션으로 전파되면 안 됩니다."""
    fake_client = FakeRedis()
    _install_connector(monkeypatch, RecordingConnector(client=fake_client))

    layer = CacheLayer(connection=RedisConnection(backoff_seconds=BACKOFF, label="cache"))
    store = SessionStore(
        connection=RedisConnection(backoff_seconds=BACKOFF, label="session"),
        allow_local_fallback=False,
    )
    assert store._conn is not layer._conn

    store.create("tok", {"user_id": 7, "username": "u"}, ttl=60)
    assert store.read("tok") == {"user_id": 7, "username": "u"}

    # 조회 캐시 연결만 끊고 백오프 안으로 묶어 로컬 degrade 상태로 만듭니다.
    layer._conn.invalidate(ConnectionError("연결 끊김"))
    layer.set("query", {"v": 1}, ttl=60)
    assert layer.get("query") == {"v": 1}
    assert layer._local  # 조회 캐시는 로컬로 내려갔습니다.

    # 세션은 여전히 Redis 를 보고 있어야 하고 fail-closed 도 발동하지 않습니다.
    assert store.read("tok") == {"user_id": 7, "username": "u"}
    assert store._local == {}
    assert fake_client.store[f"{security_module.SESSION_CACHE_PREFIX}tok"]


def test_session_store_fails_closed_when_redis_unavailable(monkeypatch, clock):
    """production 정책. Redis 불가 시 세션은 로컬로 내려가지 않고 실패합니다."""
    _install_connector(monkeypatch, RecordingConnector(client=None))
    store = SessionStore(
        connection=RedisConnection(backoff_seconds=BACKOFF, label="session"),
        allow_local_fallback=False,
    )

    with pytest.raises(SessionStoreUnavailable):
        store.create("tok", {"user_id": 1, "username": "u"}, ttl=60)
    with pytest.raises(SessionStoreUnavailable):
        store.read("tok")
    with pytest.raises(SessionStoreUnavailable):
        store.destroy("tok")


def test_read_session_distinguishes_absence_from_outage(monkeypatch, clock):
    """세션 없음은 None, 저장소 장애는 예외로 구분되어야 합니다."""
    fake_client = FakeRedis()
    _install_connector(monkeypatch, RecordingConnector(client=fake_client))
    store = SessionStore(
        connection=RedisConnection(backoff_seconds=BACKOFF, label="session"),
        allow_local_fallback=False,
    )

    assert store.read("없는토큰") is None

    store._conn.invalidate(ConnectionError("연결 끊김"))
    with pytest.raises(SessionStoreUnavailable):
        store.read("없는토큰")


def test_local_fallback_allowed_only_in_development(monkeypatch):
    store = SessionStore()

    monkeypatch.setattr(security_module.settings, "ENVIRONMENT", "development")
    assert store.local_fallback_allowed is True

    for env in ("staging", "production"):
        monkeypatch.setattr(security_module.settings, "ENVIRONMENT", env)
        assert store.local_fallback_allowed is False


def test_session_cookie_secure_flag_follows_environment(client, monkeypatch):
    from src.app.api.v1 import accounts as accounts_module

    # ENVIRONMENT 를 production 으로 바꾸면 세션 저장소도 fail-closed 가 됩니다.
    # 이 테스트가 보려는 것은 쿠키 속성뿐이므로 저장소는 로컬로 고정합니다.
    monkeypatch.setattr(security_module.session_store, "_allow_local_fallback", True)

    payload = {
        "username": "cookieuser",
        "password1": "StrongPass123!!",
        "password2": "StrongPass123!!",
        "nickname": "쿠키",
        "email": "cookie@example.com",
        "birth_date": "1990-01-01",
        "gender": "M",
        "agree_terms": True,
        "agree_privacy": True,
    }

    monkeypatch.setattr(accounts_module.settings, "ENVIRONMENT", "development")
    response = client.post("/api/v1/accounts/signup", json=payload)
    assert response.status_code == 200, response.text
    assert "secure" not in response.headers["set-cookie"].lower()

    monkeypatch.setattr(accounts_module.settings, "ENVIRONMENT", "production")
    response = client.post("/api/v1/accounts/login", json={"username": "cookieuser", "password": "StrongPass123!!"})
    assert response.status_code == 200, response.text
    set_cookie = response.headers["set-cookie"].lower()
    assert "secure" in set_cookie
    # CORS 가 allow_origins=["*"] + allow_credentials=True 인 동안 lax 가
    # cross-site 요청에 쿠키가 붙는 것을 막는 유일한 방어선입니다.
    assert "samesite=lax" in set_cookie
