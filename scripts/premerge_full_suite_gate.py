#!/usr/bin/env python3
"""
scripts/premerge_full_suite_gate.py

main 브랜치 병합 시 전량 테스트 실행 및 통과 증거를 기계적으로 검증하는 게이트 스크립트입니다.
pre-commit 프레임워크의 pre-merge-commit 스테이지에서 실행되어, 전량 테스트 통과 증거 없이
수동 git merge 또는 도구 병합이 이루어지는 것을 fail-closed 방식으로 차단합니다.
"""

from __future__ import annotations

import argparse
import datetime
import json
import os
import subprocess  # nosec B404 - 고정된 인자 목록으로만 git 및 pytest를 호출합니다
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

DEFAULT_EVIDENCE_PATH = Path(".cache/premerge_full_suite_evidence.json")
BYPASS_ENV_VAR = "BYPASS_PREMERGE_FULL_SUITE_GATE"


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
        return None, [f"전량 테스트 증거 파일을 읽을 수 없습니다: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"전량 테스트 증거 JSON 형식이 올바르지 않습니다: {exc.msg}"]

    if not isinstance(data, dict):
        return None, ["전량 테스트 증거 데이터가 JSON 객체(dict) 형식이 아닙니다."]

    return data, []


def verify_premerge_gate(
    *,
    target_branch: str = "main",
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
    source_commit: str | None = None,
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

    # 2. 현재 브랜치 확인 (main 브랜치 병합 커밋만 게이트 대상)
    current_branch_proc = runner(["git", "branch", "--show-current"])
    if current_branch_proc.returncode != 0:
        return 1, f"현재 브랜치를 확인할 수 없습니다: {current_branch_proc.stderr.strip()}"

    current_branch = current_branch_proc.stdout.strip()
    if current_branch != target_branch:
        return 0, (
            f"[premerge-gate] 현재 브랜치('{current_branch}')가 "
            f"게이트 대상 브랜치('{target_branch}')가 아니므로 검사를 건너뜁니다."
        )

    # 3. 병합 대상 커밋(source_commit / MERGE_HEAD) 확인
    merge_sha = source_commit
    if not merge_sha:
        merge_head_proc = runner(["git", "rev-parse", "--verify", "MERGE_HEAD"])
        if merge_head_proc.returncode != 0 or not merge_head_proc.stdout.strip():
            return 1, (
                "병합 대상 커밋(MERGE_HEAD)을 확인할 수 없습니다.\n"
                "pre-merge-commit 단계가 아니거나 병합 커밋 생성이 진행 중이 아닙니다."
            )
        merge_sha = merge_head_proc.stdout.strip()
    else:
        sha_proc = runner(["git", "rev-parse", "--verify", f"{merge_sha}^{{commit}}"])
        if sha_proc.returncode != 0 or not sha_proc.stdout.strip():
            return (
                1,
                f"지정된 소스 커밋({merge_sha})을 확인할 수 없습니다: {sha_proc.stderr.strip()}",
            )
        merge_sha = sha_proc.stdout.strip()

    # 4. 증거 로드 및 fail-closed 검증
    evidence, errors = load_evidence(evidence_path)
    if errors:
        return 1, "전량 테스트 게이트 검증 실패:\n" + "\n".join(errors)

    if evidence is None:
        return 1, "전량 테스트 증거가 없습니다."

    # 5. 증거 필드 검증: exit_code == 0
    ev_exit_code = evidence.get("exit_code")
    if ev_exit_code != 0:
        return 1, f"전량 테스트 증거의 종료 코드가 0이 아닙니다 (exit_code: {ev_exit_code})."

    # 6. 증거 필드 검증: commit 일치 여부
    ev_commit = str(evidence.get("commit", "")).strip()
    if not ev_commit:
        return 1, "전량 테스트 증거에 커밋 해시(commit)가 누락되었거나 비어 있습니다."

    ev_commit_proc = runner(["git", "rev-parse", "--verify", f"{ev_commit}^{{commit}}"])
    if ev_commit_proc.returncode != 0 or not ev_commit_proc.stdout.strip():
        # git rev-parse 가 안 되더라도 문자열 일치 검사
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


def record_evidence(
    *,
    evidence_path: Path = DEFAULT_EVIDENCE_PATH,
    pytest_args: Sequence[str] | None = None,
    runner: Runner = run_process,
) -> tuple[int, str]:
    """현재 HEAD 커밋에 대해 전량 테스트를 실행하고 증거 파일을 기록합니다."""
    # 1. 현재 커밋 및 브랜치 확인
    head_proc = runner(["git", "rev-parse", "--verify", "HEAD"])
    if head_proc.returncode != 0 or not head_proc.stdout.strip():
        return 1, f"현재 HEAD 커밋을 확인할 수 없습니다: {head_proc.stderr.strip()}"
    head_sha = head_proc.stdout.strip()

    branch_proc = runner(["git", "branch", "--show-current"])
    branch_name = branch_proc.stdout.strip() if branch_proc.returncode == 0 else ""

    # 2. 테스트 명령 조립 및 실행
    args = list(pytest_args) if pytest_args else ["tests/", "-q"]
    cmd = ["uv", "run", "pytest", *args]
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

    # 3. 증거 디렉터리 생성 및 기록
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_data = {
        "commit": head_sha,
        "branch": branch_name,
        "exit_code": test_proc.returncode,
        "summary": summary_line,
        "command": " ".join(cmd),
        "recorded_at": datetime.datetime.now(datetime.UTC).isoformat(),
    }

    try:
        evidence_path.write_text(
            json.dumps(evidence_data, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except OSError as exc:
        return 1, f"증거 파일 작성 실패 ({evidence_path}): {exc}"

    if test_proc.returncode != 0:
        return test_proc.returncode, (
            f"[premerge-gate] 전량 테스트 실패 (종료 코드: {test_proc.returncode}).\n"
            f"증거가 기록되었으나 실패 상태입니다: {summary_line}"
        )

    return 0, (
        f"[premerge-gate] 전량 테스트 통과 및 증거 기록 완료\n"
        f"  commit: {head_sha[:8]}\n"
        f"  summary: {summary_line}\n"
        f"  file: {evidence_path}"
    )


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="main 브랜치 병합 시 전량 테스트 통과 증거를 검증하는 게이트"
    )
    parser.add_argument(
        "--record",
        action="store_true",
        help="현재 HEAD 커밋에 대해 전량 테스트를 실행하고 증거 파일을 기록합니다.",
    )
    parser.add_argument(
        "--target-branch",
        default="main",
        help="게이트를 강제할 대상 브랜치 이름 (기본값: main)",
    )
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=DEFAULT_EVIDENCE_PATH,
        help=f"전량 테스트 증거 JSON 파일 경로 (기본값: {DEFAULT_EVIDENCE_PATH})",
    )
    parser.add_argument(
        "--source-commit",
        help="검증할 소스 커밋 SHA (미지정 시 git MERGE_HEAD 사용)",
    )
    parser.add_argument(
        "--pytest-args",
        nargs=argparse.REMAINDER,
        help="--record 시 pytest 에 추가로 넘길 인자들",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_arguments(argv)

    if args.record:
        code, message = record_evidence(
            evidence_path=args.evidence_path,
            pytest_args=args.pytest_args,
        )
    else:
        code, message = verify_premerge_gate(
            target_branch=args.target_branch,
            evidence_path=args.evidence_path,
            source_commit=args.source_commit,
        )

    stream = sys.stdout if code == 0 else sys.stderr
    print(message, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
