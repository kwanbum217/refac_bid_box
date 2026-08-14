from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts.orca_contract import char_len
from scripts.summarize_worker_done import (
    REQUIRED_FIELDS,
    main,
    summarize_worker_report,
)

SAMPLE_CAPSULE = """schema: ORCA_TASK_CAPSULE_V2
version: "2.1.0"
mode: worker
task_id: "task_123"

allowed_read_files:
  - "scripts/orca_contract.py"
  - "docs/ops/..."

allowed_write_files:
  - "scripts/summarize_worker_done.py"
  - "tests/test_summarize_worker_done.py"
"""

SAMPLE_VALID_REPORT = {
    "schema": "ORCA_WORKER_DONE_V2",
    "version": "2.1.0",
    "task_id": "task_123",
    "dispatch_id": "ctx_456",
    "status": "succeeded",
    "branch": "kwanbum217/test-branch",
    "commit": "abc1234567890",
    "commit_count": 1,
    "changed_files": [
        "scripts/summarize_worker_done.py",
        "tests/test_summarize_worker_done.py",
    ],
    "read_files": [
        "scripts/orca_contract.py",
        "docs/ops/orca_task_capsule_v2.md",
    ],
    "verification": [
        {
            "command": "uv run pytest tests/test_summarize_worker_done.py -q",
            "result": "9 passed",
        }
    ],
    "verdict": "pass",
    "blocking_issues": [],
}


def _write_report(path: Path, data: dict) -> Path:
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def _write_capsule(path: Path, text: str = SAMPLE_CAPSULE) -> Path:
    path.write_text(text, encoding="utf-8")
    return path


def test_valid_report_returns_zero_violations_and_exit_code_zero(tmp_path: Path):
    """(1) 완전한 보고는 위반 0과 종료 코드 0을 반환합니다."""
    report_file = _write_report(tmp_path / "report.json", SAMPLE_VALID_REPORT)
    capsule_file = _write_capsule(tmp_path / "capsule.yaml")

    result = summarize_worker_report(report_file, capsule_file)
    assert result["violations_count"] == 0
    assert result["violations"] == []
    assert result["exit_code"] == 0
    assert result["declared_verdict"] == "pass"
    assert result["effective_verdict"] == "pass"
    assert char_len(result["digest"]) <= 1200


def test_missing_required_fields_detected_individually(tmp_path: Path):
    """(2) 필수 필드 누락이 각각 위반으로 검출됩니다."""
    for field in REQUIRED_FIELDS:
        data = dict(SAMPLE_VALID_REPORT)
        del data[field]
        report_file = _write_report(tmp_path / f"missing_{field}.json", data)
        result = summarize_worker_report(report_file)
        assert result["exit_code"] == 1
        assert any(f"필수 필드 누락: {field}" in v for v in result["violations"]), (
            f"필드 누락 미검출: {field}"
        )

    # schema 불일치 검증
    bad_schema = dict(SAMPLE_VALID_REPORT, schema="WRONG_SCHEMA")
    bad_schema_file = _write_report(tmp_path / "bad_schema.json", bad_schema)
    res_schema = summarize_worker_report(bad_schema_file)
    assert res_schema["exit_code"] == 1
    assert any("schema 불일치" in v for v in res_schema["violations"])

    # version 비어있음 검증
    empty_version = dict(SAMPLE_VALID_REPORT, version="")
    empty_version_file = _write_report(tmp_path / "empty_version.json", empty_version)
    res_ver = summarize_worker_report(empty_version_file)
    assert res_ver["exit_code"] == 1
    assert any("version 값" in v for v in res_ver["violations"])


def test_succeeded_with_zero_commits_and_changed_files_violates_rule_3_3(tmp_path: Path):
    """(3) status 가 succeeded 인데 commit_count 0 이고 changed_files 있음이 검출됩니다."""
    data = dict(SAMPLE_VALID_REPORT, status="succeeded", commit_count=0)
    report_file = _write_report(tmp_path / "zero_commit.json", data)

    result = summarize_worker_report(report_file)
    assert result["exit_code"] == 1
    assert any("규약 3.3 위반" in v for v in result["violations"])

    # changed_files 가 없으면 위반이 아님
    no_change_data = dict(SAMPLE_VALID_REPORT, status="succeeded", commit_count=0, changed_files=[])
    no_change_file = _write_report(tmp_path / "no_change.json", no_change_data)
    res_no_change = summarize_worker_report(no_change_file)
    assert not any("규약 3.3 위반" in v for v in res_no_change["violations"])


def test_read_scope_excess_reported_without_failing(tmp_path: Path):
    """(4) read_files 초과가 read_scope_excess 로 나오되 그것만으로는 위반으로 세지 않습니다."""
    data = dict(
        SAMPLE_VALID_REPORT,
        read_files=[
            "scripts/orca_contract.py",
            "unauthorized_dir/secret.py",
        ],
    )
    report_file = _write_report(tmp_path / "read_excess.json", data)
    capsule_file = _write_capsule(tmp_path / "capsule.yaml")

    result = summarize_worker_report(report_file, capsule_file)
    assert result["read_scope_excess"] == ["unauthorized_dir/secret.py"]
    assert result["violations_count"] == 0
    assert result["exit_code"] == 0


def test_write_scope_excess_counted_as_violation(tmp_path: Path):
    """(5) changed_files 초과는 위반으로 셉니다."""
    data = dict(
        SAMPLE_VALID_REPORT,
        changed_files=[
            "scripts/summarize_worker_done.py",
            "forbidden_directory/test.py",
        ],
    )
    report_file = _write_report(tmp_path / "write_excess.json", data)
    capsule_file = _write_capsule(tmp_path / "capsule.yaml")

    result = summarize_worker_report(report_file, capsule_file)
    assert result["write_scope_excess"] == ["forbidden_directory/test.py"]
    assert any("allowed_write_files 범위 초과" in v for v in result["violations"])
    assert result["exit_code"] == 1


def test_verdict_pass_or_candidate_with_blocking_issues_demoted_to_blocked(tmp_path: Path):
    """(6) verdict pass/candidate 에 blocking_issues 가 있으면 실효 verdict 가 blocked 이고 종료 코드 1입니다."""
    # pass 케이스
    data_pass = dict(
        SAMPLE_VALID_REPORT,
        verdict="pass",
        blocking_issues=["심각한 결함 발견"],
    )
    report_pass = _write_report(tmp_path / "demote_pass.json", data_pass)
    res_pass = summarize_worker_report(report_pass)
    assert res_pass["declared_verdict"] == "pass"
    assert res_pass["effective_verdict"] == "blocked"
    assert res_pass["exit_code"] == 1
    assert any("verdict 격하" in v for v in res_pass["violations"])

    # candidate 케이스
    data_cand = dict(
        SAMPLE_VALID_REPORT,
        verdict="candidate",
        blocking_issues=[{"id": "C1", "reason": "테스트 실패"}],
    )
    report_cand = _write_report(tmp_path / "demote_cand.json", data_cand)
    res_cand = summarize_worker_report(report_cand)
    assert res_cand["declared_verdict"] == "candidate"
    assert res_cand["effective_verdict"] == "blocked"
    assert res_cand["exit_code"] == 1
    assert any("verdict 격하" in v for v in res_cand["violations"])


def test_giant_report_with_huge_log_respects_max_chars_cap(tmp_path: Path):
    """(7) verification 에 10만자 로그를 넣은 거대 보고를 줘도 다이제스트가 --max-chars 이하입니다."""
    huge_log = "ERROR: detail line\n" * 5000  # 10만자 초과
    data = dict(
        SAMPLE_VALID_REPORT,
        verification=[
            {
                "command": "uv run pytest tests/ -v",
                "result": huge_log,
            }
        ],
    )
    report_file = _write_report(tmp_path / "huge_report.json", data)

    max_limit = 1200
    result = summarize_worker_report(report_file, max_chars=max_limit, field_max_chars=600)
    assert char_len(result["digest"]) <= max_limit
    assert any("계약 비대" in v for v in result["violations"])
    assert result["exit_code"] == 1


def test_invalid_json_or_missing_file_returns_exit_code_2(tmp_path: Path, monkeypatch):
    """(8) 잘못된 JSON 및 누락된 파일은 종료 코드 2를 반환합니다."""
    # 1. 파일 없음
    monkeypatch.setattr(
        sys,
        "argv",
        ["summarize_worker_done.py", "--report", str(tmp_path / "nonexistent.json")],
    )
    assert main() == 2

    # 2. JSON 파싱 오류
    bad_json = tmp_path / "invalid.json"
    bad_json.write_text("invalid json {", encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        ["summarize_worker_done.py", "--report", str(bad_json)],
    )
    assert main() == 2


def test_json_output_flag_outputs_valid_json(tmp_path: Path, monkeypatch, capsys):
    """(9) --json 출력이 유효한 JSON이고 모든 메타데이터를 포함합니다."""
    report_file = _write_report(tmp_path / "report.json", SAMPLE_VALID_REPORT)
    capsule_file = _write_capsule(tmp_path / "capsule.yaml")

    monkeypatch.setattr(
        sys,
        "argv",
        [
            "summarize_worker_done.py",
            "--report",
            str(report_file),
            "--capsule",
            str(capsule_file),
            "--json",
        ],
    )
    exit_code = main()
    assert exit_code == 0

    captured = capsys.readouterr()
    parsed = json.loads(captured.out)
    assert parsed["schema"] == "ORCA_WORKER_DONE_SUMMARY"
    assert parsed["task_id"] == "task_123"
    assert parsed["status"] == "succeeded"
    assert parsed["declared_verdict"] == "pass"
    assert parsed["effective_verdict"] == "pass"
    assert parsed["short_commit"] == "abc12345"
    assert parsed["commit_count"] == 1
    assert parsed["read_files_count"] == 2
    assert parsed["violations_count"] == 0
    assert "digest" in parsed
