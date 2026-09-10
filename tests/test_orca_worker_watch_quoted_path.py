"""git status 의 인용 경로를 감시기가 올바르게 해석하는지 검증합니다."""

from __future__ import annotations

from pathlib import Path

from scripts.orca_worker_watch import find_forbidden_lockfiles


def test_unquoted_ascii_path_is_still_detected(tmp_path: Path) -> None:
    assert find_forbidden_lockfiles(tmp_path, ["?? pnpm-lock.yaml"]) == ["pnpm-lock.yaml"]


def test_quoted_utf8_path_is_decoded_and_detected(tmp_path: Path) -> None:
    # git status --short: ?? "\355\225\234\352\270\200/pnpm-lock.yaml"
    status = r'''?? "\355\225\234\352\270\200/pnpm-lock.yaml"'''
    assert find_forbidden_lockfiles(tmp_path, [status]) == ["한글/pnpm-lock.yaml"]


def test_quoted_path_with_spaces_is_detected(tmp_path: Path) -> None:
    status = '?? "vendor tools/yarn.lock"'
    assert find_forbidden_lockfiles(tmp_path, [status]) == ["vendor tools/yarn.lock"]


def test_node_modules_is_excluded_after_quoted_path_decoding(tmp_path: Path) -> None:
    status = r'''?? "\355\225\234/node_modules/pnpm-lock.yaml"'''
    assert find_forbidden_lockfiles(tmp_path, [status]) == []


def test_undecodable_quoted_path_is_skipped_without_raising(tmp_path: Path) -> None:
    status = r'''?? "bad/\377/pnpm-lock.yaml"'''
    assert find_forbidden_lockfiles(tmp_path, [status]) == []
