"""
src/app/schemas/chatbot.py

챗봇 요청/응답 스키마. 응답 필드는 원본 chat_api JsonResponse 계약을 따릅니다.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from src.app.core.timeutil import utcnow


class ChatRequest(BaseModel):
    """원본 chat_api POST 파라미터 대응."""

    message: str = Field("", description="사용자 메시지")
    session_key: str | None = Field(None, description="대화 세션 키")
    confirmation_token: str = Field("", description="자동화 실행 확인 토큰")


class PlanStepPayload(BaseModel):
    step_id: str
    kind: str
    tool: str


class ChatResponse(BaseModel):
    """원본 chat_api 응답 계약."""

    status: str = "success"
    mode: str = "answer"
    intent: str = ""
    message: str = ""
    answer: str = ""
    kb_status: dict[str, Any] | None = None
    suggestions: list[str] = Field(default_factory=list)
    advisory_signals: list[dict[str, Any]] = Field(default_factory=list)
    visualizations: list[dict[str, Any]] = Field(default_factory=list)
    provenance: dict[str, Any] | None = None
    plan_steps: list[PlanStepPayload] = Field(default_factory=list)
    result_payload: dict[str, Any] = Field(default_factory=dict)
    job: dict[str, Any] | None = None
    confirmation_token: str = ""
    session_key: str = ""
    # 세션 전환 응답 전용. chat.html 의 사이드바가 대화창을 복원할 때 사용합니다.
    last_query: str = ""
    history: list[dict[str, Any]] = Field(default_factory=list)
    llm_backend: str = Field("", description="답변을 생성한 LLM 백엔드")
    latency_ms: float = 0.0


class ChatbotQueryRequest(BaseModel):
    """리팩토링 신규 간이 계약 (단발 질의)."""

    query: str = Field(..., min_length=1, description="질문 내용")
    session_id: str | None = Field(None, description="세션 ID")
    stream: bool = Field(False, description="실시간 SSE 스트리밍 여부")


class ChatbotQueryResponse(BaseModel):
    query: str
    response: str
    retrieved_docs: list[dict[str, Any]] = Field(
        default_factory=list, description="RAG 참조 문서 정보"
    )
    latency_ms: float = Field(0.0, description="응답 소요 시간 (ms)")
    route_reason: str = ""
    citations: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utcnow)
