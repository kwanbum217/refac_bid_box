"""Antigravity 런처의 대기/기동 계약을 검증합니다."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from scripts.orca_agy_launch import COMMIT_NOTICE, build_command, wait_for_preamble


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
