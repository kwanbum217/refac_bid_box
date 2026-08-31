"""Antigravity 런처의 대기/기동 계약을 검증합니다."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from scripts.orca_agy_launch import (
    COMMIT_NOTICE,
    PERMISSION_SETUP_FLAG,
    acquire_permissions,
    build_command,
    main,
    spawn_permission_setup,
    wait_for_preamble,
)


def test_wait_returns_content_once_written(tmp_path: Path):
    target = tmp_path / "preamble.txt"

    def writer():
        time.sleep(0.2)
        target.write_text("지시문 본문", encoding="utf-8")

    threading.Thread(target=writer, daemon=True).start()
    assert wait_for_preamble(target, timeout_sec=5.0, poll_sec=0.05) == "지시문 본문"


def test_empty_file_is_not_accepted(tmp_path: Path):
    """비어 있는 파일을 지시문으로 읽으면 워커가 빈 지시로 기동합니다."""
    target = tmp_path / "preamble.txt"
    target.write_text("   \n", encoding="utf-8")

    with pytest.raises(TimeoutError):
        wait_for_preamble(target, timeout_sec=0.3, poll_sec=0.05)


def test_missing_file_times_out(tmp_path: Path):
    with pytest.raises(TimeoutError):
        wait_for_preamble(tmp_path / "absent.txt", timeout_sec=0.3, poll_sec=0.05)


def test_build_command_passes_prompt_as_agy_argument():
    """-i 인자 경로여야 합니다. 스플래시 멈춤을 피하려면 지시문을 인자로 줘야 합니다."""
    cmd = build_command("gemini-3.7-flash-medium", "본문")
    assert cmd == ["agy", "--model", "gemini-3.7-flash-medium", "-i", "본문"]


def test_build_command_supports_different_model_ids():
    """추론 수준이 모델 ID 에 포함되므로 어떤 ID 든 그대로 전달돼야 합니다."""
    high = build_command("claude-sonnet-4-6", "지시")
    assert high == ["agy", "--model", "claude-sonnet-4-6", "-i", "지시"]


def test_commit_notice_mentions_commit_requirement():
    assert "커밋" in COMMIT_NOTICE
    assert "git add -A" in COMMIT_NOTICE


def test_commit_notice_is_appended_when_enabled(tmp_path: Path, monkeypatch, capsys):
    """기본값에서는 preamble 뒤에 커밋 고지문이 붙어야 합니다."""
    from scripts import orca_agy_launch as mod

    target = tmp_path / "preamble.txt"
    target.write_text("원래 지시문", encoding="utf-8")

    captured: dict = {}

    def fake_execvpe(cmd0, cmd, env):
        captured["cmd0"] = cmd0
        captured["cmd"] = list(cmd)
        captured["env"] = env
        # execvpe 가 성공했다고 가정하고 호출자 main 으로 돌아가게 하려면
        # 예외를 던지지 않고 호출자가 return 0 줄에 도달하지 못하게 막아야 합니다.
        # main 은 execvpe 이후 어떤 일도 하지 않으므로 그냥 raise 로 끊습니다.
        raise SystemExit(0)

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.7-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
            ]
        )
    assert exc.value.code == 0
    prompt = captured["cmd"][-1]
    assert prompt.startswith("원래 지시문")
    assert COMMIT_NOTICE.strip() in prompt


def test_commit_notice_omitted_when_disabled(tmp_path: Path, monkeypatch):
    target = tmp_path / "preamble.txt"
    target.write_text("원래 지시문", encoding="utf-8")

    captured: dict = {}

    def fake_execvpe(cmd0, cmd, env):
        captured["cmd"] = list(cmd)
        raise SystemExit(0)

    from scripts import orca_agy_launch as mod

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)
    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.7-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
                "--no-commit-notice",
            ]
        )
    assert exc.value.code == 0
    prompt = captured["cmd"][-1]
    assert prompt == "원래 지시문"
    assert COMMIT_NOTICE.strip() not in prompt


def test_main_returns_nonzero_when_preamble_times_out(tmp_path: Path, capsys):
    target = tmp_path / "preamble.txt"
    # 파일을 만들지 않음 → 시간 초과
    from scripts import orca_agy_launch as mod

    code = mod.main(
        [
            "--model",
            "gemini-3.7-flash-medium",
            "--preamble",
            str(target),
            "--timeout-sec",
            "0.2",
        ]
    )
    assert code != 0
    err = capsys.readouterr().err
    assert "preamble" in err


class _FakePrepare:
    """prepare_worker_terminal 대역.

    실제 함수는 orca terminal 을 호출하므로 테스트에서 쓸 수 없습니다.
    """

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


def test_acquire_permissions_records_cli_metadata():
    """cli_type 을 넘기지 않으면 CLI 판정이 fail-closed 로 막혀 모드를 못 잡습니다.

    2026-08-31 에 감시기 헬퍼만 직접 불러 메타데이터가 비었고, 워커가 파일 편집
    대화창에 그대로 갇혔습니다.
    """
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    ok, _ = acquire_permissions(
        "term_x", "gemini-3.7-flash-high", delay_sec=0, sleep=lambda _: None, prepare=prepare
    )

    assert ok is True
    assert len(prepare.calls) == 1
    call = prepare.calls[0]
    assert call["cli_type"] == "antigravity"
    assert call["model"] == "gemini-3.7-flash-high"
    assert call["launcher"], "런처 경로를 기록하지 않았습니다"


def test_acquire_permissions_never_forces_mode_transition():
    """force_file_edit 은 스피너 화면에서도 키를 보내 plan 으로 밀어 넣습니다."""
    prepare = _FakePrepare([{"ok": True, "file_edit_auto_approve": {"ok": True}}])

    acquire_permissions(
        "term_x", "gemini-3.7-flash-high", delay_sec=0, sleep=lambda _: None, prepare=prepare
    )

    assert prepare.calls[0]["kwargs"].get("force_file_edit") in (None, False)


def test_acquire_permissions_retries_while_not_ready():
    """생성 중에는 모드가 unknown 이라 준비가 실패합니다. 포기하면 안 됩니다."""
    prepare = _FakePrepare(
        [{"ok": False}, {"ok": False}, {"ok": True, "file_edit_auto_approve": {"ok": True}}]
    )

    ok, _ = acquire_permissions(
        "term_x",
        "gemini-3.7-flash-high",
        delay_sec=0,
        deadline_sec=100.0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 3


def test_acquire_permissions_retries_when_top_level_ok_but_file_edit_fails():
    """최상위 ok 가 True 더라도 file_edit_auto_approve.ok 가 False 면 성공으로 처리하지 않고 재시도해야 합니다."""
    prepare = _FakePrepare(
        [
            {
                "ok": True,
                "auto_approve_watcher": {"ok": True},
                "file_edit_auto_approve": {"status": "skipped_or_failed", "ok": False},
            },
            {
                "ok": True,
                "auto_approve_watcher": {"ok": True},
                "file_edit_auto_approve": {"status": "enabled", "ok": True},
            },
        ]
    )

    ok, _ = acquire_permissions(
        "term_x",
        "gemini-3.7-flash-high",
        delay_sec=0,
        deadline_sec=100.0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is True
    assert len(prepare.calls) == 2


def test_acquire_permissions_reports_failure_after_deadline():
    """확보하지 못했는데 성공으로 보고하면 승인 중단이 조용히 남습니다."""
    prepare = _FakePrepare([{"ok": False}] * 50)

    ok, detail = acquire_permissions(
        "term_x",
        "gemini-3.7-flash-high",
        delay_sec=0,
        deadline_sec=0,
        interval_sec=0,
        sleep=lambda _: None,
        prepare=prepare,
    )

    assert ok is False
    assert "마치지 못했습니다" in detail


def test_launcher_schedules_permission_setup(tmp_path: Path, monkeypatch):
    """런처가 exec 전에 준비 자식을 띄우지 않으면 4단계가 통째로 빠집니다."""
    monkeypatch.chdir(tmp_path)
    spawned = []

    def fake_popen(cmd, **kwargs):
        spawned.append((cmd, kwargs))
        return object()

    spawn_permission_setup("term_y", "gemini-3.7-flash-high", popen=fake_popen)

    assert len(spawned) == 1
    cmd, kwargs = spawned[0]
    assert PERMISSION_SETUP_FLAG in cmd
    assert "term_y" in cmd
    assert "gemini-3.7-flash-high" in cmd, "자식이 모델을 몰라 메타데이터를 못 남깁니다"
    assert kwargs["start_new_session"] is True, "부모가 exec 되면 자식이 같이 죽습니다"


def test_permission_setup_child_requires_handle_and_model():
    """핸들이나 모델 없이 자식 모드를 부르면 조용히 통과시키면 안 됩니다."""
    assert main([PERMISSION_SETUP_FLAG]) == 2
    assert main([PERMISSION_SETUP_FLAG, "term_y"]) == 2
    assert main([PERMISSION_SETUP_FLAG, "   ", "model"]) == 2
    assert main([PERMISSION_SETUP_FLAG, "term_y", "  "]) == 2


def test_main_warns_when_terminal_handle_missing(tmp_path: Path, monkeypatch, capsys):
    target = tmp_path / "preamble.txt"
    target.write_text("지시문", encoding="utf-8")
    from scripts import orca_agy_launch as mod

    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)

    def fake_execvpe(cmd0, cmd, env):
        raise SystemExit(0)

    monkeypatch.setattr(mod.os, "execvpe", fake_execvpe)

    with pytest.raises(SystemExit) as exc:
        mod.main(
            [
                "--model",
                "gemini-3.7-flash-medium",
                "--preamble",
                str(target),
                "--timeout-sec",
                "1.0",
            ]
        )
    assert exc.value.code == 0
    err = capsys.readouterr().err
    assert "ORCA_TERMINAL_HANDLE" in err
