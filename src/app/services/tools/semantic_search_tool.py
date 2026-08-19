"""
src/app/services/tools/semantic_search_tool.py

의미 검색 도구 (원본 apps/chatbot/tools/semantic_search_tool.py 1:1 이식).
"""

from __future__ import annotations

from typing import Any

from src.rag.engine import build_retrieval_plan
from src.rag.schemas import DEFAULT_VECTOR_TOP_K, RetrievalPlan
from src.rag.vector_store import retrieve_semantic_context


def execute(
    *, query: str = "", top_k: int = DEFAULT_VECTOR_TOP_K, **_ignored: Any
) -> dict[str, Any]:
    retrieval_plan = build_retrieval_plan(query)
    explicit_plan = RetrievalPlan(
        use_sql=False,
        use_vector=True,
        use_kb_status=False,
        filters=dict(retrieval_plan.filters or {}),
        semantic_query=query,
        top_k=max(int(top_k or retrieval_plan.top_k or DEFAULT_VECTOR_TOP_K), 1),
        time_bias=retrieval_plan.time_bias,
        route_reason=retrieval_plan.route_reason or "semantic_search_tool execution",
        insufficiency_hints=list(retrieval_plan.insufficiency_hints),
    )
    result = retrieve_semantic_context(explicit_plan)
    documents = result.documents

    return {
        "query": query,
        "retrieval_plan": explicit_plan.model_dump(),
        "search_failed": not result.ok,
        "documents": documents,
        "document": documents[0]["document"] if documents else "",
    }
