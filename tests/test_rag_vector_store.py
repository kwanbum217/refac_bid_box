"""
tests/test_rag_vector_store.py

정확 공고명 재순위(_rerank_by_exact_title) 포함 관계 매칭 및
엔진(HybridRAGEngine) 벡터 바이패스 분리 단위 테스트.

검증 항목:
1. q21 형태의 자연어 질의에서 공고명이 부분 문자열인 문서가 1위로 승격된다.
2. 최소 길이 하한(RERANK_MIN_TITLE_LENGTH) 미만의 짧은 제목은 승격되지 않는다.
3. 어느 문서도 걸리지 않으면 기존 distance 순서가 그대로 유지된다.
4. 복수 승격 시 결정적 정렬(_extract_doc_sort_key) 순서가 유지된다.
5. Lexical 채널에서 포함 매칭만 걸린 경우 벡터 경로가 생략(bypass)되지 않고 호출된다.
6. Lexical 채널에서 엄격 동치 일치 시에는 벡터 경로가 정상적으로 생략(bypass)된다.
"""

from typing import Any
from unittest.mock import MagicMock

from src.rag.engine import HybridRAGEngine
from src.rag.vector_store import (
    RERANK_MIN_TITLE_LENGTH,
    SemanticSearchResult,
    _extract_doc_sort_key,
    _normalize_match_key,
    _rerank_by_exact_title,
)

# 실제 q21 fixture 질의 및 공고명 상수
Q21_QUERY = "2026년 조림지 풀베기사업 2차(동부지구)의 공고번호, 수요기관, 낙찰업체 및 최종 낙찰금액과 낙찰률을 알려줘"
Q21_TARGET_TITLE = "2026년 조림지 풀베기사업 2차(동부지구)"


# ===========================================================================
# 0. 최소 길이 상수 및 정규화 키 포함 검증
# ===========================================================================


def test_rerank_min_title_length_constant():
    """RERANK_MIN_TITLE_LENGTH 상수가 5로 올바르게 선언되었는지 확인합니다."""
    assert RERANK_MIN_TITLE_LENGTH == 5


def test_normalize_match_key_q21_containment():
    """q21 질의와 공고명의 정규화 키가 부분 문자열 관계를 만족함을 확인합니다."""
    query_key = _normalize_match_key(Q21_QUERY)
    title_key = _normalize_match_key(Q21_TARGET_TITLE)
    assert title_key in query_key
    assert len(title_key) >= RERANK_MIN_TITLE_LENGTH


# ===========================================================================
# 1. q21 자연어 질의 부분 문자열 승격 테스트
# ===========================================================================


def test_rerank_q21_natural_language_query_promotes_target_doc_to_first():
    """q21 형태의 자연어 질의에서 공고명이 부분 문자열로 포함된 문서가 1위로 승격되어야 합니다."""
    # ChromaDB 에서 거리 순으로 정렬되어 반환된 후보 풀 (기대 문서가 9위에 위치)
    docs = [
        {
            "id": "bid_10146912",
            "document": "[공고명] 2026년 조림지 풀베기사업(2차)(영암지구)\n[수요기관] 영암군산림조합",
            "metadata": {"bid_ntce_nm": "2026년 조림지 풀베기사업(2차)(영암지구)"},
            "distance": 0.2980,
        },
        {
            "id": "bid_10179117",
            "document": "[공고명] 2026년 조림지풀베기사업 2차 (산동용방2지구)\n[수요기관] 구례군산림조합",
            "metadata": {"bid_ntce_nm": "2026년 조림지풀베기사업 2차 (산동용방2지구)"},
            "distance": 0.3041,
        },
        {
            "id": "bid_10146781",
            "document": "[공고명] 2026년 2차 조림지 풀베기사업(산청오부지구)\n[수요기관] 산청군산림조합",
            "metadata": {"bid_ntce_nm": "2026년 2차 조림지 풀베기사업(산청오부지구)"},
            "distance": 0.3091,
        },
        {
            "id": "bid_10148336",
            "document": "[공고명] 2026년 조림지 풀베기 사업(대술지구 2차)\n[수요기관] 예산군산림조합",
            "metadata": {"bid_ntce_nm": "2026년 조림지 풀베기 사업(대술지구 2차)"},
            "distance": 0.3114,
        },
        {
            "id": "bid_7951329",
            "document": "[공고명] 2026년 조림지 풀베기사업(신양2지구 2차)\n[수요기관] 예산군산림조합",
            "metadata": {"bid_ntce_nm": "2026년 조림지 풀베기사업(신양2지구 2차)"},
            "distance": 0.3123,
        },
        {
            "id": "bid_10148341",
            "document": "[공고명] 2026년 조림지 풀베기사업(예산지구 2차)\n[수요기관] 예산군산림조합",
            "metadata": {"bid_ntce_nm": "2026년 조림지 풀베기사업(예산지구 2차)"},
            "distance": 0.3147,
        },
        {
            "id": "bid_10146882",
            "document": "[공고명] 2026년 조림지 풀베기사업(2차)(신북지구)\n[수요기관] 영암군산림조합",
            "metadata": {"bid_ntce_nm": "2026년 조림지 풀베기사업(2차)(신북지구)"},
            "distance": 0.3151,
        },
        {
            "id": "bid_5976271",
            "document": "[공고명] 2026년 조림지풀베기사업(2-4지구)(2회베기)\n[수요기관] 영암군산림조합",
            "metadata": {"bid_ntce_nm": "2026년 조림지풀베기사업(2-4지구)(2회베기)"},
            "distance": 0.3155,
        },
        {
            "id": "bid_10169448",
            "document": f"[공고명] {Q21_TARGET_TITLE}\n[수요기관] 경상남도 거제시",
            "metadata": {
                "bid_ntce_nm": Q21_TARGET_TITLE,
                "bid_ntce_dt": "2026-08-13 20:01:17",
            },
            "distance": 0.3161,
        },
    ]

    reranked = _rerank_by_exact_title(docs, Q21_QUERY)

    # 9위였던 bid_10169448 이 1위(인덱스 0)로 승격되어야 함
    assert len(reranked) == len(docs)
    assert reranked[0]["id"] == "bid_10169448"
    assert reranked[0]["metadata"]["bid_ntce_nm"] == Q21_TARGET_TITLE

    # 나머지 문서는 기존 distance 순서를 유지해야 함
    other_ids = [d["id"] for d in reranked[1:]]
    expected_other_ids = [
        "bid_10146912",
        "bid_10179117",
        "bid_10146781",
        "bid_10148336",
        "bid_7951329",
        "bid_10148341",
        "bid_10146882",
        "bid_5976271",
    ]
    assert other_ids == expected_other_ids


# ===========================================================================
# 2. 최소 길이 하한 미만 제목 비승격 검증
# ===========================================================================


def test_rerank_ignores_short_title_under_min_length_guard():
    """최소 길이 하한(RERANK_MIN_TITLE_LENGTH=5) 미만의 짧은 공고명은 질의에 포함되어도 승격되지 않아야 합니다."""
    # '풀베기' (3자), '조림' (2자) 은 RERANK_MIN_TITLE_LENGTH 미만이므로 오탐 방지 가드에 걸려야 함
    short_title_doc = {
        "id": "bid_short",
        "document": "[공고명] 풀베기\n[수요기관] 산림청",
        "metadata": {"bid_ntce_nm": "풀베기"},
        "distance": 0.45,
    }
    other_doc = {
        "id": "bid_other",
        "document": "[공고명] 일반 산림 정비 사업\n[수요기관] 산림청",
        "metadata": {"bid_ntce_nm": "일반 산림 정비 사업"},
        "distance": 0.20,
    }

    docs = [other_doc, short_title_doc]
    reranked = _rerank_by_exact_title(docs, Q21_QUERY)

    # short_title_doc 은 승격되지 않고 기존 distance 순서(other_doc 먼저) 유지
    assert len(reranked) == 2
    assert reranked[0]["id"] == "bid_other"
    assert reranked[1]["id"] == "bid_short"


# ===========================================================================
# 3. 매칭 대상 없을 때 distance 순서 보존 검증
# ===========================================================================


def test_rerank_preserves_original_distance_order_when_no_match():
    """질의와 일치하는 공고명이 없는 경우 원본 후보 리스트의 distance 순서가 완전히 유지되어야 합니다."""
    docs = [
        {"id": "doc_1", "document": "[공고명] 도로포장 공사 1차", "distance": 0.10},
        {"id": "doc_2", "document": "[공고명] 상하수도 정비 사업", "distance": 0.20},
        {"id": "doc_3", "document": "[공고명] 학교 시설 개선 공사", "distance": 0.30},
    ]

    unrelated_query = "2026년 항만 시설 안전 점검 용역 관련 현황"
    reranked = _rerank_by_exact_title(docs, unrelated_query)

    assert len(reranked) == 3
    assert [d["id"] for d in reranked] == ["doc_1", "doc_2", "doc_3"]


# ===========================================================================
# 4. 복수 승격 시 결정적 정렬 순서 보존 검증
# ===========================================================================


def test_rerank_multiple_matches_sorted_deterministically():
    """동일 질의에 복수 문서가 포함 매칭될 때 _extract_doc_sort_key(공고일시 최신순 등)로 결정적 정렬되어야 합니다."""
    doc_older = {
        "id": "bid_2025_east",
        "document": f"[공고명] {Q21_TARGET_TITLE}\n[공고일시] 2025-08-10 10:00:00",
        "metadata": {
            "bid_ntce_no": "20250810001",
            "bid_ntce_nm": Q21_TARGET_TITLE,
            "bid_ntce_dt": "2025-08-10 10:00:00",
        },
        "distance": 0.15,  # 과거 공고의 벡터 거리가 더 가깝더라도
    }
    doc_newer = {
        "id": "bid_2026_east",
        "document": f"[공고명] {Q21_TARGET_TITLE}\n[공고일시] 2026-08-13 20:01:17",
        "metadata": {
            "bid_ntce_no": "20260813001",
            "bid_ntce_nm": Q21_TARGET_TITLE,
            "bid_ntce_dt": "2026-08-13 20:01:17",
        },
        "distance": 0.35,  # 최신 공고의 벡터 거리가 더 멀더라도
    }
    other_doc = {
        "id": "bid_unrelated",
        "document": "[공고명] 기타 산림 사업",
        "metadata": {"bid_ntce_nm": "기타 산림 사업"},
        "distance": 0.05,
    }

    # 입력 리스트 순서: unrelated, older, newer
    docs = [other_doc, doc_older, doc_newer]
    reranked = _rerank_by_exact_title(docs, Q21_QUERY)

    # 1위는 최신(2026) 공고, 2위는 과거(2025) 공고, 3위는 미일치 문서
    assert _extract_doc_sort_key(doc_newer) > _extract_doc_sort_key(doc_older)
    assert len(reranked) == 3
    assert reranked[0]["id"] == "bid_2026_east"
    assert reranked[1]["id"] == "bid_2025_east"
    assert reranked[2]["id"] == "bid_unrelated"


# ===========================================================================
# 5. HybridRAGEngine: Lexical 포함 매칭 시 벡터 경로 미생략(No Bypass) 검증
# ===========================================================================


def test_engine_containment_match_does_not_bypass_vector_search(monkeypatch):
    """Meilisearch 에서 부분/포함 매칭(containment)만 일치한 경우 벡터 검색이 생략(bypass)되지 않고 실행되어야 합니다."""
    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)

    lexical_hit = {
        "id": "announcement_Cnstwk_R26BK01682348",
        "source_id": 10169448,
        "dataset": "announcement",
        "bid_ntce_no": "R26BK01682348",
        "bid_ntce_nm": Q21_TARGET_TITLE,
        "dminstt_nm": "경상남도 거제시",
        "category": "Cnstwk",
        "bid_ntce_dt": "2026-08-13 20:01:17",
    }

    class MockMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            return {"hits": [lexical_hit]}

    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: MockMeiliClient(),
    )

    vector_doc = {
        "id": "vec_doc_10169448",
        "document": f"[공고명] {Q21_TARGET_TITLE}\n[수요기관] 경상남도 거제시",
        "metadata": {"bid_ntce_nm": Q21_TARGET_TITLE},
        "distance": 0.3161,
    }

    mock_semantic = MagicMock(return_value=SemanticSearchResult(ok=True, documents=[vector_doc]))
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    # 자연어 질의(q21)를 보내면 query_key 는 질의 전체가 되므로 doc_title 과 엄격 동치는 성립하지 않고 포함 매칭만 성립함
    context = engine._prepare_context(Q21_QUERY)

    # 벡터 검색이 호출되었음을 검증 (바이패스되지 않음)
    mock_semantic.assert_called_once()
    assert context.vector_docs is not None
    assert len(context.vector_docs) >= 1
    assert context.vector_docs[0]["metadata"]["bid_ntce_nm"] == Q21_TARGET_TITLE
    assert "동부지구" in context.vector_docs[0]["document"]


# ===========================================================================
# 6. HybridRAGEngine: Lexical 엄격 동치 일치 시 벡터 경로 생략(Bypass) 검증
# ===========================================================================


def test_engine_strict_equality_match_bypasses_vector_search(monkeypatch):
    """Meilisearch 에서 질의와 완전히 일치하는 엄격 동치(==) 공고명이 적중하면 벡터 검색이 생략(bypass)되어야 합니다."""
    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)

    lexical_hit = {
        "id": "announcement_Cnstwk_R26BK01682348",
        "source_id": 10169448,
        "dataset": "announcement",
        "bid_ntce_no": "R26BK01682348",
        "bid_ntce_nm": Q21_TARGET_TITLE,
        "dminstt_nm": "경상남도 거제시",
        "category": "Cnstwk",
        "bid_ntce_dt": "2026-08-13 20:01:17",
    }

    class MockMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            return {"hits": [lexical_hit]}

    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: MockMeiliClient(),
    )

    mock_semantic = MagicMock()
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    # 따옴표로 감싼 정확 공고명 질의는 lexical_query 가 정확 공고명과 엄격 일치함
    context = engine._prepare_context(f'"{Q21_TARGET_TITLE}"')

    # 벡터 검색이 호출되지 않았음을 검증 (바이패스 성공)
    mock_semantic.assert_not_called()
    assert context.vector_docs is not None
    assert len(context.vector_docs) == 1
    assert context.vector_docs[0]["metadata"]["bid_ntce_nm"] == Q21_TARGET_TITLE
    assert "동부지구" in context.vector_docs[0]["document"]


# ===========================================================================
# 8. Lexical 공고 전용 문서가 낙찰 결과 문서를 밀어내지 않는지 검증
# ===========================================================================


def test_lexical_announcement_docs_do_not_displace_vector_result_docs(monkeypatch):
    """Lexical 채널은 dataset="announcement" 만 조회해 낙찰 결과 필드를 담지 않습니다.

    포함 매칭만 성립한 공고 전용 문서를 상위로 승격하면 결과를 담은 벡터 문서가
    top_k 절단선 밖으로 밀려 낙찰 질의가 답을 잃습니다. 2026-08-30 정본 측정에서
    q05, q08 이 이 기전으로 회귀했습니다(evidence recall 은 1.0 을 유지한 채
    numeric 미검출과 과잉거절만 발생해 검색 지표로는 드러나지 않았습니다).
    """
    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)

    announcement_only_hits = [
        {
            "id": f"announcement_Cnstwk_R26BK0168{idx:04d}",
            "source_id": 10169000 + idx,
            "dataset": "announcement",
            "bid_ntce_no": f"R26BK0168{idx:04d}",
            "bid_ntce_nm": Q21_TARGET_TITLE,
            "dminstt_nm": "경상남도 거제시",
            "category": "Cnstwk",
            "bid_ntce_dt": "2026-08-13 20:01:17",
        }
        for idx in range(1, 5)
    ]

    class MockMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            return {"hits": announcement_only_hits}

    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: MockMeiliClient(),
    )

    result_doc = {
        "id": "vec_doc_10169448",
        "document": (
            f"[공고명] {Q21_TARGET_TITLE}\n[수요기관] 경상남도 거제시\n"
            "[낙찰업체] 주식회사 백화\n[낙찰금액] 48,445,040\n[낙찰률] 90.0150"
        ),
        "metadata": {"bid_ntce_nm": Q21_TARGET_TITLE, "has_result": True},
        "distance": 0.3161,
    }

    monkeypatch.setattr(
        "src.rag.engine.retrieve_semantic_context",
        MagicMock(return_value=SemanticSearchResult(ok=True, documents=[result_doc])),
    )

    engine = HybridRAGEngine()
    context = engine._prepare_context(Q21_QUERY)

    assert context.vector_docs, "벡터 문서가 비어서는 안 됩니다"
    documents = [doc.get("document") or "" for doc in context.vector_docs]
    assert any("낙찰금액" in text for text in documents), (
        "낙찰 결과를 담은 벡터 문서가 공고 전용 Lexical 문서에 밀려났습니다"
    )
    assert context.vector_docs[0]["id"] == "vec_doc_10169448"
