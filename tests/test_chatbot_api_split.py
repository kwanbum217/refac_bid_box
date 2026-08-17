"""
tests/test_chatbot_api_split.py

chatbot.py 기계적 분할(chatbot_format.py, chatbot_confirmation.py) 무결성 및 정합성 검증 테스트.
"""

from __future__ import annotations

import ast
from pathlib import Path

from fastapi.routing import APIRoute

import src.app.api.v1.chatbot as chatbot_mod
import src.app.api.v1.chatbot_confirmation as chatbot_confirmation_mod
import src.app.api.v1.chatbot_format as chatbot_format_mod
from src.app.schemas.chat import ChatPlan, PlanStep


def test_chatbot_line_counts():
    repo_root = Path(__file__).resolve().parent.parent
    chatbot_path = repo_root / "src/app/api/v1/chatbot.py"
    format_path = repo_root / "src/app/api/v1/chatbot_format.py"
    conf_path = repo_root / "src/app/api/v1/chatbot_confirmation.py"

    chatbot_lines = len(chatbot_path.read_text(encoding="utf-8").splitlines())
    format_lines = len(format_path.read_text(encoding="utf-8").splitlines())
    conf_lines = len(conf_path.read_text(encoding="utf-8").splitlines())

    assert chatbot_lines <= 550, f"chatbot.py exceeds 550 lines: {chatbot_lines}"
    assert format_lines <= 300, f"chatbot_format.py exceeds 300 lines: {format_lines}"
    assert conf_lines <= 300, f"chatbot_confirmation.py exceeds 300 lines: {conf_lines}"


def test_no_circular_imports_in_new_modules():
    repo_root = Path(__file__).resolve().parent.parent
    format_path = repo_root / "src/app/api/v1/chatbot_format.py"
    conf_path = repo_root / "src/app/api/v1/chatbot_confirmation.py"

    for path in (format_path, conf_path):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != "src.app.api.v1.chatbot", (
                        f"{path.name} must not import chatbot module"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != "src.app.api.v1.chatbot", (
                    f"{path.name} must not import from chatbot module"
                )
                assert not (module == "src.app.api.v1" and any(a.name == "chatbot" for a in node.names)), (
                    f"{path.name} must not import chatbot from src.app.api.v1"
                )


def test_symbol_reexport_identities():
    format_symbols = [
        "_append_kb_status",
        "_format_won",
        "_format_percent",
        "_markdown_cell",
        "_format_bid_number",
        "_format_model_summary",
        "_build_direct_tool_answer",
        "_build_advisory_bundle",
        "_build_answer_tool_context",
        "_plan_steps_payload",
    ]
    for name in format_symbols:
        assert hasattr(chatbot_format_mod, name), f"chatbot_format missing {name}"
        assert hasattr(chatbot_mod, name), f"chatbot missing re-export {name}"
        assert getattr(chatbot_mod, name) is getattr(chatbot_format_mod, name), (
            f"{name} in chatbot is not identical to chatbot_format.{name}"
        )

    conf_symbols = [
        "_is_text_confirmation_message",
        "_find_pending_confirmation_request",
        "_build_confirmed_automation_response",
        "_build_missing_confirmation_response",
        "_build_automation_status_payload",
    ]
    for name in conf_symbols:
        assert hasattr(chatbot_confirmation_mod, name), f"chatbot_confirmation missing {name}"
        assert hasattr(chatbot_mod, name), f"chatbot missing re-export {name}"
        assert getattr(chatbot_mod, name) is getattr(chatbot_confirmation_mod, name), (
            f"{name} in chatbot is not identical to chatbot_confirmation.{name}"
        )


def test_core_symbols_remain_in_chatbot():
    core_symbols = [
        "router",
        "chat_api",
        "chat_stream_api",
        "new_chat_session_api",
        "query_chatbot",
        "_PendingRagAnswer",
        "_prepare_chat",
        "_finalize_rag_answer",
        "_run_chat",
        "_sse",
        "_new_trace_id",
    ]
    for name in core_symbols:
        assert hasattr(chatbot_mod, name), f"chatbot.py missing core symbol {name}"


def test_router_routes_unchanged():
    router = chatbot_mod.router
    route_map = {}
    for route in router.routes:
        if isinstance(route, APIRoute):
            route_map[route.path] = route.methods

    expected_routes = {
        "/chatbot/chat": {"POST"},
        "/chatbot/chat/stream": {"POST"},
        "/chatbot/session/new": {"POST"},
        "/chatbot/query": {"POST"},
    }

    assert route_map == expected_routes, f"Route configuration mismatch: {route_map} != {expected_routes}"


def test_format_helpers():
    assert chatbot_format_mod._format_won(1234567) == "1,234,567원"
    assert chatbot_format_mod._format_won("invalid") == "-"
    assert chatbot_format_mod._format_percent(87.654) == "87.7%"
    assert chatbot_format_mod._format_percent("invalid") == "-"
    assert chatbot_format_mod._markdown_cell("a|b\nc", bold=True) == "**a\\|b c**"
    assert chatbot_format_mod._markdown_cell("code_val", code=True) == "`code_val`"
    assert chatbot_format_mod._format_bid_number({"bid_ntce_no": "20260101", "bid_ntce_ord": "00"}) == "20260101-00"

    plan = ChatPlan(
        mode="answer",
        intent_type="general",
        reason="test",
        steps=[PlanStep(step_id="s1", kind="pipeline", tool="test_tool")],
    )
    steps_payload = chatbot_format_mod._plan_steps_payload(plan)
    assert steps_payload == [{"step_id": "s1", "kind": "pipeline", "tool": "test_tool"}]


def test_confirmation_helpers():
    assert chatbot_confirmation_mod._is_text_confirmation_message("승인") is True
    assert chatbot_confirmation_mod._is_text_confirmation_message("승인 후 실행해줘") is True
    assert chatbot_confirmation_mod._is_text_confirmation_message("확인 후 진행해줘") is True
    assert chatbot_confirmation_mod._is_text_confirmation_message("ok") is True
    assert chatbot_confirmation_mod._is_text_confirmation_message("그냥 검색해줘") is False
    assert chatbot_confirmation_mod._is_text_confirmation_message("") is False
