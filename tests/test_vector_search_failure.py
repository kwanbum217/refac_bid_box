"""
tests/test_vector_search_failure.py

벡터 검색 실패가 조용히 지나가지 않는지 검증.

2026-08-05 에 ChromaDB 컬렉션 설정 JSON 이 비어 클라이언트가 컬렉션을 열지
못했습니다. 그런데 `retrieve_semantic_context` 는 예외를 잡아
`{"document": "문맥 검색 오류: ..."}` 를 **문서인 것처럼** 돌려주고 있었습니다.

결과는 이렇습니다.

- 그 오류 문자열이 그대로 LLM 프롬프트에 실렸습니다
- 화면에는 검색이 성공한 것처럼 보였습니다
- 로그에도 아무것도 남지 않았습니다
- 챗봇이 **닷새 동안 지식베이스 없이** 답했는데 아무도 몰랐습니다

실패는 실패로 보여야 합니다. 잘못된 결과를 내느니 결과가 없는 편이 낫습니다
(SKILLS.md 품질 우선순위 1. 정확성).
"""

import logging

import pytest

from src.rag import vector_store
from src.rag.schemas import DEFAULT_VECTOR_TOP_K, RetrievalPlan


def _plan() -> RetrievalPlan:
    return RetrievalPlan(semantic_query="적격심사 기준", top_k=5)


def test_search_failure_returns_no_documents(monkeypatch):
    """오류 문구를 문서로 위장하지 않아야 합니다."""

    class BrokenChroma:
        @staticmethod
        def PersistentClient(path):
            raise KeyError("_type")

    monkeypatch.setitem(__import__("sys").modules, "chromadb", BrokenChroma)

    docs = vector_store.retrieve_semantic_context(_plan())

    assert docs == []


def test_search_failure_is_logged(monkeypatch, caplog):
    """로그에 남지 않으면 며칠이 지나도 아무도 모릅니다."""

    class BrokenChroma:
        @staticmethod
        def PersistentClient(path):
            raise KeyError("_type")

    monkeypatch.setitem(__import__("sys").modules, "chromadb", BrokenChroma)

    with caplog.at_level(logging.ERROR, logger="src.rag.vector_store"):
        vector_store.retrieve_semantic_context(_plan())

    assert any("ChromaDB 검색 실패" in record.message for record in caplog.records)


def test_empty_query_returns_empty_without_touching_chroma(monkeypatch):
    """질의가 비면 검색 자체를 하지 않습니다."""

    def explode(path):
        raise AssertionError("빈 질의로 ChromaDB 를 열면 안 됩니다")

    class Chroma:
        PersistentClient = staticmethod(explode)

    monkeypatch.setitem(__import__("sys").modules, "chromadb", Chroma)

    assert vector_store.retrieve_semantic_context(RetrievalPlan(semantic_query="  ")) == []


@pytest.mark.asyncio
async def test_async_vector_store_uses_the_shared_top_k_default(monkeypatch):
    captured: list[RetrievalPlan] = []

    def retrieve(plan: RetrievalPlan):
        captured.append(plan)
        return []

    monkeypatch.setattr(vector_store, "retrieve_semantic_context", retrieve)

    assert await vector_store.AsyncVectorStore().search_similar_docs("적격심사") == []
    assert captured[0].top_k == DEFAULT_VECTOR_TOP_K
