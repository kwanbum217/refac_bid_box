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
import os
import re
import subprocess  # nosec B404 - 개발 스크립트가 고정 인자 목록으로만 외부 도구를 호출합니다
import sys
import tempfile
import time
import uuid
from contextlib import suppress
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any

try:
    from scripts.orca_level1_gate import (
        CAP_BACKEND_PYTEST,
        CAP_COMPOSE_CONFIG,
        CAP_DOCKER_BUILD,
        CAP_FRONTEND_BUILD,
        CAP_FRONTEND_TEST,
        CAP_WORKFLOW_LINT,
        parse_verification_command,
        required_capabilities,
    )
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_level1_gate import (
        CAP_BACKEND_PYTEST,
        CAP_COMPOSE_CONFIG,
        CAP_DOCKER_BUILD,
        CAP_FRONTEND_BUILD,
        CAP_FRONTEND_TEST,
        CAP_WORKFLOW_LINT,
        parse_verification_command,
        required_capabilities,
    )

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

try:
    from scripts.orca_model_router import MODEL_POOL, pool_for_model, record_reliability_outcome
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_model_router import MODEL_POOL, pool_for_model, record_reliability_outcome

# ---------------------------------------------------------------------------
# 상수
# ---------------------------------------------------------------------------

CAPSULE_BUDGET = 8000
COMPLEX_CAPSULE_BUDGET = 12000
DEFAULT_MODEL = "gemini-3.7-flash-high"
DEFAULT_RUN_ID = "run_auto"
CAPSULE_VERSION = "2.1.0"
MAX_CONCURRENT_WRITE_WORKERS = 3
ROUTING_STATE_FILENAME = "routing.json"

# 검증 명령 기본값. Capsule 이 선언한 명령을 Level 1 게이트 3 이 그대로 실행하므로
# 여기 적히지 않은 검증은 아무도 실행하지 않습니다. 반대로 변경과 무관한 검증을
# 넣으면 문서만 고친 Task 도 전량 pytest 를 돌립니다. 쓰기 범위 성격에 맞춰 붙입니다.
RULES_VERIFICATION_COMMAND = "python3 scripts/validate_agent_rules.py --quiet"
BACKEND_VERIFICATION_COMMAND = "uv run pytest tests/ -q -m 'not data_assets'"
DEFAULT_VERIFICATION_COMMANDS = [BACKEND_VERIFICATION_COMMAND, RULES_VERIFICATION_COMMAND]

# 검증 능력과 그것을 덮는 명령의 대응. 순서가 Capsule 에 적히는 순서입니다.
# docker_build 는 빌드 컨텍스트별로 갈리므로 여기 두지 않고 따로 만듭니다.
CAPABILITY_COMMANDS = [
    (CAP_BACKEND_PYTEST, BACKEND_VERIFICATION_COMMAND),
    (CAP_FRONTEND_TEST, "npm --prefix frontend run test"),
    (CAP_FRONTEND_BUILD, "npm --prefix frontend run build"),
    (CAP_COMPOSE_CONFIG, "docker compose config -q"),
    (CAP_WORKFLOW_LINT, "uv run actionlint"),
]


def _docker_build_command(capability: str) -> str:
    """`docker_build:<context>` 능력을 덮는 빌드 명령을 만듭니다.

    컨텍스트마다 이미지가 다르므로 태그도 나눕니다. 루트 빌드 하나로 모든
    Dockerfile 을 덮으면 루트 `.dockerignore` 가 제외한 경로는 검증되지 않습니다.
    """
    context = capability.split(":", 1)[1]
    slug = "root" if context == "." else context.replace("/", "-")
    return f"docker build -t refac-bid-box-{slug}:orca-gate {context}"


# docker 를 점유하는 검증을 붙이면서 공유 자원 선언을 빼면, 세 워커가 동시에
# 같은 daemon 과 빌드 캐시를 쓰게 됩니다. 검증 부착과 자원 선언은 같은 판정에서
# 함께 나와야 합니다. resource 와 ownership 값은 Capsule v2 규약의 열거형입니다.
BASE_SHARED_RESOURCES = [("features_py", "read_only")]

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
{ground_truth}

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
{shared_resources}

required_change:
{required_change}

acceptance:
{acceptance}

verification_commands:
{verification_commands}

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
{report_schema}"""

REVIEW_REPORT_SCHEMA = """report_schema:
  schema: "ORCA_REVIEW_DONE_V2"
  version: "2.1.0"
  verdict: "pass 또는 fail 문자열 하나. 객체나 배열로 쓰지 않는다"
  checklist_results: "배열. 각 항목은 id, answer, evidence 키를 가진다. checklist 라는 이름을 쓰지 않는다"
  blocking_issues: "배열. 결함 항목마다 id, file, description"
  unverified_claims: "배열"
  missing_tests: "배열"
"""

# 아래 키 목록은 scripts/summarize_worker_done.py 의 REQUIRED_FIELDS 와 일치해야
# 합니다. 어긋나면 워커가 지시를 정확히 따를수록 검증기에서 필수 필드 누락으로
# 거부됩니다. tests/test_orca_taskctl.py 가 이 일치를 강제합니다.
WORKER_REPORT_SCHEMA = """report_schema:
  schema: "ORCA_WORKER_DONE_V2"
  version: "2.1.0"
  task_id: "위 task_id 를 그대로 적는다"
  status: "succeeded 또는 escalation 문자열 하나"
  branch: "작업한 브랜치 이름"
  commit: "마지막 커밋 SHA. 커밋이 없으면 빈 문자열"
  commit_count: "정수. 0 이면 status 를 escalation 으로 쓴다"
  changed_files: "배열. 실제로 커밋한 파일 경로"
  read_files: "배열. 실제로 읽은 파일 경로"
  verification: "배열. 각 항목은 command 와 result 키를 가진다"
  verdict: "candidate 또는 blocked 문자열 하나"
  blocking_issues: "배열. 차단 사유가 없으면 빈 배열"
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
        proc = subprocess.run(  # nosec B603 - shell 없이 고정 인자 목록으로 호출합니다
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


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def _start_reliability_tracking(
    capsule_path: Path,
    task_id: str,
    model: str,
    started_at: float,
) -> dict[str, Any]:
    """무료 풀 Dispatch의 모델·역할·시작 시각을 Finalize용으로 보존합니다."""
    pool_name = pool_for_model(model)
    if pool_name is None or MODEL_POOL[pool_name]["tier"] != "free":
        return {"status": "skipped", "reason": "not_free_pool"}

    role = parse_capsule_scalar(capsule_path.read_text(encoding="utf-8"), "role") or "builder"
    state = {
        "schema": "ORCA_RELIABILITY_DISPATCH_V1",
        "task_id": task_id,
        "pool": pool_name,
        "role": role,
        "started_at": started_at,
        "observation_id": f"{task_id}:{started_at}",
    }
    state_path = capsule_path.parent / ROUTING_STATE_FILENAME
    _write_json_atomic(state_path, state)
    return {"status": "tracking", "pool": pool_name, "role": role, "path": str(state_path)}


def _record_finalize_reliability(
    capsule_path: Path,
    result: dict[str, Any],
) -> dict[str, Any]:
    """검증 성공·실패를 한 번만 rolling reliability 이력에 반영합니다."""
    state_path = capsule_path.parent / ROUTING_STATE_FILENAME
    if not state_path.exists():
        return {"status": "skipped", "reason": "tracking_state_missing"}
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {"status": "error", "reason": f"tracking_state_invalid: {exc}"}
    if not isinstance(state, dict):
        return {"status": "error", "reason": "tracking_state_not_object"}
    if state.get("recorded_at"):
        return {
            "status": "already_recorded",
            "pool": state.get("pool"),
            "role": state.get("role"),
        }

    exit_code = int(result.get("exit_code", 2))
    if exit_code not in (0, 1):
        return {"status": "skipped", "reason": "verification_inconclusive"}

    pool_name = str(state.get("pool") or "")
    role = str(state.get("role") or "")
    if pool_name not in MODEL_POOL or MODEL_POOL[pool_name]["tier"] != "free" or not role:
        return {"status": "error", "reason": "tracking_identity_invalid"}

    started_at = state.get("started_at")
    elapsed_sec = None
    if isinstance(started_at, (int, float)):
        elapsed_sec = max(0, int(time.time() - started_at))
    ok = exit_code == 0
    record_reliability_outcome(
        pool_name,
        role,
        ok=ok,
        failure=None if ok else "verification_failed",
        elapsed_sec=elapsed_sec,
        observation_id=str(state.get("observation_id") or "") or None,
    )
    state["recorded_at"] = time.time()
    state["outcome"] = "succeeded" if ok else "failed"
    _write_json_atomic(state_path, state)
    return {"status": "recorded", "pool": pool_name, "role": role, "ok": ok}


def _uses_docker(capabilities: set[str]) -> bool:
    """docker daemon 을 점유하는 능력이 있는지 봅니다."""
    return any(
        capability == CAP_COMPOSE_CONFIG or capability.startswith(f"{CAP_DOCKER_BUILD}:")
        for capability in capabilities
    )


def resolve_shared_resources(
    write_files: list[str],
    verification_commands: list[str] | None = None,
) -> list[tuple[str, str]]:
    """점유하는 공유 자원과 소유권 수준을 정합니다.

    docker 검증이 붙는 Task 는 docker 를 배타 점유합니다. 스킬 문서는 이를
    요구하는데 템플릿은 features_py 만 고정으로 적고 있었습니다.

    쓰기 범위뿐 아니라 실제로 실행할 검증 명령도 봅니다. Intent 가 docker 명령을
    직접 적고 쓰기 범위에는 파이썬 파일만 두면, 범위만 보는 판정은 점유를
    놓칩니다.
    """
    paths = [str(path).strip() for path in write_files if str(path).strip()]
    capabilities = set(required_capabilities(paths))
    for command in verification_commands or []:
        try:
            capabilities |= set(parse_verification_command(command).provides)
        except ValueError:
            # 허용 목록 밖 명령은 게이트 3 이 거부합니다. 여기서는 무시합니다.
            continue

    resources = list(BASE_SHARED_RESOURCES)
    if _uses_docker(capabilities):
        resources.append(("docker", "exclusive"))
    return resources


def _format_shared_resources(resources: list[tuple[str, str]]) -> str:
    """shared_resources 를 Capsule YAML 블록으로 포맷합니다."""
    lines = []
    for resource, ownership in resources:
        lines.append(f"  - resource: {resource}")
        lines.append(f"    ownership: {ownership}")
    return "\n".join(lines)


def resolve_verification_commands(
    intent: dict[str, Any],
    write_files: list[str],
) -> list[str]:
    """Task Intent 와 쓰기 범위로부터 Capsule 의 verification_commands 를 정합니다.

    Intent 가 명시하면 그것을 씁니다. 종전에는 템플릿에 backend pytest 두 줄이
    박혀 있어 Intent 가 무엇을 적든 무시됐습니다. 명시가 없으면 쓰기 범위가
    요구하는 검증 능력을 게이트와 같은 함수로 구해 그 능력을 덮는 명령만
    붙입니다. 판정 기준을 따로 구현하면 Capsule 이 붙이지 않은 검증을 게이트가
    요구하는, 통과 불가능한 Task 가 생깁니다. 문서만 고치는 Task 에 전량
    pytest 가 붙던 것도 이 기준을 쓰지 않았기 때문입니다.
    """
    declared = [str(item).strip() for item in intent.get("verification_commands", [])]
    if declared:
        return list(dict.fromkeys(item for item in declared if item))

    paths = [str(path).strip() for path in write_files if str(path).strip()]
    needed = required_capabilities(paths)
    commands = [command for capability, command in CAPABILITY_COMMANDS if capability in needed]
    commands += [
        _docker_build_command(capability)
        for capability in sorted(needed)
        if capability.startswith(f"{CAP_DOCKER_BUILD}:")
    ]
    commands.append(RULES_VERIFICATION_COMMAND)
    return list(dict.fromkeys(commands))


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
            base = path_str[: -len(suffix)]
            return f"{base}/**"
    return path_str


def _strip_leading_dot_slash(value: str) -> str:
    """선행 `./` 만 제거합니다. `.env` 같은 dotfile 은 그대로 둡니다."""
    while value.startswith("./"):
        value = value[2:]
    return value.lstrip("/") if value.startswith("/") else value


def validate_contained_path(path_str: str | Path, field_name: str = "경로") -> str:
    """경로가 워크트리 내부 상대 경로인지 검증합니다.

    절대경로(POSIX /, Windows C:, UNC //), 상위 디렉터리 탈출(..),
    홈 디렉터리(~) 참조를 fail-closed 로 거부합니다.
    """
    raw = str(path_str).strip()
    if not raw:
        raise ValueError(f"{field_name} 에 빈 경로는 허용되지 않습니다.")

    normalized = raw.replace("\\", "/")

    # 1. 절대경로, UNC, 드라이브 레터, 홈 디렉터리 접두사 거부
    if (
        normalized.startswith("/")
        or normalized.startswith("//")
        or raw.startswith("\\")
        or raw.startswith("\\\\")
        or bool(re.match(r"^[a-zA-Z]:", raw))
        or raw.startswith("~")
        or PurePosixPath(normalized).is_absolute()
        or PureWindowsPath(raw).is_absolute()
        or PureWindowsPath(raw).drive != ""
    ):
        raise ValueError(f"{field_name} 에 절대경로는 허용되지 않습니다: {raw}")

    # 2. 상위 디렉터리 탐색(..) 거부
    parts = normalized.split("/")
    if ".." in parts:
        raise ValueError(f"{field_name} 에 상위 디렉터리 탐색(..)은 허용되지 않습니다: {raw}")

    # 3. 선행 ./ 제거 후 빈 문자열 거부
    cleaned = _strip_leading_dot_slash(normalized)
    if not cleaned:
        raise ValueError(f"{field_name} 에 빈 경로는 허용되지 않습니다: {raw}")

    return raw


# ---------------------------------------------------------------------------
# Task Intent 파싱
# ---------------------------------------------------------------------------


BASE_GROUND_TRUTH: tuple[tuple[str, str], ...] = (
    ("G1 데이터 무손실: DB 스키마 및 행 수 100% 보존", "docs/context/CURRENT_STATE.md"),
    ("Train/Serve 특징 단일화: src/ml/features.py 만 사용", "src/ml/features.py"),
    ("1인 작업: Pull Request 생성 금지, main 직접 커밋 금지", "AGENTS.md"),
)


def _format_ground_truth(extra_facts: list[str]) -> str:
    """기본 사실 3건 뒤에 Intent 가 주입한 사실을 덧붙입니다.

    코디네이터가 이미 확인한 경계 조건을 사실로 못박지 않으면 워커가 같은
    것을 다시 조사하거나, 조사하지 않고 잘못된 가정으로 고칩니다.
    """
    lines = []
    for fact, evidence in BASE_GROUND_TRUTH:
        lines.append(f'  - fact: "{_escape(fact)}"')
        lines.append(f'    evidence: "{_escape(evidence)}"')
        lines.append("    recheck: false")
    for fact in extra_facts:
        lines.append(f'  - fact: "{_escape(fact)}"')
        lines.append('    evidence: "코디네이터 확인 사실"')
        lines.append("    recheck: false")
    return "\n".join(lines)


def _escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


def parse_intent(text: str) -> dict[str, Any]:
    """Task Intent YAML 을 정규식 기반으로 파싱합니다."""
    result: dict[str, Any] = {
        "schema": "ORCA_TASK_INTENT_V1",
        "role": "builder",
        "objective": "",
        "scope": [],
        "read_scope": [],
        "acceptance": [],
        "risk": "medium",
        "context": "",
        "ground_truth": [],
        "required_change": [],
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

            if key in ("scope", "read_scope", "acceptance", "ground_truth", "required_change"):
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

    for item in result.get("scope", []):
        validate_contained_path(item, field_name="scope")
    for item in result.get("read_scope", []):
        validate_contained_path(item, field_name="read_scope")
    if result.get("report_path"):
        validate_contained_path(result["report_path"], field_name="report_path")

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
    # 리뷰어는 판정만 하므로 쓰기 범위가 없습니다. scope 는 검토 대상이라 읽기로만
    # 갑니다. 예전에는 scope 가 그대로 쓰기 범위가 되어 리뷰어에게 검토 대상을
    # 고칠 권한이 열렸습니다.
    if is_reviewer:
        write_files: list[str] = []
    else:
        write_files = list(scope) if scope else ["src/...", "tests/..."]

    for path_item in write_files:
        validate_contained_path(path_item, field_name="scope")

    # 템플릿이 artifact_paths 로 지시하는 분석 문서 경로를 쓰기 범위에 함께 넣습니다.
    # 넣지 않으면 워커가 템플릿을 따라 만든 산출물이 Level 1 범위 게이트에서
    # 초과로 거부됩니다 (반복 금지 4.7.2). 리뷰어는 문서를 쓰지 않으므로 제외합니다.
    analysis_artifact = f"docs/analysis/{task_id}.md"
    if not is_reviewer and analysis_artifact not in write_files:
        write_files.append(analysis_artifact)

    # 읽기만 필요한 경로. 감사나 조사 작업은 대상 파일을 읽어야 하지만 고쳐서는
    # 안 됩니다. read_scope 가 없으면 대상을 scope 에 넣어야 하고 그러면 쓰기까지
    # 열려 범위 게이트가 무단 수정을 잡지 못합니다.
    extra_read = [str(item) for item in intent.get("read_scope", []) if str(item).strip()]
    for path_item in extra_read:
        validate_contained_path(path_item, field_name="read_scope")
    if is_reviewer:
        extra_read = list(scope) + extra_read

    self_capsule_str = (
        worktree_relative_capsule_path(Path(capsule_path))
        if capsule_path
        else f".orca/capsules/{task_id}/capsule.yaml"
    )
    validate_contained_path(self_capsule_str, field_name="capsule_path")
    reference_files = [self_capsule_str, "docs/context/CURRENT_STATE.md"]
    read_files = list(dict.fromkeys(reference_files + write_files + extra_read))

    allowed_read_formatted = _format_yaml_list(read_files)
    allowed_write_formatted = _format_yaml_list(write_files)

    globs = [_to_glob(s) for s in list(dict.fromkeys(write_files + extra_read))]
    allowed_globs_formatted = _format_yaml_list(globs, indent="    - ")

    # required_change
    req_items = [str(item) for item in intent.get("required_change", []) if str(item).strip()]
    if not req_items:
        req_items = [objective[:120]] if objective else ["(작업 목표 참조)"]
    required_change_formatted = _format_yaml_list(req_items)

    # acceptance
    acc_items = list(acceptance) if acceptance else ["테스트 통과", "규칙 검증 통과"]
    acceptance_formatted = _format_yaml_list(acc_items)

    # artifact_paths & report_path
    if is_reviewer:
        report_path = str(intent.get("report_path") or f".orca/capsules/{task_id}/review_done.json")
        validate_contained_path(report_path, field_name="report_path")
        return_contract = "ORCA_REVIEW_DONE_V2"
        mode = "reviewer"
        artifact_paths_formatted = _format_yaml_list([report_path])
    else:
        report_path = str(intent.get("report_path") or f".orca/capsules/{task_id}/worker_done.json")
        validate_contained_path(report_path, field_name="report_path")
        return_contract = "ORCA_WORKER_DONE_V2"
        mode = intent.get("mode", "worker")
        artifact_paths_formatted = _format_yaml_list([f"docs/analysis/{task_id}.md"])

    # 계약 이름만 적으면 스키마를 모르는 모델이 필드명을 제 마음대로 바꿉니다.
    # 2026-08-17 측정에서 Claude 계열 워커 2대가 checklist_results 대신 checklist 를
    # 쓰고 verdict 를 객체로 냈습니다. 기계 집계가 깨지므로 필드명을 열거합니다.
    report_schema = REVIEW_REPORT_SCHEMA if is_reviewer else WORKER_REPORT_SCHEMA

    verification_commands = resolve_verification_commands(intent, write_files)

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
        ground_truth=_format_ground_truth(
            [str(item) for item in intent.get("ground_truth", []) if str(item).strip()]
        ),
        required_change=required_change_formatted,
        acceptance=acceptance_formatted,
        shared_resources=_format_shared_resources(
            resolve_shared_resources(write_files, verification_commands)
        ),
        verification_commands=_format_yaml_list(verification_commands),
        artifact_paths=artifact_paths_formatted,
        report_path=report_path,
        return_contract=return_contract,
        report_schema=report_schema,
    )

    if review_checklist:
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


def _launch_succeeded(stdout: str, expect_json: bool = False) -> bool:
    """종료 코드 0 이어도 ok 가 false 인 응답을 성공으로 보지 않습니다.

    `--json` 을 붙여 호출한 명령은 JSON 을 돌려주기로 되어 있습니다. 그런데도
    파싱되지 않거나 비어 있으면 응답을 판정할 수 없는 상태이며, 이를 성공으로
    보면 미확인이 SUCCESS 로 승격됩니다. `expect_json` 은 그 경우를 실패로
    돌립니다. JSON 을 요구하지 않은 호출은 사람이 읽는 출력이 정상이므로
    종전대로 관대하게 봅니다.
    """
    if not stdout or not stdout.strip():
        return not expect_json
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return not expect_json
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


TRUST_PROMPT_MARKERS: tuple[str, ...] = (
    "trust the contents",
    "i trust this folder",
    "do you trust",
)


def terminal_tail(handle: str, timeout: int = 30) -> str | None:
    """터미널의 최근 출력을 읽습니다. 조회에 실패하면 None 을 돌려줍니다."""
    cmd = ["orca", "terminal", "show", "--terminal", handle, "--json"]
    code, stdout, _stderr = _run_command(cmd, timeout=timeout)
    if code != 0 or not stdout.strip():
        return None
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("ok") is False:
        return None
    terminal = (payload.get("result") or {}).get("terminal") or {}
    text = terminal.get("tail") or terminal.get("preview") or ""
    return str(text)


def has_trust_prompt(text: str) -> bool:
    """워크스페이스 신뢰 확인 대화창이 떠 있는지 판정합니다."""
    lowered = text.lower()
    return any(marker in lowered for marker in TRUST_PROMPT_MARKERS)


# opencode TUI 는 입력 프롬프트를 단독 `>` 로 그리지 않고 하단 상태줄에 조작
# 안내를 남깁니다. 이 표지를 모르면 opencode 워커가 항상 대기 시간을 다
# 소진한 뒤 not_settled 로 판정됩니다. 2026-08-19 Dispatch 3회가 전부
# 그렇게 오탐이었습니다.
AGENT_READY_MARKERS = (
    "esc interrupt",
    "ctrl+p commands",
    "shift+tab",
)


# 상태줄 표지는 TUI 가 그려지자마자 나타나므로, 백엔드가 아직 연결 중이어도
# 준비로 보입니다. 그 상태로 주입하면 지시가 삼켜집니다. 2026-08-19 에 opencode
# 워커가 실제로 이렇게 지시를 잃었습니다. 표지가 이 시간만큼 계속 보여야
# 준비로 인정합니다. 단독 `>` 프롬프트는 입력 대기가 확실하므로 즉시 인정합니다.
AGENT_READY_SETTLE_SECONDS = 6


def agent_prompt_ready(text: str) -> bool:
    """CLI 입력 프롬프트가 준비된 상태인지 판정합니다.

    Antigravity CLI 는 배너를 그린 뒤 마지막 줄에 단독 `>` 를 남깁니다.
    작업 중이면 진행 표시가 남으므로 준비로 보지 않습니다. opencode 는
    `>` 대신 하단 상태줄 표지로 판정합니다.
    """
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    if lines and lines[-1] == ">":
        return True
    lowered = text.lower()
    return any(marker in lowered for marker in AGENT_READY_MARKERS)


def agent_prompt_is_input_caret(text: str) -> bool:
    """단독 `>` 입력 프롬프트인지 판정합니다. 이 형태는 즉시 준비로 봅니다."""
    lines = [line.rstrip() for line in text.splitlines() if line.strip()]
    return bool(lines) and lines[-1] == ">"


def instruction_observed(text: str, markers: list[str]) -> bool:
    """주입한 지시가 터미널에 실제로 도달했는지 판정합니다."""
    if not markers:
        return False
    lowered = text.lower()
    return any(marker.lower() in lowered for marker in markers if marker)


def verify_instruction_delivered(
    handle: str,
    markers: list[str],
    timeout: int = 30,
    wait_seconds: int = 30,
    poll_seconds: float = 1.0,
) -> str:
    """Dispatch 이후 지시가 워커 터미널에 도달했는지 확인합니다.

    Dispatch 전의 준비 상태 판정만으로 전달 실패를 단정하면 오탐이 납니다.
    CLI 가 아직 뜨는 중이어도 주입은 큐에 남아 정상 도달하기 때문입니다.
    실제 도달 여부는 주입한 문자열이 화면에 나타나는지로만 알 수 있습니다.

    **폴링은 촘촘해야 합니다.** 표지는 터미널 뷰포트에 잠깐 머물다 워커가
    출력을 쏟아내면 밀려납니다. 2026-08-19 실측에서 3초 간격으로는 Gemini 워커의
    표지를 놓쳐 도달했는데도 not_observed 로 판정했습니다.

    반환값: delivered | not_observed | unreadable
    """
    deadline = time.monotonic() + max(0, wait_seconds)
    unreadable_only = True
    while True:
        text = terminal_tail(handle, timeout=timeout)
        if text is not None:
            unreadable_only = False
            if instruction_observed(text, markers):
                return "delivered"
        if time.monotonic() >= deadline:
            return "unreadable" if unreadable_only else "not_observed"
        time.sleep(max(0.2, poll_seconds))


def start_auto_approve(terminal: str) -> tuple[bool, str]:
    """워커 터미널에 권한 프롬프트 자동 승인 감시기를 배경으로 붙인다.

    붙이지 않으면 셸 명령 승인 대화창마다 워커가 멈춘다. shift+tab(accept-edits)은
    파일 편집만 자동 승인하므로 명령 대화창은 이 감시기가 없으면 사람이 눌러야 한다.
    """
    script = Path(__file__).resolve().parent / "orca_auto_approve.py"
    if not script.exists():
        return False, f"자동 승인 감시기를 찾지 못했습니다: {script}"
    log_dir = Path(tempfile.gettempdir()) / "orca_auto_approve"
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        log_path = log_dir / f"{terminal}.log"
        with log_path.open("ab") as log_file:
            subprocess.Popen(  # nosec B603  고정된 스크립트 경로와 터미널 핸들만 넘깁니다
                [sys.executable, str(script), terminal],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
    except OSError as exc:
        return False, f"자동 승인 감시기 기동 실패: {exc}"
    return True, str(log_path)


def approve_trust_prompt(
    handle: str,
    attempts: int = 2,
    timeout: int = 30,
    wait_seconds: int = 40,
    poll_seconds: int = 2,
) -> str:
    """신뢰 확인 대화창이 뜨면 승인합니다. 뜰 때까지 기다립니다.

    Antigravity CLI 는 새 워크트리마다 신뢰 확인 대화창을 띄웁니다. 그 상태로
    지시를 보내면 대화창이 입력을 삼켜 워커가 작업을 시작하지 못합니다.
    2026-08-17 에 Capsule 고지문이 이렇게 소실됐습니다. 기본 선택이 신뢰이므로
    빈 텍스트에 Enter 만 보내면 승인됩니다.

    **기동 직후에 한 번만 보고 판정하면 안 됩니다.** CLI 가 아직 부팅 중이면
    대화창이 없어 통과시키고, 그 직후 대화창이 떠서 지시를 먹습니다. 대화창이
    뜨거나 입력 프롬프트가 준비될 때까지 기다립니다.

    반환값: not_present | approved | still_present | unreadable | not_settled
    """
    deadline = time.monotonic() + max(0, wait_seconds)
    ready_since: float | None = None
    while True:
        text = terminal_tail(handle, timeout=timeout)
        if text is None:
            return "unreadable"

        if has_trust_prompt(text):
            for _ in range(max(1, attempts)):
                terminal_send(handle, "", timeout=timeout)
                after = terminal_tail(handle, timeout=timeout)
                if after is None:
                    return "unreadable"
                if not has_trust_prompt(after):
                    return "approved"
            return "still_present"

        if agent_prompt_ready(text):
            if agent_prompt_is_input_caret(text):
                return "not_present"
            # 상태줄 표지만 본 경우입니다. 백엔드가 아직 연결 중일 수 있으므로
            # 표지가 계속 보이는지 확인한 뒤에 준비로 인정합니다.
            if ready_since is None:
                ready_since = time.monotonic()
            elif time.monotonic() - ready_since >= AGENT_READY_SETTLE_SECONDS:
                return "not_present"
        else:
            ready_since = None

        if time.monotonic() >= deadline:
            return "not_settled"
        time.sleep(max(1, poll_seconds))


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


DELIVERY_PROBE_PREFIX = "ORCA_DELIVERY_PROBE_"


def new_delivery_probe() -> str:
    """이번 Dispatch 만 식별하는 도달 증명 표지를 만듭니다.

    task_id 나 Capsule 경로로 도달을 판정하면, 같은 Task 를 재 Dispatch 할 때
    화면에 남아 있는 이전 시도의 잔상이 그대로 통과합니다. 실제로는 지시가
    도달하지 않았는데 성공으로 보고되므로 fail-open 입니다. 매 시도마다 새
    표지를 만들어 그것만 찾습니다.
    """
    return f"{DELIVERY_PROBE_PREFIX}{uuid.uuid4().hex[:12]}"


def worktree_relative_capsule_path(capsule_path: Path) -> str:
    """워커에게 줄 Capsule 경로를 워크트리 상대 경로로 바꿉니다.

    절대 경로를 주면 워커가 그 경로의 저장소로 `cd` 해서 일합니다. 2026-08-23 에
    워커 4대가 이 경로를 보고 주 저장소로 이동했고, 그중 하나는 거기서 브랜치까지
    만들어 코디네이터의 병합 2건이 엉뚱한 브랜치에 쌓였습니다. Capsule 은 각
    워크트리에 같은 상대 경로로 복사되므로 상대 경로가 어느 트리에서나 맞습니다.
    """
    parts = capsule_path.parts
    if ".orca" in parts:
        # Capsule 경로는 YAML 에 적혀 어느 플랫폼에서든 같은 문자열로 대조되므로
        # 구분자를 POSIX 로 고정합니다. Windows 에서 str(Path(...)) 는 역슬래시를
        # 내어 워커와 게이트가 같은 경로를 다른 문자열로 읽습니다.
        return Path(*parts[parts.index(".orca") :]).as_posix()
    return capsule_path.name


def build_capsule_notice(
    capsule_path: Path,
    report_path: str | None = None,
    dispatch_id: str | None = None,
    delivery_probe: str | None = None,
    worktree_path: str | None = None,
) -> str:
    """Capsule 정본 경로 고지문을 만듭니다.

    `dispatch --inject` 는 Orca Task 의 spec 만 주입하며 Capsule 경로도 내용도
    전달하지 않습니다. 이 고지문 없이는 워커가 한두 문장 요약만 보고 일하며,
    2026-08-17 에 워커 3대 전부가 파일명과 보고 계약을 위반했습니다.

    경로는 반드시 워크트리 상대 경로로 줍니다. 절대 경로를 주면 워커가 그
    저장소로 이동합니다 (2026-08-23, `worktree_relative_capsule_path` 참조).
    """
    relative_capsule = worktree_relative_capsule_path(capsule_path)
    validate_contained_path(relative_capsule, field_name="capsule_path")
    parts = [
        f"정본 사양은 현재 작업 디렉터리 기준 {relative_capsule} 입니다.",
        "지금 그 파일을 읽고 이 작업의 유일한 정본으로 삼으십시오.",
        "현재 작업 디렉터리가 당신의 격리 작업 트리입니다. 절대 벗어나지 마십시오.",
        "cd 로 다른 저장소로 이동하지 말고 모든 경로를 상대 경로로 다루십시오.",
        "objective, acceptance, allowed_write_files, forbidden 을 그대로 지킵니다.",
        "allowed_write_files 에 없는 파일명을 새로 만들지 마십시오.",
        "README, AGENTS.md, SKILLS.md, 설계서는 읽지 않습니다.",
        "코드 변경 작업은 커밋해야 완료입니다. commit_count 가 0 이면 succeeded 대신 escalation 을 보냅니다.",
    ]
    if worktree_path:
        parts.insert(
            2,
            f"당신의 작업 트리는 {worktree_path} 이며 그 밖의 파일을 읽거나 쓰면 계약 위반입니다.",
        )
    if report_path:
        validate_contained_path(report_path, field_name="report_path")
        parts.append(f"보고 JSON 은 {report_path} 에 ORCA_WORKER_DONE_V2 계약으로 씁니다.")
    if dispatch_id:
        parts.append(f"worker_done 전송 시 dispatchId 는 {dispatch_id} 입니다.")
    if delivery_probe:
        # 코디네이터가 이번 시도의 도달을 확인하는 표지입니다. 워커는 아무
        # 조치도 하지 않아도 되며, 화면에 남는 것만으로 목적을 다합니다.
        parts.append(f"(전달 확인 표지: {delivery_probe} - 별도 조치 불필요)")
    return " ".join(parts)


def bare_directory_write_scopes(allowed_write: list[str], repo_root: Path) -> list[str]:
    """하위를 포함하지 못하는 디렉터리 항목을 찾아냅니다.

    `matches_any` 는 `src/app/static` 을 그 경로 하나로만 봅니다. 하위까지
    허용하려면 `src/app/static/...` 으로 적어야 하는데, 디렉터리 이름만 쓰면
    선언은 통과하고 게이트 2 에서만 터집니다. 2026-08-25 에 CDN 자산 로컬화
    Task 가 이 형태로 26건을 범위 초과로 맞았습니다. 워커 산출물은 의도 안에
    있었고 Capsule 표기만 틀린 경우였습니다.
    """
    suspicious: list[str] = []
    for entry in allowed_write:
        cleaned = entry.strip().rstrip("/")
        if not cleaned or cleaned.endswith(("...", "**", "*")):
            continue
        if (repo_root / cleaned).is_dir():
            suspicious.append(cleaned)
    return suspicious


def build_task_spec(objective: str, capsule_path: Path) -> str:
    """Orca Task 의 spec 에 Capsule 의 워크트리 상대 경로를 함께 넣습니다.

    spec 은 `dispatch --inject` 가 워커에게 실제로 전달하는 유일한 본문입니다.
    경로를 여기에 넣으면 워커가 첫 턴부터 정본을 찾을 수 있습니다.

    절대 경로를 넣으면 안 됩니다. 워커는 spec 을 가장 먼저 읽고 그 경로가 가리키는
    저장소로 이동합니다 (2026-08-23 사고, `worktree_relative_capsule_path` 참조).
    """
    summary = objective.strip().replace("\n", " ")
    if char_len(summary) > 400:
        summary = truncate(summary, 400)
    relative_capsule = worktree_relative_capsule_path(capsule_path)
    validate_contained_path(relative_capsule, field_name="capsule_path")
    return (
        f"{summary} 정본 사양(Capsule): 현재 작업 디렉터리의 {relative_capsule}. "
        "현재 작업 디렉터리를 벗어나지 마십시오."
    )


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
    strict: bool = True,
    max_diff_chars: int | None = None,
    allow_truncated_diff: bool = False,
) -> dict[str, Any]:
    """worker_done 보고를 검증하고 Level 1/Reviewer 검증 파이프라인을 실행합니다."""
    scripts_dir = Path(__file__).resolve().parent
    result: dict[str, Any] = {
        "execution_mode": "strict" if strict else "allow_skipped_gates",
        "source_branch": branch,
        "target_branch": base,
        "commit": None,
        "target_commit": None,
        "summarize": None,
        "level1": None,
        "reviewer": None,
        "exit_code": 0,
    }

    tool_error = False
    gate_fail = False
    target_repo = worktree_path if worktree_path else repo

    # Level 1 은 리뷰어보다 먼저 돌므로 그 시점에는 리뷰 보고서가 존재할 수
    # 없습니다. 그래서 게이트 5 는 이 호출의 적용 대상이 아니며, 리뷰 계약은
    # 뒤이어 도는 orca_run_reviewer 가 같은 evaluate() 로 판정합니다.
    # 따라서 strict 인데 리뷰어를 돌리지 않으면 리뷰가 통째로 빠집니다.
    # 병합 판정에 쓰는 호출이므로 조용히 통과시키지 않고 거부합니다.
    if strict and not run_reviewer:
        result["level1"] = {
            "error": (
                "strict 모드는 리뷰 검증을 포함해야 합니다. --reviewer 를 함께 지정하거나 "
                "--allow-skipped-gates 로 strict 를 끄십시오."
            ),
            "exit_code": 2,
        }
        result["exit_code"] = 2
        return result

    # 1. summarize_worker_done.py 실행
    summarize_cmd = [
        sys.executable,
        str(scripts_dir / "summarize_worker_done.py"),
        "--report",
        str(report_path),
        "--capsule",
        str(capsule_path),
        "--repo",
        str(target_repo),
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
    # 명시된 작업 트리가 없으면 검증 대상이 없는 것입니다. 주 저장소로 대체하면
    # 워커 변경분 대신 깨끗한 기본 저장소를 검사해 통과가 조작됩니다.
    if worktree_path is not None and not worktree_path.exists():
        result["level1"] = {
            "error": f"지정된 작업 트리가 없습니다: {worktree_path}",
            "exit_code": 2,
        }
        result["exit_code"] = 2
        return result

    # 검증 명령은 게이트가 Capsule 에서 직접 읽습니다. 여기서 pytest 만 뽑아
    # 넘기던 종전 방식은 npm 등 나머지 검증을 조용히 버렸습니다.
    commit_cmd = ["git", "rev-parse", "--verify", f"{branch}^{{commit}}"]
    code_commit, stdout_commit, stderr_commit = _run_command(
        commit_cmd, cwd=target_repo, timeout=30
    )
    if code_commit != 0 or not stdout_commit.strip():
        result["commit_error"] = truncate(
            stderr_commit.strip() or "검증 대상 commit을 확인할 수 없습니다.", 200
        )
        result["exit_code"] = 2
        return result
    result["commit"] = stdout_commit.strip()

    target_commit_cmd = ["git", "rev-parse", "--verify", f"{base}^{{commit}}"]
    code_target_commit, stdout_target_commit, stderr_target_commit = _run_command(
        target_commit_cmd, cwd=target_repo, timeout=30
    )
    if code_target_commit != 0 or not stdout_target_commit.strip():
        result["target_commit_error"] = truncate(
            stderr_target_commit.strip() or "검증 대상 target commit을 확인할 수 없습니다.", 200
        )
        result["exit_code"] = 2
        return result
    result["target_commit"] = stdout_target_commit.strip()

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
        "--report",
        str(report_path),
        "--json",
    ]
    if strict:
        level1_cmd.append("--strict")
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

    # summarize 결과의 changed_files 와 Level 1 게이트 1 의 git diff 결과 대조
    if isinstance(result.get("summarize"), dict) and isinstance(result.get("level1"), dict):
        summ_data = result["summarize"]
        l1_data = result["level1"]
        summ_changed = summ_data.get("changed_files")
        l1_gates = l1_data.get("gates", {})
        l1_gate1 = l1_gates.get("gate1_changed_files", {})
        l1_changed = l1_gate1.get("changed_files")
        if isinstance(summ_changed, list) and isinstance(l1_changed, list):
            norm_summ = {
                p.strip().lstrip("./").lstrip("/")
                for p in summ_changed
                if isinstance(p, str) and p.strip()
            }
            norm_l1 = {
                p.strip().lstrip("./").lstrip("/")
                for p in l1_changed
                if isinstance(p, str) and p.strip()
            }
            if norm_summ != norm_l1:
                gate_fail = True
                missing = sorted(norm_l1 - norm_summ)
                phantom = sorted(norm_summ - norm_l1)
                result["changed_files_mismatch"] = {
                    "error": "worker_done 보고의 changed_files 가 실제 git diff 와 일치하지 않습니다.",
                    "missing_in_report": missing,
                    "phantom_in_report": phantom,
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
            "--diff-base",
            base,
            "--diff-branch",
            branch,
            "--repo",
            str(target_repo),
            "--model",
            reviewer_model,
            "--json",
        ]
        if max_diff_chars is not None:
            reviewer_cmd += ["--max-diff-chars", str(max_diff_chars)]
        if allow_truncated_diff:
            reviewer_cmd.append("--allow-truncated-diff")
        code_rev, stdout_rev, stderr_rev = _run_command(reviewer_cmd, timeout=600)
        if code_rev == 2:
            tool_error = True
            # 리뷰어는 진단 메시지를 stdout JSON 의 error 필드로 내보낸다.
            # stderr 만 읽으면 원인을 알 수 없는 "리뷰어 도구 오류" 만 남는다.
            detail = stderr_rev.strip()
            if not detail:
                try:
                    detail = str(json.loads(stdout_rev).get("error") or "").strip()
                except json.JSONDecodeError:
                    detail = stdout_rev.strip()
            result["reviewer"] = {
                "error": truncate(detail or "리뷰어 도구 오류", 400),
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
    try:
        intent = parse_intent(intent_text)
    except ValueError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2

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

    parsed_task_id = (
        parse_capsule_scalar(capsule, "task_id") or intent.get("task_id") or "auto-generated"
    )
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
    report_path = intent.get("report_path")
    if not report_path:
        rel_capsule = worktree_relative_capsule_path(capsule_path)
        rel_parent = str(Path(rel_capsule).parent)
        report_path = f"{rel_parent}/worker_done.json" if rel_parent != "." else "worker_done.json"
    delivery_probe = new_delivery_probe()
    try:
        text = build_capsule_notice(
            capsule_path,
            report_path=str(report_path),
            dispatch_id=dispatch_id,
            delivery_probe=delivery_probe,
            worktree_path=getattr(args, "worktree", None),
        )
    except ValueError as err:
        sys.stderr.write(f"경고: Capsule 고지문 작성 실패: {err}\n")
        return {"status": "failed", "reason": str(err), "dispatch_id": dispatch_id}

    code, stdout, stderr = terminal_send(args.terminal, text)
    if code == 0 and _launch_succeeded(stdout, expect_json=True):
        return {
            "status": "sent",
            "dispatch_id": dispatch_id,
            "chars": char_len(text),
            "delivery_probe": delivery_probe,
        }

    reason = stderr.strip() or _extract_cli_error(stdout) or "알 수 없는 오류"
    sys.stderr.write(
        f"경고: Capsule 고지 전송 실패: {reason}\n"
        f"워커가 Capsule 을 읽지 못한 상태로 작업할 수 있습니다. 수동 전달이 필요합니다.\n"
    )
    return {"status": "failed", "reason": reason, "dispatch_id": dispatch_id}


def cmd_create(args: argparse.Namespace) -> int:
    """Intent 를 Capsule 로 확장하고 그 경로를 담은 Orca Task 를 만듭니다.

    Task 의 spec 은 `dispatch --inject` 가 워커에게 전달하는 유일한 본문이라,
    Capsule 경로를 여기에 넣어야 워커가 첫 턴부터 정본을 찾습니다.
    Orca 가 반환한 실제 Task ID 로 Capsule 내부 task_id 및 디렉터리를 확정합니다.
    """
    intent_path = Path(args.intent)
    if not intent_path.exists():
        sys.stderr.write(f"오류: Intent 파일 없음: {intent_path}\n")
        return 2

    try:
        intent = parse_intent(intent_path.read_text(encoding="utf-8"))
    except ValueError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2
    task_id = args.task_id or intent.get("task_id") or f"task_{intent_path.stem}"

    capsule_dir = Path(args.capsule_dir)
    task_capsule_dir = capsule_dir / task_id
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

    bare_dirs = bare_directory_write_scopes(
        parse_capsule_list(capsule, "allowed_write_files"), Path.cwd()
    )
    if bare_dirs:
        sys.stderr.write(
            "경고: allowed_write_files 에 디렉터리 이름만 적힌 항목이 있습니다. "
            "하위 파일은 허용되지 않아 게이트 2 에서 범위 초과로 잡힙니다. "
            f"'<경로>/...' 형태로 고치십시오: {', '.join(bare_dirs)}\n"
        )

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
    if code != 0 or not _launch_succeeded(stdout, expect_json=True):
        capsule_path.unlink(missing_ok=True)
        with suppress(OSError):
            task_capsule_dir.rmdir()
        reason = stderr.strip() or _extract_cli_error(stdout) or "알 수 없는 오류"
        sys.stderr.write(f"오류: task-create 실패: {reason}\n")
        return 1

    created_id = None
    payload = _maybe_json(stdout)
    if isinstance(payload, dict):
        created_id = ((payload.get("result") or {}).get("task") or {}).get("id")

    if not created_id:
        capsule_path.unlink(missing_ok=True)
        with suppress(OSError):
            task_capsule_dir.rmdir()
        sys.stderr.write("오류: task-create 결과에서 Task ID 를 얻지 못했습니다.\n")
        return 1

    actual_task_id = str(created_id)
    actual_capsule_dir = capsule_dir / actual_task_id
    actual_capsule_dir.mkdir(parents=True, exist_ok=True)
    actual_capsule_path = (actual_capsule_dir / "capsule.yaml").resolve()

    try:
        final_capsule = expand_intent_to_capsule(
            intent,
            task_id=actual_task_id,
            run_id=args.run_id,
            capsule_path=actual_capsule_path,
        )
    except ValueError as err:
        if capsule_path != actual_capsule_path:
            actual_capsule_path.unlink(missing_ok=True)
            with suppress(OSError):
                actual_capsule_dir.rmdir()
        capsule_path.unlink(missing_ok=True)
        with suppress(OSError):
            task_capsule_dir.rmdir()
        sys.stderr.write(f"오류: {err}\n")
        return 2

    actual_capsule_path.write_text(final_capsule, encoding="utf-8")

    # Orca 의 task-update 는 status 만 바꾸고 spec 은 바꾸지 못합니다. spec 은
    # 실제 Task ID 를 알기 전에 확정되므로 잠정 경로를 가리키고, 그 경로의
    # Capsule 을 지우면 워커가 첫 턴에 없는 파일을 엽니다. 두 경로를 모두
    # 남겨 spec 이 가리키는 곳과 도구가 task_id 로 찾는 곳이 함께 성립하게
    # 합니다 (2026-08-25 워커 3대 동시 오조준).
    if capsule_path != actual_capsule_path:
        capsule_path.write_text(final_capsule, encoding="utf-8")

    final_spec = build_task_spec(intent.get("objective", ""), actual_capsule_path)
    spec_capsule = worktree_relative_capsule_path(capsule_path)

    if args.json:
        print(
            json.dumps(
                {
                    "task_id": actual_task_id,
                    "capsule": str(actual_capsule_path),
                    "spec_capsule": str(capsule_path),
                    "spec_capsule_relative": spec_capsule,
                    "spec": spec,
                    "canonical_spec": final_spec,
                    "char_count": char_len(final_capsule),
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(f"Task 생성 완료: {actual_task_id}")
        print(f"Capsule: {actual_capsule_path}")
        if capsule_path != actual_capsule_path:
            print(f"spec 이 가리키는 Capsule 사본: {capsule_path}")
    if capsule_path != actual_capsule_path:
        sys.stderr.write(
            "안내: 워크트리에는 .orca/capsules/ 전체를 복사하십시오. "
            f"spec 은 {spec_capsule} 를 가리킵니다.\n"
        )
    return 0


def cmd_dispatch(args: argparse.Namespace) -> int:
    intent_path = Path(args.intent)
    if not intent_path.exists():
        sys.stderr.write(f"오류: Intent 파일 없음: {intent_path}\n")
        return 2

    intent_text = intent_path.read_text(encoding="utf-8")
    try:
        intent = parse_intent(intent_text)
    except ValueError as err:
        sys.stderr.write(f"오류: {err}\n")
        return 2
    task_id = args.task_id or intent.get("task_id") or f"task_{intent_path.stem}"

    capsule_dir = Path(args.capsule_dir)
    if args.capsule:
        # create 가 이미 만든 Capsule 을 그대로 쓴다. 재확장하면 같은 Task 에
        # Capsule 이 두 벌 생기고 Task spec 이 가리키는 쪽과 어긋난다.
        capsule_path = Path(args.capsule).resolve()
        if not capsule_path.exists():
            sys.stderr.write(f"오류: Capsule 파일 없음: {capsule_path}\n")
            return 2
        capsule = capsule_path.read_text(encoding="utf-8")
        capsule_task_id = parse_capsule_scalar(capsule, "task_id")
        if capsule_task_id:
            task_id = capsule_task_id
        try:
            for p in parse_capsule_list(capsule, "allowed_read_files"):
                validate_contained_path(p, field_name="allowed_read_files")
            for p in parse_capsule_list(capsule, "allowed_write_files"):
                validate_contained_path(p, field_name="allowed_write_files")
            rep_p = parse_capsule_scalar(capsule, "report_path")
            if rep_p:
                validate_contained_path(rep_p, field_name="report_path")
        except ValueError as err:
            sys.stderr.write(f"오류: {err}\n")
            return 2

    else:
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
        sys.stderr.write(
            "경고: --skip-concurrency-check 지정으로 동시 쓰기 워커 상한 검사를 건너뜁니다.\n"
        )
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
    delivery_unverified: list[str] = []
    # Dispatch 전 관찰은 최종 실패 후보가 아닙니다. 사후 확인 결과와 함께
    # 판정하기 위해 따로 모읍니다.
    pre_dispatch_warnings: list[str] = []
    dispatch_started_at = time.time()
    if args.terminal:
        # 신뢰 확인 대화창을 먼저 치운다. 떠 있는 상태로 Dispatch 하면 주입한
        # 지시와 Capsule 고지문이 대화창에 먹혀 워커가 시작하지 못한다.
        trust_status = approve_trust_prompt(args.terminal)
        if trust_status == "approved":
            sys.stderr.write("신뢰 확인 대화창을 승인했습니다.\n")
        elif trust_status == "still_present":
            sys.stderr.write(
                "오류: 신뢰 확인 대화창이 남아 있어 Dispatch 를 중단했습니다. "
                f"터미널 {args.terminal} 을 직접 확인하십시오. 이 상태로 보내면 "
                "지시가 대화창에 먹혀 사라집니다.\n"
            )
            return 2
        elif trust_status in ("unreadable", "not_settled"):
            # Dispatch 전의 준비 상태만으로 전달 실패를 단정하면 오탐입니다.
            # CLI 가 아직 뜨는 중이어도 주입은 큐에 남아 정상 도달합니다.
            # 실제 도달 여부는 Dispatch 이후에 화면으로 확인합니다.
            pre_dispatch_warnings.append(
                "trust_prompt_unreadable"
                if trust_status == "unreadable"
                else "terminal_not_settled"
            )
            sys.stderr.write(
                f"경고: 터미널 {args.terminal} 의 Dispatch 전 상태가 {trust_status} 입니다. "
                "Dispatch 이후 도달을 확인합니다.\n"
            )

        sys.stderr.write(f"터미널 부착 Dispatch 중... (task={task_id}, terminal={args.terminal})\n")
        code, stdout, stderr = dispatch_worker(
            task_id=task_id,
            to_handle=args.terminal,
            run_id=args.run_id if args.run_id != DEFAULT_RUN_ID else None,
            inject=True,
            as_json=args.json,
        )
        launch_cmd = f"orca orchestration dispatch --task {task_id} --to {args.terminal} --inject"

        # 권한 프롬프트 자동 승인 감시기는 선택이 아니라 기동 절차의 일부입니다.
        # 붙이지 않으면 워커가 셸 명령 승인 대화창마다 멈추고, 감시 도구는 이를
        # 진행으로 오판할 수 있습니다.
        approve_started, approve_detail = start_auto_approve(args.terminal)
        if approve_started:
            sys.stderr.write(f"권한 자동 승인 감시기를 붙였습니다. 로그: {approve_detail}\n")
        else:
            sys.stderr.write(
                f"경고: {approve_detail}. 워커가 권한 대화창에서 멈출 수 있으니 "
                f"python3 scripts/orca_auto_approve.py {args.terminal} 를 직접 띄우십시오.\n"
            )
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

    if code == 0 and _launch_succeeded(stdout, expect_json=args.json):
        try:
            reliability_tracking = _start_reliability_tracking(
                capsule_path,
                task_id,
                model,
                dispatch_started_at,
            )
        except Exception as exc:
            reliability_tracking = {"status": "error", "reason": str(exc)}
        notice = _deliver_capsule_notice(args, task_id, capsule_path, intent)
        if notice["status"] == "failed":
            delivery_unverified.append("capsule_notice_failed")

        # 사후 확인: 주입한 문자열이 실제로 화면에 나타났는지 본다. Dispatch
        # 전의 준비 상태 판정만으로 실패를 단정하면 오탐이 난다. 도달을
        # 확인하면 사전 경고는 해소된 것으로 본다.
        delivery_check = "skipped"
        probe = notice.get("delivery_probe")
        if args.terminal and probe:
            # 이번 시도의 표지만 찾습니다. task_id 나 Capsule 경로로 찾으면
            # 재 Dispatch 시 화면에 남은 이전 시도의 잔상이 그대로 통과합니다.
            delivery_check = verify_instruction_delivered(args.terminal, [probe])
            if delivery_check == "not_observed":
                delivery_unverified.append("instruction_not_observed")
            elif delivery_check == "unreadable":
                delivery_unverified.append("terminal_unreadable_after_dispatch")
        elif args.terminal:
            # 표지가 없으면 이번 시도의 도달을 증명할 수단이 없습니다. 고지문
            # 전송 실패나 --no-capsule-notice 가 여기 해당합니다. 증명 없음을
            # 성공으로 돌리면 검증 자체가 성립하지 않습니다.
            delivery_check = "no_probe"
            delivery_unverified.append("delivery_probe_missing")
        elif pre_dispatch_warnings:
            # worker-start 경로는 핸들을 즉시 알 수 없어 사후 확인을 못 한다.
            # 이때만 사전 경고를 그대로 미확인으로 승계한다.
            delivery_unverified.extend(pre_dispatch_warnings)

        # 워커 기동 성공만으로 0 을 돌려주면 "정본 지시가 워커에게 도달했는가"
        # 라는 제어 평면의 핵심 불변식이 검증되지 않은 채 성공으로 보고된다.
        # 2026-08-17 에 신뢰 대화창 때문에 지시가 유실된 사고가 실제로 있었다.
        unverified = delivery_unverified and not args.allow_unverified_delivery
        exit_code = 3 if unverified else 0

        if args.json:
            payload: dict[str, Any] = {"launch": _maybe_json(stdout)}
            payload["capsule"] = str(capsule_path)
            payload["capsule_notice"] = notice
            payload["pre_dispatch_warnings"] = pre_dispatch_warnings
            payload["delivery_check"] = delivery_check
            payload["delivery_unverified"] = delivery_unverified
            payload["reliability_tracking"] = reliability_tracking
            payload["exit_code"] = exit_code
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"워커 기동 완료:\n{stdout}")
            print(f"Capsule 고지: {notice['status']}")
            if reliability_tracking["status"] == "tracking":
                print(f"신뢰도 추적: {reliability_tracking['pool']}/{reliability_tracking['role']}")
        if unverified:
            sys.stderr.write(
                "오류: 워커는 기동했으나 지시 도달을 확인하지 못했습니다 "
                f"({', '.join(delivery_unverified)}). 워커가 정본 지시를 받았는지 "
                "직접 확인한 뒤 진행하십시오. 확인 없이 진행하려면 "
                "--allow-unverified-delivery 를 쓰십시오.\n"
            )
        return exit_code

    # Orca CLI 는 실패를 stdout JSON 의 error.message 로 내보내면서 stderr 를 비워
    # 두는 경우가 있다. stderr 만 읽으면 원인이 사라지므로 stdout 도 함께 본다.
    err_msg = stderr.strip() or _extract_cli_error(stdout) or "알 수 없는 오류"
    sys.stderr.write(f"오류: 워커 기동 실패 (종료 코드 {code}): {err_msg}\n")
    if "Task not found" in err_msg:
        # Orca 는 Task ID 를 스스로 발급하므로 Intent 파일명에서 만든 잠정 ID 로는
        # 찾을 수 없다. create 를 먼저 돌리고 그 ID 를 --task-id 로 넘겨야 한다.
        sys.stderr.write(
            f"안내: Task {task_id} 는 Orca 에 없습니다. Task ID 는 Orca 가 발급하므로 "
            "Intent 파일명으로 유추할 수 없습니다. "
            f"먼저 `orca_taskctl.py create --intent {intent_path} --run-id {args.run_id}` 를 "
            "돌리고, 그 결과의 task_id 와 capsule 을 "
            "`--task-id`, `--capsule` 로 넘겨 다시 Dispatch 하십시오.\n"
        )
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
        strict=not args.allow_skipped_gates,
        max_diff_chars=args.max_diff_chars,
        allow_truncated_diff=args.allow_truncated_diff,
    )
    try:
        result["reliability"] = _record_finalize_reliability(capsule_path, result)
    except Exception as exc:
        result["reliability"] = {"status": "error", "reason": str(exc)}

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
    dsp.add_argument(
        "--capsule",
        help="이미 만들어 둔 Capsule 경로. 지정하면 재확장하지 않고 그 파일을 그대로 씁니다 "
        "(create 로 만든 Capsule 을 재사용할 때).",
    )
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
    dsp.add_argument(
        "--allow-unverified-delivery",
        action="store_true",
        help="지시 도달을 확인하지 못해도 종료 코드 0 으로 처리합니다 (권장하지 않음).",
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
    fin.add_argument(
        "--max-diff-chars",
        type=int,
        default=None,
        help="리뷰어 diff 본문 상한 (기본: 리뷰어 도구 기본값 20000)",
    )
    fin.add_argument(
        "--allow-truncated-diff",
        action="store_true",
        help="diff 가 절단되어도 리뷰어 판정을 받아들임",
    )
    fin.add_argument(
        "--allow-skipped-gates",
        action="store_true",
        help="건너뛴 Level 1 게이트를 실패로 보지 않습니다 (기본은 실패 처리)",
    )
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
