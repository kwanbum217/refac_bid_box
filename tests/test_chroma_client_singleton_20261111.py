"""
tests/test_chroma_client_singleton_20261111.py

RAG 질의·헬스체크가 요청마다 ChromaDB 클라이언트를 새로 만들던 문제(I-ai F-14)의
회귀 시험. 프로세스 단위 접근자가 클라이언트와 기본 컬렉션 핸들을 한 번만 만들고,
경로·팩토리가 바뀌거나 컬렉션이 사라지면 다시 여는지 확인합니다.

전·후 질의 지연도 같은 파일에서 잰다. 운영 chroma_db 와 Redis 는 건드리지 않고
tmp_path 에 소형 컬렉션을 만든다.
"""

from __future__ import annotations

import json
import math
import platform
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

from src.app.core.config import settings
from src.rag import chroma_client, embeddings, vector_store
from src.rag.chroma_client import (
    DEFAULT_COLLECTION,
    get_chroma_client,
    get_default_collection,
    reset_chroma_client,
)
from src.rag.schemas import RetrievalPlan

MEASURE_ROUNDS = 40
MEASURE_WARMUP_ROUNDS = 3
MEASURE_DOC_COUNT = 20
MEASURE_QUERY = "측정용 낙찰 공고 질의"


@pytest.fixture(autouse=True)
def _reset_client_cache():
    """모든 시험이 빈 캐시에서 시작하고, 남은 핸들을 다음 시험으로 넘기지 않습니다."""
    reset_chroma_client()
    yield
    reset_chroma_client()


def test_client_is_created_once(monkeypatch):
    """(1) 같은 경로로 두 번 불러도 PersistentClient 생성자는 한 번만 불립니다."""
    created: list[str] = []

    class FakeChroma:
        @staticmethod
        def PersistentClient(path):
            created.append(path)
            return FakeChroma()

    monkeypatch.setitem(sys.modules, "chromadb", FakeChroma)

    first = get_chroma_client()
    second = get_chroma_client()

    assert first is second
    assert created == [str(settings.CHROMA_DB_PATH)]


def test_client_is_recreated_when_path_changes(monkeypatch):
    """(2) CHROMA_DB_PATH 가 바뀌면 새 클라이언트를 만듭니다."""
    created: list[str] = []

    class FakeChroma:
        @staticmethod
        def PersistentClient(path):
            created.append(path)
            return FakeChroma()

    monkeypatch.setitem(sys.modules, "chromadb", FakeChroma)
    monkeypatch.setattr(settings, "CHROMA_DB_PATH", "/tmp/chroma-singleton-a")
    first = get_chroma_client()

    monkeypatch.setattr(settings, "CHROMA_DB_PATH", "/tmp/chroma-singleton-b")
    second = get_chroma_client()

    assert first is not second
    assert created == ["/tmp/chroma-singleton-a", "/tmp/chroma-singleton-b"]


def test_collection_is_opened_through_get_collection(monkeypatch):
    """(3) 컬렉션은 기본 임베딩이 끼어들지 않도록 get_collection 을 거쳐 엽니다."""
    assert chroma_client.get_collection is embeddings.get_collection

    sentinel = object()
    opened: list[tuple[Any, str]] = []

    class FakeChroma:
        @staticmethod
        def PersistentClient(path):
            return object()

    monkeypatch.setitem(sys.modules, "chromadb", FakeChroma)

    def fake_get_collection(client, name):
        opened.append((client, name))
        return sentinel

    monkeypatch.setattr(chroma_client, "get_collection", fake_get_collection)

    assert get_default_collection() is sentinel
    assert get_default_collection() is sentinel
    assert len(opened) == 1
    assert opened[0][1] == DEFAULT_COLLECTION


def test_concurrent_callers_share_one_client(monkeypatch):
    """(4) 동시에 부른 8개 스레드가 같은 클라이언트 객체를 받습니다."""
    created: list[str] = []
    barrier = threading.Barrier(8)

    class SlowChroma:
        @staticmethod
        def PersistentClient(path):
            created.append(path)
            time.sleep(0.02)
            return SlowChroma()

    monkeypatch.setitem(sys.modules, "chromadb", SlowChroma)

    def call(_: int) -> Any:
        barrier.wait()
        return get_chroma_client()

    with ThreadPoolExecutor(max_workers=8) as pool:
        clients = list(pool.map(call, range(8)))

    assert len({id(client) for client in clients}) == 1
    assert len(created) == 1


def test_missing_collection_error_reopens_once(monkeypatch):
    """(5) 색인 재구축 뒤 낡은 컬렉션 핸들이면 한 번만 다시 열어 질의를 살립니다."""

    class NotFoundError(Exception):
        pass

    class FakeCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            return {
                "documents": [["재구축 뒤 문서"]],
                "metadatas": [[{}]],
                "distances": [[0.1]],
            }

    class FakeChroma:
        @staticmethod
        def PersistentClient(path):
            return FakeChroma()

    monkeypatch.setitem(sys.modules, "chromadb", FakeChroma)

    opens: list[str] = []

    def opener(client, name):
        opens.append(name)
        if len(opens) == 1:
            raise NotFoundError(f"Collection {name} does not exist")
        return FakeCollection()

    monkeypatch.setattr(vector_store, "get_collection", opener)

    result = vector_store.retrieve_semantic_context(
        RetrievalPlan(semantic_query="낙찰률 알려줘", top_k=5)
    )

    assert result.ok is True
    assert [document["document"] for document in result.documents] == ["재구축 뒤 문서"]
    assert opens == [DEFAULT_COLLECTION, DEFAULT_COLLECTION]


def test_other_errors_are_not_retried(monkeypatch):
    """컬렉션 부재가 아닌 오류는 다시 열지 않고 그대로 실패로 남깁니다."""

    class FakeChroma:
        @staticmethod
        def PersistentClient(path):
            return FakeChroma()

    monkeypatch.setitem(sys.modules, "chromadb", FakeChroma)

    opens: list[str] = []

    def opener(client, name):
        opens.append(name)
        raise ValueError("설정 오류")

    monkeypatch.setattr(vector_store, "get_collection", opener)

    result = vector_store.retrieve_semantic_context(
        RetrievalPlan(semantic_query="낙찰률 알려줘", top_k=5)
    )

    assert result.ok is False
    assert opens == [DEFAULT_COLLECTION]


def test_health_check_uses_default_collection(monkeypatch):
    """헬스체크는 요청마다 클라이언트를 만들지 않고 접근자의 컬렉션만 봅니다."""
    from src.app.api.v1 import health

    counted: list[int] = []

    class FakeCollection:
        @staticmethod
        def count():
            counted.append(1)
            return 3

    monkeypatch.setattr(chroma_client, "get_default_collection", lambda: FakeCollection())

    health._check_chromadb()

    assert counted == [1]


def _percentile(values: list[float], ratio: float) -> float:
    """최근접 순위(nearest-rank) 백분위."""
    ordered = sorted(values)
    rank = max(1, math.ceil(ratio * len(ordered)))
    return ordered[rank - 1]


def _seed_collection(path: str) -> None:
    import chromadb

    client = chromadb.PersistentClient(path=path)
    collection = embeddings.get_collection(client, DEFAULT_COLLECTION, create=True)
    collection.add(
        ids=[f"probe-{index}" for index in range(MEASURE_DOC_COUNT)],
        documents=[f"{MEASURE_QUERY} 문서 {index}" for index in range(MEASURE_DOC_COUNT)],
    )


def test_query_latency_before_and_after(monkeypatch, tmp_path, capsys):
    """전·후 질의 지연을 tmp_path 컬렉션에서 실측합니다.

    전: 요청마다 PersistentClient + get_collection (종전 경로)
    후: 프로세스 접근자가 보관한 컬렉션 핸들 재사용
    운영 chroma_db 와 Redis 는 읽지도 쓰지도 않습니다.
    """
    path = str(tmp_path / "chroma")
    monkeypatch.setattr(settings, "CHROMA_DB_PATH", path)
    _seed_collection(path)
    reset_chroma_client()

    import chromadb

    def before() -> list[str]:
        client = chromadb.PersistentClient(path=path)
        collection = embeddings.get_collection(client, DEFAULT_COLLECTION)
        results = collection.query(query_texts=[MEASURE_QUERY], n_results=5)
        return (results.get("ids") or [[]])[0]

    def after() -> list[str]:
        results = get_default_collection().query(query_texts=[MEASURE_QUERY], n_results=5)
        return (results.get("ids") or [[]])[0]

    for _ in range(MEASURE_WARMUP_ROUNDS):
        before()
        after()

    before_ms: list[float] = []
    after_ms: list[float] = []
    for _ in range(MEASURE_ROUNDS):
        started = time.perf_counter()
        before_ids = before()
        before_ms.append((time.perf_counter() - started) * 1000.0)

        started = time.perf_counter()
        after_ids = after()
        after_ms.append((time.perf_counter() - started) * 1000.0)

        assert before_ids == after_ids

    assert len(before_ms) == MEASURE_ROUNDS
    assert len(after_ms) == MEASURE_ROUNDS

    payload = {
        "rounds": MEASURE_ROUNDS,
        "documents": MEASURE_DOC_COUNT,
        "before_p50_ms": round(_percentile(before_ms, 0.50), 3),
        "before_p95_ms": round(_percentile(before_ms, 0.95), 3),
        "after_p50_ms": round(_percentile(after_ms, 0.50), 3),
        "after_p95_ms": round(_percentile(after_ms, 0.95), 3),
        "python": platform.python_version(),
        "platform": platform.platform(terse=True),
        "chromadb": chromadb.__version__,
    }
    print("CHROMA_SINGLETON_MEASUREMENTS " + json.dumps(payload, ensure_ascii=False))
    assert payload["before_p50_ms"] >= 0.0
    assert payload["after_p50_ms"] >= 0.0
