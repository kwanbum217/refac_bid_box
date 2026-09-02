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
