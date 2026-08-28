from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts.orca_contract import (
    ContractError,
    char_len,
    load_capsule,
    load_report,
    matches_any,
    parse_capsule_list,
    parse_capsule_scalar,
    parse_pytest_summary,
    scope_excess,
    string_list,
    truncate,
    verify_verification_truth,
    write_scope_excess,
)

CAPSULE = """schema: ORCA_TASK_CAPSULE_V2
version: "2.1.0"
mode: worker
task_id: "task_abc"

objective: >
  무언가를 한다.

ground_truth:
  - fact: "이미 확인된 사실"
    evidence: "docs/context/CURRENT_STATE.md"
    recheck: false

allowed_read_files:
  - "scripts/orca_contract.py"
  - "docs/ops/..."   # 이 아래 전부
  - "tests/*"

allowed_write_files:
  - "scripts/new_tool.py"
  - "tests/test_new_tool.py"

forbidden:
  - "main 직접 커밋 금지"

return_contract: ORCA_WORKER_DONE_V2
"""


def test_parse_capsule_scalar():
    assert parse_capsule_scalar(CAPSULE, "schema") == "ORCA_TASK_CAPSULE_V2"
    assert parse_capsule_scalar(CAPSULE, "version") == "2.1.0"
    assert parse_capsule_scalar(CAPSULE, "task_id") == "task_abc"
    assert parse_capsule_scalar(CAPSULE, "nonexistent") is None


def test_parse_capsule_list_takes_only_string_items():
    assert parse_capsule_list(CAPSULE, "allowed_write_files") == [
        "scripts/new_tool.py",
        "tests/test_new_tool.py",
    ]
    assert parse_capsule_list(CAPSULE, "forbidden") == ["main 직접 커밋 금지"]
    # 객체 리스트는 경로 목록이 아니므로 걸러진다
    assert parse_capsule_list(CAPSULE, "ground_truth") == []
    assert parse_capsule_list(CAPSULE, "nonexistent") == []


def test_parse_capsule_list_strips_trailing_comment():
    assert "docs/ops/..." in parse_capsule_list(CAPSULE, "allowed_read_files")


def test_parse_capsule_list_stops_at_dedent():
    # allowed_read_files 블록이 allowed_write_files 항목을 삼키지 않는다
    read = parse_capsule_list(CAPSULE, "allowed_read_files")
    assert "scripts/new_tool.py" not in read


@pytest.mark.parametrize(
    ("path", "pattern", "expected"),
    [
        ("scripts/a.py", "scripts/a.py", True),
        ("scripts/a.py", "scripts/b.py", False),
        ("docs/ops/x.md", "docs/ops/...", True),
        ("docs/ops/deep/x.md", "docs/ops/...", True),
        ("docs/opsx/x.md", "docs/ops/...", False),
        ("docs/ops", "docs/ops/...", True),
        ("tests/a.py", "tests/*", True),
        # `*` 는 구분자를 넘지 않는다. 재귀는 `tests/...` 로 적어야 한다
        ("tests/a/b.py", "tests/*", False),
        ("tests/a/b.py", "tests/...", True),
        ("src/ml/features.py", "src/**", True),
        ("src/ml/features.py", "src/**/*.py", True),
        ("docs/ops/x.md", "docs/ops/*.md", True),
        ("docs/ops/deep/x.md", "docs/ops/*.md", False),
        ("./scripts/a.py", "scripts/a.py", True),
        (".env", ".env", True),
    ],
)
def test_matches_any(path, pattern, expected):
    assert matches_any(path, [pattern]) is expected


def test_scope_excess_without_allowlist_reports_nothing():
    # 허용 목록이 없으면 판정 근거가 없다. 전부 초과로 몰지 않는다.
    assert scope_excess(["a.py", "b.py"], []) == []


def test_write_scope_excess_without_allowlist_denies_everything():
    # 쓰기 범위에서 빈 허용 목록은 전면 금지다. 허용 목록이 비면 전부 초과다.
    assert write_scope_excess(["a.py"], []) == ["a.py"]
    assert write_scope_excess(["a.py", "b.py", "c.py"], []) == ["a.py", "b.py", "c.py"]
    assert write_scope_excess([], []) == []


def test_write_scope_excess_reports_only_outsiders():
    allowed = ["scripts/new_tool.py", "tests/..."]
    excess = write_scope_excess(
        ["scripts/new_tool.py", "tests/test_new_tool.py", "src/main.py"], allowed
    )
    assert excess == ["src/main.py"]


def test_scope_excess_reports_only_outsiders():
    allowed = ["scripts/new_tool.py", "tests/..."]
    excess = scope_excess(["scripts/new_tool.py", "tests/test_new_tool.py", "src/main.py"], allowed)
    assert excess == ["src/main.py"]


def test_load_capsule_and_report(tmp_path):
    capsule = tmp_path / "capsule.yaml"
    capsule.write_text(CAPSULE, encoding="utf-8")
    assert parse_capsule_scalar(load_capsule(capsule), "mode") == "worker"

    report = tmp_path / "report.json"
    report.write_text(json.dumps({"status": "succeeded"}), encoding="utf-8")
    assert load_report(report)["status"] == "succeeded"


def test_load_report_raises_on_bad_json(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text('{"note": "\\D 는 유효한 이스케이프가 아니다"}', encoding="utf-8")
    with pytest.raises(ContractError, match="파싱 실패"):
        load_report(bad)


def test_load_report_raises_on_non_object(tmp_path):
    arr = tmp_path / "arr.json"
    arr.write_text("[1, 2]", encoding="utf-8")
    with pytest.raises(ContractError, match="객체가 아님"):
        load_report(arr)


def test_missing_files_raise():
    with pytest.raises(ContractError, match="Capsule 파일 없음"):
        load_capsule("/nonexistent/capsule.yaml")
    with pytest.raises(ContractError, match="보고 파일 없음"):
        load_report("/nonexistent/report.json")


def test_string_list_normalizes_shapes():
    assert string_list(None) == []
    assert string_list("a.py") == ["a.py"]
    assert string_list(["a.py", "b.py"]) == ["a.py", "b.py"]
    assert string_list([{"path": "a.py"}, {"file": "b.py"}, {"x": 1}]) == [
        "a.py",
        "b.py",
    ]
    assert string_list(42) == []


def test_char_len_counts_characters_not_bytes():
    # 한글은 UTF-8 에서 3바이트다. 예산 판정은 문자 수로 한다.
    assert char_len("가나다") == 3


def test_truncate_marks_loss_and_respects_limit():
    assert truncate("abc", 10) == "abc"
    out = truncate("가" * 100, 20)
    assert char_len(out) == 20
    assert out.endswith("...(잘림)")
    assert truncate("abc", 0) == ""
    assert truncate("abcdefgh", 3) == "abc"


def test_matches_any_rejects_parent_directory_traversal():
    """결함 1: 상위 디렉터리 참조가 포함된 경로는 거부됩니다."""
    assert matches_any("scripts/../../secret.py", ["scripts/..."]) is False


def test_matches_any_rejects_empty_path():
    """결함 2: 빈 경로는 거부됩니다."""
    assert matches_any("", ["*"]) is False


def test_parse_capsule_list_preserves_hash_in_quotes():
    """결함 3: 따옴표 안의 샵(#) 문자는 주석으로 잘리지 않고 보존됩니다."""
    capsule = 'allowed_read_files:\n  - "src/file #1.py"\n'
    assert parse_capsule_list(capsule, "allowed_read_files") == ["src/file #1.py"]


def test_parse_capsule_list_continues_past_column_zero_comments():
    """결함 4: 0열 주석 줄이 블록을 끊지 않고 다음 항목들이 파싱됩니다."""
    capsule = 'allowed_read_files:\n  - "a.py"\n# comm\n  - "b.py"\n'
    assert parse_capsule_list(capsule, "allowed_read_files") == ["a.py", "b.py"]


def test_parse_capsule_scalar_folded_scalar():
    """결함 6: YAML folded scalar (>)를 실제 문장으로 파싱합니다."""
    capsule = "objective: >\n  abc def\n"
    assert parse_capsule_scalar(capsule, "objective") == "abc def"


# ---------------------------------------------------------------------------
# parse_pytest_summary 순수 함수 테스트
# ---------------------------------------------------------------------------


def test_parse_pytest_summary_passed_and_skipped():
    """(a) '43 passed, 2 skipped in 12.34s' 를 정확히 파싱합니다."""
    result = parse_pytest_summary("43 passed, 2 skipped in 12.34s")
    assert result is not None
    assert result["passed"] == 43
    assert result["skipped"] == 2


def test_parse_pytest_summary_failed_and_passed():
    """(b) '3 failed, 40 passed in 9.9s' 를 파싱합니다."""
    result = parse_pytest_summary("3 failed, 40 passed in 9.9s")
    assert result is not None
    assert result["failed"] == 3
    assert result["passed"] == 40


def test_parse_pytest_summary_no_summary_returns_none():
    """(c) 요약이 없는 출력에서 None 을 돌려줍니다."""
    result = parse_pytest_summary("collecting ... done\nsome debug output\n")
    assert result is None


def test_parse_pytest_summary_with_ansi_and_decoration():
    """(d) 색상 이스케이프와 '=' 장식이 섞인 줄도 파싱됩니다."""
    ansi_line = "\x1b[32m43 passed\x1b[0m, 2 skipped in 12.34s"
    result = parse_pytest_summary(ansi_line)
    assert result is not None
    assert result["passed"] == 43
    assert result["skipped"] == 2

    decorated = "====== 10 passed in 1.0s ======"
    result2 = parse_pytest_summary(decorated)
    assert result2 is not None
    assert result2["passed"] == 10


def test_parse_pytest_summary_finds_summary_not_only_last_line():
    """요약 줄이 마지막이 아닌 경우에도 탐색합니다."""
    output = "43 passed in 1.0s\nDocs: https://docs.pytest.org/...\n"
    result = parse_pytest_summary(output)
    assert result is not None
    assert result["passed"] == 43


# ---------------------------------------------------------------------------
# verify_verification_truth 결과 동일성 대조 테스트
# ---------------------------------------------------------------------------


def _mock_proc(stdout: str = "", returncode: int = 0):
    """subprocess.run 모의 반환값을 생성합니다."""

    class _Proc:
        pass

    p = _Proc()
    p.returncode = returncode
    p.stdout = stdout
    p.stderr = ""
    return p


def test_verify_verification_truth_count_mismatch_fails(tmp_path):
    """(e) 실제 43 passed 인데 보고서가 500 passed 라고 적으면 FAIL 합니다."""
    actual_output = "43 passed, 2 skipped in 12.34s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "500 passed in 9.9s",
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(actual_output, 0)
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    assert not ok
    assert len(violations) == 1
    assert "건수 불일치" in violations[0]
    assert details[0]["count_match"] is False
    assert details[0]["actual_counts"]["passed"] == 43
    assert details[0]["reported_counts"]["passed"] == 500


def test_verify_verification_truth_count_match_passes(tmp_path):
    """(f) 실제와 보고 건수가 같으면 PASS 합니다."""
    actual_output = "43 passed, 2 skipped in 12.34s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "43 passed, 2 skipped in 12.34s",
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(actual_output, 0)
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    assert ok
    assert violations == []
    assert details[0]["count_match"] is True


def test_verify_verification_truth_no_counts_in_report_passes(tmp_path):
    """(g) 보고서가 건수를 안 적었으면 기존처럼 PASS 합니다(하위 호환)."""
    actual_output = "43 passed in 1.0s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "tests passed",  # 건수 없는 간단한 보고
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(actual_output, 0)
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    assert ok
    assert violations == []
    assert details[0]["count_match"] is None
    assert details[0]["status"] == "pass"


def test_verify_verification_truth_explicit_passed_mismatch_fails(tmp_path):
    """(h) 명시적 passed 필드가 실제와 다르면 FAIL 합니다."""
    actual_output = "43 passed in 1.0s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "43 passed in 1.0s",
            "passed": 999,  # 명시적으로 잘못 기재
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(actual_output, 0)
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    assert not ok
    assert "건수 불일치" in violations[0]
    assert details[0]["count_match"] is False


def test_verify_verification_truth_explicit_exit_code_mismatch_fails(tmp_path):
    """(i) 명시적 exit_code 가 실제와 다르면 FAIL 합니다."""
    actual_output = "43 passed in 1.0s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "43 passed in 1.0s",
            "exit_code": 1,  # 실제는 0 인데 1 로 기재
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(actual_output, 0)
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    assert not ok
    assert "exit_code" in violations[0]
    assert details[0]["count_match"] is False


def test_verify_verification_truth_details_have_required_fields(tmp_path):
    """detailed_results 각 항목에 actual_counts, reported_counts, count_match, actual_exit_code, stdout_digest 가 있습니다."""
    actual_output = "43 passed, 2 skipped in 12.34s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "43 passed, 2 skipped in 12.34s",
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(actual_output, 0)
        _ok, _violations, details = verify_verification_truth(str(tmp_path), verification)

    d = details[0]
    assert "actual_counts" in d
    assert "reported_counts" in d
    assert "count_match" in d
    assert "actual_exit_code" in d
    assert "stdout_digest" in d
    # stdout_digest 는 16 자리 hex
    assert d["stdout_digest"] is not None
    assert len(d["stdout_digest"]) == 16
