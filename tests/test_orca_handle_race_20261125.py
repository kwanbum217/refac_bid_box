"""2026-11-25 .handle 고아 정리 나이 조건 회귀 시험.

taskctl 은 .handle 을 preamble 보다 먼저 씁니다. 그 사이에 codex 런처의 고아
정리가 돌면 방금 쓴 .handle 이 짝 preamble 없이 보여 지워질 수 있습니다. 여기서는
새 핸들은 진행 중 Dispatch 로 보고 남기며, 충분히 오래된 핸들만 지우는지
확인합니다. 시각은 now 인자로 고정합니다.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

HANDLE = "term_race_20261125_worker"
FIXED_NOW = 1_800_000_000.0
FRESH_AGE_SECONDS = 0.0
STALE_AGE_SECONDS = 301.0


def _orca_dir(tmp_path: Path) -> Path:
    orca = tmp_path / ".orca"
    orca.mkdir()
    return orca


def _handle(orca: Path, name: str, *, age_seconds: float, now: float) -> Path:
    handle = orca / f"{name}.handle"
    handle.write_text(HANDLE + "\n", encoding="utf-8")
    stamp = now - age_seconds
    os.utime(handle, (stamp, stamp))
    return handle


def test_fresh_orphan_handle_survives_dispatch_window(tmp_path: Path) -> None:
    """(a) 짝 preamble 이 없어도 방금 쓴 .handle 은 진행 중일 수 있어 남깁니다."""
    from scripts.orca_worker_launch_common import remove_orphan_worker_handles

    orca = _orca_dir(tmp_path)
    handle = _handle(
        orca, "preamble_task_fresh_dispatch", age_seconds=FRESH_AGE_SECONDS, now=time.time()
    )

    removed = remove_orphan_worker_handles(orca)

    assert removed == []
    assert handle.exists(), "진행 중 Dispatch 의 .handle 이 고아로 지워졌습니다"


def test_old_orphan_handle_is_removed(tmp_path: Path) -> None:
    """(b) 짝 preamble 이 없고 나이가 기준 이상인 .handle 은 지웁니다."""
    from scripts.orca_worker_launch_common import remove_orphan_worker_handles

    orca = _orca_dir(tmp_path)
    handle = _handle(orca, "preamble_task_stale_run", age_seconds=STALE_AGE_SECONDS, now=FIXED_NOW)

    removed = remove_orphan_worker_handles(orca, now=FIXED_NOW)

    assert [path.name for path in removed] == [handle.name]
    assert not handle.exists()


def test_paired_handle_survives_regardless_of_age(tmp_path: Path) -> None:
    """(c) 짝 preamble 이 있는 .handle 은 나이와 무관하게 남깁니다."""
    from scripts.orca_worker_launch_common import remove_orphan_worker_handles

    orca = _orca_dir(tmp_path)
    handle = _handle(
        orca, "preamble_task_live_run", age_seconds=STALE_AGE_SECONDS * 12, now=FIXED_NOW
    )
    (orca / "preamble_task_live_run.txt").write_text("지시문", encoding="utf-8")

    removed = remove_orphan_worker_handles(orca, now=FIXED_NOW)

    assert removed == []
    assert handle.exists()


def test_codex_launcher_keeps_fresh_orphan_handle(tmp_path: Path) -> None:
    """codex 런처의 고아 정리도 방금 쓴 .handle 은 남깁니다."""
    from scripts import orca_codex_launch

    orca = _orca_dir(tmp_path)
    handle = _handle(
        orca, "preamble_task_fresh_dispatch", age_seconds=FRESH_AGE_SECONDS, now=time.time()
    )

    removed = orca_codex_launch.cleanup_orphan_handles(tmp_path)

    assert removed == []
    assert handle.exists()


def test_codex_launcher_removes_old_orphan_handle(tmp_path: Path) -> None:
    """codex 런처의 고아 정리는 오래된 .handle 을 지웁니다."""
    from scripts import orca_codex_launch

    orca = _orca_dir(tmp_path)
    handle = _handle(
        orca, "preamble_task_stale_run", age_seconds=STALE_AGE_SECONDS * 12, now=time.time()
    )

    removed = orca_codex_launch.cleanup_orphan_handles(tmp_path)

    assert [Path(item).name for item in removed] == [handle.name]
    assert not handle.exists()
