import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
MAKEFILE_PATH = PROJECT_ROOT / "Makefile"
CI_WORKFLOW_PATH = PROJECT_ROOT / ".github" / "workflows" / "ci.yml"
CROSS_PLATFORM_GUIDE_PATH = PROJECT_ROOT / "docs" / "ops" / "cross_platform_guide.md"
ENVIRONMENT_VARIABLES_PATH = PROJECT_ROOT / "docs" / "ops" / "environment_variables.md"

# make check-all 이 반드시 실행해야 하는 CI 필수 검사 대상입니다.
CI_PARITY_TARGETS = (
    "frontend-check",
    "lint",
    "security",
    "typecheck",
    "dup-check",
    "check-rules",
    "check-tests",
    "lint-workflows",
    "check-docs",
    "secret-scan",
    "css-check",
)

# check-all 의 보조 대상입니다.
SUPPORT_TARGETS = ("frontend-deps",)

# Makefile 과 CI 가 같은 문자열로 실행해야 하는 명령입니다.
CI_COMMANDS = (
    "dir --no-banner --redact --config .gitleaks.toml .",
    "git --no-banner --redact --config .gitleaks.toml .",
    "scripts/validate_doc_links.py",
    "jscpd",
    "npm ci",
    "npx tsc --noEmit",
    "npm run test",
    "npm run build",
    "npm run build:css",
    "git diff --exit-code -- src/app/static/css/tailwind.css",
    "ruff check .",
    "ruff format --check .",
    "bandit -c pyproject.toml -r src/ scripts/",
    "mypy src/",
    "scripts/validate_agent_rules.py",
    "actionlint",
)

# 로컬에서 실행할 수 없어 check-all 에서 제외한 CI 게이트와 사유가 주석으로 남아 있어야 합니다.
LOCAL_EXCLUSIONS = (
    "supply-chain",
    "e2e-browser-test",
    "docker-build",
    "mysql-ngram-integration",
    "g1-schema-signature",
    "pytest 경고 예산",
)

# Windows(Git Bash)에서 make 레시피가 깨지는 셸 구성입니다.
WINDOWS_UNSAFE_TOKENS = ("/tmp/", "sudo ", "mapfile ", "<(", "sha256sum", "#!/bin/bash")


def _makefile_text() -> str:
    return MAKEFILE_PATH.read_text(encoding="utf-8")


def _check_all_dependencies(text: str) -> list[str]:
    match = re.search(r"^check-all:([^\n]*)$", text, re.MULTILINE)
    assert match is not None, "check-all 대상을 찾지 못했습니다"
    return match.group(1).split()


def _recipe(target: str, text: str) -> str:
    match = re.search(
        rf"^{re.escape(target)}:(?:[^\n]*)\n((?:\t[^\n]*\n)+)",
        text,
        re.MULTILINE,
    )
    assert match is not None, f"{target} 대상의 레시피를 찾지 못했습니다"
    return match.group(1)


def test_check_all_dependencies_cover_ci_gates():
    dependencies = _check_all_dependencies(_makefile_text())
    missing = [target for target in CI_PARITY_TARGETS if target not in dependencies]
    assert not missing, f"check-all 에 빠진 CI 필수 검사: {missing}"


def test_parity_targets_are_phony():
    text = _makefile_text()
    match = re.search(r"^\.PHONY:([^\n]*)$", text, re.MULTILINE)
    assert match is not None, ".PHONY 선언을 찾지 못했습니다"
    declared = set(match.group(1).split())
    missing = [target for target in CI_PARITY_TARGETS + SUPPORT_TARGETS if target not in declared]
    assert not missing, f".PHONY 에 빠진 대상: {missing}"


def test_parity_targets_have_recipes():
    text = _makefile_text()
    for target in CI_PARITY_TARGETS + SUPPORT_TARGETS:
        assert _recipe(target, text).strip(), f"{target} 레시피가 비어 있습니다"


def test_make_and_ci_use_same_commands():
    makefile_text = _makefile_text()
    missing = [command for command in CI_COMMANDS if command not in makefile_text]
    assert not missing, f"Makefile 에 없는 CI 명령: {missing}"

    ci_text = CI_WORKFLOW_PATH.read_text(encoding="utf-8")
    missing = [command for command in CI_COMMANDS if command not in ci_text]
    assert not missing, f"CI 워크플로우에서 사라진 명령: {missing}"


def test_local_exclusions_are_documented():
    text = _makefile_text()
    assert "로컬에서 실행할 수 없어 제외한 CI 게이트" in text
    missing = [gate for gate in LOCAL_EXCLUSIONS if gate not in text]
    assert not missing, f"로컬 제외 사유가 빠진 CI 게이트: {missing}"


def test_parity_target_recipes_avoid_windows_unsafe_shell():
    text = _makefile_text()
    for target in CI_PARITY_TARGETS + SUPPORT_TARGETS:
        recipe = _recipe(target, text)
        unsafe = [token for token in WINDOWS_UNSAFE_TOKENS if token in recipe]
        assert not unsafe, f"{target} 레시피에 Windows 비호환 셸 구성: {unsafe}"


def test_cross_platform_guide_documents_check_all_targets():
    guide = CROSS_PLATFORM_GUIDE_PATH.read_text(encoding="utf-8")
    missing = [target for target in CI_PARITY_TARGETS if f"`{target}`" not in guide]
    assert not missing, f"크로스 플랫폼 가이드에 빠진 대상: {missing}"


def test_local_tool_overrides_are_documented():
    document = ENVIRONMENT_VARIABLES_PATH.read_text(encoding="utf-8")
    for variable in ("PYTHON", "UV", "GITLEAKS"):
        assert f"`{variable}`" in document, f"환경변수 명세에 빠진 Makefile 변수: {variable}"
