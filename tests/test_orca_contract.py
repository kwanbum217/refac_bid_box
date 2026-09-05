from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from scripts.orca_contract import (
    DEFAULT_VERIFY_PYTEST_TIMEOUT,
    DEFAULT_VERIFY_TIMEOUT,
    DEFAULT_VERIFY_VALIDATE_TIMEOUT,
    ContractError,
    char_len,
    classify_verification_command,
    get_verification_timeout,
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


def test_verify_verification_truth_omitted_warning_count_passes(tmp_path):
    """warning 건수를 적지 않은 정직한 보고가 실패하면 안 됩니다.

    실제 출력에는 거의 항상 warning 이 섞이지만 워커 보고서는 대개 이를 적지
    않습니다. 누락을 0 으로 간주해 대조하면 참인 보고가 전부 실패합니다.
    """
    actual_output = "2495 passed, 6 skipped, 3 deselected, 306 warnings in 67.28s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "2495 passed, 6 skipped, 3 deselected in 117.47s",
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(actual_output, 0)
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    assert ok
    assert violations == []
    assert details[0]["count_match"] is True


def test_verify_verification_truth_omitted_skipped_count_passes(tmp_path):
    """skipped 를 적지 않은 축약 보고는 위반이 아닙니다."""
    actual_output = "43 passed, 2 skipped in 12.34s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "43 passed",
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc(actual_output, 0)
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    assert ok
    assert violations == []
    assert details[0]["count_match"] is True


def test_verify_verification_truth_reported_warning_mismatch_ignored(tmp_path):
    """보고서가 warning 을 적었더라도 그 수치 차이는 위반이 아닙니다."""
    actual_output = "43 passed, 306 warnings in 12.34s"
    verification = [
        {
            "command": "uv run pytest tests/ -q",
            "result": "43 passed, 1 warning in 12.34s",
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


# ---------------------------------------------------------------------------
# 명령 종류 판별 및 타임아웃 테스트 (Task t6)
# ---------------------------------------------------------------------------


def test_classify_verification_command():
    """classify_verification_command 순수 함수가 명령 종류와 argv 를 올바르게 반환합니다."""
    # 1. pytest 계열
    cmd_type, argv = classify_verification_command("uv run pytest tests/ -q")
    assert cmd_type == "pytest"
    assert argv == ["uv", "run", "pytest", "tests/", "-q"]

    cmd_type, argv = classify_verification_command("pytest tests/test_app.py")
    assert cmd_type == "pytest"
    assert argv == ["uv", "run", "pytest", "tests/test_app.py", "-q"]

    cmd_type, argv = classify_verification_command("python3 -m pytest tests/")
    assert cmd_type == "pytest"
    assert argv == ["uv", "run", "pytest", "tests/", "-q"]

    # 2. validate_agent_rules 계열
    cmd_type, argv = classify_verification_command(
        "python3 scripts/validate_agent_rules.py --quiet"
    )
    assert cmd_type == "validate_agent_rules"
    assert argv is not None
    assert argv[1] == "scripts/validate_agent_rules.py"

    cmd_type, argv = classify_verification_command("scripts/validate_agent_rules.py")
    assert cmd_type == "validate_agent_rules"
    assert argv is not None

    # 3. 화이트리스트 밖 명령
    cmd_type, argv = classify_verification_command("npm test")
    assert cmd_type == "unknown"
    assert argv is None

    cmd_type, argv = classify_verification_command("")
    assert cmd_type == "unknown"
    assert argv is None


def test_get_verification_timeout():
    """get_verification_timeout 이 명령 종류별 기본값 및 사용자 지정값을 올바르게 반환합니다."""
    # (a) pytest 기본값 900
    assert get_verification_timeout("uv run pytest tests/ -q") == DEFAULT_VERIFY_PYTEST_TIMEOUT
    assert get_verification_timeout("uv run pytest tests/ -q") == 900

    # (b) validate_agent_rules 기본값 30 (pytest 와 다름)
    assert (
        get_verification_timeout("python3 scripts/validate_agent_rules.py --quiet")
        == DEFAULT_VERIFY_VALIDATE_TIMEOUT
    )
    assert get_verification_timeout("python3 scripts/validate_agent_rules.py --quiet") == 30
    assert DEFAULT_VERIFY_PYTEST_TIMEOUT != DEFAULT_VERIFY_VALIDATE_TIMEOUT

    # (c) 기타 미분류 명령 기본값 30
    assert get_verification_timeout("npm test") == DEFAULT_VERIFY_TIMEOUT

    # (d) custom_timeout 명시 시 최우선 적용
    assert get_verification_timeout("uv run pytest tests/ -q", custom_timeout=45) == 45
    assert (
        get_verification_timeout(
            "python3 scripts/validate_agent_rules.py --quiet", custom_timeout=10
        )
        == 10
    )


def test_verify_verification_truth_applies_pytest_timeout(tmp_path):
    """(a) pytest 계열 명령에 적용되는 기본 타임아웃이 30 이 아니라 900 초입니다."""
    verification = [{"command": "uv run pytest tests/ -q", "result": "1 passed"}]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc("1 passed in 1.0s", 0)
        ok, _violations, _details = verify_verification_truth(str(tmp_path), verification)

    assert ok
    assert mock_run.call_args.kwargs["timeout"] == DEFAULT_VERIFY_PYTEST_TIMEOUT
    assert mock_run.call_args.kwargs["timeout"] == 900


def test_verify_verification_truth_applies_validate_timeout(tmp_path):
    """(b) validate_agent_rules 계열에 적용되는 기본 타임아웃이 pytest 용 값과 다릅니다."""
    verification = [
        {
            "command": "python3 scripts/validate_agent_rules.py --quiet",
            "result": "검증 통과: 12/12 건.",
        }
    ]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc("검증 통과: 12/12 건.", 0)
        ok, _violations, _details = verify_verification_truth(str(tmp_path), verification)

    assert ok
    assert mock_run.call_args.kwargs["timeout"] == DEFAULT_VERIFY_VALIDATE_TIMEOUT
    assert mock_run.call_args.kwargs["timeout"] == 30


def test_verify_verification_truth_explicit_timeout_takes_precedence(tmp_path):
    """(c) 호출자가 timeout 을 명시하면 그 값이 우선합니다."""
    verification = [{"command": "uv run pytest tests/ -q", "result": "1 passed"}]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.return_value = _mock_proc("1 passed in 1.0s", 0)
        ok, _violations, _details = verify_verification_truth(
            str(tmp_path), verification, timeout=120
        )

    assert ok
    assert mock_run.call_args.kwargs["timeout"] == 120


def test_verify_verification_truth_timeout_marks_status_and_fails_closed(tmp_path):
    """(d), (e) 타임아웃 발생 시 status 가 fail 및 timed_out=True 로 표기되고, 게이트는 fail-closed 로 처리됩니다."""
    import subprocess as sp

    verification = [{"command": "uv run pytest tests/ -q", "result": "2495 passed"}]
    with patch("scripts.orca_contract.subprocess.run") as mock_run:
        mock_run.side_effect = sp.TimeoutExpired(
            cmd=["uv", "run", "pytest", "tests/", "-q"], timeout=900
        )
        ok, violations, details = verify_verification_truth(str(tmp_path), verification)

    # (e) fail-closed 검증
    assert ok is False
    assert len(violations) == 1
    # (d) 타임아웃 표기 및 위반 메시지에 timeout 초와 명령 종류가 기재됨
    assert "재실행 타임아웃 (pytest, 900초)" in violations[0]
    assert details[0]["status"] == "fail"
    assert details[0]["timed_out"] is True
    assert details[0]["timeout_seconds"] == 900
    assert details[0]["command_type"] == "pytest"


def test_single_source_of_truth_required_fields():
    """O-05: 필수 필드 정본이 일관되게 공유되며 디스크 템플릿과 고지문이 정본과 100% 일치합니다."""
    from pathlib import Path

    from scripts.orca_contract import (
        WORKER_DONE_REQUIRED_FIELDS,
        WORKER_DONE_SCHEMA_SPEC,
        render_worker_done_template,
    )
    from scripts.orca_taskctl import WORKER_REPORT_SCHEMA
    from scripts.summarize_worker_done import REQUIRED_FIELDS

    # 1. dispatch_id 는 하위 호환성을 위해 선택 필드(required: False)로 정의됨
    assert "dispatch_id" in WORKER_DONE_SCHEMA_SPEC
    assert WORKER_DONE_SCHEMA_SPEC["dispatch_id"]["required"] is False
    assert "dispatch_id" not in WORKER_DONE_REQUIRED_FIELDS

    # 2. summarize_worker_done 의 REQUIRED_FIELDS 가 정본과 동일
    assert set(REQUIRED_FIELDS) == set(WORKER_DONE_REQUIRED_FIELDS)

    # 3. orca_taskctl 의 WORKER_REPORT_SCHEMA 와 정본 필수 필드가 정확히 1:1 일치
    taught = {
        line.split(":", 1)[0].strip()
        for line in WORKER_REPORT_SCHEMA.splitlines()
        if line.startswith("  ") and ":" in line
    }
    assert taught == set(WORKER_DONE_REQUIRED_FIELDS)

    # 4. .agents/templates/worker_done_v2.json 디스크 템플릿이 렌더러 출력과 100% 완전 일치
    template_path = Path(".agents/templates/worker_done_v2.json")
    assert template_path.is_file(), "템플릿 파일이 디스크에 존재해야 합니다"
    disk_data = json.loads(template_path.read_text(encoding="utf-8"))
    assert disk_data == render_worker_done_template(), (
        "디스크 템플릿이 정본 렌더러와 100% 일치해야 합니다"
    )


def test_drift_detected_when_spec_modified_without_syncing_template_or_notice(monkeypatch):
    """O-05: 정본(WORKER_DONE_SCHEMA_SPEC)에 새 필수 필드가 추가되었을 때 디스크 템플릿이나 고지문이 따라오지 않으면 검사가 실패함을 입증합니다."""
    from pathlib import Path

    from scripts.orca_contract import (
        WORKER_DONE_SCHEMA_SPEC,
        get_worker_done_required_fields,
        render_worker_done_template,
    )
    from scripts.orca_taskctl import WORKER_REPORT_SCHEMA

    # 1. 정본에 가상의 새 필수 필드 추가
    augmented_spec = dict(WORKER_DONE_SCHEMA_SPEC)
    augmented_spec["unpropagated_drift_field"] = {
        "required": True,
        "description": '"미동기화 검출용 필드"',
        "sample": "drift_val",
    }
    monkeypatch.setattr("scripts.orca_contract.WORKER_DONE_SCHEMA_SPEC", augmented_spec)

    # 2. 렌더러는 새 필드를 생성하지만, 디스크 파일은 이전 상태이므로 완전 일치 검사가 실패함
    disk_template = json.loads(
        Path(".agents/templates/worker_done_v2.json").read_text(encoding="utf-8")
    )
    assert disk_template != render_worker_done_template()
    assert "unpropagated_drift_field" not in disk_template

    # 3. 고지문(WORKER_REPORT_SCHEMA)도 갱신 전 상태이므로 필수 필드 일치 검사가 실패함
    taught = {
        line.split(":", 1)[0].strip()
        for line in WORKER_REPORT_SCHEMA.splitlines()
        if line.startswith("  ") and ":" in line
    }
    augmented_required = get_worker_done_required_fields(augmented_spec)
    assert "unpropagated_drift_field" in augmented_required
    assert taught != set(augmented_required)


def test_sync_worker_done_template_updates_disk_file(tmp_path):
    """O-05: sync_worker_done_template 이 정본으로부터 템플릿 파일을 정확히 동기화함을 검증합니다."""
    from scripts.orca_contract import (
        render_worker_done_template,
        sync_worker_done_template,
    )

    out_file = tmp_path / "worker_done_v2.json"
    sync_worker_done_template(path=out_file)
    assert out_file.is_file()
    data = json.loads(out_file.read_text(encoding="utf-8"))
    assert data == render_worker_done_template()
