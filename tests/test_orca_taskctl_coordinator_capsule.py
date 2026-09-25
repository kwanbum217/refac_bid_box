from __future__ import annotations

import json
import shutil
import subprocess
import types
from pathlib import Path

import pytest

from scripts.orca_contract import parse_capsule_list
from scripts.orca_level1_gate import (
    CAP_BACKEND_MYPY,
    CAP_BACKEND_PYTEST,
    parse_verification_command,
    required_capabilities,
    run_gate2_scope,
    run_gate6_worker_done,
)
from scripts.orca_taskctl import main

OBJECTIVE = "코디네이터 직접 작성 브랜치용 최소 Capsule 을 만든다"

GIT_BIN = shutil.which("git") or "/usr/bin/git"


def _run(
    tmp_path: Path,
    scope: list[str],
    slug: str = "demo",
    out: Path | None = None,
) -> tuple[int, Path]:
    """coordinator-capsule 을 실행하고 (종료 코드, 출력 경로) 를 돌려줍니다."""
    out_path = out if out is not None else tmp_path / "capsule.yaml"
    argv = ["coordinator-capsule", "--slug", slug, "--objective", OBJECTIVE]
    for item in scope:
        argv += ["--scope", item]
    argv += ["--out", str(out_path), "--json"]
    return main(argv), out_path


def test_allowed_write_files_equal_scope(tmp_path: Path, capsys: pytest.CaptureFixture):
    """(a) 생성 Capsule 의 allowed_write_files 가 --scope 와 정확히 같다."""
    scope = ["scripts/orca_taskctl.py", "tests/test_orca_taskctl_coordinator_capsule.py"]
    code, out_path = _run(tmp_path, scope)
    assert code == 0

    capsule_text = out_path.read_text(encoding="utf-8")
    assert parse_capsule_list(capsule_text, "allowed_write_files") == scope

    payload = json.loads(capsys.readouterr().out)
    assert payload["capsule_path"] == str(out_path)
    assert payload["task_id"] == "coord_demo"
    assert payload["allowed_write_files"] == scope
    assert payload["verification_commands"] == parse_capsule_list(
        capsule_text, "verification_commands"
    )


def test_gate2_scope_pass_and_fail(tmp_path: Path):
    """(b) 같은 Capsule 로 게이트 2 가 범위 안은 pass, 범위 밖은 fail."""
    scope = ["scripts/orca_taskctl.py"]
    code, out_path = _run(tmp_path, scope)
    assert code == 0

    inside = run_gate2_scope(["scripts/orca_taskctl.py"], out_path)
    assert inside.status == "pass"

    outside = run_gate2_scope(["scripts/orca_taskctl.py", "src/ml/features.py"], out_path)
    assert outside.status == "fail"


def test_verification_covers_src_capabilities(tmp_path: Path):
    """(c) src/ 아래 .py 를 scope 로 주면 게이트 3 능력을 덮는 명령이 붙는다."""
    scope = ["src/ml/demo_feature.py"]
    code, out_path = _run(tmp_path, scope)
    assert code == 0

    commands = parse_capsule_list(out_path.read_text(encoding="utf-8"), "verification_commands")
    covered: set[str] = set()
    for command in commands:
        covered |= set(parse_verification_command(command).provides)

    required = required_capabilities(scope)
    assert {CAP_BACKEND_PYTEST, CAP_BACKEND_MYPY} <= required
    assert required <= covered


def test_invalid_slug_rejected(tmp_path: Path):
    """(d) 영문 소문자·숫자·하이픈이 아닌 slug 는 종료 코드 2."""
    code, out_path = _run(tmp_path, ["scripts/orca_taskctl.py"], slug="Bad_Slug")
    assert code == 2
    assert not out_path.exists()


def test_absolute_scope_rejected(tmp_path: Path):
    """(d) 절대 경로 scope 는 종료 코드 2."""
    code, out_path = _run(tmp_path, ["/etc/passwd"])
    assert code == 2
    assert not out_path.exists()


def test_parent_traversal_scope_rejected(tmp_path: Path):
    """(d) 상위 디렉터리 탐색(..) scope 는 종료 코드 2."""
    code, out_path = _run(tmp_path, ["../outside.py"])
    assert code == 2
    assert not out_path.exists()


def test_existing_out_file_rejected(tmp_path: Path):
    """(d) --out 파일이 이미 있으면 덮어쓰지 않고 종료 코드 2."""
    out_path = tmp_path / "capsule.yaml"
    out_path.write_text("기존 내용", encoding="utf-8")

    code, _ = _run(tmp_path, ["scripts/orca_taskctl.py"], out=out_path)
    assert code == 2
    assert out_path.read_text(encoding="utf-8") == "기존 내용"


def test_does_not_invoke_orca_cli(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """(e) coordinator-capsule 은 orca CLI 나 외부 프로세스를 호출하지 않는다."""
    calls: list[tuple[object, ...]] = []

    def _blocked(*args: object, **kwargs: object) -> None:
        calls.append(args)
        raise AssertionError("orca CLI 또는 외부 프로세스를 호출하면 안 됩니다")

    fake_subprocess = types.SimpleNamespace(run=_blocked, Popen=_blocked)
    monkeypatch.setattr("scripts.orca_taskctl.subprocess", fake_subprocess)

    code, out_path = _run(tmp_path, ["scripts/orca_taskctl.py"])
    assert code == 0
    assert calls == []
    assert out_path.exists()


def test_no_report_declaration(tmp_path: Path):
    """(f) 생성 Capsule 에 report_path 와 worker_done.json 문자열이 없다.

    코디네이터 브랜치에는 워커 보고가 없으므로 보고 선언을 남기면 게이트 6 이
    보고 파일을 요구해 --strict 가 실패합니다.
    """
    code, out_path = _run(tmp_path, ["scripts/orca_taskctl.py"])
    assert code == 0

    capsule_text = out_path.read_text(encoding="utf-8")
    assert "report_path" not in capsule_text
    assert "worker_done.json" not in capsule_text


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603
        [GIT_BIN, *args], cwd=str(repo), check=True, capture_output=True
    )


def _git_commit(repo: Path, message: str) -> None:
    subprocess.run(  # noqa: S603
        [
            GIT_BIN,
            "-c",
            "user.email=test@example.com",
            "-c",
            "user.name=Test",
            "commit",
            "-m",
            message,
        ],
        cwd=str(repo),
        check=True,
        capture_output=True,
    )


def _init_doc_change_repo(tmp_path: Path) -> tuple[Path, str, Path]:
    """문서(.md) 한 건만 바꾼 임시 git 저장소와 그 scope 의 Capsule 을 만듭니다."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")

    docs_dir = repo / "docs"
    docs_dir.mkdir()
    (docs_dir / "note.md").write_text("베이스 내용\n", encoding="utf-8")
    _git(repo, "add", "docs/note.md")
    _git_commit(repo, "docs: 초기 베이스 커밋")

    branch = "feature-branch"
    _git(repo, "checkout", "-b", branch)
    (docs_dir / "note.md").write_text("베이스 내용\n작업 브랜치 변경\n", encoding="utf-8")
    _git(repo, "add", "docs/note.md")
    _git_commit(repo, "docs: 작업 브랜치 문서 변경")

    capsule_path = repo / ".orca" / "capsules" / "coord_demo" / "capsule.yaml"
    code, out_path = _run(tmp_path, ["docs/note.md"], out=capsule_path)
    assert code == 0
    return repo, branch, out_path


def test_strict_gate6_skipped_for_coordinator_capsule(tmp_path: Path):
    """(g) 코디네이터 Capsule 은 게이트 2 를 통과하고 게이트 6 은 적용 대상이 아니다.

    임시 저장소의 문서 한 건을 scope 로 준 Capsule 로 게이트 2 와 게이트 6 을
    직접 호출합니다. 게이트 6 이 skipped/required=False 이므로 --strict 의
    필수 건너뜀 집계에 들어가지 않아 strict 판정이 실패하지 않습니다.
    """
    repo, branch, capsule_path = _init_doc_change_repo(tmp_path)
    changed_files = ["docs/note.md"]

    scope_gate = run_gate2_scope(changed_files, capsule_path)
    assert scope_gate.status == "pass"

    report_gate = run_gate6_worker_done(
        capsule_path=capsule_path, repo_path=repo, base="main", branch=branch
    )
    assert report_gate.status == "skipped"
    assert report_gate.required is False

    # orca_level1_gate.run_level1_gate 의 strict 판정과 같은 식으로 계산합니다.
    blocking_skips = [
        g.name for g in (scope_gate, report_gate) if g.status == "skipped" and g.required
    ]
    assert blocking_skips == []
