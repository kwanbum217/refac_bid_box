"""
tests/test_automation_orchestrator_split.py

automation_orchestrator 모듈 기계적 분할 및 토큰 호환성 회귀 테스트.
"""

import ast
from pathlib import Path

import pytest

from src.app.services import (
    automation_callbacks,
    automation_jobs,
    automation_orchestrator,
    automation_responses,
    automation_tokens,
)


def test_token_signing_and_unsigning_compatibility():
    """_sign과 _unsign 동작 및 automation_tokens <-> automation_orchestrator 호환성 검증."""
    job_id = "test-job-uuid-12345"

    # confirmation token 생성 및 검증
    token = automation_tokens.make_confirmation_token(job_id)
    assert automation_orchestrator.resolve_confirmation_token(token) == job_id
    assert automation_tokens.resolve_confirmation_token(token) == job_id

    # orchestrator에서 생성하고 tokens에서 검증
    token2 = automation_orchestrator.make_confirmation_token(job_id)
    assert automation_tokens.resolve_confirmation_token(token2) == job_id

    # callback token 생성 및 검증
    cb_token = automation_tokens.make_callback_token(job_id)
    assert automation_orchestrator.verify_callback_token(job_id, cb_token) is True
    assert automation_tokens.verify_callback_token(job_id, cb_token) is True
    assert automation_tokens.verify_callback_token("other-id", cb_token) is False
    assert automation_tokens.verify_callback_token(job_id, "") is False


def test_token_tampering_and_expiration():
    """위조 및 변조 토큰에 대한 예외 발생 검증."""
    job_id = "tamper-test-id"
    token = automation_tokens.make_confirmation_token(job_id)

    # 서명 위조
    tampered = token[:-4] + "xxxx"
    with pytest.raises(automation_tokens.AutomationError, match="서명이 일치하지 않습니다"):
        automation_tokens.resolve_confirmation_token(tampered)

    # 형식 오류
    with pytest.raises(automation_tokens.AutomationError, match="서명 형식이 올바르지 않습니다"):
        automation_tokens.resolve_confirmation_token("invalid_token_without_colons")

    # 만료 토큰
    with pytest.raises(automation_tokens.AutomationError, match="토큰이 만료되었습니다"):
        automation_tokens.resolve_confirmation_token(token, max_age=-1)


def test_reexported_symbols_presence():
    """automation_orchestrator 가 이동된 모든 심볼을 누락 없이 재익스포트하는지 검증."""
    expected_symbols = [
        "CALLBACK_PATH_TEMPLATE",
        "CALLBACK_SALT",
        "CONFIRMATION_MAX_AGE",
        "CONFIRMATION_SALT",
        "REUSABLE_ACTIONS",
        "REUSE_MAX_AGE_HOURS",
        "RUN_MODE_TASKS",
        "STATUS_CANCELED",
        "STATUS_FAILED",
        "STATUS_PENDING_CONFIRMATION",
        "STATUS_QUEUED",
        "STATUS_RUNNING",
        "STATUS_SUCCESS",
        "TERMINAL_STATUSES",
        "AutomationError",
        "AutomationResponse",
        "CallbackDelivery",
        "_attach_reused_execution",
        "_build_canceled_answer",
        "_build_confirmation_answer",
        "_build_failure_answer",
        "_build_in_progress_answer",
        "_callback_metadata",
        "_callback_status_lines",
        "_enqueue_arq_job",
        "_find_reusable_execution",
        "_get_pipeline_execution",
        "_get_pipeline_step",
        "_is_worker_unreachable_host",
        "_job_payload",
        "_load_plan_from_request_payload",
        "_run_arq_coroutine",
        "_sign",
        "_step_status_lines",
        "_try_reuse_recent_execution",
        "_unsign",
        "abort_arq_job",
        "apply_callback_payload",
        "build_action_response",
        "build_confirmation_from_plan",
        "cancel_automation_request",
        "confirm_automation_request",
        "create_action_request",
        "create_automation_request",
        "enqueue_pipeline_run",
        "get_automation_request",
        "make_callback_token",
        "make_confirmation_token",
        "plan_requires_confirmation",
        "resolve_callback_delivery",
        "resolve_confirmation_token",
        "start_automation_request",
        "sync_automation_status",
        "verify_callback_token",
    ]
    for sym in expected_symbols:
        assert hasattr(automation_orchestrator, sym), (
            f"심볼 {sym} 이 automation_orchestrator 에 없음"
        )


def test_no_circular_imports_in_submodules():
    """신규 4개 분할 모듈이 automation_orchestrator 를 import 하지 않는지 AST 레벨 검증."""
    submodules = [
        "src/app/services/automation_tokens.py",
        "src/app/services/automation_callbacks.py",
        "src/app/services/automation_responses.py",
        "src/app/services/automation_jobs.py",
    ]
    for subpath in submodules:
        content = Path(subpath).read_text(encoding="utf-8")
        tree = ast.parse(content, filename=subpath)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert "automation_orchestrator" not in alias.name, (
                        f"{subpath} 가 automation_orchestrator 를 import 함"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert "automation_orchestrator" not in node.module, (
                        f"{subpath} 가 automation_orchestrator 를 importFrom 함"
                    )


def test_module_line_count_limits():
    """분할 후 원본 모듈 600줄 이하 및 신규 4개 모듈 각각 400줄 이하 제약 검증."""
    services_dir = Path("src/app/services")
    orchestrator_lines = len(
        (services_dir / "automation_orchestrator.py").read_text(encoding="utf-8").splitlines()
    )
    assert orchestrator_lines <= 600, (
        f"automation_orchestrator.py 줄 수 초과: {orchestrator_lines} > 600"
    )

    submodules = [
        "automation_tokens.py",
        "automation_callbacks.py",
        "automation_responses.py",
        "automation_jobs.py",
    ]
    for name in submodules:
        lines = len((services_dir / name).read_text(encoding="utf-8").splitlines())
        assert lines <= 400, f"{name} 줄 수 초과: {lines} > 400"
