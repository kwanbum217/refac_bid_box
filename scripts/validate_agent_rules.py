#!/usr/bin/env python3
"""
다중 에이전트 규칙 자동 로드 통합 정합성 검증 스크립트 (pre-commit / CI).

v2 자동 주입 계약:
  - 단일 진실 원천(AGENTS.md) + 얇은 진입점(thin pointer/요약본) 아키텍처
  - Coordinator / Worker / Reviewer / Standalone 부트스트랩 분리
  - Task Capsule v2 스키마 및 템플릿 정합성

검증 항목:
  1. CLAUDE.md 가 @AGENTS.md thin pointer 인지 (정본 복사 금지)
  2. .antigravity/rules.md 가 존재 + 12,000자 이하 + 핵심 섹션 포함
  3. .cursor/rules/00-core-guidelines.mdc 가 AGENTS.md 참조 여부
  4. opencode.json instructions 가 정확히 ["AGENTS.md"] 단일 배열인지 (타입/빈 배열/추가 항목/SKILLS.md 이중 주입 금지)
  5. .agents/skills/ 와 .claude/skills/, .opencode/skills/ 내용 동일성 (미러 정합성)
  6. AGENTS.md 가 단일 진실 원천으로서 핵심 비협상 원칙 포함 및 @SKILLS.md 미참조 (단일 부트스트랩)
  7. Task Capsule v2 규약 문서 (docs/ops/orca_task_capsule_v2.md) 정합성
  8. Task Capsule v2 템플릿 (.agents/templates/*) 스키마 및 필수 필드 정합성
  9. orca-section-coordination 스킬의 v2 계약 포함 여부
  10. CURRENT_STATE 판정 사실 원장의 주장·앵커·증거 정합성

사용:
  python3 scripts/validate_agent_rules.py          # 전체 검증
  python3 scripts/validate_agent_rules.py --quiet   # 요약만

pre-commit 연동:
  .git/hooks/pre-commit 또는 .pre-commit-config.yaml 에서 본 스크립트 호출.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import os
import re
import subprocess  # nosec B404 - 개발 스크립트가 고정 인자 목록으로만 외부 도구를 호출합니다
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

try:
    from scripts.orca_model_router import MODEL_POOL, TIER_POLICY
except (ImportError, ModuleNotFoundError):
    _repo_root = Path(__file__).resolve().parent.parent
    if str(_repo_root) not in sys.path:
        sys.path.insert(0, str(_repo_root))
    from scripts.orca_model_router import MODEL_POOL, TIER_POLICY

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ANTIGRAVITY_CHAR_CAP = 12000

# 설계 5장 컨텍스트 예산. 초과는 FAIL 이 아니라 WARN 으로 시작해 운영 데이터를 보고
# 강화합니다. 자동 주입 문서가 커지면 모든 워커의 시작 비용이 함께 늘어납니다.
AGENTS_CHAR_BUDGET = 8000
CURRENT_STATE_CHAR_BUDGET = 8000

# CURRENT_STATE.md 필수 필드 (설계 6.1). 이 문서가 v2 의 현재 상태 정본이므로
# 존재와 형식을 기계로 검증합니다.
CURRENT_STATE_PATH = ("docs", "context", "CURRENT_STATE.md")

# source_commit 은 같은 커밋에서 갱신되므로 HEAD 와 정확히 일치할 수 없습니다.
# 갱신 커밋과 병합 커밋만으로도 2~3 이 벌어지므로 소폭 지연은 정상으로 봅니다.
# 이 값을 넘으면 문서가 실제 상태를 놓치기 시작한다는 신호입니다.
CURRENT_STATE_LAG_TOLERANCE = 5

# git 조회 상한. 검증기는 pre-commit 에서 돌므로 멈추면 커밋이 막힙니다.
GIT_PROBE_TIMEOUT_SECONDS = 10

# 계약 집합 버전. 세 템플릿이 같은 버전을 공유해야 합니다. 한쪽만 올리면
# 코디네이터와 워커가 서로 다른 계약을 쓰게 됩니다.
# 2.1.0: Reviewer 에 review_checklist / checklist_results 를 필수화
CONTRACT_VERSION = "2.1.0"
CURRENT_STATE_REQUIRED = [
    "updated_at",
    "source_commit",
    "G1",
    "G2",
    "G3",
]
CURRENT_STATE_FACTS_PATH = ("docs", "context", "current_state_facts.yaml")
CURRENT_STATE_FACT_STATUSES = {"active", "rejected", "closed", "blocked"}
CURRENT_STATE_FACT_LEDGER_VERSION = "2.0"
CURRENT_STATE_STATUS_TERMS = {
    "active": ("진행", "착수", "추진"),
    "rejected": ("기각", "반려"),
    "closed": ("완료", "종결", "해소", "해결", "통과", "강등"),
    "blocked": ("보류", "차단", "대기", "미검증"),
}
CURRENT_STATE_CONTRADICTORY_TERMS = {
    "active": ("기각", "반려", "종결", "완료"),
    "rejected": ("미착수", "착수 예정", "추진 예정", "권고"),
    "closed": ("미해결", "미적용", "미착수", "착수 예정"),
    "blocked": ("완료", "종결", "해소", "해결"),
}

# .antigravity/rules.md 요약본이 반드시 포함해야 할 핵심 키워드 (드리프트 탐지용)
ANTIGRAVITY_REQUIRED_SECTIONS = [
    "데이터 무손실",
    "Train/Serve",
    "금지 행위",
    "이모지",
    "main",
    "재학습",
    "스킬 인덱스",
]

# AGENTS.md 정본이 반드시 포함해야 할 핵심 비협상 키워드
AGENTS_REQUIRED_SECTIONS = [
    "데이터 무손실",
    "금지 행위",
    "이모지",
    "main",
    "에이전트 부트스트랩 모드",
    "ORCA_TASK_CAPSULE_V2",
]

# Task Capsule v2 필수 최상위 키 목록
CAPSULE_REQUIRED_KEYS = [
    "schema",
    "version",
    "mode",
    "run_id",
    "task_id",
    "role",
    "objective",
    "why_now",
    "ground_truth",
    "allowed_read_files",
    "allowed_write_files",
    "search_scope",
    "forbidden",
    "shared_resources",
    "required_change",
    "acceptance",
    "verification_commands",
    "artifact_paths",
    "escalate_when",
    "return_contract",
]

WORKER_DONE_REQUIRED_KEYS = [
    "schema",
    "version",
    "task_id",
    "dispatch_id",
    "status",
    "branch",
    "commit",
    "commit_count",
    "changed_files",
    "verification",
    "metrics",
    "verdict",
    "blocking_issues",
    "remaining_risks",
    "artifacts",
    "reproduce",
]

REVIEW_DONE_REQUIRED_KEYS = [
    "schema",
    "version",
    "task_id",
    "dispatch_id",
    "verdict",
    "blocking_issues",
    "unverified_claims",
    "missing_tests",
    "requested_context",
    "commands_to_verify",
]


class CheckResult:
    def __init__(self, name: str, ok: bool, detail: str = "", warn: bool = False) -> None:
        self.name = name
        self.ok = ok
        self.detail = detail
        # WARN 은 통과로 세지만 화면에 드러냅니다. 권장 예산 초과처럼 즉시 차단할
        # 근거는 없으나 방치하면 되돌리기 어려워지는 항목에 씁니다.
        self.warn = warn and ok

    def format(self, quiet: bool = False) -> str:
        tag = "WARN" if self.warn else ("PASS" if self.ok else "FAIL")
        line = f"[{tag}] {self.name}"
        if not quiet and self.detail:
            line += f"\n       {self.detail}"
        return line


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def _pre_commit_stages(config_path: Path) -> list[str]:
    """pre-commit 설정에서 요구하는 Git hook stage를 수집합니다."""
    content = read_text(config_path)
    if not content:
        return []
    if yaml is not None:
        try:
            config = yaml.safe_load(content) or {}
            stages: set[str] = set()
            for repo in config.get("repos", []):
                for hook in repo.get("hooks", []):
                    values = hook.get("stages", [])
                    if isinstance(values, list):
                        stages.update(str(value) for value in values if value)
            return sorted(stages)
        except (AttributeError, TypeError, ValueError):
            pass
    # pre-commit 설정의 stages는 단순한 인라인 목록이므로 PyYAML 없이도 읽습니다.
    return sorted(
        {
            stage.strip().strip("'\"")
            for match in re.finditer(r"^\s+stages:\s*\[([^]]*)\]", content, re.MULTILINE)
            for stage in match.group(1).split(",")
            if stage.strip()
        }
    )


def _git_hooks_path(root: Path) -> Path | None:
    """현재 저장소가 사용하는 hooks 디렉터리를 확인합니다."""
    try:
        result = subprocess.run(  # nosec B603 B607 - 고정 인자 목록으로 Git hooks 경로만 조회합니다
            ["git", "-C", str(root), "rev-parse", "--git-path", "hooks"],
            capture_output=True,
            text=True,
            check=True,
            timeout=GIT_PROBE_TIMEOUT_SECONDS,
        )
        raw_path = result.stdout.strip()
        if raw_path:
            path = Path(raw_path)
            return path if path.is_absolute() else (root / path).resolve()
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        pass
    fallback = root / ".git" / "hooks"
    return fallback if fallback.is_dir() else None


def check_hook_installation(root: Path = PROJECT_ROOT) -> CheckResult:
    """설정이 요구하는 모든 pre-commit hook stage의 설치 상태를 확인합니다."""
    name = "pre-commit 훅 설치"
    if os.environ.get("CI", "").lower() == "true":
        return CheckResult(name, True, "CI=true 환경에서는 로컬 훅 설치 검사를 건너뜁니다")
    config_path = root / ".pre-commit-config.yaml"
    stages = _pre_commit_stages(config_path)
    if not stages:
        return CheckResult(name, False, f"{config_path}에서 요구 stage를 찾을 수 없습니다")
    hooks_dir = _git_hooks_path(root)
    if hooks_dir is None:
        return CheckResult(name, False, "Git hooks 디렉터리를 찾을 수 없습니다")
    missing = [stage for stage in stages if not (hooks_dir / stage).is_file()]
    non_executable = [
        stage
        for stage in stages
        if (hooks_dir / stage).is_file() and not os.access(hooks_dir / stage, os.X_OK)
    ]
    overwritten = []
    for stage in stages:
        hook_file = hooks_dir / stage
        if stage in missing or stage in non_executable:
            continue
        content = read_text(hook_file)
        if "File generated by pre-commit" not in content or f"--hook-type={stage}" not in content:
            overwritten.append(stage)
    if not missing and not non_executable and not overwritten:
        return CheckResult(
            name, True, f"{len(stages)}개 stage 훅 설치·실행 권한 확인: {', '.join(stages)}"
        )
    problems = []
    if missing:
        problems.append(f"미설치={missing}")
    if non_executable:
        problems.append(f"실행 권한 없음={non_executable}")
    if overwritten:
        problems.append(f"pre-commit 래퍼가 아닌 파일로 덮어씀={overwritten}")
    command = "uv run pre-commit install" + "".join(f" --hook-type {stage}" for stage in stages)
    return CheckResult(name, False, f"{'; '.join(problems)}. 해소 명령: {command}")


def parse_yaml_keys_fallback(content: str) -> dict[str, Any]:
    """PyYAML 미설치 환경을 위한 안전한 최상위 YAML 키 파서."""
    keys: dict[str, Any] = {}
    for line in content.splitlines():
        match = re.match(r"^([a-zA-Z0-9_]+)\s*:\s*(.*)$", line)
        if match:
            k, v = match.group(1), match.group(2).strip()
            # 간단한 스칼라 값 정리
            if (v.startswith('"') and v.endswith('"')) or (v.startswith("'") and v.endswith("'")):
                v = v[1:-1]
            keys[k] = v
    return keys


def check_claude_is_pointer(root: Path = PROJECT_ROOT) -> CheckResult:
    target = root / "CLAUDE.md"
    if not target.exists():
        return CheckResult("CLAUDE.md thin pointer", False, "CLAUDE.md 파일 없음")
    content = read_text(target)
    has_import = "@AGENTS.md" in content
    canonical_markers = [
        "## 1. 프로젝트 개요",
        "## 2. 기술 스택",
        "## 3. 코딩 규칙",
        "## 6. 금지 행위",
        "## 7. 금지 행위",
    ]
    copied_count = sum(1 for marker in canonical_markers if marker in content)
    is_pointer = has_import and copied_count == 0
    if is_pointer:
        return CheckResult("CLAUDE.md thin pointer", True, "@AGENTS.md import 포함, 정본 미복사")
    detail = (
        f"@AGENTS.md import={'있음' if has_import else '없음'}, 정본 섹션 {copied_count}개 복사됨"
    )
    return CheckResult("CLAUDE.md thin pointer", False, detail)


def check_antigravity_rules(root: Path = PROJECT_ROOT) -> CheckResult:
    target = root / ".antigravity" / "rules.md"
    if not target.exists():
        return CheckResult(".antigravity/rules.md", False, ".antigravity/rules.md 파일 없음")
    content = read_text(target)
    char_count = len(content)
    if char_count > ANTIGRAVITY_CHAR_CAP:
        over = char_count - ANTIGRAVITY_CHAR_CAP
        return CheckResult(".antigravity/rules.md", False, f"{char_count:,}자, 캡 초과 {over:,}자")
    missing = [s for s in ANTIGRAVITY_REQUIRED_SECTIONS if s not in content]
    if missing:
        return CheckResult(".antigravity/rules.md", False, f"핵심 키워드 누락: {missing}")
    margin = ANTIGRAVITY_CHAR_CAP - char_count
    return CheckResult(
        ".antigravity/rules.md",
        True,
        f"{char_count:,}자 (여유 {margin:,}자), 핵심 섹션 포함",
    )


def check_cursor_references_agents(root: Path = PROJECT_ROOT) -> CheckResult:
    target = root / ".cursor" / "rules" / "00-core-guidelines.mdc"
    if not target.exists():
        return CheckResult(".cursor core rule AGENTS.md 참조", False, "00-core-guidelines.mdc 없음")
    content = read_text(target)
    if "AGENTS.md" in content:
        return CheckResult(".cursor core rule AGENTS.md 참조", True, "AGENTS.md 참조 확인")
    return CheckResult(".cursor core rule AGENTS.md 참조", False, "AGENTS.md 참조 문구 없음")


def check_opencode_json(root: Path = PROJECT_ROOT) -> CheckResult:
    """opencode.json instructions 가 정확히 [\"AGENTS.md\"] 단일 배열인지 검증합니다.

    v2 계약은 문자열값, 빈 배열, 추가 항목 배열, SKILLS.md 이중 주입을 모두
    단일 주입 위반으로 간주해 확정적으로 실패시킵니다.
    """
    target = root / "opencode.json"
    if not target.exists():
        return CheckResult("opencode.json instructions v2 단일 주입", False, "opencode.json 없음")
    try:
        data = json.loads(read_text(target))
    except json.JSONDecodeError as e:
        return CheckResult("opencode.json instructions v2 단일 주입", False, f"JSON 파싱 실패: {e}")

    instructions = data.get("instructions")
    if not isinstance(instructions, list):
        return CheckResult(
            "opencode.json instructions v2 단일 주입",
            False,
            f"instructions 타입 위반 (JSON 배열만 허용, 현재: {type(instructions).__name__})",
        )

    if instructions == ["AGENTS.md"]:
        return CheckResult(
            "opencode.json instructions v2 단일 주입",
            True,
            'AGENTS.md 단일 자동 로드 확인 (instructions == ["AGENTS.md"])',
        )

    if "SKILLS.md" in instructions:
        return CheckResult(
            "opencode.json instructions v2 단일 주입",
            False,
            'SKILLS.md 이중 주입 감지 (v2 단일 주입 위반: opencode.json instructions는 정확히 ["AGENTS.md"] 배열만 허용)',
        )
    if not instructions:
        return CheckResult(
            "opencode.json instructions v2 단일 주입",
            False,
            '빈 배열 (v2 단일 주입 위반: instructions가 비어 있으며 정확히 ["AGENTS.md"] 배열만 허용)',
        )
    if "AGENTS.md" not in instructions:
        return CheckResult(
            "opencode.json instructions v2 단일 주입",
            False,
            "AGENTS.md 누락 (instructions에 AGENTS.md가 포함되어야 함)",
        )
    extra = [item for item in instructions if item != "AGENTS.md"]
    return CheckResult(
        "opencode.json instructions v2 단일 주입",
        False,
        f'추가 항목 포함 (v2 단일 주입 위반: 정확히 ["AGENTS.md"] 배열만 허용, 추가 항목: {extra})',
    )


def _dir_trees_equal(dir_a: Path, dir_b: Path) -> tuple[bool, list[str]]:
    diffs: list[str] = []
    if not dir_a.exists() and not dir_b.exists():
        return True, []
    if not dir_a.exists():
        return False, [f"정본 없음: {dir_a}"]
    if not dir_b.exists():
        return False, [f"사본 없음: {dir_b}"]
    deep = filecmp.dircmp(dir_a, dir_b)
    _collect_dircmp_diffs(deep, dir_a, dir_b, diffs)
    return len(diffs) == 0, diffs


def _collect_dircmp_diffs(dc: filecmp.dircmp, root_a: Path, root_b: Path, diffs: list[str]) -> None:
    if dc.left_only:
        diffs.append(f"정본에만: {[str(root_a / n) for n in dc.left_only]}")
    if dc.right_only:
        diffs.append(f"사본에만: {[str(root_b / n) for n in dc.right_only]}")
    if dc.diff_files:
        diffs.append(f"내용 상이: {[str(root_a / n) for n in dc.diff_files]}")
    for sub_name, sub_dc in dc.subdirs.items():
        _collect_dircmp_diffs(sub_dc, root_a / sub_name, root_b / sub_name, diffs)


def check_skills_mirror(root: Path = PROJECT_ROOT) -> CheckResult:
    agents_dir = root / ".agents" / "skills"
    mirrors = [
        (".claude/skills", root / ".claude" / "skills"),
        (".opencode/skills", root / ".opencode" / "skills"),
    ]
    all_diffs: list[str] = []
    for label, mirror_dir in mirrors:
        equal, diffs = _dir_trees_equal(agents_dir, mirror_dir)
        if not equal:
            all_diffs.extend(f"{label}: {diff}" for diff in diffs)
    if not all_diffs:
        return CheckResult(
            "스킬 미러 정합성", True, ".claude/skills, .opencode/skills 내용 완전 일치"
        )
    detail = f"{len(all_diffs)}건 차이: " + " | ".join(all_diffs[:3])
    if len(all_diffs) > 3:
        detail += f" ... 외 {len(all_diffs) - 3}건"
    return CheckResult("스킬 미러 정합성", False, detail)


def check_agents_single_root(root: Path = PROJECT_ROOT) -> CheckResult:
    target = root / "AGENTS.md"
    if not target.exists():
        return CheckResult(
            "AGENTS.md 단일 진실 원천 (@SKILLS.md 미참조)", False, "AGENTS.md 파일 없음"
        )
    content = read_text(target)

    # v2 원칙: AGENTS.md는 단일 진실 원천이며 SKILLS.md를 import하지 않아야 함
    if "@SKILLS.md" in content:
        return CheckResult(
            "AGENTS.md 단일 진실 원천 (@SKILLS.md 미참조)",
            False,
            "AGENTS.md 에 레거시 @SKILLS.md import 구문 존재 (v2 단일 부트스트랩 위반)",
        )

    missing = [s for s in AGENTS_REQUIRED_SECTIONS if s not in content]
    if missing:
        return CheckResult(
            "AGENTS.md 단일 진실 원천 (@SKILLS.md 미참조)",
            False,
            f"핵심 비협상 키워드 누락: {missing}",
        )

    return CheckResult(
        "AGENTS.md 단일 진실 원천 (@SKILLS.md 미참조)",
        True,
        "단일 부트스트랩 정본 확인 (@SKILLS.md 미참조, 비협상 원칙 완비)",
    )


def check_task_capsule_v2_docs(root: Path = PROJECT_ROOT) -> CheckResult:
    doc_path = root / "docs" / "ops" / "orca_task_capsule_v2.md"
    if not doc_path.exists():
        return CheckResult(
            "Task Capsule v2 규약 문서", False, "docs/ops/orca_task_capsule_v2.md 없음"
        )
    content = read_text(doc_path)
    required_keywords = [
        "ORCA_TASK_CAPSULE_V2",
        "ORCA_WORKER_DONE_V2",
        "ORCA_REVIEW_DONE_V2",
        "3단계 검증",
        "자족적 실행 계약",
    ]
    missing = [kw for kw in required_keywords if kw not in content]
    if missing:
        return CheckResult(
            "Task Capsule v2 규약 문서",
            False,
            f"규약 핵심 키워드 누락: {missing}",
        )
    return CheckResult(
        "Task Capsule v2 규약 문서",
        True,
        "docs/ops/orca_task_capsule_v2.md 규약 완비",
    )


def check_v2_templates(root: Path = PROJECT_ROOT) -> CheckResult:
    template_dir = root / ".agents" / "templates"
    capsule_yaml = template_dir / "task_capsule_v2.yaml"
    worker_done_json = template_dir / "worker_done_v2.json"
    review_done_json = template_dir / "review_done_v2.json"

    # 1. task_capsule_v2.yaml 검증
    if not capsule_yaml.exists():
        return CheckResult(
            "Task Capsule v2 템플릿 정합성", False, f"템플릿 파일 없음: {capsule_yaml}"
        )
    capsule_content = read_text(capsule_yaml)
    if yaml is not None:
        try:
            parsed_capsule = yaml.safe_load(capsule_content) or {}
        except Exception as e:
            return CheckResult(
                "Task Capsule v2 템플릿 정합성", False, f"task_capsule_v2.yaml 파싱 실패: {e}"
            )
    else:
        parsed_capsule = parse_yaml_keys_fallback(capsule_content)

    if parsed_capsule.get("schema") != "ORCA_TASK_CAPSULE_V2":
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"task_capsule_v2.yaml schema 불일치: {parsed_capsule.get('schema')}",
        )
    if str(parsed_capsule.get("version")) != CONTRACT_VERSION:
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"task_capsule_v2.yaml version 불일치: {parsed_capsule.get('version')}",
        )
    missing_capsule_keys = [k for k in CAPSULE_REQUIRED_KEYS if k not in parsed_capsule]
    if missing_capsule_keys:
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"task_capsule_v2.yaml 필수 키 누락: {missing_capsule_keys}",
        )

    # 2. worker_done_v2.json 검증
    if not worker_done_json.exists():
        return CheckResult(
            "Task Capsule v2 템플릿 정합성", False, f"템플릿 파일 없음: {worker_done_json}"
        )
    try:
        parsed_worker = json.loads(read_text(worker_done_json))
    except json.JSONDecodeError as e:
        return CheckResult(
            "Task Capsule v2 템플릿 정합성", False, f"worker_done_v2.json 파싱 실패: {e}"
        )

    if parsed_worker.get("schema") != "ORCA_WORKER_DONE_V2":
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"worker_done_v2.json schema 불일치: {parsed_worker.get('schema')}",
        )
    if str(parsed_worker.get("version")) != CONTRACT_VERSION:
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"worker_done_v2.json version 불일치: {parsed_worker.get('version')}",
        )
    missing_worker_keys = [k for k in WORKER_DONE_REQUIRED_KEYS if k not in parsed_worker]
    if missing_worker_keys:
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"worker_done_v2.json 필수 키 누락: {missing_worker_keys}",
        )

    # 3. review_done_v2.json 검증
    if not review_done_json.exists():
        return CheckResult(
            "Task Capsule v2 템플릿 정합성", False, f"템플릿 파일 없음: {review_done_json}"
        )
    try:
        parsed_review = json.loads(read_text(review_done_json))
    except json.JSONDecodeError as e:
        return CheckResult(
            "Task Capsule v2 템플릿 정합성", False, f"review_done_v2.json 파싱 실패: {e}"
        )

    if parsed_review.get("schema") != "ORCA_REVIEW_DONE_V2":
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"review_done_v2.json schema 불일치: {parsed_review.get('schema')}",
        )
    if str(parsed_review.get("version")) != CONTRACT_VERSION:
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"review_done_v2.json version 불일치: {parsed_review.get('version')}",
        )
    missing_review_keys = [k for k in REVIEW_DONE_REQUIRED_KEYS if k not in parsed_review]
    if missing_review_keys:
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"review_done_v2.json 필수 키 누락: {missing_review_keys}",
        )

    return CheckResult(
        "Task Capsule v2 템플릿 정합성",
        True,
        "task_capsule_v2.yaml, worker_done_v2.json, review_done_v2.json 스키마 검증 통과",
    )


def _current_state_path(root: Path) -> Path:
    return root.joinpath(*CURRENT_STATE_PATH)


def check_current_state_exists(root: Path = PROJECT_ROOT) -> CheckResult:
    """v2 의 현재 운영 상태 정본이 존재하는지 확인합니다.

    이 파일이 사라지면 코디네이터 부트스트랩이 과거 handoff 나 stale README 로
    되돌아갑니다. 자동 주입 축소의 전제가 무너지므로 FAIL 로 둡니다.
    """
    name = "CURRENT_STATE 정본 존재"
    target = _current_state_path(root)
    if not target.exists():
        return CheckResult(
            name, False, "docs/context/CURRENT_STATE.md 없음 (v2 부트스트랩 정본 누락)"
        )
    return CheckResult(name, True, f"{target.relative_to(root)} 확인")


def check_current_state_sections(root: Path = PROJECT_ROOT) -> CheckResult:
    """필수 필드와 증거 포인터, source_commit 신선도를 확인합니다."""
    name = "CURRENT_STATE 필수 필드"
    target = _current_state_path(root)
    if not target.exists():
        return CheckResult(name, False, "docs/context/CURRENT_STATE.md 없음")
    content = read_text(target)

    missing = [k for k in CURRENT_STATE_REQUIRED if k not in content]
    if missing:
        return CheckResult(name, False, f"필수 필드 누락: {missing}")
    if "docs/" not in content:
        return CheckResult(
            name, False, "증거 경로(docs/...) 없음. 수치는 evidence path 를 가져야 합니다"
        )

    # \D 는 줄바꿈도 매칭하므로 값이 비었을 때 아래 줄의 해시 유사 문자열을
    # source_commit 으로 오인합니다. 같은 줄로 한정하고 경계를 명시합니다.
    match = re.search(
        r"source_commit[*_`\t ]*[:=][*_`\t ]*([0-9a-f]{7,40})\b",
        content,
    )
    if match is None:
        return CheckResult(name, False, "source_commit 값에서 커밋 해시를 읽을 수 없음")

    recorded = match.group(1)
    behind = _commits_behind_head(root, recorded)
    if behind is None:
        # 전체 이력을 가진 저장소에서 커밋을 찾지 못하면 오타, 잘못된 해시,
        # 이력 재작성 중 하나이므로 실패입니다. 다만 얕은 클론은 커밋이 없는
        # 것과 못 받은 것을 구분할 수 없습니다. 증명할 수 없는 상태를 확정된
        # 실패로 단정하면 fail-open 을 뒤집은 같은 크기의 오류가 됩니다.
        if _can_verify_commit_history(root):
            return CheckResult(
                name,
                False,
                f"source_commit {recorded} 을 이 저장소 이력에서 찾을 수 없습니다. "
                "값이 잘못됐거나 이력이 재작성됐는지 확인하십시오",
            )
        return CheckResult(
            name,
            True,
            f"필수 필드 완비. source_commit {recorded} 은 전체 이력이 없어 신선도 미검증",
            warn=True,
        )
    if behind > CURRENT_STATE_LAG_TOLERANCE:
        # 경고로 두면 아무도 고치지 않습니다. 2026-08-19 측정에서 6 커밋 뒤처진
        # 상태로 WARN 만 내고 exit 0 이었습니다. 정본이 실제 상태를 놓치기
        # 시작하는 지점이므로 실패로 막습니다.
        return CheckResult(
            name,
            False,
            f"source_commit {recorded} 이 HEAD 보다 {behind} 커밋 뒤처짐 "
            f"(허용 {CURRENT_STATE_LAG_TOLERANCE}). CURRENT_STATE.md 를 갱신하십시오",
        )
    return CheckResult(
        name,
        True,
        f"필수 필드 완비. source_commit {recorded} 은 HEAD 대비 {behind} 커밋 (허용 {CURRENT_STATE_LAG_TOLERANCE})",
    )


def _can_verify_commit_history(root: Path) -> bool:
    """커밋의 부재를 증명할 수 있는 저장소인지 확인합니다.

    이력이 있어야 하고, 얕은 클론이 아니어야 합니다. 얕은 클론은 커밋이
    존재하지 않는 것과 아직 받지 않은 것을 구분하지 못합니다. 이력 유무만
    보면 `fetch-depth: 1` 로 받은 CI 잡이 정상 값을 오타로 판정합니다.
    """
    try:
        subprocess.run(  # nosec B603 B607 - shell 없이 고정 인자 목록으로 호출합니다
            ["git", "-C", str(root), "rev-parse", "--verify", "HEAD"],
            check=True,
            capture_output=True,
            timeout=GIT_PROBE_TIMEOUT_SECONDS,
        )
        shallow = subprocess.run(  # nosec B603 B607 - shell 없이 고정 인자 목록으로 호출합니다
            ["git", "-C", str(root), "rev-parse", "--is-shallow-repository"],
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_PROBE_TIMEOUT_SECONDS,
        )
        return shallow.stdout.strip() != "true"
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
        return False


def _freshness_ref(root: Path) -> str:
    """신선도를 재는 기준 ref 를 고릅니다.

    HEAD 로 재면 작업 브랜치의 커밋까지 세어, 워커가 커밋을 낼수록 문서가 낡은
    것으로 오판됩니다. 2026-08-30 세션에서 이 때문에 갱신을 네 번 반복했고 그중
    두 번은 어떤 값으로도 수렴하지 않았습니다. 갱신 커밋 자체가 정본 브랜치를
    두 커밋 앞세우고, 작업 브랜치가 그것을 병합하면 거리가 다시 늘기 때문입니다.

    정본 문서의 신선도는 정본 브랜치 기준으로 재는 것이 맞습니다. main 이 있으면
    HEAD 와 main 의 공통 조상을 기준으로 삼아 작업 브랜치의 자체 커밋을 제외합니다.
    """
    for ref in ("main", "origin/main"):
        try:
            out = subprocess.run(  # nosec B603 B607 - shell 없이 고정 인자 목록으로 호출합니다
                ["git", "-C", str(root), "merge-base", "HEAD", ref],
                check=True,
                capture_output=True,
                text=True,
                timeout=GIT_PROBE_TIMEOUT_SECONDS,
            )
            base = out.stdout.strip()
            if base:
                return base
        except (subprocess.CalledProcessError, subprocess.TimeoutExpired, OSError):
            continue
    return "HEAD"


def _commits_behind_head(root: Path, commit: str) -> int | None:
    """기록된 커밋이 정본 브랜치 기준으로 몇 커밋 뒤처졌는지 셉니다. 확인 불가면 None."""
    # timeout 을 두지 않으면 git 이 잠기거나 잠금 파일을 기다릴 때 검증기가 함께
    # 멈춥니다. 이 검증기는 pre-commit 에서 돌기 때문에 커밋 자체가 막힙니다.
    try:
        subprocess.run(  # nosec B603 B607 - shell 없이 고정 인자 목록으로 호출합니다
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
            check=True,
            capture_output=True,
            timeout=GIT_PROBE_TIMEOUT_SECONDS,
        )
        ref = _freshness_ref(root)
        out = subprocess.run(  # nosec B603 B607 - shell 없이 고정 인자 목록으로 호출합니다
            ["git", "-C", str(root), "rev-list", "--count", f"{commit}..{ref}"],
            check=True,
            capture_output=True,
            text=True,
            timeout=GIT_PROBE_TIMEOUT_SECONDS,
        )
        return int(out.stdout.strip())
    except (
        subprocess.CalledProcessError,
        subprocess.TimeoutExpired,
        OSError,
        ValueError,
    ):
        # 확인 불가는 실패가 아닙니다. 호출부가 WARN 으로 처리합니다.
        return None


def check_context_budgets(root: Path = PROJECT_ROOT) -> CheckResult:
    """자동 주입 문서의 크기 예산을 확인합니다 (설계 5장).

    초과가 곧 오류는 아니지만, 자동 주입 문서는 모든 워커의 시작 비용이므로
    커지는 것을 조용히 넘기지 않습니다.
    """
    name = "컨텍스트 예산"
    targets = [
        (root / "AGENTS.md", AGENTS_CHAR_BUDGET),
        (_current_state_path(root), CURRENT_STATE_CHAR_BUDGET),
    ]
    over = []
    sizes = []
    missing = []
    for path, budget in targets:
        if not path.exists():
            missing.append(path.name)
            continue
        size = len(read_text(path))
        sizes.append(f"{path.name} {size}자/{budget}")
        if size > budget:
            over.append(f"{path.name} {size}자 (권장 {budget}자)")
    if missing:
        # 예산 검사가 대상 부재를 통과로 처리하면 파일이 사라진 상태를 조용히
        # 넘깁니다. 존재 검사가 따로 있어도 이 검사 자체가 오해를 만듭니다.
        return CheckResult(name, False, f"측정 대상 없음: {missing}")
    detail = ", ".join(sizes) if sizes else "대상 파일 없음"
    if over:
        return CheckResult(name, True, f"권장 예산 초과: {'; '.join(over)}", warn=True)
    return CheckResult(name, True, detail)


def check_orca_coordination_skill(root: Path = PROJECT_ROOT) -> CheckResult:
    skill_path = root / ".agents" / "skills" / "orca-section-coordination" / "SKILL.md"
    if not skill_path.exists():
        return CheckResult(
            "orca-section-coordination v2 스킬",
            False,
            ".agents/skills/orca-section-coordination/SKILL.md 파일 없음",
        )
    content = read_text(skill_path)
    required = [
        "ORCA_TASK_CAPSULE_V2",
        "ORCA_WORKER_DONE_V2",
        "ORCA_REVIEW_DONE_V2",
    ]
    missing = [r for r in required if r not in content]
    if missing:
        return CheckResult(
            "orca-section-coordination v2 스킬",
            False,
            f"v2 계약 키워드 누락: {missing}",
        )
    return CheckResult(
        "orca-section-coordination v2 스킬",
        True,
        "orca-section-coordination 스킬 내 v2 계약 포함 확인",
    )


def _parse_worker_model_table(content: str) -> dict[tuple[str, str], list[str]]:
    """orca_worker_model_pool.md 문서 내 역할별 모델 배정 정책 표를 파싱합니다."""
    lines = content.splitlines()
    in_table = False
    doc_policy: dict[tuple[str, str], list[str]] = {}
    for line in lines:
        stripped = line.strip()
        if (
            "역할" in stripped
            and "위험도" in stripped
            and ("1순위" in stripped or "Primary" in stripped)
        ):
            in_table = True
            continue
        if in_table:
            if not stripped.startswith("|"):
                if doc_policy:
                    break
                continue
            cells = [c.strip().strip("`").strip() for c in stripped.split("|")[1:-1]]
            if not cells or all(re.match(r"^:?-+:?$", c) for c in cells):
                continue
            if len(cells) >= 4:
                role, risk, primary, fallback = cells[0], cells[1], cells[2], cells[3]
                doc_policy[(role, risk)] = [primary, fallback]
    return doc_policy


def check_worker_model_pool_drift(
    root: Path = PROJECT_ROOT,
    tier_policy: dict[tuple[str, str], list[str]] | None = None,
) -> CheckResult:
    """TIER_POLICY 실행 정본과 docs/ops/orca_worker_model_pool.md 문서 표의 일치 여부를 검증합니다.

    역할(role)과 위험도(risk) 조합별로 1순위(Primary)와 2순위(Fallback)가
    완전 일치하는지 대조하며, 파싱 실패 시 반드시 FAIL로 처리합니다.
    """
    name = "워커 모델 배정표 정합성 (TIER_POLICY vs 문서)"
    doc_path = root / "docs" / "ops" / "orca_worker_model_pool.md"
    if not doc_path.exists():
        return CheckResult(name, False, "문서 파일 없음: docs/ops/orca_worker_model_pool.md")

    content = read_text(doc_path)
    doc_policy = _parse_worker_model_table(content)
    if not doc_policy:
        return CheckResult(
            name, False, "docs/ops/orca_worker_model_pool.md 에서 배정표를 찾을 수 없거나 파싱 실패"
        )

    expected_policy = tier_policy if tier_policy is not None else TIER_POLICY

    doc_keys = set(doc_policy.keys())
    code_keys = set(expected_policy.keys())

    doc_only = sorted(doc_keys - code_keys)
    code_only = sorted(code_keys - doc_keys)
    common_keys = sorted(doc_keys & code_keys)

    mismatches: list[str] = []
    for k in common_keys:
        d_val = doc_policy[k]
        c_val = expected_policy[k][:2]  # primary, fallback
        if d_val != c_val:
            mismatches.append(f"{k}: 문서={d_val} != 코드={c_val}")

    if not doc_only and not code_only and not mismatches:
        return CheckResult(name, True, f"{len(common_keys)}개 역할/위험도 조합 완전 일치")

    diff_details: list[str] = []
    if mismatches:
        diff_details.append(f"값 불일치 {len(mismatches)}건: {'; '.join(mismatches)}")
    if code_only:
        diff_details.append(f"코드에만 있는 조합 {len(code_only)}건: {code_only}")
    if doc_only:
        diff_details.append(f"문서에만 있는 조합 {len(doc_only)}건: {doc_only}")

    return CheckResult(name, False, " | ".join(diff_details))


def check_agents_model_table_absence(
    root: Path = PROJECT_ROOT,
    model_pool: dict[str, dict[str, Any]] | None = None,
) -> CheckResult:
    """AGENTS.md 에 구체 워커 모델 배정표가 다시 생기지 않았는지 검증합니다.

    AGENTS.md 는 TIER_POLICY 정본 포인터만 유지해야 하며, MODEL_POOL 에 등록된
    워커 모델 풀 키 및 모델 ID 문자열이 본문에 나타나면 실패로 판정합니다.
    (코디네이터 전용 모델은 허용)
    """
    name = "AGENTS.md 워커 모델 배정표 부재"
    target = root / "AGENTS.md"
    if not target.exists():
        return CheckResult(name, False, "AGENTS.md 파일 없음")
    content = read_text(target)

    pool = model_pool if model_pool is not None else MODEL_POOL
    worker_tokens: set[str] = set()
    for k, v in pool.items():
        if v.get("tier") in ("coordinator", "coordinator_reserve"):
            continue
        worker_tokens.add(k)
        if v.get("id"):
            worker_tokens.add(v["id"])

    found_tokens = [t for t in sorted(worker_tokens) if t in content]
    if found_tokens:
        return CheckResult(
            name,
            False,
            f"AGENTS.md 내 워커 모델 풀 키/ID 발견 (배정표 drift 감지): {found_tokens}",
        )
    return CheckResult(
        name,
        True,
        "AGENTS.md 에 개별 워커 모델 배정표 없음 (TIER_POLICY 포인터 유지)",
    )


def _parse_facts_without_yaml(text: str) -> dict:
    """PyYAML 없이 상태 원장의 최소 구조만 읽습니다.

    **pre-commit 은 이 스크립트를 시스템 `python3` 로 실행하며 거기에는 PyYAML 이
    없습니다.** `uv run` 에서만 통과하고 커밋 훅에서는 실패하면 검사가 사실상
    작동하지 않습니다(2026-09-01 실측: uv 17/17 통과, python3 16/17 실패).

    들여쓰기로 항목 경계를 판정합니다. `related_documents` 처럼 중첩된 목록의
    `- ` 항목을 새 fact 로 오인하지 않으려면 이 구분이 필요합니다.

    중첩 매핑이나 인용 규칙을 온전히 다루지는 않으므로, **형식이 복잡해지면
    PyYAML 을 의존성에 넣고 이 함수를 지우십시오.**
    """
    facts: list[dict] = []
    top_level: dict[str, str] = {}
    current: dict | None = None
    item_indent: int | None = None
    pending_list_key: str | None = None

    for raw in text.splitlines():
        if not raw.strip() or raw.strip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip())
        stripped = raw.strip()

        if stripped.startswith("- "):
            body = stripped[2:].strip()
            is_new_fact = item_indent is None or indent <= item_indent
            if is_new_fact and ":" in body:
                item_indent = indent
                current = {}
                facts.append(current)
                stripped = body
            else:
                # 중첩 목록의 값입니다. 직전 키의 목록에 담습니다.
                if current is not None and pending_list_key:
                    current.setdefault(pending_list_key, []).append(body)
                continue
        elif current is not None and item_indent is not None and indent <= item_indent:
            # 항목보다 얕게 돌아오면 facts 블록을 벗어난 것입니다.
            current = None
            continue

        if ":" not in stripped:
            continue
        key, _, value = stripped.partition(":")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if current is None:
            # facts 블록 밖의 최상위 스칼라입니다. version 처럼 원장 계약을
            # 판정하는 데 쓰이므로 버리지 않습니다. 2026-09-04 에 이 누락으로
            # 원장 version 검사가 폴백 경로에서 항상 실패했습니다.
            if indent == 0 and value:
                top_level[key] = value
            continue
        if value:
            current[key] = value
            pending_list_key = None
        else:
            # 값이 비면 다음 줄부터 목록이 이어집니다.
            pending_list_key = key
    result: dict = dict(top_level)
    result["facts"] = facts
    return result


def check_current_state_fact_statuses(root: Path = PROJECT_ROOT) -> CheckResult:
    """기계 판독 상태 원장과 CURRENT_STATE 서술의 상태 정합성을 검사합니다."""
    name = "CURRENT_STATE 기계 상태 원장 정합성"
    facts_path = root.joinpath(*CURRENT_STATE_FACTS_PATH)
    state_path = _current_state_path(root)
    if not facts_path.exists():
        return CheckResult(name, False, "docs/context/current_state_facts.yaml 없음")
    if not state_path.exists():
        return CheckResult(name, False, "docs/context/CURRENT_STATE.md 없음")
    try:
        facts = (
            yaml.safe_load(read_text(facts_path))
            if yaml is not None
            else _parse_facts_without_yaml(read_text(facts_path))
        )
    except Exception as exc:
        return CheckResult(name, False, f"상태 원장 YAML 파싱 실패: {exc}")
    if not isinstance(facts, dict) or not isinstance(facts.get("facts"), list):
        return CheckResult(name, False, "상태 원장은 facts 배열을 가져야 합니다")

    content = read_text(state_path)
    failures: list[str] = []
    seen_ids: set[str] = set()
    for index, fact in enumerate(facts["facts"], start=1):
        if not isinstance(fact, dict):
            failures.append(f"facts[{index}] 항목이 객체가 아님")
            continue
        fact_id = fact.get("id")
        status = fact.get("status")
        anchor = fact.get("document_anchor")
        if not isinstance(fact_id, str) or not fact_id:
            failures.append(f"facts[{index}] id 누락")
            continue
        if fact_id in seen_ids:
            failures.append(f"중복 id: {fact_id}")
        seen_ids.add(fact_id)
        if status not in CURRENT_STATE_FACT_STATUSES:
            failures.append(f"{fact_id}: 허용되지 않은 status '{status}'")
        if not isinstance(fact.get("decision_date"), str) or not fact["decision_date"]:
            failures.append(f"{fact_id}: decision_date 누락")
        related = fact.get("related_documents")
        if (
            not isinstance(related, list)
            or not related
            or not all(isinstance(v, str) for v in related)
        ):
            failures.append(f"{fact_id}: related_documents 누락")
        if not isinstance(anchor, str) or not anchor:
            failures.append(f"{fact_id}: document_anchor 누락")
            continue
        position = content.find(anchor)
        if position < 0:
            failures.append(f"{fact_id}: CURRENT_STATE 앵커 없음 '{anchor}'")
            continue
        # 앵커가 속한 Markdown 문단 또는 목록 항목만 상태 문맥으로 삼습니다.
        # 고정 길이 창은 인접 항목의 기각·미해결 표지를 현재 항목의 모순으로
        # 오인하므로, 항목 경계를 보존하면서 같은 항목의 줄바꿈 서술은 포함합니다.
        line_start = content.rfind("\n", 0, position) + 1
        block_start = line_start
        while block_start > 0:
            previous_end = block_start - 1
            previous_start = content.rfind("\n", 0, previous_end) + 1
            previous_line = content[previous_start:previous_end].strip()
            if not previous_line or previous_line.startswith(("- ", "* ", "+ ", "#")):
                break
            block_start = previous_start
        block_end = content.find("\n\n", position)
        if block_end < 0:
            block_end = len(content)
        window = content[block_start:block_end]
        expected = CURRENT_STATE_STATUS_TERMS.get(status, ())
        contradictory = CURRENT_STATE_CONTRADICTORY_TERMS.get(status, ())
        if not any(term in window for term in expected):
            failures.append(f"{fact_id}: status={status} 상태 표지 없음")
        found_contradictory = [term for term in contradictory if term in window]
        if found_contradictory:
            failures.append(f"{fact_id}: status={status} 와 충돌하는 표지 {found_contradictory}")

    if failures:
        return CheckResult(name, False, "; ".join(failures))
    return CheckResult(
        name, True, f"{len(facts['facts'])}개 과업 상태 원장과 문서 앵커 정합성 확인"
    )


def check_current_state_fact_ledger(root: Path = PROJECT_ROOT) -> CheckResult:
    """판정 사실 원장과 부팅 문서의 주장·증거 정합성을 검사합니다.

    상태 표지만 확인하면 원장 항목의 주장 자체가 문서에서 바뀌는 drift를
    놓칠 수 있습니다. 각 항목의 claim과 document_anchor를 CURRENT_STATE.md와
    대조하고, 기계 판정에 사용할 증거 경로를 요구합니다.
    """
    name = "CURRENT_STATE 판정 사실 원장 검증"
    facts_path = root.joinpath(*CURRENT_STATE_FACTS_PATH)
    state_path = _current_state_path(root)
    if not facts_path.exists():
        return CheckResult(name, False, "docs/context/current_state_facts.yaml 없음")
    if not state_path.exists():
        return CheckResult(name, False, "docs/context/CURRENT_STATE.md 없음")
    try:
        facts = (
            yaml.safe_load(read_text(facts_path))
            if yaml is not None
            else _parse_facts_without_yaml(read_text(facts_path))
        )
    except Exception as exc:
        return CheckResult(name, False, f"판정 사실 원장 YAML 파싱 실패: {exc}")
    if not isinstance(facts, dict) or not isinstance(facts.get("facts"), list):
        return CheckResult(name, False, "판정 사실 원장은 facts 배열을 가져야 합니다")
    if facts.get("version") != CURRENT_STATE_FACT_LEDGER_VERSION:
        return CheckResult(
            name,
            False,
            "판정 사실 원장 version이 "
            f"{CURRENT_STATE_FACT_LEDGER_VERSION}이 아닙니다: {facts.get('version')!r}",
        )

    content = read_text(state_path)
    failures: list[str] = []
    seen_ids: set[str] = set()
    for index, fact in enumerate(facts["facts"], start=1):
        if not isinstance(fact, dict):
            failures.append(f"facts[{index}] 항목이 객체가 아님")
            continue
        fact_id = fact.get("id")
        if not isinstance(fact_id, str) or not fact_id:
            failures.append(f"facts[{index}] id 누락")
            continue
        if fact_id in seen_ids:
            failures.append(f"중복 id: {fact_id}")
        seen_ids.add(fact_id)

        claim = fact.get("claim") or fact.get("fact")
        if not isinstance(claim, str) or not claim.strip():
            failures.append(f"{fact_id}: claim 또는 fact 누락")
        elif content.count(claim) != 1:
            failures.append(
                f"{fact_id}: CURRENT_STATE claim 일치 실패 (발견 {content.count(claim)}회)"
            )

        anchor = fact.get("document_anchor")
        if not isinstance(anchor, str) or not anchor.strip():
            failures.append(f"{fact_id}: document_anchor 누락")
        elif content.count(anchor) < 1:
            failures.append(f"{fact_id}: CURRENT_STATE document_anchor 일치 실패 (발견 0회)")

        evidence = fact.get("evidence")
        if isinstance(evidence, str):
            evidence = [evidence]
        if (
            not isinstance(evidence, list)
            or not evidence
            or not all(isinstance(value, str) and value.strip() for value in evidence)
        ):
            failures.append(f"{fact_id}: evidence 경로 누락")

    if failures:
        return CheckResult(name, False, "; ".join(failures))
    return CheckResult(
        name, True, f"{len(facts['facts'])}개 판정 사실의 claim·anchor·evidence 정합성 확인"
    )


def check_current_state_unknowns_contradictions(root: Path = PROJECT_ROOT) -> CheckResult:
    """CURRENT_STATE.md 6.1절(알려진 미해결 사항) 내에서 동일 사안에 대한 상태 표기 모순(해소 vs 미해결)을 검사합니다.

    [검사 대상 및 탐지 범위 (잡을 수 있는 범위)]:
      1. 단일 항목 표제/상태 괄호 내에 해소 표지('해소', '완료', '종결', '해결' 등)와 미해결 표지('미해결', '미적용', '미수행', '미검증', '미착수', '수정 미적용' 등)가 동시에 존재하는 경우.
      2. 6.1절 내 복수 항목이 동일/정규화된 표제(또는 공유 식별자)를 가지면서 한쪽은 해소 상태, 다른 쪽은 미해결 상태로 기술된 경우.

    [탐지 제외 및 한계 (못 잡는 범위)]:
      1. 6.1절 외 타 섹션(예: 2장 성능 정본, 4장 진행 과업)과의 문맥적/의미적 불일치.
      2. 표제나 키워드가 전혀 다른 자연어 문장으로 서술된 의미적 모순.
      3. 조건부 부분 해결 서술(예: 'Linux는 완료, Windows는 미검증'과 같은 플랫폼별 분기).
      4. 수치 지표의 논리적 모순이나 날짜 선후 관계 불일치.
    """
    name = "CURRENT_STATE 6.1 상태 모순 검사"
    target = _current_state_path(root)
    if not target.exists():
        return CheckResult(name, False, "docs/context/CURRENT_STATE.md 파일 없음")
    content = read_text(target)

    match = re.search(
        r"### 6\.1 알려진 미해결 사항 \(Unknowns\)(.*?)(?=\n### 6\.2|\n## |\Z)",
        content,
        re.DOTALL,
    )
    if not match:
        return CheckResult(name, False, "CURRENT_STATE.md 6.1절 (알려진 미해결 사항) 없음")

    section_text = match.group(1)
    items: list[str] = []
    for block in re.split(r"\n(?=[-*\+]\s+)", section_text):
        block = block.strip()
        if block.startswith(("-", "*", "+")):
            items.append(block)

    if not items:
        return CheckResult(name, True, "6.1절 미해결 항목 0건")

    resolved_markers = (
        "해소",
        "해결",
        "병합 완료",
        "수정 완료",
        "적용 완료",
        "판정 종료",
        "종결",
        "종료",
        "결함 해소",
    )
    unresolved_markers = (
        "미해결",
        "미적용",
        "수정 미적용",
        "적용 미완료",
        "미수행",
        "미검증",
        "미실시",
        "미착수",
        "미완료",
    )
    antonym_pairs = [
        ("해소", "미해결"),
        ("해소", "미적용"),
        ("해소", "수정 미적용"),
        ("해소", "미수행"),
        ("해소", "미완료"),
        ("해결", "미해결"),
        ("완료", "미완료"),
        ("완료", "미적용"),
        ("수정 완료", "수정 미적용"),
        ("적용 완료", "미적용"),
    ]

    conflicts: list[str] = []
    parsed_items: list[dict[str, Any]] = []

    for item in items:
        bold_match = re.search(r"^\s*[-*+]\s+\*\*(.*?)\*\*", item)
        first_line = item.splitlines()[0]
        header = bold_match.group(1) if bold_match else first_line.lstrip("-*+ ").split(":")[0]

        paren_match = re.search(r"\((.*?)\)", header)
        paren_text = paren_match.group(1) if paren_match else ""

        # 1. 단일 항목 내부 상태 모순 검사
        # 미해결 표지를 먼저 지우고 해소 표지를 찾습니다. 부분 문자열로 그냥 찾으면
        # "미해결" 안의 "해결" 과 "미완료" 안의 "완료" 가 해소 표지로 잡혀,
        # 정상적으로 미해결이라고만 적은 항목이 전부 모순으로 오탐됩니다.
        masked_paren = paren_text
        for _unres in unresolved_markers:
            masked_paren = masked_paren.replace(_unres, "")
        for res_term, unres_term in antonym_pairs:
            if res_term in masked_paren and unres_term in paren_text:
                conflicts.append(
                    f"단일 항목 내부 상태 모순: '{header}' (해소 '{res_term}' vs 미해결 '{unres_term}')"
                )

        # 항목 상태 분류
        is_res = any(m in paren_text or m in header for m in resolved_markers)
        is_unres = any(m in paren_text or m in header for m in unresolved_markers)

        # 표제 정규화 및 식별자 추출
        cleaned_header = re.sub(r"\([^\)]*\)", "", header)
        norm_title = re.sub(r"[^a-zA-Z0-9가-힣]", "", cleaned_header).lower()
        topic_ids = {
            m.group(1).lower() for m in re.finditer(r"\b(q\d{1,3})\b", header, re.IGNORECASE)
        }

        parsed_items.append(
            {
                "header": header,
                "norm": norm_title,
                "ids": topic_ids,
                "is_res": is_res,
                "is_unres": is_unres,
            }
        )

    # 2. 복수 항목 간 동일 사안 상반 상태 기술 검사
    for i in range(len(parsed_items)):
        for j in range(i + 1, len(parsed_items)):
            a, b = parsed_items[i], parsed_items[j]
            same_topic = bool(a["norm"] and b["norm"] and a["norm"] == b["norm"])
            shared_ids = a["ids"].intersection(b["ids"])
            if (same_topic or shared_ids) and (
                (a["is_res"] and b["is_unres"]) or (a["is_unres"] and b["is_res"])
            ):
                topic_desc = (
                    f"동일 표제 '{a['header']}' / '{b['header']}'"
                    if same_topic
                    else f"공유 식별자 {shared_ids}"
                )
                conflicts.append(f"복수 항목 간 상태 모순 ({topic_desc})")

    if conflicts:
        return CheckResult(name, False, "; ".join(conflicts))
    return CheckResult(name, True, f"{len(parsed_items)}개 미해결 항목 모순 없음 확인")


def check_analysis_metrics_docs(root: Path = PROJECT_ROOT) -> CheckResult:
    """docs/analysis/ 의 마커 있는 문서를 원시 JSON 과 대조합니다.

    METRICS_BEGIN 마커가 있는 문서만 검사 대상입니다.
    마커가 없는 문서는 통과로 처리합니다.
    종료 코드 1 은 수치 불일치, 2 는 파일/키 부재입니다.
    """
    name = "분석 문서 수치 정합성 (METRICS 마커)"
    docs_dir = root / "docs" / "analysis"
    if not docs_dir.exists():
        return CheckResult(name, False, "docs/analysis/ 디렉터리 없음")

    script = root / "scripts" / "render_analysis_metrics.py"
    if not script.exists():
        return CheckResult(name, False, "scripts/render_analysis_metrics.py 없음")

    md_files = sorted(docs_dir.glob("*.md"))
    if not md_files:
        return CheckResult(name, True, "docs/analysis/ 에 .md 파일 없음")

    marker_pattern = re.compile(r"<!--\s*METRICS_BEGIN\s+")
    checked: list[str] = []
    failed: list[str] = []

    for md_path in md_files:
        content = read_text(md_path)
        if not marker_pattern.search(content):
            continue  # 마커 없는 문서는 통과
        checked.append(md_path.name)
        try:
            result = subprocess.run(  # nosec B603 B607 - 고정 인자 목록으로 호출합니다
                [sys.executable, str(script), "verify", "--doc", str(md_path)],
                capture_output=True,
                text=True,
                timeout=GIT_PROBE_TIMEOUT_SECONDS,
                cwd=str(root),
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            return CheckResult(name, False, f"{md_path.name}: 실행 실패 ({exc})")

        if result.returncode != 0:
            detail_lines = (result.stdout + result.stderr).strip().splitlines()
            summary = "; ".join(detail_lines[:3]) if detail_lines else "(출력 없음)"
            failed.append(f"{md_path.name} (코드 {result.returncode}): {summary}")

    if not checked:
        return CheckResult(name, True, "docs/analysis/ 에 METRICS 마커 문서 없음 - 검사 대상 없음")
    if failed:
        detail = f"{len(failed)}/{len(checked)} 문서 실패: " + " | ".join(failed)
        return CheckResult(name, False, detail)
    return CheckResult(
        name, True, f"{len(checked)}개 문서 METRICS 수치 검증 통과: {', '.join(checked)}"
    )


CANONICAL_ORCHESTRATION_SKILL_COMMAND = "orca skills get orchestration"


def check_canonical_skill_pointer(root: Path = PROJECT_ROOT) -> CheckResult:
    """AGENTS.md 및 저장소 스킬 0장의 Orca 정본 명령 포인터 정합성을 검증합니다.

    .agents/skills/orca-section-coordination/SKILL.md 0장에 명시된 정본 조회 명령이
    'orca skills get orchestration' 과 일치하는지 확인하여 정본 포인터가 갈라지는 것을 방지합니다.
    """
    name = "Orca 정본 스킬 포인터 정합성"
    skill_path = root / ".agents" / "skills" / "orca-section-coordination" / "SKILL.md"
    if not skill_path.exists():
        return CheckResult(name, False, f"스킬 파일 없음: {skill_path}")

    content = read_text(skill_path)
    if CANONICAL_ORCHESTRATION_SKILL_COMMAND not in content:
        rel_path = skill_path.relative_to(root) if skill_path.is_relative_to(root) else skill_path
        return CheckResult(
            name,
            False,
            f"{rel_path} 0장에 정본 명령 '{CANONICAL_ORCHESTRATION_SKILL_COMMAND}' 누락",
        )

    return CheckResult(
        name,
        True,
        f"정본 스킬 포인터 확인 ('{CANONICAL_ORCHESTRATION_SKILL_COMMAND}')",
    )


def get_all_checks(root: Path = PROJECT_ROOT) -> list[CheckResult]:
    return [
        check_claude_is_pointer(root),
        check_antigravity_rules(root),
        check_cursor_references_agents(root),
        check_opencode_json(root),
        check_skills_mirror(root),
        check_agents_single_root(root),
        check_task_capsule_v2_docs(root),
        check_v2_templates(root),
        check_orca_coordination_skill(root),
        check_canonical_skill_pointer(root),
        check_current_state_exists(root),
        check_current_state_sections(root),
        check_context_budgets(root),
        check_worker_model_pool_drift(root),
        check_agents_model_table_absence(root),
        check_current_state_fact_statuses(root),
        check_current_state_fact_ledger(root),
        check_current_state_unknowns_contradictions(root),
        check_analysis_metrics_docs(root),
        check_hook_installation(root),
    ]


def run_all_checks(root: Path = PROJECT_ROOT, quiet: bool = False) -> int:
    checks = get_all_checks(root)
    print("=" * 60)
    print("다중 에이전트 규칙 정합성 검증 (pre-commit / v2)")
    print("=" * 60)
    for chk in checks:
        print(chk.format(quiet=quiet))
    failed = [c for c in checks if not c.ok]
    print("-" * 60)
    if failed:
        print(f"검증 실패: {len(failed)}/{len(checks)} 건. 커밋을 중단합니다.")
        return 1
    print(f"검증 통과: {len(checks)}/{len(checks)} 건.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="다중 에이전트 규칙 정합성 검증 (pre-commit / v2)")
    parser.add_argument("--quiet", action="store_true", help="요약만 출력")
    args = parser.parse_args()
    return run_all_checks(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
