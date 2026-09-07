"""Orca 워커 런처 공통 모듈(orca_worker_launch_common) 계약 검증."""

from __future__ import annotations

import io
from pathlib import Path

from scripts.orca_worker_launch_common import (
    COMMIT_NOTICE,
    PERMISSION_SETUP_FLAG,
    REVIEWER_NOTICE,
    acquire_permissions,
    append_role_notice,
    detect_role,
    is_terminal_ready,
    resolve_notice,
    run_permission_setup_child,
    schedule_permission_setup,
    spawn_permission_setup,
)


class _FakePrepare:
    """prepare_worker_terminal 대역."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

    def __call__(self, terminal, cli_type=None, model=None, launcher=None, **kwargs):
        self.calls.append(
            {
                "terminal": terminal,
                "cli_type": cli_type,
                "model": model,
                "launcher": launcher,
                "kwargs": kwargs,
            }
        )
        return self.results.pop(0) if self.results else {"ok": False, "detail": "후보 소진"}


def test_prepare_called_with_cli_type_model_and_launcher():
    """(1) prepare_worker_terminal 을 호출하며 cli_type, model, launcher 를 넘겨야 합니다."""
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    ok, _ = acquire_permissions(
        "term_1",
        "model_a",
        cli_type="antigravity",
        launcher="scripts/orca_agy_launch.py",
        delay_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 1
    call = prepare.calls[0]
    assert call["terminal"] == "term_1"
    assert call["cli_type"] == "antigravity"
    assert call["model"] == "model_a"
    assert call["launcher"] == "scripts/orca_agy_launch.py"


def test_prepare_never_forces_file_edit():
    """(2) force_file_edit 을 사용하지 않아야 합니다."""
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    acquire_permissions(
        "term_1",
        "model_a",
        cli_type="antigravity",
        delay_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert prepare.calls[0]["kwargs"].get("force_file_edit") in (None, False)


def test_retries_until_ready_when_not_ready():
    """(3) 준비되지 않으면 마감까지 재시도해야 합니다."""
    prepare = _FakePrepare(
        [
            {"ok": False},
            {"ok": False},
            {"ok": True, "file_edit_auto_approve": {"ok": True}},
        ]
    )

    ok, _ = acquire_permissions(
        "term_1",
        "model_a",
        cli_type="antigravity",
        delay_sec=0,
        deadline_sec=100.0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 3


def test_retries_when_top_level_ok_but_file_edit_not_ok_for_antigravity():
    """최상위 ok 가 True 더라도 file_edit_auto_approve.ok 가 False 면 성공으로 판단하지 않고 재시도해야 합니다."""
    prepare = _FakePrepare(
        [
            {
                "ok": True,
                "meta": {"cli_type": "antigravity"},
                "trust_prompt": {"ok": True},
                "auto_approve_watcher": {"ok": True},
                "file_edit_auto_approve": {"status": "skipped_or_failed", "ok": False},
            },
            {
                "ok": True,
                "meta": {"cli_type": "antigravity"},
                "trust_prompt": {"ok": True},
                "auto_approve_watcher": {"ok": True},
                "file_edit_auto_approve": {"status": "enabled", "ok": True},
            },
        ]
    )

    ok, detail = acquire_permissions(
        "term_1",
        "gemini-3.8-flash-medium",
        cli_type="antigravity",
        delay_sec=0,
        deadline_sec=100.0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 2
    assert "준비 완료" in detail


def test_reports_failure_after_deadline_exceeded():
    """(4) 마감 초과 시 성공으로 보고하지 않고 False 를 반환해야 합니다."""
    prepare = _FakePrepare([{"ok": False}] * 20)

    ok, detail = acquire_permissions(
        "term_1",
        "model_a",
        cli_type="antigravity",
        delay_sec=0,
        deadline_sec=0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is False
    assert "마치지 못했습니다" in detail


def test_spawn_permission_setup_detaches_child_session(tmp_path: Path, monkeypatch):
    """(5) 자식이 start_new_session=True 로 분리되어 실행되어야 합니다."""
    monkeypatch.chdir(tmp_path)
    spawned = []

    def fake_popen(cmd, **kwargs):
        spawned.append((cmd, kwargs))
        return object()

    spawn_permission_setup(
        "scripts/orca_agy_launch.py",
        "term_z",
        "gemini-3.8-flash-medium",
        popen=fake_popen,
    )

    assert len(spawned) == 1
    cmd, kwargs = spawned[0]
    assert PERMISSION_SETUP_FLAG in cmd
    assert "term_z" in cmd
    assert "gemini-3.8-flash-medium" in cmd
    assert kwargs.get("start_new_session") is True


def test_child_mode_returns_exit_code_2_on_empty_args():
    """(6) 핸들이나 모델이 비어 있으면 자식 모드가 종료 코드 2 를 반환해야 합니다."""
    err_stream = io.StringIO()
    assert (
        run_permission_setup_child([PERMISSION_SETUP_FLAG], cli_type="kimi", stderr=err_stream) == 2
    )
    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "term_x"], cli_type="kimi", stderr=err_stream
        )
        == 2
    )
    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "  ", "model_a"], cli_type="kimi", stderr=err_stream
        )
        == 2
    )
    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "term_x", "   "], cli_type="kimi", stderr=err_stream
        )
        == 2
    )


def test_child_mode_returns_0_on_success_and_1_on_failure():
    """자식 모드에서 acquire_permissions 결과에 따라 0 또는 1 을 반환합니다."""
    out_stream = io.StringIO()
    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "term_x", "model_a"],
            cli_type="kimi",
            acquire_fn=lambda *args, **kwargs: (True, "완료"),
            stdout=out_stream,
        )
        == 0
    )

    assert (
        run_permission_setup_child(
            [PERMISSION_SETUP_FLAG, "term_x", "model_a"],
            cli_type="kimi",
            acquire_fn=lambda *args, **kwargs: (False, "실패"),
            stdout=out_stream,
        )
        == 1
    )


def test_schedule_permission_setup_warns_when_handle_absent():
    """ORCA_TERMINAL_HANDLE 이 없으면 stderr 에 경고를 남기고 False 를 반환합니다."""
    err_stream = io.StringIO()
    out_stream = io.StringIO()
    spawned = []

    res = schedule_permission_setup(
        "scripts/orca_kimi_launch.py",
        "or-free/nemotron-ultra",
        terminal="",
        spawn_fn=lambda *args: spawned.append(args),
        stderr=err_stream,
        stdout=out_stream,
    )

    assert res is False
    assert len(spawned) == 0
    assert "ORCA_TERMINAL_HANDLE" in err_stream.getvalue()


def test_schedule_permission_setup_spawns_when_handle_present():
    """ORCA_TERMINAL_HANDLE 이 존재하면 자식을 띄우고 True 를 반환합니다."""
    out_stream = io.StringIO()
    spawned = []

    res = schedule_permission_setup(
        "scripts/orca_kimi_launch.py",
        "or-free/nemotron-ultra",
        terminal="term_k",
        spawn_fn=lambda *args: spawned.append(args),
        stdout=out_stream,
    )

    assert res is True
    assert len(spawned) == 1
    assert spawned[0][1] == "term_k"
    assert spawned[0][2] == "or-free/nemotron-ultra"


def test_is_terminal_ready_rules():
    """CLI 별 준비 완료 판정 규칙을 검증합니다."""
    # Antigravity: file_edit_auto_approve.ok 가 True 여야 함
    assert (
        is_terminal_ready(
            {"ok": True, "file_edit_auto_approve": {"ok": True}},
            cli_type="antigravity",
        )
        is True
    )
    assert (
        is_terminal_ready(
            {"ok": True, "file_edit_auto_approve": {"ok": False}},
            cli_type="antigravity",
        )
        is False
    )
    assert (
        is_terminal_ready(
            {"ok": True},
            cli_type="antigravity",
        )
        is False
    )

    # Kimi / Qwen: auto_approve_watcher.ok 가 True 이고 trust_prompt 가 still_present 가 아니면 준비 완료
    assert (
        is_terminal_ready(
            {
                "ok": True,
                "auto_approve_watcher": {"ok": True},
                "trust_prompt": {"status": "not_present", "ok": True},
                "file_edit_auto_approve": {"status": "skipped_or_failed", "ok": False},
            },
            cli_type="kimi",
        )
        is True
    )
    assert (
        is_terminal_ready(
            {
                "ok": False,
                "auto_approve_watcher": {"ok": False},
            },
            cli_type="kimi",
        )
        is False
    )


def test_detect_role_identifies_reviewer_indicators():
    """ORCA_REVIEW_DONE_V2 나 review_done.json 또는 role: reviewer 가 있으면 reviewer 로 판정합니다."""
    assert (
        detect_role("return_contract: ORCA_REVIEW_DONE_V2\nreport_path: review_done.json")
        == "reviewer"
    )
    assert detect_role("review_done.json 보고서를 작성하십시오.") == "reviewer"
    assert detect_role("role: reviewer") == "reviewer"
    assert detect_role('role: "reviewer"') == "reviewer"


def test_detect_role_identifies_builder():
    """ORCA_WORKER_DONE_V2 가 있거나 리뷰어 표지가 없으면 builder 로 판정합니다."""
    assert (
        detect_role("return_contract: ORCA_WORKER_DONE_V2\nreport_path: worker_done.json")
        == "builder"
    )


def test_detect_role_fails_closed_to_builder():
    """역할 표지가 없는 텍스트나 빈 문자열은 fail-closed 원칙에 따라 builder 로 판정합니다."""
    assert detect_role("일반 빌드 작업 지시문입니다.") == "builder"
    assert detect_role("") == "builder"
    assert detect_role("   \n\t") == "builder"


def test_reviewer_notice_contract_content():
    """리뷰어 고지문은 커밋 금지, git add 금지, review_done.json 커밋 금지, 보고서+전송 완료를 명시해야 합니다."""
    assert "커밋" in REVIEWER_NOTICE
    assert "git add" in REVIEWER_NOTICE
    assert "review_done.json" in REVIEWER_NOTICE
    assert "worker_done" in REVIEWER_NOTICE


def test_resolve_notice_with_auto():
    """role='auto' 일 때 지시문 분석 결과에 따라 올바른 고지문을 반환합니다."""
    assert resolve_notice("auto", "review_done.json 작성") == REVIEWER_NOTICE
    assert resolve_notice("auto", "worker_done.json 작성") == COMMIT_NOTICE
    assert resolve_notice("auto", "알 수 없는 작업") == COMMIT_NOTICE


def test_resolve_notice_role_override():
    """role='reviewer' 또는 role='builder' 로 명시적 강제 시 지시문 내용과 무관하게 지정된 고지문을 반환합니다."""
    # 빌더 지시문이지만 role='reviewer' 로 강제
    assert resolve_notice("reviewer", "ORCA_WORKER_DONE_V2") == REVIEWER_NOTICE
    # 리뷰어 지시문이지만 role='builder' 로 강제
    assert resolve_notice("builder", "ORCA_REVIEW_DONE_V2") == COMMIT_NOTICE


def test_append_role_notice_respects_no_commit_notice():
    """no_commit_notice=True 이면 역할이나 지시문과 무관하게 어떤 고지문도 붙이지 않습니다."""
    reviewer_prompt = "review_done.json 검토 지시"
    builder_prompt = "코드 수정 지시"

    assert (
        append_role_notice(reviewer_prompt, role="auto", no_commit_notice=True) == reviewer_prompt
    )
    assert append_role_notice(builder_prompt, role="auto", no_commit_notice=True) == builder_prompt
    assert (
        append_role_notice(reviewer_prompt, role="reviewer", no_commit_notice=True)
        == reviewer_prompt
    )
    assert (
        append_role_notice(builder_prompt, role="builder", no_commit_notice=True) == builder_prompt
    )


def test_append_role_notice_appends_correct_notice():
    """no_commit_notice=False 일 때 적절한 고지문이 prompt 뒤에 추가됩니다."""
    reviewer_prompt = "review_done.json 검토 지시"
    res_reviewer = append_role_notice(reviewer_prompt, role="auto", no_commit_notice=False)
    assert res_reviewer.startswith(reviewer_prompt)
    assert REVIEWER_NOTICE in res_reviewer
    assert COMMIT_NOTICE not in res_reviewer

    builder_prompt = "코드 수정 지시"
    res_builder = append_role_notice(builder_prompt, role="auto", no_commit_notice=False)
    assert res_builder.startswith(builder_prompt)
    assert COMMIT_NOTICE in res_builder
    assert REVIEWER_NOTICE not in res_builder
