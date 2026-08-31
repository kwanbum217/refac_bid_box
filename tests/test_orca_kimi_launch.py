"""Kimi 런처의 대기·실행·창 유지 계약을 검증합니다."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import orca_kimi_launch
from scripts.orca_kimi_launch import (
    COMMIT_NOTICE,
    PERMISSION_SETUP_FLAG,
    build_command,
    build_completion_message,
    main,
    open_interactive_shell,
    resolve_shell,
    run_kimi,
    wait_for_preamble,
)


@pytest.fixture(autouse=True)
def _skip_model_registry_check(request, monkeypatch):
    """기존 main() 테스트는 실제 프로필에 없는 가짜 모델명을 씁니다.

    main() 은 기동 전에 모델 등록 여부를 검증하므로 그대로 두면 전부 SystemExit 이
    납니다. 검증 자체는 아래 전용 테스트가 따로 다룹니다.
    """
    if request.node.name.startswith("test_assert_model_available"):
        return
    monkeypatch.setattr(orca_kimi_launch, "assert_model_available", lambda model, home: None)


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


# ===========================================================================
# 기동 전 모델 등록 검증
# ===========================================================================


def test_assert_model_available_lists_profile_models(tmp_path: Path):
    """모델이 없으면 그 프로필에서 쓸 수 있는 목록과 함께 중단합니다.

    2026-08-30 에 기본 프로필에서 응답을 확인한 모델을 런처로 띄웠는데, 런처의
    DEFAULT_HOME 이 다른 프로필이라 그곳에는 모델이 없어 기동 직후 종료했습니다.
    화면에는 워커가 뜬 것처럼 보여 원인을 찾기 어려웠습니다.
    """
    (tmp_path / "config.toml").write_text(
        '[models."or-free/alpha"]\nmodel = "x"\n[models."or-free/beta"]\nmodel = "y"\n',
        encoding="utf-8",
    )
    assert orca_kimi_launch.available_models(tmp_path) == ["or-free/alpha", "or-free/beta"]

    orca_kimi_launch.assert_model_available("or-free/alpha", tmp_path)

    with pytest.raises(SystemExit) as err:
        orca_kimi_launch.assert_model_available("or-free/missing", tmp_path)
    message = str(err.value)
    assert "or-free/missing" in message
    assert "or-free/alpha" in message
    assert "or-free/beta" in message


def test_assert_model_available_without_config(tmp_path: Path):
    """프로필에 config.toml 이 없으면 명확히 중단합니다."""
    with pytest.raises(SystemExit) as err:
        orca_kimi_launch.assert_model_available("or-free/alpha", tmp_path)
    assert "config.toml" in str(err.value)


# ===========================================================================
# 권한 자동 승인 준비 계약 검증
# ===========================================================================


def test_permission_setup_child_in_kimi_launcher():
    """Kimi 런처의 자식 모드 인자 검증 및 실행을 확인합니다."""
    assert main([PERMISSION_SETUP_FLAG]) == 2
    assert main([PERMISSION_SETUP_FLAG, "term_k"]) == 2
    assert main([PERMISSION_SETUP_FLAG, "  ", "model_k"]) == 2

    with patch("scripts.orca_kimi_launch.run_permission_setup_child", return_value=0) as mock_child:
        code = main([PERMISSION_SETUP_FLAG, "term_k", "or-free/nemotron-ultra"])
        assert code == 0
        mock_child.assert_called_once()
        args, kwargs = mock_child.call_args
        assert args[0] == [PERMISSION_SETUP_FLAG, "term_k", "or-free/nemotron-ultra"]
        assert kwargs.get("cli_type") == "kimi"


@patch("scripts.orca_kimi_launch.run_kimi", return_value=0)
@patch("scripts.orca_kimi_launch.wait_for_preamble", return_value="지시")
def test_kimi_launcher_schedules_permission_setup(
    mock_wait: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
    monkeypatch,
):
    preamble = tmp_path / "preamble.txt"
    preamble.write_text("지시", encoding="utf-8")
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_kimi_123")

    spawned = []
    monkeypatch.setattr(
        "scripts.orca_kimi_launch.spawn_permission_setup",
        lambda script, term, model: spawned.append((script, term, model)),
    )

    with patch("scripts.orca_kimi_launch.open_interactive_shell"):
        main(
            [
                "--model",
                "or-free/nemotron-ultra",
                "--preamble",
                str(preamble),
                "--no-commit-notice",
                "--no-keep-open",
            ]
        )

    assert len(spawned) == 1
    assert spawned[0][1] == "term_kimi_123"
    assert spawned[0][2] == "or-free/nemotron-ultra"


@patch("scripts.orca_kimi_launch.run_kimi", return_value=0)
@patch("scripts.orca_kimi_launch.wait_for_preamble", return_value="지시")
def test_kimi_launcher_warns_when_handle_absent(
    mock_wait: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
    monkeypatch,
    capsys,
):
    preamble = tmp_path / "preamble.txt"
    preamble.write_text("지시", encoding="utf-8")
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)

    with patch("scripts.orca_kimi_launch.open_interactive_shell"):
        main(
            [
                "--model",
                "or-free/nemotron-ultra",
                "--preamble",
                str(preamble),
                "--no-commit-notice",
                "--no-keep-open",
            ]
        )

    err = capsys.readouterr().err
    assert "ORCA_TERMINAL_HANDLE" in err
