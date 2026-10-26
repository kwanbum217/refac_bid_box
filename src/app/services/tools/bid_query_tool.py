"""
src/app/services/tools/bid_query_tool.py

정형 통계 질의 도구 (원본 apps/chatbot/tools/bid_query_tool.py 1:1 이식).
"""

from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from src.rag.engine import build_retrieval_plan
from src.rag.query_planning import (
    apply_default_statistics_window,
    replace_whole_period_insufficiency_hint,
    uses_recent_announcement_window,
)
from src.rag.schemas import DEFAULT_STATISTICS_WINDOW_YEARS, RetrievalPlan
from src.rag.structured_data import retrieve_structured_data


def execute(
    *,
    db: Session,
    query: str = "",
    institution_name: str = "",
    category: str = "",
    years: int | None = None,
    date_from: str = "",
    date_to: str = "",
    limit: int = 0,
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
    explicit_window = bool(filters.get("date_from") or filters.get("date_to"))
    is_quarter_bucket = str(filters.get("time_bucket") or "") == "quarter"
    # 플래너는 기간을 말하지 않은 질의에도 years=5 를 넘깁니다. 공고 건수와
    # 금액 정렬 공고 목록은 그 기본값 대신 최근 30일 창을 쓰게 합니다.
    # years=0 처럼 호출부가 명시한 다른 값은 그대로 존중합니다.
    inject_years = years is not None and not explicit_window and not is_quarter_bucket
    if (
        inject_years
        and years == DEFAULT_STATISTICS_WINDOW_YEARS
        and uses_recent_announcement_window(filters, query)
    ):
        inject_years = False
    if inject_years:
        filters["relative_years"] = years
    filters = apply_default_statistics_window(filters, query=query)
    if limit:
        filters["result_limit"] = min(max(int(limit), 1), 20)

    explicit_plan = RetrievalPlan(
        use_sql=True,
        use_vector=False,
        use_kb_status=False,
        filters=filters,
        semantic_query=query,
        top_k=retrieval_plan.top_k,
        time_bias=retrieval_plan.time_bias,
        route_reason=retrieval_plan.route_reason or "bid_query_tool execution",
        insufficiency_hints=replace_whole_period_insufficiency_hint(
            list(retrieval_plan.insufficiency_hints), filters
        ),
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
