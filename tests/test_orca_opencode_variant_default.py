"""opencode Go 워커 모델의 대화형 variant 기본값(high)과 Task 별 조정을 검증합니다."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from scripts.orca_opencode_launch import (
    OPENCODE_DEFAULT_VARIANT,
    OPENCODE_MODEL_VARIANTS,
    build_command,
    build_env,
    main,
    resolve_variant,
)

DEEPSEEK = "opencode-go/deepseek-v4.1-flash"
GLM = "opencode-go/glm-5.3-flash"


def _preamble(tmp_path: Path) -> Path:
    target = tmp_path / "preamble_variant_default.txt"
    target.write_text("지시문", encoding="utf-8")
    return target


def test_registered_models_expose_low_high_max_and_default_high():
    assert OPENCODE_DEFAULT_VARIANT == "high"
    for model in (DEEPSEEK, GLM):
        assert OPENCODE_MODEL_VARIANTS[model] == ("low", "high", "max")


@pytest.mark.parametrize("model", [DEEPSEEK, GLM])
def test_resolve_variant_defaults_to_high_for_registered_models(model: str):
    assert resolve_variant(model, None, binary="opencode", one_shot=False) == "high"


def test_resolve_variant_keeps_explicit_choice_and_rejects_unlisted_value():
    assert resolve_variant(DEEPSEEK, "max", binary="opencode", one_shot=False) == "max"
    assert resolve_variant(GLM, "low", binary="opencode", one_shot=False) == "low"
    with pytest.raises(ValueError):
        resolve_variant(DEEPSEEK, "medium", binary="opencode", one_shot=False)


def test_resolve_variant_leaves_other_models_and_kilo_unchanged():
    assert (
        resolve_variant("opencode/space-bunny-free", None, binary="opencode", one_shot=False)
        is None
    )
    assert resolve_variant(DEEPSEEK, None, binary="kilo", one_shot=False) is None


def test_build_env_pins_variant_on_build_agent():
    env = build_env({"PATH": "/bin"}, DEEPSEEK, variant="high")
    config = json.loads(env["OPENCODE_CONFIG_CONTENT"])
    assert config["model"] == DEEPSEEK
    assert config["agent"]["build"] == {"model": DEEPSEEK, "variant": "high"}


def test_build_command_allows_interactive_variant_only_for_registered_models():
    assert build_command(GLM, "지시문", variant="high") == [
        "opencode",
        "--standalone",
        "--prompt",
        "지시문",
    ]
    with pytest.raises(ValueError):
        build_command("opencode/space-bunny-free", "지시문", variant="high")


@patch("scripts.orca_opencode_launch.os.execvpe")
def test_main_defaults_registered_model_to_high(mock_exec: MagicMock, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    assert (
        main(["--model", DEEPSEEK, "--preamble", str(_preamble(tmp_path)), "--no-commit-notice"])
        == 0
    )
    env = mock_exec.call_args[0][2]
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"])["agent"]["build"]["variant"] == "high"


@patch("scripts.orca_opencode_launch.os.execvpe")
def test_main_accepts_task_specific_variant(mock_exec: MagicMock, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    argv = ["--model", GLM, "--preamble", str(_preamble(tmp_path)), "--variant", "low"]
    assert main([*argv, "--no-commit-notice"]) == 0
    env = mock_exec.call_args[0][2]
    assert json.loads(env["OPENCODE_CONFIG_CONTENT"])["agent"]["build"]["variant"] == "low"


def test_main_rejects_variant_the_model_does_not_offer(tmp_path: Path):
    with pytest.raises(SystemExit) as exc:
        main(["--model", DEEPSEEK, "--preamble", str(_preamble(tmp_path)), "--variant", "medium"])
    assert exc.value.code == 2


def test_build_env_adds_worker_profile_for_registered_models_only():
    config = json.loads(build_env({}, DEEPSEEK, variant="high")["OPENCODE_CONFIG_CONTENT"])
    assert config["tool_output"] == {"max_lines": 400, "max_bytes": 16384}
    assert config["compaction"]["buffer"] == 800000
    assert config["update"] == "disable"
    assert config["snapshots"] is False
    other = json.loads(build_env({}, "opencode/space-bunny-free")["OPENCODE_CONFIG_CONTENT"])
    assert other == {"model": "opencode/space-bunny-free"}


def test_build_env_caps_reviewer_steps_but_not_builder():
    reviewer = json.loads(
        build_env({}, GLM, variant="high", role="reviewer")["OPENCODE_CONFIG_CONTENT"]
    )
    assert reviewer["agent"]["build"]["steps"] == 150
    builder = json.loads(
        build_env({}, DEEPSEEK, variant="high", role="builder")["OPENCODE_CONFIG_CONTENT"]
    )
    assert "steps" not in builder["agent"]["build"]


@patch("scripts.orca_opencode_launch.os.execvpe")
def test_main_passes_role_to_profile(mock_exec: MagicMock, tmp_path: Path, monkeypatch):
    monkeypatch.delenv("OPENCODE_CONFIG_CONTENT", raising=False)
    argv = ["--model", GLM, "--preamble", str(_preamble(tmp_path)), "--role", "reviewer"]
    assert main([*argv, "--no-commit-notice"]) == 0
    config = json.loads(mock_exec.call_args[0][2]["OPENCODE_CONFIG_CONTENT"])
    assert config["agent"]["build"] == {"model": GLM, "variant": "high", "steps": 150}
