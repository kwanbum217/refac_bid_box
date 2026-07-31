"""
src/app/schemas/chat.py

챗봇 계획/해석 스키마 (원본 apps/chatbot/schemas/plan_schema.py,
interpretation_schema.py, advisory_schema.py 1:1 이식).
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PlanStep(BaseModel):
    step_id: str
    kind: Literal["internal_tool", "pipeline", "respond", "advisory"]
    tool: str
    params: dict[str, Any] = Field(default_factory=dict)
    mutating: bool = False
    requires_confirmation: bool = False
    output_key: str = ""


class ChatPlan(BaseModel):
    mode: Literal["answer", "action", "advisory", "confirmation", "error"]
    intent_type: str
    response_mode: Literal["simple", "detailed", "visual"] = "simple"
    primary_action_key: str = ""
    requires_confirmation: bool = False
    followup_query: str = ""
    reason: str = ""
    suggestions: list[str] = Field(default_factory=list)
    poll_after_ms: int = 3000
    steps: list[PlanStep] = Field(default_factory=list)
    llm_draft_used: bool = False

    @property
    def intent(self) -> str:
        return self.intent_type

    @property
    def action_key(self) -> str:
        return self.primary_action_key

    @property
    def followup_after_completion(self) -> bool:
        return bool(self.followup_query)


class ChatExecutionPlan(BaseModel):
    """
    고도화된 질의 해석 계층을 위한 상위 해석 객체.
    사용자의 의도를 정규화된 형태(Intent/Policy)로 캡처하며,
    이후 단계에서 구체적인 PlanStep들로 컴파일된다.
    """

    query_type: Literal["answer", "action", "advisory", "hybrid", "unknown"]
    requested_capabilities: list[str] = Field(default_factory=list)
    requires_fresh_data: bool = False
    last_intent_type: str = ""
    response_mode: Literal["simple", "detailed", "visual"] = "simple"
    confidence: float = 1.0
    parameters: dict[str, Any] = Field(default_factory=dict)
    filters: dict[str, Any] = Field(default_factory=dict)
    action_key: str = ""
    last_action_key: str = ""
    job_id: str = ""
    last_query: str = ""
    last_response_mode: str = ""
    reasoning: str = ""
    is_followup: bool = False
    original_message: str = ""
    effective_query: str = ""


class AdvisorySignal(BaseModel):
    """
    고도화된 Proactive Advisory 신호 객체.
    우선순위, 심각도, 카테고리를 기반으로 정교한 노출 로직을 지원한다.
    """

    action_key: str
    message: str
    severity: Literal["critical", "warning", "info", "notice"] = "info"
    priority: Literal["urgent", "high", "medium", "low"] = "medium"
    category: Literal[
        "knowledge_base", "automation", "prediction", "ingestion", "preflight", "general"
    ] = "general"
    reason_code: str
    metadata: dict[str, Any] = Field(default_factory=dict)
    weight_override: float = 1.0

    def get_score(self, category_weights: dict[str, float] | None = None) -> float:
        severity_map = {"critical": 40.0, "warning": 30.0, "info": 20.0, "notice": 10.0}
        priority_map = {"urgent": 40.0, "high": 30.0, "medium": 20.0, "low": 10.0}

        base_score = severity_map.get(self.severity, 0.0) + priority_map.get(self.priority, 0.0)
        category_weight = (category_weights or {}).get(self.category, 1.0)

        return base_score * category_weight * self.weight_override
