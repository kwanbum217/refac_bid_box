"""
src/rag/vector_store.py

ChromaDB 검색 래퍼 (원본 rag_engine.retrieve_semantic_context 이식 + 비동기 래퍼).
컬렉션명(bidding_kb)과 반환 스키마(document/metadata/distance)를 원본과 동일하게 유지합니다.
"""

from __future__ import annotations

import asyncio
import unicodedata
from pathlib import Path
from typing import Any

from src.app.core.config import PROJECT_ROOT, settings
from src.rag.schemas import RetrievalPlan

DEFAULT_COLLECTION = "bidding_kb"


def _normalize_text(value: str | None) -> str:
    return unicodedata.normalize("NFC", (value or "").strip())


def retrieve_semantic_context(plan: RetrievalPlan) -> list[dict[str, Any]]:
    """원본 rag_engine.retrieve_semantic_context 와 동일한 동기 검색 경로."""
    semantic_query = _normalize_text(plan.semantic_query)
    if not semantic_query:
        return []

    try:
        import chromadb

        client = chromadb.PersistentClient(path=str(settings.CHROMA_DB_PATH))
        collection = client.get_collection(DEFAULT_COLLECTION)
        results = collection.query(query_texts=[semantic_query], n_results=plan.top_k)
    except Exception as exc:
        return [{"document": f"문맥 검색 오류: {exc}", "metadata": {}, "distance": None}]

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
    return structured_documents


class AsyncVectorStore:
    """이벤트 루프를 막지 않도록 ChromaDB 조회를 스레드로 오프로드합니다."""

    def __init__(self, chroma_dir: str | Path | None = None):
        self.chroma_path = Path(chroma_dir or PROJECT_ROOT / "chroma_db")

    async def search_similar_docs(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        plan = RetrievalPlan(use_vector=True, semantic_query=query, top_k=max(int(top_k or 3), 1))
        return await asyncio.to_thread(retrieve_semantic_context, plan)


vector_store = AsyncVectorStore()
