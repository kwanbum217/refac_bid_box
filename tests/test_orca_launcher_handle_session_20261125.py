"""2026-11-25 런처 핸들 파일 소비 회귀 시험.

taskctl 은 preamble 옆에 같은 nonce 의 `.handle` 을 씁니다. opencode 런처만
이 파일을 읽고 지웠기 때문에 다른 런처에서는 낡은 핸들이 워크트리에 남았고,
읽지 않은 런처의 에이전트는 코디네이터 핸들을 상속해 worker_done 이 거부될
수 있었습니다. 여기서는 실제 CLI 를 띄우지 않고 subprocess/exec 만 가로채
런처별 소비 지점을 확인합니다.
"""

from __future__ import annotations

import os
import subprocess
import time
from pathlib import Path

import pytest

from scripts import (
    orca_agy_launch,
    orca_claude_launch,
    orca_cmd_launch,
    orca_codex_launch,
    orca_grok_launch,
    orca_kimi_launch,
    orca_qwen_launch,
)
from scripts import orca_worker_launch_common as common

WORKER_HANDLE = "term_worker_self_launcher_20261125"
PARENT_HANDLE = "term_coordinator_parent_launcher_20261125"
PREAMBLE_STEM = "preamble_task_ctx_launcher"


def _preamble(tmp_path: Path, handle: str | None) -> Path:
    target = tmp_path / f"{PREAMBLE_STEM}.txt"
    if handle is not None:
        _handle_file(tmp_path).write_text(handle + "\n", encoding="utf-8")
    target.write_text("지시문 본문", encoding="utf-8")
    return target


def _handle_file(tmp_path: Path) -> Path:
    return tmp_path / f"{PREAMBLE_STEM}.handle"


def _run(
    name: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    handle: str | None,
) -> tuple[int, dict[str, object], dict[str, object], Path]:
    """지정한 런처의 main 을 실제 CLI 없이 실행하고 관측값을 돌려줍니다."""
    preamble = _preamble(tmp_path, handle)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", PARENT_HANDLE)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    monkeypatch.setattr(orca_kimi_launch, "assert_model_available", lambda *a, **k: None)

    calls: dict[str, object] = {}

    def fake_schedule(*args, **kwargs):
        calls["args"] = args
        calls["kwargs"] = kwargs
        return True

    captured: dict[str, object] = {}

    def fake_run(cmd, env=None, **kwargs):
        if kwargs.get("capture_output"):
            return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")
        captured["cmd"] = list(cmd)
        captured["env"] = dict(env or {})
        return subprocess.CompletedProcess(cmd, 0)

    def fake_exec(file, argv, env):
        captured["file"] = file
        captured["argv"] = list(argv)
        captured["env"] = dict(env or {})

    monkeypatch.setattr(subprocess, "run", fake_run)
    monkeypatch.setattr(os, "execvpe", fake_exec)

    common_args = ["--preamble", str(preamble)]
    if name == "agy":
        monkeypatch.setattr(common, "schedule_permission_setup", fake_schedule)
        code = orca_agy_launch.main(["--model", "gemini-3.8-flash-medium", *common_args])
    elif name == "claude":
        monkeypatch.setattr(common, "schedule_permission_setup", fake_schedule)
        code = orca_claude_launch.main(
            ["--model", "claude-sonnet-4-6", *common_args, "--one-shot", "--no-keep-open"]
        )
    elif name == "cmd":
        monkeypatch.setattr(common, "schedule_permission_setup", fake_schedule)
        code = orca_cmd_launch.main(
            [
                "--model",
                "deepseek/deepseek-v4.1-flash",
                *common_args,
                "--one-shot",
                "--no-keep-open",
            ]
        )
    elif name == "grok":
        monkeypatch.setattr(common, "schedule_permission_setup", fake_schedule)
        code = orca_grok_launch.main(
            ["--model", "grok-2", *common_args, "--one-shot", "--no-keep-open"]
        )
    elif name == "kimi":
        monkeypatch.setattr(orca_kimi_launch, "schedule_permission_setup", fake_schedule)
        code = orca_kimi_launch.main(
            ["--model", "or-free/nemotron-ultra", *common_args, "--no-keep-open"]
        )
    elif name == "qwen":
        monkeypatch.setattr(orca_qwen_launch, "schedule_permission_setup", fake_schedule)
        code = orca_qwen_launch.main(
            ["--model", "qwen-plus", *common_args, "--one-shot", "--no-keep-open"]
        )
    else:  # pragma: no cover - 파라미터 오타 방지
        raise AssertionError(f"알 수 없는 런처: {name}")
    return code, captured, calls, preamble


@pytest.mark.parametrize("name", ["agy", "claude", "cmd", "grok", "kimi", "qwen"])
def test_launcher_consumes_handle_file_and_applies_worker_env(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(a)(b) preamble 을 소비하는 런처는 핸들도 소비하고 에이전트 env 에 씁니다."""
    code, captured, calls, preamble = _run(name, tmp_path, monkeypatch, handle=WORKER_HANDLE)

    assert code == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert env.get("ORCA_TERMINAL_HANDLE") == WORKER_HANDLE
    assert env.get("ORCA_TERMINAL_HANDLE") != PARENT_HANDLE
    assert not preamble.exists()
    assert not _handle_file(tmp_path).exists()
    # 권한 자동 승인 자식도 코디네이터가 아니라 워커 터미널을 대상으로 해야 한다.
    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    assert kwargs.get("terminal") == WORKER_HANDLE


@pytest.mark.parametrize("name", ["agy", "claude", "cmd", "grok", "kimi", "qwen"])
def test_launcher_without_handle_file_still_runs(
    name: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(c) .handle 이 없어도 런처는 실패하지 않고 상속 핸들만 비웁니다."""
    code, captured, calls, preamble = _run(name, tmp_path, monkeypatch, handle=None)

    assert code == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert "ORCA_TERMINAL_HANDLE" not in env
    assert not preamble.exists()
    kwargs = calls["kwargs"]
    assert isinstance(kwargs, dict)
    # 핸들을 모르면 권한 자식은 상속 env 로 물러섭니다(종전 동작).
    assert kwargs.get("terminal") is None


def test_launcher_discards_invalid_handle_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """핸들 형식이 아닌 값도 파일은 지우고, env 에는 넣지 않습니다."""
    code, captured, _calls, _preamble_path = _run(
        "cmd", tmp_path, monkeypatch, handle="coordinator-shell-value"
    )

    assert code == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert "ORCA_TERMINAL_HANDLE" not in env
    assert not _handle_file(tmp_path).exists()


def test_codex_launcher_cleans_orphan_handle_files(tmp_path: Path):
    """codex 런처는 preamble 없는 낡은 .handle 만 정리하고 살아있는 것은 둡니다."""
    cleanup = getattr(orca_codex_launch, "cleanup_orphan_handles", None)
    assert callable(cleanup), "orca_codex_launch.cleanup_orphan_handles 가 없습니다"

    orca_dir = tmp_path / ".orca"
    orca_dir.mkdir()
    stale = orca_dir / "preamble_stale_run.handle"
    stale.write_text(WORKER_HANDLE + "\n", encoding="utf-8")
    # 고아 정리는 수정 시각이 오래된 핸들만 지우므로, 남은 시도가 아닌 낡은
    # 핸들임을 파일 시각으로도 드러냅니다.
    stale_mtime = time.time() - 3600
    os.utime(stale, (stale_mtime, stale_mtime))
    live_handle = orca_dir / "preamble_live_run.handle"
    live_handle.write_text(WORKER_HANDLE + "\n", encoding="utf-8")
    (orca_dir / "preamble_live_run.txt").write_text("지시문", encoding="utf-8")

    removed = cleanup(tmp_path)

    assert [Path(item).name for item in removed] == ["preamble_stale_run.handle"]
    assert not stale.exists()
    assert live_handle.exists()
