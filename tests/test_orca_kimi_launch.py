"""Kimi 런처의 대기·실행·창 유지 계약을 검증합니다."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.orca_kimi_launch import (
    COMMIT_NOTICE,
    build_command,
    build_completion_message,
    main,
    open_interactive_shell,
    resolve_shell,
    run_kimi,
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


def test_build_command_passes_prompt_as_argument():
    """-p 인자 경로여야 합니다. 주입 경로는 Kimi TUI 를 종료시킵니다."""
    cmd = build_command("or-free/nemotron-ultra", "본문")
    assert cmd == ["kimi", "-m", "or-free/nemotron-ultra", "-p", "본문"]


def test_commit_notice_mentions_commit_requirement():
    assert "커밋" in COMMIT_NOTICE
    assert "git add -A" in COMMIT_NOTICE


def test_build_completion_message_includes_exit_code_and_continue_hint():
    message = build_completion_message(17, "or-free/nemotron-ultra")
    assert "종료 코드: 17" in message
    assert "kimi -m or-free/nemotron-ultra -c" in message


def test_build_completion_message_shows_nonzero_exit_code():
    message = build_completion_message(1, "test-model")
    assert "종료 코드: 1" in message


def test_resolve_shell_uses_shell_env():
    assert resolve_shell({"SHELL": "/bin/zsh"}) == "/bin/zsh"


def test_resolve_shell_falls_back_to_default():
    assert resolve_shell({}) == "/bin/bash"


@patch("scripts.orca_kimi_launch.subprocess.run")
def test_run_kimi_uses_subprocess_not_exec(mock_run: MagicMock):
    mock_run.return_value = MagicMock(returncode=0)
    code = run_kimi(["kimi", "-m", "m", "-p", "p"], {"PATH": "/usr/bin"})
    assert code == 0
    mock_run.assert_called_once_with(["kimi", "-m", "m", "-p", "p"], env={"PATH": "/usr/bin"})


@patch("scripts.orca_kimi_launch.os.execvpe")
@patch("scripts.orca_kimi_launch.run_kimi", return_value=0)
@patch("scripts.orca_kimi_launch.wait_for_preamble", return_value="지시")
def test_default_keeps_terminal_open_with_shell(
    mock_wait: MagicMock,
    mock_run: MagicMock,
    mock_exec: MagicMock,
    tmp_path: Path,
):
    preamble = tmp_path / "preamble.txt"
    preamble.write_text("지시", encoding="utf-8")
    with patch.dict("os.environ", {"SHELL": "/bin/zsh"}, clear=False):
        assert (
            main(
                [
                    "--model",
                    "or-free/nemotron-ultra",
                    "--preamble",
                    str(preamble),
                    "--no-commit-notice",
                ]
            )
            == 0
        )
    mock_wait.assert_called_once()
    mock_run.assert_called_once()
    mock_exec.assert_called_once()
    shell, argv, _env = mock_exec.call_args[0]
    assert shell == "/bin/zsh"
    assert argv == ["/bin/zsh"]


@patch("scripts.orca_kimi_launch.open_interactive_shell")
@patch("scripts.orca_kimi_launch.run_kimi", return_value=3)
@patch("scripts.orca_kimi_launch.wait_for_preamble", return_value="지시")
def test_default_prints_exit_code_before_shell(
    mock_wait: MagicMock,
    mock_run: MagicMock,
    mock_shell: MagicMock,
    tmp_path: Path,
    capsys,
):
    preamble = tmp_path / "preamble.txt"
    preamble.write_text("지시", encoding="utf-8")
    assert (
        main(
            [
                "--model",
                "test-model",
                "--preamble",
                str(preamble),
                "--no-commit-notice",
            ]
        )
        == 3
    )
    captured = capsys.readouterr()
    assert "종료 코드: 3" in captured.out
    mock_wait.assert_called_once()
    mock_run.assert_called_once()
    mock_shell.assert_called_once()


@patch("scripts.orca_kimi_launch.open_interactive_shell")
@patch("scripts.orca_kimi_launch.run_kimi", return_value=5)
@patch("scripts.orca_kimi_launch.wait_for_preamble", return_value="지시")
def test_no_keep_open_returns_kimi_exit_code_without_shell(
    mock_wait: MagicMock,
    mock_run: MagicMock,
    mock_shell: MagicMock,
    tmp_path: Path,
):
    preamble = tmp_path / "preamble.txt"
    preamble.write_text("지시", encoding="utf-8")
    assert (
        main(
            [
                "--model",
                "test-model",
                "--preamble",
                str(preamble),
                "--no-commit-notice",
                "--no-keep-open",
            ]
        )
        == 5
    )
    mock_wait.assert_called_once()
    mock_run.assert_called_once()
    mock_shell.assert_not_called()


@patch("scripts.orca_kimi_launch.run_kimi")
@patch("scripts.orca_kimi_launch.wait_for_preamble", return_value="본문")
def test_commit_notice_appended_by_default(
    mock_wait: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
):
    mock_run.return_value = 0
    preamble = tmp_path / "preamble.txt"
    preamble.write_text("본문", encoding="utf-8")
    with patch("scripts.orca_kimi_launch.open_interactive_shell"):
        assert (
            main(
                [
                    "--model",
                    "m",
                    "--preamble",
                    str(preamble),
                    "--no-keep-open",
                ]
            )
            == 0
        )
    mock_wait.assert_called_once()
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    prompt = cmd[-1]
    assert COMMIT_NOTICE in prompt
    assert "커밋" in prompt


@patch("scripts.orca_kimi_launch.run_kimi", return_value=0)
@patch("scripts.orca_kimi_launch.wait_for_preamble", return_value="본문")
def test_no_commit_notice_skips_append(
    mock_wait: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
):
    preamble = tmp_path / "preamble.txt"
    preamble.write_text("본문", encoding="utf-8")
    with patch("scripts.orca_kimi_launch.open_interactive_shell"):
        assert (
            main(
                [
                    "--model",
                    "m",
                    "--preamble",
                    str(preamble),
                    "--no-commit-notice",
                    "--no-keep-open",
                ]
            )
            == 0
        )
    mock_wait.assert_called_once()
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    prompt = cmd[-1]
    assert COMMIT_NOTICE not in prompt
    assert prompt == "본문"


def test_preamble_timeout_returns_nonzero(tmp_path: Path):
    missing = tmp_path / "missing.txt"
    assert (
        main(
            [
                "--model",
                "m",
                "--preamble",
                str(missing),
                "--timeout-sec",
                "0.1",
                "--no-commit-notice",
            ]
        )
        == 2
    )


@patch("scripts.orca_kimi_launch.os.execvpe")
def test_open_interactive_shell_uses_resolved_shell(mock_exec: MagicMock):
    open_interactive_shell({"SHELL": "/bin/fish"})
    mock_exec.assert_called_once_with("/bin/fish", ["/bin/fish"], {"SHELL": "/bin/fish"})
