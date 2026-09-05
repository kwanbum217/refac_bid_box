from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.backup_recovery import run_restore_drill
from src.tasks import scheduled_tasks


def test_retention_dry_run_lists_without_deleting(tmp_path: Path):
    from scripts.backup_recovery import prune_snapshots

    for name in ("snapshot_20260902_010000", "snapshot_20260902_020000"):
        (tmp_path / name).mkdir()
    result = prune_snapshots(tmp_path, retain_count=1)
    assert len(result["stale"]) == 1
    assert result["deleted"] is False
    assert (tmp_path / "snapshot_20260902_010000").exists()


def test_restore_drill_requires_isolated_target(tmp_path: Path):
    with pytest.raises(ValueError):
        run_restore_drill(tmp_path / "missing", Path())
    with pytest.raises(ValueError):
        run_restore_drill(tmp_path / "missing", Path(__file__).resolve().parents[1])


@pytest.mark.asyncio
async def test_backup_task_disabled_by_default():
    with patch.object(scheduled_tasks.settings, "BACKUP_SCHEDULE_ENABLED", False):
        result = await scheduled_tasks.backup_schedule_task({})
    assert result == {"status": "skipped", "reason": "disabled"}


@pytest.mark.asyncio
async def test_backup_task_notifies_failure_without_running_real_dump():
    with (
        patch.object(scheduled_tasks.settings, "BACKUP_SCHEDULE_ENABLED", True),
        patch.object(scheduled_tasks, "execute_backup", side_effect=RuntimeError("fake failure")),
        patch.object(scheduled_tasks, "notify_task_failure", new_callable=AsyncMock) as notify,
    ):
        result = await scheduled_tasks.backup_schedule_task({})
    assert result["status"] == "failed"
    notify.assert_awaited_once()


def test_restore_drill_rejects_empty_manifest_snapshot(tmp_path: Path):
    """빈 매니페스트를 가진 스냅샷은 복원 드릴에서도 snapshot_valid=False 로 처리됩니다."""
    from scripts.backup_recovery_core import MANIFEST_FILENAME

    snap = tmp_path / "snap"
    snap.mkdir()
    (snap / MANIFEST_FILENAME).write_text("{}", encoding="utf-8")
    target = tmp_path.parent / f"{tmp_path.name}_drill_target"
    target.mkdir(parents=True, exist_ok=True)

    try:
        report = run_restore_drill(
            snap,
            target,
            drill_db_config={"name": "test_drill_db", "host": "127.0.0.1", "port": 3307},
            project_root=tmp_path,
        )
        assert report["snapshot_valid"] is False
        assert len(report["errors"]) > 0
    finally:
        import shutil

        if target.exists():
            shutil.rmtree(target)


def test_retention_prune_deletes_excess_snapshots_when_delete_is_true(tmp_path: Path):
    """보존 개수를 초과한 오래된 스냅샷은 delete=True 시 실제로 디렉토리에서 삭제되고 retain_count 개수가 남습니다."""
    from scripts.backup_snapshots import prune_snapshots

    snapshots = [
        "snapshot_20260901_010000",
        "snapshot_20260902_010000",
        "snapshot_20260903_010000",
        "snapshot_20260904_010000",
    ]
    for s in snapshots:
        (tmp_path / s).mkdir()

    # retain_count=2, delete=True -> 오래된 2개(0901, 0902) 삭제, 최신 2개(0903, 0904) 보존
    result = prune_snapshots(tmp_path, retain_count=2, delete=True)
    assert result["deleted"] is True
    assert result["deleted_count"] == 2
    assert len(result["stale"]) == 2
    assert not (tmp_path / "snapshot_20260901_010000").exists()
    assert not (tmp_path / "snapshot_20260902_010000").exists()
    assert (tmp_path / "snapshot_20260903_010000").exists()
    assert (tmp_path / "snapshot_20260904_010000").exists()


def test_retention_fail_closed_on_corrupt_manifest(tmp_path: Path):
    """보존 대상 스냅샷의 매니페스트가 손상된 경우 판정 실패로 처리되어 아무것도 삭제하지 않습니다 (fail-closed)."""
    from scripts.backup_recovery_core import MANIFEST_FILENAME
    from scripts.backup_snapshots import prune_snapshots

    # 최신 스냅샷(보존 대상)에 손상된 매니페스트 배치
    corrupt_snap = tmp_path / "snapshot_20260902_010000"
    corrupt_snap.mkdir()
    (corrupt_snap / MANIFEST_FILENAME).write_text("{broken json", encoding="utf-8")

    # 오래된 스냅샷(삭제 후보)
    old_snap = tmp_path / "snapshot_20260901_010000"
    old_snap.mkdir()

    result = prune_snapshots(tmp_path, retain_count=1, delete=True)
    assert result["deleted"] is False
    assert result["deleted_count"] == 0
    assert len(result["errors"]) > 0
    # 손상된 스냅샷과 오래된 스냅샷 모두 그대로 보존되어야 함
    assert corrupt_snap.exists()
    assert old_snap.exists()


def test_retention_never_leaves_less_than_retain_count(tmp_path: Path):
    """후보 개수가 retain_count 이하이면 삭제 대상이 0개이며 아무것도 삭제되지 않습니다."""
    from scripts.backup_snapshots import prune_snapshots

    for name in ("snapshot_20260901_010000", "snapshot_20260902_010000"):
        (tmp_path / name).mkdir()

    result = prune_snapshots(tmp_path, retain_count=5, delete=True)
    assert result["deleted"] is False
    assert result["deleted_count"] == 0
    assert len(result["stale"]) == 0
    assert (tmp_path / "snapshot_20260901_010000").exists()
    assert (tmp_path / "snapshot_20260902_010000").exists()


@pytest.mark.asyncio
async def test_backup_task_executes_retention_deletion(tmp_path: Path):
    """정기 백업 태스크 실행 시 보존 정책에 따라 오래된 스냅샷이 실제로 삭제됩니다."""
    snap1 = tmp_path / "snapshot_20260901_010000"
    snap2 = tmp_path / "snapshot_20260902_010000"
    snap3 = tmp_path / "snapshot_20260903_010000"
    for s in (snap1, snap2, snap3):
        s.mkdir()

    with (
        patch.object(scheduled_tasks.settings, "BACKUP_SCHEDULE_ENABLED", True),
        patch.object(scheduled_tasks.settings, "BACKUP_RETENTION_COUNT", 2),
        patch.object(scheduled_tasks, "DEFAULT_SNAPSHOTS_DIR", tmp_path),
        patch.object(
            scheduled_tasks, "execute_backup", return_value={"schema": "BACKUP_MANIFEST_V1"}
        ),
        patch.object(scheduled_tasks, "check_backup_disk_space", return_value=(50.0, False)),
    ):
        result = await scheduled_tasks.backup_schedule_task({})

    assert result["status"] == "success"
    assert result["retention"]["deleted"] is True
    assert result["retention"]["deleted_count"] == 1
    # 가장 오래된 snap1만 삭제되고 snap2, snap3은 유지
    assert not snap1.exists()
    assert snap2.exists()
    assert snap3.exists()


@pytest.mark.asyncio
async def test_backup_task_notifies_low_disk_space(tmp_path: Path):
    """백업 스토리지 여유 공간이 설정 임계값 미만이면 기존 notifier로 경보가 발송됩니다."""
    with (
        patch.object(scheduled_tasks.settings, "BACKUP_SCHEDULE_ENABLED", True),
        patch.object(scheduled_tasks.settings, "BACKUP_DISK_MIN_FREE_GB", 10.0),
        patch.object(scheduled_tasks, "DEFAULT_SNAPSHOTS_DIR", tmp_path),
        patch.object(scheduled_tasks, "check_backup_disk_space", return_value=(2.5, True)),
        patch.object(
            scheduled_tasks, "execute_backup", return_value={"schema": "BACKUP_MANIFEST_V1"}
        ),
        patch.object(scheduled_tasks, "notify", new_callable=AsyncMock) as mock_notify,
    ):
        result = await scheduled_tasks.backup_schedule_task({})

    assert result["status"] == "success"
    mock_notify.assert_awaited_once()
    args, kwargs = mock_notify.await_args
    assert "디스크 여유 공간 부족" in args[0]
    assert kwargs.get("level") == "warning"
