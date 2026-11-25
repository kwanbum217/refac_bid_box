"""tests/test_orca_gate11_backfill.py

게이트 11 소급 실행 스크립트 scripts/orca_gate11_backfill.py 를 작은 임시 git
저장소로 검증합니다.

실제 저장소의 refs/backup 참조나 데이터 자산을 읽지 않고, 병합 커밋 유무에 따른
base 선택 방식과 표준출력 JSON, 실행 전후 저장소 상태 불변을 확인합니다.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from scripts import orca_gate11_backfill as backfill
from scripts.orca_level1_gate import GateResult

GIT_BIN = shutil.which("git") or "/usr/bin/git"


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _git(repo: Path, *args: str) -> str:
    proc = subprocess.run(  # noqa: S603
        [GIT_BIN, "-c", "user.email=test@example.com", "-c", "user.name=Test", *args],
        cwd=str(repo),
        check=True,
        capture_output=True,
        text=True,
    )
    return proc.stdout


def _rev(repo: Path, ref: str = "HEAD") -> str:
    return _git(repo, "rev-parse", ref).strip()


def _commit(repo: Path, rel: str, content: str, message: str) -> str:
    _write(repo / rel, content)
    _git(repo, "add", rel)
    _git(repo, "commit", "-m", message)
    return _rev(repo)


def _init_repo(repo: Path) -> str:
    """기준 커밋 하나를 만들고 SHA 를 반환합니다."""
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    return _commit(repo, "README.md", "기준\n", "feat: 기준 커밋을 추가한다")


def _add_feature_branch(repo: Path) -> str:
    """main 에서 갈라진 feature 브랜치에 커밋 하나를 만듭니다."""
    _git(repo, "checkout", "-b", "feature")
    _commit(repo, "src/feature.py", "VALUE = 1\n", "feat: 기능 모듈을 추가한다")
    return _rev(repo, "feature")


def _fake_gate_result(verdict: str) -> GateResult:
    return GateResult(
        name="게이트 11 실패→통과 증명",
        status="pass" if verdict == "proven" else "skipped",
        summary="[경고 모드] 시험 대역",
        required=False,
        raw_data={
            "commit_types": ["test"],
            "target_files": ["tests/test_feature.py"],
            "base_counts": {},
            "branch_counts": {},
            "duration_seconds": 0.0,
            "verdict": verdict,
        },
    )


def _snapshot(repo: Path) -> dict[str, object]:
    """작업 트리 파일 목록과 참조·브랜치·HEAD 상태를 모읍니다."""
    files = sorted(
        path.relative_to(repo).as_posix()
        for path in repo.rglob("*")
        if path.is_file() and ".git" not in path.relative_to(repo).parts
    )
    return {
        "head": _rev(repo),
        "files": files,
        "branches": _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/heads"),
        "backup": _git(repo, "for-each-ref", "--format=%(refname) %(objectname)", "refs/backup"),
        "status": _git(repo, "status", "--porcelain"),
    }


def test_find_base_commit_uses_first_parent_of_merge(tmp_path: Path):
    """(a) 병합 커밋이 있으면 두 번째 부모가 그 참조인 병합의 첫 부모를 base 로 씁니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    feature_commit = _add_feature_branch(repo)
    _git(repo, "checkout", "main")
    main_head = _commit(repo, "docs/guide.md", "안내\n", "docs: 안내 문서를 추가한다")
    _git(repo, "merge", "--no-ff", "-m", "merge: 기능 브랜치를 병합한다", "feature")

    found, source = backfill.find_base_commit(repo, "feature", "main")

    assert (found, source) == (main_head, "merge_parent")
    assert found != base
    assert feature_commit != found


def test_find_base_commit_falls_back_to_merge_base(tmp_path: Path):
    """(b) 병합 커밋이 없으면 merge-base 결과를 base 로 쓰고 방법을 merge_base 로 남깁니다."""
    repo = tmp_path / "repo"
    base = _init_repo(repo)
    _add_feature_branch(repo)
    _git(repo, "checkout", "main")
    _commit(repo, "docs/guide.md", "안내\n", "docs: 안내 문서를 추가한다")
    assert "merge" not in _git(repo, "log", "main", "--merges", "--format=%H")

    found, source = backfill.find_base_commit(repo, "feature", "main")

    assert (found, source) == (base, "merge_base")


def test_main_prints_json_verdict_per_ref(tmp_path: Path, monkeypatch, capsys):
    """(c) main 이 참조별 verdict 를 담은 JSON 을 표준출력에 내고 종료 코드 0 을 반환합니다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    _add_feature_branch(repo)
    _git(repo, "checkout", "main")
    calls: list[tuple[str, str]] = []

    def fake_run(*, repo: Path, base: str, branch: str, python_executable=None, timeout=None):
        calls.append((base, branch))
        return _fake_gate_result("exempt")

    monkeypatch.setattr(backfill, "run_gate11_fail_pass", fake_run)

    exit_code = backfill.main(["--refs", "feature", "--main", "main", "--repo", str(repo)])

    assert exit_code == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["schema"] == backfill.GATE11_BACKFILL_SCHEMA
    assert payload["main"] == "main"
    assert payload["repo"] == str(repo.resolve())
    assert [entry["ref"] for entry in payload["refs"]] == ["feature"]
    entry = payload["refs"][0]
    assert entry["verdict"] == "exempt"
    assert entry["base_source"] == "merge_base"
    assert entry["commit"] == _rev(repo, "feature")[:8]
    assert entry["status"] == "skipped"
    assert entry["required"] is False
    assert calls == [(_rev(repo, "HEAD"), "feature")]


def test_main_leaves_repository_unchanged(tmp_path: Path, monkeypatch):
    """(d) 실행 뒤 작업 트리·브랜치·참조·HEAD 가 그대로입니다."""
    repo = tmp_path / "repo"
    _init_repo(repo)
    feature_commit = _add_feature_branch(repo)
    _git(repo, "checkout", "main")
    _commit(repo, "docs/guide.md", "안내\n", "docs: 안내 문서를 추가한다")
    _git(repo, "update-ref", "refs/backup/trial", feature_commit)
    before = _snapshot(repo)

    def fake_run(*, repo: Path, base: str, branch: str, python_executable=None, timeout=None):
        return _fake_gate_result("proven")

    monkeypatch.setattr(backfill, "run_gate11_fail_pass", fake_run)

    exit_code = backfill.main(
        ["--refs", "refs/backup/trial", "--main", "main", "--repo", str(repo)]
    )

    assert exit_code == 0
    assert _snapshot(repo) == before
    assert "refs/backup/trial" in _git(repo, "for-each-ref", "--format=%(refname)", "refs/backup")
