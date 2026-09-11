"""MySQL 영속 통계 신선도 판정 및 점검 서비스 (단일 원천).

대상 테이블의 영속 통계 행 수와 마지막 갱신 시각을 읽어 실제 행 수(또는 기준 행 수) 대비
어긋난 비율과 갱신 경과일을 계산하고 신선도를 판정한다.

읽기 전용 보장:
- ANALYZE TABLE, OPTIMIZE TABLE 등 어떤 통계 갱신 및 쓰기 명령도 실행하지 않는다.
- 오직 영속 통계 메타데이터(mysql.innodb_table_stats) 및 현재 시각, 행 수 카운트만 읽는다.
- 감지만 자동화하고 갱신은 운영자/사람의 승인에 맡긴다.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from src.app.models.bids import BidAnnouncement, BidResult

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_STALE = 1
EXIT_ERROR = 2

DEFAULT_TABLES: tuple[str, ...] = ("bid_results", "bid_announcements")

DEFAULT_MAX_DRIFT_PCT = 25.0
DEFAULT_MAX_STALE_DAYS = 3.0

STATS_QUERY = (
    "SELECT table_name, last_update, n_rows "
    "FROM mysql.innodb_table_stats WHERE database_name = DATABASE()"
)
NOW_QUERY = "SELECT NOW() AS now"

DATETIME_FORMAT = "%Y-%m-%d %H:%M:%S"

TABLE_MODEL_MAP = {
    "bid_results": BidResult,
    "bid_announcements": BidAnnouncement,
}


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
    max_drift_pct: float = DEFAULT_MAX_DRIFT_PCT,
    max_stale_days: float = DEFAULT_MAX_STALE_DAYS,
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


def evaluate_all(
    tables: list[str] | tuple[str, ...],
    fetched: dict[str, tuple[int | None, datetime | None]],
    expected: dict[str, int],
    now: datetime,
    max_drift_pct: float = DEFAULT_MAX_DRIFT_PCT,
    max_stale_days: float = DEFAULT_MAX_STALE_DAYS,
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


def build_payload(
    results: list[dict[str, Any]],
    max_drift_pct: float = DEFAULT_MAX_DRIFT_PCT,
    max_stale_days: float = DEFAULT_MAX_STALE_DAYS,
    exit_code: int = EXIT_OK,
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


def fetch_live_row_counts(
    db: Session,
    tables: tuple[str, ...] | list[str] = DEFAULT_TABLES,
) -> dict[str, int]:
    """대상 테이블의 실제 행 수를 읽는다.

    하드코딩하지 않고 실측 질의로 행 수를 센다.
    """
    counts: dict[str, int] = {}
    for table_name in tables:
        model = TABLE_MODEL_MAP.get(table_name)
        if model is None:
            raise ValueError(f"지원되지 않는 테이블명입니다: {table_name}")
        count = db.scalar(select(func.count()).select_from(model))
        counts[table_name] = int(count or 0)
    return counts


def fetch_innodb_stats(
    db: Session,
    tables: tuple[str, ...] | list[str] = DEFAULT_TABLES,
) -> tuple[datetime, dict[str, tuple[int | None, datetime | None]]]:
    """mysql.innodb_table_stats 와 DB 시각을 읽는다."""
    now_raw = db.execute(text(NOW_QUERY)).scalar()
    now = parse_last_update(now_raw)
    if now is None:
        now = now_raw if isinstance(now_raw, datetime) else datetime.now()

    rows = db.execute(text(STATS_QUERY)).mappings().all()
    found: dict[str, tuple[int | None, datetime | None]] = {}
    for row in rows:
        t_name = str(row["table_name"])
        if t_name in tables:
            found[t_name] = (
                int(row["n_rows"]) if row["n_rows"] is not None else None,
                parse_last_update(row["last_update"]),
            )
    result_map = {table: found.get(table, (None, None)) for table in tables}
    return now, result_map


def check_mysql_stats_freshness(
    db: Session,
    tables: tuple[str, ...] | list[str] = DEFAULT_TABLES,
    max_drift_pct: float = DEFAULT_MAX_DRIFT_PCT,
    max_stale_days: float = DEFAULT_MAX_STALE_DAYS,
) -> dict[str, Any]:
    """DB 세션을 받아 실제 행 수와 영속 통계를 읽고 신선도를 점검한다 (읽기 전용).

    어떤 통계 갱신(ANALYZE TABLE 등)도 실행하지 않는다.
    기준 행 수는 하드코딩하지 않고 실제 행 수를 측정하여 사용한다.
    """
    now, fetched = fetch_innodb_stats(db, tables)
    actual_counts = fetch_live_row_counts(db, tables)

    results = evaluate_all(
        tables=tables,
        fetched=fetched,
        expected=actual_counts,
        now=now,
        max_drift_pct=max_drift_pct,
        max_stale_days=max_stale_days,
    )
    stale = any(item["stale"] for item in results)
    exit_code = EXIT_STALE if stale else EXIT_OK
    payload = build_payload(
        results=results,
        max_drift_pct=max_drift_pct,
        max_stale_days=max_stale_days,
        exit_code=exit_code,
    )
    payload["status"] = "success"
    payload["checked_at"] = now.strftime(DATETIME_FORMAT)
    return payload


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
    "TABLE_MODEL_MAP",
    "build_payload",
    "check_mysql_stats_freshness",
    "compute_age_days",
    "compute_drift_pct",
    "evaluate_all",
    "evaluate_table",
    "fetch_innodb_stats",
    "fetch_live_row_counts",
    "parse_expected_rows",
    "parse_last_update",
    "render_table",
]
