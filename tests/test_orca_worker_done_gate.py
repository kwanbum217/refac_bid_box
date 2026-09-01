from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.orca_contract import (
    verify_branch_exists,
    verify_changed_files_match,
    verify_commit_exists,
)
from scripts.orca_level1_gate import run_level1_gate
from scripts.orca_taskctl import finalize_task
from scripts.summarize_worker_done import summarize_worker_report

GIT_BIN = shutil.which("git") or "/usr/bin/git"


@pytest.fixture(autouse=True)
def mock_subprocesses(monkeypatch):
    """비-git 하위 프로세스 호출(pytest, validate_agent_rules, ruff, summarize/level1 subprocess)을 mock 하여 테스트 속도를 높입니다."""
    import subprocess as real_subprocess

    from scripts import orca_contract, orca_level1_gate, orca_taskctl

    orig_run_command_safe = orca_level1_gate.run_command_safe
    orig_subprocess_run = real_subprocess.run
    orig_taskctl_run = orca_taskctl._run_command

    def mock_run_command_safe(cmd, cwd, timeout):
        cmd_str = " ".join(str(c) for c in cmd)
        if cmd and "git" in Path(str(cmd[0])).name:
            return orig_run_command_safe(cmd, cwd, timeout)
        if "pytest" in cmd_str:
            return 0, "1 passed in 0.01s", "", False
        if "validate_agent_rules.py" in cmd_str:
            return 0, "검증 통과: 12/12 건.", "", False
        if "ruff" in cmd_str:
            return 0, "All checks passed!", "", False
        return orig_run_command_safe(cmd, cwd, timeout)

    class MockCompletedProc:
        def __init__(self, returncode: int, stdout: str, stderr: str = ""):
            self.returncode = returncode
            self.stdout = stdout
            self.stderr = stderr

    def mock_contract_subprocess_run(cmd, *args, **kwargs):
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if isinstance(cmd, (list, tuple)) and cmd and "git" in Path(str(cmd[0])).name:
            return orig_subprocess_run(cmd, *args, **kwargs)
        if "pytest" in cmd_str:
            return MockCompletedProc(0, "1 passed in 0.01s", "")
        if "validate_agent_rules.py" in cmd_str:
            return MockCompletedProc(0, "검증 통과: 12/12 건.", "")
        return orig_subprocess_run(cmd, *args, **kwargs)

    def mock_run_command_taskctl(cmd, cwd=None, timeout=30):
        cmd_str = " ".join(str(c) for c in cmd)
        if "summarize_worker_done.py" in cmd_str:
            report = None
            capsule = None
            repo = None
            idx = 0
            while idx < len(cmd):
                if cmd[idx] == "--report":
                    report = Path(cmd[idx + 1])
                    idx += 2
                    continue
                if cmd[idx] == "--capsule":
                    capsule = Path(cmd[idx + 1])
                    idx += 2
                    continue
                if cmd[idx] == "--repo":
                    repo = Path(cmd[idx + 1])
                    idx += 2
                    continue
                idx += 1
            res = summarize_worker_report(report, capsule_path=capsule, repo_path=repo)
            return res["exit_code"], json.dumps(res), ""

        if "orca_level1_gate.py" in cmd_str:
            base = "main"
            branch = "HEAD"
            repo = Path(".")
            capsule = None
            report = None
            strict = "--strict" in cmd
            idx = 0
            while idx < len(cmd):
                if cmd[idx] == "--base":
                    base = cmd[idx + 1]
                    idx += 2
                    continue
                if cmd[idx] == "--branch":
                    branch = cmd[idx + 1]
                    idx += 2
                    continue
                if cmd[idx] == "--repo":
                    repo = Path(cmd[idx + 1])
                    idx += 2
                    continue
                if cmd[idx] == "--capsule":
                    capsule = Path(cmd[idx + 1])
                    idx += 2
                    continue
                if cmd[idx] == "--report":
                    report = Path(cmd[idx + 1])
                    idx += 2
                    continue
                idx += 1
            code, out = run_level1_gate(
                base=base,
                branch=branch,
                repo=repo,
                capsule=capsule,
                report=report,
                as_json=True,
                strict=strict,
            )
            return code, out, ""

        return orig_taskctl_run(cmd, cwd=cwd, timeout=timeout)

    monkeypatch.setattr(orca_level1_gate, "run_command_safe", mock_run_command_safe)
    monkeypatch.setattr(orca_contract.subprocess, "run", mock_contract_subprocess_run)
    monkeypatch.setattr(orca_taskctl, "_run_command", mock_run_command_taskctl)


def _init_git_repo(tmp_path: Path) -> tuple[Path, str, str, str]:
    """테스트용 임시 git 저장소를 생성합니다.

    반환값: (repo_path, base_ref, branch_name, head_commit_sha)
    """
    repo = tmp_path / "repo"
    repo.mkdir()

    subprocess.run(  # noqa: S603
        [GIT_BIN, "init", "-b", "main"],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    # 1. Base 커밋
    scripts_dir = repo / "scripts"
    scripts_dir.mkdir()
    (scripts_dir / "validate_agent_rules.py").write_text(
        "print('검증 통과: 12/12 건.')\n", encoding="utf-8"
    )
    (repo / "base.txt").write_text("base content\n", encoding="utf-8")
    subprocess.run([GIT_BIN, "add", "."], cwd=str(repo), check=True, capture_output=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [
            GIT_BIN,
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "chore: initial base commit",
        ],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    # 2. 작업 브랜치 생성 및 파일 변경
    branch = "feature/truth-gate"
    subprocess.run(  # noqa: S603
        [GIT_BIN, "checkout", "-b", branch],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )
    src_dir = repo / "src"
    src_dir.mkdir()
    (src_dir / "app.py").write_text("def run():\n    return True\n", encoding="utf-8")
    tests_dir = repo / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_app.py").write_text("def test_run():\n    assert True\n", encoding="utf-8")
    subprocess.run([GIT_BIN, "add", "."], cwd=str(repo), check=True, capture_output=True)  # noqa: S603
    subprocess.run(  # noqa: S603
        [
            GIT_BIN,
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            "feat: implement truth gate logic",
        ],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )

    rev_proc = subprocess.run(  # noqa: S603
        [GIT_BIN, "rev-parse", "HEAD"],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )
    head_sha = rev_proc.stdout.strip()

    return repo, "main", branch, head_sha


def _create_capsule(
    repo: Path,
    report_rel_path: str,
    allowed_writes: list[str] | None = None,
) -> Path:
    """테스트용 Capsule 파일을 생성합니다."""
    if allowed_writes is None:
        allowed_writes = ["src/app.py", "tests/test_app.py"]
    capsule_dir = repo / ".orca" / "capsules" / "task_test"
    capsule_dir.mkdir(parents=True, exist_ok=True)
    capsule_path = capsule_dir / "capsule.yaml"

    lines = [
        "schema: ORCA_TASK_CAPSULE_V2",
        "version: '2.1.0'",
        "task_id: 'task_test123'",
        f"report_path: '{report_rel_path}'",
        "allowed_write_files:",
    ]
    for w in allowed_writes:
        lines.append(f"  - '{w}'")
    lines.append("verification_commands:")
    lines.append("  - 'uv run pytest tests/test_app.py -q'")

    capsule_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return capsule_path


def _create_report(
    repo: Path,
    report_rel_path: str,
    branch: str,
    commit: str,
    commit_count: int = 1,
    changed_files: list[str] | None = None,
    status: str = "succeeded",
    verdict: str = "candidate",
    blocking_issues: list[str] | None = None,
) -> Path:
    """테스트용 worker_done 보고 JSON 을 생성합니다."""
    if changed_files is None:
        changed_files = ["src/app.py", "tests/test_app.py"]
    if blocking_issues is None:
        blocking_issues = []

    report_path = repo / report_rel_path
    report_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "schema": "ORCA_WORKER_DONE_V2",
        "version": "2.1.0",
        "task_id": "task_test123",
        "status": status,
        "branch": branch,
        "commit": commit,
        "commit_count": commit_count,
        "changed_files": changed_files,
        "read_files": ["scripts/orca_contract.py"],
        "verification": [
            {
                "command": "uv run pytest tests/test_app.py -q",
                "result": "1 passed",
            }
        ],
        "verdict": verdict,
        "blocking_issues": blocking_issues,
    }
    report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# (a) 보고 파일 없음이면 FAIL
# ---------------------------------------------------------------------------
def test_missing_report_fails_level1_gate(tmp_path: Path):
    """보고 파일이 실제로 존재하지 않으면 Level 1 게이트 6 이 FAIL 되고 전체 판정이 FAIL 이 된다."""
    repo, base, branch, _sha = _init_git_repo(tmp_path)
    report_rel = ".orca/capsules/task_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)

    # 보고서 파일을 생성하지 않고 Level 1 실행
    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule_path,
        as_json=True,
    )
    assert code == 1
    data = json.loads(output)
    assert data["verdict"] == "fail"
    g6 = data["gates"]["gate6_worker_done"]
    assert g6["status"] == "fail"
    assert "worker_done 보고 파일 없음" in g6["summary"]


# ---------------------------------------------------------------------------
# (b) 존재하지 않는 commit SHA 를 적으면 FAIL
# ---------------------------------------------------------------------------
def test_nonexistent_commit_sha_fails(tmp_path: Path):
    """존재하지 않는 가짜 commit SHA 를 보고서에 적으면 진실성 검증에서 잡힌다."""
    repo, base, branch, _sha = _init_git_repo(tmp_path)
    fake_sha = "deadbeef11112222333344445555666677778888"

    # 1. 헬퍼 직접 검증
    ok, reason = verify_commit_exists(repo, fake_sha)
    assert ok is False
    assert "실존성 검증 실패" in reason

    # 2. summarize_worker_done 검증
    report_rel = ".orca/capsules/task_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)
    report_path = _create_report(repo, report_rel, branch, commit=fake_sha)

    summ = summarize_worker_report(report_path, capsule_path=capsule_path, repo_path=repo)
    assert summ["exit_code"] == 1
    assert summ["effective_verdict"] == "blocked"
    assert any("commit SHA" in v for v in summ["violations"])

    # 3. Level 1 게이트 검증
    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule_path,
        as_json=True,
    )
    assert code == 1
    data = json.loads(output)
    assert data["verdict"] == "fail"
    assert data["gates"]["gate6_worker_done"]["status"] == "fail"


# ---------------------------------------------------------------------------
# (c) 존재하지 않는 브랜치면 FAIL
# ---------------------------------------------------------------------------
def test_nonexistent_branch_fails(tmp_path: Path):
    """존재하지 않는 가짜 브랜치명을 보고서에 적으면 진실성 검증에서 잡힌다."""
    repo, base, branch, sha = _init_git_repo(tmp_path)
    fake_branch = "feature/nonexistent-branch-name"

    # 1. 헬퍼 직접 검증
    ok, reason = verify_branch_exists(repo, fake_branch)
    assert ok is False
    assert "실존성 검증 실패" in reason

    # 2. summarize_worker_done 검증
    report_rel = ".orca/capsules/task_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)
    report_path = _create_report(repo, report_rel, branch=fake_branch, commit=sha)

    summ = summarize_worker_report(report_path, capsule_path=capsule_path, repo_path=repo)
    assert summ["exit_code"] == 1
    assert summ["effective_verdict"] == "blocked"
    assert any("브랜치" in v for v in summ["violations"])

    # 3. Level 1 게이트 검증
    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule_path,
        as_json=True,
    )
    assert code == 1
    data = json.loads(output)
    assert data["verdict"] == "fail"
    assert data["gates"]["gate6_worker_done"]["status"] == "fail"


# ---------------------------------------------------------------------------
# (d) changed_files 가 실제 diff 와 다르면 FAIL
# ---------------------------------------------------------------------------
def test_changed_files_mismatch_fails_gate_and_finalize(tmp_path: Path):
    """보고서의 changed_files 가 실제 git diff 와 일치하지 않으면 게이트와 finalize 가 실패한다."""
    repo, base, branch, sha = _init_git_repo(tmp_path)
    # 실제 변경은 ["src/app.py", "tests/test_app.py"] 인데 허위로 ["src/other.py"] 만 보고
    falsified_changed = ["src/other.py"]

    # 1. 헬퍼 직접 검증
    ok, reason = verify_changed_files_match(repo, base, branch, falsified_changed)
    assert ok is False
    assert "changed_files 불일치" in reason

    # 2. Level 1 게이트 검증
    report_rel = ".orca/capsules/task_test/worker_done.json"
    capsule_path = _create_capsule(
        repo, report_rel, allowed_writes=["src/app.py", "tests/test_app.py", "src/other.py"]
    )
    report_path = _create_report(
        repo, report_rel, branch=branch, commit=sha, changed_files=falsified_changed
    )

    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule_path,
        as_json=True,
    )
    assert code == 1
    data = json.loads(output)
    assert data["verdict"] == "fail"
    assert data["gates"]["gate6_worker_done"]["status"] == "fail"

    # 3. finalize_task 검증
    final_res = finalize_task(
        report_path=report_path,
        capsule_path=capsule_path,
        repo=repo,
        base=base,
        branch=branch,
        strict=False,
    )
    assert final_res["exit_code"] == 1
    assert "changed_files_mismatch" in final_res


# ---------------------------------------------------------------------------
# (e) 정상 보고는 PASS
# ---------------------------------------------------------------------------
def test_valid_report_passes(tmp_path: Path):
    """올바른 commit SHA, 올바른 브랜치, 일치하는 changed_files 를 담은 정상 보고는 모두 PASS 한다."""
    repo, base, branch, sha = _init_git_repo(tmp_path)
    report_rel = ".orca/capsules/task_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)
    report_path = _create_report(
        repo,
        report_rel,
        branch=branch,
        commit=sha,
        changed_files=["src/app.py", "tests/test_app.py"],
    )

    # 1. summarize 검증
    summ = summarize_worker_report(report_path, capsule_path=capsule_path, repo_path=repo)
    assert summ["exit_code"] == 0
    assert summ["violations"] == []
    assert summ["effective_verdict"] == "candidate"

    # 2. Level 1 게이트 검증
    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule_path,
        tests=["tests/test_app.py -q"],
        as_json=True,
    )
    assert code == 0
    data = json.loads(output)
    assert data["verdict"] == "pass"
    assert data["gates"]["gate6_worker_done"]["status"] == "pass"

    # 3. finalize_task 검증
    final_res = finalize_task(
        report_path=report_path,
        capsule_path=capsule_path,
        repo=repo,
        base=base,
        branch=branch,
        strict=False,
    )
    assert final_res["exit_code"] == 0


# ---------------------------------------------------------------------------
# (f) --allow-missing-report 명시 시에만 우회
# ---------------------------------------------------------------------------
def test_allow_missing_report_bypasses(tmp_path: Path):
    """--allow-missing-report 명시 시에만 보고서 부재가 PASS/SKIPPED 로 처리된다."""
    repo, base, branch, _sha = _init_git_repo(tmp_path)
    report_rel = ".orca/capsules/task_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)

    # 보고서 파일 없는 상태에서 allow_missing_report=True 지정
    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule_path,
        tests=["tests/test_app.py -q"],
        allow_missing_report=True,
        as_json=True,
    )
    assert code == 0
    data = json.loads(output)
    assert data["verdict"] == "pass"
    g6 = data["gates"]["gate6_worker_done"]
    assert g6["status"] == "skipped"
    assert g6["required"] is False
