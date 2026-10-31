#!/usr/bin/env python3
"""
scripts/backfill_openg_results.py

나라장터 개찰결과(유찰 상태 포함) 기간 소급 수집 스크립트.

기본은 dry-run 입니다. `--execute` 를 명시할 때만 외부 API 호출과 적재를 합니다.
지정 기간을 `--window-days`(기본 7일) 창으로 나눠 공사·물품·용역 개찰결과를
수집하고, T3 의 upsert 적재를 재사용해 같은 창을 다시 돌려도 행이 늘지 않게
합니다. 창별 결과는 JSON 원장에 남기며, 재실행 시 성공한 창은 건너뛰고
실패·중단된 창만 다시 시도합니다.

`--max-calls` 는 창 단위 호출 상한입니다. 창 하나는 최소 1회 호출이며 실제
요청 수는 응답 페이지 수만큼 늘어납니다. 승인 트래픽 단위가 확정되지 않았으므로
보수적으로 잡으십시오.

서비스 키 값은 코드·원장·표준출력에 기록하지 않습니다.

실행:
    uv run python scripts/backfill_openg_results.py --max-calls 400
    uv run python scripts/backfill_openg_results.py --start 20251031 --end 20261031 --max-calls 400
    uv run python scripts/backfill_openg_results.py --start 20251031 --end 20261031 --max-calls 400 --execute

설계 정본: docs/analysis/fail_bid_collection_design_20261031.md 5.3·8장 T4.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from collections.abc import Sequence
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.core.timeutil import utcnow  # noqa: E402
from src.app.models.openg_results import BidOpengResult  # noqa: E402
from src.app.services.api_collector import (  # noqa: E402
    BID_CATEGORIES,
    OPENG_RESULT_URLS,
    RangeCollectionError,
    get_service_key,
    mask_credentials,
    stream_openg_results,
)
from src.app.services.collector_service import _upsert_openg_results  # noqa: E402

DEFAULT_WINDOW_DAYS = 7
DEFAULT_MAX_CALLS = 400
DEFAULT_CATEGORIES = ("공사", "물품", "용역")
DEFAULT_LEDGER_PATH = PROJECT_ROOT / ".cache" / "openg_backfill_ledger.json"

LEDGER_SCHEMA = "OPENG_BACKFILL_LEDGER_V1"
STATUS_SUCCESS = "success"
STATUS_FAILED = "failed"
STATUS_SKIPPED = "skipped"

Window = tuple[date, date]


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="개찰결과(유찰 포함) 기간 소급 수집 (기본 dry-run)",
    )
    parser.add_argument("--start", help="시작일 YYYYMMDD. 기본 오늘 기준 1년 전")
    parser.add_argument("--end", help="종료일 YYYYMMDD. 기본 오늘")
    parser.add_argument(
        "--window-days",
        type=int,
        default=DEFAULT_WINDOW_DAYS,
        help=f"창 크기(일). 기본 {DEFAULT_WINDOW_DAYS}",
    )
    parser.add_argument(
        "--categories",
        nargs="+",
        default=list(DEFAULT_CATEGORIES),
        metavar="CATEGORY",
        help="수집 분류. 코드(Cnstwk|Thng|Servc) 또는 이름(공사|물품|용역). 기본 공사 물품 용역",
    )
    parser.add_argument(
        "--max-calls",
        type=int,
        required=True,
        help="창 단위 호출 상한. 초과하면 남은 창을 원장에 skipped 로 남기고 중단합니다",
    )
    parser.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=True,
        help="창 목록과 예상 호출 수만 출력합니다. 기본값",
    )
    parser.add_argument(
        "--execute",
        dest="dry_run",
        action="store_false",
        help="실제 API 호출과 적재를 수행합니다",
    )
    parser.add_argument(
        "--ledger",
        type=Path,
        default=DEFAULT_LEDGER_PATH,
        help=f"창별 실패 원장 JSON 경로. 기본 {DEFAULT_LEDGER_PATH.relative_to(PROJECT_ROOT)}",
    )
    return parser


def split_windows(start: date, end: date, window_days: int) -> list[Window]:
    """기간을 `window_days` 일 창으로 나눕니다. 마지막 창은 남은 날짜만 담습니다."""
    if window_days < 1:
        raise ValueError("--window-days 는 1 이상이어야 합니다")
    if start > end:
        raise ValueError(f"시작일 {start} 이 종료일 {end} 보다 늦습니다")

    windows: list[Window] = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=window_days - 1), end)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def load_ledger(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"schema": LEDGER_SCHEMA, "updated_at": None, "windows": {}}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"원장 파일을 읽을 수 없습니다: {path}: {exc}") from exc

    if not isinstance(data, dict) or not isinstance(data.get("windows"), dict):
        raise ValueError(f"원장 파일 형식이 올바르지 않습니다: {path}")
    if data.get("schema") != LEDGER_SCHEMA:
        raise ValueError(f"원장 스키마가 다릅니다: {path} ({data.get('schema')!r})")
    return data


def save_ledger(path: Path, ledger: dict[str, Any]) -> None:
    """창 하나를 처리할 때마다 원장을 원자적으로 다시 씁니다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    ledger["updated_at"] = utcnow().isoformat(timespec="seconds")
    temp_path = path.with_name(path.name + ".tmp")
    temp_path.write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temp_path.replace(path)


def _window_key(category: str, window: Window) -> str:
    start, end = window
    return f"{category}|{start:%Y%m%d}|{end:%Y%m%d}"


def _ledger_entry(ledger: dict[str, Any], category: str, window: Window) -> dict[str, Any]:
    key = _window_key(category, window)
    entry = ledger["windows"].get(key)
    if entry is None:
        start, end = window
        entry = {
            "category": category,
            "start": f"{start:%Y%m%d}",
            "end": f"{end:%Y%m%d}",
            "status": STATUS_SKIPPED,
            "rows": 0,
            "error": "",
            "attempts": 0,
            "updated_at": None,
        }
        ledger["windows"][key] = entry
    return entry


def _record(
    ledger: dict[str, Any],
    category: str,
    window: Window,
    status: str,
    *,
    rows: int | None = None,
    error: str = "",
    attempted: bool = False,
) -> None:
    entry = _ledger_entry(ledger, category, window)
    if attempted:
        entry["attempts"] = int(entry.get("attempts") or 0) + 1
    entry["status"] = status
    if rows is not None:
        entry["rows"] = rows
    entry["error"] = error
    entry["updated_at"] = utcnow().isoformat(timespec="seconds")


def status_distribution(db: Session, start: date, end: date) -> dict[str, int]:
    """요청 기간의 개찰결과를 `progrs_div_cd_nm` 별로 집계합니다."""
    begin = datetime.combine(start, time.min)
    finish = datetime.combine(end + timedelta(days=1), time.min)
    stmt = (
        select(BidOpengResult.progrs_div_cd_nm, func.count())
        .where(BidOpengResult.openg_dt >= begin, BidOpengResult.openg_dt < finish)
        .group_by(BidOpengResult.progrs_div_cd_nm)
        .order_by(func.count().desc(), BidOpengResult.progrs_div_cd_nm)
    )
    return {(name or ""): int(count) for name, count in db.execute(stmt)}


def _resolve_categories(values: Sequence[str]) -> tuple[str, ...]:
    name_to_code = {
        info["name"]: code for code, info in BID_CATEGORIES.items() if code in OPENG_RESULT_URLS
    }
    resolved: list[str] = []
    for value in values:
        code = value if value in OPENG_RESULT_URLS else name_to_code.get(value)
        if code is None:
            raise ValueError(
                f"지원하지 않는 분류입니다: {value} (사용 가능: 공사, 물품, 용역 / Cnstwk, Thng, Servc)"
            )
        if code not in resolved:
            resolved.append(code)
    if not resolved:
        raise ValueError("수집할 분류가 하나도 없습니다")
    return tuple(resolved)


def _resolve_period(start_value: str | None, end_value: str | None) -> tuple[date, date]:
    today = utcnow().date()
    try:
        start = (
            datetime.strptime(start_value, "%Y%m%d").date()
            if start_value
            else today - timedelta(days=365)
        )
        end = datetime.strptime(end_value, "%Y%m%d").date() if end_value else today
    except ValueError as exc:
        raise ValueError(f"날짜는 YYYYMMDD 형식이어야 합니다: {exc}") from exc
    if start > end:
        raise ValueError(f"시작일 {start} 이 종료일 {end} 보다 늦습니다")
    return start, end


def _print_report(
    *,
    start: date,
    end: date,
    summary: dict[str, Any],
    ledger_path: Path,
    max_calls: int,
) -> None:
    print("-" * 60)
    print(f"적재 기간: {start:%Y-%m-%d} ~ {end:%Y-%m-%d}")
    print(f"원장: {ledger_path}")
    print(
        f"창 처리: 성공 {summary['succeeded']} / 실패 {summary['failed']} "
        f"/ 건너뜀 {summary['skipped']} (호출 {summary['calls_used']}회, 상한 {max_calls}회)"
    )
    print(f"이번 실행 적재: {summary['rows_upserted']:,}건")
    print(f"기간 내 적재 행 수: {summary['rows_in_range']:,}건")
    distribution = summary["distribution"]
    if distribution:
        print("progrs_div_cd_nm 분포:")
        for name, count in distribution.items():
            print(f"  - {name or '(빈 값)'}: {count:,}건")
    else:
        print("progrs_div_cd_nm 분포: 데이터 없음")


async def run_backfill(
    db: Session,
    *,
    start: date,
    end: date,
    categories: tuple[str, ...],
    window_days: int = DEFAULT_WINDOW_DAYS,
    max_calls: int = DEFAULT_MAX_CALLS,
    dry_run: bool = True,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
) -> dict[str, Any]:
    """기간을 창으로 나눠 개찰결과를 수집·적재하고 원장과 요약을 돌려줍니다."""
    if max_calls < 1:
        raise ValueError("--max-calls 는 1 이상이어야 합니다")

    windows = split_windows(start, end, window_days)
    planned_calls = len(windows) * len(categories)
    summary: dict[str, Any] = {
        "status": "dry_run" if dry_run else "success",
        "window_count": len(windows),
        "planned_windows": planned_calls,
        "estimated_calls": planned_calls,
        "calls_used": 0,
        "succeeded": 0,
        "failed": 0,
        "skipped": 0,
        "rows_upserted": 0,
        "rows_in_range": 0,
        "distribution": {},
    }

    span_days = (end - start).days + 1
    print(
        f"대상 기간: {start:%Y-%m-%d} ~ {end:%Y-%m-%d} ({span_days}일), "
        f"창 {len(windows)}개 x 분류 {len(categories)}개"
    )
    if dry_run:
        for window_start, window_end in windows:
            print(f"  - {window_start:%Y-%m-%d} ~ {window_end:%Y-%m-%d}")
        print(f"예상 호출 수(창 단위 최소): {planned_calls}회")
        if planned_calls > max_calls:
            print(
                f"주의: 예상 호출 수가 --max-calls {max_calls} 를 넘습니다. "
                "--execute 시 상한에서 중단되고 남은 창은 원장에 skipped 로 남습니다."
            )
        print("dry-run 입니다. 외부 호출과 DB 적재는 --execute 를 명시해야 수행합니다.")
        return summary

    if not get_service_key():
        print("FAIL: G2B serviceKey 가 설정되지 않았습니다 (.env 확인)", file=sys.stderr)
        summary["status"] = "error"
        return summary

    ledger = load_ledger(ledger_path)
    truncated = False
    stop = False

    for category in categories:
        if stop:
            break
        for window in windows:
            window_start, window_end = window

            if _ledger_entry(ledger, category, window).get("status") == STATUS_SUCCESS:
                summary["skipped"] += 1
                continue

            if summary["calls_used"] >= max_calls:
                _record(
                    ledger,
                    category,
                    window,
                    STATUS_SKIPPED,
                    error=f"max-calls 상한({max_calls}) 도달",
                )
                summary["skipped"] += 1
                truncated = True
                stop = True
                continue

            summary["calls_used"] += 1
            label = f"[{category}] {window_start:%Y%m%d}~{window_end:%Y%m%d}"
            try:
                saved = await stream_openg_results(
                    f"{window_start:%Y%m%d}",
                    f"{window_end:%Y%m%d}",
                    lambda rows: _upsert_openg_results(db, rows),
                    category=category,
                )
            except RangeCollectionError as exc:
                error = mask_credentials(exc)
                _record(
                    ledger,
                    category,
                    window,
                    STATUS_FAILED,
                    rows=exc.saved,
                    error=error,
                    attempted=True,
                )
                summary["failed"] += 1
                summary["rows_upserted"] += exc.saved
                print(f"  {label}: 실패 (부분 적재 {exc.saved:,}건) {error}", file=sys.stderr)
            except Exception as exc:  # 창 단위 실패를 원장에 남기고 계속합니다
                error = mask_credentials(exc)
                _record(
                    ledger,
                    category,
                    window,
                    STATUS_FAILED,
                    error=error,
                    attempted=True,
                )
                summary["failed"] += 1
                print(f"  {label}: 실패 {error}", file=sys.stderr)
            else:
                _record(
                    ledger,
                    category,
                    window,
                    STATUS_SUCCESS,
                    rows=saved,
                    attempted=True,
                )
                summary["succeeded"] += 1
                summary["rows_upserted"] += saved
                print(f"  {label}: 적재 {saved:,}건")
            save_ledger(ledger_path, ledger)

    save_ledger(ledger_path, ledger)
    summary["distribution"] = status_distribution(db, start, end)
    summary["rows_in_range"] = sum(summary["distribution"].values())

    if truncated:
        summary["status"] = "truncated"
    elif summary["failed"]:
        summary["status"] = "partial_success"

    _print_report(
        start=start,
        end=end,
        summary=summary,
        ledger_path=ledger_path,
        max_calls=max_calls,
    )
    return summary


def run(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        start, end = _resolve_period(args.start, args.end)
        categories = _resolve_categories(args.categories)
        split_windows(start, end, args.window_days)
        if args.max_calls < 1:
            raise ValueError("--max-calls 는 1 이상이어야 합니다")
    except ValueError as exc:
        print(f"입력 오류: {exc}", file=sys.stderr)
        return 2

    session = SessionLocal()
    try:
        summary = asyncio.run(
            run_backfill(
                session,
                start=start,
                end=end,
                categories=categories,
                window_days=args.window_days,
                max_calls=args.max_calls,
                dry_run=args.dry_run,
                ledger_path=args.ledger,
            )
        )
    finally:
        session.close()

    if summary["status"] in ("error", "partial_success", "truncated"):
        return 1
    return 0


def main(argv: Sequence[str] | None = None) -> int:
    return run(argv)


if __name__ == "__main__":
    raise SystemExit(main())
