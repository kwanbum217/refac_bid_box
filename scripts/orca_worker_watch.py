"""
scripts/orca_worker_watch.py

활성 Orca 워커의 진척과 차단 상태를 한 번에 점검합니다.

코디네이터가 Dispatch 후 감시를 잊지 않도록, 워커별 커밋 수·미커밋 변경 수와
터미널 화면의 차단 신호(신뢰 대화창, 설문, 인증 정체, 권한 요청)를 한 명령으로
모아 보여줍니다. 감시를 지침으로만 두면 지켜지지 않습니다. 2026-08-26 세션에서
워커가 CLI 설문 프롬프트에 막혀 있었고, 부팅이 'not signed in' 에서 멈춘 사례가
세 번 있었습니다.

사용법:
    uv run python scripts/orca_worker_watch.py
    uv run python scripts/orca_worker_watch.py --json

종료 코드:
    0  모든 워커가 정상 진행 중이거나 감시 대상 없음
    1  차단 신호가 감지된 워커가 있음 (코디네이터 개입 필요)
    2  도구 오류
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404  고정된 git·orca 명령만 실행하며 사용자 입력을 받지 않습니다
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 터미널 화면에서 워커가 사람 개입을 기다리고 있음을 뜻하는 신호.
# 값은 (사유, 해제 방법) 이며 코디네이터가 바로 조치할 수 있게 적습니다.
BLOCK_SIGNALS: list[tuple[str, str, str]] = [
    (
        "Do you trust",
        "Antigravity 폴더 신뢰 대화창",
        "terminal send --enter --text '' (기본 선택이 신뢰)",
    ),
    ("Trust this workspace", "Cursor 워크스페이스 신뢰 대화창", "terminal send --text 'a'"),
    (
        "not signed in",
        "Antigravity 부팅이 인증 단계에서 정체",
        "터미널을 닫고 재기동. --model 플래그 없이 agy 로 띄울 것",
    ),
    ("How's the CLI experience", "CLI 만족도 설문 프롬프트", "terminal send --text '0' (Skip)"),
    (
        "Allow this",
        "도구 실행 권한 요청",
        "화면을 읽고 승인 여부를 판단. shift+tab 으로 auto-approve 전환 가능",
    ),
    ("Do you want to proceed", "진행 확인 프롬프트", "화면을 읽고 승인 여부를 판단"),
]

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")


@dataclass
class WorkerState:
    name: str
    path: str
    branch: str
    commits: int
    dirty: int
    terminal: str | None = None
    blocked_reason: str | None = None
    blocked_fix: str | None = None
    notes: list[str] = field(default_factory=list)

    @property
    def blocked(self) -> bool:
        return self.blocked_reason is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "path": self.path,
            "branch": self.branch,
            "commits": self.commits,
            "dirty": self.dirty,
            "terminal": self.terminal,
            "blocked": self.blocked,
            "blocked_reason": self.blocked_reason,
            "blocked_fix": self.blocked_fix,
            "notes": list(self.notes),
        }


def _run(args: list[str], timeout: int = 30) -> str:
    try:
        # 호출부가 고정 인자 배열만 넘기고 shell 을 쓰지 않습니다.
        proc = subprocess.run(  # nosec B603
            args, capture_output=True, text=True, timeout=timeout
        )
        return proc.stdout
    except Exception:
        return ""


def list_worktrees(repo: Path) -> list[tuple[str, str, str]]:
    """(이름, 절대경로, 브랜치) 목록. 주 저장소는 제외합니다."""
    out = _run(["git", "-C", str(repo), "worktree", "list", "--porcelain"])
    entries: list[tuple[str, str, str]] = []
    path = branch = ""
    for line in out.splitlines():
        if line.startswith("worktree "):
            path = line.split(" ", 1)[1].strip()
        elif line.startswith("branch "):
            branch = line.split(" ", 1)[1].strip().replace("refs/heads/", "")
        elif not line.strip() and path:
            if Path(path).resolve() != repo.resolve():
                entries.append((Path(path).name, path, branch))
            path = branch = ""
    if path and Path(path).resolve() != repo.resolve():
        entries.append((Path(path).name, path, branch))
    return entries


def worktree_progress(path: str, base: str = "main") -> tuple[int, int]:
    commits = _run(["git", "-C", path, "log", "--oneline", f"{base}..HEAD"])
    dirty = _run(["git", "-C", path, "status", "--short"])
    return (
        len([x for x in commits.splitlines() if x.strip()]),
        len([x for x in dirty.splitlines() if x.strip()]),
    )


# 차단 신호는 화면 끝부분에서만 찾습니다. 이미 승인하고 지나간 대화창이
# 스크롤백에 남아 있어, 전체를 훑으면 정상 작업 중인 워커를 차단으로 오판합니다.
TAIL_LINES = 15


def terminal_map() -> dict[str, dict[str, Any]]:
    """워크트리 경로 -> 터미널 정보. orca 를 쓸 수 없으면 빈 딕셔너리."""
    raw = _run(["orca", "terminal", "list", "--json"], timeout=60)
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    result = payload.get("result") or {}
    terminals = result.get("terminals") or result.get("sessions") or []
    mapping: dict[str, dict[str, Any]] = {}
    for item in terminals:
        path = item.get("worktreePath")
        if path:
            mapping[str(path)] = item
    return mapping


def terminal_tail(handle: str, lines: int = TAIL_LINES) -> str:
    detail = ANSI_RE.sub("", _run(["orca", "terminal", "read", "--terminal", handle], timeout=60))
    return "\n".join(detail.splitlines()[-lines:])


def detect_block(screen_tail: str) -> tuple[str, str] | None:
    for needle, reason, fix in BLOCK_SIGNALS:
        if needle in screen_tail:
            return reason, fix
    return None


def collect(repo: Path, base: str) -> list[WorkerState]:
    terminals = terminal_map()
    states: list[WorkerState] = []
    for name, path, branch in list_worktrees(repo):
        commits, dirty = worktree_progress(path, base)
        state = WorkerState(name=name, path=path, branch=branch, commits=commits, dirty=dirty)
        info = terminals.get(path)
        if info:
            state.terminal = info.get("handle")
            if state.terminal:
                found = detect_block(terminal_tail(state.terminal))
                if found:
                    state.blocked_reason, state.blocked_fix = found
        else:
            state.notes.append(
                "연결된 터미널이 없습니다. 워커가 종료됐거나 아직 기동되지 않았습니다"
            )
        if commits == 0 and dirty == 0 and not state.blocked:
            state.notes.append(
                "커밋 0 · 미커밋 0. 조사 단계이거나 정체일 수 있으니 터미널을 확인하십시오"
            )
        states.append(state)
    return states


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orca 워커 진척·차단 감시")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="주 저장소 경로")
    parser.add_argument("--base", default="main", help="진척 비교 기준 브랜치")
    parser.add_argument("--json", action="store_true", help="기계 판독 출력")
    args = parser.parse_args(argv)

    try:
        states = collect(args.repo, args.base)
    except Exception as exc:  # 도구 오류와 차단을 구분합니다
        print(f"감시 실패: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps([s.as_dict() for s in states], ensure_ascii=False, indent=2))
    else:
        if not states:
            print("감시 대상 워커 워크트리가 없습니다.")
        for s in states:
            mark = "차단" if s.blocked else "진행"
            print(f"[{mark}] {s.name}  branch={s.branch}  commits={s.commits}  dirty={s.dirty}")
            if s.blocked:
                print(f"        사유: {s.blocked_reason}")
                print(f"        조치: {s.blocked_fix}")
                print(f"        터미널: {s.terminal}")
            for note in s.notes:
                print(f"        참고: {note}")

    return 1 if any(s.blocked for s in states) else 0


if __name__ == "__main__":
    raise SystemExit(main())
