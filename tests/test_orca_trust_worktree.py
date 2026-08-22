"""scripts.orca_trust_worktree.py의 원자적 신뢰 등록 회귀 테스트."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts import orca_trust_worktree


@pytest.fixture
def trust_files(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    gemini_dir = tmp_path / ".gemini"
    settings_path = gemini_dir / "antigravity-cli" / "settings.json"
    folders_path = gemini_dir / "trustedFolders.json"
    settings_path.parent.mkdir(parents=True)
    settings_path.write_text('{"other": true}\n', encoding="utf-8")
    monkeypatch.setattr(orca_trust_worktree, "CLI_SETTINGS", settings_path)
    monkeypatch.setattr(orca_trust_worktree, "TRUSTED_FOLDERS", folders_path)
    monkeypatch.setattr(orca_trust_worktree, "LOCK_FILE", gemini_dir / ".trust.lock")
    return settings_path, folders_path


def test_register_creates_missing_trusted_folders_file(trust_files, tmp_path: Path):
    """처음 실행에도 trustedFolders.json을 생성하고 등록합니다."""
    settings_path, folders_path = trust_files
    worktree = tmp_path / "worker"
    worktree.mkdir()

    assert orca_trust_worktree.register([worktree], dry_run=False) == 0

    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    folders = json.loads(folders_path.read_text(encoding="utf-8"))
    assert str(worktree.resolve()) in settings["trustedWorkspaces"]
    assert folders[str(worktree.resolve()).lower()] == "TRUST_FOLDER"


def test_register_rolls_back_both_files_when_second_write_fails(
    trust_files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """두 번째 파일 쓰기가 실패하면 첫 번째 파일도 원본으로 복구합니다."""
    settings_path, folders_path = trust_files
    folders_path.write_text('{"existing": "TRUST_FOLDER"}\n', encoding="utf-8")
    worktree = tmp_path / "worker"
    worktree.mkdir()
    settings_before = settings_path.read_text(encoding="utf-8")
    folders_before = folders_path.read_text(encoding="utf-8")
    original_write = orca_trust_worktree._atomic_write
    failed = False

    def fail_once_on_folders(path: Path, payload):
        nonlocal failed
        if path == folders_path and not failed:
            failed = True
            raise OSError("simulated write failure")
        original_write(path, payload)

    monkeypatch.setattr(orca_trust_worktree, "_atomic_write", fail_once_on_folders)

    assert orca_trust_worktree.register([worktree], dry_run=False) == 1
    assert settings_path.read_text(encoding="utf-8") == settings_before
    assert folders_path.read_text(encoding="utf-8") == folders_before
