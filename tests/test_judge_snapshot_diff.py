"""정량평가 판정 스냅샷 덤프·비교 도구 시험 (DB 없이).

diff 는 tmp_path 의 작은 TSV 로, dump 는 수집 함수와 DB 접근을 가짜로 바꾼 입력으로
검사합니다. 검사 항목: 정렬·결정성, 변경 검출, 한쪽 키 차이 보고, --expect 종료 코드,
--json 출력 형식, READ ONLY 조회.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from scripts import judge_snapshot_diff as script
from src.app.services.evaluation_rules import (
    RULE_SCOPE_ALL,
    EvaluationRule,
    RuleResolutionResult,
)


def _rule(rule_id: str = "R_PPS") -> EvaluationRule:
    return EvaluationRule(
        rule_id=rule_id,
        service_type="GENERAL",
        table_name="시험 별표",
        description="시험용",
        effective_date="2020-01-01",
        source="시험",
        patterns=(),
        lwlt_rate=Decimal("80"),
        institution_scope=RULE_SCOPE_ALL,
    )


def _pps_result() -> RuleResolutionResult:
    return RuleResolutionResult(is_blocked=False, rule=_rule())


def _record(
    bid_ntce_no: str,
    bid_ntce_ord: str = "00",
    *,
    result: RuleResolutionResult | None = None,
    error_type: str | None = None,
    dminstt_cd: str = "A",
    dminstt_nm: str = "기관A",
) -> dict[str, Any]:
    return {
        "bid_ntce_no": bid_ntce_no,
        "bid_ntce_ord": bid_ntce_ord,
        "dminstt_cd": dminstt_cd,
        "dminstt_nm": dminstt_nm,
        "result": _pps_result() if result is None and error_type is None else result,
        "error_type": error_type,
    }


def _snapshot_row(bid_ntce_no: str, bid_ntce_ord: str = "00", **overrides: str) -> dict[str, str]:
    row = {
        "scope": "PPS_DEFAULT",
        "rule_id": "R_PPS",
        "block_code": "",
        "bid_ntce_no": bid_ntce_no,
        "bid_ntce_ord": bid_ntce_ord,
        "dminstt_cd": "A",
        "dminstt_nm": "기관A",
    }
    row.update(overrides)
    return row


def _write_snapshot(path: Path, rows: list[dict[str, str]]) -> None:
    lines = ["\t".join(script.SNAPSHOT_COLUMNS)]
    lines.extend("\t".join(row[column] for column in script.SNAPSHOT_COLUMNS) for row in rows)
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


class _FakeAnnouncement:
    def __init__(self, bid_ntce_no: str, bid_ntce_ord: str, method_code: str = "낙030001") -> None:
        self.bid_ntce_no = bid_ntce_no
        self.bid_ntce_ord = bid_ntce_ord
        self.category = "Servc"
        self.dminstt_nm = "기관A"
        self.cntrct_mthd_nm = "일반경쟁"
        self.presmpt_prce = None
        self.raw_data = {
            "bidNtceNo": bid_ntce_no,
            "bidNtceOrd": bid_ntce_ord,
            "sucsfbidMthdCd": method_code,
        }


class _FakeResult:
    def __init__(self, rows: list[Any]) -> None:
        self._rows = rows

    def mappings(self) -> _FakeResult:
        return self

    def all(self) -> list[Any]:
        return self._rows

    def execution_options(self, **_kwargs: Any) -> _FakeResult:
        return self

    def close(self) -> None:
        return None

    def __iter__(self) -> Any:
        return iter(self._rows)


class _FakeConnection:
    def __init__(self, announcement_rows: list[Any]) -> None:
        self._announcement_rows = announcement_rows
        self.statements: list[str] = []

    def execute(self, statement: Any, params: Any = None) -> _FakeResult:
        sql = str(statement)
        self.statements.append(sql)
        if "g2b_demand_institutions" in sql:
            return _FakeResult([])
        return _FakeResult(self._announcement_rows)

    def execution_options(self, **_kwargs: Any) -> _FakeConnection:
        return self

    def __enter__(self) -> _FakeConnection:
        return self

    def __exit__(self, *exc_info: Any) -> bool:
        return False


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self._connection = connection

    def connect(self) -> _FakeConnection:
        return self._connection


def test_dump_sorts_rows_and_repeats_byte_for_byte(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    records = [
        _record("R26BK0002", "00"),
        _record("R26BK0001", "01"),
        _record("R26BK0001", "00"),
    ]
    monkeypatch.setattr(script, "collect_judgments", lambda **kwargs: records)
    first = tmp_path / "first.tsv"
    second = tmp_path / "second.tsv"

    assert script.main(["dump", "--output", str(first)]) == 0
    assert script.main(["dump", "--output", str(second)]) == 0

    assert first.read_bytes() == second.read_bytes()
    lines = first.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "\t".join(script.SNAPSHOT_COLUMNS)
    assert [tuple(line.split("\t")[3:5]) for line in lines[1:]] == [
        ("R26BK0001", "00"),
        ("R26BK0001", "01"),
        ("R26BK0002", "00"),
    ]


def test_dump_writes_scope_rule_and_block_code(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    blocked = RuleResolutionResult(is_blocked=True, block_reason_code="MANUAL_EVALUATION")
    records = [
        _record("R26BK0001", dminstt_cd="A", dminstt_nm="기관A"),
        _record("R26BK0002", result=blocked, dminstt_cd="B", dminstt_nm="기관B"),
        _record("R26BK0003", result=None, error_type="ValueError", dminstt_cd="C"),
    ]
    monkeypatch.setattr(script, "collect_judgments", lambda **kwargs: records)
    output = tmp_path / "snapshot.tsv"

    assert script.main(["dump", "--output", str(output)]) == 0

    rows = [line.split("\t") for line in output.read_text(encoding="utf-8").splitlines()[1:]]
    assert rows[0][:3] == ["PPS_DEFAULT", "R_PPS", ""]
    assert rows[1][:3] == ["BLOCKED", "", "MANUAL_EVALUATION"]
    assert rows[2][:3] == ["ERROR", "", "ValueError"]
    assert [row[5] for row in rows] == ["A", "B", "C"]


def test_dump_passes_window_and_defaults_to_today(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    seen: list[dict[str, Any]] = []

    def fake(**kwargs: Any) -> list[Any]:
        seen.append(kwargs)
        return []

    monkeypatch.setattr(script, "collect_judgments", fake)

    assert script.main(["dump", "--as-of", "2026-11-15", "--output", str(tmp_path / "a.tsv")]) == 0
    assert script.main(["dump", "--output", str(tmp_path / "b.tsv")]) == 0

    assert seen[0]["today"] == date(2026, 11, 15)
    assert seen[0]["months"] == 12
    assert seen[0]["category"] == "Servc"
    assert seen[0]["method_code"] == "낙030001"
    assert seen[1]["today"] == date.today()


def test_collect_judgments_reads_read_only_and_keeps_latest_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    connection = _FakeConnection(
        [
            _FakeAnnouncement("R26BK0001", "00"),
            _FakeAnnouncement("R26BK0001", "01"),
            _FakeAnnouncement("R26BK0002", "00", method_code="낙030002"),
        ]
    )
    monkeypatch.setattr(script.coverage, "lookup_attachment_regimes", lambda db, keys: {})

    collected = script.collect_judgments(
        months=12,
        category="Servc",
        method_code="낙030001",
        today=date(2026, 11, 15),
        engine=_FakeEngine(connection),
    )

    assert any("SET SESSION TRANSACTION READ ONLY" in item for item in connection.statements)
    assert [row["bid_ntce_no"] for row in collected] == ["R26BK0001"]
    assert [row["bid_ntce_ord"] for row in collected] == ["01"]
    assert any("FROM bid_announcements" in item for item in connection.statements)


def test_diff_reports_content_change(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    _write_snapshot(before, [_snapshot_row("R26BK0001"), _snapshot_row("R26BK0002")])
    _write_snapshot(
        after,
        [
            _snapshot_row("R26BK0001", scope="BLOCKED", rule_id="", block_code="RULE_NOT_FOUND"),
            _snapshot_row("R26BK0002"),
        ],
    )

    assert script.main(["diff", str(before), str(after)]) == 0

    output = capsys.readouterr().out
    assert "바뀐 공고 1건" in output
    assert "R26BK0001" in output
    assert "scope: PPS_DEFAULT -> BLOCKED" in output
    assert "R26BK0002" not in output


def test_diff_reports_no_change(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    rows = [_snapshot_row("R26BK0001"), _snapshot_row("R26BK0002")]
    _write_snapshot(before, rows)
    _write_snapshot(after, rows)

    assert script.main(["diff", str(before), str(after)]) == 0

    assert "바뀐 공고 0건" in capsys.readouterr().out


def test_diff_reports_one_sided_keys(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    _write_snapshot(before, [_snapshot_row("R26BK0001"), _snapshot_row("R26BK0002")])
    _write_snapshot(after, [_snapshot_row("R26BK0002"), _snapshot_row("R26BK0003")])

    assert script.main(["diff", str(before), str(after)]) == 0

    output = capsys.readouterr().out
    assert "바뀐 공고 2건" in output
    assert "before 만 1건, after 만 1건" in output
    assert "[before 만] R26BK0001 00" in output
    assert "[after 만] R26BK0003 00" in output


def test_diff_expect_matches_changed_notices(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    expect = tmp_path / "expect.txt"
    _write_snapshot(before, [_snapshot_row("R26BK0001"), _snapshot_row("R26BK0002")])
    _write_snapshot(after, [_snapshot_row("R26BK0001", scope="REGION"), _snapshot_row("R26BK0002")])
    expect.write_text("R26BK0001\n", encoding="utf-8")

    assert script.main(["diff", str(before), str(after), "--expect", str(expect)]) == 0

    assert "[expect] 일치: 1건" in capsys.readouterr().out


def test_diff_expect_counts_one_sided_keys(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    expect = tmp_path / "expect.txt"
    _write_snapshot(before, [_snapshot_row("R26BK0001")])
    _write_snapshot(after, [])
    expect.write_text("R26BK0001\n", encoding="utf-8")

    assert script.main(["diff", str(before), str(after), "--expect", str(expect)]) == 0


def test_diff_expect_missing_notice_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    expect = tmp_path / "expect.txt"
    _write_snapshot(before, [_snapshot_row("R26BK0001")])
    _write_snapshot(after, [_snapshot_row("R26BK0001", scope="REGION")])
    expect.write_text("R26BK0001\nR26BK0009\n", encoding="utf-8")

    assert script.main(["diff", str(before), str(after), "--expect", str(expect)]) == 1

    output = capsys.readouterr().out
    assert "[expect] 불일치" in output
    assert "바뀌지 않은 예상: R26BK0009" in output


def test_diff_expect_unexpected_change_exits_one(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    expect = tmp_path / "expect.txt"
    _write_snapshot(before, [_snapshot_row("R26BK0001")])
    _write_snapshot(after, [_snapshot_row("R26BK0001", scope="REGION")])
    expect.write_text("R26BK0009\n", encoding="utf-8")

    assert script.main(["diff", str(before), str(after), "--expect", str(expect)]) == 1

    assert "예상에 없는 변경: R26BK0001" in capsys.readouterr().out


def test_diff_expect_empty_with_change_exits_one(tmp_path: Path) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    expect = tmp_path / "expect.txt"
    _write_snapshot(before, [_snapshot_row("R26BK0001")])
    _write_snapshot(after, [_snapshot_row("R26BK0001", scope="REGION")])
    expect.write_text("", encoding="utf-8")

    assert script.main(["diff", str(before), str(after), "--expect", str(expect)]) == 1


def test_diff_expect_empty_without_change_exits_zero(tmp_path: Path) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    expect = tmp_path / "expect.txt"
    _write_snapshot(before, [_snapshot_row("R26BK0001")])
    _write_snapshot(after, [_snapshot_row("R26BK0001")])
    expect.write_text("\n\n", encoding="utf-8")

    assert script.main(["diff", str(before), str(after), "--expect", str(expect)]) == 0


def test_diff_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    expect = tmp_path / "expect.txt"
    _write_snapshot(before, [_snapshot_row("R26BK0001")])
    _write_snapshot(
        after,
        [_snapshot_row("R26BK0001", scope="BLOCKED", rule_id="", block_code="RULE_NOT_FOUND")],
    )
    expect.write_text("R26BK0001\n", encoding="utf-8")

    assert script.main(["diff", str(before), str(after), "--expect", str(expect), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["before"] == before.as_posix()
    assert payload["after"] == after.as_posix()
    assert payload["counts"]["changed_notices"] == 1
    assert payload["changed_notices"] == ["R26BK0001"]
    assert payload["content_changed"][0]["changes"]["block_code"] == {
        "before": "",
        "after": "RULE_NOT_FOUND",
    }
    assert payload["expect"]["matched"] is True
    assert payload["expect"]["missing"] == []


def test_diff_json_without_expect_is_zero(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tmp_path / "before.tsv"
    after = tmp_path / "after.tsv"
    _write_snapshot(before, [_snapshot_row("R26BK0001")])
    _write_snapshot(after, [_snapshot_row("R26BK0001", scope="REGION")])

    assert script.main(["diff", str(before), str(after), "--json"]) == 0

    payload = json.loads(capsys.readouterr().out)
    assert payload["expect"] is None


def test_diff_missing_expect_file_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    before = tmp_path / "before.tsv"
    _write_snapshot(before, [_snapshot_row("R26BK0001")])

    assert (
        script.main(["diff", str(before), str(before), "--expect", str(tmp_path / "missing.txt")])
        == 2
    )

    assert "--expect 파일이 없습니다" in capsys.readouterr().err


def test_diff_snapshot_missing_column_returns_two(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    broken = tmp_path / "broken.tsv"
    broken.write_text("bid_ntce_no\tbid_ntce_ord\nR26BK0001\t00\n", encoding="utf-8")

    assert script.main(["diff", str(broken), str(broken)]) == 2

    assert "없는 열" in capsys.readouterr().err
