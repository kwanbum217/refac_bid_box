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

from src.app.services.tools import semantic_search_tool
from src.rag import engine as rag_engine
from src.rag import vector_store
from src.rag.schemas import DEFAULT_VECTOR_TOP_K, RetrievalPlan
from src.rag.vector_store import SemanticSearchResult


def _plan() -> RetrievalPlan:
    return RetrievalPlan(semantic_query="적격심사 기준", top_k=5)


def test_search_failure_returns_no_documents_with_ok_false(monkeypatch):
    """오류 문구를 문서로 위장하지 않고 ok=False 를 반환해야 합니다."""

    class BrokenChroma:
        @staticmethod
        def PersistentClient(path):
            raise KeyError("_type")

    monkeypatch.setitem(__import__("sys").modules, "chromadb", BrokenChroma)

    result = vector_store.retrieve_semantic_context(_plan())

    assert isinstance(result, SemanticSearchResult)
    assert result.ok is False
    assert result.documents == []
    assert result.error is not None


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
    """질의가 비면 검색 자체를 하지 않고 ok=True 를 반환합니다."""

    def explode(path):
        raise AssertionError("빈 질의로 ChromaDB 를 열면 안 됩니다")

    class Chroma:
        PersistentClient = staticmethod(explode)

    monkeypatch.setitem(__import__("sys").modules, "chromadb", Chroma)

    result = vector_store.retrieve_semantic_context(RetrievalPlan(semantic_query="  "))

    assert isinstance(result, SemanticSearchResult)
    assert result.ok is True
    assert result.documents == []
    assert result.error is None


def test_search_success_with_zero_results_returns_ok_true(monkeypatch):
    """정상 검색 결과가 0건일 때 ok=True 이고 documents 가 빈 목록이어야 합니다."""

    class EmptyCollection:
        @staticmethod
        def query(query_texts, n_results):
            return {"documents": [[]], "metadatas": [[]], "distances": [[]]}

    class Chroma:
        @staticmethod
        def PersistentClient(path):
            return Chroma()

    monkeypatch.setitem(__import__("sys").modules, "chromadb", Chroma)
    monkeypatch.setattr(vector_store, "get_collection", lambda client, name: EmptyCollection())

    result = vector_store.retrieve_semantic_context(_plan())

    assert isinstance(result, SemanticSearchResult)
    assert result.ok is True
    assert result.documents == []
    assert result.error is None


def test_search_recent_details_failure_and_empty_messages_are_distinct(monkeypatch):
    """search_recent_details 의 실패 문구와 0건 문구는 반드시 달라야 합니다."""
    monkeypatch.setattr(
        rag_engine,
        "retrieve_semantic_context",
        lambda plan: SemanticSearchResult(ok=False, documents=[], error="Chroma connection failed"),
    )
    fail_msg = rag_engine.search_recent_details("적격심사 사례")

    monkeypatch.setattr(
        rag_engine,
        "retrieve_semantic_context",
        lambda plan: SemanticSearchResult(ok=True, documents=[], error=None),
    )
    empty_msg = rag_engine.search_recent_details("적격심사 사례")

    assert fail_msg == "지식베이스 검색에 실패해 상세 문서를 확인하지 못했습니다."
    assert empty_msg == "최근 문맥에서 관련된 상세 문서를 찾지 못했습니다."
    assert fail_msg != empty_msg


def test_prepare_context_records_failure_hint_and_hides_raw_error(monkeypatch):
    """검색 실패 시 Provenance 에 실패 힌트가 들어가고 원본 예외 문구는 노출되지 않아야 합니다."""
    raw_error_message = "ChromaInternalCrash: disk is full and socket closed"
    monkeypatch.setattr(
        rag_engine,
        "retrieve_semantic_context",
        lambda plan: SemanticSearchResult(ok=False, documents=[], error=raw_error_message),
    )

    engine = rag_engine.HybridRAGEngine()
    (
        _plan,
        _structured_data,
        vector_docs,
        _kb_status,
        provenance,
        context_text,
        messages,
    ) = engine._prepare_context(user_query="적격심사 세부기준 알려줘")

    expected_hint = "지식베이스 문맥 검색에 실패해 문맥 없이 답변합니다."
    assert expected_hint in provenance.insufficiency_hints
    assert vector_docs == []

    # 원본 예외 문구가 insufficiency_hints, context_text, messages 어디에도 없어야 함
    for hint in provenance.insufficiency_hints:
        assert raw_error_message not in hint
    assert raw_error_message not in context_text
    for msg in messages:
        assert raw_error_message not in msg["content"]


def test_semantic_search_tool_search_failed_flag(monkeypatch):
    """semantic_search_tool 반환 dict 에 search_failed 플래그가 정확히 반영되어야 합니다."""
    monkeypatch.setattr(
        semantic_search_tool,
        "retrieve_semantic_context",
        lambda plan: SemanticSearchResult(ok=False, documents=[], error="timeout"),
    )
    fail_result = semantic_search_tool.execute(query="적격심사")
    assert fail_result["search_failed"] is True
    assert fail_result["documents"] == []
    assert fail_result["document"] == ""

    sample_doc = {
        "document": "테스트 문서 내용",
        "content": "테스트 문서 내용",
        "metadata": {"title": "테스트"},
        "distance": 0.12,
    }
    monkeypatch.setattr(
        semantic_search_tool,
        "retrieve_semantic_context",
        lambda plan: SemanticSearchResult(ok=True, documents=[sample_doc], error=None),
    )
    ok_result = semantic_search_tool.execute(query="적격심사")
    assert ok_result["search_failed"] is False
    assert len(ok_result["documents"]) == 1
    assert ok_result["document"] == "테스트 문서 내용"


@pytest.mark.asyncio
async def test_async_vector_store_uses_the_shared_top_k_default(monkeypatch):
    captured: list[RetrievalPlan] = []

    def retrieve(plan: RetrievalPlan):
        captured.append(plan)
        return SemanticSearchResult(ok=True, documents=[])

    monkeypatch.setattr(vector_store, "retrieve_semantic_context", retrieve)

    result = await vector_store.AsyncVectorStore().search_similar_docs("적격심사")
    assert isinstance(result, SemanticSearchResult)
    assert result.ok is True
    assert result.documents == []
    assert captured[0].top_k == DEFAULT_VECTOR_TOP_K
