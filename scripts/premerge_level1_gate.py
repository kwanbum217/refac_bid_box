#!/usr/bin/env python3
"""
scripts/premerge_level1_gate.py

main 브랜치 병합 시 Level 1 strict 게이트 통과 증거를 기계적으로 검증하는 게이트 스크립트입니다.
pre-commit 프레임워크의 prepare-commit-msg 스테이지에서 실행되어, 병합 커밋(commit source == "merge")
생성 시점에 Level 1 strict 통과 증거 없이 수동 git merge 또는 도구 병합이 이루어지는 것을
fail-closed 방식으로 차단합니다. 일반 커밋(message, template, squash, commit 등)은 즉시 통과합니다.

증거는 scripts/orca_level1_gate.py --strict --record-evidence 가 주 저장소 공통
.cache/level1_strict_evidence.json 에 기록합니다. 이 훅은 증거의 commit 이 병합 대상
커밋(MERGE_HEAD)과 같은지 검사하므로, 다른 커밋의 통과 증거를 재사용할 수 없습니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404 - 고정된 인자 목록으로만 git 을 호출합니다
import sys
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

Runner = Callable[[Sequence[str]], subprocess.CompletedProcess[str]]

DEFAULT_EVIDENCE_PATH = Path(".cache/level1_strict_evidence.json")
BYPASS_ENV_VAR = "BYPASS_PREMERGE_LEVEL1_GATE"
EVIDENCE_SCHEMA = "LEVEL1_STRICT_EVIDENCE_V1"
RECORD_COMMAND = (
    "python3 scripts/orca_level1_gate.py --base main --branch <작업브랜치> --repo <워크트리> "
    "--capsule <Capsule 경로> --strict --record-evidence"
)


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


def record_hint() -> str:
    """증거를 다시 만들기 위한 기록 명령 안내문을 만듭니다."""
    return (
        "병합 전에 작업 브랜치에서 Level 1 strict 게이트를 실행하고 증거를 기록하십시오:\n"
        f"  {RECORD_COMMAND}"
    )


def resolve_evidence_path(
    evidence_path: Path | None = None,
    runner: Runner = run_process,
) -> Path:
    """Level 1 strict 증거 파일 경로를 해소합니다.

    지정되지 않았거나 기본 경로인 경우, git rev-parse --git-common-dir 를 기준으로
    주 저장소(main repo)의 .cache/level1_strict_evidence.json 공통 위치를 반환합니다.
    이를 통해 워크트리에서 --record-evidence 한 증거를 주 저장소의 병합 훅에서 즉시
    공유할 수 있습니다.
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
    """Level 1 strict 증거 파일을 읽고 fail-closed 방식으로 구조를 검증합니다."""
    if not evidence_path.exists():
        return None, [
            f"Level 1 strict 증거 파일이 존재하지 않습니다 ({evidence_path}).\n" + record_hint()
        ]

    try:
        data = json.loads(evidence_path.read_text(encoding="utf-8"))
    except OSError as exc:
        return None, [f"Level 1 strict 증거 파일을 읽을 수 없습니다 ({evidence_path}): {exc}"]
    except json.JSONDecodeError as exc:
        return None, [
            f"Level 1 strict 증거 JSON 형식이 올바르지 않습니다 ({evidence_path}): {exc.msg}"
        ]

    if not isinstance(data, dict):
        return None, ["Level 1 strict 증거 데이터가 JSON 객체(dict) 형식이 아닙니다."]

    return data, []


def verify_premerge_gate(
    *,
    target_branch: str = "main",
    evidence_path: Path | None = None,
    source_commit: str | None = None,
    commit_source: str | None = "merge",
    runner: Runner = run_process,
) -> tuple[int, str]:
    """main 브랜치 병합 시점에 Level 1 strict 통과 증거를 검증합니다."""
    # 1. 단일 우회 수단 검사
    if is_bypass_active():
        warning_msg = (
            f"[경고] {BYPASS_ENV_VAR} 환경변수가 설정되어 Level 1 strict 게이트를 우회합니다."
        )
        print(warning_msg, file=sys.stderr)
        return 0, warning_msg

    # 2. 커밋 소스(commit_source) 검사: prepare-commit-msg 단계에서 commit_source가 "merge"가 아니면
    # (예: 일반 커밋인 "message", "template", "commit", "squash", "none" 등) 즉시 통과
    if commit_source is not None and commit_source != "merge" and not source_commit:
        return 0, (
            f"[premerge-level1] 커밋 소스('{commit_source}')가 병합('merge')이 아니므로 검사를 건너뜁니다."
        )

    # 3. 현재 브랜치 확인 (main 브랜치 병합 커밋만 게이트 대상)
    current_branch_proc = runner(["git", "branch", "--show-current"])
    if current_branch_proc.returncode != 0:
        return 1, f"현재 브랜치를 확인할 수 없습니다: {current_branch_proc.stderr.strip()}"

    current_branch = current_branch_proc.stdout.strip()
    if current_branch != target_branch:
        return 0, (
            f"[premerge-level1] 현재 브랜치('{current_branch}')가 "
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
        return 1, "Level 1 strict 게이트 검증 실패:\n" + "\n".join(errors)

    if evidence is None:
        return 1, "Level 1 strict 증거가 없습니다."

    # 6. 증거 스키마 검증
    if evidence.get("schema") != EVIDENCE_SCHEMA:
        return 1, (
            f"Level 1 strict 증거의 schema 가 '{EVIDENCE_SCHEMA}' 가 아닙니다 "
            f"(schema: {evidence.get('schema')!r}).\n" + record_hint()
        )

    # 7. 증거 필드 검증: strict == true
    if evidence.get("strict") is not True:
        return 1, (
            f"Level 1 strict 증거의 strict 속성이 true 가 아닙니다 (strict: {evidence.get('strict')!r}).\n"
            + record_hint()
        )

    # 8. 증거 필드 검증: verdict == "pass"
    if evidence.get("verdict") != "pass":
        return 1, (
            f"Level 1 strict 증거의 판정이 pass 가 아닙니다 (verdict: {evidence.get('verdict')!r}).\n"
            + record_hint()
        )

    # 9. 증거 필드 검증: commit 일치 여부
    ev_commit = str(evidence.get("commit", "")).strip()
    if not ev_commit:
        return 1, (
            "Level 1 strict 증거에 커밋 해시(commit)가 누락되었거나 비어 있습니다.\n"
            + record_hint()
        )

    ev_commit_proc = runner(["git", "rev-parse", "--verify", f"{ev_commit}^{{commit}}"])
    if ev_commit_proc.returncode != 0 or not ev_commit_proc.stdout.strip():
        if ev_commit != merge_sha:
            return 1, (
                f"Level 1 strict 증거의 커밋({ev_commit})이 "
                f"병합 대상 커밋({merge_sha})과 일치하지 않습니다.\n" + record_hint()
            )
    else:
        resolved_ev_commit = ev_commit_proc.stdout.strip()
        if resolved_ev_commit != merge_sha:
            return 1, (
                f"Level 1 strict 증거의 커밋({resolved_ev_commit})이 "
                f"병합 대상 커밋({merge_sha})과 일치하지 않습니다.\n" + record_hint()
            )

    return 0, f"[premerge-level1] Level 1 strict 증거 검증 통과 (commit: {merge_sha[:8]})"


def parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="main 브랜치 병합 시 Level 1 strict 게이트 통과 증거를 검증하는 게이트"
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
        "--target-branch",
        default="main",
        help="게이트를 강제할 대상 브랜치 이름 (기본값: main)",
    )
    parser.add_argument(
        "--evidence-path",
        type=Path,
        default=None,
        help=f"Level 1 strict 증거 JSON 파일 경로 (기본값: 주 저장소 {DEFAULT_EVIDENCE_PATH})",
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
