"""tests/test_orca_gate11_fail_pass.py

게이트 11(실패→통과 증명) 경고 모드 계약을 작은 임시 git 저장소로 검증합니다.

실제 저장소의 데이터 자산이나 운영 서비스에 기대지 않습니다. 기준 코드에는
결함이 있고 브랜치에는 수정이 있는 최소 저장소를 만들어, 게이트가 기준 트리와
브랜치 트리를 각각 풀어 같은 시험을 돌리는지 확인합니다.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

from scripts import orca_level1_gate
from scripts.orca_level1_gate import (
    GATE11_GATE_NAME,
    GateResult,
    build_json_output,
    run_gate11_fail_pass,
)

GIT_BIN = shutil.which("git") or "/usr/bin/git"

PYPROJECT_TOML = """[tool.pytest.ini_options]
pythonpath = ["."]
"""

BASE_DIRTY_SOURCE = "def add(a, b):\n    return a - b\n"
BASE_DIRTY_TEST = "from src.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == -1\n"
CLEAN_SOURCE = "def add(a, b):\n    return a + b\n"
CLEAN_TEST = "from src.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        [GIT_BIN, "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


def _rev(repo: Path, ref: str = "HEAD") -> str:
    proc = subprocess.run(  # noqa: S603
        [GIT_BIN, "rev-parse", ref],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout.strip()


def _init_repo(repo: Path, source: str, test: str) -> str:
    """기준 커밋을 만들고 base SHA 를 반환합니다."""
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _write(repo / "pyproject.toml", PYPROJECT_TOML)
    _write(repo / "src" / "calc.py", source)
    _write(repo / "tests" / "test_calc.py", test)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "feat: 기준 계산기를 추가한다")
    return _rev(repo)


def _commit_changes(
    repo: Path,
    *,
    source: str | None = None,
    test: str | None = None,
    extra: dict[str, str] | None = None,
    message: str = "feat: 계산기를 고친다",
) -> None:
    """브랜치 커밋을 만듭니다."""
    if source is not None:
        _write(repo / "src" / "calc.py", source)
    if test is not None:
        _write(repo / "tests" / "test_calc.py", test)
    for rel, content in (extra or {}).items():
        _write(repo / rel, content)
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", message)


def _run(repo: Path, base: str):
    return run_gate11_fail_pass(repo, base, "HEAD", python_executable=sys.executable)


def _assert_warning_mode(result: GateResult) -> None:
    """어떤 verdict 에서도 fail 이 아니고 summary 접두사가 고정되어 있는지 확인합니다."""
    assert result.name == GATE11_GATE_NAME
    assert result.status != "fail"
    assert result.required is False
    assert result.summary.startswith("[경고 모드]")


def test_gate11_proven_when_base_fails_and_branch_passes(tmp_path: Path):
    """(a) 기준에서 단언 실패, 브랜치에서 통과하면 proven 과 status pass 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, BASE_DIRTY_SOURCE, BASE_DIRTY_TEST)
    _commit_changes(repo, source=CLEAN_SOURCE, test=CLEAN_TEST)

    result = _run(repo, base)

    _assert_warning_mode(result)
    assert result.raw_data["verdict"] == "proven"
    assert result.status == "pass"
    assert result.raw_data["target_files"] == ["tests/test_calc.py"]
    assert result.raw_data["base_counts"]["failed"] >= 1
    assert result.raw_data["base_counts"]["errors"] == 0
    assert result.raw_data["branch_counts"]["failed"] == 0
    assert result.raw_data["branch_counts"]["errors"] == 0
    assert result.raw_data["branch_counts"]["passed"] >= 1


def test_gate11_not_proven_when_base_also_passes(tmp_path: Path):
    """(b) 기준 코드에서도 전부 통과하면 not_proven 이고 skipped 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        test=CLEAN_TEST + "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n",
    )

    result = _run(repo, base)

    _assert_warning_mode(result)
    assert result.raw_data["verdict"] == "not_proven"
    assert result.status == "skipped"
    assert result.raw_data["base_counts"]["failed"] == 0
    assert result.raw_data["base_counts"]["errors"] == 0
    assert result.raw_data["branch_counts"]["failed"] == 0


def test_gate11_collection_only_when_base_import_fails(tmp_path: Path):
    """(c) 기준 코드에서 수집·import 오류만 나면 단언 실패로 세지 않습니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    extra_source = CLEAN_SOURCE + "\n\ndef multiply(a, b):\n    return a * b\n"
    extra_test = (
        "from src.calc import add, multiply\n\n\n"
        "def test_add():\n    assert add(1, 2) == 3\n\n\n"
        "def test_multiply():\n    assert multiply(2, 3) == 6\n"
    )
    _commit_changes(repo, source=extra_source, test=extra_test)

    result = _run(repo, base)

    _assert_warning_mode(result)
    assert result.raw_data["verdict"] == "collection_only"
    assert result.status == "skipped"
    assert result.raw_data["base_counts"]["failed"] == 0
    assert result.raw_data["base_counts"]["errors"] >= 1
    assert result.raw_data["branch_counts"]["errors"] == 0


def test_gate11_branch_failed_when_branch_test_fails(tmp_path: Path):
    """(d) 브랜치에서도 시험이 실패하면 branch_failed 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(repo, test=CLEAN_TEST + "\n\ndef test_broken():\n    assert add(1, 2) == 4\n")

    result = _run(repo, base)

    _assert_warning_mode(result)
    assert result.raw_data["verdict"] == "branch_failed"
    assert result.status == "skipped"
    assert result.raw_data["branch_counts"]["failed"] >= 1


def test_gate11_exempt_when_no_target_test_files(tmp_path: Path):
    """(e) 대상 시험 파일이 없으면 시험을 돌리지 않고 exempt 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        source=CLEAN_SOURCE + "\n\ndef multiply(a, b):\n    return a * b\n",
    )

    result = _run(repo, base)

    _assert_warning_mode(result)
    assert result.raw_data["verdict"] == "exempt"
    assert result.status == "skipped"
    assert result.raw_data["target_files"] == []
    assert "base_counts" not in result.raw_data


def test_gate11_error_is_skipped_not_fail(tmp_path: Path):
    """(f) 도구 오류도 fail 이 아니라 error verdict 의 skipped 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, BASE_DIRTY_SOURCE, BASE_DIRTY_TEST)
    _commit_changes(repo, source=CLEAN_SOURCE, test=CLEAN_TEST)

    result = run_gate11_fail_pass(
        repo,
        base,
        "HEAD",
        python_executable=str(tmp_path / "missing-python"),
    )

    _assert_warning_mode(result)
    assert result.raw_data["verdict"] == "error"
    assert result.status == "skipped"
    assert "도구 오류" in result.summary


def test_gate11_key_does_not_shift_existing_gate_keys():
    """(g) gate11_fail_pass 키가 추가되어도 기존 키 순서가 바뀌지 않습니다."""
    names = [
        "게이트 1 변경 파일",
        "게이트 2 범위 검증",
        "게이트 3 테스트",
        "게이트 4 규칙 검증",
        "게이트 4b 린터",
        "게이트 5 리뷰 보고",
        "게이트 6 worker_done 보고",
        "게이트 7 gitignore 검증",
        "게이트 8 커밋 메시지",
        "게이트 9 금지 lockfile 검증",
        "게이트 10 명령 실재성",
        GATE11_GATE_NAME,
    ]
    expected_keys = [
        "gate1_changed_files",
        "gate2_scope",
        "gate3_tests",
        "gate4_rules",
        "gate4b_lint",
        "gate5_review_report",
        "gate6_worker_done",
        "gate7_gitignored",
        "gate8_commit_message",
        "gate9_forbidden_lockfiles",
        "gate10_command_reality",
        "gate11_fail_pass",
    ]
    gates = [GateResult(name=name, status="pass", summary="", required=False) for name in names]

    data = build_json_output(gates, "pass", 0, len(gates), 0, 0)

    assert list(data["gates"]) == expected_keys
    assert data["gates"]["gate11_fail_pass"]["name"] == GATE11_GATE_NAME
    assert not [key for key in data["gates"] if key.startswith("gate_")]


def test_gate11_removes_temporary_directories(tmp_path: Path, monkeypatch):
    """(h) 실행이 끝나면 기준/브랜치 임시 디렉터리가 남지 않습니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, BASE_DIRTY_SOURCE, BASE_DIRTY_TEST)
    _commit_changes(repo, source=CLEAN_SOURCE, test=CLEAN_TEST)

    created: list[str] = []
    real_mkdtemp = orca_level1_gate.tempfile.mkdtemp

    def tracking_mkdtemp(*args, **kwargs):
        path = real_mkdtemp(*args, **kwargs)
        created.append(path)
        return path

    monkeypatch.setattr(orca_level1_gate.tempfile, "mkdtemp", tracking_mkdtemp)

    result = _run(repo, base)

    assert result.raw_data["verdict"] == "proven"
    assert created
    assert all(not Path(path).exists() for path in created)
