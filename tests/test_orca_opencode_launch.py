"""OpenCode 런처의 대기·실행·창 유지 계약을 검증합니다."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts import orca_opencode_launch
from scripts.orca_opencode_launch import (
    COMMIT_NOTICE,
    PERMISSION_SETUP_FLAG,
    REVIEWER_NOTICE,
    build_command,
    build_completion_message,
    build_env,
    main,
    open_interactive_shell,
    resolve_shell,
    run_opencode,
    wait_for_preamble,
)


@pytest.fixture(autouse=True)
def _guard_opencode_permission_setup(monkeypatch):
    """OpenCode 런처 테스트가 실제 분리 프로세스를 띄우지 않도록 안전망을 제공합니다."""
    import subprocess

    orig_spawn = orca_opencode_launch.spawn_permission_setup
    _SENTINEL = object()

    def safe_spawn(
        launcher_script: str | Path, terminal: str, model: str, *, popen=_SENTINEL
    ) -> None:
        if popen is _SENTINEL or popen is subprocess.Popen:
            return None
        return orig_spawn(launcher_script, terminal, model, popen=popen)

    monkeypatch.setattr(orca_opencode_launch, "spawn_permission_setup", safe_spawn)


def test_wait_returns_content_once_written(tmp_path: Path):
    """고유 preamble_*.txt 파일이 작성되면 내용을 읽고 파일을 즉시 삭제해야 합니다."""
    target = tmp_path / "preamble_owait.txt"

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


@patch("scripts.orca_opencode_launch.run_opencode", return_value=0)
@patch("scripts.orca_opencode_launch.open_interactive_shell")
def test_opencode_main_consumes_and_deletes_unique_preamble(
    mock_shell: MagicMock,
    mock_run: MagicMock,
    tmp_path: Path,
):
    """OpenCode main 실행 시 고유 preamble_*.txt 파일을 읽고 소비 후 삭제해야 합니다."""
    target = tmp_path / "preamble_run_unique_opencode.txt"
    target.write_text("오픈코드 고유 지시문", encoding="utf-8")

    code = main(
        [
            "--model",
            "openai/gpt-5.6-turbo",
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
    assert prompt == "오픈코드 고유 지시문"


def test_build_command_interactive_and_one_shot():
    """대화형은 opencode --standalone --prompt, 단발은 opencode run --model 형태여야 합니다.

    opencode v2.0.32 최상위 TUI 에는 --model 과 --agent 가 없으므로 대화형 명령에
    모델을 싣지 않습니다. 모델은 build_env 가 OPENCODE_CONFIG_CONTENT 로 주입합니다.
    """
    interactive_cmd = build_command("openai/gpt-5.6-turbo", "지시문", one_shot=False)
    assert interactive_cmd == ["opencode", "--standalone", "--prompt", "지시문"]
    assert "--model" not in interactive_cmd
    assert "--agent" not in interactive_cmd

    one_shot_cmd = build_command("openai/gpt-5.6-turbo", "지시문", one_shot=True)
    assert one_shot_cmd == ["opencode", "run", "--model", "openai/gpt-5.6-turbo", "지시문"]


def test_build_command_never_forwards_auto_flag():
    """--auto 는 어떤 조합에서도 opencode 에 넘기지 않아야 합니다.

    --auto 는 명시 deny 가 아닌 모든 승인 요청을 자동 승인합니다(opencode --help:
    "auto-approve permissions that are not explicitly denied (dangerous!)").
    인자 자체는 호환을 위해 남기지만 argv 에는 실리지 않습니다.
    """
    for one_shot in (False, True):
        for auto in (False, True):
            cmd = build_command("openai/gpt-5.6-turbo", "지시문", one_shot=one_shot, auto=auto)
            assert "--auto" not in cmd, cmd

    assert build_command("openai/gpt-5.6-turbo", "지시문", auto=True) == [
        "opencode",
        "--standalone",
        "--prompt",
        "지시문",
    ]
    assert build_command("openai/gpt-5.6-turbo", "지시문", one_shot=True, auto=True) == [
        "opencode",
        "run",
        "--model",
        "openai/gpt-5.6-turbo",
        "지시문",
    ]


def test_commit_notice_mentions_commit_requirement():
    assert "커밋" in COMMIT_NOTICE
    assert "git add -A" in COMMIT_NOTICE


def test_build_completion_message_includes_exit_code():
    message = build_completion_message(0, "openai/gpt-5.6-turbo")
    assert "종료 코드: 0" in message


def test_resolve_shell_uses_shell_env():
    assert resolve_shell({"SHELL": "/bin/zsh"}) == "/bin/zsh"
    assert resolve_shell({}) == "/bin/bash"


@patch("scripts.orca_opencode_launch.subprocess.run")
def test_run_opencode_uses_subprocess(mock_run: MagicMock):
    mock_run.return_value = MagicMock(returncode=0)
    code = run_opencode(["opencode", "run", "--model", "m", "p"], {"PATH": "/usr/bin"})
    assert code == 0
    mock_run.assert_called_once_with(
        ["opencode", "run", "--model", "m", "p"], env={"PATH": "/usr/bin"}
    )


@patch("scripts.orca_opencode_launch.os.execvpe")
def test_open_interactive_shell_uses_resolved_shell(mock_exec: MagicMock):
    open_interactive_shell({"SHELL": "/bin/fish"})
    mock_exec.assert_called_once_with("/bin/fish", ["/bin/fish"], {"SHELL": "/bin/fish"})


@patch("scripts.orca_opencode_launch.open_interactive_shell")
@patch("scripts.orca_opencode_launch.run_opencode", return_value=0)
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
            "openai/gpt-5.6-turbo",
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
    with patch("scripts.orca_opencode_launch.run_opencode", return_value=0) as mock_run:
        main(["--model", "m", "--preamble", str(target), "--one-shot", "--no-keep-open"])
    assert COMMIT_NOTICE in mock_run.call_args[0][0][-1]

    # 2. --no-commit-notice 지정: 고지문 미부착
    target.write_text("일반 빌드 작업", encoding="utf-8")
    with patch("scripts.orca_opencode_launch.run_opencode", return_value=0) as mock_run:
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
    with patch("scripts.orca_opencode_launch.run_opencode", return_value=0) as mock_run:
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
    with patch("scripts.orca_opencode_launch.run_opencode", return_value=0) as mock_run:
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


def test_permission_setup_child_in_opencode_launcher():
    """OpenCode 런처의 자식 모드 인자 검증 및 실행을 확인합니다."""
    assert main([PERMISSION_SETUP_FLAG]) == 2
    assert main([PERMISSION_SETUP_FLAG, "term_o"]) == 2
    assert main([PERMISSION_SETUP_FLAG, "  ", "model_o"]) == 2

    with patch(
        "scripts.orca_worker_launch_common.run_permission_setup_child", return_value=0
    ) as mock_child:
        code = main([PERMISSION_SETUP_FLAG, "term_o", "openai/gpt-5.6-turbo"])
        assert code == 0
        mock_child.assert_called_once()
        args, kwargs = mock_child.call_args
        assert args[0] == [PERMISSION_SETUP_FLAG, "term_o", "openai/gpt-5.6-turbo"]
        assert kwargs.get("cli_type") == "opencode"


def test_main_never_calls_popen_for_permission_setup(tmp_path: Path, monkeypatch):
    """OpenCode main 실행 시 ORCA_TERMINAL_HANDLE 이 설정되어 있어도 subprocess.Popen 이 절대 호출되지 않아야 합니다."""
    target = tmp_path / "preamble_popen.txt"
    target.write_text("회귀 검증 지시", encoding="utf-8")
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", "term_REGRESSION_PROBE_OPENCODE")

    popen_called = []

    def tracking_popen(*args, **kwargs):
        popen_called.append((args, kwargs))
        raise RuntimeError(
            "subprocess.Popen 이 호출되었습니다! 실제 프로세스 생성이 차단되지 않았습니다."
        )

    monkeypatch.setattr("subprocess.Popen", tracking_popen)

    with patch("scripts.orca_opencode_launch.run_opencode", return_value=0):
        code = main(
            [
                "--model",
                "openai/gpt-5.6-turbo",
                "--preamble",
                str(target),
                "--one-shot",
                "--no-keep-open",
            ]
        )
    assert code == 0
    assert len(popen_called) == 0, "subprocess.Popen 이 호출되었습니다"


def test_build_command_kilo_binary_with_variant():
    """kilo 바이너리와 추론 등급은 run 단발 명령에 그대로 실려야 합니다."""
    cmd = build_command(
        "openrouter/stealth/space-bunny-alpha",
        "지시문",
        one_shot=True,
        auto=True,
        binary="kilo",
        variant="max",
    )
    assert cmd == [
        "kilo",
        "run",
        "--model",
        "openrouter/stealth/space-bunny-alpha",
        "--variant",
        "max",
        "지시문",
    ]
    assert "--auto" not in cmd


def test_opencode_interactive_command_has_standalone_without_unknown_flags():
    """opencode 대화형 명령에는 v2.0.32 가 모르는 플래그가 없어야 합니다."""
    cmd = build_command("opencode/deepseek-v4.1-flash-free", "지시문")
    assert "--standalone" in cmd
    assert "--prompt" in cmd
    assert "--model" not in cmd
    assert "--agent" not in cmd
    assert "--variant" not in cmd


def test_build_command_opencode_one_shot_embeds_variant_in_model_id():
    """opencode 단발 등급은 --variant 플래그가 아니라 모델 ID 뒤 #variant 로 붙입니다."""
    cmd = build_command("opencode/space-bunny-free", "지시문", one_shot=True, variant="max")
    assert cmd == ["opencode", "run", "--model", "opencode/space-bunny-free#max", "지시문"]
    assert "--variant" not in cmd


def test_build_command_rejects_variant_in_opencode_interactive_mode():
    """opencode 대화형 TUI 에는 --variant 가 없으므로 조용히 버리지 않고 거부해야 합니다."""
    with pytest.raises(ValueError):
        build_command("openrouter/stealth/space-bunny-alpha", "지시문", variant="max")


def test_main_rejects_variant_without_one_shot_for_opencode(tmp_path: Path):
    target = tmp_path / "preamble_variant.txt"
    target.write_text("지시문", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["--model", "m", "--preamble", str(target), "--variant", "max"])
    assert exc.value.code == 2
    assert target.exists()


def test_build_command_kilo_interactive_variant_selects_injected_agent():
    """kilo 대화형 등급은 --model 대신 주입 에이전트를 골라 TUI 로 띄워야 합니다."""
    cmd = build_command(
        "openrouter/stealth/space-bunny-alpha",
        "지시문",
        auto=True,
        binary="kilo",
        variant="max",
    )
    assert cmd == ["kilo", "--agent", "orca-worker", "--prompt", "지시문"]
    assert "--auto" not in cmd


def test_build_env_injects_kilo_agent_with_model_and_variant():
    env = build_env(
        {"PATH": "/bin"}, "openrouter/stealth/space-bunny-alpha", binary="kilo", variant="max"
    )
    agent = json.loads(env["KILO_CONFIG_CONTENT"])["agent"]["orca-worker"]
    assert agent["model"] == "openrouter/stealth/space-bunny-alpha"
    assert agent["variant"] == "max"
    assert env["PATH"] == "/bin"


def test_build_env_injects_opencode_model_config():
    """opencode 대화형 모델은 TUI 플래그가 아니라 OPENCODE_CONFIG_CONTENT 로 주입합니다."""
    env = build_env({"PATH": "/bin"}, "opencode/space-bunny-free")
    assert env["OPENCODE_CONFIG_CONTENT"] == json.dumps({"model": "opencode/space-bunny-free"})
    assert env["PATH"] == "/bin"


def test_build_env_refuses_to_overwrite_existing_opencode_config():
    with pytest.raises(ValueError):
        build_env({"OPENCODE_CONFIG_CONTENT": "{}"}, "m")


def test_build_env_leaves_env_untouched_for_one_shot_and_kilo_without_variant():
    base = {"PATH": "/bin"}
    assert build_env(base, "m", binary="opencode", one_shot=True, variant="max") == base
    assert build_env(base, "m", binary="kilo", variant=None) == base
    assert build_env(base, "m", binary="kilo", one_shot=True, variant="max") == base


def test_build_env_refuses_to_overwrite_existing_kilo_config():
    with pytest.raises(ValueError):
        build_env({"KILO_CONFIG_CONTENT": "{}"}, "m", binary="kilo", variant="max")


@patch("scripts.orca_opencode_launch.os.execvpe")
def test_main_opencode_interactive_execs_tui_with_injected_model(
    mock_exec: MagicMock, tmp_path: Path, monkeypatch
):
    """opencode 대화형은 --standalone 으로 TUI 를 exec 하고 모델은 환경변수로 넘깁니다."""
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    target = tmp_path / "preamble_opencode_tui.txt"
    target.write_text("지시문", encoding="utf-8")
    code = main(
        [
            "--model",
            "opencode/space-bunny-free",
            "--preamble",
            str(target),
            "--auto",
            "--no-commit-notice",
        ]
    )
    assert code == 0
    cmd, env = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
    assert cmd == ["opencode", "--standalone", "--prompt", "지시문"]
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"])["model"] == "opencode/space-bunny-free"


@patch("scripts.orca_opencode_launch.os.execvpe")
def test_main_kilo_interactive_execs_tui_with_injected_agent(
    mock_exec: MagicMock, tmp_path: Path, monkeypatch
):
    monkeypatch.delenv("KILO_CONFIG_CONTENT", raising=False)
    target = tmp_path / "preamble_kilo_tui.txt"
    target.write_text("지시문", encoding="utf-8")
    code = main(
        [
            "--binary",
            "kilo",
            "--model",
            "openrouter/stealth/space-bunny-alpha",
            "--preamble",
            str(target),
            "--variant",
            "max",
            "--auto",
            "--no-commit-notice",
        ]
    )
    assert code == 0
    cmd, env = mock_exec.call_args[0][1], mock_exec.call_args[0][2]
    assert cmd[:3] == ["kilo", "--agent", "orca-worker"]
    assert json.loads(env["KILO_CONFIG_CONTENT"])["agent"]["orca-worker"]["variant"] == "max"


def test_main_rejects_unknown_variant(tmp_path: Path):
    """두 CLI 모두 모르는 등급을 오류 없이 무시하므로 런처가 먼저 거부해야 합니다."""
    target = tmp_path / "preamble_bogus.txt"
    target.write_text("지시문", encoding="utf-8")
    with pytest.raises(SystemExit) as exc:
        main(["--model", "m", "--preamble", str(target), "--one-shot", "--variant", "bogus"])
    assert exc.value.code == 2


@patch("scripts.orca_opencode_launch.open_interactive_shell")
@patch("scripts.orca_opencode_launch.run_opencode", return_value=0)
def test_main_one_shot_runs_kilo_binary(mock_run: MagicMock, mock_shell: MagicMock, tmp_path: Path):
    target = tmp_path / "preamble_kilo.txt"
    target.write_text("지시문", encoding="utf-8")
    code = main(
        [
            "--binary",
            "kilo",
            "--model",
            "openrouter/stealth/space-bunny-alpha",
            "--preamble",
            str(target),
            "--one-shot",
            "--variant",
            "max",
            "--auto",
            "--no-commit-notice",
        ]
    )
    assert code == 0
    cmd = mock_run.call_args[0][0]
    assert cmd[:6] == [
        "kilo",
        "run",
        "--model",
        "openrouter/stealth/space-bunny-alpha",
        "--variant",
        "max",
    ]
    assert "--auto" not in cmd
