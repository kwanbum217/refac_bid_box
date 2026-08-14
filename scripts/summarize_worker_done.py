#!/usr/bin/env python3
"""
scripts/summarize_worker_done.py

워커의 완료 보고(ORCA_WORKER_DONE_V2)를 검증하고 고정 상한 이하의 다이제스트로 요약합니다.

주요 기능:
  1. 필수 필드 누락 검증 (REQUIRED_FIELDS)
  2. status == "succeeded" 인데 commit_count == 0 및 changed_files 비어있지 않음 검증 (규약 3.3)
  3. Task Capsule 의 allowed_read_files 및 allowed_write_files 대조 (scope_excess)
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
    )
except ImportError:
    # 저장소 루트를 sys.path 에 추가하여 직접 실행(python3 scripts/...) 시 모듈 해석 지원
    _REPO_ROOT = Path(__file__).resolve().parent.parent
    if str(_REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(_REPO_ROOT))
    from scripts.orca_contract import (  # type: ignore[no-redef]
        ContractError,
        char_len,
        load_capsule,
        load_report,
        parse_capsule_list,
        scope_excess,
        string_list,
        truncate,
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


def summarize_worker_report(
    report_path: str | Path,
    capsule_path: str | Path | None = None,
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

    # 2. 위반 검사 A: status == succeeded 인데 commit_count == 0 이고 changed_files 존재 (규약 3.3)
    if status == "succeeded" and commit_count == 0 and len(changed_files) > 0:
        violations.append(
            "규약 3.3 위반: status 가 succeeded 인데 commit_count 가 0 이고 changed_files 가 비어 있지 않음"
        )

    # 3. 위반 검사 B & C: Capsule 범위 검사
    read_excess: list[str] = []
    write_excess: list[str] = []
    if capsule_path is not None:
        capsule_text = load_capsule(capsule_path)
        allowed_read = parse_capsule_list(capsule_text, "allowed_read_files")
        allowed_write = parse_capsule_list(capsule_text, "allowed_write_files")

        # B: read_files 초과는 지시 불일치 사후 확인용이므로 read_scope_excess 로 기록하되 위반으로 세지 않음 (규약 2.9.2)
        read_excess = scope_excess(read_files, allowed_read)

        # C: changed_files 초과는 범위 위반이므로 위반으로 집계
        write_excess = scope_excess(changed_files, allowed_write)
        if write_excess:
            violations.append(f"allowed_write_files 범위 초과: {', '.join(write_excess)}")

    # 4. 위반 검사 D: verdict 격하 검사
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
    else:
        effective_verdict = declared_verdict

    # 5. 위반 검사 E: 계약 비대 (contract bloat) 검사
    bloated = _find_bloated_fields(report_data, field_max_chars)
    for field_path, length in bloated:
        violations.append(
            f"계약 비대 (contract bloat): 필드 '{field_path}' 길이 {length}자가 field_max_chars({field_max_chars}) 초과"
        )

    # 다이제스트 포맷 구성
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

    verifications = report_data.get("verification")
    verification_lines: list[str] = []
    if isinstance(verifications, list):
        for v in verifications:
            if isinstance(v, dict):
                cmd = truncate(str(v.get("command", "")), 80)
                res = truncate(str(v.get("result", "")), 80)
                verification_lines.append(f"  * [{res}] {cmd}")
            else:
                verification_lines.append(f"  * {truncate(str(v), 80)}")

    blocking_lines: list[str] = []
    if isinstance(blocking_issues, list):
        for b in blocking_issues:
            if isinstance(b, dict):
                title = b.get("title") or b.get("id") or b.get("reason") or str(b)
            else:
                title = str(b)
            blocking_lines.append(f"  * {truncate(title, 80)}")

    violation_lines: list[str] = []
    for viol in violations:
        violation_lines.append(f"  * {truncate(viol, 120)}")

    digest_parts = [
        "[Worker Done Summary]",
        f"- Status: {status}",
        f"- Verdict: {declared_verdict} (실효: {effective_verdict})",
        f"- Branch: {report_data.get('branch')} (commit: {short_commit}, count: {commit_count})",
        f"- Changed files ({len(changed_files)}개): {files_preview}",
        f"- Read files: {len(read_files)}개",
        f"- Scope excess: write {len(write_excess)}개{write_scope_info}, read {len(read_excess)}개{read_scope_info}",
    ]

    if verification_lines:
        digest_parts.append(f"- Verification ({len(verification_lines)}건):")
        digest_parts.extend(verification_lines)

    if blocking_lines:
        digest_parts.append(f"- Blocking issues ({len(blocking_lines)}건):")
        digest_parts.extend(blocking_lines)

    if violation_lines:
        digest_parts.append(f"- Violations ({len(violation_lines)}건):")
        digest_parts.extend(violation_lines)
    else:
        digest_parts.append("- Violations: 0건 (계약 준수)")

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
        "verification_count": len(verification_lines),
        "blocking_issues_count": len(blocking_lines),
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
