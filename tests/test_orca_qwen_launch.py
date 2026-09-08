"""Qwen Code 런처의 대기·실행·창 유지 계약을 검증합니다."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import orca_qwen_launch
from scripts.orca_qwen_launch import (
    COMMIT_NOTICE,
    PERMISSION_SETUP_FLAG,
    REVIEWER_NOTICE,
    build_command,
    build_completion_message,
    main,
    registered_qwen_models,
    resolve_model,
    resolve_shell,
    run_qwen,
    wait_for_preamble,
)


@pytest.fixture(autouse=True)
def _guard_qwen_permission_setup(monkeypatch):
    """Qwen 런처 테스트가 실제 분리 프로세스를 띄우지 않도록 안전망을 제공합니다."""
    import subprocess

    orig_spawn = orca_qwen_launch.common.spawn_permission_setup
    _SENTINEL = object()

    def safe_spawn(
        launcher_script: str | Path, terminal: str, model: str, *, popen=_SENTINEL
    ) -> None:
        if popen is _SENTINEL or popen is subprocess.Popen:
            return None
        return orig_spawn(launcher_script, terminal, model, popen=popen)

    monkeypatch.setattr(orca_qwen_launch.common, "spawn_permission_setup", safe_spawn)


def test_wait_returns_content_once_written(tmp_path: Path):
    """고유 preamble_*.txt 파일이 작성되면 내용을 읽고 파일을 즉시 삭제해야 합니다."""
    target = tmp_path / "preamble_qwait.txt"

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


def test_wait_for_preamble_rejects_multiple_candidates_in_qwen(tmp_path: Path):
    """둘 이상의 preamble_*.txt 후보가 있으면 어느 것도 소비하지 않고 ValueError 로 거부해야 합니다."""
    f1 = tmp_path / "preamble_q1.txt"
    f2 = tmp_path / "preamble_q2.txt"
    f1.write_text("지시 1", encoding="utf-8")
    f2.write_text("지시 2", encoding="utf-8")

    with pytest.raises(ValueError) as exc:
        wait_for_preamble(f1, timeout_sec=1.0, poll_sec=0.05)
    assert "다중 preamble 후보 발견" in str(exc.value)
    assert f1.exists()
    assert f2.exists()


def test_build_command_interactive_and_one_shot():
    """기본은 -i(대화형), --one-shot 은 -p(단발) 플래그를 사용해야 합니다."""
    interactive_cmd = build_command("qwen3.7-plus", "지시문", one_shot=False)
    assert interactive_cmd == ["qwen", "-m", "qwen3.7-plus", "-i", "지시문"]

    one_shot_cmd = build_command("qwen3.7-plus", "지시문", one_shot=True)
    assert one_shot_cmd == ["qwen", "-m", "qwen3.7-plus", "-p", "지시문"]


def test_commit_notice_mentions_commit_requirement():
    assert "커밋" in COMMIT_NOTICE
    assert "git add -A" in COMMIT_NOTICE


def test_build_completion_message_includes_exit_code_and_continue_hint():
    message = build_completion_message(0, "qwen3.7-plus")
    assert "종료 코드: 0" in message
    assert "qwen -m qwen3.7-plus -c" in message


def test_resolve_shell_uses_shell_env_and_default():
    assert resolve_shell({"SHELL": "/bin/zsh"}) == "/bin/zsh"
    assert resolve_shell({}) == "/bin/bash"


def test_resolve_model_validates_against_registry():
    registered = registered_qwen_models()
    assert len(registered) > 0

    pool_key = next(iter(registered.keys()))
    actual_id = registered[pool_key]

    assert resolve_model(pool_key) == actual_id
    assert resolve_model(actual_id) == actual_id

    with pytest.raises(SystemExit) as exc:
        resolve_model("unregistered-qwen-model")
    assert "등록되어 있지 않습니다" in str(exc.value)


@patch("scripts.orca_qwen_launch.subprocess.run")
def test_run_qwen_uses_subprocess(mock_run: MagicMock):
    mock_run.return_value = MagicMock(returncode=0)
    code = run_qwen(["qwen", "-m", "qwen3.7-plus", "-i", "prompt"], {"PATH": "/usr/bin"})
    assert code == 0
    mock_run.assert_called_once_with(
        ["qwen", "-m", "qwen3.7-plus", "-i", "prompt"], env={"PATH": "/usr/bin"}
    )


@patch("scripts.orca_qwen_launch.open_interactive_shell")
@patch("scripts.orca_qwen_launch.run_qwen", return_value=0)
def test_qwen_main_consumes_and_deletes_unique_preamble(
    mock_run: MagicMock,
    mock_shell: MagicMock,
    tmp_path: Path,
):
    """Qwen main 실행 시 고유 preamble_*.txt 파일을 읽고 소비 후 삭제해야 합니다."""
    target = tmp_path / "preamble_run_unique_qwen.txt"
    target.write_text("큐웬 고유 지시문", encoding="utf-8")

    code = main(
        [
            "--model",
            "qwen3.7-plus",
            "--preamble",
            str(target),
            "--no-commit-notice",
            "--no-keep-open",
        ]
    )
    assert code == 0
    assert not target.exists(), "런처 기동 후 preamble 파일이 삭제되어야 합니다"
    prompt = mock_run.call_args[0][0][-1]
    assert prompt == "큐웬 고유 지시문"


@patch("scripts.orca_qwen_launch.open_interactive_shell")
@patch("scripts.orca_qwen_launch.run_qwen", return_value=0)
def test_commit_notice_appended_by_default(
    mock_run: MagicMock,
    mock_shell: MagicMock,
    tmp_path: Path,
):
    target = tmp_path / "preamble_test.txt"
    target.write_text("본문", encoding="utf-8")

    code = main(
        [
            "--model",
            "qwen3.7-plus",
            "--preamble",
            str(target),
            "--no-keep-open",
        ]
    )
    assert code == 0
    prompt = mock_run.call_args[0][0][-1]
    assert COMMIT_NOTICE in prompt
    assert "커밋" in prompt


@patch("scripts.orca_qwen_launch.open_interactive_shell")
@patch("scripts.orca_qwen_launch.run_qwen", return_value=0)
def test_reviewer_notice_is_appended_for_reviewer_preamble(
    mock_run: MagicMock,
    mock_shell: MagicMock,
    tmp_path: Path,
):
    reviewer_text = "계약: ORCA_REVIEW_DONE_V2\n산출물: review_done.json"
    target = tmp_path / "preamble_test.txt"
    target.write_text(reviewer_text, encoding="utf-8")

    code = main(
        [
            "--model",
            "qwen3.7-plus",
            "--preamble",
            str(target),
            "--no-keep-open",
        ]
    )
    assert code == 0
    prompt = mock_run.call_args[0][0][-1]
    assert REVIEWER_NOTICE in prompt
    assert COMMIT_NOTICE not in prompt


@patch("scripts.orca_qwen_launch.open_interactive_shell")
@patch("scripts.orca_qwen_launch.run_qwen", return_value=0)
def test_role_flag_overrides_automatic_detection(
    mock_run: MagicMock,
    mock_shell: MagicMock,
    tmp_path: Path,
):
    target = tmp_path / "preamble_test.txt"
    target.write_text("일반 작업 지시", encoding="utf-8")

    code = main(
        [
            "--model",
            "qwen3.7-plus",
            "--preamble",
            str(target),
            "--role",
            "reviewer",
            "--no-keep-open",
        ]
    )
    assert code == 0
    prompt = mock_run.call_args[0][0][-1]
    assert REVIEWER_NOTICE in prompt
    assert COMMIT_NOTICE not in prompt


def test_preamble_timeout_returns_nonzero(tmp_path: Path):
    missing = tmp_path / "missing.txt"
    assert (
        main(
            [
                "--model",
                "qwen3.7-plus",
                "--preamble",
                str(missing),
                "--timeout-sec",
                "0.1",
                "--no-commit-notice",
            ]
        )
        == 2
    )


def test_preamble_multiple_candidates_returns_nonzero(tmp_path: Path, capsys):
    f1 = tmp_path / "preamble_q1.txt"
    f2 = tmp_path / "preamble_q2.txt"
    f1.write_text("1", encoding="utf-8")
    f2.write_text("2", encoding="utf-8")

    code = main(
        [
            "--model",
            "qwen3.7-plus",
            "--preamble",
            str(f1),
            "--timeout-sec",
            "1.0",
            "--no-commit-notice",
        ]
    )
    assert code == 2
    err = capsys.readouterr().err
    assert "다중 preamble 후보 발견" in err


def test_permission_setup_child_in_qwen_launcher():
    assert main([PERMISSION_SETUP_FLAG]) == 2
    assert main([PERMISSION_SETUP_FLAG, "term_q"]) == 2
    assert main([PERMISSION_SETUP_FLAG, "  ", "qwen3.7-plus"]) == 2

    with patch("scripts.orca_qwen_launch.run_permission_setup_child", return_value=0) as mock_child:
        code = main([PERMISSION_SETUP_FLAG, "term_q", "qwen3.7-plus"])
        assert code == 0
        mock_child.assert_called_once()
        args, kwargs = mock_child.call_args
        assert args[0] == [PERMISSION_SETUP_FLAG, "term_q", "qwen3.7-plus"]
        assert kwargs.get("cli_type") == "qwen"


@patch("scripts.orca_qwen_launch.open_interactive_shell")
@patch("scripts.orca_qwen_launch.run_qwen", return_value=0)
def test_qwen_launcher_schedules_permission_setup(
    mock_run: MagicMock,
    mock_shell: MagicMock,
    tmp_path: Path,
    monkeypatch,
):
    target = tmp_path / "preamble_q.txt"
    target.write_text("지시", encoding="utf-8")
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_qwen_123")

    scheduled = []
    monkeypatch.setattr(
        orca_qwen_launch,
        "schedule_permission_setup",
        lambda script, model, **kw: scheduled.append((script, model)),
    )

    main(
        [
            "--model",
            "qwen3.7-plus",
            "--preamble",
            str(target),
            "--no-commit-notice",
            "--no-keep-open",
        ]
    )

    assert len(scheduled) == 1
    assert scheduled[0][1] == "qwen3.7-plus"


def test_main_never_calls_popen_for_permission_setup(tmp_path: Path, monkeypatch):
    """Qwen main 실행 시 ORCA_TERMINAL_HANDLE 이 있어도 subprocess.Popen 이 절대 호출되지 않아야 합니다."""
    target = tmp_path / "preamble_probe.txt"
    target.write_text("회귀 검증 지시", encoding="utf-8")
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_REGRESSION_PROBE_QWEN")

    popen_called = []

    def tracking_popen(*args, **kwargs):
        popen_called.append((args, kwargs))
        raise RuntimeError(
            "subprocess.Popen 이 호출되었습니다! 실제 프로세스 생성이 차단되지 않았습니다."
        )

    monkeypatch.setattr("subprocess.Popen", tracking_popen)

    with (
        patch("scripts.orca_qwen_launch.run_qwen", return_value=0),
        patch("scripts.orca_qwen_launch.open_interactive_shell"),
    ):
        code = main(
            [
                "--model",
                "qwen3.7-plus",
                "--preamble",
                str(target),
                "--no-commit-notice",
                "--no-keep-open",
            ]
        )
    assert code == 0
    assert len(popen_called) == 0, "subprocess.Popen 이 호출되었습니다"
