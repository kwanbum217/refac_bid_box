"""OS 간 경로 구분자(Windows 백슬래시 vs POSIX 슬래시) 차이로 인한 CI 회귀 방지 테스트."""

from __future__ import annotations

from pathlib import Path, PureWindowsPath

from scripts.orca_level1_gate import (
    find_forbidden_lockfiles,
    run_gate9_forbidden_lockfiles,
)
from scripts.orca_taskctl import (
    record_dispatch_capability as taskctl_record_capability,
)
from scripts.orca_worker_done_guard import dispatch_capability_file


def test_gate9_reports_posix_paths_on_all_platforms(tmp_path: Path) -> None:
    """중첩 경로에 존재하는 금지된 산출물 검출 시 항상 POSIX 슬래시 경로로 보고되는지 검증합니다."""
    nested_dir = tmp_path / "deeply" / "nested" / "subproject"
    nested_dir.mkdir(parents=True)
    pnpm_file = nested_dir / "pnpm-lock.yaml"
    pnpm_file.write_text("lockfile\n", encoding="utf-8")

    yarn_file = tmp_path / "tooling" / "yarn.lock"
    yarn_file.parent.mkdir(parents=True)
    yarn_file.write_text("lockfile\n", encoding="utf-8")

    forbidden_list = find_forbidden_lockfiles(tmp_path)
    assert len(forbidden_list) == 2

    for rel_path in forbidden_list:
        assert "\\" not in rel_path
        assert "/" in rel_path

    assert forbidden_list == [
        "deeply/nested/subproject/pnpm-lock.yaml",
        "tooling/yarn.lock",
    ]

    result = run_gate9_forbidden_lockfiles(tmp_path)
    assert result.status == "fail"
    for forbidden in result.raw_data["forbidden_files"]:
        assert "\\" not in forbidden
        assert "/" in forbidden

    detail_line = result.details[0]
    assert "\\" not in detail_line
    assert "deeply/nested/subproject/pnpm-lock.yaml" in detail_line
    assert "tooling/yarn.lock" in detail_line


def test_windows_path_simulation_requires_as_posix_for_gate_match() -> None:
    """Windows 환경의 백슬래시 경로 객체를 다룰 때 as_posix()가 아니면 불일치가 발생하고 as_posix()로 해결됨을 검증합니다."""
    win_root = PureWindowsPath("C:\\repo\\worktree")
    win_target = win_root / "nested" / "pnpm-lock.yaml"

    rel = win_target.relative_to(win_root)

    assert str(rel) == "nested\\pnpm-lock.yaml"
    assert str(rel) != "nested/pnpm-lock.yaml"

    assert rel.as_posix() == "nested/pnpm-lock.yaml"


def test_dispatch_capability_relative_path_posix_normalization(tmp_path: Path) -> None:
    """taskctl capability 기록 파일 경로가 as_posix() 변환 시 항상 .orca/ 접두사로 시작함을 검증합니다."""
    worktree = tmp_path / "worktree_dir"
    worktree.mkdir()

    cap_file = taskctl_record_capability(
        worktree, "task_ci_test", "지시문 토큰 dcap_test_token_123 포함", None
    )
    assert cap_file is not None
    assert cap_file.exists()

    rel_posix = cap_file.relative_to(worktree).as_posix()
    assert rel_posix.startswith(".orca/")
    assert "\\" not in rel_posix

    win_worktree = PureWindowsPath("D:\\workspace\\repo")
    win_cap_file = win_worktree / ".orca" / "dispatch_capabilities" / "task_sample.capability"
    win_rel = win_cap_file.relative_to(win_worktree)

    assert str(win_rel) == ".orca\\dispatch_capabilities\\task_sample.capability"
    assert not str(win_rel).startswith(".orca/")
    assert win_rel.as_posix().startswith(".orca/")
    assert "\\" not in win_rel.as_posix()


def test_dispatch_capability_file_path_resolution(tmp_path: Path) -> None:
    """dispatch_capability_file 헬퍼가 .orca 디렉터리 하위 경로를 반환하며 POSIX 정규화가 보장되는지 검증합니다."""
    resolved = dispatch_capability_file(tmp_path, "task_123")
    rel_posix = resolved.relative_to(tmp_path).as_posix()

    assert rel_posix == ".orca/dispatch_capabilities/task_123.capability"
    assert "\\" not in rel_posix
