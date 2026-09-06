#!/usr/bin/env python3
"""scripts/orca_read_scope_audit.py

Orca 워커 읽기 스코프 사후 감사 도구 (Read Scope Post-Audit).

워커 터미널의 화면 버퍼(또는 버퍼 텍스트 파일)를 파싱하여 워커가 Capsule 의
`search_scope.allowed_globs` 및 `allowed_read_files` 범위를 벗어난 경로를
실제로 읽었거나 접근했는지 사후에 검사합니다.

[중요 한계 및 주의사항 (Limitations)]
본 도구는 워커 터미널의 화면 버퍼(tail/preview)에 남아 있는 출력 텍스트에만 의존합니다.
화면 버퍼는 스크롤이나 긴 출력으로 인해 잘리거나(truncated) 밀려날 수 있습니다.
따라서 본 감사는 '화면 버퍼에 증거가 남아 있는 범위'에서만 유효하며,
'위반 없음(clean)' 판정이 '실제로 위반이 전혀 없었다'는 완전한 증명이 되지는 못합니다.
이 도구의 결과를 절대적인 안전 게이트나 커밋 차단용 하드 게이트로 오해해서는 안 되며,
사후 감사 및 이상 징후 조기 탐지 목적으로 활용해야 합니다.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess  # nosec B404 - 고정된 orca 인자만 호출합니다
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        load_capsule,
        matches_any,
        parse_capsule_list,
        parse_capsule_scalar,
    )
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_contract import (
        load_capsule,
        matches_any,
        parse_capsule_list,
        parse_capsule_scalar,
    )

# ANSI 색상 이스케이프 패턴
_ANSI_RE = re.compile(r"\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])")

# URL 스킴 제외 패턴 (http, https, file 등)
_URL_RE = re.compile(r"(?:https?|file)://[^\s\"'<>`()\[\]{}]+", re.IGNORECASE)

# 시스템 경로 허용 목록 (잡음 억제용 모듈 상수)
SYSTEM_ALLOWLIST_PREFIXES: tuple[str, ...] = (
    "/usr",
    "/bin",
    "/sbin",
    "/etc",
    "/opt",
    "/Library",
    "/System",
    "/private/var",
    "/private/tmp",
    "/tmp",  # nosec B108 # noqa: S108
    "/dev",
    "/proc",
)

SYSTEM_ALLOWLIST_CONTAINS: tuple[str, ...] = (
    ".venv",
    "site-packages",
    "node_modules",
    "__pycache__",
)


def parse_search_scope_allowed_globs(capsule_text: str) -> list[str]:
    """Capsule 의 search_scope.allowed_globs 목록을 파싱합니다."""
    lines = capsule_text.splitlines()
    in_search_scope = False
    in_allowed_globs = False
    globs: list[str] = []
    globs_indent = -1

    for raw in lines:
        if raw and not raw[0].isspace():
            if raw.startswith("#"):
                continue
            if re.match(r"^search_scope:[ \t]*(?:#.*)?$", raw):
                in_search_scope = True
                in_allowed_globs = False
                continue
            else:
                if in_search_scope:
                    break

        if not in_search_scope:
            continue

        line = raw.strip()
        if not line or line.startswith("#"):
            continue

        m = re.match(r"^allowed_globs:[ \t]*(.*)$", line)
        if m:
            val = m.group(1).strip()
            clean_val = re.sub(r"\s+#.*$", "", val).strip()
            if clean_val == "[]":
                return []
            if clean_val.startswith("[") and clean_val.endswith("]"):
                inner = clean_val[1:-1].strip()
                if not inner:
                    return []
                items: list[str] = []
                for part in inner.split(","):
                    p = part.strip().strip("'\"")
                    if p:
                        items.append(p)
                return items
            in_allowed_globs = True
            globs_indent = len(raw) - len(raw.lstrip())
            continue

        if in_allowed_globs:
            current_indent = len(raw) - len(raw.lstrip())
            if current_indent <= globs_indent:
                break
            if not line.startswith("- "):
                continue
            val = line[2:].strip()
            if val.startswith('"'):
                m_val = re.match(r'^"((?:[^"\\]|\\.)*)"(?:\s+#.*)?$', val)
                if m_val:
                    globs.append(m_val.group(1).replace('\\"', '"').replace("\\\\", "\\"))
                    continue
            elif val.startswith("'"):
                m_val = re.match(r"^'([^']*)'(?:\s+#.*)?$", val)
                if m_val:
                    globs.append(m_val.group(1))
                    continue
            unquoted = re.sub(r"\s+#.*$", "", val).strip()
            if unquoted:
                globs.append(unquoted)

    return globs


def is_system_path(path: str) -> bool:
    """시스템 경로 또는 빌드/의존성 잡음 경로인지 확인합니다."""
    for prefix in SYSTEM_ALLOWLIST_PREFIXES:
        p_clean = prefix.rstrip("/")
        if path == p_clean or path.startswith(f"{p_clean}/"):
            return True
    return any(sub in path for sub in SYSTEM_ALLOWLIST_CONTAINS)


def extract_paths_from_text(text: str) -> list[str]:
    """화면 텍스트에서 ANSI 와 URL 을 제거하고 유효한 경로 토큰들을 추출합니다.

    절대 경로(/ 시작), 홈 경로(~/ 시작), 워크트리 상대 경로를 추출하며,
    중복을 제거하고 정렬하여 반환합니다.
    """
    clean_text = _ANSI_RE.sub("", text)
    clean_text = re.sub(r"\\x1b(?:[@-Z\\-_]|\[[0-?]*[ -/]*[@-~])", "", clean_text)
    clean_text = _URL_RE.sub(" ", clean_text)
    clean_text = re.sub(r"\\[nrt]", " ", clean_text)

    tokens = re.split(r"[\s\"'`()\[\]{}<>,;=|]+", clean_text)
    extracted: set[str] = set()

    for raw_token in tokens:
        token = raw_token.strip()
        if not token or "/" not in token:
            continue

        # 순수 슬래시나 점으로만 이루어진 토큰(/, //, ./, ../ 등) 제외
        if not token.strip("/."):
            continue

        # 앞뒤 콜론 제거 및 컴파일러 옵션(-I/usr..., -L/...) 접두부 제거
        token = token.lstrip(":")
        if re.match(r"^-[a-zA-Z]/", token):
            token = token[2:]

        # 뒤에 붙은 라인 번호(:123:45 또는 :123) 제거 및 콜론 정리
        token = token.rstrip(":")
        token = re.sub(r":\d+(?::\d+)?$", "", token)
        token = token.rstrip(":")

        # 문장 끝 단일 마침표 제거 (.. 나 ... 는 보존)
        if token.endswith(".") and not token.endswith(".."):
            token = token.rstrip(".")

        if "/" not in token or not token.strip("/."):
            continue

        # 날짜 형식(YYYY/MM/DD) 제외
        if re.match(r"^\d{4}/\d{2}/\d{2}$", token):
            continue

        # 상대 경로의 불필요한 선행 ./ 정규화
        if token.startswith("./"):
            token = token[2:]
            if not token or "/" not in token:
                continue

        # 경로 시작 문자 검증: /, ~, 또는 일반 파일명 시작 문자
        if not (
            token.startswith("/") or token.startswith("~") or re.match(r"^[a-zA-Z0-9._]", token)
        ):
            continue

        extracted.add(token)

    return sorted(extracted)


def read_terminal_buffer(handle: str, timeout: int = 30) -> str | None:
    """orca terminal read 명령으로 워커 터미널의 화면 버퍼를 읽습니다."""
    cmd = ["orca", "terminal", "read", "--terminal", handle, "--json"]
    try:
        proc = subprocess.run(  # nosec B603 B607
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (subprocess.SubprocessError, OSError):
        return None

    if proc.returncode != 0 or not proc.stdout.strip():
        return None

    try:
        payload = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return None

    if not isinstance(payload, dict) or payload.get("ok") is False:
        return None

    terminal = (payload.get("result") or {}).get("terminal") or {}
    tail = terminal.get("tail")
    if isinstance(tail, list):
        return "\n".join(str(line) for line in tail)
    if isinstance(tail, str):
        return tail
    return None


def audit_read_scope(
    *,
    text: str,
    capsule_path: Path | str,
    repo: Path | str = ".",
    no_system_allowlist: bool = False,
    terminal_label: str | list[str] | None = None,
    text_file_label: str | None = None,
) -> tuple[int, dict[str, Any]]:
    """텍스트에서 경로를 추출하고 Capsule 의 읽기 허용 범위와 대조하여 판정합니다.

    반환값: (종료 코드, 결과 딕셔너리)
      - 0: 위반 없음 (clean)
      - 1: 위반 발견 (violations)
      - 2: 도구 오류 (fail-closed)
    """
    repo_path = Path(repo).resolve()
    capsule_file = Path(capsule_path)

    try:
        capsule_text = load_capsule(capsule_file)
    except Exception as exc:
        return 2, {"error": f"Capsule 로드 실패: {exc}"}

    allowed_read_files = parse_capsule_list(capsule_text, "allowed_read_files")
    search_scope_globs = parse_search_scope_allowed_globs(capsule_text)
    allowed_patterns = allowed_read_files + search_scope_globs

    read_paths = extract_paths_from_text(text)
    outside_worktree: list[str] = []
    scope_excess: list[str] = []

    for p in read_paths:
        if not no_system_allowlist and is_system_path(p):
            continue

        if p.startswith("~"):
            expanded_str = os.path.expanduser(p)
            is_abs = True
        elif p.startswith("/"):
            expanded_str = p
            is_abs = True
        else:
            expanded_str = None
            is_abs = False

        if is_abs:
            abs_path = Path(expanded_str).resolve()
            try:
                rel_path = abs_path.relative_to(repo_path)
                rel_str = str(rel_path).replace("\\", "/")
                if not matches_any(rel_str, allowed_patterns):
                    scope_excess.append(p)
            except ValueError:
                outside_worktree.append(p)
        else:
            target_path = (repo_path / p).resolve()
            try:
                rel_path = target_path.relative_to(repo_path)
                rel_str = str(rel_path).replace("\\", "/")
                if not matches_any(rel_str, allowed_patterns):
                    scope_excess.append(p)
            except ValueError:
                outside_worktree.append(p)

    outside_sorted = sorted(set(outside_worktree))
    excess_sorted = sorted(set(scope_excess))
    verdict = "violations" if (outside_sorted or excess_sorted) else "clean"
    exit_code = 1 if verdict == "violations" else 0

    result: dict[str, Any] = {}
    if text_file_label is not None:
        result["text_file"] = text_file_label
    elif terminal_label is not None:
        result["terminal"] = terminal_label
    else:
        result["terminal"] = "unknown"

    result["capsule"] = str(capsule_file)
    result["repo"] = str(repo_path)
    result["read_paths"] = read_paths
    result["outside_worktree"] = outside_sorted
    result["scope_excess"] = excess_sorted
    result["verdict"] = verdict

    return exit_code, result


def main(argv: list[str] | None = None) -> int:
    """CLI 진입점."""
    parser = argparse.ArgumentParser(
        description="Orca 워커 읽기 스코프 사후 감사 도구",
    )
    parser.add_argument(
        "--terminal",
        action="append",
        dest="terminals",
        help="워커 터미널 핸들 (반복 지정 가능)",
    )
    parser.add_argument(
        "--text-file",
        dest="text_file",
        type=Path,
        help="버퍼 텍스트 파일 경로 (테스트 및 오프라인 감사용)",
    )
    parser.add_argument(
        "--capsule",
        dest="capsule",
        type=Path,
        required=True,
        help="Task Capsule 파일 경로",
    )
    parser.add_argument(
        "--repo",
        dest="repo",
        type=Path,
        default=Path("."),
        help="저장소 루트 디렉터리 (기본값: 현재 디렉터리)",
    )
    parser.add_argument(
        "--out",
        dest="out",
        type=Path,
        default=None,
        help="감사 결과 JSON 출력 파일 경로",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="결과를 표준 출력에 JSON 으로 출력",
    )
    parser.add_argument(
        "--no-system-allowlist",
        action="store_true",
        dest="no_system_allowlist",
        help="시스템 경로 허용 목록을 끄고 전량 판정",
    )

    args = parser.parse_args(argv)

    if not args.terminals and not args.text_file:
        sys.stderr.write("오류: --terminal 또는 --text-file 중 하나를 지정해야 합니다.\n")
        return 2

    if args.terminals and args.text_file:
        sys.stderr.write("오류: --terminal 과 --text-file 은 동시에 지정할 수 없습니다.\n")
        return 2

    # Capsule 확인
    if not args.capsule.exists():
        sys.stderr.write(f"오류: Capsule 파일을 찾을 수 없습니다: {args.capsule}\n")
        return 2

    try:
        capsule_raw = load_capsule(args.capsule)
    except Exception as exc:
        sys.stderr.write(f"오류: Capsule 읽기 실패: {exc}\n")
        return 2

    task_id = parse_capsule_scalar(capsule_raw, "task_id") or "unknown"

    # 버퍼 텍스트 확보
    text_content: str
    terminal_label: str | list[str] | None = None
    text_file_label: str | None = None

    if args.text_file:
        text_file_path = args.text_file
        if not text_file_path.exists():
            sys.stderr.write(f"오류: 텍스트 파일을 찾을 수 없습니다: {text_file_path}\n")
            return 2
        try:
            text_content = text_file_path.read_text(encoding="utf-8")
        except Exception as exc:
            sys.stderr.write(f"오류: 텍스트 파일 읽기 실패: {exc}\n")
            return 2
        text_file_label = str(text_file_path)
    else:
        buffer_chunks: list[str] = []
        for handle in args.terminals:
            chunk = read_terminal_buffer(handle)
            if chunk is None:
                sys.stderr.write(f"오류: 터미널 버퍼를 읽지 못했습니다 (handle={handle})\n")
                return 2
            buffer_chunks.append(chunk)
        text_content = "\n".join(buffer_chunks)
        terminal_label = args.terminals[0] if len(args.terminals) == 1 else args.terminals

    exit_code, result = audit_read_scope(
        text=text_content,
        capsule_path=args.capsule,
        repo=args.repo,
        no_system_allowlist=args.no_system_allowlist,
        terminal_label=terminal_label,
        text_file_label=text_file_label,
    )

    if exit_code == 2:
        sys.stderr.write(f"도구 오류: {result.get('error')}\n")
        return 2

    # 결과 JSON 저장 경로 결정
    repo_path = Path(args.repo).resolve()
    if args.out:
        out_path = Path(args.out)
    else:
        out_path = repo_path / ".orca" / "reports" / f"read_scope_audit_{task_id}.json"

    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(
            json.dumps(result, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:
        sys.stderr.write(f"오류: 결과 파일 쓰기 실패: {exc}\n")
        return 2

    if args.json_output:
        sys.stdout.write(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    else:
        status_msg = (
            "위반 없음 (clean)" if result["verdict"] == "clean" else "위반 발견 (violations)"
        )
        sys.stdout.write(f"[판정] {status_msg}\n")
        if result["outside_worktree"]:
            sys.stdout.write(
                f"  - outside_worktree ({len(result['outside_worktree'])}건): {result['outside_worktree']}\n"
            )
        if result["scope_excess"]:
            sys.stdout.write(
                f"  - scope_excess ({len(result['scope_excess'])}건): {result['scope_excess']}\n"
            )
        sys.stdout.write(f"결과 저장: {out_path}\n")

    return exit_code


if __name__ == "__main__":
    sys.exit(main())
