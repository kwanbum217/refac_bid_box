"""
scripts/orca_contract.py

Orca Task Capsule v2 및 보고 계약을 다루는 공용 파싱 헬퍼입니다.

코디네이터 수신면 도구(`orca_level1_gate.py`, `summarize_worker_done.py`,
`orca_metrics_ledger.py`)가 같은 Capsule 과 같은 보고 JSON 을 읽습니다. 각 도구가
자기 파서를 따로 두면 같은 Capsule 을 놓고 판정이 갈립니다. 파싱 규칙은 여기
한 곳에만 둡니다.

PyYAML 을 새로 추가하지 않습니다. Capsule 은 중첩이 얕고 형식이 고정돼 있어
필요한 필드만 정규식으로 뽑는 범위에서 충분합니다.

규약 정본: docs/ops/orca_task_capsule_v2.md
"""

from __future__ import annotations

import hashlib
import json
import re
import shlex
import subprocess  # nosec B404
import sys
from pathlib import Path, PurePosixPath
from typing import Any


class ContractError(Exception):
    """Capsule 또는 보고가 계약 형식을 만족하지 않을 때 발생합니다."""


# Capsule 에서 경로 목록으로 다루는 필드
PATH_LIST_FIELDS = ("allowed_read_files", "allowed_write_files", "artifact_paths")

# 경로 패턴에서 "이 아래 전부" 를 뜻하는 접미사. Capsule 예시가 `src/...` 를 씁니다.
_PREFIX_SUFFIXES = ("/...", "/**", "/")

# ---------------------------------------------------------------------------
# 워커 완료 보고(ORCA_WORKER_DONE_V2) 필드 정본 (Single Source of Truth)
# ---------------------------------------------------------------------------
# 필수 필드(required=True)와 부가 필드(required=False)의 명세입니다.
# summarize_worker_done.py 의 REQUIRED_FIELDS, orca_taskctl.py 의 WORKER_REPORT_SCHEMA,
# .agents/templates/worker_done_v2.json 템플릿이 모두 이 단일 정본에서 파생됩니다.
WORKER_DONE_SCHEMA_SPEC: dict[str, dict[str, Any]] = {
    "schema": {
        "required": True,
        "description": '"ORCA_WORKER_DONE_V2"',
        "sample": "ORCA_WORKER_DONE_V2",
    },
    "version": {
        "required": True,
        "description": '"2.1.0"',
        "sample": "2.1.0",
    },
    "task_id": {
        "required": True,
        "description": '"위 task_id 를 그대로 적는다"',
        "sample": "<task_id>",
    },
    "dispatch_id": {
        "required": False,
        "description": '"위 dispatch_id 를 적는다. 없는 경우 생략 가능"',
        "sample": "<dispatch_id>",
    },
    "status": {
        "required": True,
        "description": '"succeeded 또는 escalation 문자열 하나"',
        "sample": "succeeded",
    },
    "branch": {
        "required": True,
        "description": '"작업한 브랜치 이름"',
        "sample": "kwanbum217/feat-example",
    },
    "commit": {
        "required": True,
        "description": '"마지막 커밋 SHA. 커밋이 없으면 빈 문자열"',
        "sample": "<commit_sha>",
    },
    "commit_count": {
        "required": True,
        "description": '"정수. 0 이면 status 를 escalation 으로 쓴다"',
        "sample": 1,
    },
    "changed_files": {
        "required": True,
        "description": '"배열. 실제로 커밋한 파일 경로"',
        "sample": [
            "src/example.py",
            "tests/test_example.py",
        ],
    },
    "read_files": {
        "required": True,
        "description": '"배열. 실제로 읽은 파일 경로"',
        "sample": [
            "scripts/orca_contract.py",
            "docs/ops/orca_task_capsule_v2.md",
        ],
    },
    "verification": {
        "required": True,
        "description": '"배열. 각 항목은 command 와 result 키를 가진다"',
        "sample": [
            {
                "command": "uv run pytest tests/test_example.py -q",
                "result": "5 passed",
            },
            {
                "command": "python3 scripts/validate_agent_rules.py --quiet",
                "result": "PASS (6/6)",
            },
        ],
    },
    "metrics": {
        "required": False,
        "description": '"객체. before 및 after 지표"',
        "sample": {
            "before": None,
            "after": None,
        },
    },
    "verdict": {
        "required": True,
        "description": '"candidate 또는 blocked 문자열 하나"',
        "sample": "candidate",
    },
    "blocking_issues": {
        "required": True,
        "description": '"배열. 차단 사유가 없으면 빈 배열"',
        "sample": [],
    },
    "remaining_risks": {
        "required": False,
        "description": '"배열. 잔여 리스크"',
        "sample": [],
    },
    "artifacts": {
        "required": False,
        "description": '"배열. 생성한 산출물 문서 경로"',
        "sample": [
            "docs/analysis/example_report.md",
        ],
    },
    "reproduce": {
        "required": False,
        "description": '"배열. 재현 명령"',
        "sample": [
            "uv run pytest tests/test_example.py -q",
        ],
    },
}


def get_worker_done_required_fields(
    spec: dict[str, dict[str, Any]] | None = None,
) -> tuple[str, ...]:
    """워커 완료 보고 필수 필드 튜플을 반환합니다."""
    s = spec if spec is not None else WORKER_DONE_SCHEMA_SPEC
    return tuple(k for k, v in s.items() if v.get("required", False))


WORKER_DONE_REQUIRED_FIELDS: tuple[str, ...] = get_worker_done_required_fields()


def render_worker_report_schema(
    spec: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Capsule report_schema 블록 문자열을 생성합니다."""
    s = spec if spec is not None else WORKER_DONE_SCHEMA_SPEC
    lines = ["report_schema:"]
    for k, v in s.items():
        if v.get("required", False):
            lines.append(f"  {k}: {v['description']}")
    return "\n".join(lines) + "\n"


def render_worker_done_template(
    spec: dict[str, dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """worker_done_v2.json 템플릿 딕셔너리를 생성합니다."""
    s = spec if spec is not None else WORKER_DONE_SCHEMA_SPEC
    return {k: v["sample"] for k, v in s.items()}


def char_len(text: str) -> int:
    """문자 수를 셉니다.

    설계 5장의 예산은 문자 수이며 바이트가 아닙니다. `wc -c` 로 재면 한글이
    3바이트라 초과처럼 보입니다. 크기 판정은 반드시 이 함수를 씁니다.
    """
    return len(text)


def _unquote(value: str) -> str:
    """따옴표를 벗기고 이스케이프를 되돌립니다.

    Capsule 을 쓸 때 경로의 역슬래시를 `\\\\` 로 이스케이프하므로, 읽을 때
    되돌리지 않으면 Windows 경로가 `C:\\\\Users` 형태로 남아 원본과 대조되지
    않습니다.
    """
    stripped = value.strip()
    if len(stripped) >= 2 and stripped[0] == stripped[-1] and stripped[0] in "\"'":
        inner = stripped[1:-1]
        if stripped[0] == '"':
            return inner.replace('\\"', '"').replace("\\\\", "\\")
        return inner
    return stripped


def parse_capsule_scalar(capsule_text: str, field: str) -> str | None:
    """Capsule 최상위의 단일값 필드를 읽습니다. 없으면 None."""
    lines = capsule_text.splitlines()
    field_idx = -1
    field_val = ""
    for idx, line in enumerate(lines):
        match = re.match(rf"^{re.escape(field)}:[ \t]*(.*)$", line)
        if match:
            field_idx = idx
            field_val = match.group(1).strip()
            break
    if field_idx == -1:
        return None

    # 주석 제거 후 folded scalar 헤더인지 확인
    clean_val = re.sub(r"\s+#.*$", "", field_val).strip()
    if clean_val in (">", "|", ">-", "|-"):
        collected: list[str] = []
        for raw in lines[field_idx + 1 :]:
            if raw and not raw[0].isspace():
                break
            line_str = raw.strip()
            if line_str and not line_str.startswith("#"):
                collected.append(line_str)
        if not collected:
            return None
        joined = " ".join(collected).strip()
        return joined or None

    # 일반 단일값
    val = _unquote(clean_val)
    return val or None


def parse_capsule_list(capsule_text: str, field: str) -> list[str]:
    """Capsule 최상위의 문자열 리스트 필드를 읽습니다.

    `field:` 다음 줄부터 들여쓰기된 `- ` 항목만 취하고, 들여쓰기가 풀리는
    첫 줄에서 멈춥니다. 항목이 `key: value` 형태인 객체 리스트는 대상이
    아니므로 빈 목록으로 돌려줍니다.
    """
    lines = capsule_text.splitlines()
    field_idx = -1
    for idx, line in enumerate(lines):
        if re.match(rf"^{re.escape(field)}:[ \t]*(?:#.*)?$", line):
            field_idx = idx
            break
    if field_idx == -1:
        return []

    items: list[str] = []
    for raw in lines[field_idx + 1 :]:
        if raw and not raw[0].isspace():
            if raw.startswith("#"):
                continue  # 0열 주석 줄은 건너뜀
            break  # 다음 최상위 키

        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if not line.startswith("- "):
            continue

        value = line[2:].strip()
        # 따옴표가 있는 경우 따옴표 내부의 샵은 보존
        if value.startswith('"'):
            m = re.match(r'^"((?:[^"\\]|\\.)*)"(?:\s+#.*)?$', value)
            if m:
                items.append(m.group(1).replace('\\"', '"').replace("\\\\", "\\"))
                continue
            if re.match(r'^"[^"]*":', value):
                continue
        elif value.startswith("'"):
            m = re.match(r"^'([^']*)'(?:\s+#.*)?$", value)
            if m:
                items.append(m.group(1))
                continue
            if re.match(r"^'[^']*':", value):
                continue

        # 따옴표가 없는 경우 공백 뒤 샵부터 주석 제거
        unquoted = re.sub(r"\s+#.*$", "", value).strip()
        if unquoted.endswith(":") or re.match(r"^[a-z_]+:\s", unquoted):
            continue
        items.append(unquoted.strip("\"'"))

    return items


def _strip_leading_dot_slash(value: str) -> str:
    """선행 `./` 만 제거합니다. `.env` 같은 dotfile 은 그대로 둡니다."""
    while value.startswith("./"):
        value = value[2:]
    return value.lstrip("/") if value.startswith("/") else value


def _glob_to_regex(pattern: str) -> re.Pattern[str]:
    """glob 을 정규식으로 옮깁니다.

    `fnmatch` 는 `*` 가 `/` 를 넘습니다. 그러면 `docs/ops/*.md` 가
    `docs/ops/deep/x.md` 까지 허용해 범위 초과를 놓칩니다. 감사 도구는
    놓치는 쪽보다 넓게 잡는 쪽이 안전하므로 `*` 는 구분자를 넘지 않게 하고,
    재귀는 `**` 또는 Capsule 관용 표기 `.../` 로만 씁니다.
    """
    out: list[str] = []
    i = 0
    while i < len(pattern):
        char = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif char == "*":
            out.append("[^/]*")
            i += 1
        elif char == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(char))
            i += 1
    return re.compile(f"^{''.join(out)}$")


def matches_any(path: str, patterns: list[str]) -> bool:
    """경로가 허용 패턴 중 하나에 걸리는지 봅니다.

    `src/...`, `src/**`, `src/` 는 그 아래 전부를 뜻합니다. 그 밖에는 glob 으로
    판정하며 `*` 는 경로 구분자를 넘지 않습니다. 하위 디렉터리까지 허용하려면
    `tests/*` 가 아니라 `tests/...` 로 적으십시오.
    """
    # 감사 도구는 애매하면 허용하지 않고 거부하는 쪽이 안전하므로,
    # 빈 경로나 상위 디렉터리 참조(..)가 포함된 경로는 판정 이전에 즉시 거부합니다.
    if not path or not path.strip():
        return False
    if ".." in path.replace("\\", "/").split("/"):
        return False

    normalized = _strip_leading_dot_slash(path.strip())
    if not normalized:
        return False

    for pattern in patterns:
        candidate = _strip_leading_dot_slash(pattern.strip())
        if not candidate or ".." in candidate.replace("\\", "/").split("/"):
            continue
        for suffix in _PREFIX_SUFFIXES:
            if candidate.endswith(suffix):
                prefix = candidate[: -len(suffix)].rstrip("/")
                if normalized == prefix or normalized.startswith(f"{prefix}/"):
                    return True
                break
        else:
            if _glob_to_regex(candidate).match(normalized):
                return True
    return False


def scope_excess(paths: list[str], allowed: list[str]) -> list[str]:
    """허용 목록을 벗어난 경로만 골라냅니다.

    허용 목록이 비어 있으면 판정 근거가 없으므로 초과 없음으로 봅니다.
    `allowed_read_files` 는 지시이며 강제 장치가 아니라서, 이 함수의 결과는
    사후 확인용입니다 (규약 2.9.2).
    """
    if not allowed:
        return []
    return [p for p in paths if not matches_any(p, allowed)]


def write_scope_excess(paths: list[str], allowed: list[str]) -> list[str]:
    """쓰기 범위에서 허용 목록을 벗어난 경로만 골라냅니다.

    읽기 범위(`scope_excess`)와 달리 쓰기 범위는 강제 장치입니다. 허용 목록이
    비어 있으면 어떤 파일도 수정해서는 안 되므로 `paths` 전부를 초과로 반환합니다.
    읽기 전용 Task 는 `allowed_write_files` 를 빈 목록으로 쓰기 때문에, 비었을 때
    전면 금지로 보지 않으면 쓰기 범위가 fail-open 됩니다.
    """
    if not allowed:
        return list(paths)
    return [p for p in paths if not matches_any(p, allowed)]


def load_capsule(path: str | Path) -> str:
    """Capsule 원문을 읽습니다."""
    capsule_path = Path(path)
    if not capsule_path.exists():
        raise ContractError(f"Capsule 파일 없음: {capsule_path}")
    return capsule_path.read_text(encoding="utf-8")


def load_report(path: str | Path) -> dict[str, Any]:
    """보고 JSON 을 읽습니다.

    2026-08-15 감도 시험에서 리뷰어 한 대가 이스케이프되지 않은 `\\D` 를 넣어
    JSON 파싱이 깨졌습니다. 파싱 실패는 조용히 넘기지 않고 예외로 올립니다.
    """
    report_path = Path(path)
    if not report_path.exists():
        raise ContractError(f"보고 파일 없음: {report_path}")
    try:
        data = json.loads(report_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ContractError(f"보고 JSON 파싱 실패: {exc}") from exc
    if not isinstance(data, dict):
        raise ContractError("보고 최상위가 객체가 아님")
    return data


def string_list(value: Any) -> list[str]:
    """보고의 리스트 필드를 문자열 목록으로 정규화합니다.

    워커가 문자열 하나를 그대로 넣거나 객체 리스트를 넣는 경우가 있어
    형식을 신뢰하지 않습니다.
    """
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        out: list[str] = []
        for item in value:
            if isinstance(item, str):
                out.append(item)
            elif isinstance(item, dict):
                for key in ("path", "file", "name"):
                    if isinstance(item.get(key), str):
                        out.append(item[key])
                        break
        return out
    return []


def truncate(text: str, limit: int) -> str:
    """길이를 제한하고 잘렸음을 표시합니다.

    코디네이터 수신면의 목적은 읽을 양의 상한을 두는 것입니다. 잘린 사실을
    감추면 상한이 아니라 손실이 됩니다.
    """
    if limit <= 0:
        return ""
    if char_len(text) <= limit:
        return text
    marker = "...(잘림)"
    if limit <= char_len(marker):
        return text[:limit]
    return text[: limit - char_len(marker)] + marker


def _run_git_command(repo: str | Path, args: list[str], timeout: int = 10) -> tuple[int, str, str]:
    """git 하위 명령을 실행하고 (returncode, stdout, stderr) 를 반환합니다.

    실패 시 예외를 삼키지 않고 반환 코드로 fail-closed 처리합니다.
    """
    repo_path = Path(repo).resolve()
    try:
        proc = subprocess.run(  # nosec B603 B607
            ["git", *args],
            cwd=str(repo_path),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return -1, "", str(exc)


def verify_commit_exists(repo: str | Path, commit_sha: str) -> tuple[bool, str]:
    """commit SHA 가 실제 git 역사에 존재하는지 검증합니다.

    `git rev-parse --verify <commit_sha>^{commit}` 로 대조합니다.
    """
    cleaned = (commit_sha or "").strip()
    if not cleaned:
        return False, "commit SHA 가 비어 있음"
    code, stdout, stderr = _run_git_command(
        repo, ["rev-parse", "--verify", f"{cleaned}^{{commit}}"]
    )
    if code == 0 and stdout.strip():
        return True, "commit SHA 실존 확인"
    err = stderr.strip() or "존재하지 않는 commit SHA"
    return False, f"commit SHA '{cleaned}' 실존성 검증 실패: {err}"


def verify_branch_exists(repo: str | Path, branch: str) -> tuple[bool, str]:
    """branch 가 refs/heads/ 아래에 실제로 존재하는지 검증합니다.

    `git show-ref --verify refs/heads/<branch>` 로 대조합니다.
    """
    cleaned = (branch or "").strip()
    if not cleaned:
        return False, "브랜치명이 비어 있음"
    ref_name = cleaned if cleaned.startswith("refs/heads/") else f"refs/heads/{cleaned}"
    code, _stdout, stderr = _run_git_command(repo, ["show-ref", "--verify", ref_name])
    if code == 0:
        return True, "브랜치 실존 확인"
    err = stderr.strip() or "존재하지 않는 브랜치"
    return False, f"브랜치 '{cleaned}' 실존성 검증 실패: {err}"


def verify_changed_files_match(
    repo: str | Path, base: str, branch: str, reported_files: list[str]
) -> tuple[bool, str]:
    """보고된 changed_files 목록이 실제 git diff 와 일치하는지 검증합니다.

    `git diff --name-only <base>..<branch>` 로 대조합니다.
    """
    base_clean = (base or "").strip() or "main"
    branch_clean = (branch or "").strip() or "HEAD"
    code, stdout, stderr = _run_git_command(
        repo, ["diff", "--name-only", f"{base_clean}...{branch_clean}"]
    )
    if code != 0:
        err = stderr.strip() or "git diff 실패"
        return False, f"git diff 실행 실패 ({base_clean}...{branch_clean}): {err}"

    actual_files = {
        _strip_leading_dot_slash(line.strip()) for line in stdout.splitlines() if line.strip()
    }
    normalized_reported = {
        _strip_leading_dot_slash(p.strip()) for p in reported_files if p and p.strip()
    }

    missing_in_report = sorted(actual_files - normalized_reported)
    phantom_in_report = sorted(normalized_reported - actual_files)

    if not missing_in_report and not phantom_in_report:
        return True, "변경 파일 목록 일치"

    parts: list[str] = []
    if missing_in_report:
        parts.append(f"보고 누락: {', '.join(missing_in_report)}")
    if phantom_in_report:
        parts.append(f"허위 보고(diff 에 없음): {', '.join(phantom_in_report)}")
    return False, f"changed_files 불일치 ({'; '.join(parts)})"


# 검증 재실행 타임아웃 기본값 (초)
# pytest 계열은 전량 pytest 실행 실측이 63~117초 소요되므로 scripts/orca_level1_gate.py 의 DEFAULT_PYTEST_TIMEOUT 과 동일하게 900초(15분)를 적용합니다.
# validate_agent_rules.py 계열은 정적 규칙 검사이므로 30초를 적용합니다.
DEFAULT_VERIFY_PYTEST_TIMEOUT = 900
DEFAULT_VERIFY_VALIDATE_TIMEOUT = 30
DEFAULT_VERIFY_TIMEOUT = 30


def classify_verification_command(command: str) -> tuple[str, list[str] | None]:
    """검증 명령 문자열의 종류(command_type)와 재실행 인자(argv)를 판별합니다.

    화이트리스트에 해당하는 경우:
    - pytest 계열: ("pytest", argv)
    - validate_agent_rules 계열: ("validate_agent_rules", argv)
    화이트리스트 외인 경우:
    - ("unknown", None)
    """
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "unknown", None

    if not tokens:
        return "unknown", None

    # uv run 접두사 제거
    if tokens[:2] == ["uv", "run"]:
        tokens = tokens[2:]
    if not tokens:
        return "unknown", None

    head = tokens[0]

    # 1. pytest 계열
    if head == "pytest":
        argv = ["uv", "run", "pytest", *tokens[1:]]
        if "-q" not in argv and "--quiet" not in argv:
            argv.append("-q")
        return "pytest", argv

    if (
        head in {"python", "python3", sys.executable}
        and len(tokens) > 2
        and tokens[1] == "-m"
        and tokens[2] == "pytest"
    ):
        argv = ["uv", "run", "pytest", *tokens[3:]]
        if "-q" not in argv and "--quiet" not in argv:
            argv.append("-q")
        return "pytest", argv

    # 2. validate_agent_rules 계열
    if head in {"python", "python3", sys.executable} and len(tokens) > 1:
        script_name = PurePosixPath(tokens[1]).name
        if script_name == "validate_agent_rules.py":
            return "validate_agent_rules", [sys.executable, tokens[1], *tokens[2:]]

    if PurePosixPath(head).name == "validate_agent_rules.py":
        return "validate_agent_rules", [sys.executable, head, *tokens[1:]]

    return "unknown", None


def get_verification_timeout(command: str, custom_timeout: int | None = None) -> int:
    """검증 명령에 적용할 타임아웃(초)을 결정합니다.

    custom_timeout 이 명시된 경우(None 이 아님) 해당 값을 최우선으로 사용합니다.
    명시되지 않은 경우 명령 종류에 따라 적절한 기본값을 반환합니다:
    - pytest 계열: DEFAULT_VERIFY_PYTEST_TIMEOUT (900초)
    - validate_agent_rules 계열: DEFAULT_VERIFY_VALIDATE_TIMEOUT (30초)
    - 기타/미분류: DEFAULT_VERIFY_TIMEOUT (30초)
    """
    if custom_timeout is not None:
        return custom_timeout
    cmd_type, _ = classify_verification_command(command)
    if cmd_type == "pytest":
        return DEFAULT_VERIFY_PYTEST_TIMEOUT
    if cmd_type == "validate_agent_rules":
        return DEFAULT_VERIFY_VALIDATE_TIMEOUT
    return DEFAULT_VERIFY_TIMEOUT


def is_whitelisted_verification_command(command: str) -> tuple[bool, list[str] | None]:
    """검증 명령이 게이트 재실행 화이트리스트(pytest, validate_agent_rules)에 해당하는지 판별합니다.

    화이트리스트에 해당하면 (True, argv_list) 를 반환하고, 아니면 (False, None) 을 반환합니다.
    """
    cmd_type, argv = classify_verification_command(command)
    if cmd_type != "unknown" and argv is not None:
        return True, argv
    return False, None


# ANSI 색상 이스케이프 제거 패턴
_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# pytest -q 요약 줄에서 건수를 추출하는 패턴
# 예: "43 passed, 2 skipped in 12.34s", "3 failed, 40 passed in 9.9s"
_PYTEST_COUNT_RE = re.compile(
    r"\b(\d+)\s+(passed|failed|errors?|skipped|xfailed|xpassed|deselected|warnings?)\b",
    re.IGNORECASE,
)
_PYTEST_SUMMARY_MARKER_RE = re.compile(
    r"\b(?:passed|failed|errors?|skipped|xfailed|xpassed)\b",
    re.IGNORECASE,
)

# 건수 동일성 대조에서 제외하는 범주.
# warning 은 결과가 아니라 환경과 의존성 버전에 따라 흔들리는 부수 정보이며
# 정직한 보고서도 대개 적지 않습니다. 대조에 넣으면 참인 보고가 실패합니다.
_COUNT_COMPARE_IGNORED = {"warning"}

# 보고서가 적지 않았는데 실제에만 있을 때 위반으로 볼 범주.
# 실패와 에러를 누락하면 진실성 문제이지만 skipped, deselected 누락은 아닙니다.
_COUNT_OMISSION_CRITICAL = {"failed", "errors"}


def parse_pytest_summary(text: str) -> dict[str, int] | None:
    """pytest -q 출력 전체에서 요약 줄을 찾아 건수 사전을 돌려줍니다.

    출력 뒤에서부터 요약 형태의 줄을 탐색합니다. ANSI 색상 이스케이프와
    '=' 로 둘러싸인 장식 문자를 제거한 뒤 판정합니다. passed/failed/
    errors/skipped/xfailed/xpassed 건수를 정수 사전으로 돌려줍니다.
    요약 줄을 찾지 못하면 None 을 돌려줍니다.
    """
    if not text:
        return None
    lines = text.splitlines()
    for raw in reversed(lines):
        # ANSI 이스케이프 제거
        cleaned = _ANSI_RE.sub("", raw)
        # '=' 장식 제거
        cleaned = re.sub(r"^=+\s*|\s*=+$", "", cleaned).strip()
        if not cleaned:
            continue
        # 요약 줄 특징: 건수 토큰이 있어야 함
        if not _PYTEST_SUMMARY_MARKER_RE.search(cleaned):
            continue
        counts: dict[str, int] = {}
        for m in _PYTEST_COUNT_RE.finditer(cleaned):
            count = int(m.group(1))
            label = m.group(2).lower().rstrip("s")  # errors -> error, warnings -> warning
            # 정규화: error -> errors 를 하나의 키로
            if label in ("error",):
                label = "errors"
            counts[label] = counts.get(label, 0) + count
        if counts:
            return counts
    return None


def _is_failure_result_str(result_str: str) -> bool:
    """결과 문자열이 실패/에러를 나타내는지 검사합니다."""
    cleaned = (result_str or "").strip().lower()
    if not cleaned:
        return False
    # "0 failed", "0 errors", "0 failure" 등은 성공 표기
    if re.search(r"\b0\s*(?:failed|errors?|failures?)\b", cleaned):
        return False
    return bool(re.search(r"\b(?:fail|failed|failure|errors?|blocked|exception|crash)\b", cleaned))


def verify_verification_truth(
    repo: str | Path,
    verification: list[Any],
    timeout: int | None = None,
) -> tuple[bool, list[str], list[dict[str, Any]]]:
    """worker_done 의 verification 배열 진실성을 검증합니다.

    1. 각 항목의 형식(dict 여부, 비어있지 않은 command 및 result 문자열)을 엄격 검증합니다.
    2. 화이트리스트(pytest, validate_agent_rules) 명령은 repo 에서 실제로 재실행하고 결과와 대조합니다.
    3. 화이트리스트 밖 명령은 unverified 로 표기하여 기록합니다.
    4. 재실행 타임아웃 및 실행 실패는 fail-closed 로 처리합니다. 타임아웃 발생 시 status='fail' 및 timed_out=True 로 구분 표기합니다.
    5. pytest 결과 건수를 파싱해 보고서 건수와 대조합니다 (결과 동일성 게이트).
    6. 보고서가 건수를 적지 않은 경우 건너뛰고 기존 pass/fail 판정만 적용합니다(하위 호환).

    반환값: (all_ok, violations, detailed_results)
    """
    repo_path = Path(repo).resolve()
    violations: list[str] = []
    detailed_results: list[dict[str, Any]] = []

    if not isinstance(verification, list):
        return False, ["타입 위반: verification 은 배열이어야 함"], []

    for idx, item in enumerate(verification):
        if not isinstance(item, dict):
            msg = f"형식 위반: verification[{idx}] 은 객체여야 함 ({type(item).__name__})"
            violations.append(msg)
            detailed_results.append(
                {
                    "index": idx,
                    "status": "fail",
                    "reason": msg,
                }
            )
            continue

        cmd = item.get("command")
        res = item.get("result")

        if not isinstance(cmd, str) or not cmd.strip():
            msg = f"형식 위반: verification[{idx}].command 는 비어 있지 않은 문자열이어야 함"
            violations.append(msg)
            detailed_results.append(
                {
                    "index": idx,
                    "command": str(cmd or ""),
                    "reported_result": str(res or ""),
                    "status": "fail",
                    "reason": msg,
                }
            )
            continue

        if not isinstance(res, str) or not res.strip():
            msg = f"형식 위반: verification[{idx}].result 는 비어 있지 않은 문자열이어야 함"
            violations.append(msg)
            detailed_results.append(
                {
                    "index": idx,
                    "command": cmd,
                    "reported_result": str(res or ""),
                    "status": "fail",
                    "reason": msg,
                }
            )
            continue

        cmd_clean = cmd.strip()
        res_clean = res.strip()

        cmd_type, argv = classify_verification_command(cmd_clean)
        if cmd_type == "unknown" or argv is None:
            # 화이트리스트 밖 명령: unverified 로 명시
            detailed_results.append(
                {
                    "index": idx,
                    "command": cmd_clean,
                    "reported_result": res_clean,
                    "status": "unverified",
                    "reason": "화이트리스트 외 명령 (게이트 재실행 대상 아님)",
                    "actual_counts": None,
                    "reported_counts": None,
                    "count_match": None,
                    "actual_exit_code": None,
                    "stdout_digest": None,
                }
            )
            continue

        effective_timeout = get_verification_timeout(cmd_clean, timeout)

        # 화이트리스트 명령: repo 에서 재실행
        try:
            proc = subprocess.run(  # nosec B603
                argv,
                cwd=str(repo_path),
                capture_output=True,
                text=True,
                timeout=effective_timeout,
                check=False,
            )
            code = proc.returncode
            stdout = proc.stdout
            stderr = proc.stderr
            timed_out = False
        except subprocess.TimeoutExpired as exc:
            code = -1
            stdout = (
                exc.stdout
                if isinstance(exc.stdout, str)
                else (exc.stdout or b"").decode("utf-8", errors="replace")
            )
            stderr = (
                exc.stderr
                if isinstance(exc.stderr, str)
                else (exc.stderr or b"").decode("utf-8", errors="replace")
            )
            timed_out = True
        except Exception as exc:
            msg = f"재실행 실패: '{cmd_clean}' 실행 불가 ({exc})"
            violations.append(msg)
            detailed_results.append(
                {
                    "index": idx,
                    "command": cmd_clean,
                    "reported_result": res_clean,
                    "status": "fail",
                    "reason": msg,
                    "actual_counts": None,
                    "reported_counts": None,
                    "count_match": None,
                    "actual_exit_code": None,
                    "stdout_digest": None,
                }
            )
            continue

        if timed_out:
            msg = f"재실행 타임아웃 ({cmd_type}, {effective_timeout}초): '{cmd_clean}'"
            violations.append(msg)
            detailed_results.append(
                {
                    "index": idx,
                    "command": cmd_clean,
                    "reported_result": res_clean,
                    "status": "fail",
                    "timed_out": True,
                    "timeout_seconds": effective_timeout,
                    "command_type": cmd_type,
                    "reason": msg,
                    "actual_counts": None,
                    "reported_counts": None,
                    "count_match": None,
                    "actual_exit_code": code,
                    "stdout_digest": None,
                }
            )
            continue

        # stdout_digest: 재실행 stdout+stderr 의 sha256 앞 16 자리 (기록용)
        combined_output = stdout + stderr
        stdout_digest = hashlib.sha256(
            combined_output.encode("utf-8", errors="replace")
        ).hexdigest()[:16]

        # 출력 요약 추출
        summary_text = combined_output.strip()
        summary_line = (
            summary_text.splitlines()[-1].strip() if summary_text.splitlines() else "출력 없음"
        )

        # 실제 건수 파싱
        actual_counts = parse_pytest_summary(combined_output)

        # 보고서 건수 파싱: 명시적 필드 우선, 없으면 result 문자열에서 파싱
        reported_counts: dict[str, int] | None = None
        explicit_fields_present = False

        explicit_passed = item.get("passed")
        explicit_failed = item.get("failed")
        explicit_skipped = item.get("skipped")
        explicit_exit_code = item.get("exit_code")

        if any(v is not None for v in (explicit_passed, explicit_failed, explicit_skipped)):
            explicit_fields_present = True
            reported_counts = {}
            if explicit_passed is not None:
                reported_counts["passed"] = int(explicit_passed)
            if explicit_failed is not None:
                reported_counts["failed"] = int(explicit_failed)
            if explicit_skipped is not None:
                reported_counts["skipped"] = int(explicit_skipped)
        else:
            reported_counts = parse_pytest_summary(res_clean)

        # 명시적 exit_code 필드 대조
        if explicit_exit_code is not None and code != int(explicit_exit_code):
            msg = (
                f"검증 불일치: '{cmd_clean}' 명시 exit_code={explicit_exit_code} 이지만 "
                f"실제 exit code={code}"
            )
            violations.append(msg)
            detailed_results.append(
                {
                    "index": idx,
                    "command": cmd_clean,
                    "reported_result": res_clean,
                    "actual_exit_code": code,
                    "actual_summary": summary_line,
                    "actual_counts": actual_counts,
                    "reported_counts": reported_counts,
                    "count_match": False,
                    "stdout_digest": stdout_digest,
                    "status": "fail",
                    "reason": msg,
                }
            )
            continue

        # 결과 대조: exit code 우선
        if code != 0:
            # 실제 실행 실패 (테스트 실패, assertion error 등)
            msg = (
                f"검증 불일치/실패: '{cmd_clean}' 실제 실행 실패 (exit code {code}), "
                f"보고서에는 '{res_clean}' 로 기재됨 (출력: {summary_line})"
            )
            violations.append(msg)
            detailed_results.append(
                {
                    "index": idx,
                    "command": cmd_clean,
                    "reported_result": res_clean,
                    "actual_exit_code": code,
                    "actual_summary": summary_line,
                    "actual_counts": actual_counts,
                    "reported_counts": reported_counts,
                    "count_match": None,
                    "stdout_digest": stdout_digest,
                    "status": "fail",
                    "reason": msg,
                }
            )
        elif _is_failure_result_str(res_clean) and not explicit_fields_present:
            # 실제로는 성공(code==0)인데 보고서에 실패라고 적은 경우
            msg = (
                f"검증 불일치: '{cmd_clean}' 실제 실행 통과 (exit code 0)이나 "
                f"보고서에는 실패('{res_clean}')로 기재됨"
            )
            violations.append(msg)
            detailed_results.append(
                {
                    "index": idx,
                    "command": cmd_clean,
                    "reported_result": res_clean,
                    "actual_exit_code": code,
                    "actual_summary": summary_line,
                    "actual_counts": actual_counts,
                    "reported_counts": reported_counts,
                    "count_match": None,
                    "stdout_digest": stdout_digest,
                    "status": "fail",
                    "reason": msg,
                }
            )
        else:
            # exit code 통과: 건수 동일성 대조
            count_match: bool | None = None
            count_violation_msg: str | None = None

            if reported_counts is not None and actual_counts is not None:
                # 보고서가 건수를 적었을 때만 대조한다
                mismatches: list[str] = []
                for key in reported_counts:
                    if key in _COUNT_COMPARE_IGNORED:
                        continue
                    reported_val = reported_counts[key]
                    actual_val = actual_counts.get(key, 0)
                    if reported_val != actual_val:
                        mismatches.append(f"{key}: 보고={reported_val}, 실제={actual_val}")
                # 보고서가 적지 않은 범주는 대조하지 않습니다. 누락을 0 으로 간주하면
                # 정직한 축약 보고가 실패합니다. 실패와 에러 누락만 위반입니다.
                for key in actual_counts:
                    if key in _COUNT_COMPARE_IGNORED or key in reported_counts:
                        continue
                    if key in _COUNT_OMISSION_CRITICAL and actual_counts[key] != 0:
                        mismatches.append(f"{key}: 보고=0(미기재), 실제={actual_counts[key]}")
                if mismatches:
                    count_match = False
                    count_violation_msg = (
                        f"건수 불일치: '{cmd_clean}' 보고 건수와 실제 건수가 다름 "
                        f"({'; '.join(mismatches)})"
                    )
                else:
                    count_match = True
            elif reported_counts is not None and actual_counts is None:
                # 보고는 있는데 실제 출력에서 파싱 불가 -> 대조 불가 (건너뜀)
                count_match = None
            else:
                # 보고서가 건수를 적지 않음 -> 하위 호환, 대조 건너뜀
                count_match = None

            if count_violation_msg is not None:
                violations.append(count_violation_msg)
                detailed_results.append(
                    {
                        "index": idx,
                        "command": cmd_clean,
                        "reported_result": res_clean,
                        "actual_exit_code": code,
                        "actual_summary": summary_line,
                        "actual_counts": actual_counts,
                        "reported_counts": reported_counts,
                        "count_match": count_match,
                        "stdout_digest": stdout_digest,
                        "status": "fail",
                        "reason": count_violation_msg,
                    }
                )
            else:
                detailed_results.append(
                    {
                        "index": idx,
                        "command": cmd_clean,
                        "reported_result": res_clean,
                        "actual_exit_code": code,
                        "actual_summary": summary_line,
                        "actual_counts": actual_counts,
                        "reported_counts": reported_counts,
                        "count_match": count_match,
                        "stdout_digest": stdout_digest,
                        "status": "pass",
                        "reason": "재실행 결과 일치 (통과)",
                    }
                )

    all_ok = len(violations) == 0
    return all_ok, violations, detailed_results
