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
"""

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
    import src.app.core.security as _security_mod

    monkeypatch.setattr(_security_mod, "make_password", _fast_make_password)


@pytest.fixture(autouse=True)
def _disable_orca_auto_approve(monkeypatch):
    """테스트가 실제 권한 자동 승인 감시기 프로세스를 띄우지 않게 막습니다."""
    monkeypatch.setenv("ORCA_DISABLE_AUTO_APPROVE", "1")
