"""
tests/test_vector_store_filters.py

ChromaDB 메타데이터 where 절 변환 및 필터 검색 단위 테스트.
- (a) category 가 있으면 where 에 들어가는지
- (b) 결과 질의면 has_result=True 가 추가되는지
- (c) 결과 질의가 아니면 has_result 가 없는지
- (d) date_from/date_to/institution_name 이 where 로 새어 나가지 않는지
- (e) 조건 둘 이상이면 $and 로 묶이는지
- (f) 필터 결과 0건이면 무필터 재검색 없이 빈 결과로 처리하고 프로비넌스를 기록하는지
"""

from typing import Any

import pytest

from src.rag.schemas import RetrievalPlan
from src.rag.vector_store import (
    AsyncVectorStore,
    SemanticSearchResult,
    build_vector_where,
    retrieve_semantic_context,
)


def test_build_vector_where_single_category():
    """(a) category 단일 조건이 where 에 정확히 반영되어야 합니다."""
    plan = RetrievalPlan(
        semantic_query="입찰 참가 자격 안내",
        filters={"category": "Servc"},
    )
    where = build_vector_where(plan)
    assert where == {"category": "Servc"}


def test_build_vector_where_result_query_adds_has_result():
    """(b) 낙찰 결과를 묻는 질의는 has_result=True 가 where 에 추가되어야 합니다."""
    plan = RetrievalPlan(
        semantic_query="대구불로초등학교 공사의 낙찰업체와 낙찰금액을 알려줘",
        filters={},
    )
    where = build_vector_where(plan)
    assert where == {"has_result": True}


def test_build_vector_where_non_result_query_omits_has_result():
    """(c) 낙찰 결과를 묻지 않는 일반 공고 질의에는 has_result 가 포함되지 않아야 합니다."""
    plan = RetrievalPlan(
        semantic_query="충북대학교병원 개선공사의 수요기관과 입찰 참가 조건",
        filters={},
    )
    where = build_vector_where(plan)
    assert where is None

    plan_with_category = RetrievalPlan(
        semantic_query="충북대학교병원 개선공사의 수요기관과 입찰 참가 조건",
        filters={"category": "Cnstwk"},
    )
    where_cat = build_vector_where(plan_with_category)
    assert where_cat == {"category": "Cnstwk"}


def test_build_vector_where_unsupported_keys_do_not_leak():
    """(d) date_from, date_to, institution_name 등 메타데이터에 없는 키는 where 로 새어나가지 않아야 합니다."""
    plan = RetrievalPlan(
        semantic_query="충북대학교병원 개선공사의 수요기관과 입찰 참가 조건",
        filters={
            "date_from": "2026-01-01",
            "date_to": "2026-01-31",
            "institution_name": "충북대학교병원",
            "result_limit": 5,
            "analysis_mode": "trend",
        },
    )
    where = build_vector_where(plan)
    assert where is None


def test_build_vector_where_multiple_conditions_bundled_with_and():
    """(e) category 와 has_result 등 둘 이상의 조건은 $and 로 묶여야 합니다."""
    plan = RetrievalPlan(
        semantic_query="안녕 자두야 포스트프로덕션 용역의 최종 낙찰금액 및 낙찰률은 얼마인가요?",
        filters={
            "category": "Servc",
            "date_from": "2026-01-01",
            "institution_name": "서울",
        },
    )
    where = build_vector_where(plan)
    assert where is not None
    assert "$and" in where
    conditions = where["$and"]
    assert {"category": "Servc"} in conditions
    assert {"has_result": True} in conditions
    assert len(conditions) == 2


def test_build_vector_where_with_direct_dict_and_explicit_has_result():
    """직접 딕셔너리 전달 및 명시적 has_result=False 도 지원되어야 합니다."""
    where_false = build_vector_where(
        filters={"category": "Thng", "has_result": False},
        query="공고 안내",
    )
    assert where_false == {"$and": [{"category": "Thng"}, {"has_result": False}]}


def test_retrieve_semantic_context_applies_where_to_chroma(monkeypatch):
    """retrieve_semantic_context 가 ChromaDB query 호출 시 where 절을 올바르게 전달하는지 검증합니다."""
    recorded_calls: list[dict[str, Any]] = []

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            recorded_calls.append(
                {"query_texts": query_texts, "n_results": n_results, "where": where}
            )
            return {
                "documents": [["테스트 문서 내용"]],
                "metadatas": [[{"category": "Servc", "has_result": True}]],
                "distances": [[0.15]],
            }

    class MockChroma:
        @staticmethod
        def PersistentClient(path):
            return MockChroma()

    monkeypatch.setitem(__import__("sys").modules, "chromadb", MockChroma)
    monkeypatch.setattr(
        "src.rag.vector_store.get_collection", lambda client, name: MockCollection()
    )

    plan = RetrievalPlan(
        semantic_query="안녕 자두야 포스트프로덕션 용역의 최종 낙찰금액 및 낙찰률",
        filters={"category": "Servc"},
        top_k=5,
    )
    result = retrieve_semantic_context(plan)

    assert isinstance(result, SemanticSearchResult)
    assert result.ok is True
    assert len(result.documents) == 1
    assert result.relaxed is False
    assert result.filter_relaxed is False

    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    assert call["where"] is not None
    assert "$and" in call["where"]
    assert {"category": "Servc"} in call["where"]["$and"]
    assert {"has_result": True} in call["where"]["$and"]


def test_retrieve_semantic_context_fail_closed_when_filter_miss(monkeypatch):
    """P1 회귀: Frgcpt/has_result=True 필터 miss가 Cnstwk/has_result=False 문서를 반환해서는 안 됩니다.

    필터 적용 검색 결과가 0건이면 무필터 재검색 없이 빈 결과(empty success)로
    처리합니다. Chroma query 호출은 1회뿐이며, 완화 여부는 False 로 남습니다.
    """
    recorded_calls: list[dict[str, Any]] = []

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            recorded_calls.append(
                {"query_texts": query_texts, "n_results": n_results, "where": where}
            )
            if where is not None:
                return {"documents": [[]], "metadatas": [[]], "distances": [[]]}
            # 무필터 재검색 경로가 호출되면 P1 이 재발한 것입니다.
            raise AssertionError("필터 해제 재검색이 실행되었습니다 (fail-closed 위반)")

    class MockChroma:
        @staticmethod
        def PersistentClient(path):
            return MockChroma()

    monkeypatch.setitem(__import__("sys").modules, "chromadb", MockChroma)
    monkeypatch.setattr(
        "src.rag.vector_store.get_collection", lambda client, name: MockCollection()
    )

    plan = RetrievalPlan(
        semantic_query="희귀 특수 공사의 낙찰업체와 낙찰금액",
        filters={"category": "Frgcpt", "date_from": "2026-01-01"},
        top_k=5,
    )
    result = retrieve_semantic_context(plan)

    assert isinstance(result, SemanticSearchResult)
    assert result.ok is True
    assert result.relaxed is False
    assert result.filter_relaxed is False
    assert result.documents == []
    assert result.error is None

    assert len(recorded_calls) == 1
    call = recorded_calls[0]
    assert call["where"] is not None
    assert {"category": "Frgcpt"} in call["where"]["$and"]
    assert {"has_result": True} in call["where"]["$and"]

    assert result.original_filters == {"category": "Frgcpt", "date_from": "2026-01-01"}
    assert result.effective_filters == {"$and": [{"category": "Frgcpt"}, {"has_result": True}]}
    assert result.unsupported_filters == {"date_from": "2026-01-01"}

    provenance = result.as_filter_provenance()
    assert provenance["original_filters"]["category"] == "Frgcpt"
    assert provenance["unsupported_filters"] == {"date_from": "2026-01-01"}
    assert provenance["filter_relaxed"] is False


@pytest.mark.asyncio
async def test_async_vector_store_passes_filters(monkeypatch):
    """AsyncVectorStore.search_similar_docs 가 filters 를 포함한 RetrievalPlan 을 전달하는지 검증합니다."""
    captured: list[RetrievalPlan] = []

    def mock_retrieve(plan: RetrievalPlan):
        captured.append(plan)
        return SemanticSearchResult(ok=True, documents=[])

    monkeypatch.setattr("src.rag.vector_store.retrieve_semantic_context", mock_retrieve)

    store = AsyncVectorStore()
    result = await store.search_similar_docs(
        query="테스트 용역 공고",
        top_k=3,
        filters={"category": "Servc"},
    )
    assert result.ok is True
    assert len(captured) == 1
    assert captured[0].filters == {"category": "Servc"}
    assert captured[0].top_k == 3
