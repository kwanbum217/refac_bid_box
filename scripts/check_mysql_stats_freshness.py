"""MySQL 영속 통계 신선도 점검 실행기 (읽기 전용).

대상 테이블의 영속 통계 행 수와 마지막 갱신 시각을 읽어 기준 행 수 대비
어긋난 비율과 갱신 경과일을 계산한다. 사람이 읽는 표와 --json 기계 판독을
모두 내며 종료 코드는 정상 0, 임계 초과 1, 도구 오류 2 이다.

판정 로직 단일 원천:
- 순수 판정 로직과 기본 임계는 src/app/services/mysql_stats_freshness.py 를 단일 원천으로 삼는다.
- 본 스크립트는 해당 서비스를 임포트하여 CLI 진입점 역할을 수행한다.

읽기 전용 보장:
- DB 조회는 scripts/db_readonly_query.py 의 검사와 실행 경로를 재사용한다.
  질의는 SELECT 두 문장뿐이며 파서 검사와 READ ONLY 트랜잭션을 그대로 탄다.
- 통계 갱신 명령(ANALYZE TABLE 등)을 포함한 어떤 쓰기도 실행하지 않으며 파일도 쓰지 않는다.
  결과는 표준출력으로만 낸다.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.services.mysql_stats_freshness import (  # noqa: E402
    DATETIME_FORMAT,
    DEFAULT_MAX_DRIFT_PCT,
    DEFAULT_MAX_STALE_DAYS,
    DEFAULT_TABLES,
    EXIT_ERROR,
    EXIT_OK,
    EXIT_STALE,
    NOW_QUERY,
    STATS_QUERY,
    build_payload,
    compute_age_days,
    compute_drift_pct,
    evaluate_all,
    evaluate_table,
    parse_expected_rows,
    parse_last_update,
    render_table,
)

__all__ = [
    "DATETIME_FORMAT",
    "DEFAULT_MAX_DRIFT_PCT",
    "DEFAULT_MAX_STALE_DAYS",
    "DEFAULT_TABLES",
    "EXIT_ERROR",
    "EXIT_OK",
    "EXIT_STALE",
    "NOW_QUERY",
    "STATS_QUERY",
    "build_payload",
    "compute_age_days",
    "compute_drift_pct",
    "evaluate_all",
    "evaluate_table",
    "fetch_stats",
    "main",
    "parse_expected_rows",
    "parse_last_update",
    "render_table",
]


def fetch_stats(
    tables: list[str] | tuple[str, ...],
) -> tuple[datetime, dict[str, tuple[int | None, datetime | None]]]:
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
    found: dict[str, tuple[int | None, datetime | None]] = {}
    for row in stats_rows:
        if str(row[name_idx]) in tables:
            found[str(row[name_idx])] = (
                int(row[nrows_idx]) if row[nrows_idx] is not None else None,
                parse_last_update(row[updated_idx]),
            )
    return now, {table: found.get(table, (None, None)) for table in tables}


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
