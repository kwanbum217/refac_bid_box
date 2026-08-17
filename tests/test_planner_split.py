"""
tests/test_planner_split.py

planner.py 와 planner_interpreter.py 의 모듈 분리 정합성 및 재수출 규약 검증.
재수출 심볼(_load_last_plan, _load_last_tool_results, interpret_request) 누락 시 실패합니다.
"""

import ast
from pathlib import Path

import src.app.services.planner as planner_mod
import src.app.services.planner_interpreter as interpreter_mod
from src.app.schemas.chat import ChatExecutionPlan, ChatPlan
from src.app.services.planner import (
    _attempt_llm_plan_draft,
    _load_last_plan,
    _load_last_tool_results,
    _request_llm_plan_draft,
    compile_plan,
    interpret_request,
    plan_chat_request,
)


def test_reexported_symbols_identity():
    """planner.py 가 planner_interpreter.py 의 핵심 심볼을 동일 객체로 재수출하는지 검증."""
    assert _load_last_plan is interpreter_mod._load_last_plan
    assert _load_last_tool_results is interpreter_mod._load_last_tool_results
    assert interpret_request is interpreter_mod.interpret_request

    assert hasattr(planner_mod, "_load_last_plan")
    assert hasattr(planner_mod, "_load_last_tool_results")
    assert hasattr(planner_mod, "interpret_request")
    assert "_load_last_plan" in planner_mod.__all__
    assert "_load_last_tool_results" in planner_mod.__all__
    assert "interpret_request" in planner_mod.__all__


def test_llm_plan_draft_patch_target_remains_in_planner():
    """tests/test_chatbot_planner.py 의 patch 타겟이 planner 모듈에 유지되는지 검증."""
    assert hasattr(planner_mod, "_request_llm_plan_draft")
    assert hasattr(planner_mod, "_attempt_llm_plan_draft")
    assert callable(_request_llm_plan_draft)
    assert callable(_attempt_llm_plan_draft)


def test_unidirectional_dependency_no_reverse_import():
    """planner_interpreter.py 가 planner.py 를 역참조(import)하지 않는지 AST 로 검증."""
    interpreter_path = Path(interpreter_mod.__file__)
    tree = ast.parse(interpreter_path.read_text(encoding="utf-8"))

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name != "src.app.services.planner"
                assert not alias.name.endswith(".planner")
        elif isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            assert mod != "src.app.services.planner"
            assert not mod.endswith(".planner")


def test_file_line_limits():
    """분리된 두 모듈이 각각 600줄 미만인지 검증."""
    planner_lines = len(Path(planner_mod.__file__).read_text(encoding="utf-8").splitlines())
    interpreter_lines = len(
        Path(interpreter_mod.__file__).read_text(encoding="utf-8").splitlines()
    )

    assert planner_lines < 600, f"planner.py exceeds 600 lines: {planner_lines}"
    assert interpreter_lines < 600, f"planner_interpreter.py exceeds 600 lines: {interpreter_lines}"


def test_interpret_request_direct_vs_reexported():
    """interpret_request 가 직접 호출과 planner 재수출 호출 모두에서 동일하게 작동하는지 검증."""
    raw_query = "최근 서울 용역 통계 알려줘"
    context = {"last_query": "공고 통계", "last_filters_json": {"category": "Servc"}}

    direct_res = interpreter_mod.interpret_request(raw_query, context)
    reexported_res = interpret_request(raw_query, context)

    assert isinstance(direct_res, ChatExecutionPlan)
    assert isinstance(reexported_res, ChatExecutionPlan)
    assert direct_res.model_dump() == reexported_res.model_dump()

    # compile_plan 및 plan_chat_request 연계 검증
    plan = compile_plan(reexported_res)
    assert isinstance(plan, ChatPlan)
    assert plan.mode == "answer"

    end_to_end_plan = plan_chat_request(raw_query, context)
    assert end_to_end_plan.mode == plan.mode
    assert end_to_end_plan.intent_type == plan.intent_type
