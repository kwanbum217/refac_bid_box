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
from src.rag.schemas import DEFAULT_VECTOR_TOP_K, RetrievalPlan

logger = logging.getLogger(__name__)

DEFAULT_COLLECTION = "bidding_kb"


@dataclass
class SemanticSearchResult:
    ok: bool
    documents: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def retrieve_semantic_context(plan: RetrievalPlan) -> SemanticSearchResult:
    """원본 rag_engine.retrieve_semantic_context 와 동일한 동기 검색 경로."""
    semantic_query = _normalize_text(plan.semantic_query)
    if not semantic_query:
        return SemanticSearchResult(ok=True, documents=[], error=None)

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
        # 색인과 같은 임베딩 함수로 열어야 합니다. 그냥 get_collection 을 부르면
        # ChromaDB 가 기본 함수를 끼워 넣어, 실패 없이 결과만 엉뚱해집니다.
        collection = get_collection(client, DEFAULT_COLLECTION)
        results = collection.query(query_texts=[semantic_query], n_results=plan.top_k)
    except Exception as exc:
        # 오류 문구를 문서로 돌려주면 안 됩니다. 그 문자열이 그대로 LLM 프롬프트에
        # 실려 검색이 성공한 것처럼 보이고, 화면과 로그 어디에도 실패가 남지
        # 않습니다. 2026-08-05 에 ChromaDB 컬렉션 설정이 깨져 닷새 동안 챗봇이
        # 지식베이스 없이 답하고 있었는데 아무도 몰랐던 것이 이 때문입니다.
        logger.exception("ChromaDB 검색 실패 (collection=%s)", DEFAULT_COLLECTION)
        return SemanticSearchResult(
            ok=False, documents=[], error=str(exc) or exc.__class__.__name__
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
    return SemanticSearchResult(ok=True, documents=structured_documents, error=None)


class AsyncVectorStore:
    """이벤트 루프를 막지 않도록 ChromaDB 조회를 스레드로 오프로드합니다."""

    def __init__(self, chroma_dir: str | Path | None = None):
        self.chroma_path = Path(chroma_dir or PROJECT_ROOT / "chroma_db")

    async def search_similar_docs(
        self, query: str, top_k: int = DEFAULT_VECTOR_TOP_K
    ) -> SemanticSearchResult:
        plan = RetrievalPlan(
            use_vector=True,
            semantic_query=query,
            top_k=max(int(top_k or DEFAULT_VECTOR_TOP_K), 1),
        )
        return await asyncio.to_thread(retrieve_semantic_context, plan)


vector_store = AsyncVectorStore()
