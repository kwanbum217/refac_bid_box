"""
src/rag/vector_store.py

ChromaDB 비동기 검색 래퍼 (원본 bidding_kb 컬렉션 사용).
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

from src.app.core.config import PROJECT_ROOT

DEFAULT_COLLECTION = "bidding_kb"


class AsyncVectorStore:
    def __init__(self, chroma_dir: str | Path | None = None):
        self.chroma_path = Path(chroma_dir or PROJECT_ROOT / "chroma_db")
        self.client = None
        self.collection = None
        self._initialized = False

    def _ensure_client(self):
        if self._initialized:
            return
        self._initialized = True
        if not self.chroma_path.exists():
            return
        try:
            import chromadb

            self.client = chromadb.PersistentClient(path=str(self.chroma_path))
            self.collection = self.client.get_or_create_collection(DEFAULT_COLLECTION)
        except Exception as exc:
            print(f"[VectorStore] ChromaDB 연결 경고: {exc}")

    async def search_similar_docs(self, query: str, top_k: int = 3) -> list[dict[str, Any]]:
        self._ensure_client()
        if self.collection is None:
            return []

        def _query():
            results = self.collection.query(query_texts=[query], n_results=top_k)
            docs: list[dict[str, Any]] = []
            documents = (results.get("documents") or [[]])[0]
            metadatas = (results.get("metadatas") or [[]])[0]
            distances = (results.get("distances") or [[]])[0]
            for idx, document in enumerate(documents):
                docs.append(
                    {
                        "content": document,
                        "document": document,
                        "metadata": metadatas[idx] if idx < len(metadatas) else {},
                        "score": 1.0 - float(distances[idx]) if idx < len(distances) else None,
                    }
                )
            return docs

        try:
            return await asyncio.to_thread(_query)
        except Exception as exc:
            print(f"[VectorStore] 쿼리 실행 경고: {exc}")
            return []


vector_store = AsyncVectorStore()
