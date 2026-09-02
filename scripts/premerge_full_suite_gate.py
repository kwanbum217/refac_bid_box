#!/usr/bin/env python3
"""
scripts/premerge_full_suite_gate.py

main 브랜치 병합 시 전량 테스트 실행 및 통과 증거를 기계적으로 검증하는 게이트 스크립트입니다.
pre-commit 프레임워크의 prepare-commit-msg 스테이지에서 실행되어, 병합 커밋(commit source == "merge")
생성 시점에 전량 테스트 통과 증거 없이 수동 git merge 또는 도구 병합이 이루어지는 것을
fail-closed 방식으로 차단합니다. 일반 커밋(message, template, squash, commit 등)은 즉시 통과합니다.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import re
import shlex
import subprocess  # nosec B404 - 고정된 인자 목록으로만 git 및 pytest를 호출합니다
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

DEFAULT_EVIDENCE_PATH = Path(".cache/premerge_full_suite_evidence.json")
BYPASS_ENV_VAR = "BYPASS_PREMERGE_FULL_SUITE_GATE"
CANONICAL_FULL_SUITE_CMD = ["uv", "run", "pytest", "tests/", "-q", "-m", "not data_assets"]


def run_process(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """셸 없이 고정 토큰 인자 목록으로 프로세스를 실행합니다."""
    return subprocess.run(  # nosec B603 - 호출부가 고정 토큰 목록을 전달합니다
        list(cmd),
        capture_output=True,
        text=True,
        check=False,
    )


def is_bypass_active() -> bool:
    """우회 환경변수가 설정되어 있는지 단일 판정합니다."""
    val = os.environ.get(BYPASS_ENV_VAR, "").strip().lower()
    return val in {"1", "true", "yes"}


def is_full_suite_command(command: str) -> tuple[bool, str]:
    """테스트 실행 명령이 개별 파일/노드가 아닌 전량 테스트(tests/)를 대상으로 하는지 검증합니다."""
    if not command or not command.strip():
        return False, "증거에 테스트 실행 명령(command)이 누락되었거나 비어 있습니다."

    try:
        tokens = shlex.split(command)
    except ValueError as exc:
        return False, f"명령 구문 분석 실패: {exc}"

    if not any("pytest" in tok for tok in tokens):
        return False, f"pytest 실행 명령이 아닙니다: {command}"

    # 개별 테스트 파일(.py)이나 노드 ID(::)가 인자로 포함되어 있는지 검사
    for tok in tokens:
        if tok.endswith(".py") or ".py::" in tok or "::" in tok:
            return False, f"전체 테스트가 아닌 특정 파일/테스트 대상 실행입니다: {tok}"

    # tests 전체 디렉터리가 대상에 포함되어 있는지 검사
    has_tests_target = any(tok in {"tests", "tests/", "./tests", "./tests/"} for tok in tokens)
    if not has_tests_target:
        return False, f"전체 테스트 디렉터리(tests/)가 대상에 포함되지 않았습니다: {command}"

    return True, ""


def parse_pytest_counts(summary: str) -> dict[str, int]:
    """pytest 요약 줄에서 passed, failed, skipped 건수를 추출합니다."""
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for match in re.finditer(r"(\d+)\s+(passed|failed|skipped|error|errors)", summary):
        val = int(match.group(1))
        key = match.group(2)
        if key.startswith("error"):
            key = "failed"
        counts[key] = counts.get(key, 0) + val
    return counts


def resolve_evidence_path(
    evidence_path: Path | None = None,
    runner: Runner = run_process,
) -> Path:
    """전량 테스트 증거 파일 경로를 해소합니다.

    지정되지 않았거나 기본 경로인 경우, git rev-parse --git-common-dir 를 기준으로
    주 저장소(main repo)의 .cache/premerge_full_suite_evidence.json 공통 위치를 반환합니다.
    이를 통해 워크트리에서 --record 한 증거를 주 저장소의 병합 훅에서 즉시 공유할 수 있습니다.
    """
    if evidence_path is not None and evidence_path != DEFAULT_EVIDENCE_PATH:
        return evidence_path

    proc = runner(["git", "rev-parse", "--git-common-dir"])
    if proc.returncode == 0 and proc.stdout.strip():
        common_dir_str = proc.stdout.strip()
        common_dir = Path(common_dir_str)
        if not common_dir.is_absolute():
            common_dir = (Path.cwd() / common_dir).resolve()
        else:
            common_dir = common_dir.resolve()

        if common_dir.name == ".git":
            repo_root = common_dir.parent
            return repo_root / DEFAULT_EVIDENCE_PATH
        return common_dir / DEFAULT_EVIDENCE_PATH

    return (Path.cwd() / DEFAULT_EVIDENCE_PATH).resolve()


def get_merge_head_sha(runner: Runner = run_process) -> tuple[str | None, str]:
    """prepare-commit-msg 훅 문맥에서 병합 대상 커밋(MERGE_HEAD) SHA를 조회합니다.

    1) `git rev-parse --verify MERGE_HEAD`로 조회하고,
    2) `git rev-parse --git-path MERGE_HEAD`로 파일 경로를 획득하여 직접 읽습니다.
    """
    # 1. git rev-parse --verify MERGE_HEAD
    verify_proc = runner(["git", "rev-parse", "--verify", "MERGE_HEAD"])
    if verify_proc.returncode == 0 and verify_proc.stdout.strip():
        return verify_proc.stdout.strip(), ""

    # 2. git rev-parse --git-path MERGE_HEAD 파일 직접 읽기
    path_proc = runner(["git", "rev-parse", "--git-path", "MERGE_HEAD"])
    if path_proc.returncode == 0 and path_proc.stdout.strip():
        merge_head_file_str = path_proc.stdout.strip()
        merge_head_path = Path(merge_head_file_str)
        if not merge_head_path.is_absolute():
            merge_head_path = (Path.cwd() / merge_head_path).resolve()

        if merge_head_path.exists():
            try:
                content = merge_head_path.read_text(encoding="utf-8").strip()
                lines = [line.strip() for line in content.splitlines() if line.strip()]
                if lines:
                    sha = lines[0]
                    sha_proc = runner(["git", "rev-parse", "--verify", f"{sha}^{{commit}}"])
                    if sha_proc.returncode == 0 and sha_proc.stdout.strip():
                        return sha_proc.stdout.strip(), ""
                    if re.fullmatch(r"[0-9a-fA-F]{7,64}", sha):
                        return sha, ""
            except OSError as exc:
                return None, f"MERGE_HEAD 파일({merge_head_path})을 읽을 수 없습니다: {exc}"

    return None, (
        "병합 대상 커밋(MERGE_HEAD)을 확인할 수 없습니다.\n"
        "prepare-commit-msg 단계가 아니거나 병합 커밋 생성이 진행 중이 아닙니다."
    )


def load_evidence(evidence_path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """전량 테스트 증거 파일을 읽고 fail-closed 방식으로 구조를 검증합니다."""
    if not evidence_path.exists():
        return None, [
            f"전량 테스트 증거 파일이 존재하지 않습니다 ({evidence_path}).\n"
            f"병합 전에 작업 브랜치에서 전량 테스트를 실행하고 증거를 기록하십시오:\n"
            f"  python3 scripts/premerge_full_suite_gate.py --record"
        ]

    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [f"전량 테스트 증거 파일을 읽을 수 없습니다 ({evidence_path}): {exc}"]
    except json.JSONDecodeError as exc:
        return None, [
            f"전량 테스트 증거 JSON 형식이 올바르지 않습니다 ({evidence_path}): {exc.msg}"
        ]

    if not isinstance(data, dict):
        return None, ["전량 테스트 증거 데이터가 JSON 객체(dict) 형식이 아닙니다."]

    return data, []


def verify_premerge_gate(
    *,
    target_branch: str = "main",
    evidence_path: Path | None = None,
    source_commit: str | None = None,
    commit_source: str | None = "merge",
    runner: Runner = run_process,
) -> tuple[int, str]:
    """main 브랜치 병합 시점에 전량 테스트 통과 증거를 검증합니다."""
    # 1. 단일 우회 수단 검사
    if is_bypass_active():
        warning_msg = (
            f"[경고] {BYPASS_ENV_VAR} 환경변수가 설정되어 전량 테스트 게이트를 우회합니다."
        )
        print(warning_msg, file=sys.stderr)
        return 0, warning_msg

    # 2. 커밋 소스(commit_source) 검사: prepare-commit-msg 단계에서 commit_source가 "merge"가 아니면
    # (예: 일반 커밋인 "message", "template", "commit", "squash", "none" 등) 즉시 통과
    if commit_source is not None and commit_source != "merge" and not source_commit:
        return 0, (
            f"[premerge-gate] 커밋 소스('{commit_source}')가 병합('merge')이 아니므로 검사를 건너뜁니다."
        )

    # 3. 현재 브랜치 확인 (main 브랜치 병합 커밋만 게이트 대상)
    current_branch_proc = runner(["git", "branch", "--show-current"])
    if current_branch_proc.returncode != 0:
        return 1, f"현재 브랜치를 확인할 수 없습니다: {current_branch_proc.stderr.strip()}"

    current_branch = current_branch_proc.stdout.strip()
    if current_branch != target_branch:
        return 0, (
            f"[premerge-gate] 현재 브랜치('{current_branch}')가 "
            f"게이트 대상 브랜치('{target_branch}')가 아니므로 검사를 건너뜁니다."
        )

    # 4. 병합 대상 커밋(source_commit / MERGE_HEAD) 확인
    merge_sha = source_commit
    if not merge_sha:
        head_sha, err_msg = get_merge_head_sha(runner=runner)
        if head_sha is None:
            return 1, err_msg
        merge_sha = head_sha
    else:
        sha_proc = runner(["git", "rev-parse", "--verify", f"{merge_sha}^{{commit}}"])
        if sha_proc.returncode != 0 or not sha_proc.stdout.strip():
            return (
                1,
                f"지정된 소스 커밋({merge_sha})을 확인할 수 없습니다: {sha_proc.stderr.strip()}",
            )
        merge_sha = sha_proc.stdout.strip()

    # 5. 증거 경로 해소 및 로드
    resolved_path = resolve_evidence_path(evidence_path, runner=runner)
    evidence, errors = load_evidence(resolved_path)
    if errors:
        return 1, "전량 테스트 게이트 검증 실패:\n" + "\n".join(errors)

    if evidence is None:
        return 1, "전량 테스트 증거가 없습니다."

    # 6. 전량 테스트 대상 검증 (개별 파일/부분 테스트 증거 기각)
    command_str = str(evidence.get("command", "")).strip()
    is_full_suite, cmd_err = is_full_suite_command(command_str)
    if not is_full_suite:
        return 1, (
            f"전량 테스트 증거가 아닙니다. 개별 파일이나 하위 집합만 실행된 증거는 병합 게이트를 통과할 수 없습니다.\n"
            f"  사유: {cmd_err}\n"
            f"  실행 명령: {command_str or '(없음)'}\n"
            f"전량 테스트 증거를 다시 생성하십시오:\n"
            f"  python3 scripts/premerge_full_suite_gate.py --record"
        )

    if evidence.get("suite") != "full" or evidence.get("target") != "tests/":
        return 1, (
            "증거의 suite 속성이 'full' 또는 target 속성이 'tests/'가 아닙니다. "
            "전량 테스트 증거가 필요합니다."
        )

    # 7. 증거 필드 검증: exit_code == 0
    ev_exit_code = evidence.get("exit_code")
    if ev_exit_code != 0:
        return 1, f"전량 테스트 증거의 종료 코드가 0이 아닙니다 (exit_code: {ev_exit_code})."

    # 8. 증거 필드 검증: commit 일치 여부
    ev_commit = str(evidence.get("commit", "")).strip()
    if not ev_commit:
        return 1, "전량 테스트 증거에 커밋 해시(commit)가 누락되었거나 비어 있습니다."

    ev_commit_proc = runner(["git", "rev-parse", "--verify", f"{ev_commit}^{{commit}}"])
    if ev_commit_proc.returncode != 0 or not ev_commit_proc.stdout.strip():
        if ev_commit != merge_sha:
            return 1, (
                f"전량 테스트 증거의 커밋({ev_commit})이 "
                f"병합 대상 커밋({merge_sha})과 일치하지 않습니다."
            )
    else:
        resolved_ev_commit = ev_commit_proc.stdout.strip()
        if resolved_ev_commit != merge_sha:
            return 1, (
                f"전량 테스트 증거의 커밋({resolved_ev_commit})이 "
                f"병합 대상 커밋({merge_sha})과 일치하지 않습니다."
            )

    return 0, f"[premerge-gate] 전량 테스트 증거 검증 통과 (commit: {merge_sha[:8]}, exit_code: 0)"


UTC_TZ = getattr(datetime, "UTC", datetime.timezone.utc)  # noqa: UP017


def record_evidence(
    *,
    evidence_path: Path | None = None,
    runner: Runner = run_process,
) -> tuple[int, str]:
    """현재 HEAD 커밋에 대해 전량 테스트를 실행하고 공통 증거 파일에 기록합니다."""
    head_proc = runner(["git", "rev-parse", "--verify", "HEAD"])
    if head_proc.returncode != 0 or not head_proc.stdout.strip():
        return 1, f"현재 HEAD 커밋을 확인할 수 없습니다: {head_proc.stderr.strip()}"
    head_sha = head_proc.stdout.strip()

    branch_proc = runner(["git", "branch", "--show-current"])
    branch_name = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""

    target_path = resolve_evidence_path(evidence_path, runner=runner)

    cmd = list(CANONICAL_FULL_SUITE_CMD)
    print(f"[premerge-gate] 전량 테스트 실행 중: {' '.join(cmd)}")

    test_proc = runner(cmd)
    summary_line = ""
    for line in reversed((test_proc.stdout + "\n" + test_proc.stderr).splitlines()):
        line_clean = line.strip()
        if line_clean and (
            "passed" in line_clean or "failed" in line_clean or "error" in line_clean
        ):
            summary_line = line_clean
            break

    counts = parse_pytest_counts(summary_line)

    target_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_data = {
        "suite": "full",
        "target": "tests/",
        "commit": head_sha,
        "branch": branch_name,
        "exit_code": test_proc.returncode,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "skipped": counts["skipped"],
        "summary": summary_line,
        "command": " ".join(cmd),
        "recorded_at": datetime.datetime.now(UTC_TZ).isoformat(),
    }

    try:
        target_path.write_text(
            json.dumps(evidence_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return 1, f"증거 파일 작성 실패 ({target_path}): {exc}"

    if test_proc.returncode != 0:
        return test_proc.returncode, (
            f"[premerge-gate] 전량 테스트 실패 (종료 코드: {test_proc.returncode}).\n"
            f"증거가 기록되었으나 실패 상태입니다: {summary_line}"
        )

    return 0, (
        f"[premerge-gate] 전량 테스트 통과 및 증거 기록 완료\n"
        f"  commit: {head_sha[:8]}\n"
        f"  summary: {summary_line}\n"
        f"  file: {target_path}"
    )


def install_git_hooks(runner: Runner = run_process) -> tuple[int, str]:
    """pre-commit 및 prepare-commit-msg git hook 을 모두 설치합니다."""
    git_dir_proc = runner(["git", "rev-parse", "--git-dir"])
    git_common_proc = runner(["git", "rev-parse", "--git-common-dir"])
    warning_str = ""
    if (
        git_dir_proc.returncode == 0
        and git_common_proc.returncode == 0
        and git_dir_proc.stdout.strip() != git_common_proc.stdout.strip()
    ):
        warning_str = (
            "\n[주의] 워크트리 환경에서 hook을 설치하면 INSTALL_PYTHON이 워크트리 venv를 가리켜 "
            "워크트리 삭제 시 훅이 손상될 수 있습니다. 주 저장소 루트에서 설치를 수행하십시오.\n"
        )

    cmd = [
        "uv",
        "run",
        "pre-commit",
        "install",
        "--hook-type",
        "pre-commit",
        "--hook-type",
        "prepare-commit-msg",
    ]
    proc = runner(cmd)
    if proc.returncode != 0:
        return proc.returncode, f"git hook 설치 실패:\n{proc.stderr.strip() or proc.stdout.strip()}"
    return (
        0,
        f"[premerge-gate] pre-commit 및 prepare-commit-msg 훅이 정상 설치되었습니다.{warning_str}",
    )


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="main 브랜치 병합 시 전량 테스트 통과 증거를 검증하는 게이트"
    )
    parser.add_argument(
        "commit_msg_file",
        nargs="?",
        default=None,
        help="커밋 메시지 파일 경로 (prepare-commit-msg 훅 1번째 인자)",
    )
    parser.add_argument(
        "commit_source",
        nargs="?",
        default=None,
        help="커밋 소스 유형 (prepare-commit-msg 훅 2번째 인자: merge, message, template, commit, squash 등)",
    )
    parser.add_argument(
        "commit_sha",
        nargs="?",
        default=None,
        help="커밋 SHA (prepare-commit-msg 훅 3번째 인자)",
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="현재 HEAD 커밋에 대해 전량 테스트를 실행하고 증거 파일을 기록합니다.",
    )
    parser.add_argument(
        "--install-hooks",
        action="store_true",
        help="pre-commit 및 prepare-commit-msg 훅을 Git 저장소에 설치합니다.",
    )
    parser.add_argument(
        "--target-branch",
        default="main",
        help="게이트를 강제할 대상 브랜치 이름 (기본값: main)",
    )
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=None,
        help=f"전량 테스트 증거 JSON 파일 경로 (기본값: 주 저장소 {DEFAULT_EVIDENCE_PATH})",
    )
    parser.add_argument(
        "--source-commit",
        help="검증할 소스 커밋 SHA (미지정 시 git MERGE_HEAD 사용)",
    )
    parser.add_argument(
        "--commit-source",
        dest="opt_commit_source",
        default=None,
        help="명시적 커밋 소스 지정 (merge, message 등)",
    )
    return parser.parse_args(argv)


def main(
    argv: Sequence[str] | None = None,
    runner: Runner = run_process,
) -> int:
    args = parse_arguments(argv)

    if args.install_hooks:
        code, message = install_git_hooks(runner=runner)
    elif args.record:
        code, message = record_evidence(
            evidence_path=args.evidence_path,
            runner=runner,
        )
    else:
        commit_src: str | None
        if args.opt_commit_source:
            commit_src = args.opt_commit_source
        elif args.commit_source:
            commit_src = args.commit_source
        elif args.commit_msg_file:
            commit_src = "none"
        else:
            commit_src = "merge"

        code, message = verify_premerge_gate(
            target_branch=args.target_branch,
            evidence_path=args.evidence_path,
            source_commit=args.source_commit,
            commit_source=commit_src,
            runner=runner,
        )

    stream = sys.stdout if code == 0 else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
