#!/usr/bin/env python3
"""검증된 finalize 증거가 있을 때만 작업 브랜치를 병합합니다."""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - 고정된 인자 목록으로만 git을 호출합니다
import sys
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]


def evidence_errors(evidence: object) -> list[str]:
    """병합에 필요한 strict finalize 및 Level 1 PASS 증거를 검사합니다."""
    if not isinstance(evidence, Mapping):
        return ["검증 증거가 JSON 객체가 아닙니다."]

    errors: list[str] = []
    if evidence.get("strict") is not True:
        errors.append("strict finalize 실행 증거가 없습니다.")
    if evidence.get("exit_code") != 0:
        errors.append("finalize 종료 코드 0 증거가 없습니다.")

    level1 = evidence.get("level1")
    if not isinstance(level1, Mapping) or level1.get("verdict") != "pass":
        errors.append("Level 1 PASS 증거가 없습니다.")
    elif "exit_code" in level1 and level1["exit_code"] != 0:
        errors.append("Level 1 종료 코드 0 증거가 없습니다.")

    reviewer = evidence.get("reviewer")
    if not isinstance(reviewer, Mapping) or (
        reviewer.get("effective_verdict", reviewer.get("verdict")) != "pass"
    ):
        errors.append("strict finalize의 리뷰 PASS 증거가 없습니다.")
    return errors


def load_evidence(path: Path) -> tuple[dict[str, Any] | None, list[str]]:
    """명시한 JSON 증거 레코드를 읽고 fail-closed 방식으로 검증합니다."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [f"검증 증거를 읽을 수 없습니다: {exc}"]
    except json.JSONDecodeError as exc:
        return None, [f"검증 증거 JSON이 올바르지 않습니다: {exc.msg}"]
    return data if isinstance(data, dict) else None, evidence_errors(data)


def run_git(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
    """셸 없이 git 명령을 실행합니다."""
    return subprocess.run(  # nosec B603 - 호출부가 고정 토큰 목록을 전달합니다
        list(cmd), capture_output=True, text=True, check=False
    )


def merge_verified_branch(
    *,
    source_branch: str,
    target_branch: str,
    evidence_path: Path,
    message: str | None = None,
    runner: Runner = run_git,
) -> tuple[int, str]:
    """증거와 현재 대상 브랜치를 확인한 경우에만 ``git merge``를 실행합니다."""
    _evidence, errors = load_evidence(evidence_path)
    if errors:
        return 1, "병합 거부: " + " ".join(errors)

    current = runner(["git", "branch", "--show-current"])
    if current.returncode != 0:
        return 2, f"현재 브랜치를 확인할 수 없습니다: {current.stderr.strip()}"
    if current.stdout.strip() != target_branch:
        return 1, f"병합 거부: 현재 브랜치가 대상({target_branch})이 아닙니다."

    command = ["git", "merge", "--no-ff", source_branch]
    if message:
        command.extend(["-m", message])
    merged = runner(command)
    if merged.returncode != 0:
        return 1, f"병합 실패: {merged.stderr.strip() or merged.stdout.strip()}"
    return 0, f"병합 완료: {source_branch} -> {target_branch}"


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="검증 증거 기반 fail-closed 병합 도구")
    parser.add_argument("--source-branch", required=True, help="병합할 검증 완료 작업 브랜치")
    parser.add_argument(
        "--target-branch", default="main", help="현재 체크아웃되어야 할 대상 브랜치"
    )
    parser.add_argument(
        "--finalize-evidence", required=True, type=Path, help="strict finalize JSON 증거"
    )
    parser.add_argument("--message", help="선택적 git merge 커밋 메시지")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_arguments(argv)
    code, output = merge_verified_branch(
        source_branch=args.source_branch,
        target_branch=args.target_branch,
        evidence_path=args.finalize_evidence,
        message=args.message,
    )
    stream = sys.stdout if code == 0 else sys.stderr
    print(output, file=stream)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
