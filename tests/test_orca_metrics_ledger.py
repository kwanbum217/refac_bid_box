"""
tests/test_orca_metrics_ledger.py

scripts/orca_metrics_ledger.py 의 단위 테스트입니다.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from scripts.orca_metrics_ledger import (
    DEFAULT_LEDGER,
    LEDGER_SCHEMA,
    _load_rows,
    _median_or_null,
    build_parser,
    main,
)

# --------------------------------------------------------------------------
# 픽스처
# --------------------------------------------------------------------------

CAPSULE_CONTENT = """schema: ORCA_TASK_CAPSULE_V2
version: "2.1.0"
mode: worker
run_id: "run_test123"
task_id: "task_testABC"

objective: >
  테스트용 Capsule 입니다.

allowed_read_files:
  - "scripts/orca_contract.py"

allowed_write_files:
  - "scripts/new_tool.py"

return_contract: ORCA_WORKER_DONE_V2
"""

REPORT_CONTENT = {
    "schema": "ORCA_WORKER_DONE_V2",
    "version": "2.1.0",
    "status": "succeeded",
    "verdict": "candidate",
    "read_files": ["scripts/orca_contract.py", "tests/test_orca_contract.py"],
    "changed_files": ["scripts/new_tool.py"],
    "verification": [
        {"command": "uv run pytest -q", "result": "passed"},
        {"command": "uv run ruff check", "result": "passed"},
    ],
}


@pytest.fixture
def capsule_file(tmp_path: Path) -> Path:
    """임시 Capsule 파일을 만들고 경로를 반환합니다."""
    p = tmp_path / "capsule.yaml"
    p.write_text(CAPSULE_CONTENT, encoding="utf-8")
    return p


@pytest.fixture
def report_file(tmp_path: Path) -> Path:
    """임시 보고 JSON 파일을 만들고 경로를 반환합니다."""
    p = tmp_path / "worker_done.json"
    p.write_text(json.dumps(REPORT_CONTENT), encoding="utf-8")
    return p


@pytest.fixture
def ledger_file(tmp_path: Path) -> Path:
    """임시 원장 JSONL 파일 경로를 반환합니다 (아직 존재하지 않음)."""
    return tmp_path / "ledger.jsonl"


def run_record(
    capsule: Path,
    report: Path,
    ledger: Path,
    task: str = "task_testABC",
    dispatch: str = "ctx_test001",
    roundtrips: int | None = None,
) -> int:
    """record 하위 명령을 실행합니다."""
    argv = [
        "--ledger",
        str(ledger),
        "record",
        "--run",
        "run_test123",
        "--task",
        task,
        "--dispatch",
        dispatch,
        "--role",
        "builder",
        "--model",
        "test-model-v1",
        "--capsule",
        str(capsule),
        "--report",
        str(report),
    ]
    if roundtrips is not None:
        argv += ["--roundtrips", str(roundtrips)]
    return main(argv)


# --------------------------------------------------------------------------
# (1) record 가 Capsule 과 보고에서 자동 도출한 값이 정확함
# --------------------------------------------------------------------------


def test_record_auto_derives_values(
    capsule_file: Path, report_file: Path, ledger_file: Path
) -> None:
    rc = run_record(capsule_file, report_file, ledger_file)
    assert rc == 0

    rows, corrupt = _load_rows(ledger_file)
    assert corrupt == 0
    assert len(rows) == 1

    row = rows[0]
    assert row["ledger_schema"] == LEDGER_SCHEMA
    assert row["task_id"] == "task_testABC"
    assert row["dispatch_id"] == "ctx_test001"
    assert row["role"] == "builder"
    assert row["model"] == "test-model-v1"

    # capsule_chars: Capsule 원문 길이
    assert row["capsule_chars"] == len(CAPSULE_CONTENT)

    # report_chars: 보고 원문 길이
    expected_report_chars = len(json.dumps(REPORT_CONTENT))
    assert row["report_chars"] == expected_report_chars

    # read_files_count: read_files 리스트 길이
    assert row["read_files_count"] == 2

    # changed_files_count: ORCA_WORKER_DONE_V2 계약 필드 changed_files 길이
    assert row["changed_files_count"] == 1

    # verification_count: verification 리스트 길이
    assert row["verification_count"] == 2

    # verdict 자동 도출 (계약 필드 verdict 만 읽음)
    assert row["verdict"] == "candidate"
    assert row["status"] == "succeeded"

    # recorded_at 존재
    assert "recorded_at" in row


# --------------------------------------------------------------------------
# (1-b) 결함 1 재현: changed_files 만 있고 files_modified 가 없는 계약 준수 보고
# --------------------------------------------------------------------------


def test_changed_files_count_from_contract_field(
    capsule_file: Path, ledger_file: Path, tmp_path: Path
) -> None:
    """ORCA_WORKER_DONE_V2 계약 준수 보고(changed_files 필드)에서 개수가 정확해야 합니다.

    files_modified 를 읽는 버그가 있으면 changed_files_count=0 이 기록됩니다.
    """
    report = tmp_path / "contract_report.json"
    report.write_text(
        json.dumps(
            {
                "schema": "ORCA_WORKER_DONE_V2",
                "version": "2.1.0",
                "status": "succeeded",
                "verdict": "candidate",
                "read_files": ["scripts/orca_contract.py"],
                "changed_files": ["scripts/tool_a.py", "tests/test_tool_a.py"],
                # files_modified 는 의도적으로 없음 (계약 비표준 필드)
            }
        ),
        encoding="utf-8",
    )
    rc = run_record(capsule_file, report, ledger_file)
    assert rc == 0

    rows, _ = _load_rows(ledger_file)
    assert rows[0]["changed_files_count"] == 2, (
        "changed_files 필드 2건이 정확히 계산되어야 합니다. "
        "files_modified 를 읽는 버그가 있으면 0 이 됩니다."
    )


# --------------------------------------------------------------------------
# (2) roundtrips 미지정 시 null 로 저장되고 0 이 아님
# --------------------------------------------------------------------------


def test_roundtrips_null_when_not_specified(
    capsule_file: Path, report_file: Path, ledger_file: Path
) -> None:
    run_record(capsule_file, report_file, ledger_file)
    rows, _ = _load_rows(ledger_file)
    assert rows[0]["roundtrips"] is None
    assert rows[0]["roundtrips"] != 0


def test_roundtrips_stored_when_specified(
    capsule_file: Path, report_file: Path, ledger_file: Path
) -> None:
    run_record(capsule_file, report_file, ledger_file, roundtrips=3)
    rows, _ = _load_rows(ledger_file)
    assert rows[0]["roundtrips"] == 3


# --------------------------------------------------------------------------
# (3) 같은 (task_id, dispatch_id) 재기록 시 행이 늘지 않고 종료 코드 1
# --------------------------------------------------------------------------


def test_duplicate_rejected_with_exit_code_1(
    capsule_file: Path, report_file: Path, ledger_file: Path
) -> None:
    rc1 = run_record(capsule_file, report_file, ledger_file)
    assert rc1 == 0

    rc2 = run_record(capsule_file, report_file, ledger_file)
    assert rc2 == 1

    rows, _ = _load_rows(ledger_file)
    assert len(rows) == 1  # 행이 늘지 않아야 함


# --------------------------------------------------------------------------
# (4) summary 가 null 을 집계에서 제외하고 유효 행 수를 함께 보고함
# --------------------------------------------------------------------------


def _write_raw_rows(ledger: Path, rows: list[dict]) -> None:
    """테스트용 행을 직접 원장에 씁니다."""
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")


def test_summary_excludes_null_and_reports_valid_count(ledger_file: Path) -> None:
    rows = [
        {
            "ledger_schema": LEDGER_SCHEMA,
            "recorded_at": "2026-08-15T09:00:00+09:00",
            "task_id": "t1",
            "dispatch_id": "d1",
            "role": "builder",
            "model": "m1",
            "capsule_chars": 1000,
            "report_chars": 500,
            "read_files_count": 3,
            "changed_files_count": 1,
            "roundtrips": None,
            "first_useful_seconds": None,
            "verdict": "succeeded",
            "status": "succeeded",
        },
        {
            "ledger_schema": LEDGER_SCHEMA,
            "recorded_at": "2026-08-15T10:00:00+09:00",
            "task_id": "t2",
            "dispatch_id": "d2",
            "role": "builder",
            "model": "m1",
            "capsule_chars": 2000,
            "report_chars": 800,
            "read_files_count": 5,
            "changed_files_count": 2,
            "roundtrips": 4,
            "first_useful_seconds": None,
            "verdict": "succeeded",
            "status": "succeeded",
        },
    ]
    _write_raw_rows(ledger_file, rows)

    argv = ["--ledger", str(ledger_file), "summary", "--json"]
    # main 은 stdout 에 JSON 을 출력하므로 capsys 로 잡습니다.
    # 여기서는 실행 성공(rc=0)과 JSON 유효성만 검사합니다.
    rc = main(argv)
    assert rc == 0


def test_summary_json_valid(ledger_file: Path, capsys: pytest.CaptureFixture) -> None:
    """--json 출력이 유효한 JSON 이며 roundtrips 의 유효 행 수가 정확합니다."""
    rows = [
        {
            "ledger_schema": LEDGER_SCHEMA,
            "recorded_at": "2026-08-15T09:00:00+09:00",
            "task_id": "t1",
            "dispatch_id": "d1",
            "role": "builder",
            "model": "m1",
            "capsule_chars": 1000,
            "report_chars": 500,
            "read_files_count": 2,
            "changed_files_count": 1,
            "roundtrips": None,
            "first_useful_seconds": None,
            "verdict": "succeeded",
            "status": "succeeded",
        },
        {
            "ledger_schema": LEDGER_SCHEMA,
            "recorded_at": "2026-08-15T10:00:00+09:00",
            "task_id": "t2",
            "dispatch_id": "d2",
            "role": "reviewer",
            "model": "m2",
            "capsule_chars": 2000,
            "report_chars": 700,
            "read_files_count": 4,
            "changed_files_count": 2,
            "roundtrips": 5,
            "first_useful_seconds": 120,
            "verdict": "succeeded",
            "status": "succeeded",
        },
    ]
    _write_raw_rows(ledger_file, rows)

    rc = main(["--ledger", str(ledger_file), "summary", "--json"])
    assert rc == 0

    captured = capsys.readouterr()
    data = json.loads(captured.out)

    # roundtrips: 행 2개 중 1개만 유효
    assert data["metrics"]["roundtrips"]["valid_count"] == 1
    assert data["metrics"]["roundtrips"]["total_count"] == 2


# --------------------------------------------------------------------------
# (5) 유효 행 0 인 지표는 중앙값이 null
# --------------------------------------------------------------------------


def test_median_is_null_when_no_valid_rows(ledger_file: Path) -> None:
    """roundtrips 가 모두 null 이면 중앙값이 null 이어야 합니다."""
    rows = [
        {
            "ledger_schema": LEDGER_SCHEMA,
            "recorded_at": "2026-08-15T09:00:00+09:00",
            "task_id": "t1",
            "dispatch_id": "d1",
            "role": "builder",
            "model": "m1",
            "capsule_chars": 500,
            "report_chars": 200,
            "read_files_count": 1,
            "changed_files_count": 1,
            "roundtrips": None,
            "verdict": "succeeded",
        }
    ]
    _write_raw_rows(ledger_file, rows)

    rc = main(["--ledger", str(ledger_file), "summary", "--json"])
    assert rc == 0


def test_median_or_null_returns_none_for_empty_list() -> None:
    assert _median_or_null([]) is None


def test_median_or_null_returns_value_for_nonempty_list() -> None:
    assert _median_or_null([1.0, 2.0, 3.0]) == 2.0


# --------------------------------------------------------------------------
# (6) 원장 파일이 없을 때 summary 가 행 0 으로 정상 종료
# --------------------------------------------------------------------------


def test_summary_no_ledger_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    nonexistent = tmp_path / "no_ledger.jsonl"
    rc = main(["--ledger", str(nonexistent), "summary"])
    assert rc == 0
    captured = capsys.readouterr()
    assert "0" in captured.out


def test_summary_no_ledger_json_exits_zero(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    nonexistent = tmp_path / "no_ledger.jsonl"
    rc = main(["--ledger", str(nonexistent), "summary", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_rows"] == 0


# --------------------------------------------------------------------------
# (7) 손상된 행이 개수로 보고됨
# --------------------------------------------------------------------------


def test_corrupt_rows_counted(ledger_file: Path, capsys: pytest.CaptureFixture) -> None:
    ledger_file.parent.mkdir(parents=True, exist_ok=True)
    with ledger_file.open("w", encoding="utf-8") as f:
        # 유효 행 1개
        f.write(
            json.dumps(
                {
                    "ledger_schema": LEDGER_SCHEMA,
                    "task_id": "t1",
                    "dispatch_id": "d1",
                    "recorded_at": "2026-08-15T09:00:00+09:00",
                    "role": "builder",
                    "model": "m1",
                    "capsule_chars": 100,
                    "report_chars": 50,
                }
            )
            + "\n"
        )
        # 손상 행 2개
        f.write("not valid json\n")
        f.write("{incomplete\n")

    rc = main(["--ledger", str(ledger_file), "summary", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["corrupt_rows"] == 2
    assert data["total_rows"] == 1


# --------------------------------------------------------------------------
# (8) --since 와 --role 필터가 동작함
# --------------------------------------------------------------------------


def test_since_filter(ledger_file: Path, capsys: pytest.CaptureFixture) -> None:
    rows = [
        {
            "ledger_schema": LEDGER_SCHEMA,
            "task_id": "t1",
            "dispatch_id": "d1",
            "recorded_at": "2026-01-01T00:00:00+09:00",
            "role": "builder",
            "model": "m1",
            "capsule_chars": 100,
            "report_chars": 50,
            "read_files_count": 1,
            "changed_files_count": 0,
        },
        {
            "ledger_schema": LEDGER_SCHEMA,
            "task_id": "t2",
            "dispatch_id": "d2",
            "recorded_at": "2026-08-15T00:00:00+09:00",
            "role": "builder",
            "model": "m1",
            "capsule_chars": 200,
            "report_chars": 100,
            "read_files_count": 2,
            "changed_files_count": 1,
        },
    ]
    _write_raw_rows(ledger_file, rows)

    rc = main(["--ledger", str(ledger_file), "summary", "--since", "2026-08-01", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_rows"] == 1


def test_role_filter(ledger_file: Path, capsys: pytest.CaptureFixture) -> None:
    rows = [
        {
            "ledger_schema": LEDGER_SCHEMA,
            "task_id": "t1",
            "dispatch_id": "d1",
            "recorded_at": "2026-08-15T09:00:00+09:00",
            "role": "builder",
            "model": "m1",
            "capsule_chars": 100,
            "report_chars": 50,
        },
        {
            "ledger_schema": LEDGER_SCHEMA,
            "task_id": "t2",
            "dispatch_id": "d2",
            "recorded_at": "2026-08-15T10:00:00+09:00",
            "role": "reviewer",
            "model": "m1",
            "capsule_chars": 200,
            "report_chars": 80,
        },
    ]
    _write_raw_rows(ledger_file, rows)

    rc = main(["--ledger", str(ledger_file), "summary", "--role", "reviewer", "--json"])
    assert rc == 0
    data = json.loads(capsys.readouterr().out)
    assert data["total_rows"] == 1
    assert "reviewer" in data["role_counts"]


# --------------------------------------------------------------------------
# (9) --json 출력이 유효한 JSON
# --------------------------------------------------------------------------


def test_record_json_output_is_valid(
    capsule_file: Path, report_file: Path, ledger_file: Path, capsys: pytest.CaptureFixture
) -> None:
    argv = [
        "--ledger",
        str(ledger_file),
        "record",
        "--run",
        "run_test123",
        "--task",
        "task_testABC",
        "--dispatch",
        "ctx_json001",
        "--role",
        "builder",
        "--model",
        "test-model",
        "--capsule",
        str(capsule_file),
        "--report",
        str(report_file),
        "--json",
    ]
    rc = main(argv)
    assert rc == 0
    captured = capsys.readouterr()
    data = json.loads(captured.out)
    assert data["task_id"] == "task_testABC"
    assert data["ledger_schema"] == LEDGER_SCHEMA


def test_default_ledger_path() -> None:
    """기본 원장 경로가 올바른 상수와 일치합니다."""
    parser = build_parser()
    args = parser.parse_args(["summary"])
    assert args.ledger == DEFAULT_LEDGER
