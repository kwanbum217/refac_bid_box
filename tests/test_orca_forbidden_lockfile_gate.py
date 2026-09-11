from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

from scripts import orca_worker_watch as worker_watch
from scripts.orca_level1_gate import (
    build_json_output,
    find_forbidden_lockfiles,
    run_gate9_forbidden_lockfiles,
)

FORBIDDEN_NAMES = ("pnpm-lock.yaml", "pnpm-workspace.yaml", "yarn.lock", "bun.lockb")


def test_worker_watch_direct_execution_from_non_repository_cwd(tmp_path: Path) -> None:
    script = Path(__file__).resolve().parents[1] / "scripts" / "orca_worker_watch.py"

    result = subprocess.run(  # noqa: S603  고정된 인터프리터와 스크립트만 실행합니다
        [sys.executable, str(script), "--json"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode in (0, 1)
    assert "ModuleNotFoundError" not in result.stderr
    json.loads(result.stdout)


@pytest.mark.parametrize("filename", FORBIDDEN_NAMES)
def test_gate9_detects_each_forbidden_artifact(tmp_path: Path, filename: str) -> None:
    target = tmp_path / "nested" / filename
    target.parent.mkdir()
    target.write_text("generated\n", encoding="utf-8")

    result = run_gate9_forbidden_lockfiles(tmp_path)

    assert result.status == "fail"
    assert result.raw_data["forbidden_files"] == [f"nested/{filename}"]
    assert target.relative_to(tmp_path).as_posix() in result.details[0]


def test_gate9_detects_untracked_artifact_and_wires_json_key(tmp_path: Path) -> None:
    (tmp_path / "pnpm-lock.yaml").write_text("untracked\n", encoding="utf-8")

    result = run_gate9_forbidden_lockfiles(tmp_path)
    payload = build_json_output([result], "fail", 1, 0, 0, 1)

    assert result.status == "fail"
    assert payload["gates"]["gate9_forbidden_lockfiles"]["status"] == "fail"
    assert payload["exit_code"] == 1


def test_gate9_exempts_npm_lockfiles(tmp_path: Path) -> None:
    (tmp_path / "package-lock.json").write_text("{}\n", encoding="utf-8")
    frontend = tmp_path / "frontend"
    frontend.mkdir()
    (frontend / "package-lock.json").write_text("{}\n", encoding="utf-8")

    assert find_forbidden_lockfiles(tmp_path) == []
    assert run_gate9_forbidden_lockfiles(tmp_path).status == "pass"


def test_gate9_excludes_node_modules(tmp_path: Path) -> None:
    package_file = tmp_path / "node_modules" / "dependency" / "pnpm-lock.yaml"
    package_file.parent.mkdir(parents=True)
    package_file.write_text("third-party\n", encoding="utf-8")

    assert find_forbidden_lockfiles(tmp_path) == []


def test_worker_watch_warns_without_blocking(tmp_path: Path) -> None:
    artifact = tmp_path / "pnpm-workspace.yaml"
    artifact.write_text("untracked\n", encoding="utf-8")
    fake_worktrees = [("worker", str(tmp_path), "feature")]

    def fake_progress(_path: str, _base: str, status_lines: list[str]) -> tuple[int, int]:
        status_lines.append("?? pnpm-workspace.yaml")
        return 0, 1

    with (
        patch.object(worker_watch, "list_worktrees", return_value=fake_worktrees),
        patch.object(worker_watch, "worktree_progress", side_effect=fake_progress),
        patch.object(worker_watch, "terminal_map", return_value={}),
        patch.object(worker_watch, "collect_lingering_sessions", return_value=[]),
        patch.object(worker_watch, "collect_unanswered_questions", return_value=[]),
    ):
        states = worker_watch.collect(tmp_path, "main")

    assert len(states) == 1
    assert states[0].blocked is False
    assert states[0].forbidden_lockfiles == ["pnpm-workspace.yaml"]
    assert any("금지된 패키지 관리자 산출물" in note for note in states[0].notes)
    payload = states[0].as_dict()
    assert payload["forbidden_lockfiles"] == ["pnpm-workspace.yaml"]


def test_worker_watch_reuses_status_lines_without_running_a_second_process(
    tmp_path: Path,
) -> None:
    status_lines: list[str] = []
    with patch.object(
        worker_watch,
        "_run",
        side_effect=["", "?? nested/yarn.lock\n"],
    ) as run:
        progress = worker_watch.worktree_progress(str(tmp_path), status_lines=status_lines)

    assert progress == (0, 1)
    assert status_lines == ["?? nested/yarn.lock"]
    assert worker_watch.find_forbidden_lockfiles(tmp_path, status_lines) == ["nested/yarn.lock"]
    assert run.call_count == 2
    assert run.call_args_list[-1].args[0][3:] == ["status", "--short"]
