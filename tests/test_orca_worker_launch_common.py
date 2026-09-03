"""Orca 워커 런처 공통 모듈(orca_worker_launch_common) 계약 검증."""

from __future__ import annotations

import io
from pathlib import Path

from scripts.orca_worker_launch_common import (
    PERMISSION_SETUP_FLAG,
    acquire_permissions,
    is_terminal_ready,
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
