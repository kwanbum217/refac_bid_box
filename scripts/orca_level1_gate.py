"""
scripts/orca_level1_gate.py

코디네이터가 워커 산출물을 검증할 때 수행하는 Level 1 기계 검증 단일 게이트 스크립트입니다.
6개 게이트(변경 파일, 범위, 테스트, 규칙, 린터, 리뷰 보고)를 실행하고 고정된 상한 안으로 요약합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess  # nosec B404 - 개발 스크립트가 고정 인자 목록으로만 외부 도구를 호출합니다
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        load_capsule,
        load_report,
        parse_capsule_list,
        truncate,
        write_scope_excess,
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
        truncate,
        write_scope_excess,
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
    # 건너뜀이 곧 fail-open 인 게이트와, 이 호출에서 애초에 적용 대상이 아닌
    # 게이트를 구분합니다. --strict 는 전자만 실패로 봅니다. 둘을 묶으면
    # 리뷰를 요청하지 않은 호출까지 무조건 fail 이 되고, 그것을 뚫으려고
    # 건너뜀 허용 옵션을 상시로 켜면 테스트 게이트까지 함께 열립니다.
    required: bool = True


def run_command_safe(
    cmd: list[str],
    cwd: Path,
    timeout: int,
) -> tuple[int, str, str, bool]:
    """subprocess 명령을 실행하고 (returncode, stdout, stderr, timed_out) 을 반환합니다."""
    try:
        proc = subprocess.run(  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
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


# 검증을 면제해도 되는 문서 전용 확장자입니다. 코드 확장자를 나열하는 방식은
# 목록에 없는 형식이 조용히 면제되므로 쓰지 않습니다. 2026-08-19 까지 `.py` 만
# 코드로 보아 `.ts`, `.tsx`, Dockerfile 변경이 테스트 없이 strict 를 통과했습니다.
# 기본은 "검증 필요" 이고 문서만 바뀐 것이 증명될 때만 면제합니다.
DOC_ONLY_SUFFIXES = frozenset({".md", ".rst", ".adoc"})


def requires_test_verification(changed_files: list[str]) -> bool:
    """실제 변경 파일을 근거로 테스트 게이트 필수 여부를 정합니다.

    Capsule 의 allowed_write_files 는 "고쳐도 되는 범위" 선언이고, 실제로 무엇을
    고쳤는지는 Gate 1 이 구한 변경 목록만이 안다. 선언을 근거로 판정하면 범위를
    넓게 잡아 둔 Task 가 실제로는 문서만 고쳐도 테스트를 요구받고, 반대로 좁게
    적어 둔 Task 는 코드를 고쳐도 면제된다.

    변경이 없으면 검증할 대상도 없으므로 필수가 아니다. 무작업 완료 보고는
    summarize_worker_done 의 commit_count 검사가 따로 막는다.
    """
    if not changed_files:
        return False
    return not all(
        Path(path).suffix.lower() in DOC_ONLY_SUFFIXES for path in changed_files if path.strip()
    )


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
    excess = write_scope_excess(changed_files, allowed_write)

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
    required: bool = True,
) -> GateResult:
    """게이트 3: 지정된 pytest 테스트 실행.

    required 가 참인데 tests 가 비면 --strict 에서 실패합니다. 코드를 고치는
    Task 가 테스트 없이 통과하는 것이 종전의 fail-open 이었습니다. 문서만
    바꾸는 Task 는 호출부가 required 를 거짓으로 내려 구분합니다.
    """
    if not tests:
        return GateResult(
            name="게이트 3 테스트",
            status="skipped",
            summary="--tests 미지정으로 건너뜀",
            details=[],
            raw_data={"results": []},
            required=required,
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


def run_gate4b_lint(
    repo: Path,
    timeout: int = DEFAULT_VALIDATE_TIMEOUT,
) -> GateResult:
    """게이트 4b: 저장소 전체 ruff 검사.

    워커의 "린터 통과" 보고는 그 워커가 지정한 경로에 대한 것일 뿐입니다.
    2026-08-17 에 워커가 src 만 검사하고 자기가 만든 테스트 파일을 빼놓아
    병합 후 main 에서 오류 4건이 나왔습니다. 범위를 저장소 전체로 못박습니다.
    """
    cmd = ["uv", "run", "ruff", "check", ".", "--output-format", "concise"]
    code, stdout, stderr, timed_out = run_command_safe(cmd, repo, timeout)
    if timed_out:
        raise GateToolError(f"ruff check 타임아웃 ({timeout}초)")

    combined = f"{stdout}\n{stderr}".strip()
    if code == 0:
        return GateResult(
            name="게이트 4b 린터",
            status="pass",
            summary="ruff check . 통과 (저장소 전체)",
            details=[],
            raw_data={"exit_code": code},
        )

    offenders = [ln for ln in combined.splitlines() if ln.strip() and ":" in ln][:10]
    return GateResult(
        name="게이트 4b 린터",
        status="fail",
        summary=f"ruff check . 실패 (종료 코드 {code})",
        details=offenders,
        raw_data={"exit_code": code, "offenders": offenders},
    )


def run_gate5_review_report(
    review_report_path: Path | None,
    capsule_path: Path | None,
) -> GateResult:
    """게이트 5: 리뷰 보고서 계약 판정 (validate_review_report)."""
    if review_report_path is None:
        # 리뷰 보고를 넘기지 않은 호출은 이 단계에서 리뷰를 검증하지 않겠다는
        # 뜻입니다. finalize 는 Level 1 을 먼저 돌리고 리뷰어를 그 뒤에 돌리므로
        # 이 시점에는 보고서가 존재할 수 없습니다. 이를 필수 건너뜀으로 세면
        # --strict 가 어떤 입력에도 fail 을 냅니다. 리뷰 결과 자체는 리뷰어
        # 종료 코드로 finalize 가 따로 판정합니다.
        return GateResult(
            name="게이트 5 리뷰 보고",
            status="skipped",
            summary="--review-report 미지정으로 이 호출의 적용 대상이 아님",
            details=[],
            raw_data={},
            required=False,
        )

    if capsule_path is None:
        # 보고서를 명시했는데 Capsule 이 없으면 체크리스트를 대조할 정본이
        # 없습니다. 이를 "리뷰를 요청하지 않은 호출" 과 같은 N/A 로 처리하면
        # 리뷰를 요구한 호출이 조용히 검증 없이 통과합니다. 호출 오류입니다.
        raise GateToolError("--review-report 검증에는 --capsule 이 필요합니다")

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
        if g.status == "skipped" and not g.required:
            tag = "[N/A]"
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
    blocking = [g.name for g in gates if g.status == "skipped" and g.required]
    if blocking:
        lines.append(f"필수인데 건너뛴 게이트: {', '.join(blocking)}")
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
    # run_all 이 append 하는 순서와 1:1 로 맞춥니다. 4b 린터가 빠져 있어
    # 린터 결과가 gate5_review_report 로, 실제 리뷰 결과가 gate_6 으로
    # 밀려 나가 있었습니다.
    gate_keys = [
        "gate1_changed_files",
        "gate2_scope",
        "gate3_tests",
        "gate4_rules",
        "gate4b_lint",
        "gate5_review_report",
    ]
    gates_dict: dict[str, Any] = {}
    for i, g in enumerate(gates):
        key = gate_keys[i] if i < len(gate_keys) else f"gate_{i + 1}"
        gates_dict[key] = {
            "name": g.name,
            "status": g.status,
            "required": g.required,
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
            "blocking_skipped": [g.name for g in gates if g.status == "skipped" and g.required],
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
    parser.add_argument(
        "--strict",
        action="store_true",
        help="건너뛴 게이트를 실패로 간주 (병합 판정용)",
    )
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
    strict: bool = False,
) -> tuple[int, str]:
    """Level 1 게이트 전체를 실행하고 (exit_code, output_text) 를 반환합니다.

    strict 를 켜면 건너뛴 게이트가 하나라도 있을 때 fail 로 판정합니다.
    """
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
        g3 = run_gate3_tests(tests, repo_path, required=requires_test_verification(changed_files))
        gates.append(g3)

        # 게이트 4: 규칙
        g4 = run_gate4_rules(repo_path)
        gates.append(g4)

        # 게이트 4b: 린터 (저장소 전체)
        g4b = run_gate4b_lint(repo_path)
        gates.append(g4b)

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

    # 건너뛴 게이트는 검증하지 않았다는 뜻이지 통과했다는 뜻이 아닙니다.
    # 병합 판정처럼 전부 검증되어야 하는 호출은 --strict 로 이를 강제합니다.
    # 다만 이 호출의 적용 대상이 아닌 게이트(required=False)까지 실패로 세면
    # --strict 가 어떤 입력에도 fail 을 냅니다. 필수 건너뜀만 셉니다.
    blocking_skips = [g.name for g in gates if g.status == "skipped" and g.required]
    verdict = "pass" if failed_count == 0 and not (strict and blocking_skips) else "fail"
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
        strict=args.strict,
    )
    print(output)
    return code


if __name__ == "__main__":
    sys.exit(main())
