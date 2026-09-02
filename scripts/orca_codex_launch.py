#!/usr/bin/env python3
"""Codex 워커 기동과 Capsule 배치를 하나로 묶습니다.

`orca orchestration worker-start` 는 워크트리 생성과 워커 기동을 한 번에
수행합니다. 그래서 코디네이터가 기동 뒤에 Capsule 을 복사하면 워커가 그
사이에 정본을 찾으러 갔다가 없는 것을 보게 됩니다. 2026-09-02 세션에서
이 경합으로 워커 네 대가 계약 없이 작업했거나 멈췄습니다.

  E1  arq cron 대신 OS cron 생성기를 만들고 CURRENT_STATE 를 수정
  E2  health 라우터 대신 predictions 라우터에 엔드포인트 추가
  E3  Capsule 없음으로 조사 중단
  G1  Capsule 없음으로 Task 가 failed 로 종결

이 스크립트는 worker-start 를 배경으로 띄운 뒤 워크트리 디렉터리가 나타나는
즉시 Capsule 과 .env 를 넣습니다. 워커가 정본을 찾는 시점보다 먼저 도착하는
것이 목적이며, 폴링 간격을 짧게 두어 경합 창을 좁힙니다.
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess  # nosec B404 - 고정 인자 목록으로만 외부 도구를 호출합니다
import sys
import time
from pathlib import Path

POLL_SECONDS = 0.3
DEFAULT_TIMEOUT = 300


def _repo_root() -> Path:
    return Path(__file__).resolve().parent.parent


def place_capsule(worktree: Path, repo: Path) -> list[str]:
    """Capsule 전체와 .env 를 워크트리에 넣고 배치한 항목을 돌려줍니다."""
    placed: list[str] = []
    src_capsules = repo / ".orca" / "capsules"
    if src_capsules.is_dir():
        dest = worktree / ".orca" / "capsules"
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(src_capsules, dest, dirs_exist_ok=True)
        placed.append(".orca/capsules")

    env_src = repo / ".env"
    env_dest = worktree / ".env"
    # .env 는 Git 미추적이라 새 워크트리에 따라가지 않습니다. 값은 출력하지
    # 않고 존재 여부만 기록합니다.
    if env_src.is_file() and not env_dest.exists():
        shutil.copy2(env_src, env_dest)
        placed.append(".env")
    return placed


def wait_for_worktree(path: Path, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if path.is_dir():
            return True
        time.sleep(POLL_SECONDS)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Codex 워커 기동과 Capsule 배치 통합")
    parser.add_argument("--task", required=True)
    parser.add_argument("--name", required=True, help="새 워크트리 이름")
    parser.add_argument("--model", default="gpt-5.6-luna")
    parser.add_argument("--effort", default="", help="지정 시 worker-start 에 전달")
    parser.add_argument("--repo", default="", help="주 저장소 경로 (기본: 자동 감지)")
    parser.add_argument("--workspaces", default="", help="워크트리 상위 경로")
    parser.add_argument("--timeout-sec", type=float, default=DEFAULT_TIMEOUT)
    args = parser.parse_args(argv)

    repo = Path(args.repo).resolve() if args.repo else _repo_root()
    workspaces = (
        Path(args.workspaces)
        if args.workspaces
        else Path.home() / "orca" / "workspaces" / repo.name
    )
    worktree = workspaces / args.name

    cmd = [
        "orca",
        "orchestration",
        "worker-start",
        "--task",
        args.task,
        "--agent",
        "codex",
        "--model",
        args.model,
        "--worktree",
        "new-child",
        "--name",
        args.name,
        "--repo",
        f"path:{repo}",
        "--setup",
        "skip",
        "--json",
    ]
    if args.effort:
        cmd += ["--effort", args.effort]

    print(f"기동: {args.model} -> {worktree}", flush=True)
    proc = subprocess.Popen(  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True
    )

    if wait_for_worktree(worktree, args.timeout_sec):
        placed = place_capsule(worktree, repo)
        print(f"Capsule 배치: {', '.join(placed) if placed else '없음'}", flush=True)
    else:
        print(f"경고: 워크트리가 {args.timeout_sec:.0f}초 안에 생기지 않았습니다", flush=True)

    stdout, _ = proc.communicate(timeout=args.timeout_sec)
    print(stdout, flush=True)

    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return proc.returncode or 1
    return 0 if payload.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
