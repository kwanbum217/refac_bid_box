"""
src/app/services/plan_executor.py

계획 실행기 (원본 apps/chatbot/services/automation_orchestrator.py 의
execute_internal_tool_step / execute_plan_steps 이식).

역량 레지스트리의 allowed_params 화이트리스트로 파라미터를 걸러 실행하며,
결과를 tool_results 에 output_key 로 축적하는 규약을 원본 그대로 유지합니다.
파이프라인 스텝은 Harness 대신 Arq 태스크 큐로 위임합니다.
"""

from __future__ import annotations

import importlib
import inspect
from typing import Any

from sqlalchemy.orm import Session

from src.app.schemas.chat import ChatPlan, PlanStep
from src.app.services.capability_registry import CapabilityDefinition, get_capability


class CapabilityError(RuntimeError):
    """알 수 없는 역량이나 잘못된 스텝 종류에 대한 오류."""


def resolve_capability(tool_name: str) -> CapabilityDefinition:
    capability = get_capability(tool_name)
    if not capability:
        raise CapabilityError(f"Unknown capability: {tool_name}")
    return capability


def plan_requires_confirmation(plan: ChatPlan) -> bool:
    return any(step.requires_confirmation for step in plan.steps)


def build_confirmation_from_plan(plan: ChatPlan) -> dict[str, Any]:
    return {
        "primary_action_key": plan.primary_action_key,
        "requires_confirmation": plan_requires_confirmation(plan),
        "steps": [step.model_dump() for step in plan.steps],
    }


def _import_executor(dotted_path: str):
    module_path, _, attribute = dotted_path.rpartition(".")
    module = importlib.import_module(module_path)
    return getattr(module, attribute)


def execute_internal_tool_step(
    step: PlanStep, context: dict[str, Any] | None = None, db: Session | None = None
) -> dict[str, Any]:
    context = context if context is not None else {}
    capability = resolve_capability(step.tool)
    executor = _import_executor(capability.executor)
    params = {
        key: value for key, value in (step.params or {}).items() if key in capability.allowed_params
    }
    signature = inspect.signature(executor)
    if "context" in signature.parameters:
        params["context"] = context
    if "db" in signature.parameters:
        params["db"] = db if db is not None else context.get("db")

    result = executor(**params)

    tool_results = dict(context.get("tool_results") or {})
    tool_results[step.output_key or step.tool] = result
    context["tool_results"] = tool_results
    context["last_result"] = result

    if step.tool == "kb_status_tool" and isinstance(result, dict):
        context["kb_status"] = result.get("kb_status")

    if isinstance(result, dict) and isinstance(result.get("visualizations"), list):
        existing_visualizations = list(context.get("visualizations") or [])
        for visualization in result["visualizations"]:
            if visualization not in existing_visualizations:
                existing_visualizations.append(visualization)
        context["visualizations"] = existing_visualizations

    executed_steps = list(context.get("executed_steps") or [])
    executed_steps.append({"step_id": step.step_id, "kind": step.kind, "tool": step.tool})
    context["executed_steps"] = executed_steps
    return result


def execute_pipeline_step(
    step: PlanStep, context: dict[str, Any] | None = None, db: Session | None = None
) -> dict[str, Any]:
    """파이프라인 스텝을 Arq 태스크 큐로 위임합니다 (원본 Harness 트리거 대체)."""
    context = context if context is not None else {}
    capability = resolve_capability(step.tool)
    if capability.type != "pipeline":
        raise CapabilityError(f"Capability is not a pipeline step: {step.tool}")

    from src.app.services.automation_orchestrator import enqueue_pipeline_run

    trigger_result = enqueue_pipeline_run(
        db=db if db is not None else context.get("db"),
        action_key=step.tool,
        run_mode=capability.run_mode,
        pipeline_name=capability.pipeline_id,
        original_query=str(context.get("original_query") or ""),
        automation_request_id=str(context.get("automation_request_id") or ""),
    )

    executed_steps = list(context.get("executed_steps") or [])
    executed_steps.append({"step_id": step.step_id, "kind": step.kind, "tool": step.tool})
    context["executed_steps"] = executed_steps
    context["last_pipeline_result"] = trigger_result
    return trigger_result


def execute_plan_steps(
    plan: ChatPlan, context: dict[str, Any] | None = None, db: Session | None = None
) -> dict[str, Any]:
    context = context if context is not None else {}
    for step in plan.steps:
        if step.kind == "internal_tool":
            execute_internal_tool_step(step, context, db=db)
        elif step.kind == "pipeline":
            execute_pipeline_step(step, context, db=db)
    return context
