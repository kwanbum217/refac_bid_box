"""OpenCode 워커 런처가 확정 variant 를 전역 상태 대신 워커 전용 XDG 상태로 고정하는지 검증합니다."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.orca_opencode_launch import (
    OPENCODE_MODEL_STATE_FILE,
    OPENCODE_MODEL_VARIANTS,
    OPENCODE_STATE_DIRNAME,
    OPENCODE_STATE_HOME_ENV,
    ORCA_WORKER_STATE_DIR,
    build_env,
    main,
)

DEEPSEEK = "opencode-go/deepseek-v4.1-flash"
GLM = "opencode-go/glm-5.3-flash"
UNREGISTERED = "opencode/space-bunny-free"


@pytest.fixture(autouse=True)
def _isolated_worker(monkeypatch, tmp_path: Path):
    """작업 디렉터리와 HOME 을 임시 경로로 분리하고 권한 설정 자식 프로세스를 막습니다."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    monkeypatch.chdir(worktree)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("ORCA_TERMINAL_HANDLE", raising=False)
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    monkeypatch.delenv("XDG_STATE_HOME", raising=False)
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)


def _preamble(tmp_path: Path) -> Path:
    target = tmp_path / "preamble_variant_state.txt"
    target.write_text("지시문", encoding="utf-8")
    return target


def _model_state(state_home: Path) -> dict:
    target = state_home / OPENCODE_STATE_DIRNAME / OPENCODE_MODEL_STATE_FILE
    return json.loads(target.read_text(encoding="utf-8"))


@pytest.mark.usefixtures("_isolated_worker")
@pytest.mark.parametrize("model", [DEEPSEEK, GLM])
@pytest.mark.parametrize("variant", ["low", "high", "max"])
def test_interactive_registered_worker_pins_variant_in_own_state(
    model: str, variant: str, tmp_path: Path
):
    env = build_env({"PATH": "/bin"}, model, variant=variant)

    state_home = Path(env[OPENCODE_STATE_HOME_ENV])
    assert state_home.is_relative_to(tmp_path / "worktree" / ORCA_WORKER_STATE_DIR)
    state = _model_state(state_home)
    assert state["variant"] == {model: variant}
    provider, _, model_id = model.partition("/")
    assert state["recent"] == [{"providerID": provider, "modelID": model_id}]
    assert state["favorite"] == []


@pytest.mark.usefixtures("_isolated_worker")
@patch("scripts.orca_opencode_launch.os.execvpe")
def test_main_without_variant_records_high(mock_exec: MagicMock, tmp_path: Path):
    argv = ["--model", DEEPSEEK, "--preamble", str(_preamble(tmp_path)), "--no-commit-notice"]
    assert main(argv) == 0

    env = mock_exec.call_args[0][2]
    assert _model_state(Path(env[OPENCODE_STATE_HOME_ENV]))["variant"] == {DEEPSEEK: "high"}


@pytest.mark.usefixtures("_isolated_worker")
@patch("scripts.orca_opencode_launch.os.execvpe")
def test_main_with_explicit_low_records_low(mock_exec: MagicMock, tmp_path: Path):
    argv = [
        "--model",
        DEEPSEEK,
        "--preamble",
        str(_preamble(tmp_path)),
        "--variant",
        "low",
        "--no-commit-notice",
    ]
    assert main(argv) == 0

    env = mock_exec.call_args[0][2]
    assert _model_state(Path(env[OPENCODE_STATE_HOME_ENV]))["variant"] == {DEEPSEEK: "low"}
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"])["agent"]["build"]["variant"] == "low"


@pytest.mark.usefixtures("_isolated_worker")
def test_other_launch_paths_do_not_pin_state(tmp_path: Path):
    assert OPENCODE_STATE_HOME_ENV not in build_env({}, UNREGISTERED)
    assert OPENCODE_STATE_HOME_ENV not in build_env({}, UNREGISTERED, variant="high")
    assert OPENCODE_STATE_HOME_ENV not in build_env({}, DEEPSEEK, variant="high", one_shot=True)
    assert OPENCODE_STATE_HOME_ENV not in build_env(
        {}, "openrouter/stealth/space-bunny-alpha", binary="kilo", variant="max"
    )
    assert not (tmp_path / "worktree" / ORCA_WORKER_STATE_DIR).exists()


@pytest.mark.usefixtures("_isolated_worker")
def test_pinning_never_touches_global_state_or_other_xdg_dirs(tmp_path: Path):
    env = build_env(
        {"PATH": "/bin", "XDG_STATE_HOME": str(tmp_path / "global-state")}, DEEPSEEK, variant="max"
    )

    state_home = Path(env[OPENCODE_STATE_HOME_ENV])
    assert state_home != tmp_path / "global-state"
    assert state_home.is_relative_to(tmp_path / "worktree")
    assert "XDG_DATA_HOME" not in env
    assert "XDG_CONFIG_HOME" not in env
    assert not (tmp_path / "home").exists()
    assert not (tmp_path / "global-state").exists()


@pytest.mark.usefixtures("_isolated_worker")
def test_config_agent_variant_injection_is_preserved():
    env = build_env({}, GLM, variant="low", role="reviewer")

    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["model"] == GLM
    assert config["agent"]["build"] == {"model": GLM, "variant": "low", "steps": 150}
    assert config["tool_output"] == {"max_lines": 400, "max_bytes": 16384}


def test_registered_models_are_the_only_pinned_targets():
    assert set(OPENCODE_MODEL_VARIANTS) == {DEEPSEEK, GLM}
