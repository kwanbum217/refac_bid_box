"""
src/app/services/planner.py

챗봇 의도 분류 및 실행 계획 (원본 planner.py 규칙 기반 핵심 이식).
"""

from __future__ import annotations

from pydantic import BaseModel, Field

STATISTICS_KEYWORDS = ("통계", "평균", "추세", "비교", "건수", "낙찰률", "경쟁률", "집계", "그래프", "차트")
PREDICTION_KEYWORDS = ("예측", "투찰가", "투찰 금액", "입찰가", "낙찰가", "사투가")
COLLECTION_KEYWORDS = ("수집", "갱신", "업데이트", "최신화", "공고 수집")
KB_KEYWORDS = ("kb", "지식베이스", "벡터", "임베딩")


class ChatPlan(BaseModel):
    intent_type: str = "knowledge_query"
    action_key: str = "rag_query"
    requires_confirmation: bool = False
    route_reason: str = ""
    suggested_filters: dict = Field(default_factory=dict)


def build_chat_plan(query: str) -> ChatPlan:
    lowered = (query or "").lower()

    if any(k in lowered for k in PREDICTION_KEYWORDS):
        return ChatPlan(
            intent_type="prediction_validate",
            action_key="bid_prediction",
            route_reason="예측/투찰가 관련 질의",
        )

    if any(k in lowered for k in COLLECTION_KEYWORDS):
        return ChatPlan(
            intent_type="collect_refresh",
            action_key="collect_bids",
            requires_confirmation=True,
            route_reason="G2B 데이터 수집 요청",
        )

    if any(k in lowered for k in KB_KEYWORDS):
        return ChatPlan(
            intent_type="kb_refresh",
            action_key="kb_refresh",
            requires_confirmation=True,
            route_reason="지식베이스 갱신 요청",
        )

    if any(k in lowered for k in STATISTICS_KEYWORDS):
        return ChatPlan(
            intent_type="statistics_query",
            action_key="bid_statistics",
            route_reason="정형 통계 질의",
        )

    return ChatPlan(
        intent_type="knowledge_query",
        action_key="rag_query",
        route_reason="기본 RAG 지식 질의",
    )
