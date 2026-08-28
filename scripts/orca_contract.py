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

import json
import re
import subprocess  # nosec B404
from pathlib import Path
from typing import Any


class ContractError(Exception):
    """Capsule 또는 보고가 계약 형식을 만족하지 않을 때 발생합니다."""


# Capsule 에서 경로 목록으로 다루는 필드
PATH_LIST_FIELDS = ("allowed_read_files", "allowed_write_files", "artifact_paths")

# 경로 패턴에서 "이 아래 전부" 를 뜻하는 접미사. Capsule 예시가 `src/...` 를 씁니다.
_PREFIX_SUFFIXES = ("/...", "/**", "/")


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
        repo, ["diff", "--name-only", f"{base_clean}..{branch_clean}"]
    )
    if code != 0:
        err = stderr.strip() or "git diff 실패"
        return False, f"git diff 실행 실패 ({base_clean}..{branch_clean}): {err}"

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
