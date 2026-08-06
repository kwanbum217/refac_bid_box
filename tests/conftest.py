"""
tests/conftest.py

공통 pytest fixture.
 - SKIP_MODEL_LOAD 로 무거운 joblib 로드를 건너뜁니다.
 - isolated_db fixture 로 SQLite 인메모리 DB 를 사용해 쓰기 테스트를 격리합니다.
 - 임베딩은 ChromaDB 내장 함수로 고정합니다. 운영 기본값(Ollama bge-m3)을
   그대로 쓰면 테스트가 로컬 Ollama 에 의존해 CI 에서 깨집니다. 임베딩 배선
   자체는 tests/test_rag_embeddings.py 가 따로 검증합니다.
"""

import os

os.environ.setdefault("SKIP_MODEL_LOAD", "true")
os.environ.setdefault("EMBEDDING_PROVIDER", "default")

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
