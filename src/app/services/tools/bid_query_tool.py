"""
src/app/services/tools/bid_query_tool.py

정형 통계 질의 도구 (원본 apps/chatbot/tools/bid_query_tool.py 1:1 이식).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.rag.engine import build_retrieval_plan
from src.rag.schemas import RetrievalPlan
from src.rag.structured_data import retrieve_structured_data


def execute(
    *,
    db: Session,
    query: str = "",
    institution_name: str = "",
    category: str = "",
    years: int = 5,
    date_from: str = "",
    date_to: str = "",
    **_ignored: Any,
) -> dict[str, Any]:
    retrieval_plan = build_retrieval_plan(query)
    filters = dict(retrieval_plan.filters or {})
    if institution_name:
        filters["institution_name"] = institution_name
    if category:
        filters["category"] = category
    if date_from:
        filters["date_from"] = date_from
    if date_to:
        filters["date_to"] = date_to
    if years and "date_from" not in filters and "date_to" not in filters:
        filters["relative_years"] = years

    explicit_plan = RetrievalPlan(
        use_sql=True,
        use_vector=False,
        use_kb_status=False,
        filters=filters,
        semantic_query=query,
        top_k=retrieval_plan.top_k,
        time_bias=retrieval_plan.time_bias,
        route_reason=retrieval_plan.route_reason or "bid_query_tool execution",
        insufficiency_hints=list(retrieval_plan.insufficiency_hints),
    )
    result = retrieve_structured_data(db, explicit_plan)

    return {
        "query": query,
        "institution_name": institution_name,
        "category": category,
        "years": years,
        "retrieval_plan": explicit_plan.model_dump(),
        "result": result,
    }
