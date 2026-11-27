"""cmd_dispatch 의 터미널-워크트리 대조 시험.

--terminal 과 --worktree 를 함께 받았을 때 터미널이 실제로 속한 워크트리와
--worktree 값이 어긋나면 preamble/.handle 기록 전에 종료 코드 2 로 거부한다.
판정 불가는 경고 후 진행하고, 일치하면 기존 흐름을 그대로 유지한다.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from scripts.orca_taskctl import main

INTENT_TEXT = """schema: ORCA_TASK_INTENT_V1
role: builder
objective: >
  터미널-워크트리 대조 시험용 의도.
scope:
  - "scripts/orca_taskctl.py"
acceptance:
  - "pytest 통과"
risk: medium
context: >
  시험 전용.
"""


def _write_intent(tmp_path: Path) -> Path:
    intent_file = tmp_path / "intent.yaml"
    intent_file.write_text(INTENT_TEXT, encoding="utf-8")
    return intent_file


def _install_dispatch_mocks(
    monkeypatch: pytest.MonkeyPatch,
    *,
    terminal: str,
    actual_worktree: Path | None,
) -> dict[str, Any]:
    calls: dict[str, Any] = {}

    monkeypatch.setattr(
        "scripts.orca_taskctl.resolve_terminal_worktree",
        lambda *a, **k: actual_worktree,
    )
    monkeypatch.setattr("scripts.orca_taskctl.verify_skill_receipt", lambda: {"ok": True})
    monkeypatch.setattr(
        "scripts.orca_taskctl.check_write_concurrency", lambda *a, **k: {"allowed": True}
    )
    monkeypatch.setattr("scripts.orca_taskctl.approve_trust_prompt", lambda *a, **k: "approved")
    monkeypatch.setattr(
        "scripts.orca_taskctl.start_auto_approve", lambda t: (True, "/tmp/mock.log")
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl.enable_file_edit_auto_approve",
        lambda t, timeout=30, force=False: (True, "accept-edits"),
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl.verify_instruction_delivered", lambda *a, **k: "delivered"
    )
    monkeypatch.setattr(
        "scripts.orca_taskctl._deliver_capsule_notice",
        lambda *a, **k: {
            "status": "sent",
            "dispatch_id": "d1",
            "chars": 10,
            "delivery_probe": "ORCA_DELIVERY_PROBE_test",
        },
    )
    monkeypatch.setattr("scripts.orca_taskctl.time.sleep", lambda s: None)

    def mock_dispatch_worker(**kwargs: Any) -> tuple[int, str, str, list[str]]:
        calls["dispatch"] = kwargs
        return 0, json.dumps({"ok": True}), "", ["orca", "orchestration", "dispatch"]

    monkeypatch.setattr("scripts.orca_taskctl.dispatch_worker", mock_dispatch_worker)
    calls["terminal"] = terminal
    return calls


def _dispatch_argv(intent_file: Path, tmp_path: Path, terminal: str, worktree: Path) -> list[str]:
    return [
        "dispatch",
        "--intent",
        str(intent_file),
        "--capsule-dir",
        str(tmp_path / "capsules"),
        "--terminal",
        terminal,
        "--worktree",
        f"path:{worktree}",
        "--skip-settled-session-check",
    ]


def test_rejects_mismatched_terminal_worktree_before_side_effects(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """터미널 워크트리와 --worktree 가 다르면 2 로 거부하고 preamble/.handle 을 남기지 않는다."""
    terminal = "term_worktree_mismatch"
    actual_worktree = (tmp_path / "worktree_a").resolve()
    target_worktree = (tmp_path / "worktree_b").resolve()
    actual_worktree.mkdir(parents=True)
    target_worktree.mkdir(parents=True)
    # 실제 워크트리처럼 .git 을 둔다.
    (actual_worktree / ".git").mkdir()

    calls = _install_dispatch_mocks(monkeypatch, terminal=terminal, actual_worktree=actual_worktree)
    intent_file = _write_intent(tmp_path)

    code = main(_dispatch_argv(intent_file, tmp_path, terminal, target_worktree))

    assert code == 2
    captured = capsys.readouterr()
    assert "다릅니다" in captured.err
    assert str(actual_worktree) in captured.err
    assert str(target_worktree) in captured.err
    assert terminal in captured.err
    assert "dispatch" not in calls
    orca_dir = target_worktree / ".orca"
    assert list(orca_dir.glob("preamble_*.txt")) == []
    assert list(orca_dir.glob("*.handle")) == []


def test_unresolvable_terminal_worktree_warns_and_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """터미널 워크트리를 확인하지 못하면 경고만 남기고 Dispatch 를 계속한다."""
    terminal = "term_worktree_unknown"
    target_worktree = (tmp_path / "worktree_b").resolve()
    target_worktree.mkdir(parents=True)

    calls = _install_dispatch_mocks(monkeypatch, terminal=terminal, actual_worktree=None)
    intent_file = _write_intent(tmp_path)

    code = main(_dispatch_argv(intent_file, tmp_path, terminal, target_worktree))

    assert code == 0
    captured = capsys.readouterr()
    assert "워크트리를 확인하지 못했습니다" in captured.err
    assert "다릅니다" not in captured.err
    assert "dispatch" in calls


def test_stale_non_worktree_path_warns_and_proceeds(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """해석된 경로가 삭제되었거나 워크트리가 아니면 판정 불가로 경고 후 진행한다."""
    terminal = "term_worktree_stale"
    stale_worktree = (tmp_path / "deleted_worktree").resolve()
    target_worktree = (tmp_path / "worktree_b").resolve()
    target_worktree.mkdir(parents=True)

    calls = _install_dispatch_mocks(monkeypatch, terminal=terminal, actual_worktree=stale_worktree)
    intent_file = _write_intent(tmp_path)

    code = main(_dispatch_argv(intent_file, tmp_path, terminal, target_worktree))

    assert code == 0
    captured = capsys.readouterr()
    assert "워크트리를 확인하지 못했습니다" in captured.err
    assert "다릅니다" not in captured.err
    assert "dispatch" in calls


def test_matching_terminal_worktree_proceeds_without_rejection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
):
    """터미널 워크트리와 --worktree 가 같으면 거부 없이 기존 흐름을 유지한다."""
    terminal = "term_worktree_match"
    target_worktree = (tmp_path / "worktree_b").resolve()
    target_worktree.mkdir(parents=True)
    (target_worktree / ".git").mkdir()

    calls = _install_dispatch_mocks(monkeypatch, terminal=terminal, actual_worktree=target_worktree)
    intent_file = _write_intent(tmp_path)

    code = main(_dispatch_argv(intent_file, tmp_path, terminal, target_worktree))

    assert code == 0
    captured = capsys.readouterr()
    assert "다릅니다" not in captured.err
    assert "확인하지 못했습니다" not in captured.err
    assert "dispatch" in calls
