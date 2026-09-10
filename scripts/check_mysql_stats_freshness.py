"""MySQL 영속 통계 신선도 점검 실행기 (읽기 전용).

대상 테이블의 영속 통계 행 수와 마지막 갱신 시각을 읽어 기준 행 수 대비
어긋난 비율과 갱신 경과일을 계산한다. 사람이 읽는 표와 --json 기계 판독을
모두 내며 종료 코드는 정상 0, 임계 초과 1, 도구 오류 2 이다.

읽기 전용 보장:
- DB 조회는 scripts/db_readonly_query.py 의 검사와 실행 경로를 재사용한다.
  질의는 SELECT 두 문장뿐이며 파서 검사와 READ ONLY 트랜잭션을 그대로 탄다.
- 통계 갱신 명령을 포함한 어떤 쓰기도 실행하지 않으며 파일도 쓰지 않는다.
  결과는 표준출력으로만 낸다.
- 재사용을 직접 임포트 대신 조회 경로에서 지연 임포트로 하는 이유는
  그 모듈의 임포트가 DB 설정을 요구해 단위 테스트까지 DB 의존이 번지는 것을
  막기 위함이다. 판정 로직은 DB 없이 검증한다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXIT_OK = 0
EXIT_STALE = 1
EXIT_ERROR = 2

DEFAULT_TABLES = ("bid_results", "bid_announcements")

# 기본 임계 근거는 docs/ops/mysql_statistics_refresh_policy_20260911.md 3절이다.
# 편차 25%: 표본 추정 잡음을 상회한다. 2026-09-11 갱신 직후에도 공고 테이블
# 통계는 실제 대비 15.9% 과대였고 자동 재계산 임계는 10% 이다. 25% 면 잡음에
# 오탐 없이 실제 방치 규모(이 공식으로 58.3%)를 확실히 검출한다.
# 경과 3일: 수집 크론이 매일 02:00 에 적재하므로 사흘 연속 미갱신이면
# 드리프트가 누적되는 구조이다. 열흘 방치를 사흘째에 검출한다.
DEFAULT_MAX_DRIFT_PCT = 25.0
DEFAULT_MAX_STALE_DAYS = 3.0

STATS_QUERY = (
    "SELECT table_name, last_update, n_rows "
    "FROM mysql.innodb_table_stats WHERE database_name = DATABASE()"
)
NOW_QUERY = "SELECT NOW() AS now"

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"


def parse_expected_rows(spec: str) -> dict[str, int]:
    """기준 행 수 지정을 테이블별 딕셔너리로 바꾼다."""
    parsed: dict[str, int] = {}
    for item in spec.split(","):
        name, sep, value = item.partition("=")
        name = name.strip()
        value = value.strip()
        if not sep or not name or not value:
            raise ValueError(f"기준 행 수 형식이 잘못됐습니다: {item!r}")
        try:
            count = int(value)
        except ValueError:
            raise ValueError(f"기준 행 수가 정수가 아닙니다: {item!r}") from None
        if count < 0:
            raise ValueError(f"기준 행 수는 음수일 수 없습니다: {item!r}")
        parsed[name] = count
    if not parsed:
        raise ValueError("기준 행 수가 비어 있습니다.")
    return parsed


def compute_drift_pct(stats_rows: int, expected_rows: int | None) -> float | None:
    """통계 행 수와 기준 행 수의 어긋난 비율을 낸다."""
    if expected_rows is None or expected_rows <= 0:
        return None
    return abs(stats_rows - expected_rows) / expected_rows * 100.0


def compute_age_days(last_update: datetime, now: datetime) -> float:
    """마지막 갱신으로부터 경과일을 낸다."""
    return (now - last_update).total_seconds() / 86400.0


def parse_last_update(value: Any) -> datetime | None:
    """DB 에서 온 갱신 시각을 datetime 으로 바꾼다."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value.strip(), DATETIME_FORMAT)
        except ValueError:
            return None
    return None


def evaluate_table(
    table: str,
    stats_rows: int | None,
    last_update: datetime | None,
    expected_rows: int | None,
    now: datetime,
    max_drift_pct: float,
    max_stale_days: float,
) -> dict[str, Any]:
    """테이블 하나의 신선도를 판정한다."""
    if stats_rows is None or last_update is None:
        return {
            "table": table,
            "stats_rows": stats_rows,
            "expected_rows": expected_rows,
            "drift_pct": None,
            "last_update": None,
            "age_days": None,
            "status": "MISSING",
            "reason": "영속 통계 행이 없어 정상으로 볼 수 없습니다.",
            "stale": True,
        }
    drift_pct = compute_drift_pct(stats_rows, expected_rows)
    age_days = compute_age_days(last_update, now)
    reasons: list[str] = []
    if drift_pct is not None and drift_pct > max_drift_pct:
        reasons.append(f"편차 {drift_pct:.1f}% 가 임계 {max_drift_pct:.1f}% 초과")
    if age_days > max_stale_days:
        reasons.append(f"경과 {age_days:.1f}일 이 임계 {max_stale_days:.1f}일 초과")
    stale = bool(reasons)
    return {
        "table": table,
        "stats_rows": stats_rows,
        "expected_rows": expected_rows,
        "drift_pct": drift_pct,
        "last_update": last_update.strftime(DATETIME_FORMAT),
        "age_days": age_days,
        "status": "STALE" if stale else "OK",
        "reason": "; ".join(reasons) if reasons else "임계 이내입니다.",
        "stale": stale,
    }


def fetch_stats(
    tables: list[str],
) -> tuple[datetime, dict[str, tuple[int, datetime | None]]]:
    """영속 통계와 DB 시각을 읽는다. SELECT 두 문장만 쓴다."""
    from scripts.db_readonly_query import assert_read_only, run_query

    now_columns, now_rows = run_query(assert_read_only(NOW_QUERY), 1)
    now = parse_last_update(now_rows[0][now_columns.index("now")])
    if now is None:
        raise RuntimeError("DB 시각을 읽지 못했습니다.")

    stats_columns, stats_rows = run_query(assert_read_only(STATS_QUERY), 0)
    name_idx = stats_columns.index("table_name")
    updated_idx = stats_columns.index("last_update")
    nrows_idx = stats_columns.index("n_rows")
    found: dict[str, tuple[int, datetime | None]] = {}
    for row in stats_rows:
        if str(row[name_idx]) in tables:
            found[str(row[name_idx])] = (
                int(row[nrows_idx]),
                parse_last_update(row[updated_idx]),
            )
    return now, {table: found.get(table, (None, None)) for table in tables}  # type: ignore[dict-item]


def render_table(results: list[dict[str, Any]]) -> str:
    """사람이 읽는 표를 낸다."""
    headers = ["테이블", "통계행수", "기준행수", "편차%", "마지막갱신", "경과일", "판정"]
    rows: list[list[str]] = []
    for item in results:
        drift = item["drift_pct"]
        age = item["age_days"]
        rows.append(
            [
                str(item["table"]),
                str(item["stats_rows"]),
                str(item["expected_rows"]),
                f"{drift:.1f}" if drift is not None else "-",
                str(item["last_update"]),
                f"{age:.1f}" if age is not None else "-",
                str(item["status"]),
            ]
        )
    widths = [len(h) for h in headers]
    for row in rows:
        for i, value in enumerate(row):
            widths[i] = max(widths[i], len(value))
    lines = [" | ".join(h.ljust(widths[i]) for i, h in enumerate(headers))]
    lines.append("-+-".join("-" * w for w in widths))
    for row in rows:
        lines.append(" | ".join(v.ljust(widths[i]) for i, v in enumerate(row)))
    for item in results:
        if item["stale"]:
            lines.append(f"[{item['table']}] {item['reason']}")
    return "\n".join(lines)


def build_payload(
    results: list[dict[str, Any]],
    max_drift_pct: float,
    max_stale_days: float,
    exit_code: int,
) -> dict[str, Any]:
    """기계 판독용 구조를 낸다."""
    return {
        "thresholds": {
            "max_drift_pct": max_drift_pct,
            "max_stale_days": max_stale_days,
        },
        "tables": results,
        "stale": any(item["stale"] for item in results),
        "exit_code": exit_code,
    }


def evaluate_all(
    tables: list[str],
    fetched: dict[str, tuple[int | None, datetime | None]],
    expected: dict[str, int],
    now: datetime,
    max_drift_pct: float,
    max_stale_days: float,
) -> list[dict[str, Any]]:
    """조회 결과를 판정 목록으로 바꾼다."""
    return [
        evaluate_table(
            table,
            stats_rows,
            last_update,
            expected.get(table),
            now,
            max_drift_pct,
            max_stale_days,
        )
        for table, (stats_rows, last_update) in fetched.items()
    ]


def main(argv: list[str] | None = None) -> int:
    """진입점. 정상 0, 임계 초과 1, 도구 오류 2 를 돌려준다."""
    parser = argparse.ArgumentParser(description="MySQL 영속 통계 신선도 점검 (읽기 전용)")
    parser.add_argument(
        "--tables",
        default=",".join(DEFAULT_TABLES),
        help=f"점검 대상 테이블 (콤마 구분, 기본 {','.join(DEFAULT_TABLES)})",
    )
    parser.add_argument(
        "--expected-rows",
        default="",
        help="기준 행 수 (예: bid_results=3431580,bid_announcements=5504119). "
        "없으면 편차율은 계산하지 않고 경과일로만 판정한다.",
    )
    parser.add_argument(
        "--max-drift-pct",
        type=float,
        default=DEFAULT_MAX_DRIFT_PCT,
        help=f"편차율 임계 (기본 {DEFAULT_MAX_DRIFT_PCT})",
    )
    parser.add_argument(
        "--max-stale-days",
        type=float,
        default=DEFAULT_MAX_STALE_DAYS,
        help=f"경과일 임계 (기본 {DEFAULT_MAX_STALE_DAYS})",
    )
    parser.add_argument("--json", action="store_true", help="기계 판독용 JSON 출력")
    args = parser.parse_args(argv)

    tables = [name.strip() for name in args.tables.split(",") if name.strip()]
    if not tables:
        print("대상 테이블이 비어 있습니다.", file=sys.stderr)
        return EXIT_ERROR
    if args.max_drift_pct < 0 or args.max_stale_days < 0:
        print("임계는 음수일 수 없습니다.", file=sys.stderr)
        return EXIT_ERROR
    try:
        expected = parse_expected_rows(args.expected_rows) if args.expected_rows else {}
    except ValueError as exc:
        print(f"기준 행 수 오류: {exc}", file=sys.stderr)
        return EXIT_ERROR

    try:
        now, fetched = fetch_stats(tables)
    except Exception as exc:
        print(f"조회 실패: {exc}", file=sys.stderr)
        return EXIT_ERROR

    results = evaluate_all(tables, fetched, expected, now, args.max_drift_pct, args.max_stale_days)
    exit_code = EXIT_STALE if any(item["stale"] for item in results) else EXIT_OK
    if args.json:
        print(
            json.dumps(
                build_payload(results, args.max_drift_pct, args.max_stale_days, exit_code),
                ensure_ascii=False,
            )
        )
    else:
        print(render_table(results))
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
