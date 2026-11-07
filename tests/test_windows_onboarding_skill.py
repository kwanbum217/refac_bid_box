"""windows-onboarding 스킬과 사전 점검 스크립트의 정적 계약을 검증합니다."""

from __future__ import annotations

import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CANONICAL_SKILL = PROJECT_ROOT / ".agents/skills/windows-onboarding/SKILL.md"
MIRROR_SKILLS = (
    PROJECT_ROOT / ".claude/skills/windows-onboarding/SKILL.md",
    PROJECT_ROOT / ".opencode/skills/windows-onboarding/SKILL.md",
)
CHECK_SCRIPT = PROJECT_ROOT / "scripts/windows/check_prereqs.ps1"

REQUIRED_HEADINGS = (
    "## 0. 안전 규칙",
    "## 1. 사전 점검",
    "## 2. 설치",
    "## 3. 저장소 준비",
    "## 4. 데이터 확보",
    "## 5. 실행",
    "## 6. 문제 해결",
    "## 7. 실행 확인",
)

REQUIRED_SAFETY_PHRASES = (
    "사용자",
    "관리자 권한",
    "재부팅",
    ".env.example",
    "공개 저장소",
)

EXECUTION_TOKENS = (
    "Start-Process",
    "Invoke-Expression",
    "Invoke-Command",
    "Start-Job",
    "Restart-Computer",
    "Set-ExecutionPolicy",
    "| winget",
    "cmd.exe",
)

INSTALL_EXECUTION_PATTERN = re.compile(r"&\s*['\"]?winget['\"]?\s+install")
INSTALL_LINE_PATTERN = re.compile(r"^'[^']+'\s*=\s*'(?:winget install|wsl --install)[^']*'$")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_canonical_skill_has_frontmatter_and_sections() -> None:
    content = read_text(CANONICAL_SKILL)

    assert content.startswith("---\n")
    frontmatter = content.split("---\n", 2)[1]
    assert "name: windows-onboarding" in frontmatter
    assert "description: " in frontmatter
    assert "호출됩니다" in frontmatter

    for heading in REQUIRED_HEADINGS:
        assert heading in content, heading

    headings = [line for line in content.splitlines() if line.startswith("## ")]
    assert [line for line in headings if re.match(r"## \d\.", line)] == list(REQUIRED_HEADINGS)


def test_safety_rules_come_before_installation() -> None:
    content = read_text(CANONICAL_SKILL)

    assert content.index("## 0. 안전 규칙") < content.index("## 2. 설치")
    for phrase in REQUIRED_SAFETY_PHRASES:
        assert phrase in content, phrase


def test_skill_points_to_checker_and_handoff_skill() -> None:
    content = read_text(CANONICAL_SKILL)

    assert "scripts/windows/check_prereqs.ps1" in content
    assert "platform-health-checklist" in content
    for command in ("make up", "make migrate-up", "docker compose up --build -d"):
        assert command in content, command


def test_mirrors_match_canonical_bytes() -> None:
    canonical = CANONICAL_SKILL.read_bytes()

    for mirror in MIRROR_SKILLS:
        assert mirror.is_file(), mirror
        assert mirror.read_bytes() == canonical, mirror


def test_checker_is_read_only() -> None:
    content = read_text(CHECK_SCRIPT)

    for token in EXECUTION_TOKENS:
        assert token not in content, token
    assert not INSTALL_EXECUTION_PATTERN.search(content)


def test_checker_prints_install_commands_without_executing() -> None:
    content = read_text(CHECK_SCRIPT)
    install_lines = [line.strip() for line in content.splitlines() if "install" in line]

    assert any("winget install" in line for line in install_lines)
    assert any("wsl --install" in line for line in install_lines)
    for line in install_lines:
        if "winget install" in line or "wsl --install" in line:
            assert INSTALL_LINE_PATTERN.match(line), line


def test_checker_covers_tools_ports_and_exit_codes() -> None:
    content = read_text(CHECK_SCRIPT)

    for token in (
        "Git.Git",
        "Docker.DockerDesktop",
        "astral-sh.uv",
        "Python.Python.3.13",
        "OpenJS.NodeJS.LTS",
        "GnuWin32.Make",
        "wsl --status",
        "VirtualizationFirmwareEnabled",
        "3306",
        "6379",
        "7700",
        "8000",
        "exit 0",
        "exit 1",
    ):
        assert token in content, token
