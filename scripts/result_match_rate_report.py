"""
scripts/result_match_rate_report.py

개찰 완료 공고 대비 낙찰결과 매칭률 수동 조회 CLI (읽기 전용).

실행:
    uv run python scripts/result_match_rate_report.py
    uv run python scripts/result_match_rate_report.py --as-of 2026-09-27 --weeks 8 --format json
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.db import SessionLocal  # noqa: E402
from src.app.services.result_coverage import (  # noqa: E402
    compute_result_match_rates,
    evaluate_match_rate_alerts,
)

BAND_LABELS = {"large": "대형", "small": "소형"}


def _format_rate(rate: float | None) -> str:
    return f"{rate * 100:5.1f}%" if rate is not None else "   -  "


def _print_table(as_of: str, rows: list[dict[str, Any]], alerts: list[dict[str, Any]]) -> None:
    print(f"기준일 {as_of}")
    print(
        f"{'분류':<8}{'주시작':<12}{'규모':<6}"
        f"{'공고':>8}{'매칭':>8}{'매칭률':>10}"
        f"{'전년공고':>10}{'전년매칭률':>12}"
        f"{'보정률':>10}{'다주기저':>12}"
    )
    for row in rows:
        print(
            f"{row['category']:<8}{row['week_start']:<12}{BAND_LABELS.get(row['band'], row['band']):<6}"
            f"{row['announcements']:>8,}{row['matched']:>8,}{_format_rate(row['rate']):>10}"
            f"{row['baseline_announcements']:>10,}{_format_rate(row['baseline_rate']):>12}"
            f"{_format_rate(row['adjusted_rate']):>10}{_format_rate(row['baseline_multi_rate']):>12}"
        )

    if alerts:
        print()
        print("경고 대상:")
        for alert in alerts:
            print(
                f"  {alert['category']} {alert['week_start']} 주 대형: "
                f"보정 {_format_rate(alert['adjusted_rate'])} / "
                f"다주 기저 {_format_rate(alert['baseline_multi_rate'])}, 2주 연속 "
                f"(실측 {_format_rate(alert['rate'])} / 전년 {_format_rate(alert['baseline_rate'])})"
            )
    else:
        print()
        print("경고 대상 없음")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="낙찰결과 매칭률 조회")
    parser.add_argument("--as-of", type=str, default=None, help="기준일 YYYY-MM-DD (기본 오늘)")
    parser.add_argument("--weeks", type=int, default=8, help="조회할 최근 성숙 주 수 (기본 8)")
    parser.add_argument("--format", type=str, choices=("table", "json"), default="table")
    args = parser.parse_args(argv)

    as_of = date.fromisoformat(args.as_of) if args.as_of else date.today()
    db = SessionLocal()
    try:
        rows = compute_result_match_rates(db, as_of=as_of, weeks=args.weeks)
    finally:
        db.close()
    alerts = evaluate_match_rate_alerts(rows)

    if args.format == "json":
        print(
            json.dumps(
                {"as_of": as_of.isoformat(), "rows": rows, "alerts": alerts},
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        _print_table(as_of.isoformat(), rows, alerts)
    return 0


if __name__ == "__main__":
    sys.exit(main())
