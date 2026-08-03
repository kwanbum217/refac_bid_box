"""
src/app/services/capability_registry.py

역량 레지스트리 (원본 apps/chatbot/registries/capability_registry.py 1:1 이식).
executor 경로만 리팩토링 스택 모듈 경로로 치환했습니다.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.app.services.action_catalog import ACTION_CATALOG


@dataclass(frozen=True)
class CapabilityDefinition:
    name: str
    type: str
    mutating: bool
    requires_confirmation: bool
    allowed_params: tuple[str, ...]
    executor: str
    pipeline_id: str = ""
    run_mode: str = ""


def _build_pipeline_capabilities() -> dict[str, CapabilityDefinition]:
    capabilities: dict[str, CapabilityDefinition] = {}
    for action in ACTION_CATALOG.values():
        capabilities[action.action_key] = CapabilityDefinition(
            name=action.action_key,
            type="pipeline",
            mutating=action.mutating,
            requires_confirmation=action.high_cost,
            allowed_params=(),
            executor="src.app.services.automation_orchestrator.execute_pipeline_step",
            pipeline_id=action.pipeline_id,
            run_mode=action.run_mode,
        )
    return capabilities


CAPABILITY_REGISTRY: dict[str, CapabilityDefinition] = {
    **_build_pipeline_capabilities(),
    "kb_status_tool": CapabilityDefinition(
        name="kb_status_tool",
        type="internal_tool",
        mutating=False,
        requires_confirmation=False,
        allowed_params=(),
        executor="src.app.services.tools.kb_status_tool.execute",
    ),
    "automation_status_tool": CapabilityDefinition(
        name="automation_status_tool",
        type="internal_tool",
        mutating=False,
        requires_confirmation=False,
        allowed_params=("job_id", "prefer_visualization"),
        executor="src.app.services.tools.automation_status_tool.execute",
    ),
    "bid_query_tool": CapabilityDefinition(
        name="bid_query_tool",
        type="internal_tool",
        mutating=False,
        requires_confirmation=False,
        allowed_params=(
            "query",
            "institution_name",
            "category",
            "years",
            "date_from",
            "date_to",
            "limit",
        ),
        executor="src.app.services.tools.bid_query_tool.execute",
    ),
    "bid_prediction_tool": CapabilityDefinition(
        name="bid_prediction_tool",
        type="internal_tool",
        mutating=False,
        requires_confirmation=False,
        allowed_params=("query", "category", "model_id", "limit"),
        executor="src.app.services.tools.bid_prediction_tool.execute",
    ),
    "semantic_search_tool": CapabilityDefinition(
        name="semantic_search_tool",
        type="internal_tool",
        mutating=False,
        requires_confirmation=False,
        allowed_params=("query", "top_k"),
        executor="src.app.services.tools.semantic_search_tool.execute",
    ),
    "trend_analyzer": CapabilityDefinition(
        name="trend_analyzer",
        type="internal_tool",
        mutating=False,
        requires_confirmation=False,
        allowed_params=("source_key", "metric", "series_key", "top_n"),
        executor="src.app.services.tools.trend_analyzer.execute",
    ),
    "chart_builder": CapabilityDefinition(
        name="chart_builder",
        type="internal_tool",
        mutating=False,
        requires_confirmation=False,
        allowed_params=("source_key", "chart_type", "title", "max_points"),
        executor="src.app.services.tools.chart_builder.execute",
    ),
}


def get_capability(name: str) -> CapabilityDefinition | None:
    return CAPABILITY_REGISTRY.get(name)


def list_capabilities() -> list[CapabilityDefinition]:
    return list(CAPABILITY_REGISTRY.values())
