"""임베딩 함수 단일화 회귀 테스트.

가장 중요한 것은 **색인과 질의가 같은 임베딩 함수를 쓰는가** 입니다.
어긋나도 예외가 나지 않고 검색 결과만 조용히 엉망이 되므로, 배선을 코드로
고정합니다.
"""

from __future__ import annotations

import pytest

from src.rag import embeddings


def test_default_provider_is_ollama():
    """한국어 검색 품질 때문에 코드 기본값을 bge-m3 로 두었습니다.

    conftest 가 테스트 실행 중에는 `default` 로 덮으므로 인스턴스가 아니라
    필드 정의의 기본값을 확인합니다.
    """
    from src.app.core.config import Settings

    fields = Settings.model_fields
    assert fields["EMBEDDING_PROVIDER"].default == "ollama"
    assert fields["EMBEDDING_MODEL"].default == "bge-m3"


def test_get_embedding_function_returns_ollama_adapter(monkeypatch):
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_PROVIDER", "ollama")
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_MODEL", "bge-m3")

    function = embeddings.get_embedding_function()

    assert isinstance(function, embeddings.OllamaEmbeddingFunction)
    assert function.name() == "ollama-bge-m3"
    assert function.url.endswith("/api/embed")


def test_default_provider_falls_back_to_chroma_builtin(monkeypatch):
    """되돌리기 경로입니다. None 이면 ChromaDB 기본 함수를 씁니다."""
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_PROVIDER", "default")

    assert embeddings.get_embedding_function() is None


def test_unknown_provider_defaults_to_ollama(monkeypatch):
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_PROVIDER", "made-up")

    assert isinstance(embeddings.get_embedding_function(), embeddings.OllamaEmbeddingFunction)


def test_indexing_and_query_use_same_function():
    """kb_builder 와 vector_store 가 같은 진입점을 쓰는지 고정합니다."""
    from src.app.services import kb_builder
    from src.rag import vector_store

    assert kb_builder.get_collection is embeddings.get_collection
    assert vector_store.get_collection is embeddings.get_collection


def test_get_collection_passes_embedding_function(monkeypatch):
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_PROVIDER", "ollama")
    captured = {}

    class FakeClient:
        def get_collection(self, **kwargs):
            captured.update(kwargs)
            return "collection"

        def get_or_create_collection(self, **kwargs):
            captured.update(kwargs)
            return "collection"

    embeddings.get_collection(FakeClient(), "bidding_kb")
    assert captured["name"] == "bidding_kb"
    assert isinstance(captured["embedding_function"], embeddings.OllamaEmbeddingFunction)

    captured.clear()
    embeddings.get_collection(FakeClient(), "bidding_kb", create=True)
    assert "embedding_function" in captured


def test_get_collection_omits_function_for_builtin(monkeypatch):
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_PROVIDER", "default")
    captured = {}

    class FakeClient:
        def get_collection(self, **kwargs):
            captured.update(kwargs)
            return "collection"

    embeddings.get_collection(FakeClient(), "bidding_kb")
    assert "embedding_function" not in captured


def test_ollama_adapter_batches_requests(monkeypatch):
    """배치 경계에서 문서가 누락되지 않아야 합니다."""
    function = embeddings.OllamaEmbeddingFunction("bge-m3", "http://localhost:11434")
    calls = []

    class FakeResponse:
        def __init__(self, size):
            self.size = size

        def raise_for_status(self):
            return None

        def json(self):
            return {"embeddings": [[0.0] * 4 for _ in range(self.size)]}

    class FakeClient:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def post(self, _url, json):
            calls.append(len(json["input"]))
            return FakeResponse(len(json["input"]))

    monkeypatch.setattr("httpx.Client", lambda **_kwargs: FakeClient())

    total = embeddings.EMBED_BATCH_SIZE * 2 + 5
    vectors = function(["문서"] * total)

    assert len(vectors) == total
    assert sum(calls) == total
    assert calls == [embeddings.EMBED_BATCH_SIZE, embeddings.EMBED_BATCH_SIZE, 5]


@pytest.mark.parametrize("provider", ["ollama", "default"])
def test_embedding_function_is_resolved_per_call(monkeypatch, provider):
    """설정을 바꾸면 즉시 반영되어야 합니다. 모듈 로드 시점에 굳으면 안 됩니다."""
    monkeypatch.setattr(embeddings.settings, "EMBEDDING_PROVIDER", provider)
    function = embeddings.get_embedding_function()
    assert (function is None) == (provider == "default")
