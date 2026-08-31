#!/usr/bin/env python3
"""
scripts/orca_scope_guard.py

Git pre-commit 스코프 가드.
워크트리의 Git 설정(orca.capsule)에 기록된 활성 Task Capsule 을 읽고,
staged 상태의 파일들이 allowed_write_files 범위 내에 있는지 fail-closed 로 검사합니다.

규칙:
  1. Capsule 설정이 없는 일반 개발 커밋은 검사를 통과합니다 (기존 동작 유지).
  2. Capsule 경로가 설정되었으나 파일이 없거나 파싱 불가하면 fail-closed 로 커밋을 거부합니다.
  3. allowed_write_files 가 비어 있는 읽기 전용 Task 는 모든 tracked staged 변경을 거부합니다.
  4. allowed_write_files 범위를 벗어난 파일이 staged 되어 있으면 커밋을 거부합니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
from pathlib import Path

try:
    from scripts.orca_contract import (
        load_capsule,
        parse_capsule_list,
        parse_capsule_scalar,
        write_scope_excess,
    )
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_contract import (
        load_capsule,
        parse_capsule_list,
        parse_capsule_scalar,
        write_scope_excess,
    )


def get_git_config_capsule(repo: Path) -> str | None:
    """Git 설정에서 활성 Capsule 경로를 조회합니다."""
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(repo), "config", "--get", "orca.capsule"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (subprocess.SubprocessError, OSError):  # nosec B110
        pass
    return None


def get_staged_files(repo: Path) -> list[str]:
    """Git staged 파일 목록을 반환합니다."""
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", "-C", str(repo), "diff", "--cached", "--name-only"],
            capture_output=True,
            text=True,
            check=False,
        )
        if proc.returncode == 0:
            return [line.strip() for line in proc.stdout.splitlines() if line.strip()]
    except (subprocess.SubprocessError, OSError):  # nosec B110
        pass
    return []


def check_scope(
    repo: Path,
    explicit_capsule: str | Path | None = None,
    as_json: bool = False,
) -> int:
    """staged 파일들의 스코프 허용 여부를 검증합니다."""
    repo = repo.resolve()
    capsule_path_str = str(explicit_capsule) if explicit_capsule else get_git_config_capsule(repo)

    # 1. Capsule 설정이 없는 일반 커밋은 검사 통과
    if not capsule_path_str:
        if as_json:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "active_capsule": None,
                        "message": "Capsule 설정이 없어 일반 커밋으로 허용합니다.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0

    capsule_file = Path(capsule_path_str)
    if not capsule_file.is_absolute():
        capsule_file = (repo / capsule_file).resolve()

    # 2. Capsule 경로가 지정되었으나 파일이 없거나 파싱 불가 시 fail-closed
    if not capsule_file.is_file():
        err_msg = f"설정된 Capsule 파일을 찾을 수 없습니다: {capsule_path_str} ({capsule_file})"
        sys.stderr.write(f"오류 [orca_scope_guard]: {err_msg}\n")
        if as_json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "origin": "capsule_spec_error",
                        "error": "capsule_file_not_found",
                        "reason": err_msg,
                        "capsule_path": capsule_path_str,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 1

    try:
        capsule_text = load_capsule(capsule_file)
        schema = parse_capsule_scalar(capsule_text, "schema")
        if schema != "ORCA_TASK_CAPSULE_V2":
            raise ValueError(f"유효한 Capsule 스키마가 아닙니다 (schema={schema})")
        allowed_write = parse_capsule_list(capsule_text, "allowed_write_files")
    except Exception as exc:
        err_msg = f"Capsule 파일 로드 또는 파싱 실패: {exc}"
        sys.stderr.write(f"오류 [orca_scope_guard]: {err_msg}\n")
        if as_json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "origin": "capsule_spec_error",
                        "error": "capsule_parse_failed",
                        "reason": err_msg,
                        "capsule_path": str(capsule_file),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 1

    staged_files = get_staged_files(repo)
    if not staged_files:
        if as_json:
            print(
                json.dumps(
                    {
                        "ok": True,
                        "active_capsule": str(capsule_file),
                        "staged_files": [],
                        "message": "staged 파일이 없습니다.",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 0

    # 3. 읽기 전용 Task (allowed_write_files 가 빈 목록)
    if not allowed_write:
        err_msg = (
            "읽기 전용 Task(allowed_write_files 가 비어 있음)에서는 변경사항을 커밋할 수 없습니다.\n"
            f"  staged 파일 ({len(staged_files)}개): {', '.join(staged_files)}"
        )
        sys.stderr.write(f"오류 [orca_scope_guard]: {err_msg}\n")
        if as_json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "origin": "worker_scope_violation",
                        "error": "readonly_task_commit_forbidden",
                        "reason": err_msg,
                        "staged_files": staged_files,
                        "allowed_write_files": [],
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 1

    # 4. 쓰기 범위 초과 파일 검사
    excess = write_scope_excess(staged_files, allowed_write)
    if excess:
        err_msg = (
            f"허용된 쓰기 범위(allowed_write_files) 밖의 파일이 staged 되었습니다.\n"
            f"  위반 파일 ({len(excess)}개): {', '.join(excess)}\n"
            f"  허용된 범위: {', '.join(allowed_write)}"
        )
        sys.stderr.write(f"오류 [orca_scope_guard]: {err_msg}\n")
        if as_json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "origin": "worker_scope_violation",
                        "error": "staged_files_out_of_scope",
                        "reason": err_msg,
                        "violations": excess,
                        "staged_files": staged_files,
                        "allowed_write_files": allowed_write,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 1

    if as_json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "active_capsule": str(capsule_file),
                    "staged_files": staged_files,
                    "allowed_write_files": allowed_write,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orca Worktree Scope Guard")
    parser.add_argument(
        "--capsule", help="활성 Capsule YAML 경로 (미지정 시 git config orca.capsule 조회)"
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Git 저장소/워크트리 경로")
    parser.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args(argv)
    return check_scope(
        repo=args.repo,
        explicit_capsule=args.capsule,
        as_json=args.json,
    )


if __name__ == "__main__":
    raise SystemExit(main())
