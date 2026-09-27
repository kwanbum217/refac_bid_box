"""tests/test_orca_forbidden_artifacts.py

scripts/orca_forbidden_artifacts.py 의 금지 패키지 관리자 산출물 정책을 검증하는 테스트.
"""

from __future__ import annotations

from scripts.orca_forbidden_artifacts import FORBIDDEN_PACKAGE_MANAGER_ARTIFACTS


def test_forbidden_artifacts_covers_pnpm_yarn_bun():
    """금지 산출물 목록이 pnpm, yarn, bun 의 잠금 파일을 전부 포함하는지 검증합니다."""
    assert (
        frozenset({"pnpm-lock.yaml", "pnpm-workspace.yaml", "yarn.lock", "bun.lockb"})
        == FORBIDDEN_PACKAGE_MANAGER_ARTIFACTS
    )


def test_forbidden_artifacts_is_immutable_frozenset():
    """정책 목록이 변경 불가능한 frozenset 인지 검증합니다."""
    assert isinstance(FORBIDDEN_PACKAGE_MANAGER_ARTIFACTS, frozenset)
    assert "package-lock.json" not in FORBIDDEN_PACKAGE_MANAGER_ARTIFACTS
    assert "npm-shrinkwrap.json" not in FORBIDDEN_PACKAGE_MANAGER_ARTIFACTS
