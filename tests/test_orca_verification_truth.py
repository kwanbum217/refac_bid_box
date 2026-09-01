from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from scripts.orca_contract import is_whitelisted_verification_command, verify_verification_truth
from scripts.orca_level1_gate import run_level1_gate
from scripts.summarize_worker_done import summarize_worker_report

GIT_BIN = shutil.which("git") or "/usr/bin/git"


@pytest.fixture(autouse=True)
def mock_subprocesses(monkeypatch):
    """비-git 하위 프로세스 호출(pytest, validate_agent_rules, ruff)을 mock 하여 검증 진실성 로직을 빠르게 테스트합니다."""
    import subprocess as real_subprocess

    from scripts import orca_contract, orca_level1_gate

    orig_run_command_safe = orca_level1_gate.run_command_safe
    orig_subprocess_run = real_subprocess.run

    def mock_run_command_safe(cmd, cwd, timeout):
        cmd_str = " ".join(str(c) for c in cmd)
        if cmd and "git" in Path(str(cmd[0])).name:
            return orig_run_command_safe(cmd, cwd, timeout)
        if "test_failing.py" in cmd_str:
            return 1, "1 failed in 0.01s", "", False
        if "nonexistent" in cmd_str:
            return 4, "ERROR: file not found", "", False
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
        timeout = kwargs.get("timeout")
        if timeout == 0:
            raise real_subprocess.TimeoutExpired(cmd, 0)
        cmd_str = " ".join(str(c) for c in cmd) if isinstance(cmd, (list, tuple)) else str(cmd)
        if isinstance(cmd, (list, tuple)) and cmd and "git" in Path(str(cmd[0])).name:
            return orig_subprocess_run(cmd, *args, **kwargs)
        if "test_failing.py" in cmd_str:
            return MockCompletedProc(1, "1 failed in 0.01s", "")
        if "nonexistent" in cmd_str:
            return MockCompletedProc(4, "ERROR: file not found", "")
        if "pytest" in cmd_str:
            return MockCompletedProc(0, "1 passed in 0.01s", "")
        if "validate_agent_rules.py" in cmd_str:
            return MockCompletedProc(0, "검증 통과: 12/12 건.", "")
        return orig_subprocess_run(cmd, *args, **kwargs)

    monkeypatch.setattr(orca_level1_gate, "run_command_safe", mock_run_command_safe)
    monkeypatch.setattr(orca_contract.subprocess, "run", mock_contract_subprocess_run)


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

    branch = "feature/verif-truth"
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
    (tests_dir / "test_failing.py").write_text(
        "def test_fail():\n    assert False\n", encoding="utf-8"
    )
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
            "feat: implement verification logic",
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
        allowed_writes = ["src/app.py", "tests/test_app.py", "tests/test_failing.py"]
    capsule_dir = repo / ".orca" / "capsules" / "task_verif_test"
    capsule_dir.mkdir(parents=True, exist_ok=True)
    capsule_path = capsule_dir / "capsule.yaml"

    lines = [
        "schema: ORCA_TASK_CAPSULE_V2",
        "version: '2.1.0'",
        "task_id: 'task_verif123'",
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
    verification: list[dict] | list[str] | None = None,
    changed_files: list[str] | None = None,
    verdict: str = "candidate",
) -> Path:
    """테스트용 worker_done 보고 JSON 을 생성합니다."""
    if changed_files is None:
        changed_files = ["src/app.py", "tests/test_app.py", "tests/test_failing.py"]
    if verification is None:
        verification = [
            {
                "command": "uv run pytest tests/test_app.py -q",
                "result": "1 passed",
            }
        ]

    report_path = repo / report_rel_path
    report_path.parent.mkdir(parents=True, exist_ok=True)

    data = {
        "schema": "ORCA_WORKER_DONE_V2",
        "version": "2.1.0",
        "task_id": "task_verif123",
        "status": "succeeded",
        "branch": branch,
        "commit": commit,
        "commit_count": 1,
        "changed_files": changed_files,
        "read_files": ["scripts/orca_contract.py"],
        "verification": verification,
        "verdict": verdict,
        "blocking_issues": [],
    }
    report_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return report_path


# ---------------------------------------------------------------------------
# 화이트리스트 판정 단위 테스트
# ---------------------------------------------------------------------------
def test_whitelist_command_parsing():
    """화이트리스트 명령(pytest, validate_agent_rules) 판정이 올바르게 동작한다."""
    is_wl, argv = is_whitelisted_verification_command("uv run pytest tests/test_app.py -q")
    assert is_wl is True
    assert argv is not None
    assert "pytest" in argv

    is_wl, argv = is_whitelisted_verification_command("pytest tests/test_app.py")
    assert is_wl is True
    assert argv is not None
    assert "pytest" in argv

    is_wl, argv = is_whitelisted_verification_command(
        "python3 scripts/validate_agent_rules.py --quiet"
    )
    assert is_wl is True
    assert argv is not None
    assert "validate_agent_rules.py" in str(argv)

    is_wl, argv = is_whitelisted_verification_command("npm test")
    assert is_wl is False
    assert argv is None

    is_wl, argv = is_whitelisted_verification_command("docker build .")
    assert is_wl is False
    assert argv is None


# ---------------------------------------------------------------------------
# (a) 형식 위반 verification 이 격하된다
# ---------------------------------------------------------------------------
def test_malformed_verification_item_degrades_verdict(tmp_path: Path):
    """verification 항목의 형식이 비어 있거나 올바르지 않으면 verdict 가 blocked 로 격하된다."""
    repo, base, branch, sha = _init_git_repo(tmp_path)
    report_rel = ".orca/capsules/task_verif_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)

    # 1. command 가 비어 있는 경우
    bad_verif_1 = [{"command": "", "result": "1 passed"}]
    report_path_1 = _create_report(repo, report_rel, branch, sha, verification=bad_verif_1)
    summ1 = summarize_worker_report(report_path_1, capsule_path=capsule_path, repo_path=repo)
    assert summ1["exit_code"] == 1
    assert summ1["effective_verdict"] == "blocked"
    assert any("verification[0].command" in v for v in summ1["violations"])

    # 2. result 가 비어 있는 경우
    bad_verif_2 = [{"command": "uv run pytest tests/test_app.py -q", "result": "  "}]
    report_path_2 = _create_report(repo, report_rel, branch, sha, verification=bad_verif_2)
    summ2 = summarize_worker_report(report_path_2, capsule_path=capsule_path, repo_path=repo)
    assert summ2["exit_code"] == 1
    assert summ2["effective_verdict"] == "blocked"
    assert any("verification[0].result" in v for v in summ2["violations"])

    # 3. 항목이 객체가 아닌 문자열인 경우
    bad_verif_3 = ["uv run pytest tests/test_app.py -q"]
    report_path_3 = _create_report(repo, report_rel, branch, sha, verification=bad_verif_3)
    summ3 = summarize_worker_report(report_path_3, capsule_path=capsule_path, repo_path=repo)
    assert summ3["exit_code"] == 1
    assert summ3["effective_verdict"] == "blocked"
    assert any("객체여야 함" in v for v in summ3["violations"])

    # Level 1 게이트에서도 FAIL 확인
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
# (b) 조작된 result(실제로는 실패인데 통과라고 적은 경우)가 FAIL 이다
# ---------------------------------------------------------------------------
def test_forged_verification_result_fails_gate(tmp_path: Path):
    """실제로는 실패하는 테스트를 '1 passed' 로 조작 보고하면 재실행 진실성 대조에서 FAIL 된다."""
    repo, base, branch, sha = _init_git_repo(tmp_path)
    report_rel = ".orca/capsules/task_verif_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)

    # test_failing.py 는 assert False 라서 실행 시 무조건 실패함
    forged_verification = [
        {
            "command": "uv run pytest tests/test_failing.py -q",
            "result": "1 passed",  # 허위 조작 보고
        }
    ]
    report_path = _create_report(
        repo,
        report_rel,
        branch,
        sha,
        verification=forged_verification,
    )

    # 1. verify_verification_truth 직접 검증
    ok, violations, details = verify_verification_truth(repo, forged_verification)
    assert ok is False
    assert any("실제 실행 실패" in v for v in violations)
    assert details[0]["status"] == "fail"

    # 2. summarize_worker_report 검증
    summ = summarize_worker_report(report_path, capsule_path=capsule_path, repo_path=repo)
    assert summ["exit_code"] == 1
    assert summ["effective_verdict"] == "blocked"
    assert any("실제 실행 실패" in v for v in summ["violations"])

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
# (c) 화이트리스트 밖 명령이 unverified 로 표기된다
# ---------------------------------------------------------------------------
def test_non_whitelisted_commands_marked_unverified(tmp_path: Path):
    """화이트리스트(pytest, validate_agent_rules) 이외의 명령은 unverified 로 표기된다."""
    repo, base, branch, sha = _init_git_repo(tmp_path)
    report_rel = ".orca/capsules/task_verif_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)

    mixed_verification = [
        {
            "command": "uv run pytest tests/test_app.py -q",
            "result": "1 passed",
        },
        {
            "command": "npm test",
            "result": "passed (frontend test)",
        },
        {
            "command": "docker build .",
            "result": "success",
        },
    ]

    report_path = _create_report(
        repo,
        report_rel,
        branch,
        sha,
        verification=mixed_verification,
    )

    # 1. verify_verification_truth 검증
    ok, violations, details = verify_verification_truth(repo, mixed_verification)
    assert ok is True
    assert len(violations) == 0

    assert details[0]["status"] == "pass"
    assert details[1]["status"] == "unverified"
    assert details[2]["status"] == "unverified"

    # 2. summarize_worker_report 검증
    summ = summarize_worker_report(report_path, capsule_path=capsule_path, repo_path=repo)
    assert summ["exit_code"] == 0
    assert summ["effective_verdict"] == "candidate"
    assert "npm test" in summ["unverified_commands"]
    assert "docker build ." in summ["unverified_commands"]
    assert "[UNVERIFIED] npm test" in summ["digest"]

    # 3. Level 1 게이트 검증
    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule_path,
        as_json=True,
    )
    assert code == 0
    data = json.loads(output)
    assert data["verdict"] == "pass"
    g6 = data["gates"]["gate6_worker_done"]
    assert g6["status"] == "pass"
    assert "npm test" in g6["unverified_commands"]


# ---------------------------------------------------------------------------
# (d) 정상 보고가 PASS 한다
# ---------------------------------------------------------------------------
def test_valid_verification_report_passes(tmp_path: Path):
    """pytest 및 validate_agent_rules 를 성실히 수행한 정상 보고는 모든 게이트를 통과한다."""
    repo, base, branch, sha = _init_git_repo(tmp_path)
    report_rel = ".orca/capsules/task_verif_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)

    valid_verification = [
        {
            "command": "uv run pytest tests/test_app.py -q",
            "result": "1 passed",
        },
        {
            "command": "python3 scripts/validate_agent_rules.py --quiet",
            "result": "검증 통과: 12/12 건.",
        },
    ]

    report_path = _create_report(
        repo,
        report_rel,
        branch,
        sha,
        verification=valid_verification,
    )

    # 1. summarize 검증
    summ = summarize_worker_report(report_path, capsule_path=capsule_path, repo_path=repo)
    assert summ["exit_code"] == 0
    assert summ["violations"] == []
    assert summ["effective_verdict"] == "candidate"
    assert all(d["status"] == "pass" for d in summ["verification_details"])

    # 2. Level 1 게이트 검증
    code, output = run_level1_gate(
        base=base,
        branch=branch,
        repo=repo,
        capsule=capsule_path,
        as_json=True,
    )
    assert code == 0
    data = json.loads(output)
    assert data["verdict"] == "pass"
    assert data["gates"]["gate6_worker_done"]["status"] == "pass"


# ---------------------------------------------------------------------------
# (e) 재실행 실패 / 타임아웃의 fail-closed 처리
# ---------------------------------------------------------------------------
def test_execution_failure_is_fail_closed(tmp_path: Path):
    """실행 자체가 불가능한 명령이나 타임아웃은 미검증이 아니라 실패(fail-closed)로 처리된다."""
    repo, _base, branch, sha = _init_git_repo(tmp_path)
    report_rel = ".orca/capsules/task_verif_test/worker_done.json"
    capsule_path = _create_capsule(repo, report_rel)

    # 존재하지 않는 테스트 경로 실행
    nonexistent_verif = [
        {
            "command": "uv run pytest tests/nonexistent_test_file.py -q",
            "result": "passed",
        }
    ]
    report_path = _create_report(
        repo,
        report_rel,
        branch,
        sha,
        verification=nonexistent_verif,
    )

    summ = summarize_worker_report(report_path, capsule_path=capsule_path, repo_path=repo)
    assert summ["exit_code"] == 1
    assert summ["effective_verdict"] == "blocked"
    assert any("실제 실행 실패" in v for v in summ["violations"])

    # timeout=0 으로 강제 타임아웃 시뮬레이션
    ok, violations, details = verify_verification_truth(
        repo,
        [{"command": "uv run pytest tests/test_app.py -q", "result": "1 passed"}],
        timeout=0,
    )
    assert ok is False
    assert any("타임아웃" in v for v in violations)
    assert details[0]["status"] == "fail"
