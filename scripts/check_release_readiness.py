#!/usr/bin/env python3
"""릴리스에 필요한 사전 조건과 태그·릴리스 노트를 검사합니다."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404 - git 하위 명령과 고정된 GitHub API 조회에만 사용합니다.
import sys
import tomllib
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

COMMIT_TYPES = ("feat", "fix", "docs", "refactor", "chore", "test", "ci")
COMMIT_PATTERN = re.compile(
    r"^(?P<type>feat|fix|docs|refactor|chore|test|ci)(?:\([^)]*\))?!?:\s*(?P<subject>.+)$"
)


class ReleaseReadinessError(RuntimeError):
    """릴리스 준비 검사에 필요한 정보를 읽지 못했을 때 발생합니다."""


@dataclass(frozen=True)
class ReadinessCheck:
    """개별 릴리스 준비 검사 결과입니다."""

    name: str
    passed: bool
    detail: str


@dataclass(frozen=True)
class ReadinessReport:
    """릴리스 준비 검사 전체 결과입니다."""

    version: str
    tag: str
    checks: tuple[ReadinessCheck, ...]

    @property
    def passed(self) -> bool:
        return all(check.passed for check in self.checks)


def _git(repo_root: Path, *args: str, check: bool = True) -> str:
    """저장소 루트에서 git 명령을 실행하고 표준 출력을 반환합니다."""
    completed = subprocess.run(  # nosec B603, B607 - 실행 파일과 인자를 직접 고정합니다.
        ["git", *args],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )
    if check and completed.returncode != 0:
        detail = completed.stderr.strip() or completed.stdout.strip()
        raise ReleaseReadinessError(f"git {' '.join(args)} 실행에 실패했습니다: {detail}")
    return completed.stdout.strip()


def read_project_version(pyproject_path: Path) -> str:
    """pyproject.toml의 project.version을 릴리스 버전으로 읽습니다."""
    try:
        with pyproject_path.open("rb") as file:
            project = tomllib.load(file)["project"]
            version = project["version"]
    except (OSError, KeyError, TypeError, tomllib.TOMLDecodeError) as exc:
        raise ReleaseReadinessError(
            f"{pyproject_path}에서 project.version을 읽지 못했습니다: {exc}"
        ) from exc

    if not isinstance(version, str) or not version.strip():
        raise ReleaseReadinessError("pyproject.toml의 project.version이 비어 있습니다.")
    return version.strip()


def release_tag(version: str, tag_prefix: str = "v") -> str:
    """프로젝트 버전에서 릴리스 태그를 파생합니다."""
    return f"{tag_prefix}{version}"


def check_ci_passed(
    repository: str | None,
    commit_sha: str,
    token: str | None,
    api_url: str = "https://api.github.com",
) -> tuple[bool, str]:
    """대상 커밋의 가장 최근 CI 워크플로 실행이 성공했는지 확인합니다."""
    if not repository:
        return False, "GITHUB_REPOSITORY가 없어 CI 실행을 확인할 수 없습니다."
    if not token:
        return False, "GITHUB_TOKEN이 없어 CI 실행을 확인할 수 없습니다."
    parsed_api_url = urlparse(api_url)
    if parsed_api_url.scheme != "https" or not parsed_api_url.netloc:
        return False, "GitHub Actions API URL은 HTTPS 주소여야 합니다."

    query = urlencode({"head_sha": commit_sha, "per_page": "100"})
    endpoint = f"{api_url.rstrip('/')}/repos/{quote(repository, safe='/')}/actions/runs?{query}"
    request = urllib.request.Request(
        endpoint,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "refac-bid-box-release-readiness",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )

    try:
        with urllib.request.urlopen(  # nosec B310 - HTTPS GitHub API URL만 구성합니다.
            request, timeout=20
        ) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, urllib.error.HTTPError) as exc:
        return False, f"GitHub Actions CI 실행 조회에 실패했습니다: {exc}"
    except (ValueError, json.JSONDecodeError) as exc:
        return False, f"GitHub Actions 응답을 해석하지 못했습니다: {exc}"

    runs = payload.get("workflow_runs", []) if isinstance(payload, dict) else []
    ci_runs = [
        run
        for run in runs
        if isinstance(run, dict)
        and run.get("head_sha") == commit_sha
        and (
            run.get("name") == "CI"
            or str(run.get("path", "")).endswith("/.github/workflows/ci.yml")
            or str(run.get("path", "")) == ".github/workflows/ci.yml"
        )
    ]
    if not ci_runs:
        return False, f"커밋 {commit_sha[:12]}에 대한 CI 실행을 찾지 못했습니다."

    latest = max(ci_runs, key=lambda run: (run.get("id", 0), run.get("run_number", 0)))
    status = latest.get("status")
    conclusion = latest.get("conclusion")
    run_id = latest.get("id", "알 수 없음")
    if status != "completed" or conclusion != "success":
        return (
            False,
            f"CI 실행 {run_id}이 성공하지 않았습니다 (status={status}, conclusion={conclusion}).",
        )
    return True, f"CI 실행 {run_id}이 성공했습니다."


def _tag_exists(repo_root: Path, tag: str) -> bool:
    result = subprocess.run(  # nosec B603, B607 - git 태그 참조만 조회합니다.
        ["git", "show-ref", "--tags", "--verify", "--quiet", f"refs/tags/{tag}"],
        cwd=repo_root,
        capture_output=True,
        check=False,
        text=True,
    )
    if result.returncode not in (0, 1):
        detail = result.stderr.strip() or result.stdout.strip()
        raise ReleaseReadinessError(f"태그 존재 여부를 확인하지 못했습니다: {detail}")
    return result.returncode == 0


def check_readiness(
    repo_root: Path,
    *,
    expected_branch: str = "main",
    tag_prefix: str = "v",
    repository: str | None = None,
    commit_sha: str | None = None,
    token: str | None = None,
    api_url: str = "https://api.github.com",
    ci_checker: Callable[[str | None, str, str | None, str], tuple[bool, str]] | None = None,
) -> ReadinessReport:
    """릴리스 진행 여부를 결정하는 네 가지 필수 조건을 검사합니다."""
    version = read_project_version(repo_root / "pyproject.toml")
    tag = release_tag(version, tag_prefix)
    resolved_sha = commit_sha or _git(repo_root, "rev-parse", "HEAD")

    status = _git(repo_root, "status", "--porcelain=v1", "--untracked-files=all")
    branch = _git(repo_root, "branch", "--show-current")
    ci_check = (ci_checker or check_ci_passed)(repository, resolved_sha, token, api_url)

    tag_exists = _tag_exists(repo_root, tag)
    checks = (
        ReadinessCheck(
            "작업 트리 청결",
            not bool(status),
            "작업 트리가 깨끗합니다." if not status else "커밋되지 않은 변경 또는 파일이 있습니다.",
        ),
        ReadinessCheck(
            "main 브랜치",
            branch == expected_branch,
            f"현재 브랜치: {branch or '(detached HEAD)'}; 요구 브랜치: {expected_branch}",
        ),
        ReadinessCheck(
            "태그 중복 없음",
            not tag_exists,
            f"생성 예정 태그: {tag}" if not tag_exists else f"이미 존재하는 태그: {tag}",
        ),
        ReadinessCheck("CI 통과", ci_check[0], ci_check[1]),
    )
    return ReadinessReport(version=version, tag=tag, checks=checks)


def _previous_release_tag(repo_root: Path, current_tag: str) -> str | None:
    prefix = re.match(r"^[^0-9]*", current_tag)
    tag_prefix = prefix.group(0) if prefix else ""
    tags = _git(repo_root, "tag", "--list", f"{tag_prefix}*", "--sort=-version:refname")
    for tag in tags.splitlines():
        if tag and tag != current_tag:
            return tag
    return None


def _commits_since_tag(repo_root: Path, previous_tag: str | None) -> list[tuple[str, str]]:
    revision = f"{previous_tag}..HEAD" if previous_tag else "HEAD"
    output = _git(repo_root, "log", "--format=%H%x09%s", revision)
    commits: list[tuple[str, str]] = []
    for line in output.splitlines():
        commit_sha, separator, subject = line.partition("\t")
        if separator:
            commits.append((commit_sha, subject))
    return commits


def generate_release_notes(repo_root: Path, tag: str) -> str:
    """직전 릴리스 태그 이후 커밋을 type별 Markdown으로 묶습니다."""
    previous_tag = _previous_release_tag(repo_root, tag)
    grouped: dict[str, list[tuple[str, str]]] = {commit_type: [] for commit_type in COMMIT_TYPES}
    grouped["other"] = []

    for commit_sha, subject in _commits_since_tag(repo_root, previous_tag):
        match = COMMIT_PATTERN.match(subject)
        if match:
            group = match.group("type")
            rendered_subject = match.group("subject").strip()
        else:
            group = "other"
            rendered_subject = subject.strip()
        grouped[group].append((commit_sha[:7], rendered_subject))

    sections: list[str] = []
    for group in (*COMMIT_TYPES, "other"):
        commits = grouped[group]
        if not commits:
            continue
        heading = "기타" if group == "other" else group
        lines = [f"## {heading}"]
        lines.extend(f"- {subject} ({commit_sha})" for commit_sha, subject in commits)
        sections.append("\n".join(lines))
    return "\n\n".join(sections) if sections else "변경 사항이 없습니다."


def _write_github_output(path: Path, report: ReadinessReport) -> None:
    with path.open("a", encoding="utf-8") as file:
        file.write(f"version={report.version}\n")
        file.write(f"tag={report.tag}\n")


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--expected-branch", default="main")
    parser.add_argument("--tag-prefix", default="v")
    parser.add_argument("--repository", default=os.environ.get("GITHUB_REPOSITORY"))
    parser.add_argument("--commit", dest="commit_sha")
    parser.add_argument("--token", default=os.environ.get("GITHUB_TOKEN"))
    parser.add_argument(
        "--api-url", default=os.environ.get("GITHUB_API_URL", "https://api.github.com")
    )
    parser.add_argument("--github-output", type=Path)
    parser.add_argument("--notes-output", type=Path)
    parser.add_argument("--tag")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    try:
        if args.notes_output:
            version = read_project_version(repo_root / "pyproject.toml")
            expected_tag = release_tag(version, args.tag_prefix)
            if args.tag and args.tag != expected_tag:
                raise ReleaseReadinessError(
                    f"전달된 태그 {args.tag}가 pyproject.toml에서 파생한 태그 {expected_tag}와 다릅니다."
                )
            args.notes_output.write_text(
                generate_release_notes(repo_root, args.tag or expected_tag) + "\n",
                encoding="utf-8",
            )
            return 0

        report = check_readiness(
            repo_root,
            expected_branch=args.expected_branch,
            tag_prefix=args.tag_prefix,
            repository=args.repository,
            commit_sha=args.commit_sha,
            token=args.token,
            api_url=args.api_url,
        )
    except ReleaseReadinessError as exc:
        print(f"릴리스 준비 상태 검사 실패: {exc}", file=sys.stderr)
        return 1

    print(f"릴리스 버전: {report.version}")
    print(f"릴리스 태그: {report.tag}")
    for check in report.checks:
        state = "통과" if check.passed else "실패"
        print(f"[{state}] {check.name}: {check.detail}")
    if not report.passed:
        print("릴리스 준비 상태가 충족되지 않아 릴리스를 중단합니다.", file=sys.stderr)
        return 1
    if args.github_output:
        _write_github_output(args.github_output, report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
