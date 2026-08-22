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


def test_register_missing_settings_graceful_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys
):
    """CLI settings.json이 없으면 자동 생성하지 않고 종료 코드 2로 안전하게 실패합니다."""
    gemini_dir = tmp_path / ".gemini"
    settings_path = gemini_dir / "antigravity-cli" / "settings.json"
    folders_path = gemini_dir / "trustedFolders.json"
    monkeypatch.setattr(orca_trust_worktree, "CLI_SETTINGS", settings_path)
    monkeypatch.setattr(orca_trust_worktree, "TRUSTED_FOLDERS", folders_path)
    monkeypatch.setattr(orca_trust_worktree, "LOCK_FILE", gemini_dir / ".trust.lock")

    worktree = tmp_path / "worker"
    worktree.mkdir()

    exit_code = orca_trust_worktree.register([worktree], dry_run=False)
    captured = capsys.readouterr()

    assert exit_code == 2
    assert "CLI 설정을 찾을 수 없습니다" in captured.err
    assert not settings_path.exists()
    assert not folders_path.exists()


def test_settings_lock_timeout(trust_files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """활성 락 파일이 존재하고 만료되지 않았을 때 타임아웃 예외가 발생해야 합니다."""
    monkeypatch.setattr(orca_trust_worktree, "LOCK_TIMEOUT_SECONDS", 0.1)
    lock_file = orca_trust_worktree.LOCK_FILE
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text("999999", encoding="utf-8")

    with (
        pytest.raises(RuntimeError, match="신뢰 설정 잠금을 획득하지 못했습니다"),
        orca_trust_worktree._settings_lock(),
    ):
        pass


def test_settings_lock_stale_recovery(trust_files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """오래된(stale) 락 파일이 존재할 경우 이를 회수하고 정상적으로 락을 획득해야 합니다."""
    lock_file = orca_trust_worktree.LOCK_FILE
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    lock_file.write_text("999999", encoding="utf-8")

    import os
    import time

    stale_time = time.time() - (orca_trust_worktree.STALE_LOCK_SECONDS + 10.0)
    os.utime(lock_file, (stale_time, stale_time))

    # stale lock이 정상적으로 회수되어 lock 진입 성공
    with orca_trust_worktree._settings_lock():
        assert lock_file.exists()
        assert lock_file.read_text(encoding="utf-8") == str(os.getpid())

    # contextmanager 종료 후 락 파일 정리 확인
    assert not lock_file.exists()


def test_register_rolls_back_initially_absent_files(
    trust_files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """원래 존재하지 않던 trustedFolders.json 파일이 쓰기 중 에러 발생 시 삭제(롤백)되는지 검증합니다."""
    settings_path, folders_path = trust_files
    # folders_path는 fixture 시점에 아직 생성되지 않은 상태
    assert not folders_path.exists()

    worktree = tmp_path / "worker"
    worktree.mkdir()
    settings_before = settings_path.read_text(encoding="utf-8")

    original_write = orca_trust_worktree._atomic_write
    failed = False

    def fail_after_writing_settings(path: Path, payload):
        nonlocal failed
        if path == folders_path and not failed:
            failed = True
            raise OSError("simulated disk error on folders write")
        original_write(path, payload)

    monkeypatch.setattr(orca_trust_worktree, "_atomic_write", fail_after_writing_settings)

    exit_code = orca_trust_worktree.register([worktree], dry_run=False)
    assert exit_code == 1
    # settings.json은 원래 내용으로 복원
    assert settings_path.read_text(encoding="utf-8") == settings_before
    # folders_path는 원래 없었으므로 롤백 후에도 존재하지 않아야 함
    assert not folders_path.exists()
