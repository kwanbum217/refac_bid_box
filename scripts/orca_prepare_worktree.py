#!/usr/bin/env python3
"""
scripts/orca_prepare_worktree.py

워커 워크트리 준비 도구.

워크트리 생성 후 필수적인 3가지 사전 준비를 한 번에 처리합니다:
  1. .env 파일 배치 (Git 미추적 파일 복사)
  2. Antigravity 워크스페이스 신뢰 사전 등록 (다이얼로그 차단 방지)
  3. Git pre-commit 훅 확인 및 설치 (검증 생략 커밋 방지)

옵션:
  --check: 변경 없이 3개 항목의 준비 상태만 판정하여 미준비 시 종료 코드 1을 반환합니다.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess  # nosec B404 - 고정된 인자 목록으로만 git 및 pre-commit 을 호출합니다
import sys
from pathlib import Path

try:
    from scripts import orca_trust_worktree
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts import orca_trust_worktree


def git_common_dir(path: Path) -> Path | None:
    """Git common directory를 반환하고, Git 저장소가 아니면 None을 반환합니다."""
    resolved = path.resolve()
    try:
        res = subprocess.run(  # nosec B603 B607 - 고정 인자로 git common dir 확인
            ["git", "-C", str(resolved), "rev-parse", "--git-common-dir"],
            capture_output=True,
            text=True,
            check=True,
        )
        raw_dir = res.stdout.strip()
        if not raw_dir:
            return None
        common_dir = Path(raw_dir)
        if not common_dir.is_absolute():
            common_dir = (resolved / common_dir).resolve()
        return common_dir
    except (subprocess.SubprocessError, OSError):
        return None


def resolve_main_repo(worktree: Path, explicit_repo: Path | None = None) -> Path | None:
    """워크트리의 Git common directory에서 주 저장소 경로를 확정합니다."""
    if explicit_repo is not None:
        return explicit_repo.resolve() if explicit_repo.is_dir() else None

    common_dir = git_common_dir(worktree)
    if common_dir is None:
        return None
    return common_dir.parent if common_dir.name == ".git" else None


def validate_worktree_ownership(worktree: Path, repo: Path | None) -> tuple[bool, str]:
    """대상과 주 저장소가 같은 Git common directory를 공유하는지 검증합니다."""
    if repo is None:
        return False, "오류: 주 저장소를 Git common directory에서 확인할 수 없습니다"

    worktree_common = git_common_dir(worktree)
    repo_common = git_common_dir(repo)
    if worktree_common is None or repo_common is None:
        return False, "오류: 대상과 주 저장소는 모두 유효한 Git worktree여야 합니다"
    if worktree_common != repo_common:
        return False, "오류: 대상 워크트리와 주 저장소의 Git common directory가 일치하지 않습니다"
    return True, ""


def check_or_prepare_env(worktree: Path, repo: Path, check: bool) -> tuple[bool, str]:
    """1단계: .env 배치 확인 및 복사.

    보안 규칙: .env 의 실제 값을 출력하거나 로그에 남기지 않습니다.
    """
    wt_env = (worktree / ".env").resolve()
    repo_env = (repo / ".env").resolve()

    if wt_env.is_file():
        return True, f"[.env] 이미 준비됨: {wt_env}"

    if check:
        return False, f"[.env] 미준비: .env 파일 없음 ({wt_env})"

    if not repo_env.is_file():
        return False, f"[.env] 오류: 주 저장소에 .env 파일이 없습니다 ({repo_env})"

    try:
        shutil.copy2(repo_env, wt_env)
        return True, f"[.env] 복사 완료: {repo_env} -> {wt_env}"
    except OSError as exc:
        return False, f"[.env] 복사 실패: {exc}"


def is_workspace_trusted(worktree: Path) -> bool:
    """Antigravity 신뢰 목록에 등록되어 있는지 확인합니다."""
    resolved = worktree.resolve()
    settings_path = orca_trust_worktree.CLI_SETTINGS
    trusted_folders_path = orca_trust_worktree.TRUSTED_FOLDERS

    # 1. settings.json trustedWorkspaces 확인
    if not settings_path.is_file():
        return False
    try:
        settings_data = json.loads(settings_path.read_text(encoding="utf-8"))
        workspaces = settings_data.get("trustedWorkspaces")
        if not isinstance(workspaces, list) or str(resolved) not in {str(w) for w in workspaces}:
            return False
    except (OSError, json.JSONDecodeError):
        return False

    # 2. trustedFolders.json 확인
    if not trusted_folders_path.is_file():
        return False
    try:
        folders_data = json.loads(trusted_folders_path.read_text(encoding="utf-8"))
        if not isinstance(folders_data, dict) or str(resolved).lower() not in folders_data:
            return False
    except (OSError, json.JSONDecodeError):
        return False

    return True


def check_or_prepare_trust(worktree: Path, check: bool) -> tuple[bool, str]:
    """2단계: Antigravity 신뢰 등록 확인 및 수행."""
    resolved = worktree.resolve()
    if is_workspace_trusted(resolved):
        return True, f"[신뢰] 이미 신뢰됨: {resolved}"

    if check:
        return False, f"[신뢰] 미준비: Antigravity 신뢰 목록에 미등록 ({resolved})"

    code = orca_trust_worktree.register([resolved], dry_run=False)
    if code == 0:
        return True, f"[신뢰] 등록 완료: {resolved}"
    return False, f"[신뢰] 등록 실패 (코드 {code}): {resolved}"


def get_git_hooks_path(worktree: Path) -> Path | None:
    """워크트리가 사용할 Git hooks 디렉터리 경로를 조회합니다."""
    resolved = worktree.resolve()
    try:
        res = subprocess.run(  # nosec B603 B607 - 고정 인자로 git hooks 경로 조회
            ["git", "-C", str(resolved), "rev-parse", "--git-path", "hooks"],
            capture_output=True,
            text=True,
            check=True,
        )
        raw_path = res.stdout.strip()
        if not raw_path:
            return None
        hooks_dir = Path(raw_path)
        if not hooks_dir.is_absolute():
            hooks_dir = (resolved / hooks_dir).resolve()
        return hooks_dir
    except (subprocess.SubprocessError, OSError):
        git_dir = resolved / ".git"
        if git_dir.is_dir():
            return (git_dir / "hooks").resolve()
        return None


def is_pre_commit_installed(worktree: Path) -> bool:
    """Git hooks 디렉터리에 pre-commit 실행 스크립트가 설치되어 있는지 확인합니다."""
    hooks_dir = get_git_hooks_path(worktree)
    if not hooks_dir:
        return False
    hook_file = hooks_dir / "pre-commit"
    if not hook_file.is_file():
        return False
    if not os.access(hook_file, os.X_OK):
        return False
    try:
        content = hook_file.read_text(encoding="utf-8", errors="ignore")
        return "pre-commit" in content or "pre_commit" in content
    except OSError:
        return False


def install_pre_commit_hook(worktree: Path, repo: Path) -> tuple[bool, str]:
    """Git pre-commit 훅을 설치합니다."""
    resolved_wt = worktree.resolve()
    resolved_repo = repo.resolve()

    # uv run --project <repo> pre-commit install 시도
    candidates = [
        ["uv", "run", "pre-commit", "install", "--config", ".pre-commit-config.yaml"],
        [
            "uv",
            "run",
            "--project",
            str(resolved_repo),
            "pre-commit",
            "install",
            "--config",
            ".pre-commit-config.yaml",
        ],
        ["pre-commit", "install", "--config", ".pre-commit-config.yaml"],
    ]

    last_error = ""
    for cmd in candidates:
        try:
            res = subprocess.run(  # nosec B603 B607 - 고정 인자로 pre-commit install 실행
                cmd,
                cwd=str(resolved_wt),
                capture_output=True,
                text=True,
                check=False,
            )
            if res.returncode == 0:
                hooks_dir = get_git_hooks_path(resolved_wt)
                hook_file = (hooks_dir / "pre-commit") if hooks_dir else "pre-commit"
                return True, f"[pre-commit] 설치 완료: {hook_file}"
            last_error = res.stderr.strip() or res.stdout.strip()
        except (FileNotFoundError, OSError, subprocess.SubprocessError) as exc:
            last_error = str(exc)
            continue

    return False, f"[pre-commit] 설치 실패: {last_error}"


def check_or_prepare_pre_commit(worktree: Path, repo: Path, check: bool) -> tuple[bool, str]:
    """3단계: pre-commit 훅 확인 및 설치."""
    resolved_wt = worktree.resolve()
    hooks_dir = get_git_hooks_path(resolved_wt)
    hook_file = (hooks_dir / "pre-commit") if hooks_dir else Path("pre-commit")

    if is_pre_commit_installed(resolved_wt):
        return True, f"[pre-commit] 이미 준비됨: pre-commit 훅 정상 ({hook_file})"

    if check:
        return False, f"[pre-commit] 미준비: pre-commit 훅이 설치되지 않음 ({hook_file})"

    return install_pre_commit_hook(resolved_wt, repo)


def prepare_worktree(
    worktree_path: Path,
    main_repo_path: Path | None = None,
    check: bool = False,
) -> int:
    """워크트리 준비 전체 파이프라인을 실행합니다."""
    wt = worktree_path.resolve()
    if not wt.exists() or not wt.is_dir():
        print(f"오류: 유효한 워크트리 디렉터리가 아닙니다: {wt}", file=sys.stderr)
        return 1

    repo = resolve_main_repo(wt, main_repo_path)
    valid, message = validate_worktree_ownership(wt, repo)
    if not valid:
        print(message, file=sys.stderr)
        return 1
    assert repo is not None

    steps = [
        check_or_prepare_env(wt, repo, check),
        check_or_prepare_trust(wt, check),
        check_or_prepare_pre_commit(wt, repo, check),
    ]

    all_passed = True
    for success, message in steps:
        print(message)
        if not success:
            all_passed = False

    return 0 if all_passed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="워커 워크트리 준비 도구 (.env 복사, Antigravity 신뢰 등록, pre-commit 훅 설치)"
    )
    parser.add_argument("worktree", type=Path, help="준비할 워크트리 경로")
    parser.add_argument(
        "repo",
        nargs="?",
        default=None,
        type=Path,
        help="주 저장소 경로 (기본값: 자동 감지)",
    )
    parser.add_argument(
        "--repo",
        dest="repo_opt",
        default=None,
        type=Path,
        help="주 저장소 경로 명시",
    )
    parser.add_argument(
        "--check",
        action="store_true",
        help="상태를 변경하지 않고 준비 여부만 검사 (미준비 시 종료 코드 1)",
    )

    args = parser.parse_args(argv)
    explicit_repo = args.repo_opt or args.repo
    return prepare_worktree(args.worktree, explicit_repo, check=args.check)


if __name__ == "__main__":
    raise SystemExit(main())
