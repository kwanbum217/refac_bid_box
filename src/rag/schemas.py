from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class RetrievalPlan(BaseModel):
    use_sql: bool = False
    use_vector: bool = False
    use_kb_status: bool = False
    filters: dict[str, Any] = Field(default_factory=dict)
    semantic_query: str = ""
    top_k: int = 3
    time_bias: str = ""
    route_reason: str = ""
    insufficiency_hints: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    id: str
    type: str
    content: Any
    metadata: dict[str, Any] = Field(default_factory=dict)
    relevance_score: Optional[float] = None


class AnswerBundle(BaseModel):
    answer: str
    retrieved_docs: list[dict[str, Any]] = Field(default_factory=list)
    route_reason: str = ""
    latency_ms: float = 0.0
