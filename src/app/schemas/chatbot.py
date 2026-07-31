from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field


class ChatbotQueryRequest(BaseModel):
    query: str = Field(..., min_length=1, description="질문 내용")
    session_id: Optional[str] = Field(None, description="세션 ID")
    stream: bool = Field(False, description="실시간 SSE 스트리밍 여부")


class ChatbotQueryResponse(BaseModel):
    query: str
    response: str
    retrieved_docs: list[dict[str, Any]] = Field(default_factory=list, description="RAG 참조 문서 정보")
    latency_ms: float = Field(0.0, description="응답 소요 시간 (ms)")
    created_at: datetime = Field(default_factory=datetime.utcnow)
