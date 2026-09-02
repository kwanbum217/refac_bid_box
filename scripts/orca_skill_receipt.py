#!/usr/bin/env python3
"""
scripts/orca_skill_receipt.py

Orca 정본 스킬(orca skills get orchestration) 영수증 발급 및 실시간 검증 모듈.

2층 게이트 아키텍처:
  - 1층: 세션 시작 훅(.claude/settings.json SessionStart)으로 정본을 자동 주입 및 발급.
  - 2층: Task 생성(create) 및 워커 기동(dispatch) 시 정본 영수증의 유효성을 fail-closed 로 검증.

영수증 계약:
  - 정본 출력의 sha256 해시
  - Orca 런타임 appVersion
  - 발급 시각(issued_at)
  - 코디네이터 터미널 핸들(coordinator_handle)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess  # nosec B404 - 고정된 orca 명령만 실행합니다
import sys
import time
from contextlib import suppress
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

UTC = getattr(timezone, "utc", UTC)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RECEIPT_PATH = PROJECT_ROOT / ".orca" / "skill_receipt.json"
CANONICAL_COMMAND = "orca skills get orchestration"
RECEIPT_SCHEMA = "ORCA_SKILL_RECEIPT_V1"
RESOLUTION_COMMAND = "python3 scripts/orca_skill_receipt.py issue"


def _run_cmd(cmd: list[str], timeout: int = 15) -> tuple[int, str, str]:
    """subprocess.run 래퍼로 (returncode, stdout, stderr) 를 반환합니다."""
    try:
        proc = subprocess.run(  # nosec B603 - 고정 인자 목록으로 호출합니다
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        if isinstance(stdout, bytes):
            stdout = stdout.decode("utf-8", errors="replace")
        if isinstance(stderr, bytes):
            stderr = stderr.decode("utf-8", errors="replace")
        return -1, stdout, stderr
    except FileNotFoundError as exc:
        return -2, "", f"실행 파일을 찾을 수 없음 ({cmd[0]}): {exc}"
    except Exception as exc:
        return -2, "", f"명령 실행 실패 ({' '.join(cmd)}): {exc}"


def get_canonical_skill_content(
    timeout: int = 15,
    orca_cmd: list[str] | None = None,
) -> tuple[str, str]:
    """Orca 정본 스킬 본문과 sha256 다이제스트를 취득합니다."""
    cmd = orca_cmd if orca_cmd is not None else ["orca", "skills", "get", "orchestration"]
    code, stdout, stderr = _run_cmd(cmd, timeout=timeout)
    if code != 0 or not stdout.strip():
        err = stderr.strip() or f"명령 종료 코드 {code}"
        raise RuntimeError(f"정본 스킬 조회 실패 ({' '.join(cmd)}): {err}")
    content = stdout
    digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
    return content, digest


def get_orca_app_version(
    timeout: int = 15,
    orca_cmd: list[str] | None = None,
) -> str:
    """Orca 런타임 상태에서 appVersion 을 취득합니다."""
    cmd = orca_cmd if orca_cmd is not None else ["orca", "status", "--json"]
    code, stdout, stderr = _run_cmd(cmd, timeout=timeout)
    if code != 0 or not stdout.strip():
        err = stderr.strip() or f"명령 종료 코드 {code}"
        raise RuntimeError(f"Orca 상태 조회 실패 ({' '.join(cmd)}): {err}")
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Orca status JSON 파싱 실패: {exc}") from exc

    result = data.get("result", data)
    runtime = result.get("runtime", {}) if isinstance(result, dict) else {}
    app_version = runtime.get("appVersion") if isinstance(runtime, dict) else None
    if not app_version or not isinstance(app_version, str):
        raise RuntimeError(f"Orca status 에서 appVersion 을 찾을 수 없음: {stdout[:200]}")
    return app_version.strip()


def get_coordinator_handle(
    timeout: int = 15,
    orca_cmd: list[str] | None = None,
) -> str | None:
    """환경변수 또는 run-current 에서 코디네이터 터미널 핸들을 취득합니다."""
    env_handle = (
        os.environ.get("ORCA_TERMINAL_HANDLE")
        or os.environ.get("COORDINATOR_HANDLE")
        or os.environ.get("ORCA_HANDLE")
    )
    if env_handle and env_handle.strip():
        return env_handle.strip()

    cmd = orca_cmd if orca_cmd is not None else ["orca", "orchestration", "run-current", "--json"]
    code, stdout, _ = _run_cmd(cmd, timeout=timeout)
    if code == 0 and stdout.strip():
        with suppress(Exception):
            data = json.loads(stdout)
            result = data.get("result", data)
            run = result.get("run", result) if isinstance(result, dict) else {}
            handle = run.get("coordinator_handle") if isinstance(run, dict) else None
            if isinstance(handle, str) and handle.strip():
                return handle.strip()
    return None


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp_path.replace(path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)


def issue_skill_receipt(
    receipt_path: Path | None = None,
    timeout: int = 15,
    orca_skill_cmd: list[str] | None = None,
    orca_status_cmd: list[str] | None = None,
    orca_run_cmd: list[str] | None = None,
) -> dict[str, Any]:
    """정본 스킬을 조회하여 영수증 파일을 발급합니다."""
    target_path = Path(receipt_path) if receipt_path is not None else DEFAULT_RECEIPT_PATH
    try:
        content, sha256_val = get_canonical_skill_content(timeout=timeout, orca_cmd=orca_skill_cmd)
        app_version = get_orca_app_version(timeout=timeout, orca_cmd=orca_status_cmd)
        coord_handle = get_coordinator_handle(timeout=timeout, orca_cmd=orca_run_cmd)

        now_epoch = time.time()
        now_iso = datetime.now(UTC).isoformat()

        receipt_data = {
            "schema": RECEIPT_SCHEMA,
            "skill_name": "orchestration",
            "canonical_command": CANONICAL_COMMAND,
            "sha256": sha256_val,
            "app_version": app_version,
            "coordinator_handle": coord_handle,
            "issued_at": now_epoch,
            "issued_at_iso": now_iso,
            "content_bytes": len(content.encode("utf-8")),
            "content_chars": len(content),
        }

        _write_json_atomic(target_path, receipt_data)
        return {
            "ok": True,
            "receipt": receipt_data,
            "path": str(target_path),
            "reason": "영수증 발급 완료",
        }
    except Exception as exc:
        return {
            "ok": False,
            "error": "receipt_issue_failed",
            "reason": f"정본 스킬 영수증 발급 실패: {exc}",
            "fix_command": RESOLUTION_COMMAND,
        }


def verify_skill_receipt(
    receipt_path: Path | None = None,
    timeout: int = 15,
    orca_skill_cmd: list[str] | None = None,
    orca_status_cmd: list[str] | None = None,
    orca_run_cmd: list[str] | None = None,
    current_handle: str | None = None,
) -> dict[str, Any]:
    """정본 스킬 영수증의 유효성을 실시간 조회와 대조하여 fail-closed 로 검증합니다."""
    target_path = Path(receipt_path) if receipt_path is not None else DEFAULT_RECEIPT_PATH
    if not target_path.exists():
        return {
            "ok": False,
            "error": "receipt_missing",
            "reason": f"정본 스킬 영수증 파일이 없습니다 ({target_path})",
            "fix_command": RESOLUTION_COMMAND,
        }

    try:
        text = target_path.read_text(encoding="utf-8")
        receipt = json.loads(text)
    except Exception as exc:
        return {
            "ok": False,
            "error": "receipt_corrupt",
            "reason": f"정본 스킬 영수증 파싱 실패 또는 손상: {exc}",
            "fix_command": RESOLUTION_COMMAND,
        }

    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        return {
            "ok": False,
            "error": "receipt_invalid_schema",
            "reason": f"정본 스킬 영수증 스키마 위반 ({receipt.get('schema')})",
            "fix_command": RESOLUTION_COMMAND,
        }

    # 1. appVersion 실시간 대조
    try:
        curr_version = get_orca_app_version(timeout=timeout, orca_cmd=orca_status_cmd)
    except Exception as exc:
        return {
            "ok": False,
            "error": "app_version_probe_failed",
            "reason": f"Orca 런타임 버전 실시간 조회 실패: {exc}",
            "fix_command": RESOLUTION_COMMAND,
        }

    recorded_version = str(receipt.get("app_version") or "")
    if curr_version != recorded_version:
        return {
            "ok": False,
            "error": "app_version_mismatch",
            "reason": f"Orca 앱 버전 변경으로 영수증 만료 (영수증: {recorded_version}, 현재: {curr_version})",
            "fix_command": RESOLUTION_COMMAND,
        }

    # 2. sha256 실시간 대조
    try:
        _, curr_sha256 = get_canonical_skill_content(timeout=timeout, orca_cmd=orca_skill_cmd)
    except Exception as exc:
        return {
            "ok": False,
            "error": "skill_content_probe_failed",
            "reason": f"정본 스킬 실시간 조회 실패: {exc}",
            "fix_command": RESOLUTION_COMMAND,
        }

    recorded_sha256 = str(receipt.get("sha256") or "")
    if curr_sha256 != recorded_sha256:
        return {
            "ok": False,
            "error": "sha256_mismatch",
            "reason": (
                f"정본 스킬 내용 변경으로 영수증 만료 "
                f"(영수증: {recorded_sha256[:8]}, 현재: {curr_sha256[:8]})"
            ),
            "fix_command": RESOLUTION_COMMAND,
        }

    # 3. 코디네이터 터미널 핸들 대조 (조회 가능한 경우에만 대조, 불가하면 건너뜀)
    recorded_handle = receipt.get("coordinator_handle")
    live_handle = (
        current_handle
        if current_handle is not None
        else get_coordinator_handle(timeout=timeout, orca_cmd=orca_run_cmd)
    )

    handle_check_status = "skipped_unprobed"
    if recorded_handle and live_handle:
        if str(recorded_handle).strip() != str(live_handle).strip():
            return {
                "ok": False,
                "error": "coordinator_handle_mismatch",
                "reason": (
                    f"다른 세션에서 발급된 영수증 재사용 거부 "
                    f"(영수증 세션: {recorded_handle}, 현재 세션: {live_handle})"
                ),
                "fix_command": RESOLUTION_COMMAND,
            }
        handle_check_status = "verified"

    return {
        "ok": True,
        "reason": "정본 스킬 영수증 유효 (appVersion, sha256 일치)",
        "receipt": receipt,
        "coordinator_handle_check": handle_check_status,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orca 정본 스킬 영수증 관리")
    sub = parser.add_subparsers(dest="command", required=True)

    iss = sub.add_parser("issue", help="Orca 정본 스킬 영수증 발급")
    iss.add_argument(
        "--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH, help="영수증 저장 경로"
    )
    iss.add_argument("--timeout", type=int, default=15, help="타임아웃(초)")
    iss.add_argument("--json", action="store_true", help="JSON 출력")

    ver = sub.add_parser("verify", help="Orca 정본 스킬 영수증 실시간 검증")
    ver.add_argument("--receipt-path", type=Path, default=DEFAULT_RECEIPT_PATH, help="영수증 경로")
    ver.add_argument("--timeout", type=int, default=15, help="타임아웃(초)")
    ver.add_argument("--json", action="store_true", help="JSON 출력")

    args = parser.parse_args(argv)

    if args.command == "issue":
        res = issue_skill_receipt(receipt_path=args.receipt_path, timeout=args.timeout)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            if res["ok"]:
                r = res["receipt"]
                print(
                    f"[정본 영수증 발급 완료] sha256: {r['sha256'][:8]}..., "
                    f"appVersion: {r['app_version']}, 세션: {r['coordinator_handle'] or '미지정'}"
                )
            else:
                sys.stderr.write(f"오류: {res['reason']}\n")
                sys.stderr.write(f"해소 명령: {res['fix_command']}\n")
        return 0 if res["ok"] else 1

    if args.command == "verify":
        res = verify_skill_receipt(receipt_path=args.receipt_path, timeout=args.timeout)
        if args.json:
            print(json.dumps(res, ensure_ascii=False, indent=2))
        else:
            if res["ok"]:
                print(f"[정본 영수증 검증 통과] {res['reason']}")
            else:
                sys.stderr.write(f"오류: {res['reason']}\n")
                sys.stderr.write(f"해소 명령: {res['fix_command']}\n")
        return 0 if res["ok"] else 1

    return 2


if __name__ == "__main__":
    sys.exit(main())
