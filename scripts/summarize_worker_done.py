#!/usr/bin/env python3
"""
scripts/summarize_worker_done.py

워커의 완료 보고(ORCA_WORKER_DONE_V2)를 검증하고 고정 상한 이하의 다이제스트로 요약합니다.

주요 기능:
  1. 필수 필드 누락 검증 (REQUIRED_FIELDS)
  2. status == "succeeded" 인데 commit_count == 0 인 무작업 완료 보고 검증 (규약 3.3, 읽기 전용 Capsule 제외)
  3. Task Capsule 의 allowed_read_files 및 allowed_write_files 대조 (scope_excess / write_scope_excess)
  4. blocking_issues 가 있을 때 verdict(pass/candidate)를 blocked 로 자동 격하
  5. 단일 필드 길이 초과(contract bloat) 검출
  6. 최대 길이(--max-chars)가 보장된 텍스트 다이제스트 또는 JSON 요약 출력

종료 코드:
  - 0: 위반 0건 및 실효 verdict 격하 없음
  - 1: 계약 위반 검출 또는 verdict 격하 발생
  - 2: 보고 파일 없음, Capsule 파일 없음 또는 JSON 파싱 오류 (ContractError)
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        ContractError,
        char_len,
        load_capsule,
        load_report,
        parse_capsule_list,
        scope_excess,
        string_list,
        truncate,
        verify_branch_exists,
        verify_commit_exists,
        write_scope_excess,
    )
except ImportError:
    # 저장소 루트를 sys.path 에 추가하여 직접 실행(python3 scripts/...) 시 모듈 해석 지원
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.orca_contract import (
        ContractError,
        char_len,
        load_capsule,
        load_report,
        parse_capsule_list,
        scope_excess,
        string_list,
        truncate,
        verify_branch_exists,
        verify_commit_exists,
        write_scope_excess,
    )

REQUIRED_FIELDS = (
    "schema",
    "version",
    "task_id",
    "status",
    "branch",
    "commit",
    "commit_count",
    "changed_files",
    "read_files",
    "verification",
    "verdict",
    "blocking_issues",
)


# 계약이 허용하는 값 집합입니다. 필드 존재 여부만 보고 타입을 보지 않으면
# 문자열 "0" 이 정수 0 검사를 그대로 지나갑니다. 외부 워커가 항상 올바른
# 타입을 만든다는 보장이 없으므로 여기서 형과 범위를 함께 강제합니다.
ALLOWED_STATUS = ("succeeded", "escalation")
# verdict 는 pass 와 candidate 가 blocking_issues 존재 시 blocked 로 격하되는
# 계약이므로 세 값을 모두 받습니다.
ALLOWED_VERDICT = ("pass", "candidate", "blocked")


def check_field_types(report_data: dict[str, Any]) -> list[str]:
    """보고 필드의 형과 값 범위를 검사해 위반 목록을 돌려줍니다."""
    violations: list[str] = []

    commit_count = report_data.get("commit_count")
    if "commit_count" in report_data:
        # bool 은 int 의 하위형이라 True 가 1 로 통과합니다. 따로 막습니다.
        if isinstance(commit_count, bool) or not isinstance(commit_count, int):
            violations.append(
                f"타입 위반: commit_count 는 정수여야 하는데 "
                f"{type(commit_count).__name__} ({commit_count!r})"
            )
        elif commit_count < 0:
            violations.append(f"값 위반: commit_count 가 음수 ({commit_count})")

    status = report_data.get("status")
    if "status" in report_data and status not in ALLOWED_STATUS:
        violations.append(
            f"값 위반: status 는 {' 또는 '.join(ALLOWED_STATUS)} 여야 하는데 {status!r}"
        )

    verdict = report_data.get("verdict")
    if "verdict" in report_data and verdict not in ALLOWED_VERDICT:
        violations.append(
            f"값 위반: verdict 는 {' 또는 '.join(ALLOWED_VERDICT)} 여야 하는데 {verdict!r}"
        )

    for field_name in ("changed_files", "read_files", "blocking_issues"):
        if field_name not in report_data:
            continue
        value = report_data[field_name]
        if not isinstance(value, list):
            violations.append(
                f"타입 위반: {field_name} 는 배열이어야 하는데 {type(value).__name__}"
            )
        elif not all(isinstance(item, str) for item in value):
            violations.append(f"타입 위반: {field_name} 의 원소는 전부 문자열이어야 함")

    verification = report_data.get("verification")
    if "verification" in report_data:
        if not isinstance(verification, list):
            violations.append(
                f"타입 위반: verification 는 배열이어야 하는데 {type(verification).__name__}"
            )
        elif not all(isinstance(item, dict) for item in verification):
            violations.append("타입 위반: verification 의 원소는 전부 객체여야 함")

    return violations


def _find_bloated_fields(data: Any, max_len: int, path: str = "") -> list[tuple[str, int]]:
    """문자열 필드 중 max_len 을 초과하는 필드와 길이를 재귀적으로 탐색합니다."""
    bloated: list[tuple[str, int]] = []
    if isinstance(data, str):
        length = char_len(data)
        if length > max_len:
            bloated.append((path or "string", length))
    elif isinstance(data, dict):
        for k, v in data.items():
            sub_path = f"{path}.{k}" if path else str(k)
            bloated.extend(_find_bloated_fields(v, max_len, sub_path))
    elif isinstance(data, list):
        for idx, item in enumerate(data):
            sub_path = f"{path}[{idx}]"
            bloated.extend(_find_bloated_fields(item, max_len, sub_path))
    return bloated


def _format_section_with_budget(
    header: str,
    items: list[str],
    available_chars: int,
) -> tuple[list[str], int]:
    """주어진 예산(문자 수) 안에서 헤더와 항목 목록을 구성하며, 초과 시 생략 건수를 명시합니다.

    반환값: (생성된 라인 목록, 사용된 문자 수)
    """
    if not items:
        return [], 0

    header_len = char_len(header)
    if available_chars < header_len:
        return [header], header_len

    total_count = len(items)

    # 1. 모든 항목이 다 들어갈 수 있는지 확인
    all_lines = [header, *items]
    all_text = "\n".join(all_lines)
    if char_len(all_text) <= available_chars:
        return all_lines, char_len(all_text)

    # 2. 일부만 들어갈 수 있는 경우: 가능한 만큼 넣고 '... 외 M건 생략' 추가
    lines = [header]
    cur_len = header_len

    for i in range(total_count):
        item = items[i]
        item_len = 1 + char_len(item)  # 줄바꿈 포함
        omitted = total_count - (i + 1)
        omission_line = f"  * ... 외 {omitted}건 생략" if omitted > 0 else ""
        omission_len = (1 + char_len(omission_line)) if omission_line else 0

        if cur_len + item_len + omission_len <= available_chars:
            lines.append(item)
            cur_len += item_len
        else:
            actual_omitted = total_count - (len(lines) - 1)
            if actual_omitted > 0:
                final_omission = f"  * ... 외 {actual_omitted}건 생략"
                if cur_len + 1 + char_len(final_omission) <= available_chars:
                    lines.append(final_omission)
                    cur_len += 1 + char_len(final_omission)
                else:
                    short_omission = f"  * (외 {actual_omitted}건 생략)"
                    if cur_len + 1 + char_len(short_omission) <= available_chars:
                        lines.append(short_omission)
                        cur_len += 1 + char_len(short_omission)
            break

    result_text = "\n".join(lines)
    return lines, char_len(result_text)


def summarize_worker_report(
    report_path: str | Path,
    capsule_path: str | Path | None = None,
    repo_path: str | Path | None = None,
    max_chars: int = 1200,
    field_max_chars: int = 600,
) -> dict[str, Any]:
    """워커 완료 보고를 검증하고 다이제스트 요약 데이터를 생성합니다."""
    report_data = load_report(report_path)
    violations: list[str] = []

    # 1. 필수 필드 존재 여부 검사
    for field_name in REQUIRED_FIELDS:
        if field_name not in report_data:
            violations.append(f"필수 필드 누락: {field_name}")

    schema_val = report_data.get("schema")
    if "schema" in report_data and schema_val != "ORCA_WORKER_DONE_V2":
        violations.append(f"schema 불일치: '{schema_val}' (ORCA_WORKER_DONE_V2 이어야 함)")

    version_val = report_data.get("version")
    if "version" in report_data and not str(version_val or "").strip():
        violations.append("version 값이 비어 있음")

    status = report_data.get("status")
    commit_count = report_data.get("commit_count")
    changed_files = string_list(report_data.get("changed_files"))
    read_files = string_list(report_data.get("read_files"))

    # 1-1. commit 및 branch 진실성(실존성) 검증 (repo_path 가 명시된 경우 실행)
    if repo_path is not None:
        target_repo = Path(repo_path).resolve()
        commit_raw = str(report_data.get("commit", "")).strip()
        branch_raw = str(report_data.get("branch", "")).strip()

        if commit_raw:
            commit_ok, commit_msg = verify_commit_exists(target_repo, commit_raw)
            if not commit_ok:
                violations.append(commit_msg)

        if branch_raw:
            branch_ok, branch_msg = verify_branch_exists(target_repo, branch_raw)
            if not branch_ok:
                violations.append(branch_msg)

    # 2. 위반 검사 A: status == succeeded 인데 commit_count == 0 이면 무작업 완료 보고 (규약 3.3)
    #    읽기 전용 Task(allowed_write_files 가 빈 목록)는 커밋이 없는 것이 정상이므로 예외로 둔다.
    allowed_read: list[str] = []
    allowed_write: list[str] = []
    if capsule_path is not None:
        capsule_text = load_capsule(capsule_path)
        allowed_read = parse_capsule_list(capsule_text, "allowed_read_files")
        allowed_write = parse_capsule_list(capsule_text, "allowed_write_files")

    violations.extend(check_field_types(report_data))

    read_only_task = capsule_path is not None and not allowed_write
    if status == "succeeded" and commit_count == 0 and not read_only_task:
        violations.append(
            "규약 3.3 위반: status 가 succeeded 인데 commit_count 가 0 (무작업 완료 보고)"
        )

    # 3. 위반 검사 B & C: Capsule 범위 검사
    read_excess: list[str] = []
    write_excess: list[str] = []
    if capsule_path is not None:
        # B: read_files 초과는 지시 불일치 사후 확인용이므로 read_scope_excess 로 기록하되 위반으로 세지 않음 (규약 2.9.2)
        read_excess = scope_excess(read_files, allowed_read)

        # C: changed_files 초과는 범위 위반이므로 위반으로 집계
        write_excess = write_scope_excess(changed_files, allowed_write)
        if write_excess:
            violations.append(f"allowed_write_files 범위 초과: {', '.join(write_excess)}")

    # 4. 위반 검사 D: 계약 비대 (contract bloat) 검사
    bloated = _find_bloated_fields(report_data, field_max_chars)
    for field_path, length in bloated:
        violations.append(
            f"계약 비대 (contract bloat): 필드 '{field_path}' 길이 {length}자가 field_max_chars({field_max_chars}) 초과"
        )

    # 5. 위반 검사 E: verdict 격하 검사
    declared_verdict = str(report_data.get("verdict", ""))
    blocking_issues = report_data.get("blocking_issues")
    has_blocking_issues = False
    if isinstance(blocking_issues, list):
        has_blocking_issues = len(blocking_issues) > 0
    elif blocking_issues:
        has_blocking_issues = True

    if declared_verdict in ("pass", "candidate") and has_blocking_issues:
        effective_verdict = "blocked"
        violations.append(
            f"verdict 격하: 선언값 '{declared_verdict}' -> 실효값 'blocked' (blocking_issues 가 존재함)"
        )
    elif declared_verdict in ("pass", "candidate") and violations:
        effective_verdict = "blocked"
    else:
        effective_verdict = declared_verdict

    # 다이제스트 포맷 구성 (결정 중요도 우선순위 적용)
    commit_raw = str(report_data.get("commit", ""))
    short_commit = commit_raw[:8] if commit_raw else "(none)"

    if not changed_files:
        files_preview = "(없음)"
    elif len(changed_files) <= 5:
        files_preview = ", ".join(changed_files)
    else:
        files_preview = ", ".join(changed_files[:5]) + f" ... 외 {len(changed_files) - 5}개"

    write_scope_info = f" ({', '.join(write_excess)})" if write_excess else ""
    read_scope_info = f" ({', '.join(read_excess)})" if read_excess else ""

    # 1) 머리글 및 고정 요약 줄
    digest_parts: list[str] = [
        "[Worker Done Summary]",
        f"- Status: {status}",
        f"- Verdict: {declared_verdict} (실효: {effective_verdict})",
        f"- Branch: {report_data.get('branch')} (commit: {short_commit}, count: {commit_count})",
        f"- Changed files ({len(changed_files)}개): {files_preview}",
        f"- Read files: {len(read_files)}개",
    ]

    # 2) Violations (우선순위 1: 결정적 반려 요인)
    viol_items = [f"  * {v}" for v in violations]
    if violations:
        current_len = char_len("\n".join(digest_parts)) + 1
        rem = max_chars - current_len
        v_lines, _ = _format_section_with_budget(
            f"- Violations ({len(violations)}건):",
            viol_items,
            rem,
        )
        if v_lines:
            digest_parts.extend(v_lines)
        else:
            digest_parts.append(f"- Violations ({len(violations)}건): (생략)")
    else:
        digest_parts.append("- Violations: 0건 (계약 준수)")

    # 3) Blocking issues (우선순위 2: 차단 이슈)
    blocking_items: list[str] = []
    if isinstance(blocking_issues, list):
        for b in blocking_issues:
            if isinstance(b, dict):
                title = b.get("title") or b.get("id") or b.get("reason") or str(b)
            else:
                title = str(b)
            blocking_items.append(f"  * {truncate(title, 80)}")

    if blocking_items:
        current_len = char_len("\n".join(digest_parts)) + 1
        rem = max_chars - current_len
        b_lines, _ = _format_section_with_budget(
            f"- Blocking issues ({len(blocking_items)}건):",
            blocking_items,
            rem,
        )
        if b_lines:
            digest_parts.extend(b_lines)
        else:
            digest_parts.append(f"- Blocking issues ({len(blocking_items)}건): (생략)")

    # 4) Scope excess (우선순위 3: 스코프 초과 요약)
    scope_str = (
        f"- Scope excess: write {len(write_excess)}개{write_scope_info}, "
        f"read {len(read_excess)}개{read_scope_info}"
    )
    current_len = char_len("\n".join(digest_parts)) + 1
    rem = max_chars - current_len
    if char_len(scope_str) + 1 <= rem:
        digest_parts.append(scope_str)

    # 5) Verification (우선순위 4: 최하위 - 상한이 빡빡하면 개수만 요약)
    verifications = report_data.get("verification")
    verification_items: list[str] = []
    if isinstance(verifications, list):
        for v in verifications:
            if isinstance(v, dict):
                cmd = truncate(str(v.get("command", "")), 80)
                res = truncate(str(v.get("result", "")), 80)
                verification_items.append(f"  * [{res}] {cmd}")
            else:
                verification_items.append(f"  * {truncate(str(v), 80)}")

    if verification_items:
        current_len = char_len("\n".join(digest_parts)) + 1
        rem = max_chars - current_len
        v_header = f"- Verification ({len(verification_items)}건):"
        if rem >= char_len(v_header) + 1:
            ver_lines, _ = _format_section_with_budget(
                v_header,
                verification_items,
                rem,
            )
            if len(ver_lines) <= 2 and rem < 120:
                digest_parts.append(
                    f"- Verification: {len(verification_items)}건 (상한 초과로 개별 항목 생략)"
                )
            elif ver_lines:
                digest_parts.extend(ver_lines)
            else:
                digest_parts.append(
                    f"- Verification: {len(verification_items)}건 (상한 초과로 생략)"
                )

    raw_digest = "\n".join(digest_parts)
    digest = truncate(raw_digest, max_chars)

    exit_code = 0 if len(violations) == 0 and effective_verdict == declared_verdict else 1

    return {
        "schema": "ORCA_WORKER_DONE_SUMMARY",
        "task_id": report_data.get("task_id"),
        "status": status,
        "declared_verdict": declared_verdict,
        "effective_verdict": effective_verdict,
        "branch": report_data.get("branch"),
        "commit": commit_raw,
        "short_commit": short_commit,
        "commit_count": commit_count,
        "changed_files": changed_files,
        "read_files_count": len(read_files),
        "read_scope_excess": read_excess,
        "write_scope_excess": write_excess,
        "verification_count": len(verification_items),
        "blocking_issues_count": len(blocking_items),
        "violations": violations,
        "violations_count": len(violations),
        "digest": digest,
        "exit_code": exit_code,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="워커 완료 보고(ORCA_WORKER_DONE_V2) 요약 및 계약 검증"
    )
    parser.add_argument("--report", required=True, help="워커 완료 보고 JSON 경로")
    parser.add_argument("--capsule", default=None, help="Orca Task Capsule YAML 경로")
    parser.add_argument("--repo", default=None, help="저장소 루트 경로 (기본: 현재 디렉터리)")
    parser.add_argument(
        "--max-chars",
        type=int,
        default=1200,
        help="다이제스트 최대 문자 수 (기본 1200)",
    )
    parser.add_argument(
        "--field-max-chars",
        type=int,
        default=600,
        help="단일 필드 최대 문자 수 (기본 600)",
    )
    parser.add_argument("--json", action="store_true", help="JSON 형식 출력 여부")

    args = parser.parse_args()

    try:
        result = summarize_worker_report(
            report_path=args.report,
            capsule_path=args.capsule,
            repo_path=args.repo,
            max_chars=args.max_chars,
            field_max_chars=args.field_max_chars,
        )
    except ContractError as err:
        sys.stderr.write(f"계약 오류: {err}\n")
        return 2

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        print(result["digest"])

    return int(result["exit_code"])


if __name__ == "__main__":
    sys.exit(main())
