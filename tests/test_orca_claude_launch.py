"""Claude Code 런처의 대기·실행·창 유지 계약을 검증합니다."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import orca_claude_launch
from scripts.orca_claude_launch import (
    COMMIT_NOTICE,
    PERMISSION_SETUP_FLAG,
    REVIEWER_NOTICE,
    build_command,
    build_completion_message,
    main,
    open_interactive_shell,
    resolve_shell,
    run_claude,
    wait_for_preamble,
)


@pytest.fixture(autouse=True)
def _guard_claude_permission_setup(monkeypatch):
    """Claude 런처 테스트가 실제 분리 프로세스를 띄우지 않도록 안전망을 제공합니다."""
    import subprocess

    orig_spawn = orca_claude_launch.spawn_permission_setup
    _SENTINEL = object()

    def safe_spawn(
        launcher_script: str | Path, terminal: str, model: str, *, popen=_SENTINEL
    ) -> None:
        if popen is _SENTINEL or popen is subprocess.Popen:
            return None
        return orig_spawn(launcher_script, terminal, model, popen=popen)

    monkeypatch.setattr(orca_claude_launch, "spawn_permission_setup", safe_spawn)


def test_wait_returns_content_once_written(tmp_path: Path):
    """고유 preamble_*.txt 파일이 작성되면 내용을 읽고 파일을 즉시 삭제해야 합니다."""
    target = tmp_path / "preamble_cwait.txt"

    def writer():
        time.sleep(0.2)
        target.write_text("지시문 본문", encoding="utf-8")

    threading.Thread(target=writer, daemon=True).start()
    assert wait_for_preamble(target, timeout_sec=5.0, poll_sec=0.05) == "지시문 본문"
    assert not target.exists(), "고유 preamble_*.txt 파일은 소비 후 즉시 삭제되어야 합니다"


def test_empty_file_is_not_accepted(tmp_path: Path):
    """비어 있는 파일을 지시문으로 읽으면 워커가 빈 지시로 기동하므로 타임아웃까지 대기해야 합니다."""
    target = tmp_path / "preamble.txt"
    target.write_text("   \n", encoding="utf-8")

    with pytest.raises(TimeoutError):
        wait_for_preamble(target, timeout_sec=0.3, poll_sec=0.05)


def test_missing_file_times_out(tmp_path: Path):
    """존재하지 않는 파일은 타임아웃되어야 합니다."""
    with pytest.raises(TimeoutError):
        wait_for_preamble(tmp_path / "absent.txt", timeout_sec=0.3, poll_sec=0.05)


@patch("scripts.orca_claude_launch.run_claude", return_value=0)
@patch("scripts.orca_claude_launch.open_interactive_shell")
def test_claude_main_consumes_and_deletes_unique_preamble(
    mock_shell: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
):
    """Claude main 실행 시 고유 preamble_*.txt 파일을 읽고 소비 후 삭제해야 합니다."""
    target = tmp_path / "preamble_run_unique_claude.txt"
    target.write_text("클로드 고유 지시문", encoding="utf-8")

    code = main(
        [
            "--model",
            "claude-3-7-sonnet-20250219",
            "--preamble",
            str(target),
            "--no-commit-notice",
            "--one-shot",
            "--no-keep-open",
        ]
    )
    assert code == 0
    assert not target.exists(), "런처 기동 후 preamble 파일이 삭제되어야 합니다"
    prompt = mock_run.call_args[0][0][-1]
    assert prompt == "클로드 고유 지시문"


@patch("scripts.orca_claude_launch.run_claude", return_value=0)
@patch("scripts.orca_claude_launch.open_interactive_shell")
def test_claude_main_passes_permission_mode(
    mock_shell: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
):
    """Claude main 실행 시 --permission-mode 인자가 올바르게 명령 배열에 전달되어야 합니다."""
    target = tmp_path / "preamble_mode_claude.txt"
    target.write_text("지시문", encoding="utf-8")

    code = main(
        [
            "--model",
            "claude-3-7-sonnet-20250219",
            "--preamble",
            str(target),
            "--permission-mode",
            "acceptEdits",
            "--no-commit-notice",
            "--one-shot",
            "--no-keep-open",
        ]
    )
    assert code == 0
    cmd = mock_run.call_args[0][0]
    assert "--permission-mode" in cmd
    idx = cmd.index("--permission-mode")
    assert cmd[idx + 1] == "acceptEdits"
    assert "--dangerously-skip-permissions" not in cmd


def test_claude_main_rejects_invalid_permission_mode():
    """Claude main 실행 시 --permission-mode 에 bypassPermissions 등 허용되지 않은 값을 넘기면 argparse 가 SystemExit 2 로 거부해야 합니다."""
    with pytest.raises(SystemExit) as exc_info:
        main(
            [
                "--model",
                "claude-3-7-sonnet-20250219",
                "--permission-mode",
                "bypassPermissions",
            ]
        )
    assert exc_info.value.code == 2


def test_build_command_interactive_and_one_shot():
    """대화형은 claude [prompt] 위치 인자, 단발은 -p 플래그를 사용해야 합니다."""
    interactive_cmd = build_command("claude-3-7-sonnet-20250219", "지시문", one_shot=False)
    assert interactive_cmd == ["claude", "--model", "claude-3-7-sonnet-20250219", "지시문"]

    one_shot_cmd = build_command("claude-3-7-sonnet-20250219", "지시문", one_shot=True)
    assert one_shot_cmd == ["claude", "--model", "claude-3-7-sonnet-20250219", "-p", "지시문"]


def test_build_command_permission_mode():
    """권한 모드 인자는 명시적으로 지정될 때만 포함되며 acceptEdits 가 순서대로 전달되어야 합니다."""
    # 1. 기본 기동 명령에 --permission-mode 가 없다
    cmd_default = build_command("claude-3-7-sonnet-20250219", "지시문")
    assert "--permission-mode" not in cmd_default
    # 3. --dangerously-skip-permissions 문자열이 조립 명령에 어떤 경우에도 나타나지 않는다
    assert "--dangerously-skip-permissions" not in cmd_default

    # 2. 인자를 켜면 --permission-mode 와 acceptEdits 가 순서대로 들어간다
    cmd_flag = build_command("claude-3-7-sonnet-20250219", "지시문", permission_mode="acceptEdits")
    assert "--permission-mode" in cmd_flag
    assert cmd_flag == [
        "claude",
        "--model",
        "claude-3-7-sonnet-20250219",
        "--permission-mode",
        "acceptEdits",
        "지시문",
    ]
    idx = cmd_flag.index("--permission-mode")
    assert cmd_flag[idx + 1] == "acceptEdits"
    # 3. --dangerously-skip-permissions 문자열이 조립 명령에 어떤 경우에도 나타나지 않는다
    assert "--dangerously-skip-permissions" not in cmd_flag


def test_commit_notice_mentions_commit_requirement():
    assert "커밋" in COMMIT_NOTICE
    assert "git add -A" in COMMIT_NOTICE


def test_build_completion_message_includes_exit_code():
    message = build_completion_message(0, "claude-3-7-sonnet-20250219")
    assert "종료 코드: 0" in message


def test_resolve_shell_uses_shell_env():
    assert resolve_shell({"SHELL": "/bin/zsh"}) == "/bin/zsh"
    assert resolve_shell({}) == "/bin/bash"


@patch("scripts.orca_claude_launch.subprocess.run")
def test_run_claude_uses_subprocess(mock_run: MagicMock):
    mock_run.return_value = MagicMock(returncode=0)
    code = run_claude(["claude", "--model", "m", "-p", "p"], {"PATH": "/usr/bin"})
    assert code == 0
    mock_run.assert_called_once_with(
        ["claude", "--model", "m", "-p", "p"], env={"PATH": "/usr/bin"}
    )


@patch("scripts.orca_claude_launch.os.execvpe")
def test_open_interactive_shell_uses_resolved_shell(mock_exec: MagicMock):
    open_interactive_shell({"SHELL": "/bin/fish"})
    mock_exec.assert_called_once_with("/bin/fish", ["/bin/fish"], {"SHELL": "/bin/fish"})


@patch("scripts.orca_claude_launch.open_interactive_shell")
@patch("scripts.orca_claude_launch.run_claude", return_value=0)
def test_one_shot_keeps_terminal_open_with_shell(
    mock_run: MagicMock,
    mock_shell: MagicMock,
    tmp_path: Path,
):
    """단발 모드는 실행 완료 후 대화형 셸로 이어받아 터미널 창을 유지해야 합니다."""
    target = tmp_path / "preamble_keep.txt"
    target.write_text("지시문", encoding="utf-8")
    code = main(
        [
            "--model",
            "claude-3-7-sonnet-20250219",
            "--preamble",
            str(target),
            "--one-shot",
            "--no-commit-notice",
        ]
    )
    assert code == 0
    mock_run.assert_called_once()
    mock_shell.assert_called_once()


def test_commit_notice_default_and_role_overrides(tmp_path: Path):
    """--role 과 --no-commit-notice 가 고지문 부착 판정을 올바르게 제어해야 합니다."""
    target = tmp_path / "preamble_role.txt"

    # 1. 기본값: 커밋 고지문 부착
    target.write_text("일반 빌드 작업", encoding="utf-8")
    with patch("scripts.orca_claude_launch.run_claude", return_value=0) as mock_run:
        main(["--model", "m", "--preamble", str(target), "--one-shot", "--no-keep-open"])
    assert COMMIT_NOTICE in mock_run.call_args[0][0][-1]

    # 2. --no-commit-notice 지정: 고지문 미부착
    target.write_text("일반 빌드 작업", encoding="utf-8")
    with patch("scripts.orca_claude_launch.run_claude", return_value=0) as mock_run:
        main(
            [
                "--model",
                "m",
                "--preamble",
                str(target),
                "--one-shot",
                "--no-commit-notice",
                "--no-keep-open",
            ]
        )
    assert COMMIT_NOTICE not in mock_run.call_args[0][0][-1]
    assert mock_run.call_args[0][0][-1] == "일반 빌드 작업"

    # 3. 리뷰어 본문이지만 --role builder 강제 지정
    target.write_text("계약: ORCA_REVIEW_DONE_V2\n산출물: review_done.json", encoding="utf-8")
    with patch("scripts.orca_claude_launch.run_claude", return_value=0) as mock_run:
        main(
            [
                "--model",
                "m",
                "--preamble",
                str(target),
                "--one-shot",
                "--role",
                "builder",
                "--no-keep-open",
            ]
        )
    assert COMMIT_NOTICE in mock_run.call_args[0][0][-1]
    assert REVIEWER_NOTICE not in mock_run.call_args[0][0][-1]

    # 4. 빌더 본문이지만 --role reviewer 강제 지정
    target.write_text("일반 빌드 작업", encoding="utf-8")
    with patch("scripts.orca_claude_launch.run_claude", return_value=0) as mock_run:
        main(
            [
                "--model",
                "m",
                "--preamble",
                str(target),
                "--one-shot",
                "--role",
                "reviewer",
                "--no-keep-open",
            ]
        )
    assert REVIEWER_NOTICE in mock_run.call_args[0][0][-1]
    assert COMMIT_NOTICE not in mock_run.call_args[0][0][-1]


def test_permission_setup_child_in_claude_launcher():
    """Claude 런처의 자식 모드 인자 검증 및 실행을 확인합니다."""
    assert main([PERMISSION_SETUP_FLAG]) == 2
    assert main([PERMISSION_SETUP_FLAG, "term_c"]) == 2
    assert main([PERMISSION_SETUP_FLAG, "  ", "model_c"]) == 2

    with patch(
        "scripts.orca_worker_launch_common.run_permission_setup_child", return_value=0
    ) as mock_child:
        code = main([PERMISSION_SETUP_FLAG, "term_c", "claude-3-7-sonnet-20250219"])
        assert code == 0
        mock_child.assert_called_once()
        args, kwargs = mock_child.call_args
        assert args[0] == [PERMISSION_SETUP_FLAG, "term_c", "claude-3-7-sonnet-20250219"]
        assert kwargs.get("cli_type") == "claude"


def test_main_never_calls_popen_for_permission_setup(tmp_path: Path, monkeypatch):
    """Claude main 실행 시 ORCA_TERMINAL_HANDLE 이 설정되어 있어도 subprocess.Popen 이 절대 호출되지 않아야 합니다."""
    target = tmp_path / "preamble_popen.txt"
    target.write_text("회귀 검증 지시", encoding="utf-8")
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_REGRESSION_PROBE_CLAUDE")

    popen_called = []

    def tracking_popen(*args, **kwargs):
        popen_called.append((args, kwargs))
        raise RuntimeError(
            "subprocess.Popen 이 호출되었습니다! 실제 프로세스 생성이 차단되지 않았습니다."
        )

    monkeypatch.setattr("subprocess.Popen", tracking_popen)

    with patch("scripts.orca_claude_launch.run_claude", return_value=0):
        code = main(
            [
                "--model",
                "claude-3-7-sonnet-20250219",
                "--preamble",
                str(target),
                "--one-shot",
                "--no-keep-open",
            ]
        )
    assert code == 0
    assert len(popen_called) == 0, "subprocess.Popen 이 호출되었습니다"
