#!/usr/bin/env python3
"""
scripts/orca_taskctl.py

Orca Control Plane 자동화 도구. 코디네이터가 Task Intent 만 작성하면
Capsule 확장, 모델 라우팅, Worktree 관리, Worker 기동, 완료 검증까지
한 번에 처리합니다.

주요 기능:
  1. expand   -- Task Intent(YAML)를 규약 준수 ORCA_TASK_CAPSULE_V2 로 확장합니다.
  2. dispatch -- Task Intent -> Capsule -> Worker 기동(worker-start) 파이프라인.
  3. finalize -- worker_done -> summarize -> Level1 -> Reviewer -> 최종 판정.
  4. status   -- Task / Run 상태를 조회합니다.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import uuid
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        char_len,
        load_capsule,
        load_report,
        parse_capsule_list,
        parse_capsule_scalar,
        truncate,
    )
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_contract import (
        char_len,
        load_capsule,
        load_report,
        parse_capsule_list,
        parse_capsule_scalar,
        truncate,
    )

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CAPSULE_BUDGET = 8000
COMPLEX_CAPSULE_BUDGET = 12000
DEFAULT_MODEL = "gemini-3.7-flash-high"
DEFAULT_RUN_ID = "run_auto"
CAPSULE_VERSION = "2.1.0"
MAX_CONCURRENT_WRITE_WORKERS = 3
ACTIVE_TASK_STATUSES = frozenset({"dispatched"})

# 기본 Capsule 템플릿
CAPSULE_TEMPLATE = """\
schema: ORCA_TASK_CAPSULE_V2
version: "{version}"
mode: {mode}
run_id: "{run_id}"
task_id: "{task_id}"
role: "{role}"

objective: >
  {objective}

why_now: >
  {why_now}

ground_truth:
  - fact: "G1 데이터 무손실: DB 스키마 및 행 수 100% 보존"
    evidence: "docs/context/CURRENT_STATE.md"
    recheck: false
  - fact: "Train/Serve 특징 단일화: src/ml/features.py 만 사용"
    evidence: "src/ml/features.py"
    recheck: false
  - fact: "1인 작업: Pull Request 생성 금지, main 직접 커밋 금지"
    evidence: "AGENTS.md"
    recheck: false

allowed_read_files:
{allowed_read_files}

allowed_write_files:
{allowed_write_files}

search_scope:
  mode: deny_by_default
  allowed_globs:
{allowed_globs}

forbidden:
  - "README.md 전체 재독 금지"
  - "SKILLS.md 전체 재독 금지"
  - "AGENTS.md 전체 재독 금지"
  - "docs/design/REFACTORING_DESIGN.md 전체 재독 금지"
  - "DB 스키마 및 원본 데이터 변경 금지"
  - "main 브랜치 직접 수정 및 커밋 금지"
  - "Pull Request 생성 금지"
  - "이모지 사용 금지 (주석, 커밋 메시지, 문서)"

shared_resources:
  - resource: features_py
    ownership: read_only

required_change:
{required_change}

acceptance:
{acceptance}

verification_commands:
  - "uv run pytest tests/ -q -m 'not data_assets'"
  - "python3 scripts/validate_agent_rules.py --quiet"

artifact_paths:
{artifact_paths}

escalate_when:
  - "allowed_write_files 범위를 벗어난 파일 수정이 필요한 경우"
  - "ground_truth와 실제 코드/동작이 충돌하는 경우"
  - "새로운 외부 패키지/의존성 추가가 필요한 경우"
  - "DB 스키마 변경 또는 데이터 삭제가 필요한 경우"
  - "테스트 실패 원인이 Task 범위 밖의 레거시 결함인 경우"

report_path: "{report_path}"
return_contract: {return_contract}
"""


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _run_command(
    cmd: list[str],
    cwd: Path | None = None,
    timeout: int = 30,
) -> tuple[int, str, str]:
    """subprocess.run 래퍼로 (returncode, stdout, stderr) 를 반환합니다."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
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


def _format_yaml_list(items: list[str], indent: str = "  - ") -> str:
    """리스트의 모든 항목을 따옴표로 감싸고 내부 따옴표를 이스케이프하여 YAML 로 포맷합니다."""
    if not items:
        return ""
    lines = []
    for item in items:
        escaped = item.replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'{indent}"{escaped}"')
    return "\n".join(lines)


def _format_review_checklist(items: list[dict[str, str]]) -> str:
    """review_checklist 항목들을 YAML 블록으로 포맷합니다."""
    if not items:
        return ""
    lines = ["review_checklist:"]
    for item in items:
        c_id = item.get("id", "").replace("\\", "\\\\").replace('"', '\\"')
        q = item.get("question", "").replace("\\", "\\\\").replace('"', '\\"')
        d = item.get("defect_when", "").replace("\\", "\\\\").replace('"', '\\"')
        h = item.get("how", "").replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'  - id: "{c_id}"')
        lines.append(f'    question: "{q}"')
        lines.append(f'    defect_when: "{d}"')
        if h:
            lines.append(f'    how: "{h}"')
    return "\n".join(lines)


def _to_glob(path_str: str) -> str:
    """경로 문자열을 glob 패턴으로 변환합니다 (removesuffix 로 안전하게 접미사 제거)."""
    for suffix in ("/...", "/**", "/"):
        if path_str.endswith(suffix):
            base = path_str[:-len(suffix)]
            return f"{base}/**"
    return path_str


# ---------------------------------------------------------------------------
# Task Intent 파싱
# ---------------------------------------------------------------------------


def parse_intent(text: str) -> dict[str, Any]:
    """Task Intent YAML 을 정규식 기반으로 파싱합니다."""
    result: dict[str, Any] = {
        "schema": "ORCA_TASK_INTENT_V1",
        "role": "builder",
        "objective": "",
        "scope": [],
        "acceptance": [],
        "risk": "medium",
        "context": "",
        "review_checklist": [],
    }

    lines = text.splitlines()
    total_lines = len(lines)
    i = 0

    while i < total_lines:
        line = lines[i]
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            i += 1
            continue

        # review_checklist 특별 처리
        if re.match(r"^review_checklist:\s*(?:#.*)?$", stripped):
            checklist: list[dict[str, str]] = []
            i += 1
            current_item: dict[str, str] = {}
            while i < total_lines:
                raw_sub = lines[i]
                if raw_sub and not raw_sub[0].isspace() and not raw_sub.startswith("#"):
                    break
                sub_stripped = raw_sub.strip()
                if not sub_stripped or sub_stripped.startswith("#"):
                    i += 1
                    continue

                if sub_stripped.startswith("- "):
                    if current_item:
                        checklist.append(current_item)
                        current_item = {}
                    sub_content = sub_stripped[2:].strip()
                    m = re.match(r"^([a-z_]+):\s*(.*)$", sub_content)
                    if m:
                        k, v = m.group(1), m.group(2).strip().strip("\"'")
                        current_item[k] = v
                else:
                    m = re.match(r"^([a-z_]+):\s*(.*)$", sub_stripped)
                    if m:
                        k, v = m.group(1), m.group(2).strip().strip("\"'")
                        current_item[k] = v
                i += 1

            if current_item:
                checklist.append(current_item)
            result["review_checklist"] = checklist
            continue

        # 최상위 키: 값 파싱
        match = re.match(r"^([a-z_]+):\s*(.*)$", stripped)
        if match:
            key = match.group(1)
            val = match.group(2).strip()

            if key in ("scope", "acceptance"):
                items: list[str] = []
                if val and val != "[]":
                    items.append(val.strip("\"'"))
                i += 1
                while i < total_lines:
                    raw_sub = lines[i]
                    if raw_sub and not raw_sub[0].isspace() and not raw_sub.startswith("#"):
                        break
                    sub_stripped = raw_sub.strip()
                    if sub_stripped and sub_stripped.startswith("- "):
                        items.append(sub_stripped[2:].strip().strip("\"'"))
                    i += 1
                result[key] = items
                continue

            if val in (">", "|", ">-", "|-"):
                folded_lines: list[str] = []
                i += 1
                while i < total_lines:
                    raw_sub = lines[i]
                    if raw_sub and not raw_sub[0].isspace() and not raw_sub.startswith("#"):
                        break
                    sub_stripped = raw_sub.strip()
                    if sub_stripped and not sub_stripped.startswith("#"):
                        folded_lines.append(sub_stripped)
                    i += 1
                result[key] = " ".join(folded_lines).strip()
                continue

            # 일반 단일값
            clean_val = re.sub(r"\s+#.*$", "", val).strip().strip("\"'")
            result[key] = clean_val
            i += 1
            continue

        i += 1

    return result


# ---------------------------------------------------------------------------
# Intent -> Capsule 확장
# ---------------------------------------------------------------------------


def expand_intent_to_capsule(
    intent: dict[str, Any],
    task_id: str | None = None,
    run_id: str = DEFAULT_RUN_ID,
    capsule_path: str | Path | None = None,
) -> str:
    """Task Intent 를 규약 준수 ORCA_TASK_CAPSULE_V2 로 확장합니다."""
    if task_id is None:
        task_id = intent.get("task_id") or f"task_{uuid.uuid4().hex[:12]}"

    role = intent.get("role", "builder")
    is_reviewer = role == "reviewer"

    # Reviewer 인 경우 review_checklist 필수 검증 (결함 3 해결)
    review_checklist = intent.get("review_checklist", [])
    if is_reviewer and not review_checklist:
        raise ValueError("리뷰어(reviewer) Intent 에는 review_checklist 가 1개 이상 필요합니다.")

    objective = intent.get("objective") or "(작업 목표 미지정)"
    context = intent.get("context", "")
    risk = intent.get("risk", "medium")
    scope = intent.get("scope", [])
    acceptance = intent.get("acceptance", [])

    why_now = context if context else f"위험도 {risk} 작업. {role} 역할 수행."

    # 쓰기 범위와 읽기 범위 분리 (결함 2 해결: 읽기 범위는 쓰기 범위의 진상위집합)
    write_files = list(scope) if scope else ["src/...", "tests/..."]

    self_capsule_str = str(capsule_path) if capsule_path else f".orca/capsules/{task_id}/capsule.yaml"
    reference_files = [self_capsule_str, "docs/context/CURRENT_STATE.md"]
    read_files = list(dict.fromkeys(reference_files + write_files))

    allowed_read_formatted = _format_yaml_list(read_files)
    allowed_write_formatted = _format_yaml_list(write_files)

    globs = [_to_glob(s) for s in write_files]
    allowed_globs_formatted = _format_yaml_list(globs, indent="    - ")

    # required_change
    req_items = [objective[:120]] if objective else ["(작업 목표 참조)"]
    required_change_formatted = _format_yaml_list(req_items)

    # acceptance
    acc_items = list(acceptance) if acceptance else ["테스트 통과", "규칙 검증 통과"]
    acceptance_formatted = _format_yaml_list(acc_items)

    # artifact_paths & report_path
    if is_reviewer:
        report_path = str(intent.get("report_path") or f".orca/capsules/{task_id}/review_done.json")
        return_contract = "ORCA_REVIEW_DONE_V2"
        mode = "reviewer"
        artifact_paths_formatted = _format_yaml_list([report_path])
    else:
        report_path = str(intent.get("report_path") or f".orca/capsules/{task_id}/worker_done.json")
        return_contract = "ORCA_WORKER_DONE_V2"
        mode = intent.get("mode", "worker")
        artifact_paths_formatted = _format_yaml_list([f"docs/analysis/{task_id}.md"])

    capsule = CAPSULE_TEMPLATE.format(
        version=CAPSULE_VERSION,
        mode=mode,
        run_id=run_id,
        task_id=task_id,
        role=role,
        objective=objective,
        why_now=why_now,
        allowed_read_files=allowed_read_formatted,
        allowed_write_files=allowed_write_formatted,
        allowed_globs=allowed_globs_formatted,
        required_change=required_change_formatted,
        acceptance=acceptance_formatted,
        artifact_paths=artifact_paths_formatted,
        report_path=report_path,
        return_contract=return_contract,
    )

    if is_reviewer:
        checklist_block = _format_review_checklist(review_checklist)
        capsule += "\n" + checklist_block + "\n"

    # 예산 검증 (char_len 사용)
    capsule_len = char_len(capsule)
    budget = COMPLEX_CAPSULE_BUDGET if risk == "high" else CAPSULE_BUDGET
    if capsule_len > budget:
        sys.stderr.write(f"경고: Capsule 크기 {capsule_len}자가 예산 {budget}자를 초과합니다.\n")

    return capsule


# ---------------------------------------------------------------------------
# 동시성 제어 및 쓰기 워커 판별 (Preflight)
# ---------------------------------------------------------------------------


def resolve_run_id(
    explicit: str | None,
    timeout: int = 10,
) -> tuple[str | None, str | None]:
    """Run ID 를 해석합니다.

    explicit 이 있고 자리표시자 DEFAULT_RUN_ID('run_auto')가 아니면 그것을 씁니다.
    그렇지 않으면 orca orchestration run-current --json 을 호출해 result.run.id 를 씁니다.
    어느 쪽도 얻지 못하면 (None, 오류메시지) 를 반환합니다.
    """
    if explicit and explicit != DEFAULT_RUN_ID:
        return explicit, None

    cmd = ["orca", "orchestration", "run-current", "--json"]
    code, stdout, stderr = _run_command(cmd, timeout=timeout)
    if code != 0:
        err_msg = stderr.strip() or stdout.strip() or "명령 실행 실패"
        return None, f"run-current 조회 실패 (종료 코드 {code}): {err_msg}"

    try:
        data = json.loads(stdout)
    except Exception as exc:
        return None, f"run-current JSON 파싱 실패: {exc}"

    run_id = None
    if isinstance(data, dict):
        if "result" in data and isinstance(data["result"], dict):
            run_obj = data["result"].get("run", {})
            if isinstance(run_obj, dict):
                run_id = run_obj.get("id")
        elif "run" in data and isinstance(data["run"], dict):
            run_id = data["run"].get("id")

    if not run_id:
        return None, "run-current 결과에서 run.id 를 찾을 수 없습니다."

    return str(run_id), None


def list_dispatched_tasks(
    run_id: str,
    timeout: int = 30,
) -> tuple[list[dict[str, Any]], str | None]:
    """orca orchestration task-list --run <run_id> --json 을 호출해 dispatched 상태의 태스크 목록과 오류 메시지를 반환합니다."""
    cmd = ["orca", "orchestration", "task-list", "--run", run_id, "--json"]
    code, stdout, stderr = _run_command(cmd, timeout=timeout)
    if code != 0:
        err_msg = stderr.strip() or stdout.strip() or "명령 실행 실패"
        return [], f"task-list 조회 실패 (종료 코드 {code}): {err_msg}"

    try:
        data = json.loads(stdout)
    except Exception as exc:
        return [], f"task-list JSON 파싱 실패: {exc}"

    if isinstance(data, dict):
        if "result" in data and isinstance(data["result"], dict):
            raw_tasks = data["result"].get("tasks", [])
        else:
            raw_tasks = data.get("tasks", [])
    elif isinstance(data, list):
        raw_tasks = data
    else:
        raw_tasks = []

    dispatched_tasks: list[dict[str, Any]] = []
    for t in raw_tasks:
        if not isinstance(t, dict):
            continue
        status = str(t.get("status", "")).lower()
        if status in ACTIVE_TASK_STATUSES:
            dispatched_tasks.append(t)

    return dispatched_tasks, None


def task_has_write_scope(task_id: str, capsule_dir: Path) -> bool:
    """<capsule_dir>/<task_id>/capsule.yaml 의 allowed_write_files 가 비어 있지 않은지 검사합니다.

    파일이 없거나 읽을 수 없으면 fail-closed 로 True 를 반환합니다.
    다른 Run 의 Capsule 은 이 저장소의 capsule_dir 밑에 없어서 파일 부재로
    fail-closed 쓰기로 계상되며, 이는 동시성 상한을 보수적으로 만드는 방향이라 안전합니다.
    """
    if not task_id:
        return True

    capsule_path = capsule_dir / task_id / "capsule.yaml"
    if not capsule_path.exists():
        return True

    try:
        capsule_text = load_capsule(capsule_path)
        write_files = parse_capsule_list(capsule_text, "allowed_write_files")
        return len(write_files) > 0
    except Exception:
        return True


def check_write_concurrency(
    task_id: str,
    capsule_dir: Path,
    run_id: str | None = None,
    limit: int = MAX_CONCURRENT_WRITE_WORKERS,
    timeout: int = 30,
) -> dict[str, Any]:
    """동시 쓰기 워커 상한(기본 3)을 검사합니다."""
    # 이번 Task 가 읽기 전용인지 확인
    is_write = task_has_write_scope(task_id, capsule_dir)
    if not is_write:
        return {
            "allowed": True,
            "active_write_count": 0,
            "limit": limit,
            "occupying": [],
            "probe_error": None,
            "reason": f"Task {task_id}는 읽기 전용(allowed_write_files 빈 목록)이므로 동시 쓰기 상한 검사를 면제합니다.",
        }

    # Run ID 해석
    resolved_run_id, run_err = resolve_run_id(run_id, timeout=timeout)
    if run_err is not None or not resolved_run_id:
        err_msg = run_err or "Run ID 해석 실패"
        return {
            "allowed": False,
            "active_write_count": 0,
            "limit": limit,
            "occupying": [],
            "probe_error": err_msg,
            "reason": f"Run ID 해석 실패로 인한 안전 거부 (fail-closed): {err_msg}",
        }

    # dispatched 태스크 목록 조회
    dispatched_tasks, probe_error = list_dispatched_tasks(run_id=resolved_run_id, timeout=timeout)
    if probe_error is not None:
        return {
            "allowed": False,
            "active_write_count": 0,
            "limit": limit,
            "occupying": [],
            "probe_error": probe_error,
            "reason": f"dispatched 태스크 목록 조회 실패로 인한 안전 거부 (fail-closed): {probe_error}",
        }

    occupying_tasks: list[str] = []
    for t in dispatched_tasks:
        other_task_id = t.get("id") or ""
        # 자기 Task 는 점유 집계에서 제외
        if other_task_id == task_id:
            continue
        if task_has_write_scope(other_task_id, capsule_dir):
            occupying_tasks.append(other_task_id or "unknown")

    active_write_count = len(occupying_tasks)
    if active_write_count >= limit:
        return {
            "allowed": False,
            "active_write_count": active_write_count,
            "limit": limit,
            "occupying": occupying_tasks,
            "probe_error": None,
            "reason": f"동시 쓰기 워커 상한({limit}개)에 도달했습니다. 현재 점유: {active_write_count}개 ({', '.join(occupying_tasks)})",
        }

    return {
        "allowed": True,
        "active_write_count": active_write_count,
        "limit": limit,
        "occupying": occupying_tasks,
        "probe_error": None,
        "reason": f"동시 쓰기 워커 상한 검사 통과 (현재 활성: {active_write_count}/{limit}개)",
    }


# ---------------------------------------------------------------------------
# Worktree 및 Worker 시작 (결함 6 해결: 실제 CLI 서명만 사용)
# ---------------------------------------------------------------------------


def create_worktree(
    name: str,
    cwd: Path | None = None,
) -> tuple[int, str, str]:
    """orca worktree create --name <name> 을 실행합니다."""
    cmd = ["orca", "worktree", "create", "--name", name]
    return _run_command(cmd, cwd=cwd)


def worker_start(
    task_id: str,
    agent_id: str | None = None,
    terminal_handle: str | None = None,
    model: str | None = None,
    worktree: str | None = None,
    name: str | None = None,
    repo: str | None = None,
    as_json: bool = False,
    timeout: int = 30,
) -> tuple[int, str, str]:
    """orca orchestration worker-start 명령을 실행합니다."""
    cmd = ["orca", "orchestration", "worker-start", "--task", task_id]
    if agent_id:
        cmd.extend(["--agent", agent_id])
    elif terminal_handle:
        cmd.extend(["--terminal", terminal_handle])

    if model:
        cmd.extend(["--model", model])
    if worktree:
        cmd.extend(["--worktree", worktree])
    if name:
        cmd.extend(["--name", name])
    if repo:
        cmd.extend(["--repo", repo])
    if as_json:
        cmd.append("--json")

    return _run_command(cmd, timeout=timeout)


def _extract_cli_error(stdout: str) -> str | None:
    """Orca CLI 의 stdout JSON 에서 error.message 를 꺼냅니다.

    실패가 stderr 가 아니라 stdout 의 JSON 본문으로만 오는 경로가 있어
    stderr 만 읽으면 원인이 사라집니다.
    """
    if not stdout or not stdout.strip():
        return None
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    err = payload.get("error")
    if isinstance(err, dict):
        message = err.get("message")
        return str(message) if message else None
    if isinstance(err, str) and err:
        return err
    return None


def _launch_succeeded(stdout: str) -> bool:
    """종료 코드 0 이어도 ok 가 false 인 응답을 성공으로 보지 않습니다."""
    if not stdout or not stdout.strip():
        return True
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return True
    return not (isinstance(payload, dict) and payload.get("ok") is False)


def dispatch_worker(
    task_id: str,
    to_handle: str | None = None,
    from_handle: str | None = None,
    run_id: str | None = None,
    inject: bool = False,
    dry_run: bool = False,
    return_preamble: bool = False,
    as_json: bool = False,
    timeout: int = 30,
) -> tuple[int, str, str]:
    """orca orchestration dispatch 명령을 실행합니다."""
    cmd = ["orca", "orchestration", "dispatch", "--task", task_id]
    if to_handle:
        cmd.extend(["--to", to_handle])
    if from_handle:
        cmd.extend(["--from", from_handle])
    if run_id:
        cmd.extend(["--run", run_id])
    if inject:
        cmd.append("--inject")
    if dry_run:
        cmd.append("--dry-run")
    if return_preamble:
        cmd.append("--return-preamble")
    if as_json:
        cmd.append("--json")

    return _run_command(cmd, timeout=timeout)


def terminal_send(handle: str, text: str, timeout: int = 30) -> tuple[int, str, str]:
    """orca terminal send 로 터미널에 지시를 직접 투입합니다.

    `--enter` 를 빠뜨리면 텍스트가 입력창에 남기만 하고 전달되지 않습니다.
    """
    cmd = [
        "orca",
        "terminal",
        "send",
        "--terminal",
        handle,
        "--text",
        text,
        "--enter",
        "--json",
    ]
    return _run_command(cmd, timeout=timeout)


def resolve_dispatch_id(task_id: str, timeout: int = 30) -> str | None:
    """Task 의 현재 유효한 Dispatch ID 를 조회합니다.

    재 Dispatch 하면 새 권한이 발급되는데 워커는 자기 문맥에 남은 옛 ID 로
    보고해 `capability is revoked` 로 거부됩니다. 유효 ID 를 워커에게 명시
    전달하기 위해 씁니다.
    """
    cmd = ["orca", "orchestration", "dispatch-show", "--task", task_id, "--json"]
    code, stdout, _stderr = _run_command(cmd, timeout=timeout)
    if code != 0 or not stdout.strip():
        return None
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is False:
        return None
    dispatch = (payload.get("result") or {}).get("dispatch") or {}
    dispatch_id = dispatch.get("id")
    return str(dispatch_id) if dispatch_id else None


def build_capsule_notice(
    capsule_path: Path,
    report_path: str | None = None,
    dispatch_id: str | None = None,
) -> str:
    """Capsule 정본 경로 고지문을 만듭니다.

    `dispatch --inject` 는 Orca Task 의 spec 만 주입하며 Capsule 경로도 내용도
    전달하지 않습니다. 이 고지문 없이는 워커가 한두 문장 요약만 보고 일하며,
    2026-08-17 에 워커 3대 전부가 파일명과 보고 계약을 위반했습니다.
    """
    parts = [
        f"정본 사양은 {capsule_path} 입니다.",
        "지금 그 파일을 읽고 이 작업의 유일한 정본으로 삼으십시오.",
        "objective, acceptance, allowed_write_files, forbidden 을 그대로 지킵니다.",
        "allowed_write_files 에 없는 파일명을 새로 만들지 마십시오.",
        "README, AGENTS.md, SKILLS.md, 설계서는 읽지 않습니다.",
        "코드 변경 작업은 커밋해야 완료입니다. commit_count 가 0 이면 succeeded 대신 escalation 을 보냅니다.",
    ]
    if report_path:
        parts.append(f"보고 JSON 은 {report_path} 에 ORCA_WORKER_DONE_V2 계약으로 씁니다.")
    if dispatch_id:
        parts.append(f"worker_done 전송 시 dispatchId 는 {dispatch_id} 입니다.")
    return " ".join(parts)


def build_task_spec(objective: str, capsule_path: Path) -> str:
    """Orca Task 의 spec 에 Capsule 절대 경로를 함께 넣습니다.

    spec 은 `dispatch --inject` 가 워커에게 실제로 전달하는 유일한 본문입니다.
    경로를 여기에 넣으면 워커가 첫 턴부터 정본을 찾을 수 있습니다.
    """
    summary = objective.strip().replace("\n", " ")
    if char_len(summary) > 400:
        summary = truncate(summary, 400)
    return f"{summary} 정본 사양(Capsule): {capsule_path}"


# ---------------------------------------------------------------------------
# Finalize (결함 4 해결: 정확한 종료 코드 산출)
# ---------------------------------------------------------------------------


def finalize_task(
    report_path: Path,
    capsule_path: Path,
    repo: Path,
    worktree_path: Path | None = None,
    base: str = "main",
    branch: str = "HEAD",
    run_reviewer: bool = False,
    reviewer_model: str = DEFAULT_MODEL,
) -> dict[str, Any]:
    """worker_done 보고를 검증하고 Level 1/Reviewer 검증 파이프라인을 실행합니다."""
    scripts_dir = Path(__file__).resolve().parent
    result: dict[str, Any] = {
        "summarize": None,
        "level1": None,
        "reviewer": None,
        "exit_code": 0,
    }

    tool_error = False
    gate_fail = False

    # 1. summarize_worker_done.py 실행
    summarize_cmd = [
        sys.executable,
        str(scripts_dir / "summarize_worker_done.py"),
        "--report",
        str(report_path),
        "--capsule",
        str(capsule_path),
        "--json",
    ]
    code_summ, stdout_summ, stderr_summ = _run_command(summarize_cmd, timeout=30)
    if code_summ == 2:
        tool_error = True
        result["summarize"] = {
            "error": truncate(stderr_summ.strip() or "요약 도구 오류", 200),
            "exit_code": 2,
        }
    else:
        if code_summ == 1:
            gate_fail = True
        try:
            result["summarize"] = json.loads(stdout_summ)
        except json.JSONDecodeError:
            tool_error = True
            result["summarize"] = {
                "error": "요약 JSON 파싱 실패",
                "raw": truncate(stdout_summ, 200),
                "exit_code": 2,
            }

    # 2. orca_level1_gate.py 실행
    target_repo = worktree_path if (worktree_path and worktree_path.exists()) else repo
    level1_cmd = [
        sys.executable,
        str(scripts_dir / "orca_level1_gate.py"),
        "--base",
        base,
        "--branch",
        branch,
        "--repo",
        str(target_repo),
        "--capsule",
        str(capsule_path),
        "--json",
    ]
    code_l1, stdout_l1, stderr_l1 = _run_command(level1_cmd, timeout=120)
    if code_l1 == 2:
        tool_error = True
        result["level1"] = {
            "error": truncate(stderr_l1.strip() or "Level 1 게이트 도구 오류", 200),
            "exit_code": 2,
        }
    else:
        if code_l1 == 1:
            gate_fail = True
        try:
            result["level1"] = json.loads(stdout_l1)
        except json.JSONDecodeError:
            tool_error = True
            result["level1"] = {
                "error": "Level 1 JSON 파싱 실패",
                "raw": truncate(stdout_l1, 200),
                "exit_code": 2,
            }

    # 3. orca_run_reviewer.py 실행 (선택)
    if run_reviewer:
        reviewer_out = report_path.parent / f"{report_path.stem}_review.json"
        reviewer_cmd = [
            sys.executable,
            str(scripts_dir / "orca_run_reviewer.py"),
            "--capsule",
            str(capsule_path),
            "--out",
            str(reviewer_out),
            "--base",
            base,
            "--branch",
            branch,
            "--repo",
            str(target_repo),
            "--model",
            reviewer_model,
            "--json",
        ]
        code_rev, stdout_rev, stderr_rev = _run_command(reviewer_cmd, timeout=600)
        if code_rev == 2:
            tool_error = True
            result["reviewer"] = {
                "error": truncate(stderr_rev.strip() or "리뷰어 도구 오류", 200),
                "exit_code": 2,
            }
        else:
            if code_rev == 1:
                gate_fail = True
            try:
                result["reviewer"] = json.loads(stdout_rev)
            except json.JSONDecodeError:
                tool_error = True
                result["reviewer"] = {
                    "error": "리뷰어 JSON 파싱 실패",
                    "raw": truncate(stdout_rev, 200),
                    "exit_code": 2,
                }

    # 종합 종료 코드 결정 (규칙: 도구오류/파싱실패 2, 게이트실패/계약위반 1, 전부 깨끗 0)
    if tool_error:
        final_exit_code = 2
    elif gate_fail:
        final_exit_code = 1
    else:
        final_exit_code = 0

    result["exit_code"] = final_exit_code
    return result


# ---------------------------------------------------------------------------
# CLI 명령어 핸들러
# ---------------------------------------------------------------------------


def cmd_expand(args: argparse.Namespace) -> int:
    intent_path = Path(args.intent)
    if not intent_path.exists():
        sys.stderr.write(f"오류: Intent 파일 없음: {intent_path}\n")
        return 2

    intent_text = intent_path.read_text(encoding="utf-8")
    intent = parse_intent(intent_text)

    out_path = Path(args.out)
    try:
        capsule = expand_intent_to_capsule(
            intent,
            task_id=args.task_id,
            run_id=args.run_id,
            capsule_path=out_path,
        )
    except ValueError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(capsule, encoding="utf-8")

    parsed_task_id = parse_capsule_scalar(capsule, "task_id") or intent.get("task_id") or "auto-generated"
    parsed_role = parse_capsule_scalar(capsule, "role") or intent.get("role", "builder")
    write_files = parse_capsule_list(capsule, "allowed_write_files")

    if args.json:
        data = {
            "capsule_path": str(out_path),
            "char_count": char_len(capsule),
            "task_id": parsed_task_id,
            "risk": intent.get("risk", "medium"),
            "role": parsed_role,
            "write_files_count": len(write_files),
        }
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(f"Capsule 생성 완료: {out_path}")
        print(f"  문자 수: {char_len(capsule)}")
        print(f"  위험도:  {intent.get('risk', 'medium')}")
        print(f"  역할:    {parsed_role}")
        print(f"  쓰기 범위: {len(write_files)}개 항목")

    return 0


def _maybe_json(text: str) -> Any:
    """JSON 이면 파싱해서, 아니면 원문 문자열로 돌려줍니다."""
    if not text or not text.strip():
        return None
    try:
        return json.loads(text)
    except (json.JSONDecodeError, ValueError):
        return text.strip()


def _deliver_capsule_notice(
    args: argparse.Namespace,
    task_id: str,
    capsule_path: Path,
    intent: dict[str, Any],
) -> dict[str, Any]:
    """기동 직후 Capsule 정본 경로를 워커 터미널에 투입합니다.

    터미널 부착 경로에서만 가능합니다. worker-start 로 기동한 감독 워커는
    핸들을 즉시 알 수 없으므로 건너뛰고 그 사실을 상태로 남깁니다.
    """
    if getattr(args, "no_capsule_notice", False):
        return {"status": "skipped", "reason": "no_capsule_notice"}
    if not args.terminal:
        return {"status": "skipped", "reason": "no_terminal_handle"}

    dispatch_id = resolve_dispatch_id(task_id)
    report_path = intent.get("report_path") or f"{capsule_path.parent}/worker_done.json"
    text = build_capsule_notice(capsule_path, report_path=str(report_path), dispatch_id=dispatch_id)
    code, stdout, stderr = terminal_send(args.terminal, text)
    if code == 0 and _launch_succeeded(stdout):
        return {"status": "sent", "dispatch_id": dispatch_id, "chars": char_len(text)}

    reason = stderr.strip() or _extract_cli_error(stdout) or "알 수 없는 오류"
    sys.stderr.write(
        f"경고: Capsule 고지 전송 실패: {reason}\n"
        f"워커가 Capsule 을 읽지 못한 상태로 작업할 수 있습니다. 수동 전달이 필요합니다.\n"
    )
    return {"status": "failed", "reason": reason, "dispatch_id": dispatch_id}


def cmd_create(args: argparse.Namespace) -> int:
    """Intent 를 Capsule 로 확장하고 그 절대 경로를 담은 Orca Task 를 만듭니다.

    Task 의 spec 은 `dispatch --inject` 가 워커에게 전달하는 유일한 본문이라,
    Capsule 경로를 여기에 넣어야 워커가 첫 턴부터 정본을 찾습니다.
    """
    intent_path = Path(args.intent)
    if not intent_path.exists():
        sys.stderr.write(f"오류: Intent 파일 없음: {intent_path}\n")
        return 2

    intent = parse_intent(intent_path.read_text(encoding="utf-8"))
    task_id = args.task_id or intent.get("task_id") or f"task_{intent_path.stem}"

    task_capsule_dir = Path(args.capsule_dir) / task_id
    task_capsule_dir.mkdir(parents=True, exist_ok=True)
    capsule_path = (task_capsule_dir / "capsule.yaml").resolve()

    try:
        capsule = expand_intent_to_capsule(
            intent,
            task_id=task_id,
            run_id=args.run_id,
            capsule_path=capsule_path,
        )
    except ValueError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2
    capsule_path.write_text(capsule, encoding="utf-8")

    spec = build_task_spec(intent.get("objective", ""), capsule_path)
    cmd = [
        "orca",
        "orchestration",
        "task-create",
        "--run",
        args.run_id,
        "--spec",
        spec,
        "--json",
    ]
    if args.task_title:
        cmd.extend(["--task-title", args.task_title])
    if args.display_name:
        cmd.extend(["--display-name", args.display_name])
    if args.deps:
        cmd.extend(["--deps", args.deps])

    code, stdout, stderr = _run_command(cmd)
    if code != 0 or not _launch_succeeded(stdout):
        reason = stderr.strip() or _extract_cli_error(stdout) or "알 수 없는 오류"
        sys.stderr.write(f"오류: task-create 실패: {reason}\n")
        return 1

    created_id = None
    payload = _maybe_json(stdout)
    if isinstance(payload, dict):
        created_id = ((payload.get("result") or {}).get("task") or {}).get("id")

    if args.json:
        print(
            json.dumps(
                {
                    "task_id": created_id,
                    "capsule": str(capsule_path),
                    "spec": spec,
                    "char_count": char_len(capsule),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"Task 생성 완료: {created_id}")
        print(f"Capsule: {capsule_path}")
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    intent_path = Path(args.intent)
    if not intent_path.exists():
        sys.stderr.write(f"오류: Intent 파일 없음: {intent_path}\n")
        return 2

    intent_text = intent_path.read_text(encoding="utf-8")
    intent = parse_intent(intent_text)
    task_id = args.task_id or intent.get("task_id") or f"task_{intent_path.stem}"

    capsule_dir = Path(args.capsule_dir)
    task_capsule_dir = capsule_dir / task_id
    task_capsule_dir.mkdir(parents=True, exist_ok=True)
    # 워커는 다른 워크트리에서 돌기 때문에 상대 경로로는 Capsule 을 찾지 못합니다.
    capsule_path = (task_capsule_dir / "capsule.yaml").resolve()

    try:
        capsule = expand_intent_to_capsule(
            intent,
            task_id=task_id,
            run_id=args.run_id,
            capsule_path=capsule_path,
        )
    except ValueError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2

    capsule_path.write_text(capsule, encoding="utf-8")

    model = args.model or DEFAULT_MODEL

    if args.dry_run:
        if args.json:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "capsule": str(capsule_path),
                        "model": model,
                        "task_id": task_id,
                        "char_count": char_len(capsule),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"[Dry-run] Capsule: {capsule_path}")
            print(f"[Dry-run] Model:   {model}")
            print(f"[Dry-run] 문자 수: {char_len(capsule)}")
        return 0

    # 동시 쓰기 워커 상한 Preflight 검사 (worker-start 호출 직전)
    if getattr(args, "skip_concurrency_check", False):
        sys.stderr.write("경고: --skip-concurrency-check 지정으로 동시 쓰기 워커 상한 검사를 건너뜁니다.\n")
    else:
        limit = getattr(args, "max_write_workers", MAX_CONCURRENT_WRITE_WORKERS)
        concurrency = check_write_concurrency(
            task_id=task_id,
            capsule_dir=capsule_dir,
            run_id=args.run_id,
            limit=limit,
        )
        if not concurrency["allowed"]:
            active_count = concurrency["active_write_count"]
            occupying = concurrency["occupying"]
            limit_val = concurrency["limit"]
            reason = concurrency["reason"]
            occupying_str = ", ".join(occupying) if occupying else "없음"
            err_msg = (
                f"동시 쓰기 워커 상한 초과: {reason} "
                f"(현재 활성 쓰기 워커: {active_count}개, 상한: {limit_val}개, 점유: {occupying_str})"
            )
            sys.stderr.write(f"오류: {err_msg}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "concurrency_limit_exceeded"
                            if not concurrency["probe_error"]
                            else "concurrency_probe_failed",
                            "allowed": False,
                            "task_id": task_id,
                            "active_write_count": active_count,
                            "limit": limit_val,
                            "occupying": occupying,
                            "probe_error": concurrency["probe_error"],
                            "reason": reason,
                            "exit_code": 1,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 1

    # 기동 경로 선택. --terminal 이 있으면 이미 떠 있는 터미널에 Dispatch 로 부착하고,
    # 없으면 worker-start 로 새 워커를 감독 기동한다. worker-start --agent 는
    # claude, codex, cursor 만 받으므로 Antigravity 계열은 터미널 부착 경로만 쓸 수 있다.
    if args.terminal:
        sys.stderr.write(f"터미널 부착 Dispatch 중... (task={task_id}, terminal={args.terminal})\n")
        code, stdout, stderr = dispatch_worker(
            task_id=task_id,
            to_handle=args.terminal,
            run_id=args.run_id if args.run_id != DEFAULT_RUN_ID else None,
            inject=True,
            as_json=args.json,
        )
        launch_cmd = f"orca orchestration dispatch --task {task_id} --to {args.terminal} --inject"
    else:
        if not args.agent:
            sys.stderr.write(
                "오류: --agent 또는 --terminal 중 하나가 필요합니다. "
                "worker-start --agent 는 claude, codex, cursor 만 받으므로 "
                "Antigravity/OpenCode 워커는 terminal create 로 띄운 뒤 --terminal 로 부착하십시오.\n"
            )
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "launch_target_missing",
                            "task_id": task_id,
                            "capsule": str(capsule_path),
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

        worktree_name = args.worktree_name or f"orca-{task_id}"
        sys.stderr.write(f"워커 기동 시작 중... (task={task_id}, model={model})\n")
        code, stdout, stderr = worker_start(
            task_id=task_id,
            agent_id=args.agent,
            model=model,
            worktree=args.worktree,
            name=worktree_name if args.worktree.startswith("new-") else None,
            repo=args.repo,
            as_json=args.json,
        )
        launch_cmd = (
            f"orca orchestration worker-start --task {task_id} --agent {args.agent} "
            f"--model {model} --worktree {args.worktree} --name {worktree_name}"
        )

    if code == 0 and _launch_succeeded(stdout):
        notice = _deliver_capsule_notice(args, task_id, capsule_path, intent)
        if args.json:
            payload: dict[str, Any] = {"launch": _maybe_json(stdout)}
            payload["capsule"] = str(capsule_path)
            payload["capsule_notice"] = notice
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"워커 기동 완료:\n{stdout}")
            print(f"Capsule 고지: {notice['status']}")
        return 0

    # Orca CLI 는 실패를 stdout JSON 의 error.message 로 내보내면서 stderr 를 비워
    # 두는 경우가 있다. stderr 만 읽으면 원인이 사라지므로 stdout 도 함께 본다.
    err_msg = stderr.strip() or _extract_cli_error(stdout) or "알 수 없는 오류"
    sys.stderr.write(f"오류: 워커 기동 실패 (종료 코드 {code}): {err_msg}\n")
    sys.stderr.write(f"실행할 명령: {launch_cmd}\n")
    if args.json:
        print(
            json.dumps(
                {
                    "error": err_msg,
                    "task_id": task_id,
                    "model": model,
                    "capsule": str(capsule_path),
                    "exit_code": code,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 1


def cmd_finalize(args: argparse.Namespace) -> int:
    report_path = Path(args.report)
    capsule_path = Path(args.capsule)
    repo = Path(args.repo).resolve()
    worktree_path = Path(args.worktree).resolve() if args.worktree else None

    for p in (report_path, capsule_path):
        if not p.exists():
            sys.stderr.write(f"오류: 파일 없음: {p}\n")
            return 2

    # 파싱 유효성 사전 검사 (orca_contract 함수 활용)
    try:
        load_report(report_path)
        load_capsule(capsule_path)
    except Exception as exc:
        sys.stderr.write(f"오류: 파일 검증 실패 ({exc})\n")
        return 2

    sys.stderr.write("검증 파이프라인 실행 중...\n")
    result = finalize_task(
        report_path=report_path,
        capsule_path=capsule_path,
        repo=repo,
        worktree_path=worktree_path,
        base=args.base,
        branch=args.branch,
        run_reviewer=args.reviewer,
        reviewer_model=args.reviewer_model,
    )

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
    else:
        summ = result.get("summarize")
        if isinstance(summ, dict):
            digest = summ.get("digest", "")
            if digest:
                print(truncate(digest, 1500))
            else:
                verdict = summ.get("effective_verdict", summ.get("declared_verdict", "?"))
                violations = summ.get("violations_count", 0)
                print(f"요약: verdict={verdict}, violations={violations}")
        else:
            print(f"요약 정보 없음: {summ}")

        l1 = result.get("level1")
        if isinstance(l1, dict):
            print(f"\nLevel 1: {l1.get('verdict', '?')}")

        rev = result.get("reviewer")
        if isinstance(rev, dict):
            rev_verdict = rev.get("effective_verdict", rev.get("declared_verdict", "?"))
            print(f"Reviewer: {rev_verdict}")

    return int(result["exit_code"])


def cmd_status(args: argparse.Namespace) -> int:
    cmd = ["orca", "orchestration", "task-list", "--run", args.run_id]
    if args.json:
        cmd.append("--json")

    code, stdout, stderr = _run_command(cmd, timeout=10)
    if args.json:
        if code == 0:
            print(stdout)
        else:
            print(
                json.dumps(
                    {
                        "run_id": args.run_id,
                        "task_id": args.task_id,
                        "orca_available": False,
                        "error": stderr.strip(),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
    else:
        if code == 0:
            print(stdout)
        else:
            sys.stderr.write(f"Orca CLI 상태 조회 실패: {stderr.strip()}\n")
    return code if code == 0 else 1


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="orca_taskctl",
        description="Orca Control Plane 자동화 도구",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # expand
    exp = sub.add_parser("expand", help="Task Intent 를 전체 Capsule 로 확장합니다.")
    exp.add_argument("--intent", required=True, help="Task Intent YAML 파일 경로")
    exp.add_argument("--out", required=True, help="출력 Capsule YAML 경로")
    exp.add_argument("--task-id", help="Task ID (미지정 시 자동 생성)")
    exp.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run ID")
    exp.add_argument("--json", action="store_true", help="JSON 출력")

    # dispatch
    dsp = sub.add_parser("dispatch", help="Task Intent -> Capsule -> Dispatch 파이프라인")
    dsp.add_argument("--intent", required=True, help="Task Intent YAML 파일 경로")
    dsp.add_argument("--repo", default=".", help="저장소 루트 경로")
    dsp.add_argument("--model", help="모델 ID (미지정 시 자동 선택)")
    dsp.add_argument("--task-id", help="Task ID")
    dsp.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run ID")
    dsp.add_argument("--capsule-dir", default=".orca/capsules", help="Capsule 저장 디렉터리")
    dsp.add_argument("--agent", help="워커 agent ID (worker-start 경로. claude, codex, cursor 만)")
    dsp.add_argument("--terminal", help="워커 터미널 핸들 (터미널 부착 Dispatch 경로)")
    dsp.add_argument(
        "--worktree",
        default="new-child",
        help="worker-start 의 워크트리 선택자 (기본: new-child)",
    )
    dsp.add_argument(
        "--worktree-name",
        help="새 워크트리 이름. new-child 및 new-top-level 에는 필수이며 미지정 시 orca-<task_id>",
    )
    dsp.add_argument("--no-probe", action="store_true", help="모델 probe 생략")
    dsp.add_argument("--dry-run", action="store_true", help="기동 없이 Capsule 생성까지만")
    dsp.add_argument(
        "--max-write-workers",
        type=int,
        default=MAX_CONCURRENT_WRITE_WORKERS,
        help=f"동시 쓰기 워커 최대 허용 수 (기본: {MAX_CONCURRENT_WRITE_WORKERS})",
    )
    dsp.add_argument(
        "--skip-concurrency-check",
        action="store_true",
        help="동시 쓰기 워커 상한 검사를 건너뜁니다 (경고 출력).",
    )
    dsp.add_argument(
        "--no-capsule-notice",
        action="store_true",
        help="기동 직후 Capsule 정본 경로 고지문 전송을 생략합니다 (권장하지 않음).",
    )
    dsp.add_argument("--json", action="store_true", help="JSON 출력")

    # create
    crt = sub.add_parser("create", help="Intent -> Capsule -> Orca Task 생성")
    crt.add_argument("--intent", required=True, help="Task Intent YAML 파일 경로")
    crt.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run ID")
    crt.add_argument("--task-id", help="Task ID")
    crt.add_argument("--capsule-dir", default=".orca/capsules", help="Capsule 저장 디렉터리")
    crt.add_argument("--task-title", help="Task 제목")
    crt.add_argument("--display-name", help="워커 행에 표시할 이름")
    crt.add_argument("--deps", help="선행 Task ID JSON 배열")
    crt.add_argument("--json", action="store_true", help="JSON 출력")

    # finalize
    fin = sub.add_parser("finalize", help="worker_done -> 검증 파이프라인 실행")
    fin.add_argument("--report", required=True, help="worker_done 보고 JSON 경로")
    fin.add_argument("--capsule", required=True, help="Task Capsule YAML 경로")
    fin.add_argument("--repo", default=".", help="저장소 루트 경로")
    fin.add_argument("--worktree", help="작업 트리 경로")
    fin.add_argument("--base", default="main", help="비교 기준 git ref")
    fin.add_argument("--branch", default="HEAD", help="검증 대상 git ref")
    fin.add_argument("--reviewer", action="store_true", help="Level 2 Reviewer 실행")
    fin.add_argument("--reviewer-model", default=DEFAULT_MODEL, help="Reviewer 모델 ID")
    fin.add_argument("--json", action="store_true", help="JSON 출력")

    # status
    sts = sub.add_parser("status", help="Task / Run 상태를 조회합니다.")
    sts.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run ID")
    sts.add_argument("--task-id", help="Task ID")
    sts.add_argument("--json", action="store_true", help="JSON 출력")

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "expand":
        return cmd_expand(args)
    if args.command == "create":
        return cmd_create(args)
    if args.command == "dispatch":
        return cmd_dispatch(args)
    if args.command == "finalize":
        return cmd_finalize(args)
    if args.command == "status":
        return cmd_status(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
