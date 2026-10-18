"""
tests/conftest.py

공통 pytest fixture.
 - SKIP_MODEL_LOAD 로 무거운 joblib 로드를 건너뜁니다.
 - isolated_db fixture 로 SQLite 인메모리 DB 를 사용해 쓰기 테스트를 격리합니다.
 - 임베딩은 ChromaDB 내장 함수로 고정합니다. 운영 기본값(Ollama bge-m3)을
   그대로 쓰면 테스트가 로컬 Ollama 에 의존해 CI 에서 깨집니다. 임베딩 배선
   자체는 tests/test_rag_embeddings.py 가 따로 검증합니다.
 - MLOps 웹훅은 빈 값으로 강제합니다. 2026-08-06 에 .env 로 실제 Slack URL 이
   들어오자 재학습 실패/빈 데이터셋 테스트가 운영 채널로 경고를 실제 발신했습니다.
   notifier 의 발신 조건이 URL 존재 여부 하나뿐이므로 여기서 끊습니다.
 - _fast_password fixture 가 PBKDF2 반복 횟수를 1회로 줄입니다.
   Windows CI 에서 pbkdf2_sha256 600,000회 반복이 테스트당 ~4.6초를 균일하게
   소비합니다. macOS 는 OpenSSL 하드웨어 가속으로 47ms 이지만 Windows CPython 은
   약 2,300ms 이며, 회원가입(make_password 1회) 과 로그인(check_password 내부
   make_password 1회) 에서 각 1회씩 호출되므로 합계 ~4.6초가 20개 이상의 테스트에서
   균일하게 나타납니다. 이 fixture 는 암호학적 강도를 검증하지 않는 테스트가
   password hashing 비용을 부담하지 않도록 make_password 와 check_password 를
   1회 반복 버전으로 대체합니다. 운영 코드에는 영향을 주지 않습니다.
 - _fast_fail_local_services fixture 가 로컬 Redis·Ollama 연결을 즉시 실패시킵니다.
   Windows 는 닫힌 localhost 포트 연결이 4.33초 뒤에 실패해 로그인 테스트마다 그만큼 기다렸습니다.
"""

import hashlib
import os

os.environ.setdefault("SKIP_MODEL_LOAD", "true")
os.environ.setdefault("EMBEDDING_PROVIDER", "default")
os.environ.setdefault("SECRET_KEY", "test-only-secret-key-at-least-32-characters")
# setdefault 가 아니라 대입입니다. 셸에 export 된 값이 있어도 막아야 합니다.
os.environ["MLOPS_WEBHOOK_URL"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from src.app.core.db import Base, get_db
from src.app.main import app  # 모든 모델이 Base.metadata 에 등록되도록 import

# 테스트 전용 결정적 임베딩 차원. chromadb 는 모든 벡터 길이만 같으면 됩니다.
TEST_EMBEDDING_DIMENSION = 32


class DeterministicTestEmbeddingFunction:
    """테스트 전용 결정적 가짜 임베딩 함수.

    chromadb 의 기본 임베딩 함수(ONNXMiniLM_L6_V2)는 첫 호출에 all-MiniLM-L6-v2
    ONNX 모델을 인터넷에서 내려받아 압축을 풀고 ONNX 런타임으로 추론합니다.
    그러면 테스트가 네트워크와 로컬 캐시(~/.cache/chroma)에 의존해, 캐시가 없는
    CI 에서만 다운로드가 일어나고 tar.extractall DeprecationWarning 이 발생했습니다
    (2026-09-22 경고 예산 잡 1 warning 의 출처).

    문자열 SHA-256 해시를 고정 차원 float 벡터로 펼칩니다. 같은 입력에는 항상 같은
    벡터를 주고 네트워크, 파일 다운로드, ONNX 런타임을 쓰지 않습니다. 의미적
    유사도는 없으므로 검색 순위나 거리 값을 단언하는 테스트에는 쓸 수 없습니다
    (현재 그런 테스트는 없습니다).

    chromadb 의 EmbeddingFunction 규약(__call__(self, input) 이 문서 수만큼의 벡터를
    돌려줌)을 그대로 따르므로 운영 경로와 같은 자리에 끼워 넣을 수 있습니다.
    """

    def __init__(self, dimension: int = TEST_EMBEDDING_DIMENSION) -> None:
        self.dimension = dimension

    def __call__(self, input: list[str]) -> list[list[float]]:
        return [self._vector(text) for text in input]

    def _vector(self, text: str) -> list[float]:
        values: list[float] = []
        digest = hashlib.sha256(text.encode("utf-8")).digest()
        while len(values) < self.dimension:
            values.extend(byte / 255.0 for byte in digest)
            if len(values) < self.dimension:
                digest = hashlib.sha256(digest).digest()
        return values[: self.dimension]


_TEST_EMBEDDING_FUNCTION = DeterministicTestEmbeddingFunction()


@pytest.fixture
def deterministic_embedding_function():
    """테스트 전역에서 쓰는 결정적 가짜 임베딩 함수 인스턴스."""
    return _TEST_EMBEDDING_FUNCTION


@pytest.fixture(autouse=True)
def _deterministic_test_embedding(monkeypatch):
    """테스트 중 chromadb 기본 ONNX 임베딩 대신 결정적 가짜를 쓰게 합니다.

    conftest 는 EMBEDDING_PROVIDER 를 default 로 두므로
    src.rag.embeddings.get_embedding_function() 이 None 을 돌려주고, get_collection 은
    embedding_function 을 넘기지 않습니다. 그 자리에서 chromadb 가 기본값으로 끼워
    넣는 ONNXMiniLM_L6_V2 를 이 fixture 가 가짜로 바꿔 끼웁니다.

    get_embedding_function 자체는 건드리지 않습니다. tests/test_rag_embeddings.py 가
    운영 분기(default -> None, ollama 어댑터 선택)를 그대로 검증해야 하므로, 검색
    함수 대신 컬렉션을 여는 chromadb 클라이언트 메서드에서 기본값만 대체합니다.
    클라이언트가 embedding_function 을 명시로 받으면 그대로 둡니다.

    운영 코드는 바뀌지 않으며 이 프로세스의 테스트 실행에만 적용됩니다.
    """
    import functools

    from chromadb.api.client import Client

    def force_deterministic(original):
        @functools.wraps(original)
        def wrapper(self, *args, **kwargs):
            if kwargs.get("embedding_function") is None:
                kwargs["embedding_function"] = _TEST_EMBEDDING_FUNCTION
            return original(self, *args, **kwargs)

        return wrapper

    classes = [Client]
    try:
        from chromadb.api.async_client import AsyncClient
    except ImportError:
        pass
    else:
        classes.append(AsyncClient)

    for cls in classes:
        for name in ("get_collection", "get_or_create_collection", "create_collection"):
            original = getattr(cls, name, None)
            if original is None:
                continue
            monkeypatch.setattr(cls, name, force_deterministic(original))


@pytest.fixture(autouse=True)
def _isolate_process_cache(monkeypatch):
    """모든 테스트가 로컬 Redis 대신 테스트마다 비워지는 메모리 캐시를 쓰게 합니다.

    RAG 캐시 키는 SQL 문자열 해시라 DB 가 달라도 같습니다. 로컬에 Redis 가 떠 있으면
    테스트가 넣은 값을 다음 실행의 테스트와 개발용 앱이 1시간 동안 받아 갑니다
    (2026-09-13 기관명 해석 캐시로 test_rag_engine 두 건이 로컬에서만 실패했고, 전량 실행이
    rag:* 키 116개를 남겼습니다). 특정 캐시 상태가 필요한 테스트는 이 뒤에 다시 덮어씁니다.
    """
    from src.app.core.cache import cache

    monkeypatch.setattr(cache._conn, "_client", None)
    monkeypatch.setattr(cache._conn, "_next_attempt_at", float("inf"))
    monkeypatch.setattr(cache, "_local", {})


@pytest.fixture(autouse=True)
def _isolate_promotion_audit_log(tmp_path):
    """승격 감사 로그가 테스트마다 임시 디렉터리로 가게 합니다.

    승격을 부르는 테스트가 audit_log_path 를 넘기지 않으면 src.ml.promotion 의
    기본 경로로 append 되고, 그 기본값이 운영 로그(data/promotion_audit.log)입니다.
    2026-09-21 확인 결과 이 파일 9,245줄 중 9,244줄이 테스트의 test_model 기록이었고,
    마지막 기록 시각이 전량 테스트 실행 시각과 일치했습니다. 테스트가 운영 승격
    이력을 오염시키지 않도록 기본 경로를 임시 디렉터리로 돌립니다.

    scripts/promote_model 은 임포트 시점에 `from src.ml.promotion import AUDIT_LOG_PATH`
    로 값을 **복사**해 argparse 기본값(str)으로 굳혀 둡니다. 원본만 바꾸면 CLI 경로는
    여전히 운영 로그로 가므로 두 이름을 함께 바꿉니다.

    전용 MonkeyPatch 인스턴스를 씁니다. pytest 의 monkeypatch fixture 는 함수 스코프
    동안 공유되어, 테스트가 자기 monkeypatch.undo() 를 부르면(test_promotion_gate 의
    재승격 킬 시뮬레이션이 그렇습니다) 이 격리 패치까지 함께 풀려 운영 로그로 샙니다.

    운영 코드의 기본 경로와 동작은 바꾸지 않습니다. teardown 에서 원래 값으로 복구됩니다.
    """
    from scripts import promote_model
    from src.ml import promotion

    isolated = tmp_path / "promotion_audit.log"
    patcher = pytest.MonkeyPatch()
    patcher.setattr(promotion, "AUDIT_LOG_PATH", isolated)
    patcher.setattr(promote_model, "AUDIT_LOG_PATH", isolated)
    yield
    patcher.undo()


@pytest.fixture(autouse=True)
def _stub_restriction_collection(monkeypatch):
    """collect_bids 가 부르는 면허제한정보·참가가능지역 수집을 기본으로 0건 가짜로 바꿉니다.

    공고·낙찰 수집만 가짜로 바꾼 기존 테스트가 이 두 호출로 실제 조달청 API 에 나갑니다.
    로컬은 .env 인증키로 성공해 통과하고 키가 없는 CI 에서만 실패했습니다(2026-09-14).
    이 호출을 검증하는 테스트는 이 뒤에 다시 덮어씁니다.
    """
    from unittest.mock import AsyncMock

    from src.app.services import collector_service

    monkeypatch.setattr(collector_service, "stream_bid_license_limits", AsyncMock(return_value=0))
    monkeypatch.setattr(
        collector_service, "stream_bid_participation_regions", AsyncMock(return_value=0)
    )


_LOCAL_HOSTS = frozenset({"localhost", "127.0.0.1", "::1"})


@pytest.fixture(autouse=True)
def _fast_fail_local_services(monkeypatch):
    """로컬 Redis·Ollama 연결 시도를 기다리지 않고 즉시 실패시킵니다.

    Windows 는 닫힌 localhost 포트 연결이 약 2초씩 두 주소(::1, 127.0.0.1)로 재시도되어 4.33초 뒤에
    실패합니다. Linux·macOS 는 즉시 실패합니다. 세션 저장소·로그인 제한 등의 RedisConnection 은 5초
    백오프로 다시 붙으려 하는데, Windows 에서는 테스트가 느려 백오프가 거의 매번 지나므로 로그인하는
    테스트마다 4.33초를 기다렸습니다. 2026-09-13 CI(Run 34760809083)에서 Windows pytest 가 7분 52초로
    Ubuntu 2분 24초의 세 배였고, 느린 테스트 상위 25개 중 19개가 4.33초였습니다. 로컬에서 같은 지연을
    흉내 내면 전량 테스트가 90초에서 240초로 늘고 느린 테스트 목록이 CI 와 일치했습니다.
    (0d3ea959 의 PBKDF2 가속 뒤에도 남아 있던 균일 지연입니다.)

    Ollama 도 같아서 챗봇 질의 테스트가 Windows 에서 4~8초였습니다. Ollama 는 설정의 포트 하나만 막고
    MySQL 통합 테스트나 E2E 서버 포트는 건드리지 않습니다.

    CI 매트릭스에는 Redis·Ollama 가 없어 연결은 원래 실패합니다. 실패를 즉시 내는 것만 바꾸므로 동작은
    같습니다. 실제 Redis 에 붙는 테스트는 없고, 재연결 동작 테스트는 redis 모듈 대역을 씁니다.
    """
    import socket
    from urllib.parse import urlparse

    import redis.asyncio.connection
    import redis.connection

    from src.app.core.config import settings

    def refuse(connection) -> bool:
        return str(getattr(connection, "host", "")) in _LOCAL_HOSTS

    sync_connect = redis.connection.AbstractConnection.connect
    async_connect = redis.asyncio.connection.AbstractConnection.connect

    def fast_sync_connect(self, *args, **kwargs):
        if refuse(self):
            raise redis.exceptions.ConnectionError("테스트는 로컬 Redis 에 연결하지 않습니다")
        return sync_connect(self, *args, **kwargs)

    async def fast_async_connect(self, *args, **kwargs):
        if refuse(self):
            raise redis.exceptions.ConnectionError("테스트는 로컬 Redis 에 연결하지 않습니다")
        return await async_connect(self, *args, **kwargs)

    monkeypatch.setattr(redis.connection.AbstractConnection, "connect", fast_sync_connect)
    monkeypatch.setattr(redis.asyncio.connection.AbstractConnection, "connect", fast_async_connect)

    ollama_port = urlparse(settings.OLLAMA_BASE_URL).port
    create_connection = socket.create_connection

    def fast_create_connection(address, *args, **kwargs):
        host, port = address[0], address[1]
        if str(host) in _LOCAL_HOSTS and port == ollama_port:
            raise ConnectionRefusedError("테스트는 로컬 Ollama 에 연결하지 않습니다")
        return create_connection(address, *args, **kwargs)

    monkeypatch.setattr(socket, "create_connection", fast_create_connection)


@pytest.fixture
def isolated_db():
    """SQLite 인메모리 DB 세션. accounts 등 DB 쓰기 테스트를 격리합니다."""
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autocommit=False, autoflush=False)
    session = session_factory()

    def override_get_db():
        try:
            yield session
        finally:
            session.close()

    app.dependency_overrides[get_db] = override_get_db
    yield session
    app.dependency_overrides.pop(get_db, None)
    session.close()
    Base.metadata.drop_all(engine)


@pytest.fixture
def client(isolated_db):
    """isolated_db 위에서 동작하는 TestClient."""
    return TestClient(app)


@pytest.fixture(autouse=True)
def _fast_password(monkeypatch):
    """PBKDF2 반복 횟수를 1회로 줄여 Windows CI 테스트 지연을 제거합니다.

    근거: src/app/core/security.py 의 DEFAULT_ITERATIONS = 600_000 은
    Windows CPython 에서 make_password 호출당 ~2,300ms 를 소비합니다.
    _login() 헬퍼가 signup(make_password 1회) + login(check_password 내부에서
    make_password 1회) 순으로 2회 호출하므로 테스트당 합계 ~4,600ms 가 나타납니다.
    이 지연이 20건 이상의 테스트에서 균일하게 관찰된 CI run 33502305295 의
    4.59~4.63초 구간과 일치합니다.

    make_password 와 check_password 를 사용하는 모듈 두 곳을 모두 패치합니다:
      - src.app.api.v1.accounts: REST API 회원가입/로그인
      - src.app.api.ui: SSR 로그인 페이지

    운영 경로(src.app.core.security)는 패치하지 않아 실제 보안 강도를 유지합니다.
    """
    import base64
    import hashlib
    import hmac
    import secrets

    _ALGORITHM = "pbkdf2_sha256"
    _TEST_ITERATIONS = 1

    def _fast_make_password(
        raw_password: str, salt: str | None = None, iterations: int = _TEST_ITERATIONS
    ) -> str:
        salt = salt or secrets.token_hex(6)
        digest = hashlib.pbkdf2_hmac(
            "sha256", raw_password.encode(), salt.encode(), _TEST_ITERATIONS
        )
        encoded = base64.b64encode(digest).decode().strip()
        return f"{_ALGORITHM}${_TEST_ITERATIONS}${salt}${encoded}"

    def _fast_check_password(raw_password: str, encoded: str) -> bool:
        """저장된 해시의 반복 횟수를 그대로 따라 검증합니다.

        **반복 횟수를 1 로 고정하면 안 됩니다.** 테스트가
        `security.make_password`(600,000회)로 계정을 만들어 두고 이 함수로
        검증하는 경로가 있어(SSR 로그인 10건), 고정하면 전부 401 이 됩니다.
        저장된 값에 적힌 반복 횟수를 쓰면 빠른 해시와 원본 해시를 모두 검증합니다.
        """
        if not encoded or "$" not in encoded:
            return False
        try:
            algorithm, iterations, salt, _hash = encoded.split("$", 3)
        except ValueError:
            return False
        if algorithm != _ALGORITHM:
            return False
        try:
            stored_iterations = int(iterations)
            digest = hashlib.pbkdf2_hmac(
                "sha256", raw_password.encode(), salt.encode(), stored_iterations
            )
        except (TypeError, ValueError):
            return False
        candidate = (
            f"{_ALGORITHM}${stored_iterations}${salt}${base64.b64encode(digest).decode().strip()}"
        )
        return hmac.compare_digest(candidate, encoded)

    import src.app.api.ui as _ui_mod
    import src.app.api.v1.accounts as _accounts_mod

    monkeypatch.setattr(_accounts_mod, "make_password", _fast_make_password)
    monkeypatch.setattr(_accounts_mod, "check_password", _fast_check_password)
    monkeypatch.setattr(_ui_mod, "check_password", _fast_check_password)

    # 테스트 5개 파일이 fixture 안에서 security.make_password 를 직접 불러 계정을
    # 만듭니다. 위 모듈 패치는 API 경로만 덮으므로 그 fixture setup 이 그대로
    # 600,000회를 돌았습니다. Windows CI 에서 setup 하나가 4.26초였습니다
    # (2026-09-01 CI run 33506224151).
    #
    # 원본 모듈의 함수를 빠른 버전으로 바꾸되 **저장 형식(알고리즘$반복수$솔트$해시)은
    # 그대로 유지**합니다. 검증 함수가 저장된 반복 횟수를 따라가므로 두 방식으로 만든
    # 해시가 섞여도 정상 동작합니다.
    import sys

    import src.app.core.security as _security_mod

    _original_make_password = _security_mod.make_password
    monkeypatch.setattr(_security_mod, "make_password", _fast_make_password)

    # `from ... import make_password` 로 가져간 이름은 **가져간 모듈의 네임스페이스에
    # 따로 존재**합니다. 원본 모듈만 패치하면 그 이름은 그대로 600,000회를 돕니다.
    # 2026-09-01 CI 에서 원본 패치 후에도 test_home_list_parity 등의 setup 이 4.30초로
    # 남은 것이 이 때문입니다.
    #
    # 이미 임포트된 테스트 모듈을 훑어 같은 함수를 참조하는 이름만 바꿉니다. 이름이
    # 같아도 다른 함수를 가리키면 건드리지 않습니다.
    for module in list(sys.modules.values()):
        if module is None or not getattr(module, "__name__", "").startswith("tests"):
            continue
        if getattr(module, "make_password", None) is _original_make_password:
            monkeypatch.setattr(module, "make_password", _fast_make_password)


@pytest.fixture(autouse=True)
def _disable_orca_auto_approve(monkeypatch):
    """테스트가 실제 권한 자동 승인 감시기 및 런처 분리 프로세스를 띄우지 않게 막습니다."""
    monkeypatch.setenv("ORCA_DISABLE_AUTO_APPROVE", "1")

    import subprocess
    from pathlib import Path
    from unittest.mock import MagicMock

    import scripts.orca_worker_launch_common as _launch_common

    orig_spawn = _launch_common.spawn_permission_setup
    _SENTINEL = object()

    def safe_spawn(
        launcher_script: str | Path,
        terminal: str,
        model: str,
        *,
        log_path: Path = Path(".orca/permission_setup.log"),
        popen=_SENTINEL,
    ):
        if popen is _SENTINEL or popen is subprocess.Popen:
            mock_proc = MagicMock()
            mock_proc.pid = 99999
            return mock_proc
        return orig_spawn(launcher_script, terminal, model, log_path=log_path, popen=popen)

    monkeypatch.setattr(_launch_common, "spawn_permission_setup", safe_spawn)
    if (
        hasattr(_launch_common.schedule_permission_setup, "__kwdefaults__")
        and _launch_common.schedule_permission_setup.__kwdefaults__
    ):
        monkeypatch.setitem(
            _launch_common.schedule_permission_setup.__kwdefaults__, "spawn_fn", safe_spawn
        )


class _InMemoryRateLimitPipeline:
    def __init__(self, outer: "_InMemoryRateLimitClient") -> None:
        self.outer = outer
        self.ops: list[tuple[str, tuple]] = []

    def incr(self, key: str, amount: int = 1) -> "_InMemoryRateLimitPipeline":
        self.ops.append(("incr", (key, amount)))
        return self

    def expire(self, key: str, time: int) -> "_InMemoryRateLimitPipeline":
        self.ops.append(("expire", (key, time)))
        return self

    def execute(self) -> list[int]:
        results: list[int] = []
        for op, args in self.ops:
            if op == "incr":
                key, amount = args
                current = int(self.outer.store.get(key, "0"))
                new_val = current + amount
                self.outer.store[key] = str(new_val)
                results.append(new_val)
            elif op == "expire":
                key, ttl = args
                self.outer.ttls[key] = ttl
                results.append(1)
        self.ops.clear()
        return results


class _InMemoryRateLimitClient:
    """LoginRateLimiter 운영 계약(get, delete, pipeline)을 지원하는 인메모리 Redis 대역."""

    def __init__(self) -> None:
        self.store: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def get(self, key: str) -> str | None:
        return self.store.get(key)

    def delete(self, *keys: str) -> int:
        deleted = 0
        for key in keys:
            if self.store.pop(key, None) is not None:
                deleted += 1
            self.ttls.pop(key, None)
        return deleted

    def pipeline(self) -> _InMemoryRateLimitPipeline:
        return _InMemoryRateLimitPipeline(self)


@pytest.fixture(autouse=True)
def _reset_login_rate_limit(monkeypatch):
    """로그인 시도 제한 상태를 인메모리 대역으로 격리합니다.

    실제 Redis 에 scan/delete 를 실행하지 않고, 테스트마다 격리된 인메모리
    client 대역을 login_rate_limiter._conn.client 에 주입하여 테스트 간 누적 간섭을
    차단하고 불필요한 네트워크 지연을 방지합니다.
    테스트가 자체적으로 mock_redis_for_rate_limit 이나 client=None 으로 재패치할 수 있으며,
    teardown 시 monkeypatch 가 원래 상태로 복구합니다.
    """
    from src.app.core.security import login_rate_limiter

    fake_client = _InMemoryRateLimitClient()
    monkeypatch.setattr(login_rate_limiter._conn, "client", lambda: fake_client)
    return fake_client
