"""2026-11-25 게이트 11 판정 원장 시험.

strict pass 증거가 기록될 때 게이트 11 판정을 .cache/gate11_verdicts.jsonl 에
한 줄씩 덧붙여 판정 추이를 소급 실행 없이 볼 수 있어야 합니다. 원장 쓰기는
판정·증거 기록 결과를 바꾸지 않아야 하고, strict fail 에서는 쓰이지 않아야 합니다.
"""

from __future__ import annotations

import datetime
import json
import shutil
import subprocess
from pathlib import Path

import pytest

GIT_BIN = shutil.which("git") or "git"


@pytest.fixture(autouse=True)
def mock_subprocesses(monkeypatch):
    """비-git 하위 프로세스 호출(pytest, validate_agent_rules, ruff)을 mock 합니다.

    게이트 11 은 subprocess.run 을 직접 쓰므로 실제 pytest 가 임시 트리에서 돕니다.
    """
    from scripts import orca_level1_gate

    orig_run_command_safe = orca_level1_gate.run_command_safe

    def mock_run_command_safe(cmd, cwd, timeout):
        cmd_str = " ".join(str(c) for c in cmd)
        if cmd and "git" in Path(str(cmd[0])).name:
            return orig_run_command_safe(cmd, cwd, timeout)
        if "ruff" in cmd_str:
            return 0, "All checks passed!", "", False
        if "validate_agent_rules.py" in cmd_str:
            return 0, "검증 통과: 12/12 건.", "", False
        if "pytest" in cmd_str:
            return 0, "1 passed in 0.01s", "", False
        if "mypy" in cmd_str:
            return 0, "Success: no issues found in 24 source files", "", False
        return orig_run_command_safe(cmd, cwd, timeout)

    monkeypatch.setattr(orca_level1_gate, "run_command_safe", mock_run_command_safe)


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(  # noqa: S603
        [GIT_BIN, *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )


def _commit(repo: Path, message: str) -> None:
    _git(repo, "add", ".")
    _git(
        repo,
        "-c",
        "user.email=test@example.com",
        "-c",
        "user.name=Test",
        "commit",
        "-m",
        message,
    )


def _init_repo(tmp_path: Path) -> Path:
    """main 커밋 하나를 가진 최소 저장소를 만듭니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    (repo / "common.txt").write_text("common line 1\n", encoding="utf-8")
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "validate_agent_rules.py").write_text(
        "print('검증 통과: 12/12 건.')\n", encoding="utf-8"
    )
    _commit(repo, "chore: 초기 베이스 커밋")
    return repo


def _init_proven_repo(tmp_path: Path) -> tuple[Path, str, Path]:
    """기준 코드에서 실패하고 브랜치에서 통과하는 시험을 가진 저장소를 만듭니다."""
    repo = _init_repo(tmp_path)
    branch = "feature-branch"
    _git(repo, "checkout", "-b", branch)
    (repo / "common.txt").write_text("common line 1\nmodified line 2\n", encoding="utf-8")
    (repo / "unique_new.txt").write_text("new file on branch\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_gate11_probe.py").write_text(
        "from pathlib import Path\n"
        "\n"
        "\n"
        "def test_probe() -> None:\n"
        '    assert Path("unique_new.txt").exists()\n',
        encoding="utf-8",
    )
    _commit(repo, "fix: 고유 파일과 기준 실패 시험을 함께 추가한다")

    capsule = tmp_path / "capsule.yaml"
    capsule.write_text(
        "\n".join(
            [
                "schema: ORCA_TASK_CAPSULE_V2",
                "tdd: required",
                "allowed_write_files:",
                '  - "common.txt"',
                '  - "unique_new.txt"',
                '  - "tests/test_gate11_probe.py"',
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return repo, branch, capsule


def _ledger_entries(repo: Path) -> list[dict]:
    ledger_path = repo / ".cache" / "gate11_verdicts.jsonl"
    assert ledger_path.exists()
    return [json.loads(line) for line in ledger_path.read_text(encoding="utf-8").splitlines()]


def test_strict_pass_appends_gate11_verdict(tmp_path: Path):
    """(a) strict pass + 증거 기록 성공이면 원장에 한 줄이 늘고 필드가 채워집니다."""
    from scripts.orca_level1_gate import run_level1_gate

    repo, branch, capsule = _init_proven_repo(tmp_path)

    code, output = run_level1_gate(
        base="main",
        branch=branch,
        repo=repo,
        capsule=capsule,
        tests=["tests/test_gate11_probe.py -q"],
        as_json=True,
        strict=True,
        record_evidence=True,
    )

    data = json.loads(output)
    assert code == 0
    assert data["verdict"] == "pass"
    assert data["evidence"]["recorded"] is True

    entries = _ledger_entries(repo)
    assert len(entries) == 1
    entry = entries[0]
    expected_commit = _git(repo, "rev-parse", branch).stdout.strip()
    assert entry["branch"] == branch
    assert entry["base"] == "main"
    assert entry["commit"] == expected_commit
    assert entry["capsule"] == str(capsule.resolve())
    assert entry["tdd"] == "required"
    assert entry["verdict"] == "proven"
    assert entry["status"] == "pass"
    assert entry["base_failed"] == 1
    assert entry["base_errors"] == 0
    assert entry["target_files"] == 1
    assert datetime.datetime.fromisoformat(entry["recorded_at"]).tzinfo is not None


def test_strict_fail_leaves_ledger_untouched(tmp_path: Path):
    """(b) strict fail 이면 원장을 쓰지 않고 기존 내용도 건드리지 않습니다."""
    from scripts.orca_level1_gate import run_level1_gate

    repo = _init_repo(tmp_path)
    branch = "feature-branch"
    _git(repo, "checkout", "-b", branch)
    (repo / "common.txt").write_text("common line 1\nmodified\n", encoding="utf-8")
    (repo / "unique_new.txt").write_text("new file on branch\n", encoding="utf-8")
    _commit(repo, "fix: 범위를 벗어난 변경을 반영한다")
    capsule = tmp_path / "capsule.yaml"
    capsule.write_text(
        'schema: ORCA_TASK_CAPSULE_V2\nallowed_write_files:\n  - "docs/note.md"\n',
        encoding="utf-8",
    )
    ledger_path = repo / ".cache" / "gate11_verdicts.jsonl"
    ledger_path.parent.mkdir(parents=True)
    previous = '{"schema": "SENTINEL"}\n'
    ledger_path.write_text(previous, encoding="utf-8")

    code, output = run_level1_gate(
        base="main",
        branch=branch,
        repo=repo,
        capsule=capsule,
        as_json=True,
        strict=True,
        record_evidence=True,
    )

    data = json.loads(output)
    assert code == 1
    assert data["verdict"] == "fail"
    assert data["evidence"]["recorded"] is False
    assert ledger_path.read_text(encoding="utf-8") == previous


def test_missing_gate11_records_not_run(tmp_path: Path):
    """(c) 게이트 11 이 돌지 않았으면 원장에 not_run 으로 남깁니다."""
    from scripts.orca_level1_gate import record_strict_evidence

    repo = _init_repo(tmp_path)

    code, note = record_strict_evidence(
        repo=repo,
        branch="main",
        base="main",
        capsule=None,
    )

    assert code == 0
    assert "증거 기록 완료" in note
    entries = _ledger_entries(repo)
    assert len(entries) == 1
    assert entries[0]["verdict"] == "not_run"
    assert entries[0]["status"] == "not_run"
    assert entries[0]["tdd"] == "unspecified"
    assert entries[0]["target_files"] == 0


def test_ledger_write_failure_keeps_evidence_result(tmp_path: Path):
    """(d) 원장 쓰기 예외가 나도 종료 코드와 증거 기록 결과는 그대로입니다."""
    from scripts.orca_level1_gate import record_strict_evidence

    repo = _init_repo(tmp_path)
    ledger_path = repo / ".cache" / "gate11_verdicts.jsonl"
    ledger_path.mkdir(parents=True)

    code, note = record_strict_evidence(
        repo=repo,
        branch="main",
        base="main",
        capsule=None,
    )

    assert code == 0
    assert "원장 기록 실패" in note
    evidence_path = repo / ".cache" / "level1_strict_evidence.json"
    evidence = json.loads(evidence_path.read_text(encoding="utf-8"))
    assert evidence["verdict"] == "pass"
