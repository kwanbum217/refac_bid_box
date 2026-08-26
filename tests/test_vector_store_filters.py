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

from datetime import date
from typing import Any

import pytest

from src.rag.schemas import RetrievalPlan
from src.rag.vector_store import (
    POST_FILTER_FETCH_MULTIPLIER,
    AsyncVectorStore,
    SemanticSearchResult,
    build_vector_where,
    extract_document_dates,
    extract_document_institution,
    extract_effective_document_date,
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


# ===========================================================================
# 문서 본문 메타데이터 파서 및 post-filter 단위/회귀 테스트
# ===========================================================================


def test_extract_document_institution():
    """문서 본문에서 [수요기관] 파싱이 정상 동작해야 합니다."""
    doc_text = "[수요기관] 경상북도 봉화군 체육시설사업소\n[공고명] 체육관 보수 공사"
    assert extract_document_institution(doc_text) == "경상북도 봉화군 체육시설사업소"

    # [수요기관] 없는 경우 None
    assert extract_document_institution("[공고명] 체육관 보수 공사") is None
    assert extract_document_institution("") is None
    assert extract_document_institution(None) is None


def test_extract_document_dates():
    """문서 본문에서 [공고일시], [개찰일시] 파싱이 정상 동작해야 합니다."""
    # 공고일시 + 개찰일시 모두 있는 경우
    doc_both = (
        "[수요기관] 경상북도 봉화군 체육시설사업소\n"
        "[공고일시] 2026-08-03 12:07:05\n"
        "[개찰일시] 2026-08-07 11:00:00"
    )
    notice, opening = extract_document_dates(doc_both)
    assert notice == date(2026, 8, 3)
    assert opening == date(2026, 8, 7)

    # 개찰일시 없고 [낙찰상태] 만 있는 경우
    doc_notice_only = (
        "[수요기관] 경상북도 봉화군 체육시설사업소\n"
        "[공고일시] 2026-08-03 12:07:05\n"
        "[낙찰상태] 진행 중 또는 결과 미수집"
    )
    notice2, opening2 = extract_document_dates(doc_notice_only)
    assert notice2 == date(2026, 8, 3)
    assert opening2 is None

    # 파싱 불가능한 텍스트
    assert extract_document_dates("[공고일시] 알수없음") == (None, None)
    assert extract_document_dates("") == (None, None)
    assert extract_document_dates(None) == (None, None)


def test_extract_effective_document_date():
    """개찰일시 우선, 없으면 공고일시, 둘 다 없으면 None 이어야 합니다."""
    doc_both = "[공고일시] 2026-08-03 12:07:05\n[개찰일시] 2026-08-07 11:00:00"
    assert extract_effective_document_date(doc_both) == date(2026, 8, 7)

    doc_notice_only = "[공고일시] 2026-08-03 12:07:05\n[낙찰상태] 진행 중"
    assert extract_effective_document_date(doc_notice_only) == date(2026, 8, 3)

    doc_none = "메타데이터 없는 일반 텍스트"
    assert extract_effective_document_date(doc_none) is None


def test_post_filter_institution_name_excludes_mismatch(monkeypatch):
    """(a) institution_name 이 일치하지 않는 문서가 post-filter 에서 제외되어야 합니다."""
    recorded_calls: list[dict[str, Any]] = []

    doc_match = "[수요기관] 경상북도 봉화군 체육시설사업소\n[공고명] 체육관 보수"
    doc_mismatch = "[수요기관] 서울특별시 강남구\n[공고명] 도로 보수"

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            recorded_calls.append({"n_results": n_results, "where": where})
            return {
                "documents": [[doc_match, doc_mismatch]],
                "metadatas": [[{"category": "Servc"}, {"category": "Servc"}]],
                "distances": [[0.1, 0.2]],
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
        semantic_query="체육 시설 보수 용역",
        filters={"institution_name": "봉화군"},
        top_k=5,
    )
    result = retrieve_semantic_context(plan)

    assert result.ok is True
    assert len(result.documents) == 1
    assert "봉화군" in result.documents[0]["document"]
    assert result.post_filtered_count == 1
    assert result.applied_post_filters == {"institution_name": "봉화군"}

    # provenance 확인
    prov = result.as_filter_provenance()
    assert prov["applied_post_filters"] == {"institution_name": "봉화군"}
    assert prov["post_filtered_count"] == 1


def test_post_filter_date_range_excludes_out_of_bounds(monkeypatch):
    """(b) date_from/date_to 범위 밖 문서가 post-filter 에서 제외되어야 합니다."""
    doc_in_range = "[공고일시] 2026-08-01 09:00:00\n[개찰일시] 2026-08-05 10:00:00"
    doc_too_early = "[공고일시] 2026-07-20 09:00:00\n[개찰일시] 2026-07-25 10:00:00"
    doc_too_late = "[공고일시] 2026-08-12 09:00:00\n[개찰일시] 2026-08-15 10:00:00"

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            return {
                "documents": [[doc_in_range, doc_too_early, doc_too_late]],
                "metadatas": [[{}, {}, {}]],
                "distances": [[0.1, 0.2, 0.3]],
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
        semantic_query="공사 입찰 공고",
        filters={"date_from": "2026-08-01", "date_to": "2026-08-10"},
        top_k=5,
    )
    result = retrieve_semantic_context(plan)

    assert result.ok is True
    assert len(result.documents) == 1
    assert "2026-08-05" in result.documents[0]["document"]
    assert result.post_filtered_count == 2
    assert result.applied_post_filters == {"date_from": "2026-08-01", "date_to": "2026-08-10"}


def test_post_filter_fallback_to_notice_date_when_opening_date_absent(monkeypatch):
    """(c) 개찰일시가 없는 문서는 공고일시로 판정되어야 합니다."""
    doc_match = "[공고일시] 2026-08-03 12:00:00\n[낙찰상태] 진행 중"
    doc_mismatch = "[공고일시] 2026-07-25 12:00:00\n[낙찰상태] 진행 중"

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            return {
                "documents": [[doc_match, doc_mismatch]],
                "metadatas": [[{}, {}]],
                "distances": [[0.1, 0.2]],
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
        semantic_query="진행 중 공고",
        filters={"date_from": "2026-08-01", "date_to": "2026-08-05"},
        top_k=5,
    )
    result = retrieve_semantic_context(plan)

    assert result.ok is True
    assert len(result.documents) == 1
    assert "2026-08-03" in result.documents[0]["document"]
    assert result.post_filtered_count == 1


def test_post_filter_unparseable_document_excluded_fail_closed(monkeypatch):
    """(d) 파싱 불가 문서는 조건을 만족하지 않는 것으로 보고 제외(fail-closed)되어야 합니다."""
    doc_unparseable = "대괄호 메타데이터가 전혀 없는 일반 텍스트 문서"
    doc_invalid_dates = "[수요기관] 미정\n[공고일시] 알수없음"

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            return {
                "documents": [[doc_unparseable, doc_invalid_dates]],
                "metadatas": [[{}, {}]],
                "distances": [[0.1, 0.2]],
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
        semantic_query="서울 공고",
        filters={"institution_name": "서울", "date_from": "2026-01-01"},
        top_k=5,
    )
    result = retrieve_semantic_context(plan)

    assert result.ok is True
    assert result.documents == []
    assert result.post_filtered_count == 2
    assert result.relaxed is False
    assert result.filter_relaxed is False


def test_post_filter_zero_results_does_not_relax_filters(monkeypatch):
    """(e) post-filter 로 0건이 되면 필터를 풀지 않고 빈 결과를 반환해야 합니다 (fail-closed)."""
    call_count = 0

    doc_seoul = "[수요기관] 서울특별시 강남구\n[공고명] 도로 보수"

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            nonlocal call_count
            call_count += 1
            return {
                "documents": [[doc_seoul]],
                "metadatas": [[{}]],
                "distances": [[0.1]],
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
        semantic_query="제주 공고",
        filters={"institution_name": "제주특별자치도"},
        top_k=5,
    )
    result = retrieve_semantic_context(plan)

    assert result.ok is True
    assert result.documents == []
    assert result.relaxed is False
    assert result.filter_relaxed is False
    assert result.post_filtered_count == 1
    # 재검색 없이 1회만 호출되어야 함
    assert call_count == 1


def test_post_filter_supported_only_filters_no_regression(monkeypatch):
    """(f) 지원되는 메타데이터 필터만 있는 기존 경로는 over-fetching 없이 정상 동작해야 합니다."""
    recorded_calls: list[dict[str, Any]] = []

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            recorded_calls.append({"n_results": n_results, "where": where})
            return {
                "documents": [["[공고명] 일반 문서"]],
                "metadatas": [[{"category": "Servc"}]],
                "distances": [[0.1]],
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
        semantic_query="일반 용역 공고",
        filters={"category": "Servc"},
        top_k=5,
    )
    result = retrieve_semantic_context(plan)

    assert result.ok is True
    assert len(result.documents) == 1
    assert len(recorded_calls) == 1
    # post-filter 가 없으므로 n_results == top_k (배수 적용 안 됨)
    assert recorded_calls[0]["n_results"] == 5
    assert result.applied_post_filters == {}
    assert result.post_filtered_count == 0


def test_post_filter_multiplier_and_top_k_trimming(monkeypatch):
    """post-filter 활성화 시 top_k * 배수로 검색하고 최종 반환은 top_k 로 잘라야 합니다."""
    recorded_calls: list[dict[str, Any]] = []

    docs = [f"[수요기관] 서울특별시 {i}구\n[공고명] 사업 {i}" for i in range(1, 5)] + [
        f"[수요기관] 부산광역시 {i}구\n[공고명] 사업 {i}" for i in range(1, 3)
    ]

    class MockCollection:
        @staticmethod
        def query(query_texts, n_results, where=None):
            recorded_calls.append({"n_results": n_results, "where": where})
            return {
                "documents": [docs],
                "metadatas": [[{} for _ in docs]],
                "distances": [[0.1 * i for i in range(len(docs))]],
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
        semantic_query="서울 사업",
        filters={"institution_name": "서울"},
        top_k=2,
    )
    result = retrieve_semantic_context(plan)

    assert result.ok is True
    # top_k=2 이므로 2개만 반환되어야 함
    assert len(result.documents) == 2
    # 검색 요청은 2 * POST_FILTER_FETCH_MULTIPLIER = 6 이어야 함
    assert recorded_calls[0]["n_results"] == 2 * POST_FILTER_FETCH_MULTIPLIER
    # 부산 문서 2건이 제외됨
    assert result.post_filtered_count == 2
    assert result.applied_post_filters == {"institution_name": "서울"}
