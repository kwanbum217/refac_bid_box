"""
tests/test_backup_recovery_split.py

scripts/backup_recovery.py 의 기계적 분할 무결성 검증 테스트.
세 파일의 줄 수 상한, 순환 import 부재, 그리고 기존 import 경로 생존을 단언합니다.
상한은 분할 후 실측값 + 20줄입니다.
"""

from __future__ import annotations

import ast
from pathlib import Path

import scripts.backup_recovery as backup_recovery_mod
import scripts.backup_recovery_core as core_mod
import scripts.backup_snapshots as snapshots_mod

REPO_ROOT = Path(__file__).resolve().parent.parent


def test_split_line_counts_within_cap():
    paths = {
        "backup_recovery.py": (REPO_ROOT / "scripts" / "backup_recovery.py", 513),
        "backup_recovery_core.py": (REPO_ROOT / "scripts" / "backup_recovery_core.py", 298),
        "backup_snapshots.py": (REPO_ROOT / "scripts" / "backup_snapshots.py", 151),
    }
    for name, (path, cap) in paths.items():
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= cap, f"{name} exceeds {cap} lines: {lines}"


def test_no_circular_imports_in_split_modules():
    """순환 import 부재 검증: 어느 새 모듈도 backup_recovery 를 import 하면 안 된다."""
    paths = [
        REPO_ROOT / "scripts" / "backup_recovery_core.py",
        REPO_ROOT / "scripts" / "backup_snapshots.py",
    ]
    forbidden_module = "scripts.backup_recovery"
    for path in paths:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name != forbidden_module, (
                        f"{path.name} must not import {forbidden_module}"
                    )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                assert module != forbidden_module, (
                    f"{path.name} must not import from {forbidden_module}"
                )


def test_core_reexport_identities_from_backup_recovery():
    core_symbols = [
        "sha256_file",
        "get_head_commit_sha",
        "get_db_config",
        "get_model_source_paths",
        "get_chroma_source_path",
        "query_db_row_counts",
        "create_tar_archive",
        "dump_mysql_database",
        "restore_mysql_database",
        "extract_tar_archive",
    ]
    for name in core_symbols:
        assert hasattr(core_mod, name), f"backup_recovery_core missing {name}"
        assert hasattr(backup_recovery_mod, name), f"backup_recovery missing re-export {name}"
        assert getattr(backup_recovery_mod, name) is getattr(core_mod, name), (
            f"{name} in backup_recovery is not identical to backup_recovery_core.{name}"
        )


def test_snapshots_reexport_identities_from_backup_recovery():
    snapshot_symbols = [
        "verify_snapshot",
        "list_snapshots",
        "prune_snapshots",
    ]
    for name in snapshot_symbols:
        assert hasattr(snapshots_mod, name), f"backup_snapshots missing {name}"
        assert hasattr(backup_recovery_mod, name), f"backup_recovery missing re-export {name}"
        assert getattr(backup_recovery_mod, name) is getattr(snapshots_mod, name), (
            f"{name} in backup_recovery is not identical to backup_snapshots.{name}"
        )


def test_remaining_functions_stay_in_backup_recovery():
    for name in (
        "execute_backup",
        "run_restore_drill",
        "run_post_restore_verification",
        "execute_restore",
        "build_parser",
        "main",
        "mask_secret",
    ):
        assert hasattr(backup_recovery_mod, name), f"backup_recovery missing {name}"


def test_existing_import_paths_still_resolve():
    public_names = [
        "MANIFEST_FILENAME",
        "create_tar_archive",
        "execute_backup",
        "execute_restore",
        "extract_tar_archive",
        "get_db_config",
        "list_snapshots",
        "mask_secret",
        "prune_snapshots",
        "run_post_restore_verification",
        "run_restore_drill",
        "sha256_file",
        "verify_snapshot",
    ]
    for name in public_names:
        assert hasattr(backup_recovery_mod, name), f"backup_recovery.{name} import path broken"
