"""tests/test_premerge_full_suite_gate.py

scripts/premerge_full_suite_gate.py 단위 테스트.
실제 55초 전량 pytest 실행 없이 모의 러너(mock runner)를 통해
모든 분기(non-main, fail-closed, 커밋 불일치, exit_code, 우회, 증거 생성)를 검증합니다.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts.premerge_full_suite_gate import (
    BYPASS_ENV_VAR,
    is_bypass_active,
    load_evidence,
    main,
    record_evidence,
    verify_premerge_gate,
)


def make_mock_runner(
    branch: str = "main",
    merge_head: str = "abc1234def5678",
    head_sha: str = "abc1234def5678",
    pytest_exit_code: int = 0,
    pytest_stdout: str = "3216 passed, 31 skipped in 55.0s",
):
    """git 및 subprocess 명령에 대한 결정론적 모의 러너를 생성합니다."""

    def mock_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        cmd_list = list(cmd)
        if cmd_list == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{branch}\n", stderr="")

        if cmd_list == ["git", "rev-parse", "--verify", "MERGE_HEAD"]:
            if merge_head is None:
                return subprocess.CompletedProcess(
                    cmd_list, 1, stdout="", stderr="fatal: Needed a single revision"
                )
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{merge_head}\n", stderr="")

        if cmd_list == ["git", "rev-parse", "--verify", "HEAD"]:
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{head_sha}\n", stderr="")

        if len(cmd_list) >= 4 and cmd_list[:3] == ["git", "rev-parse", "--verify"]:
            ref = cmd_list[3].replace("^{commit}", "")
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{ref}\n", stderr="")

        if cmd_list[:3] == ["uv", "run", "pytest"]:
            return subprocess.CompletedProcess(
                cmd_list, pytest_exit_code, stdout=pytest_stdout, stderr=""
            )

        return subprocess.CompletedProcess(cmd_list, 0, stdout="", stderr="")

    return mock_runner


def test_bypass_active(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]):
    """BYPASS_PREMERGE_FULL_SUITE_GATE 환경변수가 설정되면 즉시 통과하고 stderr에 경고를 남깁니다."""
    monkeypatch.setenv(BYPASS_ENV_VAR, "1")
    assert is_bypass_active() is True

    runner = make_mock_runner(branch="main")
    code, msg = verify_premerge_gate(runner=runner)
    assert code == 0
    assert BYPASS_ENV_VAR in msg

    captured = capsys.readouterr()
    assert "[경고]" in captured.err
    assert BYPASS_ENV_VAR in captured.err


def test_non_main_branch_skips_gate():
    """현재 브랜치가 main이 아니면 증거 파일 검사 없이 0을 반환하고 건너뜁니다."""
    runner = make_mock_runner(branch="feature/my-task")
    code, msg = verify_premerge_gate(
        target_branch="main",
        evidence_path=Path("/non/existent/path.json"),
        runner=runner,
    )
    assert code == 0
    assert "건너뜁니다" in msg
    assert "feature/my-task" in msg


def test_main_branch_missing_merge_head():
    """main 브랜치에서 MERGE_HEAD를 확인할 수 없으면 fail-closed로 거부합니다."""
    runner = make_mock_runner(branch="main", merge_head=None)
    code, msg = verify_premerge_gate(
        target_branch="main",
        runner=runner,
    )
    assert code == 1
    assert "MERGE_HEAD" in msg


def test_main_branch_missing_evidence_file(tmp_path: Path):
    """증거 파일이 존재하지 않으면 fail-closed로 거부합니다."""
    evidence_path = tmp_path / "missing_evidence.json"
    runner = make_mock_runner(branch="main", merge_head="c0ffee1234567890")

    code, msg = verify_premerge_gate(
        target_branch="main",
        evidence_path=evidence_path,
        runner=runner,
    )
    assert code == 1
    assert "존재하지 않습니다" in msg


def test_main_branch_corrupted_evidence_file(tmp_path: Path):
    """증거 파일 JSON이 손상되었거나 dict가 아니면 fail-closed로 거부합니다."""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{broken json", encoding="utf-8")

    runner = make_mock_runner(branch="main", merge_head="c0ffee1234567890")
    code, msg = verify_premerge_gate(evidence_path=bad_json, runner=runner)
    assert code == 1
    assert "JSON" in msg

    not_dict_json = tmp_path / "list.json"
    not_dict_json.write_text("[]", encoding="utf-8")
    code2, msg2 = verify_premerge_gate(evidence_path=not_dict_json, runner=runner)
    assert code2 == 1
    assert "객체(dict)" in msg2


def test_main_branch_failed_test_evidence(tmp_path: Path):
    """증거의 exit_code가 0이 아니면 거부합니다."""
    evidence_path = tmp_path / "failed_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "commit": "c0ffee1234567890",
                "exit_code": 1,
                "summary": "1 failed, 3215 passed",
            }
        ),
        encoding="utf-8",
    )

    runner = make_mock_runner(branch="main", merge_head="c0ffee1234567890")
    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "종료 코드가 0이 아닙니다" in msg


def test_main_branch_stale_commit_evidence_rejected(tmp_path: Path):
    """다른 커밋의 증거는 재사용할 수 없으며 커밋 불일치 시 거부합니다."""
    evidence_path = tmp_path / "stale_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "commit": "old_commit_sha_1111",
                "exit_code": 0,
                "summary": "3216 passed, 31 skipped",
            }
        ),
        encoding="utf-8",
    )

    runner = make_mock_runner(branch="main", merge_head="new_commit_sha_2222")
    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "일치하지 않습니다" in msg


def test_main_branch_valid_evidence_passes(tmp_path: Path):
    """증거의 커밋이 MERGE_HEAD와 일치하고 exit_code가 0이면 통과합니다."""
    target_sha = "c0ffee1234567890"
    evidence_path = tmp_path / "valid_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "commit": target_sha,
                "exit_code": 0,
                "summary": "3216 passed, 31 skipped in 55.0s",
            }
        ),
        encoding="utf-8",
    )

    runner = make_mock_runner(branch="main", merge_head=target_sha)
    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 0
    assert "검증 통과" in msg
    assert target_sha[:8] in msg


def test_record_evidence_success(tmp_path: Path):
    """--record 모드에서 테스트가 통과하면 증거 JSON이 올바르게 기록됩니다."""
    evidence_path = tmp_path / ".cache" / "premerge_evidence.json"
    head_sha = "aabbcc1122334455"
    runner = make_mock_runner(
        branch="feature/record-test",
        head_sha=head_sha,
        pytest_exit_code=0,
        pytest_stdout="3216 passed, 31 skipped in 55.0s",
    )

    code, msg = record_evidence(
        evidence_path=evidence_path,
        runner=runner,
    )
    assert code == 0
    assert "증거 기록 완료" in msg
    assert evidence_path.exists()

    data, errs = load_evidence(evidence_path)
    assert not errs
    assert data is not None
    assert data["commit"] == head_sha
    assert data["branch"] == "feature/record-test"
    assert data["exit_code"] == 0
    assert "3216 passed" in data["summary"]


def test_record_evidence_failure(tmp_path: Path):
    """--record 모드에서 테스트가 실패하면 실패 종료 코드와 내용이 기록됩니다."""
    evidence_path = tmp_path / "fail_evidence.json"
    runner = make_mock_runner(
        branch="feature/fail-test",
        head_sha="deadbeef1234",
        pytest_exit_code=1,
        pytest_stdout="1 failed, 3215 passed in 55.0s",
    )

    code, msg = record_evidence(
        evidence_path=evidence_path,
        runner=runner,
    )
    assert code == 1
    assert "실패 상태입니다" in msg
    assert evidence_path.exists()

    data, _ = load_evidence(evidence_path)
    assert data is not None
    assert data["exit_code"] == 1


def test_main_cli_dispatch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """CLI 진입점 main() 함수가 --record 및 기본 검증 모드를 정상 호출합니다."""
    target_sha = "1234567890abcdef"
    evidence_path = tmp_path / "cli_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "commit": target_sha,
                "exit_code": 0,
                "summary": "3216 passed",
            }
        ),
        encoding="utf-8",
    )

    # 1. verify mode with source-commit
    runner = make_mock_runner(branch="main")
    monkeypatch.setattr("scripts.premerge_full_suite_gate.run_process", runner)

    ret = main(
        [
            "--target-branch",
            "main",
            "--evidence-path",
            str(evidence_path),
            "--source-commit",
            target_sha,
        ]
    )
    assert ret == 0
