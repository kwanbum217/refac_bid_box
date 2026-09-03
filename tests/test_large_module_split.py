"""
tests/test_large_module_split.py

automation_tasks / monitoring 기계적 분할 무결성 및 정합성 검증 테스트.
"""

from __future__ import annotations

import ast
from pathlib import Path

import src.ml.monitoring as monitoring_mod
import src.ml.psi as psi_mod
import src.tasks.automation_steps as automation_steps_mod
import src.tasks.automation_tasks as automation_tasks_mod


def test_large_module_line_counts():
    repo_root = Path(__file__).resolve().parent.parent
    paths = {
        "automation_tasks.py": (
            repo_root / "src/tasks/automation_tasks.py",
            452,
        ),
        "automation_steps.py": (
            repo_root / "src/tasks/automation_steps.py",
            356,
        ),
        "monitoring.py": (
            repo_root / "src/ml/monitoring.py",
            582,
        ),
        "psi.py": (
            repo_root / "src/ml/psi.py",
            165,
        ),
    }
    for name, (path, cap) in paths.items():
        lines = len(path.read_text(encoding="utf-8").splitlines())
        assert lines <= cap, f"{name} exceeds {cap} lines: {lines}"


def test_no_circular_imports_in_split_modules():
    repo_root = Path(__file__).resolve().parent.parent
    cases = [
        (
            repo_root / "src/tasks/automation_steps.py",
            "src.tasks.automation_tasks",
            "src.tasks",
            "automation_tasks",
        ),
        (
            repo_root / "src/ml/psi.py",
            "src.ml.monitoring",
            "src.ml",
            "monitoring",
        ),
    ]
    for path, forbidden_module, parent_pkg, sibling_name in cases:
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
                assert not (
                    module == parent_pkg and any(a.name == sibling_name for a in node.names)
                ), f"{path.name} must not import {sibling_name} from {parent_pkg}"


def test_automation_step_reexport_identities():
    symbols = [
        "_step_collect",
        "_step_rag",
        "_step_search",
        "_step_predict",
        "_step_retrain",
        "_check_chroma_vectors",
        "_step_inspect",
    ]
    for name in symbols:
        assert hasattr(automation_steps_mod, name), f"automation_steps missing {name}"
        assert hasattr(automation_tasks_mod, name), f"automation_tasks missing re-export {name}"
        assert getattr(automation_tasks_mod, name) is getattr(automation_steps_mod, name), (
            f"{name} in automation_tasks is not identical to automation_steps.{name}"
        )


def test_psi_reexport_identities():
    symbols = [
        "InsufficientSampleError",
        "calculate_psi",
        "calculate_categorical_psi",
        "check_feature_drift",
    ]
    for name in symbols:
        assert hasattr(psi_mod, name), f"psi missing {name}"
        assert hasattr(monitoring_mod, name), f"monitoring missing re-export {name}"
        assert getattr(monitoring_mod, name) is getattr(psi_mod, name), (
            f"{name} in monitoring is not identical to psi.{name}"
        )


def test_core_symbols_remain_in_parent_modules():
    for name in ("run_automation_pipeline", "STEP_RUNNERS", "_report", "manual_full_task"):
        assert hasattr(automation_tasks_mod, name), f"automation_tasks missing {name}"
    for name in (
        "check_dataset_drift",
        "save_baseline_distributions",
        "load_baseline_distributions",
    ):
        assert hasattr(monitoring_mod, name), f"monitoring missing {name}"
