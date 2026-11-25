"""tests/test_orca_gate11_fail_pass.py

게이트 11(실패→통과 증명) 차단 모드 계약을 작은 임시 git 저장소로 검증합니다.

실제 저장소의 데이터 자산이나 운영 서비스에 기대지 않습니다. 기준 코드에는
결함이 있고 브랜치에는 수정이 있는 최소 저장소를 만들어, 게이트가 기준 트리와
브랜치 트리를 각각 풀어 같은 시험을 돌리는지 확인합니다. proven 이 아닌 판정과
대상 시험 없는 src 변경은 --strict 병합 판정을 막아야 합니다.
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


def _write_capsule(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "capsule.yaml"
    path.write_text(body, encoding="utf-8")
    return path


def _run(repo: Path, base: str, capsule: Path | None = None):
    return run_gate11_fail_pass(
        repo,
        base,
        "HEAD",
        python_executable=sys.executable,
        capsule_path=capsule,
    )


def test_gate11_proven_passes_in_blocking_mode(tmp_path: Path):
    """(e) 기준에서 단언 실패, 브랜치에서 통과하면 proven 과 status pass 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, BASE_DIRTY_SOURCE, BASE_DIRTY_TEST)
    _commit_changes(repo, source=CLEAN_SOURCE, test=CLEAN_TEST)

    result = _run(repo, base)

    assert result.name == GATE11_GATE_NAME
    assert result.status == "pass"
    assert result.required is True
    assert result.summary.startswith("[차단 모드]")
    assert result.raw_data["verdict"] == "proven"
    assert result.raw_data["target_files"] == ["tests/test_calc.py"]
    assert result.raw_data["base_counts"]["failed"] >= 1
    assert result.raw_data["base_counts"]["errors"] == 0
    assert result.raw_data["branch_counts"]["failed"] == 0
    assert result.raw_data["branch_counts"]["errors"] == 0
    assert result.raw_data["branch_counts"]["passed"] >= 1


def test_gate11_not_proven_fails(tmp_path: Path):
    """(a) 기준 코드에서도 전부 통과하면 not_proven 은 required=True 인 fail 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        test=CLEAN_TEST + "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n",
    )

    result = _run(repo, base)

    assert result.raw_data["verdict"] == "not_proven"
    assert result.status == "fail"
    assert result.required is True
    assert result.summary.startswith("[차단 모드]")
    assert "not_proven" in orca_level1_gate.GATE11_FAIL_VERDICTS
    assert result.raw_data["base_counts"]["failed"] == 0
    assert result.raw_data["base_counts"]["errors"] == 0
    assert result.raw_data["branch_counts"]["failed"] == 0


def test_gate11_collection_only_fails(tmp_path: Path):
    """(a) 기준 코드에서 수집·import 오류만 나면 collection_only 는 fail 입니다."""
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

    assert result.raw_data["verdict"] == "collection_only"
    assert result.status == "fail"
    assert result.required is True
    assert "collection_only" in orca_level1_gate.GATE11_FAIL_VERDICTS
    assert result.raw_data["base_counts"]["failed"] == 0
    assert result.raw_data["base_counts"]["errors"] >= 1
    assert result.raw_data["branch_counts"]["errors"] == 0


def test_gate11_branch_failed_fails(tmp_path: Path):
    """(a) 브랜치에서도 시험이 실패하면 branch_failed 는 fail 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(repo, test=CLEAN_TEST + "\n\ndef test_broken():\n    assert add(1, 2) == 4\n")

    result = _run(repo, base)

    assert result.raw_data["verdict"] == "branch_failed"
    assert result.status == "fail"
    assert result.required is True
    assert "branch_failed" in orca_level1_gate.GATE11_FAIL_VERDICTS
    assert result.raw_data["branch_counts"]["failed"] >= 1


def test_gate11_error_fails_with_exempt_guidance(tmp_path: Path):
    """(a) 도구 오류도 error verdict 의 required=True 인 fail 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, BASE_DIRTY_SOURCE, BASE_DIRTY_TEST)
    _commit_changes(repo, source=CLEAN_SOURCE, test=CLEAN_TEST)

    result = run_gate11_fail_pass(
        repo,
        base,
        "HEAD",
        python_executable=str(tmp_path / "missing-python"),
    )

    assert result.raw_data["verdict"] == "error"
    assert result.status == "fail"
    assert result.required is True
    assert result.summary.startswith("[차단 모드]")
    assert "도구 오류" in result.summary
    assert "tdd: exempt(<사유>)" in result.summary
    assert "error" in orca_level1_gate.GATE11_FAIL_VERDICTS


def test_gate11_no_tests_fails_when_src_changes(tmp_path: Path):
    """(b) src/ 변경 + 시험 없음 + feat 커밋이면 no_tests fail 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        source=CLEAN_SOURCE + "\n\ndef multiply(a, b):\n    return a * b\n",
    )

    result = _run(repo, base)

    assert result.raw_data["verdict"] == "no_tests"
    assert result.status == "fail"
    assert result.required is True
    assert result.summary.startswith("[차단 모드]")
    assert result.raw_data["target_files"] == []
    assert result.raw_data["src_changed"] is True
    assert "base_counts" not in result.raw_data
    assert any("tdd: exempt(<사유>)" in line for line in result.details)


def test_gate11_exempt_when_only_exempt_commit_types_without_src(tmp_path: Path):
    """(d) docs·chore 커밋만 있고 src/ 변경이 없으면 대상 시험이 있어도 exempt 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        test=CLEAN_TEST + "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n",
        message="docs: 계산기 시험 설명을 추가한다",
    )
    _commit_changes(repo, extra={"docs/guide.md": "안내\n"}, message="chore: 안내 문서를 추가한다")

    result = _run(repo, base)

    assert result.raw_data["verdict"] == "exempt"
    assert result.status == "skipped"
    assert result.required is False
    assert sorted(result.raw_data["commit_types"]) == ["chore", "docs"]
    assert result.raw_data["src_changed"] is False
    assert result.raw_data["target_files"] == ["tests/test_calc.py"]
    assert "base_counts" not in result.raw_data


def test_gate11_exempt_when_no_target_tests_without_src(tmp_path: Path):
    """(d) src/ 변경 없이 대상 시험 파일도 없으면 exempt 입니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(repo, extra={"docs/guide.md": "안내\n"}, message="feat: 안내 문서를 추가한다")

    result = _run(repo, base)

    assert result.raw_data["verdict"] == "exempt"
    assert result.status == "skipped"
    assert result.required is False
    assert result.raw_data["target_files"] == []
    assert result.raw_data["src_changed"] is False


def test_gate11_capsule_exempt_declaration_overrides_blocking(tmp_path: Path):
    """(c) Capsule 의 tdd: exempt(<사유>) 는 차단 대상이어도 면제로 통과합니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        source=CLEAN_SOURCE + "\n\ndef multiply(a, b):\n    return a * b\n",
    )
    capsule = _write_capsule(
        tmp_path,
        "schema: ORCA_TASK_CAPSULE_V2\ntdd: exempt(동작 불변 리팩터링이라 새 단언이 없다)\n",
    )

    result = _run(repo, base, capsule)

    assert result.raw_data["verdict"] == "exempt_declared"
    assert result.status == "skipped"
    assert result.required is False
    assert result.summary.startswith("[차단 모드]")
    assert "동작 불변 리팩터링이라 새 단언이 없다" in result.summary
    assert result.raw_data["tdd"] == "exempt"
    assert result.raw_data["tdd_reason"] == "동작 불변 리팩터링이라 새 단언이 없다"


def test_gate11_capsule_exempt_declaration_under_root_key(tmp_path: Path):
    """(c) Capsule 이 ORCA_TASK_CAPSULE_V2 루트 아래에 tdd 를 둬도 읽습니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        source=CLEAN_SOURCE + "\n\ndef multiply(a, b):\n    return a * b\n",
    )
    capsule = _write_capsule(
        tmp_path,
        "ORCA_TASK_CAPSULE_V2:\n  schema: ORCA_TASK_CAPSULE_V2\n  tdd: exempt(조사 Task 산출물)\n",
    )

    result = _run(repo, base, capsule)

    assert result.raw_data["verdict"] == "exempt_declared"
    assert result.status == "skipped"
    assert result.required is False
    assert "조사 Task 산출물" in result.summary
    assert "조사 Task 산출물" in result.details[0]


def test_gate11_required_capsule_still_blocks(tmp_path: Path):
    """(c) Capsule tdd: required 와 unspecified 는 같은 차단 판정을 받습니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        source=CLEAN_SOURCE + "\n\ndef multiply(a, b):\n    return a * b\n",
    )

    for body in (
        "schema: ORCA_TASK_CAPSULE_V2\ntdd: required\n",
        "schema: ORCA_TASK_CAPSULE_V2\n",
        "schema: ORCA_TASK_CAPSULE_V2\ntdd: exempt()\n",
    ):
        capsule = _write_capsule(tmp_path, body)
        result = _run(repo, base, capsule)
        assert result.raw_data["verdict"] == "no_tests"
        assert result.status == "fail"
        assert result.required is True


def test_gate11_not_exempt_when_exempt_type_has_src_changes(tmp_path: Path):
    """(j) docs 커밋이라도 src/ 변경이 있으면 면제하지 않습니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, CLEAN_SOURCE, CLEAN_TEST)
    _commit_changes(
        repo,
        source=CLEAN_SOURCE + "\n\ndef multiply(a, b):\n    return a * b\n",
        test=CLEAN_TEST + "\n\ndef test_add_zero():\n    assert add(0, 0) == 0\n",
        message="docs: 계산기 동작을 정리한다",
    )

    result = _run(repo, base)

    assert result.raw_data["commit_types"] == ["docs"]
    assert result.raw_data["src_changed"] is True
    assert result.raw_data["verdict"] != "exempt"
    assert result.raw_data["verdict"] == "not_proven"
    assert result.status == "fail"


def test_gate11_unknown_commit_type_is_not_exempt(tmp_path: Path):
    """(k) 형식 밖 커밋 제목은 unknown type 이라 면제하지 않습니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo, BASE_DIRTY_SOURCE, BASE_DIRTY_TEST)
    _commit_changes(repo, source=CLEAN_SOURCE, test=CLEAN_TEST, message="계산기를 고친다")

    result = _run(repo, base)

    assert result.raw_data["commit_types"] == ["unknown"]
    assert result.raw_data["src_changed"] is True
    assert result.raw_data["verdict"] != "exempt"
    assert result.raw_data["verdict"] == "proven"
    assert result.status == "pass"


def test_parse_gate11_tdd_reads_both_capsule_shapes():
    """Capsule 의 tdd 는 최상위와 루트 아래 들여쓰기 모두에서 같은 값으로 읽힙니다."""
    parse_gate11_tdd = orca_level1_gate.parse_gate11_tdd
    assert parse_gate11_tdd("schema: ORCA_TASK_CAPSULE_V2\ntdd: required\n") == (
        "required",
        "",
    )
    assert parse_gate11_tdd("tdd: exempt(문서만 바뀐다)\n") == ("exempt", "문서만 바뀐다")
    assert parse_gate11_tdd(
        "ORCA_TASK_CAPSULE_V2:\n  schema: ORCA_TASK_CAPSULE_V2\n  tdd: exempt(조사)\n"
    ) == ("exempt", "조사")
    assert parse_gate11_tdd("schema: ORCA_TASK_CAPSULE_V2\n") == ("unspecified", "")
    assert parse_gate11_tdd("tdd: suspicious\n") == ("unspecified", "")


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
