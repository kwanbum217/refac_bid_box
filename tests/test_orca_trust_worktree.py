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
    """다른 컨텍스트가 락을 점유 중일 때 타임아웃 예외가 발생해야 합니다."""
    monkeypatch.setattr(orca_trust_worktree, "LOCK_TIMEOUT_SECONDS", 0.1)

    with (
        orca_trust_worktree._settings_lock(),
        pytest.raises(RuntimeError, match="신뢰 설정 잠금을 획득하지 못했습니다"),
        orca_trust_worktree._settings_lock(),
    ):
        pass


def test_settings_lock_abnormal_termination_recovery(
    trust_files, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """비정상 종료된 프로세스가 잡고 있던 락은 OS 커널에 의해 즉시 회수되어 새 프로세스가 획득할 수 있어야 합니다."""
    lock_file = orca_trust_worktree.LOCK_FILE
    lock_file.parent.mkdir(parents=True, exist_ok=True)
    monkeypatch.setattr(orca_trust_worktree, "LOCK_TIMEOUT_SECONDS", 1.0)

    import subprocess
    import sys

    repo_root = Path(__file__).resolve().parent.parent
    child_code = (
        "import sys\n"
        "sys.path.insert(0, sys.argv[1])\n"
        "import time\n"
        "from pathlib import Path\n"
        "from scripts import orca_trust_worktree\n"
        "orca_trust_worktree.LOCK_FILE = Path(sys.argv[2])\n"
        "with orca_trust_worktree._settings_lock():\n"
        "    sys.stdout.write('LOCKED\\n')\n"
        "    sys.stdout.flush()\n"
        "    time.sleep(30)\n"
    )
    proc = subprocess.Popen(  # noqa: S603
        [sys.executable, "-c", child_code, str(repo_root), str(lock_file)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert proc.stdout is not None
        line = proc.stdout.readline()
        assert line.strip() == "LOCKED"

        monkeypatch.setattr(orca_trust_worktree, "LOCK_TIMEOUT_SECONDS", 0.1)
        with (
            pytest.raises(RuntimeError, match="신뢰 설정 잠금을 획득하지 못했습니다"),
            orca_trust_worktree._settings_lock(),
        ):
            pass

        proc.kill()
        proc.wait()

        monkeypatch.setattr(orca_trust_worktree, "LOCK_TIMEOUT_SECONDS", 1.0)
        with orca_trust_worktree._settings_lock():
            assert lock_file.exists()
        token = lock_file.read_text(encoding="utf-8").strip()
        assert ":" in token
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()


def test_settings_lock_fails_closed_when_no_lock_available(
    trust_files, monkeypatch: pytest.MonkeyPatch
):
    """fcntl과 msvcrt가 모두 없으면 임계구역에 진입하지 않고 RuntimeError로 fail-closed 합니다."""
    monkeypatch.setattr(orca_trust_worktree, "_LOCK_AVAILABLE", False)

    entered = False
    with (
        pytest.raises(RuntimeError, match="파일 잠금을 지원하는 모듈이 없습니다"),
        orca_trust_worktree._settings_lock(),
    ):
        entered = True

    assert not entered


def test_settings_lock_active_holder_blocks(trust_files, tmp_path, monkeypatch):
    """활성 프로세스/스레드가 락을 잡고 있으면 다른 획득 시도는 차단되고 타임아웃되어야 합니다."""
    monkeypatch.setattr(orca_trust_worktree, "LOCK_TIMEOUT_SECONDS", 0.1)
    with (
        orca_trust_worktree._settings_lock(),
        pytest.raises(RuntimeError, match="신뢰 설정 잠금을 획득하지 못했습니다"),
        orca_trust_worktree._settings_lock(),
    ):
        pass


def test_settings_lock_sequential_reuse(trust_files, tmp_path, monkeypatch):
    """정상 해제 후 다음 컨텍스트가 바로 락을 재사용할 수 있어야 합니다."""
    lock_file = orca_trust_worktree.LOCK_FILE

    with orca_trust_worktree._settings_lock():
        assert lock_file.exists()

    with orca_trust_worktree._settings_lock():
        assert lock_file.exists()


def test_settings_lock_concurrent_acquire_serializes(trust_files, tmp_path, monkeypatch):
    """동시에 여러 스레드가 acquire를 시도해도 직렬화되어 데이터 손실이 없어야 합니다."""
    import threading
    import time

    counter = 0
    iterations = 10
    barrier = threading.Barrier(iterations)
    errors = []

    def worker():
        nonlocal counter
        try:
            barrier.wait(timeout=5.0)
            with orca_trust_worktree._settings_lock():
                current = counter
                time.sleep(0.01)
                counter = current + 1
        except Exception as exc:
            errors.append(exc)

    threads = [threading.Thread(target=worker) for _ in range(iterations)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors, f"Errors occurred during concurrent execution: {errors}"
    assert counter == iterations


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
