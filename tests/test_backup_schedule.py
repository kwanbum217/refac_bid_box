from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from scripts.backup_recovery import run_restore_drill
from scripts.backup_recovery_core import MANIFEST_FILENAME, sha256_file
from src.tasks import scheduled_tasks


def _write_valid_snapshot_manifest(snap: Path) -> None:
    """prune 보존 검증을 통과하는 정상 매니페스트를 작성합니다."""
    components = {}
    for name, filename, content in (
        ("database", "db_dump.sql.gz", b"valid_db_data"),
        ("chroma_db", "chroma_db.tar.gz", b"valid_chroma_data"),
        ("models", "models.tar.gz", b"valid_model_data"),
    ):
        file_path = snap / filename
        file_path.write_bytes(content)
        components[name] = {
            "path": filename,
            "size_bytes": len(content),
            "sha256": sha256_file(file_path),
        }
    manifest_data = {
        "schema": "BACKUP_MANIFEST_V1",
        "created_at": "2026-09-05T12:00:00Z",
        "head_commit": "valid_head",
        "components": components,
    }
    (snap / MANIFEST_FILENAME).write_text(json.dumps(manifest_data), encoding="utf-8")


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
    # 새 계약: 보존 대상(최신 2개)에 유효한 매니페스트를 갖춰 fail-closed 를 통과한다.
    _write_valid_snapshot_manifest(tmp_path / "snapshot_20260903_010000")
    _write_valid_snapshot_manifest(tmp_path / "snapshot_20260904_010000")

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


def test_retention_manifestless_retained_fails_closed(tmp_path: Path):
    """보존 대상에 매니페스트가 없으면 prune 이 fail-closed 로 아무것도 삭제하지 않습니다."""
    from scripts.backup_snapshots import prune_snapshots

    keep_snap = tmp_path / "snapshot_20260902_010000"
    keep_snap.mkdir()
    stale_snap = tmp_path / "snapshot_20260901_010000"
    stale_snap.mkdir()

    result = prune_snapshots(tmp_path, retain_count=1, delete=True)
    assert result["deleted"] is False
    assert result["deleted_count"] == 0
    assert any("매니페스트 파일 없음" in err for err in result["errors"])
    assert keep_snap.exists()
    assert stale_snap.exists()


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
    # 새 계약: 보존 대상(snap2, snap3)에 유효한 매니페스트를 갖춰 fail-closed 를 통과한다.
    _write_valid_snapshot_manifest(snap2)
    _write_valid_snapshot_manifest(snap3)

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


def _mock_disk_usage(free_gb: float):
    from types import SimpleNamespace

    free_bytes = int(free_gb * (1024**3))
    return SimpleNamespace(total=free_bytes * 2, used=free_bytes, free=free_bytes)


def test_check_backup_disk_space_threshold_above(tmp_path: Path):
    with (
        patch.object(scheduled_tasks.settings, "BACKUP_DISK_MIN_FREE_GB", 10.0),
        patch.object(scheduled_tasks.shutil, "disk_usage", return_value=_mock_disk_usage(10.5)),
    ):
        free_gb, is_low = scheduled_tasks.check_backup_disk_space(tmp_path)
    assert free_gb == pytest.approx(10.5, abs=0.01)
    assert is_low is False


def test_check_backup_disk_space_threshold_equal(tmp_path: Path):
    with (
        patch.object(scheduled_tasks.settings, "BACKUP_DISK_MIN_FREE_GB", 10.0),
        patch.object(scheduled_tasks.shutil, "disk_usage", return_value=_mock_disk_usage(10.0)),
    ):
        free_gb, is_low = scheduled_tasks.check_backup_disk_space(tmp_path)
    assert free_gb == pytest.approx(10.0, abs=0.01)
    assert is_low is False


def test_check_backup_disk_space_threshold_below(tmp_path: Path):
    with (
        patch.object(scheduled_tasks.settings, "BACKUP_DISK_MIN_FREE_GB", 10.0),
        patch.object(scheduled_tasks.shutil, "disk_usage", return_value=_mock_disk_usage(9.5)),
    ):
        free_gb, is_low = scheduled_tasks.check_backup_disk_space(tmp_path)
    assert free_gb == pytest.approx(9.5, abs=0.01)
    assert is_low is True


def test_check_backup_disk_space_measurement_failure(tmp_path: Path):
    with patch.object(scheduled_tasks.shutil, "disk_usage", side_effect=OSError("disk fail")):
        free_gb, is_low = scheduled_tasks.check_backup_disk_space(tmp_path)
    assert free_gb == 0.0
    assert is_low is True


def test_retention_symlink_stale_aborts_without_deleting(tmp_path: Path):
    """stale 항목이 심볼릭 링크면 errors에 담고 아무것도 삭제하지 않습니다."""
    from scripts.backup_snapshots import prune_snapshots

    keep_snap = tmp_path / "snapshot_20260902_010000"
    keep_snap.mkdir()
    _write_valid_snapshot_manifest(keep_snap)

    real_stale = tmp_path / "real_stale_target"
    real_stale.mkdir()
    (real_stale / "data.txt").write_text("stale", encoding="utf-8")
    stale_link = tmp_path / "snapshot_20260901_010000"
    stale_link.symlink_to(real_stale, target_is_directory=True)

    result = prune_snapshots(tmp_path, retain_count=1, delete=True)
    assert result["deleted"] is False
    assert result["deleted_count"] == 0
    assert any("심볼릭 링크" in err for err in result["errors"])
    assert keep_snap.exists()
    assert stale_link.is_symlink()
    assert real_stale.exists()


@pytest.mark.asyncio
async def test_backup_task_no_notify_when_prune_recovers_space(tmp_path: Path):
    """정리 전 임계값 미만이라도 정리 후 회복되면 경보가 나가지 않습니다."""
    with (
        patch.object(scheduled_tasks.settings, "BACKUP_SCHEDULE_ENABLED", True),
        patch.object(scheduled_tasks.settings, "BACKUP_DISK_MIN_FREE_GB", 10.0),
        patch.object(scheduled_tasks, "DEFAULT_SNAPSHOTS_DIR", tmp_path),
        patch.object(
            scheduled_tasks,
            "check_backup_disk_space",
            side_effect=[(2.5, True), (50.0, False)],
        ),
        patch.object(
            scheduled_tasks, "execute_backup", return_value={"schema": "BACKUP_MANIFEST_V1"}
        ),
        patch.object(scheduled_tasks, "prune_snapshots", return_value={"errors": []}),
        patch.object(scheduled_tasks, "notify", new_callable=AsyncMock) as mock_notify,
    ):
        result = await scheduled_tasks.backup_schedule_task({})

    assert result["status"] == "success"
    mock_notify.assert_not_awaited()
    assert result["disk_free_gb"] == pytest.approx(50.0)
    assert result["disk_free_gb_before_prune"] == pytest.approx(2.5)


@pytest.mark.asyncio
async def test_backup_task_notifies_when_post_prune_still_low(tmp_path: Path):
    """정리 후에도 임계값 미만이면 경보가 나갑니다."""
    with (
        patch.object(scheduled_tasks.settings, "BACKUP_SCHEDULE_ENABLED", True),
        patch.object(scheduled_tasks.settings, "BACKUP_DISK_MIN_FREE_GB", 10.0),
        patch.object(scheduled_tasks, "DEFAULT_SNAPSHOTS_DIR", tmp_path),
        patch.object(
            scheduled_tasks,
            "check_backup_disk_space",
            side_effect=[(2.5, True), (3.0, True)],
        ),
        patch.object(
            scheduled_tasks, "execute_backup", return_value={"schema": "BACKUP_MANIFEST_V1"}
        ),
        patch.object(scheduled_tasks, "prune_snapshots", return_value={"errors": []}),
        patch.object(scheduled_tasks, "notify", new_callable=AsyncMock) as mock_notify,
    ):
        result = await scheduled_tasks.backup_schedule_task({})

    assert result["status"] == "success"
    mock_notify.assert_awaited_once()
    assert result["disk_free_gb"] == pytest.approx(3.0)
    assert result["disk_free_gb_before_prune"] == pytest.approx(2.5)
