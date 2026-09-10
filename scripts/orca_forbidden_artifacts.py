"""Orca 작업 트리에서 금지하는 패키지 관리자 산출물 정책."""

from __future__ import annotations

FORBIDDEN_PACKAGE_MANAGER_ARTIFACTS = frozenset(
    {"pnpm-lock.yaml", "pnpm-workspace.yaml", "yarn.lock", "bun.lockb"}
)
