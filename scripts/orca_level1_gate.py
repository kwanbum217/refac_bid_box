"""
scripts/orca_level1_gate.py

코디네이터가 워커 산출물을 검증할 때 수행하는 Level 1 기계 검증 단일 게이트 스크립트입니다.
5개 게이트(변경 파일, 범위, 테스트, 규칙, 리뷰 보고)를 실행하고 고정된 상한 안으로 요약합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        load_capsule,
        load_report,
        parse_capsule_list,
        scope_excess,
        truncate,
    )
    from scripts.validate_review_report import evaluate, parse_checklist
except ModuleNotFoundError:
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_contract import (
        load_capsule,
        load_report,
        parse_capsule_list,
        scope_excess,
        truncate,
    )
    from scripts.validate_review_report import evaluate, parse_checklist

# 타임아웃 기본 상한 (초)
DEFAULT_GIT_TIMEOUT = 10
DEFAULT_PYTEST_TIMEOUT = 900
DEFAULT_VALIDATE_TIMEOUT = 30
DEFAULT_MAX_CHARS = 2000


class GateToolError(Exception):
    """도구 자체 오류 (git 오류, 경로 부재, 타임아웃 등)."""


@dataclass
class GateResult:
    """개별 게이트의 검증 결과."""

    name: str
    status: str  # "pass", "fail", "skipped"
    summary: str
    details: list[str] = field(default_factory=list)
    raw_data: dict[str, Any] = field(default_factory=dict)


def run_command_safe(
    cmd: list[str],
    cwd: Path,
    timeout: int,
) -> tuple[int, str, str, bool]:
    """subprocess 명령을 실행하고 (returncode, stdout, stderr, timed_out) 을 반환합니다."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr, False
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return -1, stdout, stderr, True
    except FileNotFoundError as exc:
        raise GateToolError(f"실행 파일을 찾을 수 없음 ({cmd[0]}): {exc}") from exc
    except Exception as exc:
        raise GateToolError(f"명령 실행 실패 ({' '.join(cmd)}): {exc}") from exc


def get_git_changed_files(
    repo: Path,
    base: str,
    branch: str,
    timeout: int = DEFAULT_GIT_TIMEOUT,
) -> tuple[list[str], list[str]]:
    """git diff 와 git ls-tree 로 changed_files 와 unique_new_files 를 구합니다.

    - changed_files: git diff --name-only <base>...<branch> (merge-base 기준 변경 파일)
    - unique_new_files: <branch> 에만 있고 <base> 에는 없는 고유 신규 파일
    """
    # 1. changed_files (3-dot diff)
    diff_cmd = ["git", "diff", "--name-only", f"{base}...{branch}"]
    code, stdout, stderr, timed_out = run_command_safe(diff_cmd, repo, timeout)
    if timed_out:
        raise GateToolError(f"git diff 타임아웃 ({timeout}초)")
    if code != 0:
        raise GateToolError(f"git diff 실패 (종료 코드 {code}): {stderr.strip()}")

    changed_files = [line.strip() for line in stdout.splitlines() if line.strip()]

    # 2. branch 파일 목록
    ls_branch_cmd = ["git", "ls-tree", "-r", "--name-only", branch]
    code, stdout, stderr, timed_out = run_command_safe(ls_branch_cmd, repo, timeout)
    if timed_out:
        raise GateToolError(f"git ls-tree {branch} 타임아웃 ({timeout}초)")
    if code != 0:
        raise GateToolError(f"git ls-tree {branch} 실패 (종료 코드 {code}): {stderr.strip()}")

    branch_files = {line.strip() for line in stdout.splitlines() if line.strip()}

    # 3. base 파일 목록
    ls_base_cmd = ["git", "ls-tree", "-r", "--name-only", base]
    code, stdout, stderr, timed_out = run_command_safe(ls_base_cmd, repo, timeout)
    if timed_out:
        raise GateToolError(f"git ls-tree {base} 타임아웃 ({timeout}초)")
    if code != 0:
        raise GateToolError(f"git ls-tree {base} 실패 (종료 코드 {code}): {stderr.strip()}")

    base_files = {line.strip() for line in stdout.splitlines() if line.strip()}

    unique_new_files = sorted(branch_files - base_files)
    return changed_files, unique_new_files


def run_gate1_changed_files(
    repo: Path,
    base: str,
    branch: str,
    timeout: int = DEFAULT_GIT_TIMEOUT,
) -> GateResult:
    """게이트 1: 변경 파일 및 고유 신규 파일 확인."""
    changed_files, unique_new_files = get_git_changed_files(repo, base, branch, timeout)

    summary = f"changed_files {len(changed_files)}건, unique_new_files {len(unique_new_files)}건"
    details: list[str] = [
        f"changed_files: {', '.join(changed_files) if changed_files else '(없음)'}",
        f"unique_new_files: {', '.join(unique_new_files) if unique_new_files else '(없음)'}",
    ]
    return GateResult(
        name="게이트 1 변경 파일",
        status="pass",
        summary=summary,
        details=details,
        raw_data={
            "changed_files": changed_files,
            "unique_new_files": unique_new_files,
        },
    )


def run_gate2_scope(
    changed_files: list[str],
    capsule_path: Path | None,
) -> GateResult:
    """게이트 2: Task Capsule allowed_write_files 범위 검증."""
    if capsule_path is None:
        return GateResult(
            name="게이트 2 범위 검증",
            status="skipped",
            summary="--capsule 미지정으로 건너뜀",
            details=[],
            raw_data={"excess_files": []},
        )

    if not capsule_path.exists():
        raise GateToolError(f"Capsule 파일 없음: {capsule_path}")

    capsule_text = load_capsule(capsule_path)
    allowed_write = parse_capsule_list(capsule_text, "allowed_write_files")
    excess = scope_excess(changed_files, allowed_write)

    if excess:
        return GateResult(
            name="게이트 2 범위 검증",
            status="fail",
            summary=f"허용 범위 초과 파일 {len(excess)}건 감지",
            details=[f"초과 목록: {', '.join(excess)}"],
            raw_data={
                "allowed_write_files": allowed_write,
                "excess_files": excess,
            },
        )

    return GateResult(
        name="게이트 2 범위 검증",
        status="pass",
        summary="allowed_write_files 범위 내 (초과 0건)",
        details=[],
        raw_data={
            "allowed_write_files": allowed_write,
            "excess_files": [],
        },
    )


ANSI_ESCAPE_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")


def strip_ansi(text: str) -> str:
    """터미널 ANSI 제어/색상 코드를 제거합니다."""
    return ANSI_ESCAPE_RE.sub("", text)


def parse_pytest_output(stdout: str, stderr: str) -> tuple[str, list[str]]:
    """pytest -q 출력에서 요약 줄과 실패한 테스트 node id 목록을 추출합니다."""
    text = strip_ansi((stdout + "\n" + stderr).strip())
    if not text:
        return "출력 없음", []

    lines = [line.strip() for line in text.splitlines() if line.strip()]

    failed_nodes: list[str] = []
    for line in lines:
        if line.startswith("FAILED "):
            match = re.match(r"^FAILED\s+([^\s:]+(?:::[^\s:]+)*)", line)
            if match:
                node = match.group(1).strip()
                if node not in failed_nodes:
                    failed_nodes.append(node)

    summary_line = ""
    for line in reversed(lines):
        if "Docs: https://docs.pytest.org" in line or line.startswith("---"):
            continue
        cleaned = re.sub(r"^=+|=+$", "", line).strip()
        if re.search(
            r"\b(?:passed|failed|skipped|error|errors|warning|warnings)\b.*\bin\b",
            cleaned,
            re.IGNORECASE,
        ) or re.search(r"\b(?:passed|failed|skipped|error|errors)\b", cleaned, re.IGNORECASE):
            summary_line = cleaned
            break

    if not summary_line:
        summary_line = re.sub(r"^=+|=+$", "", lines[-1]).strip()

    return summary_line, failed_nodes


def format_failed_nodes(nodes: list[str], max_show: int = 5) -> str:
    """실패한 node id 목록을 최대 max_show 개수까지 나열하고 나머지는 건수로 표기합니다."""
    if not nodes:
        return ""
    shown = nodes[:max_show]
    remainder = len(nodes) - max_show
    out = ", ".join(shown)
    if remainder > 0:
        out += f" (외 {remainder}건)"
    return out


def run_gate3_tests(
    tests: list[str],
    repo: Path,
    timeout: int = DEFAULT_PYTEST_TIMEOUT,
) -> GateResult:
    """게이트 3: 지정된 pytest 테스트 실행."""
    if not tests:
        return GateResult(
            name="게이트 3 테스트",
            status="skipped",
            summary="--tests 미지정으로 건너뜀",
            details=[],
            raw_data={"results": []},
        )

    results: list[dict[str, Any]] = []
    all_passed = True
    details: list[str] = []

    for test_spec in tests:
        args = shlex.split(test_spec)
        cmd = ["uv", "run", "pytest", *args]
        if "-q" not in args and "--quiet" not in args:
            cmd.append("-q")

        code, stdout, stderr, timed_out = run_command_safe(cmd, repo, timeout)
        if timed_out:
            raise GateToolError(f"pytest 타임아웃 ({timeout}초): {test_spec}")

        summary_line, failed_nodes = parse_pytest_output(stdout, stderr)
        passed = code == 0
        if not passed:
            all_passed = False

        results.append(
            {
                "target": test_spec,
                "exit_code": code,
                "summary": summary_line,
                "failed_nodes": failed_nodes,
            }
        )

        detail_line = f"{test_spec}: {summary_line}"
        if failed_nodes:
            detail_line += f" | 실패: {format_failed_nodes(failed_nodes, max_show=5)}"
        details.append(detail_line)

    overall_status = "pass" if all_passed else "fail"
    summary = f"테스트 {len(tests)}건 실행: {'전체 통과' if all_passed else '실패 발생'}"

    return GateResult(
        name="게이트 3 테스트",
        status=overall_status,
        summary=summary,
        details=details,
        raw_data={"results": results},
    )


def parse_validate_agent_rules_output(stdout: str, stderr: str) -> str:
    """validate_agent_rules.py 출력에서 마지막 요약 줄을 추출합니다."""
    text = strip_ansi((stdout + "\n" + stderr).strip())
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    for line in reversed(lines):
        if line.startswith("검증 통과") or line.startswith("검증 실패"):
            return line
    return lines[-1] if lines else "결과 없음"


def run_gate4_rules(
    repo: Path,
    timeout: int = DEFAULT_VALIDATE_TIMEOUT,
) -> GateResult:
    """게이트 4: 다중 에이전트 규칙 검증 (validate_agent_rules.py)."""
    script_path = repo / "scripts" / "validate_agent_rules.py"
    if not script_path.exists():
        raise GateToolError(f"규칙 검증 스크립트 없음: {script_path}")

    cmd = [sys.executable, str(script_path), "--quiet"]
    code, stdout, stderr, timed_out = run_command_safe(cmd, repo, timeout)
    if timed_out:
        raise GateToolError(f"validate_agent_rules.py 타임아웃 ({timeout}초)")

    summary_line = parse_validate_agent_rules_output(stdout, stderr)
    status = "pass" if code == 0 else "fail"
    details = [] if code == 0 else [f"종료 코드: {code}"]

    return GateResult(
        name="게이트 4 규칙 검증",
        status=status,
        summary=summary_line,
        details=details,
        raw_data={
            "exit_code": code,
            "summary": summary_line,
        },
    )


def run_gate5_review_report(
    review_report_path: Path | None,
    capsule_path: Path | None,
) -> GateResult:
    """게이트 5: 리뷰 보고서 계약 판정 (validate_review_report)."""
    if review_report_path is None or capsule_path is None:
        return GateResult(
            name="게이트 5 리뷰 보고",
            status="skipped",
            summary="--review-report 또는 --capsule 미지정으로 건너뜀",
            details=[],
            raw_data={},
        )

    if not review_report_path.exists():
        raise GateToolError(f"리뷰 보고 파일 없음: {review_report_path}")
    if not capsule_path.exists():
        raise GateToolError(f"Capsule 파일 없음: {capsule_path}")

    capsule_text = load_capsule(capsule_path)
    checklist = parse_checklist(capsule_text)
    report = load_report(review_report_path)
    eval_res = evaluate(checklist, report)

    effective_verdict = eval_res.get("effective_verdict", "unknown")
    violations = eval_res.get("violations", [])
    ok = eval_res.get("ok", False)

    status = "pass" if ok else "fail"
    summary = f"실효 verdict '{effective_verdict}', 위반 {len(violations)}건"
    details = [f"위반: {'; '.join(violations)}"] if violations else []

    return GateResult(
        name="게이트 5 리뷰 보고",
        status=status,
        summary=summary,
        details=details,
        raw_data=eval_res,
    )


def format_human_output(
    gates: list[GateResult],
    verdict: str,
    passed_count: int,
    skipped_count: int,
    failed_count: int,
    error_message: str = "",
) -> str:
    """사람이 읽기 좋은 정형 텍스트 블록을 생성합니다."""
    lines = [
        "=" * 60,
        "Orca Level 1 기계 검증 게이트",
        "=" * 60,
    ]
    for g in gates:
        tag = f"[{g.status.upper()}]"
        lines.append(f"{tag:<10} {g.name}")
        if g.summary:
            lines.append(f"           {g.summary}")
        for d in g.details:
            lines.append(f"           {d}")
    lines.append("-" * 60)
    if error_message:
        lines.append(f"도구 오류: {error_message}")
        lines.append("-" * 60)
    lines.append(
        f"최종 판정: {verdict.upper()} (통과 {passed_count} / 건너뜀 {skipped_count} / 실패 {failed_count})"
    )
    return "\n".join(lines)


def build_json_output(
    gates: list[GateResult],
    verdict: str,
    exit_code: int,
    passed_count: int,
    skipped_count: int,
    failed_count: int,
    error_message: str = "",
) -> dict[str, Any]:
    """기계용 JSON 구조를 생성합니다."""
    gate_keys = [
        "gate1_changed_files",
        "gate2_scope",
        "gate3_tests",
        "gate4_rules",
        "gate5_review_report",
    ]
    gates_dict: dict[str, Any] = {}
    for i, g in enumerate(gates):
        key = gate_keys[i] if i < len(gate_keys) else f"gate_{i + 1}"
        gates_dict[key] = {
            "name": g.name,
            "status": g.status,
            "summary": g.summary,
            "details": g.details,
            **g.raw_data,
        }

    return {
        "verdict": verdict,
        "exit_code": exit_code,
        "summary": {
            "total": len(gates),
            "passed": passed_count,
            "skipped": skipped_count,
            "failed": failed_count,
        },
        "gates": gates_dict,
        "error": error_message or None,
    }


def parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    """CLI 인자를 파싱합니다."""
    parser = argparse.ArgumentParser(
        description="Orca Level 1 기계 검증 단일 게이트",
    )
    parser.add_argument("--base", default="main", help="비교 기준 git ref (기본: main)")
    parser.add_argument("--branch", default="HEAD", help="검증 대상 git ref (기본: HEAD)")
    parser.add_argument("--repo", default=".", help="저장소 루트 경로 (기본: 현재 디렉터리)")
    parser.add_argument(
        "--tests",
        action="append",
        default=[],
        help="실행할 pytest 인자 문자열 (반복 지정 가능)",
    )
    parser.add_argument("--capsule", default=None, help="Task Capsule 파일 경로")
    parser.add_argument("--review-report", default=None, help="리뷰 보고서 JSON 파일 경로")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=DEFAULT_MAX_CHARS,
        help="사람 출력 최대 문자 수 상한 (기본: 2000)",
    )
    parser.add_argument("--json", action="store_true", help="결과를 JSON 으로 출력")
    return parser.parse_args(argv)


def run_level1_gate(
    base: str = "main",
    branch: str = "HEAD",
    repo: str | Path = ".",
    tests: list[str] | None = None,
    capsule: str | Path | None = None,
    review_report: str | Path | None = None,
    max_chars: int = DEFAULT_MAX_CHARS,
    as_json: bool = False,
) -> tuple[int, str]:
    """Level 1 게이트 전체를 실행하고 (exit_code, output_text) 를 반환합니다."""
    if tests is None:
        tests = []
    repo_path = Path(repo).resolve()
    capsule_path = Path(capsule).resolve() if capsule else None
    review_report_path = Path(review_report).resolve() if review_report else None

    if not repo_path.exists() or not repo_path.is_dir():
        error_msg = f"저장소 경로가 존재하지 않거나 디렉터리가 아님: {repo_path}"
        if as_json:
            data = build_json_output([], "error", 2, 0, 0, 0, error_message=error_msg)
            return 2, json.dumps(data, ensure_ascii=False, indent=2)
        out = format_human_output([], "error", 0, 0, 0, error_message=error_msg)
        return 2, truncate(out, max_chars)

    gates: list[GateResult] = []
    try:
        # 게이트 1: 변경 파일
        g1 = run_gate1_changed_files(repo_path, base, branch)
        gates.append(g1)
        changed_files = g1.raw_data.get("changed_files", [])

        # 게이트 2: 범위
        g2 = run_gate2_scope(changed_files, capsule_path)
        gates.append(g2)

        # 게이트 3: 테스트
        g3 = run_gate3_tests(tests, repo_path)
        gates.append(g3)

        # 게이트 4: 규칙
        g4 = run_gate4_rules(repo_path)
        gates.append(g4)

        # 게이트 5: 리뷰 보고
        g5 = run_gate5_review_report(review_report_path, capsule_path)
        gates.append(g5)

    except GateToolError as exc:
        error_msg = str(exc)
        passed_count = sum(1 for g in gates if g.status == "pass")
        failed_count = sum(1 for g in gates if g.status == "fail")
        skipped_count = sum(1 for g in gates if g.status == "skipped")
        if as_json:
            data = build_json_output(
                gates,
                "error",
                2,
                passed_count,
                skipped_count,
                failed_count,
                error_message=error_msg,
            )
            return 2, json.dumps(data, ensure_ascii=False, indent=2)
        out = format_human_output(
            gates, "error", passed_count, skipped_count, failed_count, error_message=error_msg
        )
        return 2, truncate(out, max_chars)

    passed_count = sum(1 for g in gates if g.status == "pass")
    failed_count = sum(1 for g in gates if g.status == "fail")
    skipped_count = sum(1 for g in gates if g.status == "skipped")

    verdict = "pass" if failed_count == 0 else "fail"
    exit_code = 0 if verdict == "pass" else 1

    if as_json:
        data = build_json_output(
            gates, verdict, exit_code, passed_count, skipped_count, failed_count
        )
        return exit_code, json.dumps(data, ensure_ascii=False, indent=2)

    human_text = format_human_output(gates, verdict, passed_count, skipped_count, failed_count)
    return exit_code, truncate(human_text, max_chars)


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    args = parse_arguments(argv)
    code, output = run_level1_gate(
        base=args.base,
        branch=args.branch,
        repo=args.repo,
        tests=args.tests,
        capsule=args.capsule,
        review_report=args.review_report,
        max_chars=args.max_chars,
        as_json=args.json,
    )
    print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
