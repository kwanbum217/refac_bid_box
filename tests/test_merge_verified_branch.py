from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.merge_verified_branch import merge_verified_branch


def _write_evidence(path: Path, **overrides: object) -> Path:
    evidence = {
        "strict": True,
        "exit_code": 0,
        "level1": {"verdict": "pass", "exit_code": 0},
        "reviewer": {"effective_verdict": "pass"},
    }
    evidence.update(overrides)
    path.write_text(json.dumps(evidence), encoding="utf-8")
    return path


def _runner(calls: list[list[str]], current: str = "main"):
    def run(command):
        calls.append(list(command))
        if command == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, current + "\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def test_merge_rejected_without_strict_evidence_never_calls_git_merge(tmp_path: Path):
    evidence = _write_evidence(tmp_path / "finalize.json", strict=False)
    calls: list[list[str]] = []

    code, _ = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        runner=_runner(calls),
    )

    assert code == 1
    assert not any(command[:2] == ["git", "merge"] for command in calls)


def test_merge_rejected_without_level1_pass_never_calls_git_merge(tmp_path: Path):
    evidence = _write_evidence(tmp_path / "finalize.json", level1={"verdict": "fail"})
    calls: list[list[str]] = []

    code, _ = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        runner=_runner(calls),
    )

    assert code == 1
    assert not any(command[:2] == ["git", "merge"] for command in calls)


def test_merge_rejected_when_evidence_is_missing_never_calls_git_merge(tmp_path: Path):
    calls: list[list[str]] = []

    code, _ = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=tmp_path / "missing.json",
        runner=_runner(calls),
    )

    assert code == 1
    assert not any(command[:2] == ["git", "merge"] for command in calls)


def test_merge_runs_only_after_complete_evidence_and_on_target_branch(tmp_path: Path):
    evidence = _write_evidence(tmp_path / "finalize.json")
    calls: list[list[str]] = []

    code, _ = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        message="merge: verified example",
        runner=_runner(calls),
    )

    assert code == 0
    assert calls == [
        ["git", "branch", "--show-current"],
        ["git", "merge", "--no-ff", "feature/example", "-m", "merge: verified example"],
    ]
