"""
src/rag/vector_store.py

ChromaDB 검색 래퍼 (원본 rag_engine.retrieve_semantic_context 이식 + 비동기 래퍼).
컬렉션명(bidding_kb)과 반환 스키마(document/metadata/distance)를 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from src.app.core.config import PROJECT_ROOT, settings
from src.rag.embeddings import get_collection
from src.rag.query_planning import is_result_query
from src.rag.schemas import DEFAULT_VECTOR_TOP_K, RetrievalPlan

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "bidding_kb"

# bidding_kb 메타데이터에서 ChromaDB where 절로 표현 가능한 필드
SUPPORTED_METADATA_KEYS = frozenset({"category", "has_result", "type", "id", "doc_hash", "fmt"})


@dataclass
class SemanticSearchResult:
    ok: bool
    documents: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    relaxed: bool = False

    @property
    def filter_relaxed(self) -> bool:
        return self.relaxed


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def build_vector_where(
    plan_or_filters: RetrievalPlan | dict[str, Any] | None = None,
    query: str | None = None,
    *,
    filters: dict[str, Any] | None = None,
) -> dict[str, Any] | None:
    """RetrievalPlan 또는 필터 딕셔너리를 ChromaDB where 절 문법으로 변환합니다.

    - bidding_kb 메타데이터로 표현 가능한 키(category 등)만 where 절에 포함합니다.
    - 날짜(date_from/date_to), 기관명(institution_name) 등 메타데이터에 없는 필터는
      조용히 누락되지 않도록 디버그/추적 로그를 남기고 where 절에서 제외합니다.
    - 낙찰 결과를 묻는 질의이거나 필터에 has_result 가 지정된 경우 has_result 조건을 반영합니다.
    - 조건이 2개 이상이면 ChromaDB 표준인 {"$and": [...]} 로 결합합니다.
    """
    if isinstance(plan_or_filters, RetrievalPlan):
        raw_filters = dict(plan_or_filters.filters or {})
        effective_query = query if query is not None else plan_or_filters.semantic_query
    elif isinstance(plan_or_filters, dict):
        raw_filters = dict(plan_or_filters)
        effective_query = query or ""
    elif filters is not None:
        raw_filters = dict(filters)
        effective_query = query or ""
    else:
        raw_filters = {}
        effective_query = query or ""

    # 메타데이터로 표현 불가능한 키 기록
    unsupported_keys = [k for k in raw_filters if k not in SUPPORTED_METADATA_KEYS]
    if unsupported_keys:
        logger.debug(
            "ChromaDB bidding_kb 메타데이터에 없어 where 절에서 제외된 필터: %s (전체 필터=%s)",
            unsupported_keys,
            raw_filters,
        )

    conditions: list[dict[str, Any]] = []

    # 1. category 필터
    if raw_filters.get("category"):
        category_val = str(raw_filters["category"]).strip()
        if category_val:
            conditions.append({"category": category_val})

    # 2. has_result 필터 (명시적 필터 또는 질의 신호)
    if "has_result" in raw_filters and raw_filters["has_result"] is not None:
        conditions.append({"has_result": bool(raw_filters["has_result"])})
    elif effective_query and is_result_query(effective_query):
        conditions.append({"has_result": True})

    # 3. 기타 지원 메타데이터 키 (type, id 등)
    if raw_filters.get("type"):
        conditions.append({"type": str(raw_filters["type"])})
    if raw_filters.get("id") is not None:
        conditions.append({"id": raw_filters["id"]})

    if not conditions:
        return None
    if len(conditions) == 1:
        return conditions[0]
    return {"$and": conditions}


def retrieve_semantic_context(plan: RetrievalPlan) -> SemanticSearchResult:
    """원본 rag_engine.retrieve_semantic_context 와 동일한 동기 검색 경로.

    where 절 필터링을 적용하며, 필터 검색 결과가 0건일 경우 필터 없이 완화(fallback)
    재검색을 수행하여 결과를 반환하고 완화 여부(relaxed=True)를 결과에 기록합니다.
    """
    semantic_query = _normalize_text(plan.semantic_query)
    if not semantic_query:
        return SemanticSearchResult(ok=True, documents=[], error=None, relaxed=False)

    where = build_vector_where(plan)
    relaxed = False

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
        # 색인과 같은 임베딩 함수로 열어야 합니다. 그냥 get_collection 을 부르면
        # ChromaDB 가 기본 함수를 끼워 넣어, 실패 없이 결과만 엉뚱해집니다.
        collection = get_collection(client, DEFAULT_COLLECTION)

        if where is not None:
            results = collection.query(
                query_texts=[semantic_query],
                n_results=plan.top_k,
                where=where,
            )
            raw_docs = (results.get("documents") or [[]])[0] if results else []
            # 필터 적용 검색 결과가 0건이면 필터 없이 완화 재검색 수행
            if not raw_docs:
                logger.info(
                    "ChromaDB 필터 적용 결과 0건으로 필터 해제 완화 재검색 수행 (where=%s, query=%s)",
                    where,
                    semantic_query,
                )
                fallback_results = collection.query(
                    query_texts=[semantic_query],
                    n_results=plan.top_k,
                )
                results = fallback_results
                relaxed = True
        else:
            results = collection.query(query_texts=[semantic_query], n_results=plan.top_k)

    except Exception as exc:
        # 오류 문구를 문서로 돌려주면 안 됩니다. 그 문자열이 그대로 LLM 프롬프트에
        # 실려 검색이 성공한 것처럼 보이고, 화면과 로그 어디에도 실패가 남지
        # 않습니다. 2026-08-05 에 ChromaDB 컬렉션 설정이 깨져 닷새 동안 챗봇이
        # 지식베이스 없이 답하고 있었는데 아무도 몰랐던 것이 이 때문입니다.
        logger.exception("ChromaDB 검색 실패 (collection=%s)", DEFAULT_COLLECTION)
        return SemanticSearchResult(
            ok=False, documents=[], error=str(exc) or exc.__class__.__name__, relaxed=False
        )

    documents = (results.get("documents") or [[]])[0] if results else []
    metadatas = (results.get("metadatas") or [[]])[0] if results else []
    distances = (results.get("distances") or [[]])[0] if results else []

    structured_documents = []
    for index, document in enumerate(documents):
        normalized_document = _normalize_text(str(document))
        structured_documents.append(
            {
                "document": normalized_document,
                "content": normalized_document,
                "metadata": metadatas[index] if index < len(metadatas) else {},
                "distance": distances[index] if index < len(distances) else None,
            }
        )
    return SemanticSearchResult(
        ok=True, documents=structured_documents, error=None, relaxed=relaxed
    )


class AsyncVectorStore:
    """이벤트 루프를 막지 않도록 ChromaDB 조회를 스레드로 오프로드합니다."""

    def __init__(self, chroma_dir: str | Path | None = None):
        self.chroma_path = Path(chroma_dir or PROJECT_ROOT / "chroma_db")

    async def search_similar_docs(
        self,
        query: str,
        top_k: int = DEFAULT_VECTOR_TOP_K,
        filters: dict[str, Any] | None = None,
    ) -> SemanticSearchResult:
        plan = RetrievalPlan(
            use_vector=True,
            semantic_query=query,
            top_k=max(int(top_k or DEFAULT_VECTOR_TOP_K), 1),
            filters=filters or {},
        )
        return await asyncio.to_thread(retrieve_semantic_context, plan)


vector_store = AsyncVectorStore()
