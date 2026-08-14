from __future__ import annotations

import json

import pytest

from scripts.orca_contract import (
    ContractError,
    char_len,
    load_capsule,
    load_report,
    matches_any,
    parse_capsule_list,
    parse_capsule_scalar,
    scope_excess,
    string_list,
    truncate,
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
