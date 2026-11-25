"""워커 런처가 에이전트 환경의 ORCA_TERMINAL_HANDLE 을 워커 자기 핸들로 확정하는지 검증합니다.

배경: 코디네이터 셸에서 워커 터미널을 만들면 부모 환경의 ORCA_TERMINAL_HANDLE 이
런처와 에이전트로 상속될 수 있습니다. 그 값이 코디네이터 핸들이면 worker_done 과
escalation 이 'not the exact process that owns Dispatch' 로 거부됩니다. 런처는
taskctl 이 preamble 옆에 남긴 워커 핸들 파일을 읽어 에이전트 환경을 확정해야 합니다.

실제 orca·opencode 프로세스는 띄우지 않고 subprocess 만 가로채서 확인합니다.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import orca_opencode_launch
from scripts.orca_opencode_launch import main

WORKER_HANDLE = "term_worker_self_20261125"
PARENT_HANDLE = "term_coordinator_parent_20261125"
MODEL = "openai/gpt-5.6-turbo"


def _write_preamble(tmp_path: Path, *, handle: str | None) -> Path:
    preamble = tmp_path / "preamble_task_ctx_deadbeef.txt"
    if handle is not None:
        (tmp_path / "preamble_task_ctx_deadbeef.handle").write_text(handle + "\n", encoding="utf-8")
    preamble.write_text("지시문 본문", encoding="utf-8")
    return preamble


def _capture_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, *, handle: str | None):
    preamble = _write_preamble(tmp_path, handle=handle)
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", PARENT_HANDLE)
    monkeypatch.setattr(orca_opencode_launch, "spawn_permission_setup", lambda *a, **k: None)

    captured: dict[str, object] = {}

    def fake_run(cmd, env=None, **kwargs):
        captured["cmd"] = cmd
        captured["env"] = env
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(orca_opencode_launch.subprocess, "run", fake_run)
    code = main(
        [
            "--model",
            MODEL,
            "--preamble",
            str(preamble),
            "--one-shot",
            "--no-keep-open",
        ]
    )
    return code, captured, preamble


def test_agent_env_uses_worker_handle_over_inherited_parent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """(a) 부모 환경에 다른 핸들이 있어도 에이전트는 워커 자기 핸들을 받아야 합니다."""
    code, captured, preamble = _capture_run(tmp_path, monkeypatch, handle=WORKER_HANDLE)

    assert code == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["ORCA_TERMINAL_HANDLE"] == WORKER_HANDLE
    assert env["ORCA_TERMINAL_HANDLE"] != PARENT_HANDLE
    assert not preamble.exists()
    assert not (tmp_path / "preamble_task_ctx_deadbeef.handle").exists()


def test_unknown_worker_handle_clears_inherited_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """(b) 워커 핸들을 모르면 상속값을 남기지 않고 비우고 경고를 남겨야 합니다."""
    code, captured, _preamble = _capture_run(tmp_path, monkeypatch, handle=None)

    assert code == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert "ORCA_TERMINAL_HANDLE" not in env
    assert "비웠습니다" in capsys.readouterr().err


def test_invalid_handle_file_is_not_trusted(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
):
    """핸들 형식이 아닌 값은 워커 핸들로 쓰지 않고 상속값을 비웁니다."""
    code, captured, _preamble = _capture_run(
        tmp_path, monkeypatch, handle="coordinator-shell-value"
    )

    assert code == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert "ORCA_TERMINAL_HANDLE" not in env
    assert "비웠습니다" in capsys.readouterr().err


def test_interactive_launch_also_applies_worker_handle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """대화형 exec 경로도 같은 워커 핸들을 에이전트 환경에 넘깁니다."""
    preamble = _write_preamble(tmp_path, handle=WORKER_HANDLE)
    monkeypatch.setenv("ORCA_TERMINAL_HANDLE", PARENT_HANDLE)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    monkeypatch.setattr(orca_opencode_launch, "spawn_permission_setup", lambda *a, **k: None)

    captured: dict[str, object] = {}

    def fake_execvpe(file, args, env):
        captured["file"] = file
        captured["args"] = args
        captured["env"] = env

    monkeypatch.setattr(orca_opencode_launch.os, "execvpe", fake_execvpe)
    code = main(["--model", MODEL, "--preamble", str(preamble)])

    assert code == 0
    env = captured["env"]
    assert isinstance(env, dict)
    assert env["ORCA_TERMINAL_HANDLE"] == WORKER_HANDLE


def test_taskctl_writes_worker_handle_sidecar(tmp_path: Path):
    """taskctl 은 preamble 과 같은 nonce 의 핸들 파일을 먼저 쓸 수 있어야 합니다."""
    from scripts import orca_taskctl
    from scripts import orca_worker_launch_common as common

    writer = getattr(common, "write_worker_handle", None)
    assert callable(writer), "orca_worker_launch_common.write_worker_handle 이 없습니다"
    assert callable(getattr(orca_taskctl, "write_worker_handle", None)), (
        "taskctl 이 write_worker_handle 을 사용하지 않습니다"
    )

    preamble = tmp_path / "preamble_task_ctx_cafebabe.txt"
    target = writer(preamble, WORKER_HANDLE)
    assert target is not None
    assert target.name == "preamble_task_ctx_cafebabe.handle"
    assert target.read_text(encoding="utf-8").strip() == WORKER_HANDLE

    path_fn = getattr(common, "worker_handle_path", None)
    assert callable(path_fn)
    assert path_fn(preamble) == target
