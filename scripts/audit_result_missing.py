#!/usr/bin/env python3
"""
나라장터 낙찰현황(용역 등)을 등록일시 구간으로 다시 조회해 bid_results 와 대조합니다.

2026-11-17 단건 확인에서 나라장터에는 낙찰자가 있으나 bid_results 에 없는 건이
발견되었습니다. 본 스크립트는 등록일시(inqryDiv=1) 기준으로 하루씩 API 를 다시
호출하고, (공고번호, 차수) 키로 DB 행과 맞춰 누락 규모를 셉니다.

읽기 전용입니다. DB 는 SELECT 만 하고 Redis 를 사용하지 않습니다.

사용법:
    python scripts/audit_result_missing.py --since 20261101 --until 20261117
    python scripts/audit_result_missing.py --since 20261101 --until 20261117 \\
        --category Servc --output-dir .cache/result_missing_audit
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidResult, normalize_bid_ntce_ord  # noqa: E402
from src.app.services import api_collector  # noqa: E402

PAGE_SIZE = 999
DB_KEY_CHUNK = 500
DEFAULT_OUTPUT_DIR = ".cache/result_missing_audit"
MISSING_TSV_COLUMNS = ("공고번호", "차수", "등록일시", "개찰일시", "낙찰업체명", "낙찰률")


@dataclass
class DayAudit:
    day: str
    status: str = "ok"
    api_count: int = 0
    db_matched: int = 0
    missing: list[dict[str, Any]] = field(default_factory=list)
    error: str = ""

    @property
    def missing_count(self) -> int:
        return len(self.missing)

    @property
    def missing_rate(self) -> float:
        return round(self.missing_count / self.api_count * 100, 4) if self.api_count else 0.0


def result_key(row: Mapping[str, Any]) -> tuple[str, str]:
    """API 행과 DB 행을 맞출 키. 차수는 0 패딩만 정규화합니다."""
    return (
        str(row.get("bid_ntce_no") or ""),
        normalize_bid_ntce_ord(row.get("bid_ntce_ord")),
    )


def load_db_result_keys(
    session: Session, category: str, bid_ntce_nos: Sequence[str]
) -> set[tuple[str, str]]:
    """해당 카테고리·공고번호의 bid_results 키를 SELECT 만으로 읽습니다."""
    keys: set[tuple[str, str]] = set()
    unique_numbers = sorted({number for number in bid_ntce_nos if number})
    for idx in range(0, len(unique_numbers), DB_KEY_CHUNK):
        chunk = unique_numbers[idx : idx + DB_KEY_CHUNK]
        statement = select(BidResult.bid_ntce_no, BidResult.bid_ntce_ord).where(
            BidResult.category == category,
            BidResult.bid_ntce_no.in_(chunk),
        )
        for bid_ntce_no, bid_ntce_ord in session.execute(statement):
            keys.add((bid_ntce_no, normalize_bid_ntce_ord(bid_ntce_ord)))
    return keys


async def _fetch_day(
    day: str,
    category: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
) -> list[dict[str, Any]]:
    return await api_collector._fetch_paged(
        client,
        api_collector.BID_CATEGORIES[category]["bid_url"],
        day,
        day,
        PAGE_SIZE,
        api_collector._map_result_item(category),
        "낙찰정보",
        sem,
        inqry_div="1",
    )


async def audit_day(
    day: str,
    category: str,
    client: httpx.AsyncClient,
    sem: asyncio.Semaphore,
    session: Session,
) -> DayAudit:
    try:
        rows = await _fetch_day(day, category, client, sem)
        db_keys = load_db_result_keys(
            session, category, [str(row.get("bid_ntce_no") or "") for row in rows]
        )
    except Exception as exc:
        return DayAudit(
            day=day,
            status="failed",
            error=api_collector.mask_credentials(str(exc)),
        )

    missing = [row for row in rows if result_key(row) not in db_keys]
    missing.sort(key=lambda row: (result_key(row), str(row.get("bidwinnr_nm") or "")))
    return DayAudit(
        day=day,
        api_count=len(rows),
        db_matched=len(rows) - len(missing),
        missing=missing,
    )


def _iter_days(since: date, until: date) -> list[date]:
    return [since + timedelta(days=offset) for offset in range((until - since).days + 1)]


def _totals(audits: Sequence[DayAudit]) -> dict[str, Any]:
    api_count = sum(audit.api_count for audit in audits if audit.status == "ok")
    db_matched = sum(audit.db_matched for audit in audits if audit.status == "ok")
    missing = sum(audit.missing_count for audit in audits if audit.status == "ok")
    return {
        "api_count": api_count,
        "db_matched": db_matched,
        "missing": missing,
        "missing_rate": round(missing / api_count * 100, 4) if api_count else 0.0,
        "failed_days": sum(1 for audit in audits if audit.status == "failed"),
    }


def build_summary(
    audits: Sequence[DayAudit], category: str, since: date, until: date
) -> dict[str, Any]:
    days: list[dict[str, Any]] = []
    for audit in audits:
        entry: dict[str, Any] = {"date": audit.day, "status": audit.status}
        if audit.status == "failed":
            entry["error"] = audit.error
        else:
            entry["api_count"] = audit.api_count
            entry["db_matched"] = audit.db_matched
            entry["missing"] = audit.missing_count
            entry["missing_rate"] = audit.missing_rate
        days.append(entry)
    return {
        "category": category,
        "since": since.strftime("%Y%m%d"),
        "until": until.strftime("%Y%m%d"),
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "days": days,
        "totals": _totals(audits),
    }


def _registration_text(day: str, row: Mapping[str, Any]) -> str:
    raw_data = row.get("raw_data")
    if isinstance(raw_data, Mapping):
        value = raw_data.get("bidNtceDt")
        if value:
            return str(value)
    return day


def _format_rate(value: Any) -> str:
    if value is None:
        return ""
    return f"{float(value):g}"


def missing_tsv_row(day: str, row: Mapping[str, Any]) -> list[str]:
    opened = row.get("rl_openg_dt")
    opened_text = opened.strftime("%Y-%m-%d %H:%M:%S") if isinstance(opened, datetime) else ""
    return [
        str(row.get("bid_ntce_no") or ""),
        str(row.get("bid_ntce_ord") or ""),
        _registration_text(day, row),
        opened_text,
        str(row.get("bidwinnr_nm") or ""),
        _format_rate(row.get("sucsf_bid_rate")),
    ]


def write_outputs(
    audits: Sequence[DayAudit],
    category: str,
    since: date,
    until: date,
    output_dir: Path,
) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(audits, category, since, until)
    (output_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    with (output_dir / "missing.tsv").open("w", encoding="utf-8", newline="") as handle:
        writer = csv.writer(handle, delimiter="\t", lineterminator="\n")
        writer.writerow(MISSING_TSV_COLUMNS)
        for audit in audits:
            for row in audit.missing:
                writer.writerow(missing_tsv_row(audit.day, row))


def _print_report(audits: Sequence[DayAudit]) -> None:
    print(f"{'일자':<10}{'API':>10}{'DB일치':>10}{'누락':>8}{'누락률':>10}  상태")
    for audit in audits:
        if audit.status == "failed":
            print(f"{audit.day:<10}{'-':>10}{'-':>10}{'-':>8}{'-':>10}  failed")
            print(f"  실패: {audit.error}", file=sys.stderr)
        else:
            print(
                f"{audit.day:<10}{audit.api_count:>10,}{audit.db_matched:>10,}"
                f"{audit.missing_count:>8,}{audit.missing_rate:>9.2f}%  ok"
            )
    totals = _totals(audits)
    print("-" * 62)
    print(
        f"{'합계':<10}{totals['api_count']:>10,}{totals['db_matched']:>10,}"
        f"{totals['missing']:>8,}{totals['missing_rate']:>9.2f}%"
    )
    if totals["failed_days"]:
        print(f"실패 일자 {totals['failed_days']}일", file=sys.stderr)


async def run_audit(
    *,
    since: date,
    until: date,
    category: str,
    session: Session,
    output_dir: Path,
) -> int:
    audits: list[DayAudit] = []
    sem = asyncio.Semaphore(api_collector.MAX_CONCURRENT)
    async with httpx.AsyncClient() as client:
        for day in _iter_days(since, until):
            audits.append(await audit_day(day.strftime("%Y%m%d"), category, client, sem, session))

    write_outputs(audits, category, since, until, output_dir)
    _print_report(audits)
    return 1 if any(audit.status == "failed" for audit in audits) else 0


def _parse_day(value: str) -> date:
    return datetime.strptime(value, "%Y%m%d").date()


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="낙찰 결과 누락 점검 (읽기 전용)")
    parser.add_argument("--since", required=True, help="시작일 YYYYMMDD")
    parser.add_argument("--until", required=True, help="종료일 YYYYMMDD (포함)")
    parser.add_argument(
        "--category",
        default="Servc",
        choices=list(api_collector.BID_CATEGORIES),
        help="업무구분 (기본 Servc)",
    )
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="출력 디렉토리")
    args = parser.parse_args(argv)

    try:
        since = _parse_day(args.since)
        until = _parse_day(args.until)
    except ValueError:
        print("FAIL: --since/--until 은 YYYYMMDD 형식이어야 합니다", file=sys.stderr)
        return 2
    if since > until:
        print("FAIL: --since 가 --until 보다 늦습니다", file=sys.stderr)
        return 2

    if not api_collector.get_service_key():
        print("FAIL: G2B serviceKey 가 설정되지 않았습니다 (.env 확인)", file=sys.stderr)
        return 1

    session = SessionLocal()
    try:
        return asyncio.run(
            run_audit(
                since=since,
                until=until,
                category=args.category,
                session=session,
                output_dir=Path(args.output_dir),
            )
        )
    finally:
        session.close()


if __name__ == "__main__":
    sys.exit(main())
