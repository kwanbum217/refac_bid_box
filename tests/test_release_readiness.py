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


def test_release_notes_are_capped_under_github_body_limit(tmp_path: Path) -> None:
    repo = _new_repo(tmp_path, version="0.1.0")
    for index in range(40):
        (repo / "source.txt").write_text(f"change {index}\n", encoding="utf-8")
        _git(repo, "add", "source.txt")
        kind = "feat" if index % 2 else "fix"
        _git(repo, "commit", "-m", f"{kind}: change number {index:02d} " + "x" * 60)

    full = readiness.generate_release_notes(repo, "v0.1.0", max_chars=1_000_000)
    capped = readiness.generate_release_notes(repo, "v0.1.0", max_chars=900)

    assert len(full) > 900
    assert len(capped) <= 900
    assert "## feat" in capped
    assert "## fix" in capped
    assert "건은 생략했습니다" in capped
    assert "change number 39" in capped
    assert "change number 38" in capped


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


def test_release_tag_normalization_pep440_and_stable() -> None:
    """PEP 440 사전 릴리스 버전은 SemVer 태그로 정규화되고 정식 버전은 v 접두사만 유지해야 합니다."""
    # (1) 0.1.0rc1 -> v0.1.0-rc.1
    assert readiness.release_tag("0.1.0rc1") == "v0.1.0-rc.1"
    assert readiness.release_tag("1.2.0b2") == "v1.2.0-beta.2"
    assert readiness.release_tag("2.0.0a1") == "v2.0.0-alpha.1"

    # (2) 0.1.0 -> v0.1.0
    assert readiness.release_tag("0.1.0") == "v0.1.0"
    assert readiness.release_tag("2.4.1") == "v2.4.1"

    # tag_prefix 인자 동작 유지
    assert readiness.release_tag("0.1.0rc1", tag_prefix="") == "0.1.0-rc.1"
    assert readiness.release_tag("0.1.0", tag_prefix="") == "0.1.0"


def test_is_prerelease_and_readiness_report_flag(tmp_path: Path) -> None:
    """사전 릴리스 판정 함수 및 ReadinessReport 플래그가 참/거짓으로 정확히 설정되어야 합니다."""
    # (3) 사전 릴리스 판정 플래그가 두 경우에 각각 참과 거짓
    assert readiness.is_prerelease("0.1.0rc1") is True
    assert readiness.is_prerelease("1.2.0b2") is True
    assert readiness.is_prerelease("2.0.0a1") is True
    assert readiness.is_prerelease("0.1.0") is False
    assert readiness.is_prerelease("2.4.1") is False

    # 사전 릴리스 저장소 검사
    rc_dir = tmp_path / "rc"
    rc_dir.mkdir()
    repo_rc = _new_repo(rc_dir, version="0.1.0rc1")
    report_rc = readiness.check_readiness(
        repo_rc, repository="owner/repo", ci_checker=_successful_ci
    )
    assert report_rc.passed
    assert report_rc.version == "0.1.0rc1"
    assert report_rc.tag == "v0.1.0-rc.1"
    assert report_rc.is_prerelease is True
    assert report_rc.prerelease is True

    gh_output_rc = tmp_path / "gh_output_rc.txt"
    readiness._write_github_output(gh_output_rc, report_rc)
    output_rc_text = gh_output_rc.read_text(encoding="utf-8")
    assert "tag=v0.1.0-rc.1\n" in output_rc_text
    assert "prerelease=true\n" in output_rc_text
    assert "is_prerelease=true\n" in output_rc_text

    # 정식 릴리스 저장소 검사
    stable_dir = tmp_path / "stable"
    stable_dir.mkdir()
    repo_stable = _new_repo(stable_dir, version="0.1.0")
    report_stable = readiness.check_readiness(
        repo_stable, repository="owner/repo", ci_checker=_successful_ci
    )
    assert report_stable.passed
    assert report_stable.version == "0.1.0"
    assert report_stable.tag == "v0.1.0"
    assert report_stable.is_prerelease is False
    assert report_stable.prerelease is False

    gh_output_stable = tmp_path / "gh_output_stable.txt"
    readiness._write_github_output(gh_output_stable, report_stable)
    output_stable_text = gh_output_stable.read_text(encoding="utf-8")
    assert "tag=v0.1.0\n" in output_stable_text
    assert "prerelease=false\n" in output_stable_text
    assert "is_prerelease=false\n" in output_stable_text


def test_notes_tag_matching_with_normalized_prerelease_tag(tmp_path: Path) -> None:
    """(4) --notes-output 의 태그 대조가 정규화된 태그로 이뤄져야 합니다."""
    repo = _new_repo(tmp_path, version="0.1.0rc1")
    output = tmp_path / "notes.md"

    # 정규화된 태그 전달 시 성공
    result_ok = readiness.main(
        [
            "--repo-root",
            str(repo),
            "--tag",
            "v0.1.0-rc.1",
            "--notes-output",
            str(output),
        ]
    )
    assert result_ok == 0
    assert output.exists()
    assert "## chore" in output.read_text(encoding="utf-8")

    # 미정규화된 태그 전달 시 불일치로 거부
    output_err = tmp_path / "notes_err.md"
    result_err = readiness.main(
        [
            "--repo-root",
            str(repo),
            "--tag",
            "v0.1.0rc1",
            "--notes-output",
            str(output_err),
        ]
    )
    assert result_err == 1
    assert not output_err.exists()


def test_prerelease_tag_does_not_become_previous_tag_of_later_release(tmp_path: Path) -> None:
    """사전 릴리스 태그가 정식 태그보다 앞서 직전 태그로 뽑히면 안 됩니다.

    versionsort.suffix 없이 정렬하면 git 은 v0.1.0-rc.1 을 v0.1.0 보다 높게 둡니다.
    그 상태로 v0.2.0 노트를 만들면 범위가 v0.1.0-rc.1..HEAD 가 되어 v0.1.0 에서
    이미 발행한 커밋이 다시 들어갑니다.
    """
    repo = _new_repo(tmp_path, version="0.2.0")
    _git(repo, "tag", "v0.1.0-rc.1")
    (repo / "source.txt").write_text("stable\n", encoding="utf-8")
    _git(repo, "commit", "-am", "feat: 정식 릴리스에 담긴 변경")
    _git(repo, "tag", "v0.1.0")
    (repo / "source.txt").write_text("next\n", encoding="utf-8")
    _git(repo, "commit", "-am", "feat: 다음 릴리스에 담길 변경")

    assert readiness._previous_release_tag(repo, "v0.2.0") == "v0.1.0"

    notes = readiness.generate_release_notes(repo, "v0.2.0")
    assert "다음 릴리스에 담길 변경" in notes
    assert "정식 릴리스에 담긴 변경" not in notes
