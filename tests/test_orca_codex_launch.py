"""tests/test_orca_codex_launch.py

scripts/orca_codex_launch.py 의 워크트리 대기, Capsule 배치, 종료 코드 분기를 검증하는 테스트.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from scripts.orca_codex_launch import main, place_capsule, wait_for_worktree


class _FakeProc:
    def __init__(self, payload: str, returncode: int = 0):
        self._payload = payload
        self.returncode = returncode

    def communicate(self, timeout: float) -> tuple[str, None]:
        return self._payload, None


def test_place_capsule_copies_capsules_and_env(tmp_path):
    repo = tmp_path / "repo"
    capsule = repo / ".orca" / "capsules" / "task_x"
    capsule.mkdir(parents=True)
    (capsule / "capsule.yaml").write_text("schema: ORCA_TASK_CAPSULE_V2", encoding="utf-8")
    (repo / ".env").write_text("KEY=value", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()

    placed = place_capsule(worktree, repo)

    assert placed == [".orca/capsules", ".env"]
    assert (worktree / ".orca" / "capsules" / "task_x" / "capsule.yaml").is_file()
    assert (worktree / ".env").is_file()


def test_place_capsule_skips_missing_sources(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    worktree = tmp_path / "wt"
    worktree.mkdir()

    assert place_capsule(worktree, repo) == []


def test_place_capsule_does_not_overwrite_existing_env(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".env").write_text("REPO=1", encoding="utf-8")
    worktree = tmp_path / "wt"
    worktree.mkdir()
    (worktree / ".env").write_text("WT=1", encoding="utf-8")

    placed = place_capsule(worktree, repo)

    assert placed == []
    assert (worktree / ".env").read_text(encoding="utf-8") == "WT=1"


def test_wait_for_worktree_true_when_present(tmp_path):
    assert wait_for_worktree(tmp_path, timeout=1) is True


def test_wait_for_worktree_false_on_timeout(tmp_path):
    assert wait_for_worktree(tmp_path / "missing", timeout=0.3) is False


def test_main_returns_zero_on_ok_payload(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    with patch(
        "scripts.orca_codex_launch.subprocess.Popen",
        return_value=_FakeProc(json.dumps({"ok": True})),
    ):
        rc = main(
            [
                "--task",
                "task_x",
                "--name",
                "wt",
                "--repo",
                str(tmp_path),
                "--workspaces",
                str(tmp_path),
                "--timeout-sec",
                "1",
            ]
        )
    assert rc == 0


def test_main_returns_one_when_payload_reports_failure(tmp_path):
    worktree = tmp_path / "wt"
    worktree.mkdir()
    with patch(
        "scripts.orca_codex_launch.subprocess.Popen",
        return_value=_FakeProc(json.dumps({"ok": False})),
    ):
        rc = main(
            [
                "--task",
                "task_x",
                "--name",
                "wt",
                "--repo",
                str(tmp_path),
                "--workspaces",
                str(tmp_path),
                "--timeout-sec",
                "1",
            ]
        )
    assert rc == 1


def test_main_returns_process_code_on_bad_payload_and_missing_worktree(tmp_path):
    with patch(
        "scripts.orca_codex_launch.subprocess.Popen",
        return_value=_FakeProc("not json", returncode=2),
    ):
        rc = main(
            [
                "--task",
                "task_x",
                "--name",
                "missing",
                "--repo",
                str(tmp_path),
                "--workspaces",
                str(tmp_path),
                "--effort",
                "high",
                "--timeout-sec",
                "0.3",
            ]
        )
    assert rc == 2
