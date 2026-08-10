#!/usr/bin/env python3
"""
다중 에이전트 규칙 자동 로드 통합 정합성 검증 스크립트 (pre-commit).

단일 진실 원천(AGENTS.md) + 얇은 진입점(thin pointer/요약본) 아키텍처가
깨지지 않았는지 커밋 직전에 검증합니다.

검증 항목:
  1. CLAUDE.md 가 @AGENTS.md thin pointer 인지 (정본 복사 금지)
  2. .antigravity/rules.md 가 존재 + 12,000자 이하 + 핵심 섹션 포함
  3. .cursor/rules/00-core-guidelines.mdc 가 AGENTS.md 참조 여부
  4. .agents/skills/ 와 .claude/skills/, .opencode/skills/ 내용 동일성 (미러 정합성)
  5. AGENTS.md 에 @SKILLS.md import 구문 존재 여부
  6. opencode.json instructions 배열 포함 여부

사용:
  python scripts/validate_agent_rules.py          # 전체 검증
  python scripts/validate_agent_rules.py --quiet   # 요약만

pre-commit 연동:
  .git/hooks/pre-commit 에서 본 스크립트 호출.
"""

from __future__ import annotations

import argparse
import filecmp
import json
import sys
from pathlib import Path

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

PROJECT_ROOT = Path(__file__).resolve().parent.parent

ANTIGRAVITY_CHAR_CAP = 12000

AGENTS_MD = PROJECT_ROOT / "AGENTS.md"
SKILLS_MD = PROJECT_ROOT / "SKILLS.md"
CLAUDE_MD = PROJECT_ROOT / "CLAUDE.md"
ANTIGRAVITY_RULES = PROJECT_ROOT / ".antigravity" / "rules.md"
CURSOR_CORE_RULE = PROJECT_ROOT / ".cursor" / "rules" / "00-core-guidelines.mdc"
OPENCODE_JSON = PROJECT_ROOT / "opencode.json"
AGENTS_SKILLS_DIR = PROJECT_ROOT / ".agents" / "skills"
CLAUDE_SKILLS_DIR = PROJECT_ROOT / ".claude" / "skills"
OPENCODE_SKILLS_DIR = PROJECT_ROOT / ".opencode" / "skills"

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


class CheckResult:
    def __init__(self, name: str, ok: bool, detail: str = "") -> None:
        self.name = name
        self.ok = ok
        self.detail = detail

    def format(self, quiet: bool = False) -> str:
        tag = "PASS" if self.ok else "FAIL"
        line = f"[{tag}] {self.name}"
        if not quiet and self.detail:
            line += f"\n       {self.detail}"
        return line


def read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError):
        return ""


def check_claude_is_pointer() -> CheckResult:
    if not CLAUDE_MD.exists():
        return CheckResult("CLAUDE.md thin pointer", False, "CLAUDE.md 파일 없음")
    content = read_text(CLAUDE_MD)
    has_import = "@AGENTS.md" in content
    canonical_markers = ["## 2. 기술 스택", "## 3. 코딩 규칙", "## 6. 금지 행위"]
    copied_count = sum(1 for marker in canonical_markers if marker in content)
    is_pointer = has_import and copied_count == 0
    if is_pointer:
        return CheckResult("CLAUDE.md thin pointer", True, "@AGENTS.md import 포함, 정본 미복사")
    detail = f"@AGENTS.md import={'있음' if has_import else '없음'}, 정본 섹션 {copied_count}개 복사됨"
    return CheckResult("CLAUDE.md thin pointer", False, detail)


def check_antigravity_rules() -> CheckResult:
    if not ANTIGRAVITY_RULES.exists():
        return CheckResult(".antigravity/rules.md", False, "파일 없음")
    content = read_text(ANTIGRAVITY_RULES)
    char_count = len(content)
    if char_count > ANTIGRAVITY_CHAR_CAP:
        over = char_count - ANTIGRAVITY_CHAR_CAP
        return CheckResult(".antigravity/rules.md", False, f"{char_count:,}자, 캡 초과 {over:,}자")
    missing = [s for s in ANTIGRAVITY_REQUIRED_SECTIONS if s not in content]
    if missing:
        return CheckResult(".antigravity/rules.md", False, f"핵심 키워드 누락: {missing}")
    margin = ANTIGRAVITY_CHAR_CAP - char_count
    return CheckResult(
        ".antigravity/rules.md", True,
        f"{char_count:,}자 (여유 {margin:,}자), 핵심 섹션 포함",
    )


def check_cursor_references_agents() -> CheckResult:
    if not CURSOR_CORE_RULE.exists():
        return CheckResult(".cursor core rule AGENTS.md 참조", False, "00-core-guidelines.mdc 없음")
    content = read_text(CURSOR_CORE_RULE)
    if "AGENTS.md" in content:
        return CheckResult(".cursor core rule AGENTS.md 참조", True, "AGENTS.md 참조 확인")
    return CheckResult(".cursor core rule AGENTS.md 참조", False, "AGENTS.md 참조 문구 없음")


def check_opencode_json() -> CheckResult:
    if not OPENCODE_JSON.exists():
        return CheckResult("opencode.json instructions", False, "opencode.json 없음")
    try:
        data = json.loads(read_text(OPENCODE_JSON))
        instructions = data.get("instructions", [])
        has_agents = "AGENTS.md" in instructions
        has_skills = "SKILLS.md" in instructions
        if has_agents and has_skills:
            return CheckResult("opencode.json instructions", True, "AGENTS.md, SKILLS.md 포함")
        missing = []
        if not has_agents:
            missing.append("AGENTS.md")
        if not has_skills:
            missing.append("SKILLS.md")
        return CheckResult("opencode.json instructions", False, f"누락: {missing}")
    except json.JSONDecodeError as e:
        return CheckResult("opencode.json instructions", False, f"JSON 파싱 실패: {e}")


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


def check_skills_mirror() -> CheckResult:
    mirrors = [
        (".claude/skills", CLAUDE_SKILLS_DIR),
        (".opencode/skills", OPENCODE_SKILLS_DIR),
    ]
    all_diffs: list[str] = []
    for label, mirror_dir in mirrors:
        equal, diffs = _dir_trees_equal(AGENTS_SKILLS_DIR, mirror_dir)
        if not equal:
            all_diffs.extend(f"{label}: {diff}" for diff in diffs)
    if not all_diffs:
        return CheckResult("스킬 미러 정합성", True, ".claude/skills, .opencode/skills 내용 완전 일치")
    detail = f"{len(all_diffs)}건 차이: " + " | ".join(all_diffs[:3])
    if len(all_diffs) > 3:
        detail += f" ... 외 {len(all_diffs) - 3}건"
    return CheckResult("스킬 미러 정합성", False, detail)


def check_agents_imports_skills() -> CheckResult:
    content = read_text(AGENTS_MD)
    if "@SKILLS.md" in content:
        return CheckResult("AGENTS.md @SKILLS.md import", True, "import 구문 존재")
    return CheckResult("AGENTS.md @SKILLS.md import", False, "@SKILLS.md 구문 없음")


def run_all_checks(quiet: bool = False) -> int:
    checks: list[CheckResult] = [
        check_claude_is_pointer(),
        check_antigravity_rules(),
        check_cursor_references_agents(),
        check_opencode_json(),
        check_skills_mirror(),
        check_agents_imports_skills(),
    ]
    print("=" * 60)
    print("다중 에이전트 규칙 정합성 검증 (pre-commit)")
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
    parser = argparse.ArgumentParser(description="다중 에이전트 규칙 정합성 검증 (pre-commit)")
    parser.add_argument("--quiet", action="store_true", help="요약만 출력")
    args = parser.parse_args()
    return run_all_checks(quiet=args.quiet)


if __name__ == "__main__":
    sys.exit(main())
