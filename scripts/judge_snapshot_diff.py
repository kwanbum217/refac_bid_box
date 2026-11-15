"""정량평가 규칙 변경 전후의 공고별 판정 스냅샷 덤프·비교 도구.

규칙을 바꾸기 전후에 같은 창의 공고 판정을 TSV 로 덤프하고, 두 덤프를 공고 키로
비교해 의도한 공고만 바뀌었는지 확인합니다. 판정 로직은 여기서 만들지 않고
scripts/report_rule_coverage.py 의 함수(collect 경로와 같은 SQL, split_by_latest_order,
_to_record, classify_result)를 그대로 씁니다.

사용법:

    uv run python scripts/judge_snapshot_diff.py dump --as-of 2026-11-15 --output /tmp/before.tsv
    uv run python scripts/judge_snapshot_diff.py dump --as-of 2026-11-15 --output /tmp/after.tsv
    uv run python scripts/judge_snapshot_diff.py diff /tmp/before.tsv /tmp/after.tsv

--expect 파일은 공고번호를 한 줄에 하나씩 적습니다. 실제로 바뀐 공고번호 집합과
정확히 같으면 0, 다르면 1 로 끝납니다. 한쪽 덤프에만 있는 공고도 바뀐 것으로 셉니다.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections.abc import Iterable
from datetime import date, datetime, timedelta
from datetime import time as day_time
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from sqlalchemy import Engine, text  # noqa: E402

from scripts import report_rule_coverage as coverage  # noqa: E402

SNAPSHOT_COLUMNS: tuple[str, ...] = (
    "scope",
    "rule_id",
    "block_code",
    "bid_ntce_no",
    "bid_ntce_ord",
    "dminstt_cd",
    "dminstt_nm",
)
KEY_COLUMNS: tuple[str, ...] = ("bid_ntce_no", "bid_ntce_ord")
CHANGE_COLUMNS: tuple[str, ...] = tuple(
    column for column in SNAPSHOT_COLUMNS if column not in KEY_COLUMNS
)
DEFAULT_MONTHS = 12
DEFAULT_CATEGORY = "Servc"
DEFAULT_METHOD_CODE = "낙030001"

SnapshotKey = tuple[str, str]
Snapshot = dict[SnapshotKey, dict[str, str]]


def collect_judgments(
    *,
    months: int,
    category: str,
    method_code: str,
    today: date | None = None,
    engine: Engine | None = None,
) -> list[dict[str, Any]]:
    """공고별 판정과 공고 키를 함께 모읍니다.

    report_rule_coverage.collect_records 는 판정 레코드에 공고번호를 남기지 않아 스냅샷
    키로 쓸 수 없습니다. 그래서 collect_records 와 같은 조회·판정 함수를 같은 순서로
    불러 레코드를 만들고 공고 키만 그 행에서 덧붙입니다. 세션은 collect_records 와 같이
    READ ONLY 로 열어 SELECT 만 씁니다.
    """
    if engine is None:
        from src.app.core.db import engine as default_engine

        engine = default_engine

    window_to = today or date.today()
    window_from = coverage._months_ago(window_to, months)
    window_end = window_to + timedelta(days=1)

    with engine.connect() as conn:
        conn.execute(text("SET SESSION TRANSACTION READ ONLY"))
        institutions = coverage._load_institutions(conn)
        statement = conn.execution_options(stream_results=True).execute(
            text(coverage.ANNOUNCEMENT_SQL),
            {
                "category": category,
                "window_from": datetime.combine(window_from, day_time.min),
                "window_end": datetime.combine(window_end, day_time.min),
            },
        )
        rows: Iterable[Any] = statement
        if method_code:
            rows = (
                row
                for row in statement
                if str(coverage._as_dict(row.raw_data).get("sucsfbidMthdCd") or "").strip()
                == method_code
            )
        latest_rows, _excluded = coverage.split_by_latest_order(rows)
        statement.close()
        regimes = coverage.lookup_attachment_regimes(
            conn, (coverage.attachment_regime_key(row) for row in latest_rows)
        )

    records: list[dict[str, Any]] = []
    for row in latest_rows:
        record = coverage._to_record(
            row, institutions, regimes.get(coverage.attachment_regime_key(row))
        )
        raw_data = coverage._as_dict(row.raw_data)
        record["bid_ntce_no"] = str(
            getattr(row, "bid_ntce_no", None) or raw_data.get("bidNtceNo") or ""
        )
        record["bid_ntce_ord"] = str(
            getattr(row, "bid_ntce_ord", None) or raw_data.get("bidNtceOrd") or ""
        )
        records.append(record)
    return records


def snapshot_row(record: dict[str, Any]) -> dict[str, str]:
    """판정 레코드 하나를 스냅샷 한 줄로 접습니다.

    차단 코드가 없는 오류 건은 block_code 자리에 예외 형식 이름을 적어 예외 종류가
    바뀐 것도 변경으로 잡습니다.
    """
    outcome = coverage.classify_result(record.get("result"), record.get("error_type"))
    block_code = outcome.block_code or ""
    if not block_code and outcome.applied_scope == coverage.LEDGER_SCOPE_ERROR:
        block_code = outcome.error_type or ""
    return {
        "scope": outcome.applied_scope,
        "rule_id": outcome.rule_id or "",
        "block_code": block_code,
        "bid_ntce_no": str(record.get("bid_ntce_no") or ""),
        "bid_ntce_ord": str(record.get("bid_ntce_ord") or ""),
        "dminstt_cd": str(record.get("dminstt_cd") or ""),
        "dminstt_nm": str(record.get("dminstt_nm") or ""),
    }


def build_snapshot(records: Iterable[dict[str, Any]]) -> list[dict[str, str]]:
    """레코드 목록을 공고번호·차수 순으로 정렬한 스냅샷 행으로 만듭니다."""
    rows = [snapshot_row(record) for record in records]
    rows.sort(key=lambda row: (row["bid_ntce_no"], row["bid_ntce_ord"]))
    return rows


def write_snapshot(path: str | Path, rows: Iterable[dict[str, str]]) -> None:
    """스냅샷을 TSV 로 씁니다. 줄바꿈은 LF 로 고정해 플랫폼 간 바이트를 맞춥니다."""
    output = Path(path)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(SNAPSHOT_COLUMNS),
            delimiter="\t",
            lineterminator="\n",
            extrasaction="ignore",
        )
        writer.writeheader()
        writer.writerows(rows)


def read_snapshot(path: str | Path) -> Snapshot:
    """스냅샷 TSV 를 공고 키 → 행 사전으로 읽습니다."""
    source = Path(path)
    with source.open(newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        missing = [column for column in SNAPSHOT_COLUMNS if column not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{source} 에 없는 열: {', '.join(missing)}")
        snapshot: Snapshot = {}
        for row in reader:
            key = (row["bid_ntce_no"] or "", row["bid_ntce_ord"] or "")
            snapshot[key] = {column: row.get(column) or "" for column in SNAPSHOT_COLUMNS}
    return snapshot


def _key_dict(key: SnapshotKey) -> dict[str, str]:
    return {"bid_ntce_no": key[0], "bid_ntce_ord": key[1]}


def diff_snapshots(before: Snapshot, after: Snapshot) -> dict[str, Any]:
    """두 스냅샷의 행 값 차이와 한쪽에만 있는 키를 모읍니다.

    changed_notices 는 내용이 바뀐 공고번호와 한쪽에만 있는 공고번호의 합집합입니다.
    """
    content_changed: list[dict[str, Any]] = []
    for key in sorted(set(before) & set(after)):
        changes = {
            column: {"before": before[key][column], "after": after[key][column]}
            for column in CHANGE_COLUMNS
            if before[key][column] != after[key][column]
        }
        if changes:
            content_changed.append({**_key_dict(key), "changes": changes})
    only_before = [_key_dict(key) for key in sorted(set(before) - set(after))]
    only_after = [_key_dict(key) for key in sorted(set(after) - set(before))]
    changed_notices = sorted(
        {item["bid_ntce_no"] for item in content_changed}
        | {item["bid_ntce_no"] for item in only_before}
        | {item["bid_ntce_no"] for item in only_after}
    )
    return {
        "counts": {
            "before_rows": len(before),
            "after_rows": len(after),
            "content_changed": len(content_changed),
            "only_before": len(only_before),
            "only_after": len(only_after),
            "changed_notices": len(changed_notices),
        },
        "changed_notices": changed_notices,
        "content_changed": content_changed,
        "only_before": only_before,
        "only_after": only_after,
    }


def load_expect(path: str | Path) -> set[str]:
    """--expect 파일을 공고번호 집합으로 읽습니다. 빈 줄은 건너뜁니다."""
    source = Path(path)
    if not source.is_file():
        raise FileNotFoundError(f"--expect 파일이 없습니다: {source}")
    return {
        line.strip() for line in source.read_text(encoding="utf-8").splitlines() if line.strip()
    }


def compare_expect(changed_notices: list[str], expect: set[str]) -> dict[str, Any]:
    """실제 변경 공고번호 집합과 --expect 집합을 비교합니다."""
    changed = set(changed_notices)
    missing = sorted(expect - changed)
    unexpected = sorted(changed - expect)
    return {
        "matched": not missing and not unexpected,
        "expected_count": len(expect),
        "changed_count": len(changed),
        "missing": missing,
        "unexpected": unexpected,
    }


def _show(value: str) -> str:
    return value or "-"


def _print_diff(result: dict[str, Any], expect_report: dict[str, Any] | None) -> None:
    counts = result["counts"]
    print(f"공고 before {counts['before_rows']}건, after {counts['after_rows']}건")
    print(
        f"바뀐 공고 {counts['changed_notices']}건"
        f"(판정 변경 {counts['content_changed']}건,"
        f" before 만 {counts['only_before']}건, after 만 {counts['only_after']}건)"
    )
    for item in result["content_changed"]:
        changes = "  ".join(
            f"{column}: {_show(change['before'])} -> {_show(change['after'])}"
            for column, change in item["changes"].items()
        )
        print(f"  [판정 변경] {item['bid_ntce_no']} {item['bid_ntce_ord']}  {changes}")
    for item in result["only_before"]:
        print(f"  [before 만] {item['bid_ntce_no']} {item['bid_ntce_ord']}")
    for item in result["only_after"]:
        print(f"  [after 만] {item['bid_ntce_no']} {item['bid_ntce_ord']}")
    if expect_report is None:
        return
    if expect_report["matched"]:
        print(f"[expect] 일치: {expect_report['changed_count']}건")
        return
    print(
        f"[expect] 불일치: 예상 {expect_report['expected_count']}건,"
        f" 실제 {expect_report['changed_count']}건"
    )
    for notice in expect_report["missing"]:
        print(f"  바뀌지 않은 예상: {notice}")
    for notice in expect_report["unexpected"]:
        print(f"  예상에 없는 변경: {notice}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="정량평가 판정 스냅샷 덤프·비교 도구")
    subparsers = parser.add_subparsers(dest="command", required=True)

    dump_parser = subparsers.add_parser("dump", help="최근 N개월 공고 판정을 TSV 로 씁니다")
    dump_parser.add_argument("--months", type=int, default=DEFAULT_MONTHS, help="조회 기간(개월)")
    dump_parser.add_argument("--category", default=DEFAULT_CATEGORY, help="업무구분")
    dump_parser.add_argument(
        "--method-code",
        default=DEFAULT_METHOD_CODE,
        help="낙찰방법 코드. 빈 문자열이면 필터하지 않습니다.",
    )
    dump_parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, help="기준일 YYYY-MM-DD. 없으면 오늘"
    )
    dump_parser.add_argument("--output", required=True, help="스냅샷 출력 경로")

    diff_parser = subparsers.add_parser("diff", help="두 TSV 를 공고 키로 비교합니다")
    diff_parser.add_argument("before", help="변경 전 스냅샷 TSV")
    diff_parser.add_argument("after", help="변경 후 스냅샷 TSV")
    diff_parser.add_argument(
        "--expect", default=None, help="바뀐 공고번호를 한 줄에 하나씩 적은 파일"
    )
    diff_parser.add_argument("--json", action="store_true", dest="as_json", help="JSON 출력")
    return parser


def _run_dump(args: argparse.Namespace) -> int:
    today = args.as_of or date.today()
    records = collect_judgments(
        months=args.months,
        category=args.category,
        method_code=args.method_code,
        today=today,
    )
    rows = build_snapshot(records)
    write_snapshot(args.output, rows)
    print(
        f"공고 {len(rows)}건을 썼습니다: {args.output} "
        f"(기준일 {today.isoformat()}, {args.months}개월, {args.category})"
    )
    return 0


def _run_diff(args: argparse.Namespace) -> int:
    try:
        before = read_snapshot(args.before)
        after = read_snapshot(args.after)
        expect = load_expect(args.expect) if args.expect else None
    except (OSError, ValueError) as exc:
        print(f"입력 파일을 읽지 못했습니다: {exc}", file=sys.stderr)
        return 2

    result = diff_snapshots(before, after)
    expect_report = (
        compare_expect(result["changed_notices"], expect) if expect is not None else None
    )
    if args.as_json:
        payload = {
            "before": Path(args.before).as_posix(),
            "after": Path(args.after).as_posix(),
            **result,
            "expect": expect_report,
        }
        print(json.dumps(payload, ensure_ascii=False, indent=2))
    else:
        _print_diff(result, expect_report)
    return 0 if expect_report is None or expect_report["matched"] else 1


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "dump":
        return _run_dump(args)
    return _run_diff(args)


if __name__ == "__main__":
    sys.exit(main())
