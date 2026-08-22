from __future__ import annotations

import json
import subprocess
from pathlib import Path

from scripts.merge_verified_branch import merge_verified_branch


def _write_evidence(path: Path, **overrides: object) -> Path:
    evidence = {
        "execution_mode": "strict",
        "source_branch": "feature/example",
        "target_branch": "main",
        "commit": "a" * 40,
        "target_commit": "c" * 40,
        "exit_code": 0,
        "level1": {"verdict": "pass", "exit_code": 0},
        "reviewer": {"effective_verdict": "pass"},
    }
    evidence.update(overrides)
    path.write_text(json.dumps(evidence), encoding="utf-8")
    return path


def _runner(calls: list[list[str]], current: str = "main", target_sha: str = "c" * 40):
    def run(command):
        calls.append(list(command))
        if command == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, current + "\n", "")
        if command == ["git", "rev-parse", "--verify", "feature/example^{commit}"]:
            return subprocess.CompletedProcess(command, 0, "a" * 40 + "\n", "")
        if command == ["git", "rev-parse", "--verify", "main^{commit}"]:
            return subprocess.CompletedProcess(command, 0, target_sha + "\n", "")
        return subprocess.CompletedProcess(command, 0, "", "")

    return run


def test_merge_rejected_without_strict_execution_mode_never_calls_git_merge(tmp_path: Path):
    evidence = _write_evidence(tmp_path / "finalize.json", execution_mode="allow_skipped_gates")
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


def test_merge_rejected_when_evidence_ref_is_reused_never_calls_git_merge(tmp_path: Path):
    evidence = _write_evidence(tmp_path / "finalize.json", commit="b" * 40)
    calls: list[list[str]] = []

    code, _ = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        runner=_runner(calls),
    )

    assert code == 1
    assert not any(command[:2] == ["git", "merge"] for command in calls)


def test_merge_rejected_when_evidence_branch_binding_differs_never_calls_git_merge(tmp_path: Path):
    evidence = _write_evidence(tmp_path / "finalize.json", target_branch="release")
    calls: list[list[str]] = []

    code, _ = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        runner=_runner(calls),
    )

    assert code == 1
    assert not any(command[:2] == ["git", "merge"] for command in calls)


def test_merge_rejected_when_target_commit_is_missing_never_calls_git_merge(tmp_path: Path):
    evidence_file = tmp_path / "finalize.json"
    evidence_data = {
        "execution_mode": "strict",
        "source_branch": "feature/example",
        "target_branch": "main",
        "commit": "a" * 40,
        "exit_code": 0,
        "level1": {"verdict": "pass", "exit_code": 0},
        "reviewer": {"effective_verdict": "pass"},
    }
    evidence_file.write_text(json.dumps(evidence_data), encoding="utf-8")
    calls: list[list[str]] = []

    code, output = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence_file,
        runner=_runner(calls),
    )

    assert code == 1
    assert "target_commit" in output
    assert not any(command[:2] == ["git", "merge"] for command in calls)


def test_merge_rejected_when_target_commit_is_blank_never_calls_git_merge(tmp_path: Path):
    evidence = _write_evidence(tmp_path / "finalize.json", target_commit="   ")
    calls: list[list[str]] = []

    code, output = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        runner=_runner(calls),
    )

    assert code == 1
    assert "target_commit" in output
    assert not any(command[:2] == ["git", "merge"] for command in calls)


def test_merge_rejected_when_target_sha_has_advanced_never_calls_git_merge(tmp_path: Path):
    evidence = _write_evidence(tmp_path / "finalize.json", target_commit="c" * 40)
    calls: list[list[str]] = []

    code, output = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        runner=_runner(calls, target_sha="d" * 40),
    )

    assert code == 1
    assert "target_commit" in output
    assert not any(command[:2] == ["git", "merge"] for command in calls)


def test_merge_accepts_actual_reviewer_declared_verdict_contract(tmp_path: Path):
    evidence = _write_evidence(
        tmp_path / "finalize.json",
        reviewer={"declared_verdict": "pass"},
    )
    calls: list[list[str]] = []

    code, _ = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        runner=_runner(calls),
    )

    assert code == 0
    assert any(command[:2] == ["git", "merge"] for command in calls)


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
        ["git", "rev-parse", "--verify", "feature/example^{commit}"],
        ["git", "rev-parse", "--verify", "main^{commit}"],
        ["git", "branch", "--show-current"],
        ["git", "merge", "--no-ff", "a" * 40, "-m", "merge: verified example"],
    ]


def test_merge_uses_verified_commit_when_source_ref_advances_before_merge(tmp_path: Path):
    verified_commit = "a" * 40
    advanced_commit = "b" * 40
    evidence = _write_evidence(tmp_path / "finalize.json", commit=verified_commit)
    calls: list[list[str]] = []

    def runner(command):
        calls.append(list(command))
        if command == ["git", "rev-parse", "--verify", "feature/example^{commit}"]:
            return subprocess.CompletedProcess(command, 0, verified_commit + "\n", "")
        if command == ["git", "rev-parse", "--verify", "main^{commit}"]:
            return subprocess.CompletedProcess(command, 0, "c" * 40 + "\n", "")
        if command == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(command, 0, "main\n", "")
        if command[:3] == ["git", "merge", "--no-ff"]:
            assert command[3] == verified_commit
            assert command[3] != advanced_commit
        return subprocess.CompletedProcess(command, 0, "", "")

    code, _ = merge_verified_branch(
        source_branch="feature/example",
        target_branch="main",
        evidence_path=evidence,
        runner=runner,
    )

    assert code == 0
    assert calls[-1] == ["git", "merge", "--no-ff", verified_commit]
