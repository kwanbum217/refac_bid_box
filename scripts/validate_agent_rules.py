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
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

try:
    import yaml
except ImportError:
    yaml = None

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
CURRENT_STATE_REQUIRED = [
    "updated_at",
    "source_commit",
    "G1",
    "G2",
    "G3",
]

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
    detail = f"@AGENTS.md import={'있음' if has_import else '없음'}, 정본 섹션 {copied_count}개 복사됨"
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
            "AGENTS.md 단일 자동 로드 확인 (instructions == [\"AGENTS.md\"])",
        )

    if "SKILLS.md" in instructions:
        return CheckResult(
            "opencode.json instructions v2 단일 주입",
            False,
            "SKILLS.md 이중 주입 감지 (v2 단일 주입 위반: opencode.json instructions는 정확히 [\"AGENTS.md\"] 배열만 허용)",
        )
    if not instructions:
        return CheckResult(
            "opencode.json instructions v2 단일 주입",
            False,
            "빈 배열 (v2 단일 주입 위반: instructions가 비어 있으며 정확히 [\"AGENTS.md\"] 배열만 허용)",
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
        f"추가 항목 포함 (v2 단일 주입 위반: 정확히 [\"AGENTS.md\"] 배열만 허용, 추가 항목: {extra})",
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
        return CheckResult("스킬 미러 정합성", True, ".claude/skills, .opencode/skills 내용 완전 일치")
    detail = f"{len(all_diffs)}건 차이: " + " | ".join(all_diffs[:3])
    if len(all_diffs) > 3:
        detail += f" ... 외 {len(all_diffs) - 3}건"
    return CheckResult("스킬 미러 정합성", False, detail)


def check_agents_single_root(root: Path = PROJECT_ROOT) -> CheckResult:
    target = root / "AGENTS.md"
    if not target.exists():
        return CheckResult("AGENTS.md 단일 진실 원천 (@SKILLS.md 미참조)", False, "AGENTS.md 파일 없음")
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
        return CheckResult("Task Capsule v2 규약 문서", False, "docs/ops/orca_task_capsule_v2.md 없음")
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
        return CheckResult("Task Capsule v2 템플릿 정합성", False, f"템플릿 파일 없음: {capsule_yaml}")
    capsule_content = read_text(capsule_yaml)
    if yaml is not None:
        try:
            parsed_capsule = yaml.safe_load(capsule_content) or {}
        except Exception as e:
            return CheckResult("Task Capsule v2 템플릿 정합성", False, f"task_capsule_v2.yaml 파싱 실패: {e}")
    else:
        parsed_capsule = parse_yaml_keys_fallback(capsule_content)

    if parsed_capsule.get("schema") != "ORCA_TASK_CAPSULE_V2":
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"task_capsule_v2.yaml schema 불일치: {parsed_capsule.get('schema')}",
        )
    if str(parsed_capsule.get("version")) != "2.0.0":
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
        return CheckResult("Task Capsule v2 템플릿 정합성", False, f"템플릿 파일 없음: {worker_done_json}")
    try:
        parsed_worker = json.loads(read_text(worker_done_json))
    except json.JSONDecodeError as e:
        return CheckResult("Task Capsule v2 템플릿 정합성", False, f"worker_done_v2.json 파싱 실패: {e}")

    if parsed_worker.get("schema") != "ORCA_WORKER_DONE_V2":
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"worker_done_v2.json schema 불일치: {parsed_worker.get('schema')}",
        )
    if str(parsed_worker.get("version")) != "2.0.0":
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
        return CheckResult("Task Capsule v2 템플릿 정합성", False, f"템플릿 파일 없음: {review_done_json}")
    try:
        parsed_review = json.loads(read_text(review_done_json))
    except json.JSONDecodeError as e:
        return CheckResult("Task Capsule v2 템플릿 정합성", False, f"review_done_v2.json 파싱 실패: {e}")

    if parsed_review.get("schema") != "ORCA_REVIEW_DONE_V2":
        return CheckResult(
            "Task Capsule v2 템플릿 정합성",
            False,
            f"review_done_v2.json schema 불일치: {parsed_review.get('schema')}",
        )
    if str(parsed_review.get("version")) != "2.0.0":
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
        return CheckResult(name, False, "docs/context/CURRENT_STATE.md 없음 (v2 부트스트랩 정본 누락)")
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
        return CheckResult(name, False, "증거 경로(docs/...) 없음. 수치는 evidence path 를 가져야 합니다")

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
        return CheckResult(
            name,
            True,
            f"필수 필드 완비. source_commit {recorded} 은 이 저장소에서 확인할 수 없어 신선도 미검증",
            warn=True,
        )
    if behind > CURRENT_STATE_LAG_TOLERANCE:
        return CheckResult(
            name,
            True,
            f"필수 필드 완비. source_commit {recorded} 이 HEAD 보다 {behind} 커밋 뒤처짐 "
            f"(허용 {CURRENT_STATE_LAG_TOLERANCE}). 현재 상태를 놓치고 있는지 확인하십시오",
            warn=True,
        )
    return CheckResult(
        name,
        True,
        f"필수 필드 완비. source_commit {recorded} 은 HEAD 대비 {behind} 커밋 (허용 {CURRENT_STATE_LAG_TOLERANCE})",
    )


def _commits_behind_head(root: Path, commit: str) -> int | None:
    """기록된 커밋이 HEAD 보다 몇 커밋 뒤처졌는지 셉니다. 확인 불가면 None."""
    # timeout 을 두지 않으면 git 이 잠기거나 잠금 파일을 기다릴 때 검증기가 함께
    # 멈춥니다. 이 검증기는 pre-commit 에서 돌기 때문에 커밋 자체가 막힙니다.
    try:
        subprocess.run(
            ["git", "-C", str(root), "merge-base", "--is-ancestor", commit, "HEAD"],
            check=True,
            capture_output=True,
            timeout=GIT_PROBE_TIMEOUT_SECONDS,
        )
        out = subprocess.run(
            ["git", "-C", str(root), "rev-list", "--count", f"{commit}..HEAD"],
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
        check_current_state_exists(root),
        check_current_state_sections(root),
        check_context_budgets(root),
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
