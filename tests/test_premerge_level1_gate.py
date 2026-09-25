"""tests/test_premerge_level1_gate.py

scripts/premerge_level1_gate.py 단위 테스트.
실제 git 병합 없이 모의 러너(mock runner)를 통해 모든 분기
(우회 변수, 비병합 커밋 소스, 비 main 브랜치, MERGE_HEAD 부재, 증거 부재,
JSON 손상, schema 불일치, strict=false, verdict=fail, 커밋 불일치, 일치 통과,
git-path 기반 MERGE_HEAD 조회, git-common-dir 기반 공통 증거 경로 해소,
prepare-commit-msg 위치 인자 처리)를 검증합니다.
"""

from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest

from scripts.premerge_level1_gate import (
    BYPASS_ENV_VAR,
    EVIDENCE_SCHEMA,
    get_merge_head_sha,
    is_bypass_active,
    load_evidence,
    main,
    resolve_evidence_path,
    verify_premerge_gate,
)

TARGET_SHA = "c0ffee1234567890abcdef1234567890abcdef12"


def make_mock_runner(
    branch: str = "main",
    merge_head: str | None = TARGET_SHA,
    git_path_merge_head: str | None = None,
    git_common_dir: str = ".git",
):
    """git 명령에 대한 결정론적 모의 러너를 생성합니다."""

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

        if cmd_list == ["git", "rev-parse", "--verify", "MERGE_HEAD"]:
            if merge_head is None:
                return subprocess.CompletedProcess(
                    cmd_list, 1, stdout="", stderr="fatal: Needed a single revision"
                )
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{merge_head}\n", stderr="")

        if len(cmd_list) >= 4 and cmd_list[:3] == ["git", "rev-parse", "--verify"]:
            ref = cmd_list[3].replace("^{commit}", "")
            return subprocess.CompletedProcess(cmd_list, 0, stdout=f"{ref}\n", stderr="")

        return subprocess.CompletedProcess(cmd_list, 0, stdout="", stderr="")

    return mock_runner


def write_evidence(path: Path, **overrides: object) -> Path:
    """검증을 통과하는 Level 1 strict 증거 파일을 만들고 필드를 덮어씁니다."""
    data: dict[str, object] = {
        "schema": EVIDENCE_SCHEMA,
        "commit": TARGET_SHA,
        "branch": "feature/my-task",
        "base": "main",
        "capsule": ".orca/capsules/task_x/capsule.yaml",
        "strict": True,
        "verdict": "pass",
        "recorded_at": "2026-09-25T00:00:00+00:00",
    }
    for key, value in overrides.items():
        if value is None:
            data.pop(key, None)
        else:
            data[key] = value
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return path


def test_bypass_active(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], tmp_path: Path
):
    """BYPASS_PREMERGE_LEVEL1_GATE 환경변수가 설정되면 즉시 통과하고 stderr에 경고를 남깁니다."""
    monkeypatch.setenv(BYPASS_ENV_VAR, "1")
    assert is_bypass_active() is True

    runner = make_mock_runner(branch="main")
    code, msg = verify_premerge_gate(evidence_path=tmp_path / "dummy.json", runner=runner)
    assert code == 0
    assert BYPASS_ENV_VAR in msg

    captured = capsys.readouterr()
    assert "[경고]" in captured.err
    assert BYPASS_ENV_VAR in captured.err


def test_non_merge_commit_source_skips_gate(tmp_path: Path):
    """prepare-commit-msg 단계에서 merge가 아닌 커밋 소스는 증거 없이 즉시 통과합니다."""
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


def test_non_main_branch_skips_gate(tmp_path: Path):
    """현재 브랜치가 main이 아니면 main 을 합치는 병합도 막지 않고 건너뜁니다."""
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

    runner = make_mock_runner(git_path_merge_head=str(merge_head_file), merge_head=None)

    sha, err = get_merge_head_sha(runner=runner)
    assert err == ""
    assert sha == expected_sha


def test_get_merge_head_sha_fallback_to_verify():
    """git-path 파일이 없을 때 git rev-parse --verify MERGE_HEAD로 폴백합니다."""
    expected_sha = "aabbccddeeff11223344556677889900aabbccdd"
    runner = make_mock_runner(git_path_merge_head=None, merge_head=expected_sha)

    sha, err = get_merge_head_sha(runner=runner)
    assert err == ""
    assert sha == expected_sha


def test_resolve_evidence_path_worktree(tmp_path: Path):
    """워크트리 환경에서 git-common-dir 를 기반으로 주 저장소 .cache 공통 경로를 해소합니다."""
    common_git_dir = tmp_path / "main_repo" / ".git"
    common_git_dir.mkdir(parents=True, exist_ok=True)

    runner = make_mock_runner(git_common_dir=str(common_git_dir))
    resolved = resolve_evidence_path(evidence_path=None, runner=runner)

    expected = tmp_path / "main_repo" / ".cache" / "level1_strict_evidence.json"
    assert resolved == expected


def test_resolve_evidence_path_explicit_override(tmp_path: Path):
    """명시적으로 지정된 커스텀 증거 경로는 git-common-dir 해석 없이 그대로 사용합니다."""
    custom_path = tmp_path / "custom_dir" / "my_evidence.json"
    runner = make_mock_runner()
    resolved = resolve_evidence_path(evidence_path=custom_path, runner=runner)
    assert resolved == custom_path


def test_main_branch_missing_evidence_file(tmp_path: Path):
    """증거 파일이 존재하지 않으면 거부하고 증거를 다시 만드는 명령을 안내합니다."""
    evidence_path = tmp_path / "missing_evidence.json"
    runner = make_mock_runner(branch="main")

    code, msg = verify_premerge_gate(
        target_branch="main",
        evidence_path=evidence_path,
        runner=runner,
    )
    assert code == 1
    assert "존재하지 않습니다" in msg
    assert "--strict --record-evidence" in msg


def test_main_branch_corrupted_evidence_file(tmp_path: Path):
    """증거 파일 JSON이 손상되었거나 dict가 아니면 fail-closed로 거부합니다."""
    bad_json = tmp_path / "bad.json"
    bad_json.write_text("{broken json", encoding="utf-8")

    runner = make_mock_runner(branch="main")
    code, msg = verify_premerge_gate(evidence_path=bad_json, runner=runner)
    assert code == 1
    assert "JSON" in msg

    not_dict_json = tmp_path / "list.json"
    not_dict_json.write_text("[]", encoding="utf-8")
    code2, msg2 = verify_premerge_gate(evidence_path=not_dict_json, runner=runner)
    assert code2 == 1
    assert "객체(dict)" in msg2


def test_main_branch_load_evidence_missing_and_valid(tmp_path: Path):
    """load_evidence 가 부재를 오류로, 정상 파일을 데이터로 돌려줍니다."""
    missing = tmp_path / "none.json"
    data, errors = load_evidence(missing)
    assert data is None
    assert errors

    valid = write_evidence(tmp_path / "valid.json")
    data_ok, errors_ok = load_evidence(valid)
    assert errors_ok == []
    assert data_ok is not None
    assert data_ok["strict"] is True


def test_main_branch_schema_mismatch_rejected(tmp_path: Path):
    """다른 스키마의 파일은 Level 1 strict 증거로 인정하지 않습니다."""
    evidence_path = write_evidence(tmp_path / "other_schema.json", schema="OTHER_EVIDENCE_V1")
    runner = make_mock_runner(branch="main")

    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "schema" in msg


def test_main_branch_strict_false_rejected(tmp_path: Path):
    """strict=false 증거는 병합 판정 통과 증거가 아니므로 거부합니다."""
    evidence_path = write_evidence(tmp_path / "not_strict.json", strict=False)
    runner = make_mock_runner(branch="main")

    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "strict" in msg


def test_main_branch_missing_strict_field_rejected(tmp_path: Path):
    """strict 필드가 아예 없어도 통과시키지 않습니다."""
    evidence_path = write_evidence(tmp_path / "no_strict.json", strict=None)
    runner = make_mock_runner(branch="main")

    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "strict" in msg


def test_main_branch_verdict_fail_rejected(tmp_path: Path):
    """verdict 가 pass 가 아니면 거부합니다."""
    evidence_path = write_evidence(tmp_path / "failed.json", verdict="fail")
    runner = make_mock_runner(branch="main")

    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "verdict" in msg


def test_main_branch_missing_commit_field_rejected(tmp_path: Path):
    """commit 필드가 비어 있으면 거부합니다."""
    evidence_path = write_evidence(tmp_path / "no_commit.json", commit=None)
    runner = make_mock_runner(branch="main")

    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "commit" in msg


def test_main_branch_commit_mismatch_rejected(tmp_path: Path):
    """다른 커밋의 증거는 재사용할 수 없으며 병합 대상과 다르면 거부합니다."""
    evidence_path = write_evidence(
        tmp_path / "stale.json", commit="deadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
    )
    runner = make_mock_runner(branch="main", merge_head=TARGET_SHA)

    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 1
    assert "일치하지 않습니다" in msg
    assert "--strict --record-evidence" in msg


def test_main_branch_valid_evidence_passes(tmp_path: Path):
    """증거의 커밋이 MERGE_HEAD와 일치하고 strict pass 이면 통과합니다."""
    evidence_path = write_evidence(tmp_path / "valid.json")
    runner = make_mock_runner(branch="main", merge_head=TARGET_SHA)

    code, msg = verify_premerge_gate(evidence_path=evidence_path, runner=runner)
    assert code == 0
    assert "검증 통과" in msg
    assert TARGET_SHA[:8] in msg


def test_source_commit_override_uses_resolved_sha(tmp_path: Path):
    """--source-commit 이 주어지면 MERGE_HEAD 대신 그 커밋과 증거를 대조합니다."""
    evidence_path = write_evidence(tmp_path / "valid.json")
    runner = make_mock_runner(branch="main", merge_head="1111111111111111111111111111111111111111")

    code, msg = verify_premerge_gate(
        evidence_path=evidence_path,
        source_commit=TARGET_SHA,
        runner=runner,
    )
    assert code == 0
    assert TARGET_SHA[:8] in msg


def test_main_cli_prepare_commit_msg_positional_args(tmp_path: Path):
    """prepare-commit-msg 훅의 위치 인자($1 msg_file, $2 source)를 올바르게 처리합니다."""
    evidence_path = write_evidence(tmp_path / "cli_evidence.json")
    runner = make_mock_runner(branch="main", merge_head=TARGET_SHA)

    # 1. merge 소스 -> 게이트 실행 및 통과
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


def test_main_cli_explicit_commit_source_flag(tmp_path: Path):
    """--commit-source 로 병합 소스를 명시하면 게이트가 실행됩니다."""
    runner = make_mock_runner(branch="main", merge_head=TARGET_SHA)

    code = main(
        [
            "--commit-source",
            "merge",
            "--evidence-path",
            str(tmp_path / "missing.json"),
        ],
        runner=runner,
    )
    assert code == 1


def test_main_cli_merge_source_without_merge_head_fails(tmp_path: Path):
    """위치 인자를 받은 병합 커밋에서 MERGE_HEAD 가 없으면 거부합니다."""
    runner = make_mock_runner(branch="main", merge_head=None)

    code = main([".git/MERGE_MSG", "merge"], runner=runner)
    assert code == 1
