"""
src/rag/schemas.py

RAG 검색/근거 스키마 (원본 apps/chatbot/schemas/retrieval_schema.py,
evidence_schema.py 1:1 이식).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DEFAULT_VECTOR_TOP_K = 5


class RetrievalPlan(BaseModel):
    use_sql: bool = False
    use_vector: bool = False
    use_kb_status: bool = False
    filters: dict[str, Any] = Field(default_factory=dict)
    semantic_query: str = ""
    top_k: int = DEFAULT_VECTOR_TOP_K
    time_bias: str = ""
    route_reason: str = ""
    insufficiency_hints: list[str] = Field(default_factory=list)


class EvidenceItem(BaseModel):
    """답변 생성에 사용된 개별 근거 항목."""

    id: str = Field(..., description="Unique ID for this evidence item (e.g., bid_no or doc_id)")
    type: Literal["sql_stats", "vector_snippet", "kb_metadata"] = Field(
        ..., description="Type of evidence"
    )
    content: Any = Field(..., description="The actual data content (stat summary or text snippet)")
    metadata: dict[str, Any] = Field(
        default_factory=dict, description="Source metadata (URL, date, category, etc.)"
    )
    relevance_score: float | None = Field(
        None, description="Similarity or relevance score if applicable"
    )


class Provenance(BaseModel):
    """정보 출처의 전체 맥락."""

    trace_id: str = Field(..., description="Trace ID for this specific retrieval session")
    retrieval_mode: str = Field(
        ..., description="How the data was routed (e.g., hybrid, vector-only)"
    )
    items: list[EvidenceItem] = Field(
        default_factory=list, description="List of evidence items used"
    )
    insufficiency_hints: list[str] = Field(
        default_factory=list, description="Limitations of the current evidence"
    )
    kb_version: str | None = Field(None, description="The version/timestamp of the KB used")
    vector_filter_provenance: dict[str, Any] | None = Field(
        None,
        description="Vector search filter state: original/effective/unsupported filters and relaxation status",
    )


class AnswerBundle(BaseModel):
    """생성된 답변과 근거의 결합 패키지."""

    answer: str = Field(..., description="The final generated answer text")
    provenance: Provenance = Field(..., description="The evidence background for the answer")
    citations: list[str] = Field(
        default_factory=list, description="Simplified citation strings for UI display"
    )
    retrieved_docs: list[dict[str, Any]] = Field(default_factory=list)
    latency_ms: float = 0.0

    @property
    def route_reason(self) -> str:
        return self.provenance.retrieval_mode
