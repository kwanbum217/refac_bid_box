"""tests/test_premerge_full_suite_gate.py

scripts/premerge_full_suite_gate.py 단위 테스트.
실제 55초 전량 pytest 실행 없이 모의 러너(mock runner)를 통해
모든 분기(non-main, fail-closed, 커밋 불일치, exit_code, 우회, 증거 생성,
부분/파일 단위 실행 기각, git-path 기반 MERGE_HEAD 조회,
git-common-dir 기반 공통 증거 경로 해소, 훅 설치)를 검증합니다.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts.premerge_full_suite_gate import (
    BYPASS_ENV_VAR,
    CANONICAL_FULL_SUITE_CMD,
    MAX_FAILED_TESTS_RECORDED,
    extract_failed_nodeids,
    get_merge_head_sha,
    install_git_hooks,
    is_bypass_active,
    is_full_suite_command,
    load_evidence,
    main,
    parse_pytest_counts,
    record_evidence,
    resolve_evidence_path,
    verify_premerge_gate,
)


def make_mock_runner(
    branch: str = "main",
    merge_head: str | None = "abc1234def5678",
    head_sha: str = "abc1234def5678",
    pytest_exit_code: int = 0,
    pytest_stdout: str = "3216 passed, 31 skipped in 55.0s",
    git_path_merge_head: str | None = None,
    git_common_dir: str = ".git",
    git_dir: str = ".git",
):
    """git 및 subprocess 명령에 대한 결정론적 모의 러너를 생성합니다."""

    def mock_runner(cmd: Sequence[str]) -> subprocess.CompletedProcess[str]:
        cmd_list = list(cmd)
        if cmd_list == ["git", "branch", "--show-current"]:
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{branch}\n", stderr="")

        if cmd_list == ["git", "rev-parse", "--git-path", "MERGE_HEAD"]:
            if git_path_merge_head is not None:
                return subprocess.CompletedProcess(
                    cmd_list, 0, stdout=f"{git_path_merge_head}\n", stderr=""
                )
            return subprocess.CompletedProcess(
                cmd_list, 1, stdout="", stderr="fatal: not a git path"
            )

        if cmd_list == ["git", "rev-parse", "--git-common-dir"]:
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{git_common_dir}\n", stderr="")

        if cmd_list == ["git", "rev-parse", "--git-dir"]:
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{git_dir}\n", stderr="")

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

        if cmd_list[:4] == ["uv", "run", "pre-commit", "install"]:
            return subprocess.CompletedProcess(
                cmd_list, 0, stdout="pre-commit installed\n", stderr=""
            )

        return subprocess.CompletedProcess(cmd_list, 0, stdout="", stderr="")

    return mock_runner


def test_bypass_active(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    """BYPASS_PREMERGE_FULL_SUITE_GATE 환경변수가 설정되면 즉시 통과하고 stderr에 경고를 남깁니다."""
    monkeypatch.setenv(BYPASS_ENV_VAR, "1")
    assert is_bypass_active() is True

    runner = make_mock_runner(branch="main")
    code, msg = verify_premerge_gate(evidence_path=tmp_path / "dummy.json", runner=runner)
    assert code == 0
    assert BYPASS_ENV_VAR in msg

    captured = capsys.readouterr()
    assert "[경고]" in captured.err
    assert BYPASS_ENV_VAR in captured.err


def test_non_main_branch_skips_gate(tmp_path: Path):
    """현재 브랜치가 main이 아니면 증거 파일 검사 없이 0을 반환하고 건너뜁니다."""
    runner = make_mock_runner(branch="feature/my-task")
    code, msg = verify_premerge_gate(
        target_branch="main",
        evidence_path=tmp_path / "non_existent.json",
        runner=runner,
    )
    assert code == 0
    assert "건너뜁니다" in msg
    assert "feature/my-task" in msg


def test_main_branch_missing_merge_head(tmp_path: Path):
    """main 브랜치에서 MERGE_HEAD를 확인할 수 없으면 fail-closed로 거부합니다."""
    runner = make_mock_runner(branch="main", merge_head=None)
    code, msg = verify_premerge_gate(
        target_branch="main",
        evidence_path=tmp_path / "dummy.json",
        runner=runner,
    )
    assert code == 1
    assert "MERGE_HEAD" in msg


def test_get_merge_head_sha_from_git_path_file(tmp_path: Path):
    """git rev-parse --git-path MERGE_HEAD 파일에서 직접 SHA를 읽어옵니다."""
    merge_head_file = tmp_path / "MERGE_HEAD"
    expected_sha = "11223344556677889900aabbccddeeff11223344"
    merge_head_file.write_text(f"{expected_sha}\n", encoding="utf-8")

    runner = make_mock_runner(
        git_path_merge_head=str(merge_head_file),
        merge_head=None,  # --verify 는 실패하도록 설정
    )

    sha, err = get_merge_head_sha(runner=runner)
    assert err == ""
    assert sha == expected_sha


def test_get_merge_head_sha_fallback_to_verify():
    """git-path 파일이 없을 때 git rev-parse --verify MERGE_HEAD로 폴백합니다."""
    expected_sha = "aabbccddeeff11223344556677889900aabbccdd"
    runner = make_mock_runner(
        git_path_merge_head=None,
        merge_head=expected_sha,
    )

    sha, err = get_merge_head_sha(runner=runner)
    assert err == ""
    assert sha == expected_sha


def test_resolve_evidence_path_worktree(tmp_path: Path):
    """워크트리 환경에서 git-common-dir 를 기반으로 주 저장소 .cache 공통 경로를 해소합니다."""
    common_git_dir = tmp_path / "main_repo" / ".git"
    common_git_dir.mkdir(parents=True, exist_ok=True)

    runner = make_mock_runner(git_common_dir=str(common_git_dir))
    resolved = resolve_evidence_path(evidence_path=None, runner=runner)

    expected = tmp_path / "main_repo" / ".cache" / "premerge_full_suite_evidence.json"
    assert resolved == expected


def test_resolve_evidence_path_explicit_override(tmp_path: Path):
    """명시적으로 지정된 커스텀 증거 경로는 git-common-dir 해석 없이 그대로 사용합니다."""
    custom_path = tmp_path / "custom_dir" / "my_evidence.json"
    runner = make_mock_runner()
    resolved = resolve_evidence_path(evidence_path=custom_path, runner=runner)
    assert resolved == custom_path


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
                "suite": "full",
                "target": "tests/",
                "command": " ".join(CANONICAL_FULL_SUITE_CMD),
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


def test_main_branch_partial_test_evidence_rejected(tmp_path: Path):
    """특정 파일이나 하위 집합만 실행한 증거는 전량 증거로 인정하지 않고 거부합니다."""
    # 1. 특정 파일 실행 증거
    evidence_path = tmp_path / "partial_file_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "suite": "full",
                "target": "tests/",
                "command": "uv run pytest tests/test_chatbot_api_split.py -q",
                "commit": "c0ffee1234567890",
                "exit_code": 0,
                "summary": "5 passed in 0.1s",
            }
        ),
        encoding="utf-8",
    )

    runner = make_mock_runner(branch="main", merge_head="c0ffee1234567890")
    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "전량 테스트 증거가 아닙니다" in msg
    assert "특정 파일/테스트 대상" in msg

    # 2. suite / target 속성 불일치 증거
    bad_suite_path = tmp_path / "bad_suite_evidence.json"
    bad_suite_path.write_text(
        json.dumps(
            {
                "suite": "partial",
                "target": "tests/test_api_v1.py",
                "command": "uv run pytest tests/ -q",
                "commit": "c0ffee1234567890",
                "exit_code": 0,
                "summary": "3216 passed",
            }
        ),
        encoding="utf-8",
    )
    code2, msg2 = verify_premerge_gate(evidence_path=bad_suite_path, runner=runner)
    assert code2 == 1
    assert "suite 속성" in msg2


def test_is_full_suite_command():
    """is_full_suite_command 가 전량 실행과 파일별 부분 실행을 정확히 구분합니다."""
    # 전량 테스트 인정
    assert is_full_suite_command("uv run pytest tests/ -q -m 'not data_assets'")[0] is True
    assert is_full_suite_command("pytest tests/ -q")[0] is True
    assert is_full_suite_command("uv run pytest tests")[0] is True

    # 부분 테스트 기각
    assert is_full_suite_command("uv run pytest tests/test_chatbot.py")[0] is False
    assert (
        is_full_suite_command("uv run pytest tests/test_chatbot.py::test_chatbot_line_counts")[0]
        is False
    )
    assert is_full_suite_command("uv run pytest src/")[0] is False
    assert is_full_suite_command("")[0] is False


def test_parse_pytest_counts():
    """parse_pytest_counts 가 passed, failed, skipped 숫자를 올바르게 추출합니다."""
    counts = parse_pytest_counts("3209 passed, 35 skipped, 3 deselected, 311 warnings in 85.28s")
    assert counts["passed"] == 3209
    assert counts["skipped"] == 35
    assert counts["failed"] == 0

    counts_fail = parse_pytest_counts("1 failed, 3208 passed in 50s")
    assert counts_fail["passed"] == 3208
    assert counts_fail["failed"] == 1


def test_main_branch_stale_commit_evidence_rejected(tmp_path: Path):
    """다른 커밋의 증거는 재사용할 수 없으며 커밋 불일치 시 거부합니다."""
    evidence_path = tmp_path / "stale_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "suite": "full",
                "target": "tests/",
                "command": " ".join(CANONICAL_FULL_SUITE_CMD),
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
    """증거의 커밋이 MERGE_HEAD와 일치하고 전량 테스트 exit_code가 0이면 통과합니다."""
    target_sha = "c0ffee1234567890"
    evidence_path = tmp_path / "valid_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "suite": "full",
                "target": "tests/",
                "command": " ".join(CANONICAL_FULL_SUITE_CMD),
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
    assert data["suite"] == "full"
    assert data["target"] == "tests/"
    assert data["commit"] == head_sha
    assert data["branch"] == "feature/record-test"
    assert data["exit_code"] == 0
    assert data["passed"] == 3216
    assert data["skipped"] == 31
    assert data["failed"] == 0


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
    assert data["failed"] == 1


def test_commit_source_non_merge_bypasses_gate(tmp_path: Path):
    """prepare-commit-msg 단계에서 merge가 아닌 커밋 소스(message, template, commit, squash, none)는 즉시 통과합니다."""
    runner = make_mock_runner(branch="main")
    for src in ["message", "template", "commit", "squash", "none"]:
        code, msg = verify_premerge_gate(
            target_branch="main",
            commit_source=src,
            evidence_path=tmp_path / "dummy.json",
            runner=runner,
        )
        assert code == 0
        assert "건너뜁니다" in msg


def test_commit_source_merge_executes_gate(tmp_path: Path):
    """commit_source가 'merge'이면 main 브랜치에서 게이트를 엄격히 실행합니다."""
    runner = make_mock_runner(branch="main", merge_head="c0ffee1234567890")
    code, msg = verify_premerge_gate(
        target_branch="main",
        commit_source="merge",
        evidence_path=tmp_path / "missing.json",
        runner=runner,
    )
    assert code == 1
    assert "존재하지 않습니다" in msg


def test_install_git_hooks():
    """install_git_hooks 가 pre-commit 및 prepare-commit-msg 를 모두 설치합니다."""
    runner = make_mock_runner()
    code, msg = install_git_hooks(runner=runner)
    assert code == 0
    assert "정상 설치되었습니다" in msg


def test_install_git_hooks_worktree_warning():
    """install_git_hooks 가 워크트리 환경에서 실행될 때 주의 경고 문구를 포함합니다."""
    runner = make_mock_runner(
        git_dir="/path/to/worktree/.git",
        git_common_dir="/path/to/main_repo/.git",
    )
    code, msg = install_git_hooks(runner=runner)
    assert code == 0
    assert "정상 설치되었습니다" in msg
    assert "[주의] 워크트리 환경에서 hook을 설치하면" in msg


def test_main_cli_dispatch(tmp_path: Path):
    """CLI 진입점 main() 함수가 --record 및 기본 검증 모드를 정상 호출합니다."""
    target_sha = "1234567890abcdef"
    evidence_path = tmp_path / "cli_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "suite": "full",
                "target": "tests/",
                "command": " ".join(CANONICAL_FULL_SUITE_CMD),
                "commit": target_sha,
                "exit_code": 0,
                "summary": "3216 passed",
            }
        ),
        encoding="utf-8",
    )

    # 1. verify mode with source-commit on main
    runner = make_mock_runner(branch="main", head_sha=target_sha)
    ret = main(
        [
            "--target-branch",
            "main",
            "--evidence-path",
            str(evidence_path),
            "--source-commit",
            target_sha,
        ],
        runner=runner,
    )
    assert ret == 0

    # 2. --record mode
    record_evidence_path = tmp_path / "cli_record.json"
    ret_record = main(
        [
            "--record",
            "--evidence-path",
            str(record_evidence_path),
        ],
        runner=runner,
    )
    assert ret_record == 0

    # 3. --install-hooks mode
    ret_hooks = main(["--install-hooks"], runner=runner)
    assert ret_hooks == 0


def test_main_cli_prepare_commit_msg_positional_args(tmp_path: Path):
    """pre-commit prepare-commit-msg 훅의 위치 인자($1 msg_file, $2 source)를 올바르게 처리합니다."""
    target_sha = "1234567890abcdef"
    evidence_path = tmp_path / "cli_evidence2.json"
    evidence_path.write_text(
        json.dumps(
            {
                "suite": "full",
                "target": "tests/",
                "command": " ".join(CANONICAL_FULL_SUITE_CMD),
                "commit": target_sha,
                "exit_code": 0,
                "summary": "3216 passed",
            }
        ),
        encoding="utf-8",
    )

    runner = make_mock_runner(branch="main", merge_head=target_sha)

    # 1. merge 소스 -> 게이트 실행 및 통과 (main 브랜치에서도 격리된 러너로 검증)
    ret_merge = main(
        [
            ".git/MERGE_MSG",
            "merge",
            "--target-branch",
            "main",
            "--evidence-path",
            str(evidence_path),
        ],
        runner=runner,
    )
    assert ret_merge == 0

    # 2. message 소스 (일반 커밋) -> main 브랜치여도 증거 없이 즉시 통과
    ret_msg = main([".git/COMMIT_EDITMSG", "message"], runner=runner)
    assert ret_msg == 0

    # 3. 소스 생략된 일반 커밋 -> main 브랜치여도 증거 없이 즉시 통과
    ret_none = main([".git/COMMIT_EDITMSG"], runner=runner)
    assert ret_none == 0


def test_extract_failed_nodeids_empty_on_pass():
    """통과 출력에는 실패 nodeid 가 없어 빈 목록을 반환합니다."""
    output = "3216 passed, 31 skipped in 55.0s\n"
    assert extract_failed_nodeids(output) == []


def test_extract_failed_nodeids_mixed_failed_and_error():
    """FAILED 와 ERROR 를 함께 추출하고 메시지를 버리며 중복을 제거하고 순서를 유지합니다."""
    output = (
        "FAILED tests/test_a.py::test_one - AssertionError: boom\n"
        "ERROR tests/test_b.py::test_two - RuntimeError: setup failed\n"
        "FAILED tests/test_a.py::test_one - AssertionError: boom\n"
        "some log line that mentions FAILED in the middle\n"
        "FAILEDtests/test_ignored.py::test_x - no separator\n"
        "FAILED tests/test_c.py::test_three\n"
    )
    assert extract_failed_nodeids(output) == [
        "tests/test_a.py::test_one",
        "tests/test_b.py::test_two",
        "tests/test_c.py::test_three",
    ]


def test_extract_failed_nodeids_from_stderr_only():
    """stdout 과 stderr 를 합친 출력에서 FAILED/ERROR 줄을 추출합니다."""
    output = "\n".join(["1 failed, 3215 passed", "FAILED tests/test_err.py::test_e - ValueError"])
    assert extract_failed_nodeids(output) == ["tests/test_err.py::test_e"]


def test_record_evidence_success_records_empty_failed_tests(tmp_path: Path):
    """통과 시 증거 JSON 에 failed_tests 빈 목록과 truncated false 가 기록됩니다."""
    evidence_path = tmp_path / "pass_evidence.json"
    runner = make_mock_runner(
        branch="feature/pass-test",
        head_sha="aabbcc1122334455",
        pytest_exit_code=0,
        pytest_stdout="3216 passed, 31 skipped in 55.0s",
    )

    code, _ = record_evidence(evidence_path=evidence_path, runner=runner)
    assert code == 0

    data, _ = load_evidence(evidence_path)
    assert data is not None
    assert data["failed_tests"] == []
    assert data["failed_tests_truncated"] is False


def test_record_evidence_failure_message_lists_failed_nodeids(tmp_path: Path):
    """실패 반환 메시지에 실패한 nodeid 가 줄바꿈으로 나열됩니다."""
    evidence_path = tmp_path / "fail_msg_evidence.json"
    runner = make_mock_runner(
        branch="feature/fail-msg",
        head_sha="deadbeef5678",
        pytest_exit_code=1,
        pytest_stdout=(
            "FAILED tests/test_x.py::test_y - AssertionError: boom\n"
            "ERROR tests/test_z.py::test_w - RuntimeError: setup\n"
            "1 failed, 1 error, 3214 passed in 55.0s"
        ),
    )

    code, msg = record_evidence(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "tests/test_x.py::test_y" in msg
    assert "tests/test_z.py::test_w" in msg

    data, _ = load_evidence(evidence_path)
    assert data is not None
    assert data["failed_tests"] == ["tests/test_x.py::test_y", "tests/test_z.py::test_w"]
    assert data["failed_tests_truncated"] is False


def test_record_evidence_failure_truncates_failed_tests(tmp_path: Path):
    """실패 nodeid 가 50건을 넘으면 앞 50건만 기록하고 truncated 를 true 로 표시합니다."""
    evidence_path = tmp_path / "truncated_evidence.json"
    nodeids = [f"tests/test_bulk.py::test_{i:03d}" for i in range(MAX_FAILED_TESTS_RECORDED + 1)]
    stdout = "\n".join(f"FAILED {nodeid} - AssertionError: boom" for nodeid in nodeids)
    stdout += f"\n{len(nodeids)} failed, 10 passed in 55.0s"
    runner = make_mock_runner(
        branch="feature/bulk-fail",
        head_sha="cafebabe0001",
        pytest_exit_code=1,
        pytest_stdout=stdout,
    )

    code, _ = record_evidence(evidence_path=evidence_path, runner=runner)
    assert code == 1

    data, _ = load_evidence(evidence_path)
    assert data is not None
    assert data["failed_tests"] == nodeids[:MAX_FAILED_TESTS_RECORDED]
    assert len(data["failed_tests"]) == MAX_FAILED_TESTS_RECORDED
    assert data["failed_tests_truncated"] is True


def test_verify_accepts_legacy_evidence_without_failed_tests(tmp_path: Path):
    """failed_tests 키가 없는 기존 증거 파일도 검증을 그대로 통과합니다."""
    target_sha = "c0ffee1234567890"
    evidence_path = tmp_path / "legacy_evidence.json"
    evidence_path.write_text(
        json.dumps(
            {
                "suite": "full",
                "target": "tests/",
                "command": " ".join(CANONICAL_FULL_SUITE_CMD),
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
