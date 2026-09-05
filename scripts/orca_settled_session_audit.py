#!/usr/bin/env python3
"""완료된 워커 세션이 터미널을 점유한 채 남아 있는지 검사합니다.

worker_done 이후에도 창을 남겨 두면 활성 섹션과 끝난 섹션이 구분되지 않습니다.
이 모듈은 그 상태를 기계로 찾아 Dispatch 를 거부합니다.
"""

from __future__ import annotations

import argparse
import json
import subprocess  # nosec B404 - 고정된 orca 인자만 호출합니다
import sys
from pathlib import Path
from typing import Any


def parse_tasks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """task-list JSON 에서 Task 목록을 꺼냅니다."""
    result = payload.get("result", payload)
    if isinstance(result, dict):
        tasks = result.get("tasks", [])
    elif isinstance(result, list):
        tasks = result
    else:
        tasks = []
    return [t for t in tasks if isinstance(t, dict)]


def parse_terminals(payload: dict[str, Any]) -> dict[str, str]:
    """terminal list JSON 에서 handle -> title 맵을 만듭니다."""
    result = payload.get("result", payload)
    terminals = result.get("terminals", []) if isinstance(result, dict) else []
    mapping: dict[str, str] = {}
    for item in terminals:
        if not isinstance(item, dict):
            continue
        handle = str(item.get("handle") or "").strip()
        if not handle:
            continue
        mapping[handle] = str(item.get("title") or "")
    return mapping


def coordinator_handle_from_run(payload: dict[str, Any]) -> str | None:
    """run-current JSON 에서 코디네이터 터미널 핸들을 읽습니다."""
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        return None
    run = result.get("run") if isinstance(result.get("run"), dict) else result
    handle = run.get("coordinator_handle") if isinstance(run, dict) else None
    if isinstance(handle, str) and handle.strip():
        return handle.strip()
    return None


def assignee_handle_from_dispatch(payload: dict[str, Any]) -> str | None:
    """dispatch-show JSON 에서 워커 핸들을 읽습니다."""
    result = payload.get("result", payload)
    if not isinstance(result, dict):
        return None
    dispatch = result.get("dispatch") if isinstance(result.get("dispatch"), dict) else result
    handle = dispatch.get("assignee_handle") if isinstance(dispatch, dict) else None
    if isinstance(handle, str) and handle.strip():
        return handle.strip()
    return None


def load_unsupervised_receipts(
    receipts_dir: Path | str | None = None,
    repo_root: Path | str | None = None,
) -> dict[str, dict[str, Any]]:
    """비감독 Dispatch 영수증(receipt)을 수집하여 task_id -> receipt 매핑을 반환합니다."""
    root = Path(repo_root).resolve() if repo_root else Path.cwd()
    search_dirs: list[Path] = []
    if receipts_dir:
        search_dirs.append(Path(receipts_dir).resolve())
    else:
        search_dirs.append(root / ".orca" / "dispatch_receipts")
        search_dirs.append(root / ".orca" / "capsules")

    receipts: dict[str, dict[str, Any]] = {}
    for sdir in search_dirs:
        if not sdir.exists():
            continue
        pattern = "*/dispatch_receipt.json" if sdir.name == "capsules" else "*.json"
        for p in sdir.glob(pattern):
            if not p.is_file():
                continue
            try:
                data = json.loads(p.read_text(encoding="utf-8"))
                if isinstance(data, dict) and data.get("task_id"):
                    t_id = str(data["task_id"]).strip()
                    if t_id:
                        receipts[t_id] = data
            except Exception:  # nosec B112 # noqa: S112
                continue
    return receipts


def lingering_settled_sessions(
    tasks: list[dict[str, Any]],
    live_terminals: dict[str, str],
    assignee_by_task: dict[str, str | None],
    coordinator_handle: str | None = None,
    receipts: dict[str, dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """completed Task 인데 워커 터미널이 아직 살아 있는 항목을 돌려줍니다."""
    lingering: list[dict[str, Any]] = []
    for task in tasks:
        status = str(task.get("status") or "").strip().lower()
        if status != "completed":
            continue
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        handle = assignee_by_task.get(task_id)
        receipt_item = None
        if not handle and receipts and task_id in receipts:
            receipt_item = receipts[task_id]
            handle = (
                str(receipt_item.get("terminal") or receipt_item.get("handle") or "").strip()
                or None
            )
        if not handle:
            continue
        if coordinator_handle and handle == coordinator_handle:
            continue
        if handle not in live_terminals:
            continue
        is_supervised = True
        if receipt_item:
            is_supervised = bool(receipt_item.get("supervised", False))
        elif receipts and task_id in receipts:
            is_supervised = bool(receipts[task_id].get("supervised", False))
        lingering.append(
            {
                "task_id": task_id,
                "handle": handle,
                "title": live_terminals.get(handle, ""),
                "task_title": str(task.get("task_title") or task.get("display_name") or ""),
                "supervised": is_supervised,
            }
        )
    return lingering


def _orca_json(args: list[str], timeout: int = 30) -> dict[str, Any]:
    completed = subprocess.run(  # nosec B603 B607 - 고정 실행 파일과 고정 하위명령만 사용
        ["orca", *args, "--json"],
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
    )
    if completed.returncode != 0:
        err = (completed.stderr or completed.stdout or "").strip()
        raise RuntimeError(err or f"orca {' '.join(args)} 종료 코드 {completed.returncode}")
    try:
        payload = json.loads(completed.stdout or "{}")
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"orca {' '.join(args)} JSON 파싱 실패: {exc}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError(f"orca {' '.join(args)} JSON 최상위가 객체가 아님")
    return payload


def audit_lingering_sessions(
    run_id: str | None = None,
    timeout: int = 30,
    repo_root: Path | str | None = None,
    receipts_dir: Path | str | None = None,
) -> dict[str, Any]:
    """실측으로 완료 세션 잔류를 검사합니다."""
    task_args = ["orchestration", "task-list"]
    if run_id:
        task_args.extend(["--run", run_id])
    tasks = parse_tasks(_orca_json(task_args, timeout=timeout))
    live = parse_terminals(_orca_json(["terminal", "list"], timeout=timeout))
    coordinator: str | None = None
    try:
        coordinator = coordinator_handle_from_run(
            _orca_json(["orchestration", "run-current"], timeout=timeout)
        )
    except RuntimeError:
        coordinator = None

    assignee_by_task: dict[str, str | None] = {}
    for task in tasks:
        if str(task.get("status") or "").strip().lower() != "completed":
            continue
        task_id = str(task.get("id") or "").strip()
        if not task_id:
            continue
        try:
            payload = _orca_json(
                ["orchestration", "dispatch-show", "--task", task_id],
                timeout=timeout,
            )
            assignee_by_task[task_id] = assignee_handle_from_dispatch(payload)
        except RuntimeError:
            assignee_by_task[task_id] = None

    receipts = load_unsupervised_receipts(receipts_dir=receipts_dir, repo_root=repo_root)

    lingering = lingering_settled_sessions(
        tasks,
        live,
        assignee_by_task,
        coordinator_handle=coordinator,
        receipts=receipts,
    )
    return {
        "allowed": not lingering,
        "lingering": lingering,
        "count": len(lingering),
        "reason": (
            "완료 세션 잔류 없음"
            if not lingering
            else "completed Task 의 워커 터미널이 아직 열려 있습니다. "
            "다음 Dispatch 전에 worker-release 와 terminal close 로 회수하십시오."
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="완료된 워커 세션 잔류 검사")
    parser.add_argument("--run-id", help="Run ID (미지정 시 현재 바인딩)")
    parser.add_argument("--repo", help="저장소 루트 경로")
    parser.add_argument("--receipts-dir", help="비감독 receipt 디렉터리 경로")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = audit_lingering_sessions(
            run_id=args.run_id,
            repo_root=args.repo,
            receipts_dir=args.receipts_dir,
        )
    except RuntimeError as exc:
        if args.json:
            print(
                json.dumps(
                    {"allowed": False, "error": str(exc), "exit_code": 2}, ensure_ascii=False
                )
            )
        else:
            sys.stderr.write(f"오류: {exc}\n")
        return 2
    if args.json:
        print(
            json.dumps(
                {**result, "exit_code": 0 if result["allowed"] else 1}, ensure_ascii=False, indent=2
            )
        )
    else:
        print(result["reason"])
        for item in result["lingering"]:
            print(f"  {item['task_id']}  {item['handle']}  {item['title']}  {item['task_title']}")
    return 0 if result["allowed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
