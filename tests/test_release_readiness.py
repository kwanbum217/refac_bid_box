from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from scripts import check_release_readiness as readiness


def _git(repo: Path, *args: str) -> None:
    subprocess.run(  # noqa: S603 - 테스트 저장소를 위한 고정 git 명령입니다.
        ["git", *args],  # noqa: S607 - 테스트 저장소를 위한 고정 git 명령입니다.
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )


def _new_repo(tmp_path: Path, version: str = "0.2.0") -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Release Test")
    (repo / "pyproject.toml").write_text(
        f'[project]\nname = "example"\nversion = "{version}"\n', encoding="utf-8"
    )
    (repo / "source.txt").write_text("initial\n", encoding="utf-8")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "chore: initialize test repository")
    return repo


def _successful_ci(*_args: object) -> tuple[bool, str]:
    return True, "CI test double passed"


def _failed_ci(*_args: object) -> tuple[bool, str]:
    return False, "CI failed in test double"


def test_tag_is_derived_from_pyproject_and_all_readiness_checks_pass(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path, version="2.4.1")

    report = readiness.check_readiness(repo, repository="owner/repo", ci_checker=_successful_ci)

    assert report.passed
    assert report.version == "2.4.1"
    assert report.tag == "v2.4.1"
    assert [check.name for check in report.checks] == [
        "작업 트리 청결",
        "main 브랜치",
        "태그 중복 없음",
        "CI 통과",
    ]


@pytest.mark.parametrize(
    ("change", "expected_name"),
    [
        ("dirty", "작업 트리 청결"),
        ("branch", "main 브랜치"),
        ("tag", "태그 중복 없음"),
        ("ci", "CI 통과"),
    ],
)
def test_readiness_failure_blocks_release(tmp_path: Path, change: str, expected_name: str) -> None:
    repo = _new_repo(tmp_path)
    ci_checker = _successful_ci

    if change == "dirty":
        (repo / "uncommitted.txt").write_text("change\n", encoding="utf-8")
    elif change == "branch":
        _git(repo, "checkout", "-b", "feature/release")
    elif change == "tag":
        _git(repo, "tag", "v0.2.0")
    else:
        ci_checker = _failed_ci

    report = readiness.check_readiness(repo, repository="owner/repo", ci_checker=ci_checker)

    assert not report.passed
    failed = {check.name for check in report.checks if not check.passed}
    assert expected_name in failed


def test_release_notes_use_only_commits_after_previous_tag(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path, version="0.1.0")
    _git(repo, "tag", "v0.1.0")
    (repo / "source.txt").write_text("feature\n", encoding="utf-8")
    _git(repo, "add", "source.txt")
    _git(repo, "commit", "-m", "feat: add release feature")
    (repo / "source.txt").write_text("bugfix\n", encoding="utf-8")
    _git(repo, "add", "source.txt")
    _git(repo, "commit", "-m", "fix(api): correct release bug")
    (repo / "source.txt").write_text("docs\n", encoding="utf-8")
    _git(repo, "add", "source.txt")
    _git(repo, "commit", "-m", "docs: explain release process")
    (repo / "source.txt").write_text("misc\n", encoding="utf-8")
    _git(repo, "add", "source.txt")
    _git(repo, "commit", "-m", "merge legacy branch")

    notes = readiness.generate_release_notes(repo, "v0.2.0")

    assert "## feat" in notes
    assert "add release feature" in notes
    assert "## fix" in notes
    assert "correct release bug" in notes
    assert "## docs" in notes
    assert "explain release process" in notes
    assert "## 기타" in notes
    assert "merge legacy branch" in notes
    assert "initialize test repository" not in notes


def test_notes_reject_tag_that_does_not_match_project_version(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path, version="0.2.0")
    output = tmp_path / "notes.md"

    result = readiness.main(
        [
            "--repo-root",
            str(repo),
            "--tag",
            "v0.9.0",
            "--notes-output",
            str(output),
        ]
    )

    assert result == 1
    assert not output.exists()
