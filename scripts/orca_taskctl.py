#!/usr/bin/env python3
"""
scripts/orca_taskctl.py

Orca Control Plane 자동화 도구. 코디네이터가 Task Intent 만 작성하면
Capsule 확장, 모델 라우팅, Worktree 생성, Worker Dispatch, 완료 검증까지
한 번에 처리합니다.

주요 기능:
  1. expand   -- Task Intent(YAML)를 전체 ORCA_TASK_CAPSULE_V2 로 확장합니다.
  2. dispatch -- Task Intent → Capsule → Worktree → Worker Dispatch 전체 파이프라인.
  3. finalize -- worker_done → summarize → Level1 → Reviewer → Digest.
  4. status   -- Task / Run 상태를 조회합니다.

설계 목표:
  - 코디네이터는 500~1,500자 TASK_INTENT 만 작성합니다.
  - Capsule 생성, 모델 선택, Worktree 관리, Dispatch 는 코드가 처리합니다.
  - 검증은 기존 도구(summarize_worker_done, orca_level1_gate, orca_run_reviewer)를 호출합니다.

Task Intent 포맷 (ORCA_TASK_INTENT_V1):
    schema: ORCA_TASK_INTENT_V1
    role: builder
    objective: >
      한 문장으로 작업 목표를 기술합니다.
    scope:
      - "src/target_module/..."
      - "tests/test_target_module.py"
    acceptance:
      - "테스트 통과"
      - "규칙 검증 통과"
    risk: medium
    context: >
      (선택) 추가 배경 정보.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    from scripts.orca_contract import (
        char_len,
        load_capsule,
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
        parse_capsule_list,
        parse_capsule_scalar,
        truncate,
    )

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CAPSULE_BUDGET = 8000  # 일반 Task Capsule 최대 문자 수
COMPLEX_CAPSULE_BUDGET = 12000  # 복잡 Task Capsule 최대 문자 수
DEFAULT_MODEL = "gemini-3.7-flash-high"
DEFAULT_RUN_ID = "run_auto"

# Capsule 템플릿
CAPSULE_TEMPLATE = """\
schema: ORCA_TASK_CAPSULE_V2
version: "2.0.0"
mode: worker
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
"""


# ---------------------------------------------------------------------------
# 유틸리티
# ---------------------------------------------------------------------------


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")  # noqa: UP017


def _run(cmd: list[str], cwd: Path | None = None, timeout: int = 30) -> tuple[int, str, str]:
    """서브프로세스를 실행하고 (returncode, stdout, stderr) 을 반환합니다."""
    try:
        proc = subprocess.run(cmd, cwd=str(cwd) if cwd else None, capture_output=True, text=True, timeout=timeout, check=False)
        return proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        stdout = (exc.stdout or b"").decode("utf-8", errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = (exc.stderr or b"").decode("utf-8", errors="replace") if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return -1, stdout, stderr
    except FileNotFoundError:
        return -2, "", f"실행 파일 없음: {cmd[0]}"


def _indent(text: str, prefix: str = "  ") -> str:
    """텍스트의 각 줄에 접두사를 붙입니다."""
    return "\n".join(prefix + line for line in text.splitlines())


def _format_list(items: list[str], indent: str = "  - ") -> str:
    """리스트를 YAML 리스트 형식으로 포맷합니다."""
    if not items:
        return "  - []"
    return "\n".join(f"{indent}\"{item}\"" if " " in item or "/" in item else f"{indent}{item}" for item in items)


# ---------------------------------------------------------------------------
# Task Intent 파싱
# ---------------------------------------------------------------------------


def parse_intent(text: str) -> dict[str, Any]:
    """Task Intent YAML 을 파싱합니다.

    간단한 정규식 기반 파서로, PyYAML 없이 동작합니다.
    """
    result: dict[str, Any] = {
        "schema": "ORCA_TASK_INTENT_V1",
        "role": "builder",
        "objective": "",
        "scope": [],
        "acceptance": [],
        "risk": "medium",
        "context": "",
    }

    lines = text.splitlines()
    current_key: str | None = None
    current_list: list[str] = []

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        # 최상위 키: 값
        match = re.match(r"^([a-z_]+):\s*(.*)$", stripped)
        if match:
            key = match.group(1)
            val = match.group(2).strip()

            if key in ("scope", "acceptance"):
                # 이전 리스트를 저장한 후 새 리스트 시작
                if current_key and current_list:
                    result[current_key] = current_list
                current_key = key
                current_list = []
                if val and val != "[]":
                    current_list.append(val.strip("\"'"))
                continue

            if key == "objective":
                if val in (">", "|", ">-", "|-"):
                    result[key] = _collect_folded(lines, lines.index(line) + 1)
                else:
                    result[key] = val.strip("\"'")
                continue

            if key == "context":
                if val in (">", "|", ">-", "|-"):
                    result[key] = _collect_folded(lines, lines.index(line) + 1)
                else:
                    result[key] = val.strip("\"'")
                continue

            if key in result:
                if val in (">", "|", ">-", "|-"):
                    result[key] = _collect_folded(lines, lines.index(line) + 1)
                else:
                    result[key] = val.strip("\"'")
            continue

        # 리스트 항목
        if current_key and stripped.startswith("- "):
            item = stripped[2:].strip().strip("\"'")
            current_list.append(item)
            continue

        # 리스트 종료
        if current_key and stripped and not stripped.startswith("- "):
            result[current_key] = current_list
            current_key = None
            current_list = []

    if current_key:
        result[current_key] = current_list

    return result


def _collect_folded(lines: list[str], start_idx: int) -> str:
    """folded scalar (> 또는 |) 의 본문을 수집합니다."""
    collected: list[str] = []
    for raw in lines[start_idx:]:
        if raw and not raw[0].isspace():
            break
        line_str = raw.strip()
        if line_str and not line_str.startswith("#"):
            collected.append(line_str)
    return " ".join(collected).strip()


# ---------------------------------------------------------------------------
# Intent → Capsule 확장
# ---------------------------------------------------------------------------


def expand_intent_to_capsule(
    intent: dict[str, Any],
    task_id: str | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> str:
    """Task Intent 를 전체 ORCA_TASK_CAPSULE_V2 로 확장합니다."""
    import uuid

    if task_id is None:
        task_id = f"task_{uuid.uuid4().hex[:12]}"

    role = intent.get("role", "builder")
    objective = intent.get("objective", "작업 목표 (미지정)")
    context = intent.get("context", "")
    risk = intent.get("risk", "medium")
    scope = intent.get("scope", [])
    acceptance = intent.get("acceptance", [])

    # why_now 생성
    if context:
        why_now = context
    else:
        why_now = f"위험도 {risk} 작업. {role} 역할."

    # allowed_read_files / allowed_write_files
    if scope:
        read_files = _format_list(scope)
        write_files = _format_list(scope)
    else:
        read_files = "  - \"src/...\"\n  - \"tests/...\""
        write_files = "  - \"src/...\"\n  - \"tests/...\""

    # allowed_globs
    if scope:
        globs = _format_list([f"{s.rstrip('/...').rstrip('/**').rstrip('/')}/**" if s.endswith(("/...", "/**")) else s for s in scope])
    else:
        globs = "  - \"src/**\"\n  - \"tests/**\""

    # required_change
    required_change = _format_list([f"{objective[:120]}"]) if objective else "  - \"(작업 목표 참조)\""

    # acceptance
    acc_items = list(acceptance) if acceptance else ["테스트 통과", "규칙 검증 통과"]
    acc_formatted = _format_list(acc_items)

    # artifact_paths
    artifact_paths = _format_list([f"docs/analysis/{task_id}.md"])

    capsule = CAPSULE_TEMPLATE.format(
        run_id=run_id,
        task_id=task_id,
        role=role,
        objective=objective,
        why_now=why_now,
        allowed_read_files=read_files,
        allowed_write_files=write_files,
        allowed_globs=globs,
        required_change=required_change,
        acceptance=acc_formatted,
        artifact_paths=artifact_paths,
    )

    capsule_len = char_len(capsule)
    budget = COMPLEX_CAPSULE_BUDGET if risk == "high" else CAPSULE_BUDGET
    if capsule_len > budget:
        print(
            f"경고: Capsule 크기 {capsule_len}자가 예산 {budget}자를 초과합니다.",
            file=sys.stderr,
        )

    return capsule


# ---------------------------------------------------------------------------
# Worktree 관리
# ---------------------------------------------------------------------------


def create_worktree(
    repo: Path,
    branch_name: str | None = None,
) -> tuple[Path, str]:
    """Orca CLI 또는 git worktree 로 격리 작업 트리를 생성합니다.

    반환값: (worktree_path, branch_name)
    """
    import uuid

    if branch_name is None:
        branch_name = f"worktree-{uuid.uuid4().hex[:8]}"

    # 1. Orca CLI 시도
    code, stdout, stderr = _run(["orca", "worktree", "create", "--branch", branch_name], cwd=repo)
    if code == 0:
        # stdout 에서 경로 추출 시도
        for line in stdout.splitlines():
            line = line.strip()
            if line and Path(line).exists():
                return Path(line), branch_name

    # 2. git worktree fallback
    worktree_path = repo.parent / f".qwen/worktrees/{branch_name}"
    worktree_path.parent.mkdir(parents=True, exist_ok=True)

    code, stdout, stderr = _run(
        ["git", "worktree", "add", str(worktree_path), "-b", branch_name],
        cwd=repo,
    )
    if code != 0:
        raise RuntimeError(f"Worktree 생성 실패: {stderr}")

    return worktree_path, branch_name


def setup_worktree_env(worktree_path: Path, repo_root: Path) -> None:
    """Worktree 에 .env 파일을 복사합니다."""
    env_src = repo_root / ".env"
    env_dst = worktree_path / ".env"
    if env_src.exists() and not env_dst.exists():
        import shutil
        shutil.copy2(env_src, env_dst)


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


def dispatch_worker(
    capsule_path: Path,
    worktree_path: Path,
    model: str = DEFAULT_MODEL,
    run_id: str = DEFAULT_RUN_ID,
    task_id: str | None = None,
) -> dict[str, Any]:
    """Orca CLI 로 워커를 Dispatch 합니다.

    Orca CLI 사용 불가 시 dry-run 모드로 전환됩니다.
    """
    result: dict[str, Any] = {
        "dispatched": False,
        "model": model,
        "capsule": str(capsule_path),
        "worktree": str(worktree_path),
        "method": "unknown",
    }

    # 1. Orca CLI dispatch 시도
    cmd = [
        "orca", "orchestration", "dispatch",
        "--run", run_id,
        "--task", task_id or "",
        "--capsule", str(capsule_path),
        "--model", model,
        "--worktree", str(worktree_path),
    ]
    code, stdout, stderr = _run(cmd, timeout=30)

    if code == 0:
        result["dispatched"] = True
        result["method"] = "orca"
        result["stdout"] = stdout
        return result

    # 2. agy dispatch 시도
    capsule_text = Path(capsule_path).read_text(encoding="utf-8")
    cmd2 = [
        "agy", "--model", model,
        "--print", capsule_text,
        "--print-timeout", "600s",
    ]
    code2, stdout2, stderr2 = _run(cmd2, timeout=10)

    if code2 == 0:
        result["dispatched"] = True
        result["method"] = "agy"
        result["stdout"] = stdout2
        return result

    # 3. Dry-run: Capsule 을 파일로 저장하고 안내
    result["method"] = "dry-run"
    result["note"] = (
        "Orca CLI 및 agy CLI 를 사용할 수 없습니다. "
        "Capsule 이 저장되었으니 수동으로 Dispatch 하십시오."
    )
    return result


# ---------------------------------------------------------------------------
# Finalize
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
    max_chars: int = 1500,
) -> dict[str, Any]:
    """worker_done 보고를 처리하고 검증 파이프라인을 실행합니다.

    단계:
      1. summarize_worker_done.py 실행
      2. orca_level1_gate.py 실행 (worktree 필요)
      3. (선택) orca_run_reviewer.py 실행
    """
    scripts_dir = Path(__file__).resolve().parent
    result: dict[str, Any] = {
        "summarize": None,
        "level1": None,
        "reviewer": None,
        "exit_code": 0,
    }

    # 1. summarize_worker_done
    summarize_cmd = [
        sys.executable, str(scripts_dir / "summarize_worker_done.py"),
        "--report", str(report_path),
        "--capsule", str(capsule_path),
        "--json",
    ]
    code, stdout, stderr = _run(summarize_cmd, timeout=30)
    if code in (0, 1):
        try:
            result["summarize"] = json.loads(stdout)
        except json.JSONDecodeError:
            result["summarize"] = {"raw": stdout, "error": "JSON 파싱 실패"}
    else:
        result["summarize"] = {"error": stderr, "exit_code": code}
        result["exit_code"] = 2

    # 2. Level 1 gate (worktree 필요)
    if worktree_path and worktree_path.exists():
        level1_cmd = [
            sys.executable, str(scripts_dir / "orca_level1_gate.py"),
            "--base", base,
            "--branch", branch,
            "--repo", str(worktree_path),
            "--capsule", str(capsule_path),
            "--json",
        ]
        code, stdout, stderr = _run(level1_cmd, timeout=60)
        try:
            result["level1"] = json.loads(stdout) if stdout.strip() else {"error": stderr}
            if code != 0 and result["exit_code"] == 0:
                result["exit_code"] = 1
        except json.JSONDecodeError:
            result["level1"] = {"raw": stdout, "error": "JSON 파싱 실패"}

    # 3. Reviewer (선택)
    if run_reviewer:
        reviewer_out = report_path.parent / f"{report_path.stem}_review.json"
        reviewer_cmd = [
            sys.executable, str(scripts_dir / "orca_run_reviewer.py"),
            "--capsule", str(capsule_path),
            "--out", str(reviewer_out),
            "--base", base,
            "--branch", branch,
            "--repo", str(worktree_path or repo),
            "--model", reviewer_model,
            "--json",
        ]
        code, stdout, stderr = _run(reviewer_cmd, timeout=600)
        try:
            result["reviewer"] = json.loads(stdout) if stdout.strip() else {"error": stderr}
            if code != 0 and result["exit_code"] == 0:
                result["exit_code"] = 1
        except json.JSONDecodeError:
            result["reviewer"] = {"raw": stdout, "error": "JSON 파싱 실패"}

    return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


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
    dsp = sub.add_parser("dispatch", help="Task Intent → Capsule → Worktree → Dispatch 전체 파이프라인.")
    dsp.add_argument("--intent", required=True, help="Task Intent YAML 파일 경로")
    dsp.add_argument("--repo", default=".", help="저장소 루트 경로")
    dsp.add_argument("--model", help="모델 ID (미지정 시 자동 선택)")
    dsp.add_argument("--task-id", help="Task ID")
    dsp.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run ID")
    dsp.add_argument("--capsule-dir", default=".orca/capsules", help="Capsule 저장 디렉터리")
    dsp.add_argument("--no-probe", action="store_true", help="모델 probe 생략")
    dsp.add_argument("--dry-run", action="store_true", help="Dispatch 없이 Capsule 생성까지만")
    dsp.add_argument("--json", action="store_true", help="JSON 출력")

    # finalize
    fin = sub.add_parser("finalize", help="worker_done → 검증 파이프라인 실행.")
    fin.add_argument("--report", required=True, help="worker_done 보고 JSON 경로")
    fin.add_argument("--capsule", required=True, help="Task Capsule YAML 경로")
    fin.add_argument("--repo", default=".", help="저장소 루트 경로")
    fin.add_argument("--worktree", help="격리 Worktree 경로 (Level 1 게이트 실행용)")
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


def cmd_expand(args: argparse.Namespace) -> int:
    intent_path = Path(args.intent)
    if not intent_path.exists():
        print(f"오류: Intent 파일 없음: {intent_path}", file=sys.stderr)
        return 2

    intent_text = intent_path.read_text(encoding="utf-8")
    intent = parse_intent(intent_text)
    capsule = expand_intent_to_capsule(intent, task_id=args.task_id, run_id=args.run_id)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(capsule, encoding="utf-8")

    if args.json:
        print(json.dumps({
            "capsule_path": str(out_path),
            "char_count": char_len(capsule),
            "task_id": intent.get("task_id") or "auto-generated",
            "risk": intent.get("risk", "medium"),
            "role": intent.get("role", "builder"),
        }, ensure_ascii=False, indent=2))
    else:
        print(f"Capsule 생성 완료: {out_path}")
        print(f"  문자 수: {char_len(capsule)}")
        print(f"  위험도:  {intent.get('risk', 'medium')}")
        print(f"  역할:    {intent.get('role', 'builder')}")
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    repo = Path(args.repo).resolve()
    intent_path = Path(args.intent)

    if not intent_path.exists():
        print(f"오류: Intent 파일 없음: {intent_path}", file=sys.stderr)
        return 2

    # 1. Intent 파싱 및 Capsule 확장
    intent_text = intent_path.read_text(encoding="utf-8")
    intent = parse_intent(intent_text)
    task_id = args.task_id or f"task_{intent_path.stem}"
    capsule = expand_intent_to_capsule(intent, task_id=task_id, run_id=args.run_id)

    capsule_dir = Path(args.capsule_dir)
    capsule_dir.mkdir(parents=True, exist_ok=True)
    capsule_path = capsule_dir / f"{task_id}.yaml"
    capsule_path.write_text(capsule, encoding="utf-8")

    # 2. 모델 라우팅
    model = args.model
    if model is None:
        try:
            from scripts.orca_model_router import route
            router_result = route(
                capsule_path=capsule_path,
                probe=not args.no_probe,
            )
            if router_result.primary_available:
                model = router_result.primary_model
            elif router_result.fallback_available:
                model = router_result.fallback_model
                print(f"경고: 주 모델 사용 불가, 대체 모델 {model} 사용", file=sys.stderr)
            else:
                model = router_result.primary_model
                print(f"경고: 모델 {model} 사용 불가 상태입니다.", file=sys.stderr)
        except ImportError:
            model = DEFAULT_MODEL

    if args.dry_run:
        if args.json:
            print(json.dumps({
                "dry_run": True,
                "capsule": str(capsule_path),
                "model": model,
                "task_id": task_id,
                "char_count": char_len(capsule),
            }, ensure_ascii=False, indent=2))
        else:
            print(f"[Dry-run] Capsule: {capsule_path}")
            print(f"[Dry-run] Model:   {model}")
            print(f"[Dry-run] 문자 수: {char_len(capsule)}")
        return 0

    # 3. Worktree 생성
    print(f"Worktree 생성 중...")
    try:
        worktree_path, branch_name = create_worktree(repo)
        setup_worktree_env(worktree_path, repo)
        print(f"  Worktree: {worktree_path}")
        print(f"  Branch:   {branch_name}")
    except RuntimeError as exc:
        print(f"오류: {exc}", file=sys.stderr)
        return 2

    # 4. Dispatch
    print(f"Dispatch 중... (model={model})")
    disp_result = dispatch_worker(
        capsule_path=capsule_path,
        worktree_path=worktree_path,
        model=model,
        run_id=args.run_id,
        task_id=task_id,
    )

    if args.json:
        print(json.dumps({
            "capsule": str(capsule_path),
            "worktree": str(worktree_path),
            "branch": branch_name,
            "model": model,
            "task_id": task_id,
            "dispatched": disp_result["dispatched"],
            "method": disp_result["method"],
            "note": disp_result.get("note", ""),
        }, ensure_ascii=False, indent=2))
    else:
        if disp_result["dispatched"]:
            print(f"Dispatch 완료: {disp_result['method']}")
        else:
            print(f"Dispatch 실패: {disp_result.get('note', '알 수 없는 오류')}")
        print(f"  Capsule:  {capsule_path}")
        print(f"  Worktree: {worktree_path}")
        print(f"  Branch:   {branch_name}")

    return 0 if disp_result["dispatched"] else 1


def cmd_finalize(args: argparse.Namespace) -> int:
    report_path = Path(args.report)
    capsule_path = Path(args.capsule)
    repo = Path(args.repo).resolve()
    worktree_path = Path(args.worktree) if args.worktree else None

    for p in (report_path, capsule_path):
        if not p.exists():
            print(f"오류: 파일 없음: {p}", file=sys.stderr)
            return 2

    print("검증 파이프라인 실행 중...")
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
        summ = result.get("summarize", {})
        if isinstance(summ, dict):
            verdict = summ.get("effective_verdict", summ.get("declared_verdict", "?"))
            violations = summ.get("violations_count", 0)
            digest = summ.get("digest", "")
            print(digest if digest else f"요약: verdict={verdict}, violations={violations}")
        else:
            print(f"요약 실패: {summ}")

        level1 = result.get("level1", {})
        if isinstance(level1, dict):
            print(f"\nLevel 1: {level1.get('verdict', '?')}")

        reviewer = result.get("reviewer", {})
        if isinstance(reviewer, dict):
            print(f"Reviewer: {reviewer.get('effective_verdict', reviewer.get('declared_verdict', '?'))}")

    return result["exit_code"]


def cmd_status(args: argparse.Namespace) -> int:
    # Orca CLI 로 상태 조회 시도
    code, stdout, stderr = _run(
        ["orca", "orchestration", "task-list", "--run", args.run_id],
        timeout=10,
    )

    if args.json:
        print(json.dumps({
            "run_id": args.run_id,
            "task_id": args.task_id,
            "orca_available": code == 0,
            "raw": stdout if code == 0 else stderr,
        }, ensure_ascii=False, indent=2))
    else:
        if code == 0:
            print(stdout)
        else:
            print(f"Orca CLI 사용 불가: {stderr.strip()}")
            print("git worktree list 로 수동 확인하십시오:")
            _run(["git", "worktree", "list"])
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "expand":
        return cmd_expand(args)
    if args.command == "dispatch":
        return cmd_dispatch(args)
    if args.command == "finalize":
        return cmd_finalize(args)
    if args.command == "status":
        return cmd_status(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())