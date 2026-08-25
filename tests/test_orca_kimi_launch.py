"""Kimi 런처의 대기 계약을 검증합니다."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from scripts.orca_kimi_launch import COMMIT_NOTICE, build_command, wait_for_preamble


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
