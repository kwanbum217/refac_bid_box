"""
scripts/orca_worker_watch.py

활성 Orca 워커의 진척과 차단 상태를 한 번에 점검하거나 상시 감시합니다.

코디네이터가 Dispatch 후 감시를 잊지 않도록, 워커별 커밋 수·미커밋 변경 수와
터미널 화면의 차단 신호(신뢰 대화창, 설문, 인증 정체, 권한 요청)를 한 명령으로
모아 보여줍니다. 감시를 지침으로만 두면 지켜지지 않습니다. 2026-08-26 세션에서
워커가 CLI 설문 프롬프트에 막혀 있었고, 부팅이 'not signed in' 에서 멈춘 사례가
세 번 있었습니다.

사용법:
    # 1회 점검 (기본)
    uv run python scripts/orca_worker_watch.py
    uv run python scripts/orca_worker_watch.py --json

    # 상시 감시 루프
    uv run python scripts/orca_worker_watch.py --watch
    uv run python scripts/orca_worker_watch.py --watch --interval 10 --max-iterations 30
    uv run python scripts/orca_worker_watch.py --watch --min-commits 1

종료 코드:
    0  모든 워커가 정상 진행 중이거나 감시 대상 없음, 또는 완료 조건(min-commits) 충족, 또는 최대 반복 완료
    1  차단 신호가 감지된 워커가 있음 (코디네이터 개입 필요)
    2  도구 오류
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess  # nosec B404  고정된 git·orca 명령만 실행하며 사용자 입력을 받지 않습니다
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# 기본 주기 및 정체 후보 판정 기준 시간 (초 단위)
DEFAULT_INTERVAL_SECONDS: float = 10.0
DEFAULT_STALL_THRESHOLD_SECONDS: float = 300.0

# Antigravity 파일 편집/생성 승인 대화창 신호 상수 (단일 진실 원천)
FILE_EDIT_DIALOG_SIGNALS: tuple[str, ...] = (
    "Accept this file edit?",
    "Allow creation of this file?",
)


def normalize_text(text: str) -> str:
    """대소문자와 공백(줄바꿈, 연속 공백)을 정규화합니다."""
    return " ".join(text.lower().split())


# 정체 신호 분류: prompt 는 키 입력으로 풀리는 승인 대기, failure 는 지시 재전송이 필요한 실패 정체.
BlockKind = str  # "prompt" | "failure" | "reclaim"

FAILURE_REDEPLOY_FIX = (
    "코디네이터가 동일 Task 지시를 재전송(dispatch)하거나 워커 터미널을 재기동하십시오"
)

# 터미널 화면에서 워커가 사람 개입을 기다리고 있음을 뜻하는 신호.
# 값은 (needle, 사유, 해제 방법, 분류) 이며 코디네이터가 바로 조치할 수 있게 적습니다.
BLOCK_SIGNALS: list[tuple[str, str, str, BlockKind]] = [
    # 실패 정체: 키 입력으로 풀리지 않음. detect_block 은 failure 를 prompt 보다 우선합니다.
    ("network error", "네트워크 오류로 턴 종료", FAILURE_REDEPLOY_FIX, "failure"),
    ("connection error", "네트워크 연결 오류", FAILURE_REDEPLOY_FIX, "failure"),
    ("fetch failed", "네트워크 요청 실패", FAILURE_REDEPLOY_FIX, "failure"),
    ("rate limit", "API rate limit", FAILURE_REDEPLOY_FIX, "failure"),
    ("http 429", "HTTP 429 rate limit", FAILURE_REDEPLOY_FIX, "failure"),
    ("error 429", "HTTP 429 rate limit", FAILURE_REDEPLOY_FIX, "failure"),
    ("status 429", "HTTP 429 rate limit", FAILURE_REDEPLOY_FIX, "failure"),
    ("status code 429", "HTTP 429 rate limit", FAILURE_REDEPLOY_FIX, "failure"),
    ("quota exceeded", "API quota 초과", FAILURE_REDEPLOY_FIX, "failure"),
    ("authentication failed", "인증 실패", FAILURE_REDEPLOY_FIX, "failure"),
    ("unauthorized", "인증 만료 또는 권한 없음", FAILURE_REDEPLOY_FIX, "failure"),
    ("token expired", "토큰 만료", FAILURE_REDEPLOY_FIX, "failure"),
    ("model not found", "모델을 찾을 수 없음", FAILURE_REDEPLOY_FIX, "failure"),
    ("upstream error", "업스트림 서버 오류", FAILURE_REDEPLOY_FIX, "failure"),
    ("http 502", "HTTP 502 업스트림 오류", FAILURE_REDEPLOY_FIX, "failure"),
    ("error 502", "HTTP 502 업스트림 오류", FAILURE_REDEPLOY_FIX, "failure"),
    ("status 502", "HTTP 502 업스트림 오류", FAILURE_REDEPLOY_FIX, "failure"),
    ("status code 502", "HTTP 502 업스트림 오류", FAILURE_REDEPLOY_FIX, "failure"),
    ("bad gateway", "HTTP 502 업스트림 오류", FAILURE_REDEPLOY_FIX, "failure"),
    # 승인 대기: 키 입력으로 해제 가능
    (
        "Do you trust",
        "Antigravity 폴더 신뢰 대화창",
        "terminal send --enter --text '' (기본 선택이 신뢰)",
        "prompt",
    ),
    (
        "Trust this workspace",
        "Cursor 워크스페이스 신뢰 대화창",
        "terminal send --text 'a'",
        "prompt",
    ),
    (
        "not signed in",
        "Antigravity 부팅이 인증 단계에서 정체",
        "터미널을 닫고 재기동. --model 플래그 없이 agy 로 띄울 것",
        "prompt",
    ),
    (
        "How's the CLI experience",
        "CLI 만족도 설문 프롬프트",
        "terminal send --text '0' (Skip)",
        "prompt",
    ),
    (
        "Accept this file edit?",
        "Antigravity 파일 편집 승인 대화창",
        "화면을 읽고 승인 여부를 판단. shift+tab(ESC [ Z)으로 auto-approve 전환 가능",
        "prompt",
    ),
    (
        "Allow creation of this file?",
        "Antigravity 파일 생성 승인 대화창",
        "화면을 읽고 승인 여부를 판단. shift+tab(ESC [ Z)으로 auto-approve 전환 가능",
        "prompt",
    ),
    (
        "Allow this",
        "도구 실행 권한 요청",
        "화면을 읽고 승인 여부를 판단. shift+tab 으로 auto-approve 전환 가능",
        "prompt",
    ),
    ("Do you want to proceed", "진행 확인 프롬프트", "화면을 읽고 승인 여부를 판단", "prompt"),
]

BLOCK_KIND_LABELS: dict[BlockKind, str] = {
    "prompt": "승인 대기",
    "failure": "실패 정체",
    "reclaim": "회수 대기",
}

PROMPT_BLOCK_NOTE = (
    "감시 신호와 실제 원인이 다를 수 있으니(네트워크 오류로 인한 턴 종료 등) "
    "터미널을 직접 확인하십시오"
)
FAILURE_BLOCK_NOTE = (
    "키 입력으로 풀리지 않습니다. 코디네이터가 Task 지시를 재전송(dispatch)해야 합니다"
)

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
    blocked_kind: BlockKind | None = None
    stall_candidate: bool = False
    unchanged_seconds: float = 0.0
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
            "blocked_kind": self.blocked_kind,
            "blocked_reason": self.blocked_reason,
            "blocked_fix": self.blocked_fix,
            "stall_candidate": self.stall_candidate,
            "unchanged_seconds": round(self.unchanged_seconds, 1),
            "notes": list(self.notes),
        }


def format_worker_state(s: WorkerState) -> list[str]:
    """워커 상태를 터미널 출력용 문자열 줄 목록으로 변환합니다."""
    lines: list[str] = []
    if s.blocked:
        kind_label = BLOCK_KIND_LABELS.get(s.blocked_kind or "", s.blocked_kind or "")
        mark = f"차단:{kind_label}"
    elif s.stall_candidate:
        mark = "정체후보"
    else:
        mark = "진행"
    lines.append(f"[{mark}] {s.name}  branch={s.branch}  commits={s.commits}  dirty={s.dirty}")
    if s.terminal:
        lines.append(f"        터미널: {s.terminal}")
    if s.blocked:
        kind_label = BLOCK_KIND_LABELS.get(s.blocked_kind or "", s.blocked_kind or "")
        lines.append(f"        분류: {kind_label}")
        lines.append(f"        사유: {s.blocked_reason}")
        lines.append(f"        조치: {s.blocked_fix}")
    for note in s.notes:
        lines.append(f"        참고: {note}")
    return lines


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


def is_shell_default_title(title: Any) -> bool:
    """워커 터미널로 볼 근거가 없는 제목이면 True.

    셸 기본 제목(예: Terminal 1)과 제목이 없는 터미널이 여기 해당합니다. CLI 워커는
    코디네이터가 준 제목을 갖거나 CLI 가 제목을 갱신하므로, 제목이 비어 있다는 것은
    아무 명령 없이 열린 셸이라는 뜻입니다. 2026-08-28 에 실제로 제목이 없는 셸이
    같은 워크트리에 함께 있었고, 이를 워커 후보로 보면 핸들 정렬 우연에 따라
    엉뚱한 터미널이 선택됩니다.
    """
    if not isinstance(title, str) or not title.strip():
        return True
    return title.startswith("Terminal")


def select_worker_terminal(
    candidates: list[dict[str, Any]],
) -> tuple[dict[str, Any] | None, list[str]]:
    """후보 중 워커 터미널을 고릅니다. (선택 항목, note 목록)."""
    notes: list[str] = []
    if not candidates:
        return None, notes

    if len(candidates) == 1:
        return candidates[0], notes

    worker_likes = [c for c in candidates if not is_shell_default_title(c.get("title"))]
    if worker_likes:
        chosen = sorted(worker_likes, key=lambda c: str(c.get("handle") or ""))[0]
        handle = chosen.get("handle")
        notes.append(f"워크트리에 터미널 {len(candidates)}개. 선택: {handle}")
        return chosen, notes

    chosen = candidates[0]
    handle = chosen.get("handle")
    notes.append(
        f"워크트리에 터미널 {len(candidates)}개. 모두 셸 기본 제목이어서 첫 항목 사용: {handle}"
    )
    return chosen, notes


def terminal_map() -> dict[str, list[dict[str, Any]]]:
    """워크트리 경로 -> 터미널 후보 목록. orca 를 쓸 수 없으면 빈 딕셔너리."""
    raw = _run(["orca", "terminal", "list", "--json"], timeout=60)
    try:
        payload = json.loads(raw)
    except Exception:
        return {}
    result = payload.get("result") or {}
    terminals = result.get("terminals") or result.get("sessions") or []
    mapping: dict[str, list[dict[str, Any]]] = {}
    for item in terminals:
        path = item.get("worktreePath")
        if path:
            mapping.setdefault(str(path), []).append(item)
    return mapping


def terminal_tail(handle: str, lines: int = TAIL_LINES) -> str:
    detail = ANSI_RE.sub("", _run(["orca", "terminal", "read", "--terminal", handle], timeout=60))
    return "\n".join(detail.splitlines()[-lines:])


def check_worker_done_report(
    screen_tail: str,
    worktree_path: str | None = None,
    repo: Path | None = None,
) -> tuple[str, str, BlockKind] | None:
    """worker_done 전송/완료 신호가 있으나 reportPath 가 없거나 보고 파일이 존재하지 않는 경우 차단으로 판정합니다."""
    norm = normalize_text(screen_tail)
    if "worker_done" not in norm and "orchestration send" not in norm:
        return None

    # worker_done 관련 명령/메시지가 포함된 줄 탐색
    lines = [line.strip() for line in screen_tail.splitlines() if line.strip()]
    done_lines = [
        line
        for line in lines
        if "worker_done" in line.lower()
        or ("send" in line.lower() and ("--type" in line.lower() or "worker_done" in line.lower()))
    ]
    if not done_lines:
        return None

    # report_path / --report-path / reportPath 탐색
    target_path = None
    for line in done_lines:
        m_flag = re.search(r"--report(?:-path)?\s+[\"']?([^\s\"']+)[\"']?", line)
        if m_flag:
            target_path = m_flag.group(1).strip()
            break
        m_json = re.search(r'["\']?report(?:_p|P)ath["\']?\s*:\s*["\']([^"\']+)["\']', line)
        if m_json:
            target_path = m_json.group(1).strip()
            break

    if not target_path:
        return (
            "worker_done 완료 메시지에 reportPath 가 누락됨",
            "worker_done_guard 를 통해 report_path 를 지정하여 전송하십시오",
            "failure",
        )

    # 보고 파일 존재 여부 확인
    base_dir = Path(worktree_path) if worktree_path else (repo or Path.cwd())
    resolved_file = Path(target_path)
    if not resolved_file.is_absolute():
        resolved_file = base_dir / resolved_file

    if not resolved_file.is_file():
        return (
            f"worker_done 보고 파일이 존재하지 않음 ({target_path})",
            f"보고 JSON 파일({target_path})을 생성한 후 worker_done_guard 로 전송하십시오",
            "failure",
        )

    return None


def detect_block(
    screen_tail: str,
    worktree_path: str | None = None,
    repo: Path | None = None,
) -> tuple[str, str, BlockKind] | None:
    done_block = check_worker_done_report(screen_tail, worktree_path, repo)
    if done_block:
        return done_block

    norm_tail = normalize_text(screen_tail)
    prompt_match: tuple[str, str, BlockKind] | None = None
    for needle, reason, fix, kind in BLOCK_SIGNALS:
        if normalize_text(needle) not in norm_tail:
            continue
        match = (reason, fix, kind)
        if kind == "failure":
            return match
        if prompt_match is None:
            prompt_match = match
    return prompt_match


def update_history(
    states: list[WorkerState],
    history: dict[str, dict[str, Any]],
    now: float,
    stall_threshold: float = DEFAULT_STALL_THRESHOLD_SECONDS,
) -> None:
    """워커 상태 목록의 변화 이력을 갱신하고 정체 후보 여부를 판정합니다."""
    for s in states:
        key = s.path or s.name
        entry = history.get(key)
        if entry is None:
            history[key] = {
                "commits": s.commits,
                "dirty": s.dirty,
                "last_change_time": now,
                "first_seen_time": now,
            }
            s.unchanged_seconds = 0.0
        else:
            if s.commits != entry["commits"] or s.dirty != entry["dirty"]:
                entry["commits"] = s.commits
                entry["dirty"] = s.dirty
                entry["last_change_time"] = now
                s.unchanged_seconds = 0.0
            else:
                s.unchanged_seconds = max(0.0, now - entry["last_change_time"])

        if s.unchanged_seconds >= stall_threshold and not s.blocked:
            s.stall_candidate = True
            stall_sec = int(s.unchanged_seconds)
            stall_note = (
                f"정체 후보: {stall_sec}초 동안 커밋/미커밋 변화가 없습니다 "
                f"(임계값 {int(stall_threshold)}초). 터미널을 확인하십시오"
            )
            s.notes = [n for n in s.notes if not n.startswith("커밋 0 · 미커밋 0")]
            if stall_note not in s.notes:
                s.notes.append(stall_note)


def collect(
    repo: Path,
    base: str = "main",
    history: dict[str, dict[str, Any]] | None = None,
    now: float | None = None,
    stall_threshold: float = DEFAULT_STALL_THRESHOLD_SECONDS,
) -> list[WorkerState]:
    terminals = terminal_map()
    states: list[WorkerState] = []
    for name, path, branch in list_worktrees(repo):
        commits, dirty = worktree_progress(path, base)
        state = WorkerState(name=name, path=path, branch=branch, commits=commits, dirty=dirty)
        candidates = terminals.get(path, [])
        info, select_notes = select_worker_terminal(candidates)
        state.notes.extend(select_notes)
        if info:
            state.terminal = info.get("handle")
            if state.terminal:
                found = detect_block(terminal_tail(state.terminal), worktree_path=path, repo=repo)
                if found:
                    state.blocked_reason, state.blocked_fix, state.blocked_kind = found
                    if state.blocked_kind == "failure":
                        state.notes.append(FAILURE_BLOCK_NOTE)
                    else:
                        state.notes.append(PROMPT_BLOCK_NOTE)
        else:
            state.notes.append(
                "연결된 터미널이 없습니다. 워커가 종료됐거나 아직 기동되지 않았습니다"
            )
        if commits == 0 and dirty == 0 and not state.blocked:
            state.notes.append(
                "커밋 0 · 미커밋 0. 조사 단계이거나 정체일 수 있으니 터미널을 확인하십시오"
            )
        states.append(state)

    try:
        from scripts.orca_settled_session_audit import audit_lingering_sessions
    except (ModuleNotFoundError, ImportError):
        from orca_settled_session_audit import audit_lingering_sessions
    try:
        lingering = audit_lingering_sessions().get("lingering") or []
    except Exception:
        lingering = []
    lingering_by_handle = {item.get("handle"): item for item in lingering if item.get("handle")}
    for state in states:
        item = lingering_by_handle.get(state.terminal or "")
        if not item:
            continue
        state.blocked_reason = (
            f"completed Task {item.get('task_id')} 의 워커 터미널이 아직 열려 있습니다"
        )
        state.blocked_fix = (
            "worker-release 후 terminal close 로 회수하고, 병합된 워크트리만 제거하십시오"
        )
        state.blocked_kind = "reclaim"
    seen_handles = {s.terminal for s in states if s.terminal}
    for item in lingering:
        handle = item.get("handle") or ""
        if handle in seen_handles:
            continue
        extra = WorkerState(
            name=item.get("task_id") or "settled-session",
            path="",
            branch="",
            commits=0,
            dirty=0,
            terminal=handle,
            blocked_reason=(
                f"completed Task {item.get('task_id')} 의 워커 터미널이 아직 열려 있습니다"
            ),
            blocked_fix=(
                "worker-release 후 terminal close 로 회수하고, 병합된 워크트리만 제거하십시오"
            ),
            blocked_kind="reclaim",
        )
        states.append(extra)

    if history is not None:
        current_time = time.time() if now is None else now
        update_history(states, history, current_time, stall_threshold)

    return states


def watch_loop(
    repo: Path,
    base: str = "main",
    interval: float = DEFAULT_INTERVAL_SECONDS,
    max_iterations: int | None = 1,
    min_commits: int | None = None,
    stall_threshold: float = DEFAULT_STALL_THRESHOLD_SECONDS,
    json_output: bool = False,
    time_func: Callable[[], float] | None = None,
    sleep_func: Callable[[float], None] | None = None,
) -> int:
    """워커 상태를 주기적으로 감시하고 차단 또는 완료 조건을 판정합니다."""
    get_time = time_func or time.time
    do_sleep = sleep_func or time.sleep

    history: dict[str, dict[str, Any]] = {}
    prev_signatures: dict[str, tuple[Any, ...]] = {}
    iteration = 0

    while True:
        now = get_time()
        states = collect(
            repo,
            base=base,
            history=history,
            now=now,
            stall_threshold=stall_threshold,
        )
        if history and not any(s.unchanged_seconds > 0 or s.stall_candidate for s in states):
            update_history(states, history, now, stall_threshold)

        current_signatures = {
            s.path or s.name: (
                s.name,
                s.branch,
                s.commits,
                s.dirty,
                s.terminal,
                s.blocked,
                s.blocked_kind,
                s.blocked_reason,
                s.stall_candidate,
            )
            for s in states
        }

        has_changes = iteration == 0 or current_signatures != prev_signatures

        if has_changes:
            if json_output:
                print(json.dumps([s.as_dict() for s in states], ensure_ascii=False, indent=2))
            else:
                if iteration == 0:
                    if not states:
                        print("감시 대상 워커 워크트리가 없습니다.")
                    for s in states:
                        for line in format_worker_state(s):
                            print(line)
                else:
                    for s in states:
                        key = s.path or s.name
                        if (
                            key not in prev_signatures
                            or prev_signatures[key] != current_signatures[key]
                        ):
                            for line in format_worker_state(s):
                                print(line)

        prev_signatures = current_signatures

        # 1. 차단 신호 감지 시 즉시 종료 (코디네이터 개입 필요)
        if any(s.blocked for s in states):
            return 1

        # 2. 지정된 최소 커밋 수 도달 완료 조건 충족 시 정상 종료
        if min_commits is not None and states and all(s.commits >= min_commits for s in states):
            return 0

        # 3. 최대 반복 횟수 도달 확인
        iteration += 1
        if max_iterations is not None and iteration >= max_iterations:
            return 1 if any(s.blocked for s in states) else 0

        do_sleep(interval)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Orca 워커 진척·차단 감시")
    parser.add_argument("--repo", type=Path, default=Path.cwd(), help="주 저장소 경로")
    parser.add_argument("--base", default="main", help="진척 비교 기준 브랜치")
    parser.add_argument("--json", action="store_true", help="기계 판독 출력")
    parser.add_argument("--watch", action="store_true", help="상시 감시 모드 활성화")
    parser.add_argument(
        "--interval",
        "--interval-sec",
        dest="interval",
        type=float,
        default=None,
        help="감시 주기 (초 단위, 기본 10초)",
    )
    parser.add_argument(
        "--max-iterations",
        "--max-iter",
        dest="max_iterations",
        type=int,
        default=None,
        help="최대 감시 반복 횟수 (기본: 1회, --watch 시 무제한)",
    )
    parser.add_argument(
        "--min-commits",
        type=int,
        default=None,
        help="모든 워크트리가 도달해야 하는 최소 커밋 수 (도달 시 0 종료)",
    )
    parser.add_argument(
        "--stall-threshold",
        "--stall-sec",
        dest="stall_threshold",
        type=float,
        default=DEFAULT_STALL_THRESHOLD_SECONDS,
        help="정체 후보 판정 기준 시간(초, 기본 300초)",
    )
    args = parser.parse_args(argv)

    if (
        args.watch
        or args.interval is not None
        or args.min_commits is not None
        or args.max_iterations is not None
    ):
        max_iterations = args.max_iterations
        interval = args.interval if args.interval is not None else DEFAULT_INTERVAL_SECONDS
    else:
        max_iterations = 1
        interval = DEFAULT_INTERVAL_SECONDS

    stall_threshold = args.stall_threshold

    try:
        return watch_loop(
            repo=args.repo,
            base=args.base,
            interval=interval,
            max_iterations=max_iterations,
            min_commits=args.min_commits,
            stall_threshold=stall_threshold,
            json_output=args.json,
        )
    except KeyboardInterrupt:
        return 0
    except Exception as exc:
        print(f"감시 실패: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
