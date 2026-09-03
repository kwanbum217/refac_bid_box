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
import hashlib
import json
import os
import re
import shlex
import signal
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
        DEFAULT_GIT_TIMEOUT,
        DEFAULT_PYTEST_TIMEOUT,
        DEFAULT_VALIDATE_TIMEOUT,
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
        DEFAULT_GIT_TIMEOUT,
        DEFAULT_PYTEST_TIMEOUT,
        DEFAULT_VALIDATE_TIMEOUT,
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
        write_scope_excess,
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
        write_scope_excess,
    )

try:
    from scripts.orca_model_router import (
        MODEL_POOL,
        ModelRoutingError,
        capsule_has_write_scope,
        classify_from_capsule,
        classify_risk,
        pool_for_model,
        provider_for_model,
        record_reliability_outcome,
        select_model,
    )
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_model_router import (
        MODEL_POOL,
        ModelRoutingError,
        capsule_has_write_scope,
        classify_from_capsule,
        classify_risk,
        pool_for_model,
        provider_for_model,
        record_reliability_outcome,
        select_model,
    )

try:
    from scripts.orca_skill_receipt import verify_skill_receipt
except (ModuleNotFoundError, ImportError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_skill_receipt import verify_skill_receipt

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
FILE_EDIT_AUTO_APPROVE_SEQUENCE = "\x1b[Z"

MODEL_TIER_RANK: dict[str, int] = {
    "gemini-3.7-flash-low": 1,
    "gemini-flash-low": 1,
    "gemini-3.7-flash-medium": 2,
    "gemini-flash-medium": 2,
    "gemini-3.7-flash-high": 3,
    "gemini-flash-high": 3,
    "claude-sonnet-4-6": 4,
    "claude-sonnet": 4,
    "claude-opus-4-6-thinking": 5,
    "claude-opus-thinking": 5,
    "claude-opus-5": 5,
    "claude-opus": 5,
    "gpt-5.6-terra": 6,
    "codex": 6,
}

# Level 1은 전체 pytest, 규칙 검증, ruff, Git 검사를 자체 상한으로 순차 실행합니다.
# finalize의 바깥 상한은 그 합보다 짧아서는 안 됩니다.
LEVEL1_FINALIZE_TIMEOUT = (
    DEFAULT_PYTEST_TIMEOUT + (2 * DEFAULT_VALIDATE_TIMEOUT) + (3 * DEFAULT_GIT_TIMEOUT) + 60
)
WORKER_SUMMARY_FINALIZE_TIMEOUT = LEVEL1_FINALIZE_TIMEOUT


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

required_write_files:
{required_write_files}

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

CAPSULE_CONTRACT_SCALAR_FIELDS = (
    "schema",
    "version",
    "role",
    "mode",
    "return_contract",
    "report_path",
)

CAPSULE_CONTRACT_LIST_FIELDS = (
    "allowed_write_files",
    "allowed_read_files",
    "required_write_files",
    "required_change",
    "acceptance",
    "forbidden",
    "verification_commands",
)


def compute_capsule_contract_digest(capsule_text: str) -> str:
    """Capsule 의 핵심 계약 필드들을 정규화하여 SHA256 digest 를 산출합니다."""
    payload: dict[str, Any] = {}
    for f in CAPSULE_CONTRACT_SCALAR_FIELDS:
        val = parse_capsule_scalar(capsule_text, f)
        payload[f] = val.strip() if val else ""
    for f in CAPSULE_CONTRACT_LIST_FIELDS:
        items = parse_capsule_list(capsule_text, f)
        payload[f] = sorted(item.strip() for item in items if item.strip())
    canonical_json = json.dumps(payload, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(canonical_json.encode("utf-8")).hexdigest()


def compare_capsule_contracts(cap1_text: str, cap2_text: str) -> tuple[bool, str]:
    """두 Capsule 간의 핵심 계약 필드 일치 여부를 비교합니다."""
    mismatches: list[str] = []
    for f in CAPSULE_CONTRACT_SCALAR_FIELDS:
        v1 = (parse_capsule_scalar(cap1_text, f) or "").strip()
        v2 = (parse_capsule_scalar(cap2_text, f) or "").strip()
        if v1 != v2:
            mismatches.append(f"{f}: '{v1}' vs '{v2}'")
    for f in CAPSULE_CONTRACT_LIST_FIELDS:
        l1 = sorted(item.strip() for item in parse_capsule_list(cap1_text, f) if item.strip())
        l2 = sorted(item.strip() for item in parse_capsule_list(cap2_text, f) if item.strip())
        if l1 != l2:
            mismatches.append(f"{f}: {l1} vs {l2}")
    if mismatches:
        return False, "; ".join(mismatches)
    return True, "계약 일치"


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


def validate_commit_count(
    commit_count: Any,
    status: str = "succeeded",
    has_write_scope: bool = True,
) -> list[str]:
    """commit_count 의 타입과 값을 검증하여 위반 목록을 반환합니다.

    - 정수만 허용 (bool 제외, 문자열 제외, float 제외)
    - 음수 금지 (< 0)
    - status == 'succeeded' 이고 쓰기 범위가 있는 작업에서 0 이면 무작업 위반
    """
    violations: list[str] = []
    if isinstance(commit_count, bool) or not isinstance(commit_count, int):
        violations.append(
            f"타입 위반: commit_count 는 정수여야 하는데 "
            f"{type(commit_count).__name__} ({commit_count!r})"
        )
    elif commit_count < 0:
        violations.append(f"값 위반: commit_count 가 음수 ({commit_count})")
    elif commit_count == 0 and status == "succeeded" and has_write_scope:
        violations.append(
            "규약 3.3 위반: status 가 succeeded 인데 commit_count 가 0 (무작업 완료 보고)"
        )
    return violations


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

            if key in (
                "scope",
                "read_scope",
                "acceptance",
                "ground_truth",
                "required_change",
                "required_write_files",
            ):
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
    for item in result.get("required_write_files", []):
        validate_contained_path(item, field_name="required_write_files")
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

    # required_write_files: Intent scope 또는 required_write_files 에서 도출
    if is_reviewer:
        required_write_files: list[str] = []
    else:
        raw_req_write = intent.get("required_write_files")
        if raw_req_write is not None and isinstance(raw_req_write, list):
            required_write_files = [str(item) for item in raw_req_write if str(item).strip()]
        elif intent.get("scope"):
            required_write_files = list(intent["scope"])
        else:
            required_write_files = ["src/...", "tests/..."]

    for item in required_write_files:
        validate_contained_path(item, field_name="required_write_files")

    # required_write_files 가 allowed_write_files 의 부분집합인지 엄격 검증
    excess_req = write_scope_excess(required_write_files, write_files)
    if excess_req:
        raise ValueError(
            f"required_write_files 는 allowed_write_files 의 부분집합이어야 합니다 (초과 항목: {', '.join(excess_req)})"
        )

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
    required_write_formatted = _format_yaml_list(required_write_files)

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
        required_write_files=required_write_formatted,
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


def check_settled_sessions(
    run_id: str | None = None,
    timeout: int = 30,
) -> dict[str, Any]:
    """실측으로 완료 세션 잔류를 검사합니다."""
    try:
        from scripts.orca_settled_session_audit import audit_lingering_sessions
    except (ModuleNotFoundError, ImportError):
        try:
            from orca_settled_session_audit import audit_lingering_sessions
        except (ModuleNotFoundError, ImportError):
            _repo_root = Path(__file__).resolve().parent.parent
            if str(_repo_root) not in sys.path:
                sys.path.insert(0, str(_repo_root))
            from scripts.orca_settled_session_audit import audit_lingering_sessions

    try:
        return audit_lingering_sessions(run_id=run_id, timeout=timeout)
    except Exception as exc:
        return {
            "allowed": False,
            "lingering": [],
            "count": 0,
            "reason": f"완료 세션 잔류 검사 실패로 인한 안전 거부: {exc}",
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
) -> tuple[int, str, str, list[str]]:
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

    code, stdout, stderr = _run_command(cmd, timeout=timeout)
    return code, stdout, stderr, cmd


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
) -> tuple[int, str, str, list[str]]:
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

    code, stdout, stderr = _run_command(cmd, timeout=timeout)
    return code, stdout, stderr, cmd


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


def terminal_read(handle: str, timeout: int = 30) -> str | None:
    """터미널의 전체 화면/버퍼 출력을 읽습니다 (orca terminal read). 조회에 실패하면 None 을 돌려줍니다."""
    cmd = ["orca", "terminal", "read", "--terminal", handle, "--json"]
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
    tail = terminal.get("tail")
    if isinstance(tail, list):
        return "\n".join(str(line) for line in tail)
    if isinstance(tail, str):
        return tail
    return None


def strip_terminal_metadata_header(text: str) -> str:
    """orca terminal read 의 머리말 메타 줄(handle:, cursor: 등)을 제외합니다."""
    meta_prefixes = (
        "handle:",
        "status:",
        "source:",
        "cursor:",
        "oldest cursor:",
        "latest cursor:",
        "next cursor:",
        "warning:",
    )
    cleaned_lines = []
    for line in text.splitlines():
        stripped = line.strip().lower()
        if any(stripped.startswith(prefix) for prefix in meta_prefixes):
            continue
        cleaned_lines.append(line)
    return "\n".join(cleaned_lines)


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
    *,
    _time_monotonic: Any = None,
    _time_sleep: Any = None,
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
    get_time = _time_monotonic if _time_monotonic is not None else time.monotonic
    sleep_fn = _time_sleep if _time_sleep is not None else time.sleep
    deadline = get_time() + max(0, wait_seconds)
    unreadable_only = True
    while True:
        text = terminal_tail(handle, timeout=timeout)
        if text is not None:
            unreadable_only = False
            if instruction_observed(text, markers):
                return "delivered"
        if wait_seconds <= 0 or get_time() >= deadline:
            return "unreadable" if unreadable_only else "not_observed"
        sleep_fn(max(0.2, poll_seconds))


def get_watcher_pid_path(terminal: str) -> Path:
    """터미널 핸들에 대응하는 PID 파일 경로를 반환합니다."""
    return Path(tempfile.gettempdir()) / "orca_auto_approve" / f"{terminal}.pid"


def get_watcher_log_path(terminal: str) -> Path:
    """터미널 핸들에 대응하는 로그 파일 경로를 반환합니다."""
    return Path(tempfile.gettempdir()) / "orca_auto_approve" / f"{terminal}.log"


def get_worker_meta_path(terminal: str) -> Path:
    """터미널 핸들에 대응하는 워커 메타데이터 파일 경로를 반환합니다."""
    return Path(tempfile.gettempdir()) / "orca_auto_approve" / f"{terminal}.meta.json"


def read_worker_meta(terminal: str) -> dict[str, Any] | None:
    """터미널 핸들에 대응하는 워커 메타데이터를 안전하게 읽습니다."""
    path = get_worker_meta_path(terminal)
    try:
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        payload = json.loads(content)
        return payload if isinstance(payload, dict) else None
    except Exception:
        return None


def write_worker_meta(terminal: str, meta: dict[str, Any]) -> None:
    """터미널 핸들에 대응하는 워커 메타데이터를 저장합니다."""
    path = get_worker_meta_path(terminal)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except OSError:
        pass


def remove_worker_meta(terminal: str) -> None:
    """터미널 핸들에 대응하는 워커 메타데이터를 삭제합니다."""
    path = get_worker_meta_path(terminal)
    try:
        if path.exists():
            path.unlink(missing_ok=True)
    except OSError:
        pass


def read_watcher_pid(path: Path) -> int | None:
    """PID 파일을 안전하게 읽어 유효한 정수 PID 를 반환합니다. 빈 파일이나 손상된 내용은 None."""
    try:
        if not path.exists():
            return None
        content = path.read_text(encoding="utf-8").strip()
        if not content:
            return None
        pid = int(content)
        return pid if pid > 0 else None
    except Exception:
        return None


def watcher_alive(pid: int | None) -> bool:
    """주어진 PID 프로세스가 실제로 살아 있는지 확인합니다."""
    if pid is None or pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    except OSError:
        return False


def write_watcher_pid(path: Path, pid: int) -> None:
    """PID 파일을 생성하고 PID 를 기록합니다."""
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"{pid}\n", encoding="utf-8")
    except OSError:
        pass


def remove_watcher_pid(path: Path) -> None:
    """PID 파일을 안전하게 삭제합니다."""
    try:
        if path.exists():
            path.unlink(missing_ok=True)
    except OSError:
        pass


def start_auto_approve(terminal: str) -> tuple[bool, str]:
    """워커 터미널에 권한 프롬프트 자동 승인 감시기를 단일 인스턴스로 붙인다.

    이미 살아 있는 감시기가 있으면 새로 띄우지 않고 기존 로그 경로를 돌려줍니다.
    붙이지 않으면 셸 명령 승인 대화창마다 워커가 멈춥니다.
    """
    if os.environ.get("ORCA_DISABLE_AUTO_APPROVE") == "1":
        return False, "ORCA_DISABLE_AUTO_APPROVE=1 이므로 자동 승인 감시기를 띄우지 않았습니다"
    script = Path(__file__).resolve().parent / "orca_auto_approve.py"
    if not script.exists():
        return False, f"자동 승인 감시기를 찾지 못했습니다: {script}"

    pid_path = get_watcher_pid_path(terminal)
    log_path = get_watcher_log_path(terminal)
    log_dir = log_path.parent

    # 1. 기존 PID 생존 여부 확인 (단일 인스턴스 보장)
    existing_pid = read_watcher_pid(pid_path)
    if existing_pid is not None and watcher_alive(existing_pid):
        return True, str(log_path)

    # 2. 없거나 죽어 있으면 새로 기동하고 PID 기록
    try:
        log_dir.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log_file:
            proc = subprocess.Popen(  # nosec B603  고정된 스크립트 경로와 터미널 핸들만 넘깁니다
                [sys.executable, str(script), terminal],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                start_new_session=True,
            )
            pid = getattr(proc, "pid", None)
            if pid is not None:
                write_watcher_pid(pid_path, pid)
    except OSError as exc:
        return False, f"자동 승인 감시기 기동 실패: {exc}"
    return True, str(log_path)


def stop_auto_approve(terminal: str) -> tuple[bool, str]:
    """워커 터미널에 붙은 권한 자동 승인 감시기를 명시적으로 중지하고 PID 파일 및 메타데이터를 정리합니다."""
    pid_path = get_watcher_pid_path(terminal)
    pid = read_watcher_pid(pid_path)
    if pid is not None and watcher_alive(pid):
        with suppress(OSError):
            os.kill(pid, signal.SIGTERM)
    remove_watcher_pid(pid_path)
    return True, f"자동 승인 감시기 중지 완료 ({terminal})"


def get_worker_watch_pid_path(repo: Path | str | None = None) -> Path:
    """주 저장소 경로에 대응하는 상시 감시기 PID 파일 경로를 반환합니다."""
    repo_key = hashlib.sha256(str(Path(repo or ".").resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / "orca_worker_watch" / f"watcher_{repo_key}.pid"


def get_worker_watch_log_path(repo: Path | str | None = None) -> Path:
    """주 저장소 경로에 대응하는 상시 감시기 로그 파일 경로를 반환합니다."""
    repo_key = hashlib.sha256(str(Path(repo or ".").resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / "orca_worker_watch" / f"watcher_{repo_key}.log"


def start_worker_watch(repo: Path | str = ".") -> tuple[bool, str]:
    """상시 워커 감시기(orca_worker_watch.py --watch)를 단일 인스턴스로 배경에 기동합니다.

    이미 살아 있는 감시기가 있으면 새로 띄우지 않고 기존 프로세스를 재사용합니다.
    """
    if (
        os.environ.get("ORCA_DISABLE_AUTO_APPROVE") == "1"
        or os.environ.get("ORCA_DISABLE_WORKER_WATCH") == "1"
    ):
        return False, "ORCA_DISABLE_AUTO_APPROVE=1 이므로 상시 감시기를 띄우지 않았습니다"
    script = Path(__file__).resolve().parent / "orca_worker_watch.py"
    if not script.exists():
        return False, f"워커 감시 스크립트를 찾지 못했습니다: {script}"

    repo_path = Path(repo).resolve()
    pid_path = get_worker_watch_pid_path(repo_path)
    log_path = get_worker_watch_log_path(repo_path)

    # 1. 기존 PID 생존 여부 확인 (단일 인스턴스 보장 / 중복 방지)
    existing_pid = read_watcher_pid(pid_path)
    if existing_pid is not None and watcher_alive(existing_pid):
        return True, f"기존 상시 감시기 재사용 (PID {existing_pid}, 로그: {log_path})"

    # 2. 없거나 죽어 있으면 새로 기동하고 PID 기록
    try:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("ab") as log_file:
            # start_new_session 은 POSIX 전용이라 Windows 에서는 무시됩니다. 분리하지
            # 않으면 감시기가 부모와 같은 콘솔 그룹에 남아 Ctrl+C 가 서로 전파됩니다.
            detach_kwargs: dict[str, object] = {"start_new_session": True}
            if sys.platform == "win32":
                detach_kwargs = {
                    "creationflags": subprocess.CREATE_NEW_PROCESS_GROUP
                    | subprocess.DETACHED_PROCESS
                }
            proc = subprocess.Popen(  # nosec B603  고정된 스크립트 경로와 인자만 넘깁니다
                [sys.executable, str(script), "--repo", str(repo_path), "--watch"],
                stdout=log_file,
                stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL,
                **detach_kwargs,  # type: ignore[arg-type]
            )
            pid = getattr(proc, "pid", None)
            if pid is not None:
                write_watcher_pid(pid_path, pid)
    except OSError as exc:
        return False, f"상시 감시기 기동 실패: {exc}"
    return True, f"상시 감시기 기동 완료 (PID {pid}, 로그: {log_path})"


def stop_worker_watch(repo: Path | str = ".") -> tuple[bool, str]:
    """상시 워커 감시기를 중지하고 PID 파일을 정리합니다."""
    repo_path = Path(repo).resolve()
    pid_path = get_worker_watch_pid_path(repo_path)
    pid = read_watcher_pid(pid_path)
    if pid is None:
        remove_watcher_pid(pid_path)
        return False, "실행 중인 상시 감시기가 없습니다"
    try:
        if watcher_alive(pid):
            # SIGKILL 은 POSIX 전용입니다. Windows 에는 없어 참조만으로 AttributeError
            # 가 나므로, 그 환경에서는 SIGTERM(내부적으로 TerminateProcess) 로 끝냅니다.
            force_signal = getattr(signal, "SIGKILL", signal.SIGTERM)
            os.kill(pid, signal.SIGTERM)
            time.sleep(0.1)
            if watcher_alive(pid):
                os.kill(pid, force_signal)
        remove_watcher_pid(pid_path)
        return True, f"상시 감시기 종료 (PID {pid})"
    except ProcessLookupError:
        remove_watcher_pid(pid_path)
        return True, f"상시 감시기 프로세스가 이미 종료되었습니다 (PID {pid})"
    except OSError as exc:
        return False, f"상시 감시기 종료 실패 (PID {pid}): {exc}"


CURSOR_PLAN_MODE_MARKERS: tuple[str, ...] = (
    "cursor-agent",
    "cursor agent",
    "composer",
    "plan mode",
    "enable plan mode",
    "hit shift+tab to enable plan mode",
    "run everything",
    "cursoragent@",
)

# 판정 근거는 CLI 가 상태줄에 스스로 그리는 문자열로만 좁힙니다. 도구 호출 표기나
# 사고 과정 표기 같은 범용 형식은 여러 CLI 가 공유하므로 쓰지 않습니다. 화면에는
# 코디네이터가 보낸 지시문도 남으므로, 넓은 마커는 대화 내용에 오염됩니다.
ACCEPT_EDITS_CLI_MARKERS: tuple[str, ...] = (
    "accept-edits",
    "auto-approve file edits",
    "shift+tab to auto-approve",
    "antigravity cli",
    "agy --model",
)

ANTIGRAVITY_STATUS_LINE_MARKERS: tuple[str, ...] = (
    "accept-edits",
    "plan",
    "shift+tab",
    "gemini",
    "claude",
    "flash",
    "·",
    "out of credits",
    "antigravity cli",
    "auto-approve",
    "agy --model",
)


def detect_antigravity_mode(text: str | None) -> str:
    """Antigravity CLI 터미널 화면의 하단 상태줄을 분석하여 현재 모드를 감지합니다.

    대화 본문(본문 텍스트나 사용자 지시문)에 'accept-edits' 또는 'plan' 단어가
    포함되어도 오판하지 않도록 화면 하단(최근 5줄)의 각 상태줄 단위로 판정합니다.

    반환값:
    - 'accept-edits': 파일 편집 자동 승인 모드 활성화 상태
    - 'plan': Plan Mode(읽기 전용 계획 수립 모드) 활성화 상태
    - 'normal': 기본 대화 모드 (상태줄이 확인되었으나 모드 전환되지 않은 상태)
    - 'unknown': 화면이 비어 있거나 상태줄을 식별할 수 없는 상태 (스피너만 있는 경우 등)
    """
    if not text or not text.strip():
        return "unknown"

    cleaned = strip_terminal_metadata_header(text)
    lines = [line.strip().lower() for line in cleaned.splitlines() if line.strip()]
    if not lines:
        return "unknown"

    footer_lines = lines[-5:] if len(lines) >= 5 else lines

    # 가장 최근 상태줄(아래쪽 줄)부터 역순으로 상태 표지 검사
    has_status_line = False
    for line in reversed(footer_lines):
        # 1. accept-edits 모드 판정
        if (
            "accept-edits ·" in line
            or "· accept-edits" in line
            or "accept-edits mode" in line
            or "file edits auto-approved" in line
            or (
                "accept-edits" in line
                and any(
                    m in line
                    for m in (
                        "gemini",
                        "claude",
                        "flash",
                        "high",
                        "medium",
                        "low",
                        "out of credits",
                        "·",
                    )
                )
            )
        ):
            return "accept-edits"

        # 2. plan 모드 판정
        if (
            "plan ·" in line
            or "· plan" in line
            or "plan mode" in line
            or "enable plan mode" in line
            or "hit shift+tab to enable plan mode" in line
            or (
                "plan" in line
                and any(
                    m in line
                    for m in (
                        "gemini",
                        "claude",
                        "flash",
                        "high",
                        "medium",
                        "low",
                        "out of credits",
                        "·",
                    )
                )
            )
        ):
            return "plan"

        if any(marker in line for marker in ANTIGRAVITY_STATUS_LINE_MARKERS):
            has_status_line = True

    if has_status_line:
        return "normal"

    if any(any(m in line for m in ANTIGRAVITY_STATUS_LINE_MARKERS) for line in lines):
        return "normal"

    return "unknown"


def _classify_from_screen_text(text: str | None) -> tuple[bool, str]:
    """화면 문자열을 기반으로 CLI 종류를 판정합니다."""
    if not text or not text.strip():
        return False, "터미널 화면이 비어 있어 CLI 종류를 판정할 수 없습니다 (fail-closed)"

    cleaned = strip_terminal_metadata_header(text)
    lowered = cleaned.lower()

    has_agy = any(marker in lowered for marker in ACCEPT_EDITS_CLI_MARKERS)
    has_cursor = any(marker in lowered for marker in CURSOR_PLAN_MODE_MARKERS)

    if has_agy:
        return True, "Antigravity CLI 가 확인되어 파일 편집 자동 승인 모드 전환을 지원합니다"

    if has_cursor:
        return (
            False,
            "Cursor CLI 는 shift+tab 이 Plan Mode(읽기 전용) 전환이므로 파일 편집 모드 전환을 전송하지 않습니다",
        )

    return (
        False,
        "shift+tab 을 accept-edits 로 해석하는 CLI 가 아니므로 파일 편집 모드 전환을 전송하지 않습니다 (fail-closed)",
    )


def classify_file_edit_auto_approve_support(
    text: str | None = None,
    terminal: str | None = None,
) -> tuple[bool, str]:
    """워커의 CLI 종류를 판정하여 shift+tab 이 파일 편집 자동 승인(accept-edits)으로 동작하는지 여부를 반환합니다.

    1. 터미널 핸들(terminal)이 주어지면 기동 시점에 기록된 메타데이터를 우선 신뢰합니다.
    2. 기록된 메타데이터와 화면 판정 결과가 다르면 기록을 우선하되 경고를 출력합니다.
    3. 메타데이터가 없으면 화면 문자열(text) 판정으로 fallback 합니다.
    4. 판정할 수 없는 알 수 없는 CLI 는 fail-closed 원칙에 따라 False 를 반환합니다.
    """
    # 1. 메타데이터 기록 확인
    meta = read_worker_meta(terminal) if terminal else None
    if meta and isinstance(meta, dict):
        cli_type = str(meta.get("cli_type") or meta.get("agent") or "").lower().strip()
        launcher = str(meta.get("launcher") or "").lower().strip()
        model = str(meta.get("model") or "").lower().strip()

        is_agy_record = (
            "antigravity" in cli_type
            or "agy" in cli_type
            or "agy" in launcher
            or (not cli_type and "gemini" in model)
        )
        is_cursor_record = "cursor" in cli_type or (not cli_type and "cursor" in model)
        # Qwen Code 는 기동 시점부터 Auto mode 이고 shift+tab 은 그 모드를 벗어나는
        # 순환 키입니다. 보내면 오히려 자동 승인을 끄게 되므로 전송하지 않습니다.
        is_qwen_record = "qwen" in cli_type or (
            not cli_type and any(tag in model for tag in ("qwen", "deepseek-v4", "glm-5"))
        )

        record_supported: bool | None = None
        record_reason: str | None = None

        if is_qwen_record:
            record_supported = False
            record_reason = (
                f"기록된 메타데이터(cli={cli_type or 'qwen'})에 따라 Qwen Code 로 판정되어 "
                "모드 전환을 전송하지 않습니다. Qwen Code 는 Auto mode 로 기동하며 "
                "shift+tab 은 그 모드를 벗어나는 순환 키입니다"
            )
        elif is_cursor_record:
            record_supported = False
            record_reason = (
                f"기록된 메타데이터(cli={cli_type or 'cursor'})에 따라 Cursor CLI 로 판정되어 "
                "파일 편집 모드 전환을 전송하지 않습니다"
            )
        elif is_agy_record:
            record_supported = True
            record_reason = (
                f"기록된 메타데이터(cli={cli_type or 'antigravity'})에 따라 Antigravity CLI 로 판정되어 "
                "파일 편집 자동 승인 모드 전환을 지원합니다"
            )
        elif cli_type in ("opencode", "claude", "codex", "kimi", "qwen"):
            record_supported = False
            record_reason = (
                f"기록된 메타데이터(cli={cli_type})에 따라 shift+tab 을 accept-edits 로 "
                "해석하는 CLI 가 아니므로 모드 전환을 전송하지 않습니다"
            )

        if record_supported is not None and record_reason is not None:
            # 화면 문자열도 있으면 대조하여 불일치 시 경고 출력
            if text and text.strip():
                screen_supp, _ = _classify_from_screen_text(text)
                if screen_supp != record_supported:
                    sys.stderr.write(
                        f"경고: CLI 화면 판정({screen_supp})과 메타데이터 기록({record_supported})이 "
                        f"일치하지 않아 기록({cli_type or model})을 우선합니다.\n"
                    )
            return record_supported, record_reason

    # 2. 메타데이터가 없으면 화면 문자열(text) 판정으로 fallback
    return _classify_from_screen_text(text)


def enable_file_edit_auto_approve(
    terminal: str,
    timeout: int = 30,
    force: bool = False,
    max_attempts: int = 3,
) -> tuple[bool, str]:
    """워커 터미널에 파일 편집 자동 승인 모드(accept-edits)를 안전하게 확보합니다.

    현재 모드를 먼저 읽어 이미 accept-edits 면 아무 키도 보내지 않습니다.
    plan 이나 normal 이면 accept-edits 가 될 때까지 필요한 횟수(최대 max_attempts 회)만
    shift+tab(ESC [ Z) 시퀀스를 전송하고 매 전송 후 화면으로 모드를 재확인합니다.
    force=True 지정 시 CLI 미식별 상태에서도 모드 확보를 시도하되 현재 모드 확인과 상한은 동일하게 준수합니다.
    모드가 실제로 accept-edits 로 확인되지 않으면 성공으로 처리하지 않고 실패(False)를 반환합니다.
    """
    if os.environ.get("ORCA_DISABLE_AUTO_APPROVE") == "1":
        return (
            False,
            "ORCA_DISABLE_AUTO_APPROVE=1 이므로 파일 편집 자동 승인 모드 전환을 건너뜁니다",
        )

    text = terminal_read(terminal, timeout=timeout) or terminal_tail(terminal, timeout=timeout)

    if not force:
        if text is None:
            return (
                False,
                f"터미널 {terminal} 출력을 읽을 수 없어 파일 편집 모드 전환을 건너뜁니다 (fail-closed)",
            )
        supported, reason = classify_file_edit_auto_approve_support(text, terminal=terminal)
        if not supported:
            return False, reason

    if text is None:
        text = ""

    # 1. 현재 모드 확인: 이미 accept-edits 이면 키 전송 없이 즉시 반환
    current_mode = detect_antigravity_mode(text)
    if current_mode == "accept-edits":
        return True, f"이미 파일 편집 자동 승인(accept-edits) 모드입니다 ({terminal})"
    if not force and current_mode == "unknown":
        return (
            False,
            f"터미널 {terminal} 의 화면에서 상태줄을 식별하지 못해(모드: unknown) "
            "파일 편집 모드 전환을 건너뜁니다 (fail-closed)",
        )

    # 2. 실물 순환 전송 루프: 매 전송 후 화면에서 accept-edits 모드가 확인될 때만 성공 반환
    attempts = 0
    while attempts < max_attempts:
        cmd = [
            "orca",
            "terminal",
            "send",
            "--terminal",
            terminal,
            "--text",
            FILE_EDIT_AUTO_APPROVE_SEQUENCE,
        ]
        code, stdout, stderr = _run_command(cmd, timeout=timeout)
        if code != 0:
            err = (stderr or stdout).strip() or f"종료 코드 {code}"
            return False, f"파일 편집 자동 승인 모드 전환 전송 실패: {err}"
        attempts += 1

        time.sleep(0.3)
        after_text = terminal_read(terminal, timeout=timeout) or terminal_tail(
            terminal, timeout=timeout
        )
        if after_text:
            new_mode = detect_antigravity_mode(after_text)
            if new_mode == "accept-edits":
                return (
                    True,
                    f"파일 편집 자동 승인(accept-edits) 모드로 전환했습니다 ({terminal}, 시도 {attempts}회)",
                )

    return (
        False,
        f"파일 편집 자동 승인 모드 전환 시도 상한({max_attempts}회)을 초과했으나 accept-edits 모드가 확인되지 않았습니다 ({terminal})",
    )


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


def prepare_worker_terminal(
    terminal: str,
    cli_type: str | None = None,
    model: str | None = None,
    launcher: str | None = None,
    force_file_edit: bool = False,
    timeout: int = 30,
) -> dict[str, Any]:
    """워커 기동 후 준비 절차를 순서대로 수행하는 통합 상태 기계입니다.

    1. 메타데이터 기록 (워커 종류, 모델, 런처 등)
    2. 신뢰 확인 대화창 승인 (approve_trust_prompt)
    3. 권한 자동 승인 감시기 부착 (start_auto_approve)
    4. 파일 편집 자동 승인 모드 확보 (enable_file_edit_auto_approve)

    직접 Dispatch 경로와 런처 기동 경로가 모두 이 함수를 공통으로 호출합니다.
    """
    # 1. 메타데이터 기록 갱신 (명시된 정보만 기록)
    meta = read_worker_meta(terminal) or {}
    if cli_type:
        meta["cli_type"] = cli_type
    if model:
        meta["model"] = model
    if launcher:
        meta["launcher"] = launcher
    if cli_type or model or launcher or not meta:
        meta["terminal"] = terminal
        meta["updated_at"] = time.time()
        write_worker_meta(terminal, meta)

    # 2. 신뢰 확인 대화창 승인
    try:
        trust_status = approve_trust_prompt(terminal, timeout=timeout)
    except Exception:
        trust_status = "unreadable"
    trust_ok = trust_status in ("approved", "not_present")

    # 3. 권한 자동 승인 감시기 부착
    try:
        approve_started, approve_detail = start_auto_approve(terminal)
    except Exception as exc:
        approve_started, approve_detail = False, f"자동 승인 감시기 기동 중 예외 발생 ({exc})"

    # 4. 파일 편집 자동 승인 모드 확보 (shift+tab 안전 순환)
    try:
        mode_ok, mode_detail = enable_file_edit_auto_approve(
            terminal,
            timeout=timeout,
            force=force_file_edit,
        )
    except Exception as exc:
        mode_ok, mode_detail = False, f"파일 편집 자동 승인 모드 전환 중 예외 발생 ({exc})"

    overall_ok = (trust_status != "still_present") and approve_started

    return {
        "terminal": terminal,
        "ok": overall_ok,
        "meta": meta,
        "trust_prompt": {
            "status": trust_status,
            "ok": trust_ok,
        },
        "auto_approve_watcher": {
            "status": "started" if approve_started else "failed",
            "detail": approve_detail,
            "ok": approve_started,
        },
        "file_edit_auto_approve": {
            "status": "enabled" if mode_ok else "skipped_or_failed",
            "detail": mode_detail,
            "ok": mode_ok,
        },
    }


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
        parts.append(
            f"완료 보고 전송 시에는 직접 orca orchestration send 를 실행하지 말고 "
            f"`python3 scripts/orca_worker_done_guard.py --capsule {relative_capsule} --report {report_path} --send` "
            "단일 검증 진입점 명령을 실행하십시오."
        )
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
    reviewer_model: str | None = None,
    strict: bool = True,
    max_diff_chars: int | None = None,
    allow_truncated_diff: bool = False,
    terminal: str | None = None,
    builder_model: str | None = None,
    builder_provider: str | None = None,
) -> dict[str, Any]:
    """worker_done 보고를 검증하고 Level 1/Reviewer 검증 파이프라인을 실행합니다."""
    # 자동 승인 감시기 중지 (Task 종료 시 명시적으로 내림)
    target_terminal = terminal
    if not target_terminal and capsule_path.exists():
        with suppress(Exception):
            cap_data = load_capsule(capsule_path)
            if isinstance(cap_data, dict):
                target_terminal = cap_data.get("terminal") or cap_data.get("terminal_handle")
    if target_terminal:
        stop_auto_approve(target_terminal)

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
    code_summ, stdout_summ, stderr_summ = _run_command(
        summarize_cmd, timeout=WORKER_SUMMARY_FINALIZE_TIMEOUT
    )
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
    code_l1, stdout_l1, stderr_l1 = _run_command(level1_cmd, timeout=LEVEL1_FINALIZE_TIMEOUT)
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
        # 리뷰어 모델 결정 (독립 provider 강제)
        actual_reviewer_model: str | None = None
        if reviewer_model is not None:
            actual_reviewer_model = reviewer_model
        else:
            # 빌더의 provider 파악
            b_provider = builder_provider
            if not b_provider and builder_model:
                try:
                    b_provider = provider_for_model(builder_model, strict=False)
                except Exception:
                    b_provider = None
            if not b_provider and target_terminal:
                meta = read_worker_meta(target_terminal)
                if meta and meta.get("model"):
                    try:
                        b_provider = provider_for_model(meta["model"], strict=False)
                    except Exception:
                        b_provider = None
            if not b_provider and capsule_path.exists():
                with suppress(Exception):
                    cap_data = load_capsule(capsule_path)
                    b_model_cap = parse_capsule_scalar(
                        cap_data, "builder_model"
                    ) or parse_capsule_scalar(cap_data, "model")
                    if b_model_cap:
                        b_provider = provider_for_model(b_model_cap, strict=False)
                    if not b_provider:
                        b_provider = parse_capsule_scalar(cap_data, "builder_provider")
            if not b_provider and report_path.exists():
                with suppress(Exception):
                    rep_data = load_report(report_path)
                    if isinstance(rep_data, dict) and rep_data.get("model"):
                        b_provider = provider_for_model(rep_data["model"], strict=False)

            # 위험도 파악
            risk = "medium"
            if capsule_path.exists():
                with suppress(Exception):
                    risk = classify_from_capsule(capsule_path).get("risk", "medium")

            # 독립 리뷰어 모델 라우팅
            if b_provider and b_provider != "unknown":
                try:
                    routed = select_model(
                        role="reviewer", risk=risk, exclude_providers=[b_provider]
                    )
                    actual_reviewer_model = routed["primary_model"]
                except ModelRoutingError as exc:
                    tool_error = True
                    result["reviewer"] = {
                        "error": truncate(f"독립 리뷰어 모델 라우팅 실패: {exc}", 400),
                        "exit_code": 2,
                    }
                    result["exit_code"] = 2
                    return result
            else:
                try:
                    routed = select_model(role="reviewer", risk=risk)
                    actual_reviewer_model = routed["primary_model"]
                except ModelRoutingError as exc:
                    tool_error = True
                    result["reviewer"] = {
                        "error": truncate(f"리뷰어 모델 라우팅 실패: {exc}", 400),
                        "exit_code": 2,
                    }
                    result["exit_code"] = 2
                    return result
                result["reviewer_warning"] = (
                    "빌더 provider 를 알 수 없어 독립 provider 제외를 적용하지 못했습니다."
                )

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
            actual_reviewer_model,
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

    # 정본 스킬 영수증 게이트 (2층 검증)
    if getattr(args, "skip_skill_receipt", False):
        sys.stderr.write(
            "경고: --skip-skill-receipt 지정으로 정본 스킬 영수증 검사를 건너뜁니다.\n"
        )
    else:
        receipt_check = verify_skill_receipt()
        if not receipt_check["ok"]:
            err_msg = receipt_check["reason"]
            fix_cmd = receipt_check.get(
                "fix_command", "python3 scripts/orca_skill_receipt.py issue"
            )
            sys.stderr.write(f"오류 [skill_receipt_gate]: {err_msg}\n")
            sys.stderr.write(f"해소 명령: {fix_cmd}\n")
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "error": "skill_receipt_invalid",
                            "origin": "skill_receipt_gate",
                            "task_id": task_id,
                            "reason": err_msg,
                            "fix_command": fix_cmd,
                            "exit_code": 4,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 4

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


def _extract_preamble(stdout: str) -> str | None:
    """orca orchestration dispatch --return-preamble 결과 JSON 에서 preamble 을 추출합니다."""
    if not stdout or not stdout.strip():
        return None
    try:
        payload = json.loads(stdout)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    res = payload.get("result")
    if isinstance(res, dict) and "preamble" in res:
        return str(res["preamble"])
    if "preamble" in payload:
        return str(payload["preamble"])
    return None


def dispatch_with_fallback(
    task_id: str,
    terminal: str,
    run_id: str | None = None,
    as_json: bool = False,
    timeout: int = 30,
) -> tuple[int, str, str, list[str], dict[str, Any]]:
    """orca orchestration dispatch 를 실행하되, --inject 가 agent_prompt_blocked 로 실패하면
    --return-preamble 로 지시문을 받아 terminal send 로 직접 투입하는 대체 경로를 실행합니다.
    """
    code, stdout, stderr, executed_cmd = dispatch_worker(
        task_id=task_id,
        to_handle=terminal,
        run_id=run_id,
        inject=True,
        as_json=as_json,
        timeout=timeout,
    )

    fallback_info: dict[str, Any] = {
        "fallback_used": False,
        "reason": None,
    }

    err_msg = stderr.strip() or _extract_cli_error(stdout) or ""
    is_blocked = (
        "agent_prompt_blocked" in err_msg.lower()
        or "agent_prompt_blocked" in (stdout or "").lower()
        or "agent_prompt_blocked" in (stderr or "").lower()
    )

    if (code != 0 or not _launch_succeeded(stdout, expect_json=as_json)) and is_blocked:
        sys.stderr.write(
            "경고: orca orchestration dispatch --inject 가 agent_prompt_blocked 로 실패했습니다. "
            "--return-preamble + terminal send 대체 경로로 전환합니다.\n"
        )
        code_p, stdout_p, stderr_p, executed_cmd_p = dispatch_worker(
            task_id=task_id,
            to_handle=terminal,
            run_id=run_id,
            return_preamble=True,
            as_json=True,
            timeout=timeout,
        )
        if code_p == 0 and _launch_succeeded(stdout_p, expect_json=True):
            preamble = _extract_preamble(stdout_p)
            if preamble:
                send_code, send_out, send_err = terminal_send(terminal, preamble, timeout=timeout)
                if send_code != 0:
                    fallback_info["error"] = f"terminal_send_failed: {send_err or send_out}"
                    return send_code, send_out, send_err, executed_cmd_p, fallback_info

                time.sleep(1.0)
                tail_text = terminal_tail(terminal, timeout=timeout) or ""
                if agent_prompt_is_input_caret(tail_text):
                    terminal_send(terminal, "", timeout=timeout)

                fallback_info["fallback_used"] = True
                fallback_info["reason"] = "agent_prompt_blocked"
                fallback_info["preamble_char_len"] = len(preamble)
                return 0, stdout_p, "", executed_cmd_p, fallback_info
            else:
                fallback_info["error"] = "preamble_extraction_failed"
        else:
            fallback_info["error"] = f"return_preamble_failed: {stderr_p or stdout_p}"

    return code, stdout, stderr, executed_cmd, fallback_info


LAUNCHER_WAIT_MARKERS: tuple[str, ...] = (
    "preamble 대기 중",
    "preamble 대기 중:",
    "wait_for_preamble",
)

LAUNCHER_STARTED_MARKERS: tuple[str, ...] = (
    "기동: agy",
    "기동: opencode",
    "기동: kimi",
    "기동:",
)


def resolve_terminal_worktree(terminal: str, repo: Path | str = ".") -> Path | None:
    """터미널이 속한 워크트리 경로를 확인합니다.

    1. 터미널 메타데이터 ({terminal}.meta.json) 에서 worktree 조회
    2. orca terminal show --terminal <handle> --json 에서 worktree/worktreePath/cwd 조회
    3. orca terminal list --json 에서 handle 일치 항목의 worktree/worktreePath/cwd 조회
    """
    meta = read_worker_meta(terminal)
    if meta and isinstance(meta, dict):
        wt = meta.get("worktree") or meta.get("worktree_path")
        if wt and isinstance(wt, str) and wt.strip():
            cleaned = wt.strip()
            if cleaned.startswith("path:"):
                cleaned = cleaned[5:]
            return Path(cleaned).resolve()

    cmd = ["orca", "terminal", "show", "--terminal", terminal, "--json"]
    code, stdout, _ = _run_command(cmd, timeout=10)
    if code == 0 and stdout.strip():
        try:
            payload = json.loads(stdout)
            if isinstance(payload, dict) and payload.get("ok") is not False:
                t_info = (payload.get("result") or {}).get("terminal") or {}
                wt = (
                    t_info.get("worktree")
                    or t_info.get("worktreePath")
                    or t_info.get("worktree_path")
                    or t_info.get("cwd")
                )
                if wt and isinstance(wt, str) and wt.strip():
                    cleaned = wt.strip()
                    if cleaned.startswith("path:"):
                        cleaned = cleaned[5:]
                    return Path(cleaned).resolve()
        except (json.JSONDecodeError, ValueError):
            pass

    cmd = ["orca", "terminal", "list", "--json"]
    code, stdout, _ = _run_command(cmd, timeout=10)
    if code == 0 and stdout.strip():
        try:
            payload = json.loads(stdout)
            if isinstance(payload, dict) and payload.get("ok") is not False:
                terminals = (payload.get("result") or {}).get("terminals") or []
                for item in terminals:
                    if not isinstance(item, dict):
                        continue
                    if item.get("handle") == terminal or item.get("id") == terminal:
                        wt = (
                            item.get("worktree")
                            or item.get("worktreePath")
                            or item.get("worktree_path")
                            or item.get("cwd")
                        )
                        if wt and isinstance(wt, str) and wt.strip():
                            cleaned = wt.strip()
                            if cleaned.startswith("path:"):
                                cleaned = cleaned[5:]
                            return Path(cleaned).resolve()
        except (json.JSONDecodeError, ValueError):
            pass

    return None


def verify_launcher_pickup(
    terminal: str,
    timeout_sec: float = 30.0,
    poll_interval_sec: float = 0.5,
    sleep_fn=time.sleep,
    read_fn=None,
) -> tuple[bool, str]:
    """런처가 preamble 파일을 읽고 실제 CLI 를 기동했는지 확인합니다.

    1. 터미널 출력에서 'preamble 대기 중' 대기 상태가 해소되었는지 확인
    2. '기동:' 문구 또는 에이전트 프롬프트/신뢰 확인 대화창/모드 표지 출현 확인
    3. 시한(timeout_sec) 초과 시 실패(False) 반환
    """
    if read_fn is None:

        def _default_read(h: str) -> str | None:
            return terminal_read(h) or terminal_tail(h)

        read_fn = _default_read

    deadline = time.monotonic() + max(0.0, timeout_sec)
    last_text = ""
    while True:
        text = read_fn(terminal)
        if text:
            last_text = text
            lowered = text.lower()
            has_started = any(marker in text for marker in LAUNCHER_STARTED_MARKERS)
            has_agent = (
                agent_prompt_ready(text)
                or has_trust_prompt(text)
                or detect_antigravity_mode(text) in ("accept-edits", "normal", "plan")
                or "gemini" in lowered
                or "antigravity" in lowered
            )
            is_still_waiting = (
                any(marker in text for marker in LAUNCHER_WAIT_MARKERS)
                and not has_started
                and not has_agent
            )

            if (has_started or has_agent) and not is_still_waiting:
                return (
                    True,
                    f"런처가 preamble 을 성공적으로 이어받아 에이전트를 기동했습니다 ({terminal})",
                )

        if time.monotonic() >= deadline:
            break
        sleep_fn(poll_interval_sec)

    return (
        False,
        f"런처 기동 확인 시한({timeout_sec:.0f}초) 초과: 터미널 {terminal} 에서 preamble 이어받기가 확인되지 않았습니다 (최근 출력: {truncate(last_text, 100)!r})",
    )


def resolve_dispatch_model(
    args_model: str | None,
    capsule_text: str,
    capsule_path: Path | str | None = None,
    intent: dict[str, Any] | None = None,
    builder_model: str | None = None,
    builder_provider: str | None = None,
    exclude_providers: list[str] | None = None,
) -> dict[str, Any]:
    """Dispatch 시 사용할 모델, 배정 근거, 경고 등을 판정합니다.

    우선순위:
      1. args_model (명시 지정) -> 그대로 사용하되 상위 모델 지정 시 경고.
      2. orca_model_router.select_model(role, risk) -> 배정표 기반 최적 모델 선택.
      3. 실패 시 DEFAULT_MODEL 로 fallback. (단, 리뷰어 독립성/provider 제외 실패는 fail-closed)
    """
    role = (
        (intent.get("role") if intent else None)
        or parse_capsule_scalar(capsule_text, "role")
        or "builder"
    )
    risk = (intent.get("risk") if intent else None) or parse_capsule_scalar(capsule_text, "risk")
    if not risk:
        if capsule_path and Path(capsule_path).is_file():
            try:
                classified = classify_from_capsule(capsule_path)
                risk = classified.get("risk")
            except Exception:
                risk = None
        if not risk:
            risk = classify_risk(capsule_text)

    if risk not in ("low", "medium", "high"):
        risk = "medium"

    has_write = (
        capsule_has_write_scope(capsule_path)
        if (capsule_path and Path(capsule_path).is_file())
        else len(parse_capsule_list(capsule_text, "allowed_write_files")) > 0
    )

    recommended_pool: str | None = None
    recommended_model: str | None = None
    router_error: str | None = None

    # Reviewer 역할인 경우 빌더 provider 제외 적용
    effective_exclude_providers: list[str] = list(exclude_providers) if exclude_providers else []
    builder_prov_unknown = False
    resolved_builder_provider: str | None = None

    if role == "reviewer":
        b_prov = builder_provider
        if not b_prov and builder_model:
            try:
                b_prov = provider_for_model(builder_model, strict=False)
            except Exception:
                b_prov = None
        if not b_prov and intent:
            b_model = intent.get("builder_model")
            if b_model:
                try:
                    b_prov = provider_for_model(b_model, strict=False)
                except Exception:
                    b_prov = None
            if not b_prov:
                b_prov = intent.get("builder_provider")
        if not b_prov and capsule_path and Path(capsule_path).is_file():
            with suppress(Exception):
                cap_txt = load_capsule(capsule_path)
                b_model = parse_capsule_scalar(cap_txt, "builder_model")
                if b_model:
                    b_prov = provider_for_model(b_model, strict=False)
                if not b_prov:
                    b_prov = parse_capsule_scalar(cap_txt, "builder_provider")
        if not b_prov:
            with suppress(Exception):
                b_model = parse_capsule_scalar(capsule_text, "builder_model")
                if b_model:
                    b_prov = provider_for_model(b_model, strict=False)
                if not b_prov:
                    b_prov = parse_capsule_scalar(capsule_text, "builder_provider")

        resolved_builder_provider = b_prov
        if b_prov and b_prov != "unknown":
            if b_prov not in effective_exclude_providers:
                effective_exclude_providers.append(b_prov)
        else:
            builder_prov_unknown = True

    try:
        routed = select_model(
            role=role,
            risk=risk,
            allow_free=False,
            has_write_scope=has_write,
            exclude_providers=effective_exclude_providers if effective_exclude_providers else None,
        )
        recommended_pool = routed.get("primary_pool")
        recommended_model = routed.get("primary_model")
    except Exception as exc:
        router_error = str(exc)
        if not args_model and (role == "reviewer" or exclude_providers):
            # 독립 provider 제외 실패 시 같은 계열로 fallback 하지 않고 fail-closed
            raise

    warning: str | None = None
    if args_model:
        model = args_model
        source = "explicit"
        reason = f"명시 지정: {args_model} (선언 role={role}, risk={risk})"
        if recommended_model:
            model_rank = MODEL_TIER_RANK.get(args_model, 0)
            rec_rank = MODEL_TIER_RANK.get(recommended_model, 0)
            if model_rank > rec_rank:
                warning = (
                    f"배정표 기준 권장 모델({recommended_model}, role={role}, risk={risk})보다 "
                    f"상위 모델({args_model})이 명시 지정되었습니다."
                )
                sys.stderr.write(f"경고: {warning}\n")
    else:
        if recommended_model:
            model = recommended_model
            source = "router"
            reason = (
                f"라우터 자동 배정: {model} (role={role}, risk={risk}, pool={recommended_pool})"
            )
        else:
            model = DEFAULT_MODEL
            source = "fallback_default"
            reason = (
                f"라우터 호출 실패({router_error})로 기본 모델({DEFAULT_MODEL}) 배정 "
                f"(role={role}, risk={risk})"
            )
            warning = f"모델 라우팅 실패로 기본값({DEFAULT_MODEL})으로 대체합니다: {router_error}"
            sys.stderr.write(f"경고: {warning}\n")

    if role == "reviewer" and builder_prov_unknown:
        unknown_warn = "빌더 provider 를 알 수 없어 독립 provider 제외를 적용하지 못했습니다."
        warning = f"{warning}; {unknown_warn}" if warning else unknown_warn

    return {
        "model": model,
        "source": source,
        "role": role,
        "risk": risk,
        "reason": reason,
        "warning": warning,
        "builder_provider": resolved_builder_provider
        or ("unknown" if role == "reviewer" else None),
        "recommended_model": recommended_model,
        "recommended_pool": recommended_pool,
    }


def create_rework_capsule(
    original_capsule_text: str,
    new_task_id: str,
    new_capsule_path: Path,
    rejection_reason: str,
    previous_report: dict[str, Any] | None = None,
    run_id: str = DEFAULT_RUN_ID,
) -> str:
    """기존 Capsule 과 반려 사유를 바탕으로 재작업용 Capsule YAML 을 생성합니다."""
    # 1. task_id 교체
    new_text = re.sub(
        r'task_id:\s*"?[^"\n]+"?',
        f'task_id: "{new_task_id}"',
        original_capsule_text,
        count=1,
    )
    if run_id:
        new_text = re.sub(
            r'run_id:\s*"?[^"\n]+"?',
            f'run_id: "{run_id}"',
            new_text,
            count=1,
        )

    # 2. report_path 교체 (새 Task ID 에 맞게)
    new_report_rel = f".orca/capsules/{new_task_id}/worker_done.json"
    new_text = re.sub(
        r'report_path:\s*"?[^"\n]+"?',
        f'report_path: "{new_report_rel}"',
        new_text,
        count=1,
    )

    # 3. why_now 블록에 반려 사유 추가
    orig_id = parse_capsule_scalar(original_capsule_text, "task_id") or "이전 시도"
    rework_why_now = (
        f"\n  이전 시도(task_id: {orig_id})가 반려되었습니다. 반려 사유: {rejection_reason}"
    )
    if "why_now: >" in new_text:
        new_text = new_text.replace(
            "why_now: >",
            f"why_now: >{rework_why_now}",
            1,
        )
    elif "why_now:" in new_text:
        new_text = re.sub(
            r"(why_now:\s*>[^\n]*\n)",
            rf"\1  {rework_why_now.strip()}\n",
            new_text,
            count=1,
        )

    # 4. ground_truth 에 반려 사실 추가
    escaped_reason = _escape(rejection_reason)
    gt_addition = (
        f'  - fact: "이전 시도({orig_id}) 반려 사유: {escaped_reason}"\n'
        f'    evidence: "코디네이터 반려 기록"\n'
        f"    recheck: false\n"
    )
    if previous_report and isinstance(previous_report, dict):
        prev_commit = previous_report.get("commit") or ""
        if prev_commit:
            gt_addition += (
                f'  - fact: "이전 시도 커밋: {prev_commit}"\n'
                f'    evidence: "이전 worker_done 보고서"\n'
                f"    recheck: false\n"
            )

    if "ground_truth:\n" in new_text:
        new_text = new_text.replace("ground_truth:\n", f"ground_truth:\n{gt_addition}", 1)

    # 5. required_change 에 반려 사유 해결 지시 추가
    rc_addition = f'  - "반려 사유 해결: {escaped_reason}"\n'
    if "required_change:\n" in new_text:
        new_text = new_text.replace("required_change:\n", f"required_change:\n{rc_addition}", 1)

    # 6. allowed_read_files 에 새 capsule.yaml 경로 추가
    new_relative_capsule = worktree_relative_capsule_path(new_capsule_path)
    old_read_files = parse_capsule_list(original_capsule_text, "allowed_read_files")
    if new_relative_capsule not in old_read_files and "allowed_read_files:\n" in new_text:
        new_text = new_text.replace(
            "allowed_read_files:\n",
            f'allowed_read_files:\n  - "{new_relative_capsule}"\n',
            1,
        )

    return new_text


def cmd_rework(args: argparse.Namespace) -> int:
    task_id = args.task_id
    if not task_id:
        sys.stderr.write("오류: --task-id 는 필수입니다.\n")
        return 2

    reason = (args.reason or "").strip()
    if not reason:
        sys.stderr.write("오류: --reason (반려 사유)는 필수입니다.\n")
        return 2

    capsule_dir = Path(args.capsule_dir)
    capsule_path = (
        Path(args.capsule).resolve()
        if args.capsule
        else (capsule_dir / task_id / "capsule.yaml").resolve()
    )
    if not capsule_path.is_file():
        sys.stderr.write(f"오류: 기존 Capsule 파일을 찾을 수 없습니다: {capsule_path}\n")
        return 2

    capsule_text = load_capsule(capsule_path)

    report_path = (
        Path(args.report).resolve()
        if args.report
        else (capsule_dir / task_id / "worker_done.json").resolve()
    )
    prev_report = None
    if report_path.is_file():
        try:
            prev_report = load_report(report_path)
        except Exception:
            prev_report = None

    rejection_record = {
        "task_id": task_id,
        "rejected_at": time.time(),
        "reason": reason,
        "report_path": str(report_path) if report_path.is_file() else None,
        "previous_report": prev_report,
    }
    rejection_file = capsule_path.parent / "rejection.json"
    _write_json_atomic(rejection_file, rejection_record)

    new_task_id = args.new_task_id or f"{task_id}_rework"
    new_task_dir = capsule_dir / new_task_id
    new_task_dir.mkdir(parents=True, exist_ok=True)
    new_capsule_path = (new_task_dir / "capsule.yaml").resolve()

    new_capsule_text = create_rework_capsule(
        original_capsule_text=capsule_text,
        new_task_id=new_task_id,
        new_capsule_path=new_capsule_path,
        rejection_reason=reason,
        previous_report=prev_report,
        run_id=args.run_id,
    )
    new_capsule_path.write_text(new_capsule_text, encoding="utf-8")

    spec = build_task_spec(
        parse_capsule_scalar(new_capsule_text, "objective") or "", new_capsule_path
    )
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
    elif args.task_id:
        cmd.extend(["--task-title", f"재작업: {args.task_id} ({reason[:30]})"])
    if args.display_name:
        cmd.extend(["--display-name", args.display_name])

    code, stdout, _stderr = _run_command(cmd)
    actual_task_id = new_task_id
    actual_capsule_path = new_capsule_path

    if code == 0:
        payload = _maybe_json(stdout)
        created_id = None
        if isinstance(payload, dict):
            created_id = ((payload.get("result") or {}).get("task") or {}).get("id")
        if created_id and str(created_id) != new_task_id:
            actual_task_id = str(created_id)
            actual_capsule_dir = capsule_dir / actual_task_id
            actual_capsule_dir.mkdir(parents=True, exist_ok=True)
            actual_capsule_path = (actual_capsule_dir / "capsule.yaml").resolve()
            final_capsule_text = create_rework_capsule(
                original_capsule_text=capsule_text,
                new_task_id=actual_task_id,
                new_capsule_path=actual_capsule_path,
                rejection_reason=reason,
                previous_report=prev_report,
                run_id=args.run_id,
            )
            actual_capsule_path.write_text(final_capsule_text, encoding="utf-8")
            if new_capsule_path != actual_capsule_path:
                new_capsule_path.write_text(final_capsule_text, encoding="utf-8")

    new_report_rel = (
        parse_capsule_scalar(new_capsule_text, "report_path")
        or f".orca/capsules/{actual_task_id}/worker_done.json"
    )

    result_payload = {
        "status": "rework_created",
        "original_task_id": task_id,
        "new_task_id": actual_task_id,
        "rejection_reason": reason,
        "rejection_record": str(rejection_file),
        "capsule": str(actual_capsule_path),
        "new_report_path": new_report_rel,
        "exit_code": 0,
    }

    if args.json:
        print(json.dumps(result_payload, ensure_ascii=False, indent=2))
    else:
        print(f"재작업 Task 생성 완료: {actual_task_id} (원래 Task: {task_id})")
        print(f"반려 사유: {reason}")
        print(f"반려 기록 저장: {rejection_file}")
        print(f"새 Capsule: {actual_capsule_path}")
        print(f"새 보고 경로: {new_report_rel}")

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

    # 정본 스킬 영수증 게이트 (2층 검증)
    if getattr(args, "skip_skill_receipt", False):
        sys.stderr.write(
            "경고: --skip-skill-receipt 지정으로 정본 스킬 영수증 검사를 건너뜁니다.\n"
        )
    else:
        receipt_check = verify_skill_receipt()
        if not receipt_check["ok"]:
            err_msg = receipt_check["reason"]
            fix_cmd = receipt_check.get(
                "fix_command", "python3 scripts/orca_skill_receipt.py issue"
            )
            sys.stderr.write(f"오류 [skill_receipt_gate]: {err_msg}\n")
            sys.stderr.write(f"해소 명령: {fix_cmd}\n")
            if getattr(args, "json", False):
                print(
                    json.dumps(
                        {
                            "error": "skill_receipt_invalid",
                            "origin": "skill_receipt_gate",
                            "task_id": task_id,
                            "reason": err_msg,
                            "fix_command": fix_cmd,
                            "exit_code": 4,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 4

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
            for p in parse_capsule_list(capsule, "required_write_files"):
                validate_contained_path(p, field_name="required_write_files")
            rep_p = parse_capsule_scalar(capsule, "report_path")
            if rep_p:
                validate_contained_path(rep_p, field_name="report_path")
        except ValueError as err:
            sys.stderr.write(f"오류: {err}\n")
            return 2

        # 동일 Task 의 실제 Task Capsule 사본과 spec Capsule 사본 간의 drift 검사
        actual_task_capsule_path = (capsule_dir / task_id / "capsule.yaml").resolve()
        if (
            actual_task_capsule_path != capsule_path
            and actual_task_capsule_path.is_file()
            and capsule_path.is_file()
        ):
            actual_capsule_text = actual_task_capsule_path.read_text(encoding="utf-8")
            matched, diff_detail = compare_capsule_contracts(capsule, actual_capsule_text)
            if not matched:
                err_msg = f"동일 Task Capsule 사본 간 계약 불일치 (drift 감지): {diff_detail}"
                sys.stderr.write(f"오류 [capsule_spec_error]: {err_msg}\n")
                if args.json:
                    print(
                        json.dumps(
                            {
                                "error": "capsule_spec_drift",
                                "origin": "capsule_spec_error",
                                "task_id": task_id,
                                "reason": err_msg,
                                "spec_capsule": str(capsule_path),
                                "actual_capsule": str(actual_task_capsule_path),
                                "exit_code": 1,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                return 1

    else:
        task_capsule_dir = capsule_dir / task_id
        task_capsule_dir.mkdir(parents=True, exist_ok=True)
        # 워커는 다른 워크트리에서 돌기 때문에 상대 경로로는 Capsule 을 찾지 못합니다.
        capsule_path = (task_capsule_dir / "capsule.yaml").resolve()

        # Intent 파일명 기반 사본과 실제 task_id 사본 간 drift 검사
        intent_stem_capsule = (capsule_dir / intent_path.stem / "capsule.yaml").resolve()
        if (
            intent_stem_capsule != capsule_path
            and intent_stem_capsule.is_file()
            and capsule_path.is_file()
        ):
            stem_text = intent_stem_capsule.read_text(encoding="utf-8")
            task_text = capsule_path.read_text(encoding="utf-8")
            matched, diff_detail = compare_capsule_contracts(stem_text, task_text)
            if not matched:
                err_msg = f"동일 Task Capsule 사본 간 계약 불일치 (drift 감지): {diff_detail}"
                sys.stderr.write(f"오류 [capsule_spec_error]: {err_msg}\n")
                if args.json:
                    print(
                        json.dumps(
                            {
                                "error": "capsule_spec_drift",
                                "origin": "capsule_spec_error",
                                "task_id": task_id,
                                "reason": err_msg,
                                "spec_capsule": str(intent_stem_capsule),
                                "actual_capsule": str(capsule_path),
                                "exit_code": 1,
                            },
                            ensure_ascii=False,
                            indent=2,
                        )
                    )
                return 1

        try:
            capsule = expand_intent_to_capsule(
                intent,
                task_id=task_id,
                run_id=args.run_id,
                capsule_path=capsule_path,
            )
        except ValueError as err:
            sys.stderr.write(f"오류 [capsule_spec_error]: {err}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "capsule_expand_error",
                            "origin": "capsule_spec_error",
                            "task_id": task_id,
                            "reason": str(err),
                            "exit_code": 2,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

        capsule_path.write_text(capsule, encoding="utf-8")

    # required_write_files 가 allowed_write_files 의 부분집합인지 재확인 (fail-closed)
    req_write_parsed = parse_capsule_list(capsule, "required_write_files")
    all_write_parsed = parse_capsule_list(capsule, "allowed_write_files")
    excess_req_parsed = write_scope_excess(req_write_parsed, all_write_parsed)
    if excess_req_parsed:
        err_msg = f"required_write_files 가 allowed_write_files 의 부분집합이 아닙니다: {', '.join(excess_req_parsed)}"
        sys.stderr.write(f"오류 [capsule_spec_error]: {err_msg}\n")
        if args.json:
            print(
                json.dumps(
                    {
                        "error": "required_write_files_not_subset",
                        "origin": "capsule_spec_error",
                        "task_id": task_id,
                        "violations": excess_req_parsed,
                        "exit_code": 1,
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        return 1

    model_resolution = resolve_dispatch_model(
        args_model=args.model,
        capsule_text=capsule,
        capsule_path=capsule_path,
        intent=intent,
    )
    model = model_resolution["model"]

    if args.dry_run:
        if args.json:
            print(
                json.dumps(
                    {
                        "dry_run": True,
                        "capsule": str(capsule_path),
                        "model": model,
                        "model_source": model_resolution["source"],
                        "model_reason": model_resolution["reason"],
                        "role": model_resolution["role"],
                        "risk": model_resolution["risk"],
                        "warning": model_resolution["warning"],
                        "task_id": task_id,
                        "char_count": char_len(capsule),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
        else:
            print(f"[Dry-run] Capsule: {capsule_path}")
            print(f"[Dry-run] Model:   {model} ({model_resolution['source']})")
            print(f"[Dry-run] Role:    {model_resolution['role']}")
            print(f"[Dry-run] Risk:    {model_resolution['risk']}")
            print(f"[Dry-run] Reason:  {model_resolution['reason']}")
            if model_resolution["warning"]:
                print(f"[Dry-run] 경고:    {model_resolution['warning']}")
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

    if getattr(args, "skip_settled_session_check", False):
        sys.stderr.write(
            "경고: --skip-settled-session-check 지정으로 완료 세션 잔류 검사를 건너뜁니다.\n"
        )
    else:
        settled = check_settled_sessions(run_id=args.run_id)
        if not settled.get("allowed"):
            lingering = settled.get("lingering") or []
            occupying = [
                f"{item.get('task_id')}@{item.get('handle')}"
                for item in lingering
                if isinstance(item, dict)
            ]
            err_msg = str(settled.get("reason") or "completed 워커 터미널이 남아 있습니다")
            sys.stderr.write(f"오류: {err_msg}\n")
            if occupying:
                sys.stderr.write(f"잔류: {', '.join(occupying)}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "settled_session_lingering",
                            "allowed": False,
                            "task_id": task_id,
                            "lingering": lingering,
                            "reason": err_msg,
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
    pre_dispatch_warnings: list[str] = []
    dispatch_started_at = time.time()
    fallback_info: dict[str, Any] = {"fallback_used": False}
    launcher_mode = bool(getattr(args, "launcher", None))
    worktree_path: Path | None = None
    preamble_file: Path | None = None
    launcher_pickup_detail: str | None = None

    if args.terminal and launcher_mode:
        # 런처 경로: --return-preamble 로 지시문을 받아 <워크트리>/.orca/preamble.txt 에 쓴 뒤 기동 확인
        if getattr(args, "worktree", None) and args.worktree != "new-child":
            wt_raw = args.worktree.strip()
            if wt_raw.startswith("path:"):
                wt_raw = wt_raw[5:]
            worktree_path = Path(wt_raw).resolve()
        else:
            worktree_path = resolve_terminal_worktree(args.terminal, repo=args.repo)

        repo_root = Path(args.repo).resolve()
        if worktree_path is None:
            err_msg = (
                f"런처 기동 실패: 워커 터미널 {args.terminal} 의 워크트리 경로를 확인할 수 없습니다. "
                "--worktree 로 워크트리 경로를 명시하십시오."
            )
            sys.stderr.write(f"오류: {err_msg}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "launcher_worktree_unresolved",
                            "task_id": task_id,
                            "capsule": str(capsule_path),
                            "terminal": args.terminal,
                            "exit_code": 2,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

        if worktree_path == repo_root:
            err_msg = (
                f"런처 기동 실패: 주 저장소({repo_root})에는 preamble.txt 를 쓸 수 없습니다. "
                "격리 워크트리 경로를 지정하십시오."
            )
            sys.stderr.write(f"오류: {err_msg}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "launcher_main_repo_write_forbidden",
                            "task_id": task_id,
                            "capsule": str(capsule_path),
                            "terminal": args.terminal,
                            "worktree": str(worktree_path),
                            "exit_code": 2,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

        # 런처 경로는 Antigravity 전용입니다. worker-start 가 받는 claude/codex/cursor 는
        # 이 분기로 오지 않으므로 --agent 가 없으면 antigravity 로 확정합니다.
        detected_cli = args.agent or "antigravity"
        launcher_val = (
            args.launcher
            if isinstance(args.launcher, str) and args.launcher
            else "scripts/orca_agy_launch.py"
        )
        meta = read_worker_meta(args.terminal) or {}
        meta["cli_type"] = detected_cli
        meta["model"] = model
        meta["launcher"] = launcher_val
        meta["worktree"] = str(worktree_path)
        meta["terminal"] = args.terminal
        meta["updated_at"] = time.time()
        write_worker_meta(args.terminal, meta)

        skip_auto_approve = (
            getattr(args, "skip_auto_approve_check", False)
            or os.environ.get("ORCA_DISABLE_AUTO_APPROVE") == "1"
        )
        approve_started, approve_detail = start_auto_approve(args.terminal)
        if approve_started:
            sys.stderr.write(f"권한 자동 승인 감시기를 붙였습니다. 로그: {approve_detail}\n")
        elif skip_auto_approve:
            if getattr(args, "skip_auto_approve_check", False):
                sys.stderr.write(
                    f"경고: --skip-auto-approve-check 지정으로 권한 자동 승인 감시기 부착 실패를 무시하고 진행합니다: {approve_detail}\n"
                )
            else:
                sys.stderr.write(
                    f"안내: ORCA_DISABLE_AUTO_APPROVE=1 지정으로 권한 자동 승인 감시기 부착을 건너뜁니다: {approve_detail}\n"
                )
        else:
            err_msg = (
                f"권한 자동 승인 감시기 부착 실패: {approve_detail}. "
                "기본값에서 fail-closed 로 Dispatch 를 중단합니다. "
                "의도적으로 우회하려면 --skip-auto-approve-check 를 사용하십시오."
            )
            sys.stderr.write(f"오류: {err_msg}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "auto_approve_watcher_failed",
                            "task_id": task_id,
                            "capsule": str(capsule_path),
                            "terminal": args.terminal,
                            "detail": approve_detail,
                            "exit_code": 2,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

        sys.stderr.write(
            f"런처 경로 Dispatch 중... (task={task_id}, terminal={args.terminal}, worktree={worktree_path})\n"
        )
        code, stdout, stderr, executed_cmd = dispatch_worker(
            task_id=task_id,
            to_handle=args.terminal,
            run_id=args.run_id if args.run_id != DEFAULT_RUN_ID else None,
            return_preamble=True,
            as_json=True,
        )
        launch_cmd = shlex.join(executed_cmd)
        if code != 0 or not _launch_succeeded(stdout, expect_json=True):
            err_msg = stderr.strip() or _extract_cli_error(stdout) or "알 수 없는 오류"
            sys.stderr.write(f"오류: 런처 Dispatch 실패 (종료 코드 {code}): {err_msg}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "launcher_dispatch_failed",
                            "task_id": task_id,
                            "detail": err_msg,
                            "exit_code": code or 2,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return code or 2

        preamble = _extract_preamble(stdout)
        if not preamble:
            err_msg = f"런처 Dispatch 결과에서 preamble 추출 실패: {stdout}"
            sys.stderr.write(f"오류: {err_msg}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "preamble_extraction_failed",
                            "task_id": task_id,
                            "detail": err_msg,
                            "exit_code": 2,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

        preamble_file = worktree_path / ".orca" / "preamble.txt"
        preamble_file.parent.mkdir(parents=True, exist_ok=True)
        preamble_file.write_text(preamble, encoding="utf-8")
        sys.stderr.write(f"preamble 작성 완료: {preamble_file} ({len(preamble)}자)\n")

        pickup_ok, launcher_pickup_detail = verify_launcher_pickup(args.terminal, timeout_sec=30.0)
        if not pickup_ok:
            sys.stderr.write(f"오류: {launcher_pickup_detail}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "launcher_pickup_timeout",
                            "task_id": task_id,
                            "terminal": args.terminal,
                            "detail": launcher_pickup_detail,
                            "exit_code": 3,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 3

        sys.stderr.write(f"{launcher_pickup_detail}\n")

    elif args.terminal:
        detected_cli = args.agent or (
            "antigravity" if (args.model and "gemini" in args.model.lower()) else None
        )
        prep = prepare_worker_terminal(
            terminal=args.terminal,
            cli_type=detected_cli,
            model=args.model,
            force_file_edit=getattr(args, "enable_file_edit_auto_approve", False),
        )

        trust_status = prep["trust_prompt"]["status"]
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
            pre_dispatch_warnings.append(
                "trust_prompt_unreadable"
                if trust_status == "unreadable"
                else "terminal_not_settled"
            )
            sys.stderr.write(
                f"경고: 터미널 {args.terminal} 의 Dispatch 전 상태가 {trust_status} 입니다. "
                "Dispatch 이후 도달을 확인합니다.\n"
            )

        skip_auto_approve = (
            getattr(args, "skip_auto_approve_check", False)
            or os.environ.get("ORCA_DISABLE_AUTO_APPROVE") == "1"
        )
        if prep["auto_approve_watcher"]["ok"]:
            sys.stderr.write(
                f"권한 자동 승인 감시기를 붙였습니다. 로그: {prep['auto_approve_watcher']['detail']}\n"
            )
        elif skip_auto_approve:
            if getattr(args, "skip_auto_approve_check", False):
                sys.stderr.write(
                    f"경고: --skip-auto-approve-check 지정으로 권한 자동 승인 감시기 부착 실패를 무시하고 진행합니다: {prep['auto_approve_watcher']['detail']}\n"
                )
            else:
                sys.stderr.write(
                    f"안내: ORCA_DISABLE_AUTO_APPROVE=1 지정으로 권한 자동 승인 감시기 부착을 건너뜁니다: {prep['auto_approve_watcher']['detail']}\n"
                )
        else:
            err_msg = (
                f"권한 자동 승인 감시기 부착 실패: {prep['auto_approve_watcher']['detail']}. "
                "기본값에서 fail-closed 로 Dispatch 를 중단합니다. "
                "의도적으로 우회하려면 --skip-auto-approve-check 를 사용하십시오."
            )
            sys.stderr.write(f"오류: {err_msg}\n")
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "auto_approve_watcher_failed",
                            "task_id": task_id,
                            "capsule": str(capsule_path),
                            "terminal": args.terminal,
                            "detail": prep["auto_approve_watcher"]["detail"],
                            "exit_code": 2,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

        if prep["file_edit_auto_approve"]["ok"]:
            sys.stderr.write(f"파일 편집 자동 승인 모드 전환을 전송했습니다 ({args.terminal}).\n")
        else:
            sys.stderr.write(
                f"파일 편집 자동 승인 모드 전환 건너뜀: {prep['file_edit_auto_approve']['detail']}\n"
            )

        sys.stderr.write(f"터미널 부착 Dispatch 중... (task={task_id}, terminal={args.terminal})\n")
        code, stdout, stderr, executed_cmd, fallback_info = dispatch_with_fallback(
            task_id=task_id,
            terminal=args.terminal,
            run_id=args.run_id if args.run_id != DEFAULT_RUN_ID else None,
            as_json=args.json,
        )
        launch_cmd = shlex.join(executed_cmd)
        if fallback_info.get("fallback_used"):
            sys.stderr.write(
                "안내: --inject 실패로 --return-preamble 대체 경로를 통해 지시를 투입했습니다.\n"
            )
    else:
        if launcher_mode:
            sys.stderr.write(
                "오류: --launcher 는 --terminal 과 함께 사용해야 합니다. "
                "런처가 실행 중인 터미널 핸들을 --terminal 로 지정하십시오.\n"
            )
            if args.json:
                print(
                    json.dumps(
                        {
                            "error": "launcher_terminal_missing",
                            "task_id": task_id,
                            "capsule": str(capsule_path),
                            "exit_code": 2,
                        },
                        ensure_ascii=False,
                        indent=2,
                    )
                )
            return 2

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
        code, stdout, stderr, executed_cmd = worker_start(
            task_id=task_id,
            agent_id=args.agent,
            model=model,
            worktree=args.worktree,
            name=worktree_name if args.worktree.startswith("new-") else None,
            repo=args.repo,
            as_json=args.json,
        )
        launch_cmd = shlex.join(executed_cmd)

    if code == 0 and _launch_succeeded(stdout, expect_json=args.json or launcher_mode):
        try:
            reliability_tracking = _start_reliability_tracking(
                capsule_path,
                task_id,
                model,
                dispatch_started_at,
            )
        except Exception as exc:
            reliability_tracking = {"status": "error", "reason": str(exc)}

        # 상시 감시기(orca_worker_watch --watch) 자동 배경 기동
        try:
            watch_started, watch_detail = start_worker_watch(args.repo)
            worker_watch_info = {
                "status": "started" if watch_started else "skipped_or_failed",
                "detail": watch_detail,
                "ok": watch_started,
            }
        except Exception as exc:
            worker_watch_info = {"status": "error", "detail": str(exc), "ok": False}

        if launcher_mode:
            notice = {
                "status": "launcher_preamble_delivered",
                "preamble_file": str(preamble_file),
            }
            delivery_check = "verified_launcher_pickup"
        else:
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
            payload["model"] = model
            payload["model_source"] = model_resolution["source"]
            payload["model_reason"] = model_resolution["reason"]
            payload["role"] = model_resolution["role"]
            payload["risk"] = model_resolution["risk"]
            payload["model_warning"] = model_resolution["warning"]
            payload["capsule_notice"] = notice
            payload["pre_dispatch_warnings"] = pre_dispatch_warnings
            payload["delivery_check"] = delivery_check
            payload["delivery_unverified"] = delivery_unverified
            payload["dispatch_fallback"] = fallback_info
            payload["reliability_tracking"] = reliability_tracking
            payload["worker_watch"] = worker_watch_info
            if launcher_mode:
                payload["launcher"] = {
                    "used": True,
                    "launcher": launcher_val if "launcher_val" in locals() else str(args.launcher),
                    "worktree": str(worktree_path) if worktree_path else None,
                    "preamble_file": str(preamble_file) if preamble_file else None,
                    "pickup": launcher_pickup_detail,
                }
            payload["exit_code"] = exit_code
            print(json.dumps(payload, ensure_ascii=False, indent=2))
        else:
            print(f"워커 기동 완료:\n{stdout}")
            print(
                f"모델 배정: {model} ({model_resolution['source']}, {model_resolution['reason']})"
            )
            print(f"Capsule 고지: {notice['status']}")
            if launcher_mode and launcher_pickup_detail:
                print(f"런처 기동: {launcher_pickup_detail}")
            if reliability_tracking["status"] == "tracking":
                print(f"신뢰도 추적: {reliability_tracking['pool']}/{reliability_tracking['role']}")
            if worker_watch_info.get("ok"):
                print(f"상시 감시: {worker_watch_info['detail']}")
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
                    "capsule": str(capsule_path),
                    "code": code,
                    "model": model,
                    "model_source": model_resolution["source"],
                    "model_reason": model_resolution["reason"],
                    "role": model_resolution["role"],
                    "risk": model_resolution["risk"],
                    "model_warning": model_resolution["warning"],
                    "stdout": stdout.strip(),
                    "stderr": stderr.strip(),
                    "command": launch_cmd,
                    "exit_code": 1,
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    return 1


def cmd_prepare_worker(args: argparse.Namespace) -> int:
    """워커 터미널의 준비 절차(신뢰 대화창, 감시기 부착, 파일 편집 승인)를 실행합니다."""
    prep = prepare_worker_terminal(
        terminal=args.terminal,
        cli_type=args.cli_type,
        model=args.model,
        launcher=args.launcher,
        force_file_edit=getattr(args, "enable_file_edit_auto_approve", False),
    )
    if args.json:
        print(json.dumps(prep, ensure_ascii=False, indent=2))
    else:
        print(f"워커 터미널 준비 결과 ({args.terminal}):")
        print(f"  - 신뢰 대화창: {prep['trust_prompt']['status']}")
        print(
            f"  - 승인 감시기: {prep['auto_approve_watcher']['status']} ({prep['auto_approve_watcher']['detail']})"
        )
        print(
            f"  - 파일 편집 승인: {prep['file_edit_auto_approve']['status']} ({prep['file_edit_auto_approve']['detail']})"
        )
        print(f"  - 종합 상태: {'성공' if prep['ok'] else '실패/주의'}")

    return 0 if prep["ok"] else 1


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
    terminal = getattr(args, "terminal", None)
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
        terminal=terminal,
    )
    if terminal:
        remove_worker_meta(terminal)
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

    # prepare-worker
    prp = sub.add_parser(
        "prepare-worker",
        help="워커 터미널 준비 절차(신뢰 대화창, 승인 감시기, accept-edits) 실행",
    )
    prp.add_argument("--terminal", required=True, help="워커 터미널 핸들")
    prp.add_argument(
        "--cli-type", help="CLI 종류 (antigravity, cursor, opencode, claude, codex, kimi)"
    )
    prp.add_argument("--model", help="워커 모델 ID")
    prp.add_argument("--launcher", help="런처 스크립트/방법")
    prp.add_argument(
        "--enable-file-edit-auto-approve",
        action="store_true",
        help="CLI 식별 여부와 무관하게 accept-edits 모드 확보를 시도합니다.",
    )
    prp.add_argument("--json", action="store_true", help="JSON 출력")

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
        "--skip-settled-session-check",
        action="store_true",
        help="완료 세션 잔류 검사를 건너뜁니다 (경고 출력).",
    )
    dsp.add_argument(
        "--no-capsule-notice",
        action="store_true",
        help="기동 직후 Capsule 정본 경로 고지문 전송을 생략합니다 (권장하지 않음).",
    )
    dsp.add_argument(
        "--enable-file-edit-auto-approve",
        action="store_true",
        help="CLI 화면 감지와 무관하게 파일 편집 자동 승인 모드 전환(shift+tab)을 강제 전송합니다.",
    )
    dsp.add_argument(
        "--launcher",
        nargs="?",
        const="scripts/orca_agy_launch.py",
        default=None,
        help="런처 경로 사용 (지정 시 --return-preamble 로 받은 지시문을 <워크트리>/.orca/preamble.txt 에 기록하고 런처 기동을 확인합니다)",
    )
    dsp.add_argument(
        "--allow-unverified-delivery",
        action="store_true",
        help="지시 도달을 확인하지 못해도 종료 코드 0 으로 처리합니다 (권장하지 않음).",
    )
    dsp.add_argument(
        "--skip-auto-approve-check",
        "--allow-no-auto-approve",
        action="store_true",
        dest="skip_auto_approve_check",
        help="권한 자동 승인 감시기 부착 실패 시에도 Dispatch 를 계속 진행합니다 (권장하지 않음, 경고 출력).",
    )
    dsp.add_argument(
        "--skip-skill-receipt",
        action="store_true",
        help="정본 스킬 영수증 검증을 건너뜁니다 (경고 출력).",
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
    crt.add_argument(
        "--skip-skill-receipt",
        action="store_true",
        help="정본 스킬 영수증 검증을 건너뜁니다 (경고 출력).",
    )
    crt.add_argument("--json", action="store_true", help="JSON 출력")

    # rework
    rwk = sub.add_parser("rework", help="반려 후 재작업 Task 를 발급하고 이력을 보존합니다.")
    rwk.add_argument("--task-id", required=True, help="반려 대상 기존 Task ID")
    rwk.add_argument("--reason", required=True, help="반려 사유")
    rwk.add_argument("--capsule", help="기존 Capsule YAML 경로 (미지정 시 자동 탐색)")
    rwk.add_argument("--report", help="기존 worker_done JSON 보고서 경로 (미지정 시 자동 탐색)")
    rwk.add_argument("--new-task-id", help="새로 발급할 재작업 Task ID")
    rwk.add_argument("--run-id", default=DEFAULT_RUN_ID, help="Run ID")
    rwk.add_argument("--capsule-dir", default=".orca/capsules", help="Capsule 저장 디렉터리")
    rwk.add_argument("--task-title", help="새 Task 제목")
    rwk.add_argument("--display-name", help="워커 행에 표시할 이름")
    rwk.add_argument("--json", action="store_true", help="JSON 출력")

    # finalize
    fin = sub.add_parser("finalize", help="worker_done -> 검증 파이프라인 실행")
    fin.add_argument("--report", required=True, help="worker_done 보고 JSON 경로")
    fin.add_argument("--capsule", required=True, help="Task Capsule YAML 경로")
    fin.add_argument("--repo", default=".", help="저장소 루트 경로")
    fin.add_argument("--worktree", help="작업 트리 경로")
    fin.add_argument("--base", default="main", help="비교 기준 git ref")
    fin.add_argument("--branch", default="HEAD", help="검증 대상 git ref")
    fin.add_argument("--reviewer", action="store_true", help="Level 2 Reviewer 실행")
    fin.add_argument(
        "--reviewer-model",
        default=None,
        help="Reviewer 모델 ID (미지정 시 빌더와 독립된 provider 계열로 자동 라우팅)",
    )
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
    fin.add_argument("--terminal", help="워커 터미널 핸들 (지정 시 종료 시 자동 승인 감시기 중지)")
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
    if args.command in ("prepare-worker", "prepare"):
        return cmd_prepare_worker(args)
    if args.command == "create":
        return cmd_create(args)
    if args.command == "rework":
        return cmd_rework(args)
    if args.command == "dispatch":
        return cmd_dispatch(args)
    if args.command == "finalize":
        return cmd_finalize(args)
    if args.command == "status":
        return cmd_status(args)
    return 1


if __name__ == "__main__":
    sys.exit(main())
