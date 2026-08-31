#!/usr/bin/env python3
"""
scripts/orca_worker_done_guard.py

worker_done 완료 보고 및 전송 단일 진입점 가드.
Capsule 과 report_path 를 받아 파일 실존, ORCA_WORKER_DONE_V2 필수 필드, task_id 일치,
commit 실존, changed_files 와 실제 diff 일치, allowed_write_files 범위 준수를
엄격히 검사하고, 통과할 때만 orca orchestration send 를 실행합니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404
import sys
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        ContractError,
        load_capsule,
        load_report,
        parse_capsule_list,
        parse_capsule_scalar,
        string_list,
        verify_changed_files_match,
        verify_commit_exists,
        write_scope_excess,
    )
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_contract import (
        ContractError,
        load_capsule,
        load_report,
        parse_capsule_list,
        parse_capsule_scalar,
        string_list,
        verify_changed_files_match,
        verify_commit_exists,
        write_scope_excess,
    )

REQUIRED_WORKER_DONE_FIELDS = [
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
]


def validate_worker_done(
    capsule_path: Path,
    report_path: Path,
    repo: Path,
    base: str = "main",
    branch: str = "HEAD",
) -> tuple[bool, list[str], dict[str, Any]]:
    """worker_done 보고서와 작업 트리의 계약 정합성을 검증합니다."""
    violations: list[str] = []
    details: dict[str, Any] = {
        "capsule": str(capsule_path),
        "report": str(report_path),
        "task_id": None,
        "origin": None,
    }

    # 1. Capsule 파일 확인 및 파싱
    if not capsule_path.is_file():
        violations.append(f"Capsule 파일이 존재하지 않습니다: {capsule_path}")
        details["origin"] = "capsule_spec_error"
        return False, violations, details

    try:
        capsule_text = load_capsule(capsule_path)
    except Exception as exc:
        violations.append(f"Capsule 파일 로드 실패: {exc}")
        details["origin"] = "capsule_spec_error"
        return False, violations, details

    capsule_task_id = parse_capsule_scalar(capsule_text, "task_id")
    details["task_id"] = capsule_task_id
    allowed_write = parse_capsule_list(capsule_text, "allowed_write_files")

    # 2. Report 파일 확인 및 파싱
    if not report_path.is_file():
        violations.append(f"worker_done 보고 파일이 존재하지 않습니다: {report_path}")
        details["origin"] = "worker_scope_violation"
        return False, violations, details

    try:
        report_data = load_report(report_path)
    except ContractError as exc:
        violations.append(f"worker_done 보고서 로드/파싱 실패: {exc}")
        details["origin"] = "worker_scope_violation"
        return False, violations, details

    # 3. 필수 필드 검사
    missing_fields = [f for f in REQUIRED_WORKER_DONE_FIELDS if f not in report_data]
    if missing_fields:
        violations.append(f"ORCA_WORKER_DONE_V2 필수 필드 누락: {missing_fields}")
        details["origin"] = "worker_scope_violation"

    schema_val = report_data.get("schema")
    if schema_val != "ORCA_WORKER_DONE_V2":
        violations.append(f"schema 가 ORCA_WORKER_DONE_V2 가 아닙니다: {schema_val}")
        details["origin"] = "worker_scope_violation"

    # 4. Task ID 대조
    report_task_id = report_data.get("task_id")
    if capsule_task_id and report_task_id != capsule_task_id:
        violations.append(f"task_id 불일치: Capsule({capsule_task_id}) vs Report({report_task_id})")
        details["origin"] = "capsule_spec_error"
        return False, violations, details

    status = report_data.get("status")
    commit_sha = str(report_data.get("commit") or "").strip()
    commit_count = report_data.get("commit_count", 0)
    changed_files = string_list(report_data.get("changed_files"))

    # 5. status == succeeded 일 때의 엄격 검증
    if status == "succeeded":
        # 쓰기 작업인데 커밋이 0인 경우
        if allowed_write and commit_count == 0:
            violations.append(
                "코드 변경 작업에서 commit_count 가 0 입니다 (succeeded 대신 escalation 필요)"
            )
            details["origin"] = "worker_scope_violation"

        # 커밋 SHA 실존성 검증
        if commit_sha:
            ok_commit, msg_commit = verify_commit_exists(repo, commit_sha)
            if not ok_commit:
                violations.append(f"커밋 실존성 검증 실패: {msg_commit}")
                details["origin"] = "worker_scope_violation"

        # diff 와 changed_files 대조
        ok_diff, msg_diff = verify_changed_files_match(repo, base, branch, changed_files)
        if not ok_diff:
            violations.append(f"실제 git diff 와 changed_files 불일치: {msg_diff}")
            details["origin"] = "worker_scope_violation"

        # allowed_write_files 범위 준수 검사
        if not allowed_write:
            if changed_files:
                violations.append(
                    f"읽기 전용 Task 인데 changed_files 가 존재합니다: {changed_files}"
                )
                details["origin"] = "worker_scope_violation"
        else:
            excess = write_scope_excess(changed_files, allowed_write)
            if excess:
                violations.append(
                    f"허용된 쓰기 범위를 벗어난 파일이 보고서에 포함되었습니다: {excess}"
                )
                details["origin"] = "worker_scope_violation"

    return len(violations) == 0, violations, details


def execute_orca_send(
    task_id: str,
    from_handle: str | None = None,
    to_handle: str | None = None,
    dispatch_id: str | None = None,
    subject: str = "I-F contract enforcement complete",
    body: str = "",
    outcome: str = "succeeded",
    files_modified: str | None = None,
    report_path: str | Path | None = None,
) -> tuple[int, str, str]:
    """orca orchestration send 명령을 실행합니다."""
    cmd = ["orca", "orchestration", "send", "--type", "worker_done"]
    if from_handle:
        cmd.extend(["--from", from_handle])
    if to_handle:
        cmd.extend(["--to", to_handle])
    if task_id:
        cmd.extend(["--task-id", task_id])
    if dispatch_id:
        cmd.extend(["--dispatch-id", dispatch_id])
    if subject:
        cmd.extend(["--subject", subject])
    if body:
        cmd.extend(["--body", body])
    if outcome:
        cmd.extend(["--outcome", outcome])
    if files_modified:
        cmd.extend(["--files-modified", files_modified])
    if report_path:
        cmd.extend(["--report-path", str(report_path)])

    try:
        proc = subprocess.run(  # nosec B603
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except Exception as exc:
        return 2, "", str(exc)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orca worker_done 검증 및 단일 전송 진입점")
    parser.add_argument("--capsule", required=True, type=Path, help="Task Capsule YAML 경로")
    parser.add_argument(
        "--report",
        "--report-path",
        dest="report",
        required=True,
        type=Path,
        help="worker_done JSON 보고서 경로",
    )
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="Git 저장소/워크트리 경로")
    parser.add_argument("--base", default="main", help="비교 기준 git ref")
    parser.add_argument("--branch", default="HEAD", help="검증 대상 git ref")
    parser.add_argument(
        "--send", action="store_true", help="검증 통과 시 orca orchestration send 실행"
    )
    parser.add_argument("--from", dest="from_handle", help="전송자 터미널 핸들")
    parser.add_argument("--to", dest="to_handle", help="수신자 (예: run:<run_id>)")
    parser.add_argument("--dispatch-id", help="Dispatch ID")
    parser.add_argument("--subject", default="Task completed", help="메시지 제목")
    parser.add_argument("--body", default="Task completion report verified.", help="메시지 본문")
    parser.add_argument("--outcome", default="succeeded", help="결과 (succeeded 또는 escalation)")
    parser.add_argument("--files-modified", help="수정된 파일 목록 (쉼표 구분)")
    parser.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args(argv)

    capsule_path = args.capsule.resolve()
    report_path = args.report.resolve()
    repo_path = args.repo.resolve()

    ok, violations, details = validate_worker_done(
        capsule_path=capsule_path,
        report_path=report_path,
        repo=repo_path,
        base=args.base,
        branch=args.branch,
    )

    if not ok:
        origin = details.get("origin") or "worker_scope_violation"
        sys.stderr.write("오류 [orca_worker_done_guard]: 검증 실패\n")
        for v in violations:
            sys.stderr.write(f"  - {v}\n")
        if args.json:
            print(
                json.dumps(
                    {
                        "ok": False,
                        "origin": origin,
                        "violations": violations,
                        "details": details,
                        "exit_code": 1,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 1

    send_result = None
    if args.send:
        task_id = details.get("task_id") or ""
        code, stdout, stderr = execute_orca_send(
            task_id=task_id,
            from_handle=args.from_handle,
            to_handle=args.to_handle,
            dispatch_id=args.dispatch_id,
            subject=args.subject,
            body=args.body,
            outcome=args.outcome,
            files_modified=args.files_modified,
            report_path=report_path,
        )
        send_result = {
            "code": code,
            "stdout": stdout.strip(),
            "stderr": stderr.strip(),
        }
        if code != 0:
            sys.stderr.write(f"오류: orca orchestration send 실패 ({code}): {stderr or stdout}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "ok": False,
                            "origin": "send_failed",
                            "send_result": send_result,
                            "exit_code": code,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return code

    if args.json:
        print(
            json.dumps(
                {
                    "ok": True,
                    "task_id": details.get("task_id"),
                    "send_executed": args.send,
                    "send_result": send_result,
                    "exit_code": 0,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print("worker_done 검증 통과!")
        if args.send:
            print("orca orchestration send 전송 완료.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
