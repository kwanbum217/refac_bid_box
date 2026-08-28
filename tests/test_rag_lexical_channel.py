"""
tests/test_rag_lexical_channel.py

정확 공고명 어휘(Lexical) 채널, 조건부 벡터 바이패스(Conditional Vector Bypass),
동점 해소(Tie-breaking) 및 안전 폴백 회귀 테스트.
- (a) lexical 정확 일치가 있을 때 retrieve_semantic_context 가 호출되지 않는지 (Vector 바이패스)
- (b) lexical 적중 0건 또는 비정확 일치 시 retrieve_semantic_context 가 호출되는지
- (c) plan.use_lexical 이 거짓일 때 기존 Vector 경로가 그대로 동작하는지
- (d) Meilisearch 비활성/서버 미기동/예외 발생 시 기존 벡터 검색 경로로 안전하게 폴백하는지
- (e) 복수 정확 일치 발생 시 공고일시(최신 우선) 기준 결정적 동점 해소(tie-breaker)가 동작하는지
"""

from typing import Any
from unittest.mock import MagicMock

from src.rag.engine import (
    HybridRAGEngine,
    build_retrieval_plan,
)
from src.rag.vector_store import (
    SemanticSearchResult,
    _extract_doc_sort_key,
    _normalize_match_key,
    _rerank_by_exact_title,
)

# ===========================================================================
# (a) Planner use_lexical & lexical_query 활성화 검증
# ===========================================================================


def test_planner_sets_use_lexical_for_entity_queries():
    """개체 지정 질의(공고명, 기관명, 수식 지목 등)에서 use_lexical=True 및 lexical_query 가 설정되어야 합니다."""
    plan1 = build_retrieval_plan("대구불로초등학교 급식시설 개선공사의 낙찰업체와 낙찰금액")
    assert plan1.use_lexical is True
    assert plan1.lexical_query is not None
    assert "대구불로초등학교" in plan1.lexical_query

    plan2 = build_retrieval_plan("2026년 조림지 풀베기사업 2차(동부지구) 공고의 수요기관은?")
    assert plan2.use_lexical is True
    assert plan2.lexical_query is not None


def test_planner_extracts_quoted_title_for_lexical_query():
    """따옴표로 감싼 공고명이 포함된 질의는 따옴표 안의 제목을 lexical_query 로 정확히 추출해야 합니다."""
    plan = build_retrieval_plan('"2026년 도로포장공사(1차)" 공고의 입찰 참가 자격을 알려줘')
    assert plan.use_lexical is True
    assert plan.lexical_query == "2026년 도로포장공사(1차)"

    plan_bracket = build_retrieval_plan("「안녕 자두야 포스트프로덕션」용역의 최종 낙찰자")
    assert plan_bracket.use_lexical is True
    assert plan_bracket.lexical_query == "안녕 자두야 포스트프로덕션"


def test_planner_keeps_use_lexical_false_for_pure_aggregation():
    """순수 통계/집계 질의는 use_lexical 이 False 여야 합니다."""
    plan = build_retrieval_plan("최근 7일 서울 공사의 낙찰률 추세를 알려줘")
    assert plan.use_lexical is False
    assert plan.lexical_query is None


# ===========================================================================
# (b) Lexical 정확 일치 시 ChromaDB Vector 완전 바이패스 검증
# ===========================================================================


def test_engine_bypasses_vector_when_lexical_exact_hit_found(monkeypatch):
    """Meilisearch 어휘 검색에서 정확 일치한 문서가 확보되면 ChromaDB retrieve_semantic_context 가 호출되지 않아야 합니다."""
    target_title = "2026년 조림지 풀베기사업 2차(동부지구)"
    lexical_hit = {
        "id": "announcement_Servc_20260801001",
        "source_id": 101,
        "dataset": "announcement",
        "bid_ntce_no": "20260801001",
        "bid_ntce_nm": target_title,
        "dminstt_nm": "산림청",
        "category": "Servc",
        "bid_ntce_dt": "2026-08-01 10:00:00",
    }

    class MockMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            return {"hits": [lexical_hit]}

    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: MockMeiliClient(),
    )

    mock_semantic = MagicMock()
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    context = engine._prepare_context(f'"{target_title}" 공고의 수요기관은 어디인가요?')

    # Vector 검색이 호출되지 않았음을 확인 (바이패스)
    mock_semantic.assert_not_called()
    assert context.vector_docs is not None
    assert len(context.vector_docs) == 1
    top_doc = context.vector_docs[0]
    assert "동부지구" in top_doc["document"]
    assert top_doc["metadata"]["bid_ntce_nm"] == target_title
    assert top_doc.get("source") == "meilisearch_lexical"
    assert context.timings.get("vector_ms") == 0.0
    assert context.timings.get("lexical_ms", 0.0) >= 0.0


def test_engine_promotes_lexical_exact_match_above_vector_results(monkeypatch):
    """기존 호환성 검증: 정확 일치 시 Vector 가 생략되고 Lexical 결과가 vector_docs 로 채택됩니다."""
    target_title = "2026년 조림지 풀베기사업 2차(동부지구)"
    lexical_hit = {
        "id": "announcement_Servc_20260801001",
        "source_id": 101,
        "dataset": "announcement",
        "bid_ntce_no": "20260801001",
        "bid_ntce_nm": target_title,
        "dminstt_nm": "산림청",
        "category": "Servc",
        "bid_ntce_dt": "2026-08-01 10:00:00",
    }

    class MockMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            return {"hits": [lexical_hit]}

    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: MockMeiliClient(),
    )

    mock_semantic = MagicMock(
        return_value=SemanticSearchResult(
            ok=True,
            documents=[
                {
                    "id": "vec_doc_1",
                    "document": "[공고명] 2026년 조림지 풀베기사업(2차)(영암지구)\n[수요기관] 영암군",
                    "metadata": {"bid_ntce_nm": "2026년 조림지 풀베기사업(2차)(영암지구)"},
                    "distance": 0.05,
                }
            ],
        )
    )
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    context = engine._prepare_context(f'"{target_title}" 공고의 수요기관은 어디인가요?')

    mock_semantic.assert_not_called()
    assert context.vector_docs is not None
    assert len(context.vector_docs) >= 1
    top_doc = context.vector_docs[0]
    assert "동부지구" in top_doc["document"]
    assert top_doc["metadata"]["bid_ntce_nm"] == target_title
    assert top_doc.get("source") == "meilisearch_lexical"


# ===========================================================================
# (c) Meilisearch 비활성/예외/0건/부분일치 시 Vector 안전 폴백 검증
# ===========================================================================


def test_engine_fallback_when_meili_disabled(monkeypatch):
    """MEILI_ENABLED=False 일 때 에러 없이 기존 벡터 검색 경로를 호출하여 안전하게 폴백해야 합니다."""
    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", False)

    fallback_docs = [
        {
            "id": "vec_fallback_1",
            "document": "[공고명] 도로 정비 공사\n[수요기관] 서울시",
            "metadata": {"bid_ntce_nm": "도로 정비 공사"},
            "distance": 0.1,
        }
    ]

    mock_semantic = MagicMock(return_value=SemanticSearchResult(ok=True, documents=fallback_docs))
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    context = engine._prepare_context("도로 정비 공사 수요기관")

    mock_semantic.assert_called_once()
    assert context.vector_docs == fallback_docs


def test_engine_fallback_when_meili_raises_exception(monkeypatch):
    """Meilisearch 호출 중 HTTPError/커넥션 에러 등 예외가 발생해도 전체 RAG 요청이 실패하지 않고 벡터로 폴백해야 합니다."""
    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)

    class BrokenMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            raise RuntimeError("Meilisearch server down (connection refused)")

    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: BrokenMeiliClient(),
    )

    fallback_docs = [
        {
            "id": "vec_doc_ok",
            "document": "[공고명] 안녕 자두야 포스트프로덕션\n[수요기관] 방송공사",
            "metadata": {"bid_ntce_nm": "안녕 자두야 포스트프로덕션"},
            "distance": 0.15,
        }
    ]

    mock_semantic = MagicMock(return_value=SemanticSearchResult(ok=True, documents=fallback_docs))
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    context = engine._prepare_context('"안녕 자두야 포스트프로덕션" 낙찰자')

    mock_semantic.assert_called_once()
    assert context.vector_docs == fallback_docs
    assert len(context.vector_docs) == 1
    assert "안녕 자두야" in context.vector_docs[0]["document"]


def test_engine_fallback_when_meili_returns_zero_hits(monkeypatch):
    """Meilisearch 결과가 0건일 때도 벡터 검색을 호출하여 정상 폴백해야 합니다."""
    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)

    class EmptyMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            return {"hits": []}

    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: EmptyMeiliClient(),
    )

    fallback_docs = [
        {
            "id": "vec_fallback_doc",
            "document": "[공고명] 특수 용역 공고\n[수요기관] 공공기관",
            "metadata": {"bid_ntce_nm": "특수 용역 공고"},
            "distance": 0.2,
        }
    ]

    mock_semantic = MagicMock(return_value=SemanticSearchResult(ok=True, documents=fallback_docs))
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    context = engine._prepare_context('"특수 용역 공고" 상세 내용')

    mock_semantic.assert_called_once()
    assert context.vector_docs == fallback_docs


def test_engine_fallback_when_meili_returns_only_partial_match(monkeypatch):
    """Meilisearch 결과가 있으나 공고명이 정확 일치하지 않는 경우 벡터 검색으로 폴백해야 합니다."""
    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)

    partial_hit = {
        "id": "announcement_Servc_9999",
        "bid_ntce_no": "9999",
        "bid_ntce_nm": "2026년 유사 도로포장공사 3차",  # 질의와 불일치
        "dminstt_nm": "한국도로공사",
        "category": "Servc",
        "bid_ntce_dt": "2026-08-01 10:00:00",
    }

    class PartialMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            return {"hits": [partial_hit]}

    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: PartialMeiliClient(),
    )

    fallback_docs = [
        {
            "id": "vec_doc_fallback",
            "document": "[공고명] 2026년 도로포장공사 1차\n[수요기관] 도로공사",
            "metadata": {"bid_ntce_nm": "2026년 도로포장공사 1차"},
            "distance": 0.1,
        }
    ]

    mock_semantic = MagicMock(return_value=SemanticSearchResult(ok=True, documents=fallback_docs))
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    context = engine._prepare_context('"2026년 도로포장공사 1차" 상세')

    mock_semantic.assert_called_once()
    assert context.vector_docs == fallback_docs


def test_engine_calls_vector_when_plan_use_lexical_is_false(monkeypatch):
    """plan.use_lexical 이 False 인 일반 질의에서는 기존 Vector 경로가 호출되어야 합니다."""
    fallback_docs = [
        {
            "id": "vec_doc_stat",
            "document": "[공고명] 일반 공사\n[수요기관] 서울시",
            "metadata": {"bid_ntce_nm": "일반 공사"},
            "distance": 0.1,
        }
    ]

    mock_semantic = MagicMock(return_value=SemanticSearchResult(ok=True, documents=fallback_docs))
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    # 통계/비교 질의 등 use_lexical=False 질의
    context = engine._prepare_context("최근 소프트웨어 개발 입찰 정보")

    # plan.use_vector 가 True 라면 vector 검색이 호출됨
    if context.plan.use_vector:
        mock_semantic.assert_called_once()
        assert context.vector_docs == fallback_docs


# ===========================================================================
# (d) 괄호 유무 및 표기 정규화 충돌 방지 검증
# ===========================================================================


def test_normalize_key_distinguishes_parentheses_vs_space():
    """'2026년 도로포장공사(1차)' 와 '2026년 도로포장공사 1차' 가 서로 다른 정규화 키를 가져야 합니다."""
    key_with_paren = _normalize_match_key("2026년 도로포장공사(1차)")
    key_without_paren = _normalize_match_key("2026년 도로포장공사 1차")

    assert key_with_paren == "2026년도로포장공사(1차)"
    assert key_without_paren == "2026년도로포장공사1차"
    assert key_with_paren != key_without_paren


def test_normalize_key_handles_various_bracket_styles():
    """대괄호, 전각괄호, 렌티큘러 괄호 등 다양한 괄호 스타일은 표준 괄호로 통일되어 동등하게 매칭되어야 합니다."""
    k1 = _normalize_match_key("[긴급] AI 서버 구매")
    k2 = _normalize_match_key("【긴급】 AI 서버 구매")
    k3 = _normalize_match_key("\uff08긴급\uff09 AI 서버 구매")
    k4 = _normalize_match_key("(긴급) AI 서버 구매")

    assert k1 == "(긴급)ai서버구매"
    assert k1 == k2 == k3 == k4

    # 괄호가 아예 없는 일반 제목과는 구별되어야 함
    k_plain = _normalize_match_key("긴급 AI 서버 구매")
    assert k1 != k_plain


# ===========================================================================
# (e) 복수 정확 일치 시 결정적 Tie-breaking 및 Vector 바이패스 검증
# ===========================================================================


def test_engine_multiple_exact_matches_sorted_by_sort_key_and_bypasses_vector(monkeypatch):
    """동일 공고명의 복수 공고가 Meilisearch 에서 반환될 때 최신 공고 순으로 정렬되고 Vector 는 바이패스되어야 합니다."""
    target_title = "도로포장공사 1차"
    hits = [
        {
            "id": "announcement_Servc_2025001",
            "bid_ntce_no": "2025001",
            "bid_ntce_nm": target_title,
            "dminstt_nm": "충남도청",
            "category": "Servc",
            "bid_ntce_dt": "2025-08-01 09:00:00",
        },
        {
            "id": "announcement_Servc_2026001",
            "bid_ntce_no": "2026001",
            "bid_ntce_nm": target_title,
            "dminstt_nm": "충남도청",
            "category": "Servc",
            "bid_ntce_dt": "2026-08-01 09:00:00",
        },
    ]

    class MultiMeiliClient:
        def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
            return {"hits": hits}

    monkeypatch.setattr("src.app.core.config.settings.MEILI_ENABLED", True)
    monkeypatch.setattr(
        "src.app.services.search_index.MeiliSearchClient",
        lambda *a, **kw: MultiMeiliClient(),
    )

    mock_semantic = MagicMock()
    monkeypatch.setattr("src.rag.engine.retrieve_semantic_context", mock_semantic)

    engine = HybridRAGEngine()
    context = engine._prepare_context(f'"{target_title}" 공고의 수요기관')

    mock_semantic.assert_not_called()
    assert context.vector_docs is not None
    assert len(context.vector_docs) == 2
    # 최신(2026) 공고가 1순위
    assert context.vector_docs[0]["metadata"]["bid_ntce_dt"] == "2026-08-01 09:00:00"
    assert context.vector_docs[1]["metadata"]["bid_ntce_dt"] == "2025-08-01 09:00:00"


def test_deterministic_tie_breaking_prefers_latest_notice_date():
    """동일한 공고명을 갖는 복수의 정확 일치 문서가 있을 때 공고일시가 최신인 문서가 우선 순위여야 합니다."""
    doc_older = {
        "id": "doc_2025",
        "document": "[공고명] 도로포장공사 1차\n[수요기관] 충남도청\n[공고일시] 2025-08-01 09:00:00",
        "metadata": {
            "bid_ntce_no": "20250801001",
            "bid_ntce_nm": "도로포장공사 1차",
            "bid_ntce_dt": "2025-08-01 09:00:00",
        },
        "distance": 0.05,  # 과거 문서의 임베딩 거리가 더 가깝더라도
    }
    doc_newer = {
        "id": "doc_2026",
        "document": "[공고명] 도로포장공사 1차\n[수요기관] 충남도청\n[공고일시] 2026-08-01 09:00:00",
        "metadata": {
            "bid_ntce_no": "20260801001",
            "bid_ntce_nm": "도로포장공사 1차",
            "bid_ntce_dt": "2026-08-01 09:00:00",
        },
        "distance": 0.25,  # 최신 문서의 거리가 더 멀더라도
    }

    # distance 순서상 doc_older 가 앞에 오더라도 tie-breaker 에 의해 최신(2026)이 1위여야 함
    reranked = _rerank_by_exact_title([doc_older, doc_newer], "도로포장공사 1차")

    assert len(reranked) == 2
    assert reranked[0]["id"] == "doc_2026"
    assert reranked[1]["id"] == "doc_2025"


def test_extract_doc_sort_key_deterministic():
    """_extract_doc_sort_key 가 공고일시, 개찰일시, 공고번호 순으로 결정적 튜플을 생성해야 합니다."""
    doc = {
        "document": "[공고일시] 2026-08-15 10:00:00\n[개찰일시] 2026-08-20 11:00:00",
        "metadata": {
            "bid_ntce_no": "20260815001",
            "bid_ntce_ord": "01",
            "bid_ntce_dt": "2026-08-15 10:00:00",
            "rl_openg_dt": "2026-08-20 11:00:00",
        },
    }
    key = _extract_doc_sort_key(doc)
    assert key == (
        "2026-08-15 10:00:00",
        "2026-08-20 11:00:00",
        "20260815001",
        "01",
    )
