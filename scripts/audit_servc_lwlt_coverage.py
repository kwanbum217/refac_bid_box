#!/usr/bin/env python3
"""미개찰 용역 공고의 낙찰하한율 가용성을 제도 구간별로 측정합니다."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import pandas as pd
from sqlalchemy import text

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.app.core.db import engine  # noqa: E402

LOWER_LIMIT_METHOD_MARKERS = ("적격심사", "낙찰하한율", "소액수의견적")


def requires_lower_limit(method: object) -> bool:
    value = str(method or "")
    return any(marker in value for marker in LOWER_LIMIT_METHOD_MARKERS)


def load_unopened_coverage(since: str) -> pd.DataFrame:
    sql = text(
        """
        SELECT
            COALESCE(
                NULLIF(JSON_UNQUOTE(JSON_EXTRACT(
                    a.raw_data, '$.prearngPrceDcsnMthdNm'
                )), ''),
                '(없음)'
            ) AS prearng_mthd,
            COALESCE(
                NULLIF(JSON_UNQUOTE(JSON_EXTRACT(
                    a.raw_data, '$.sucsfbidMthdNm'
                )), ''),
                '(없음)'
            ) AS sucsfbid_mthd,
            COALESCE(a.cntrct_mthd_nm, '(없음)') AS cntrct_mthd,
            COALESCE(
                NULLIF(JSON_UNQUOTE(JSON_EXTRACT(
                    a.raw_data, '$.srvceDivNm'
                )), ''),
                '(없음)'
            ) AS srvce_div,
            COUNT(*) AS notices,
            SUM(CASE WHEN CAST(
                NULLIF(JSON_UNQUOTE(JSON_EXTRACT(
                    a.raw_data, '$.sucsfbidLwltRate'
                )), '') AS DECIMAL(10, 4)
            ) > 0 THEN 1 ELSE 0 END) AS has_lwlt
        FROM bid_announcements a
        LEFT JOIN bid_results r
          ON a.bid_ntce_no = r.bid_ntce_no
         AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
         AND a.category = r.category
        WHERE a.category = 'Servc'
          AND r.id IS NULL
          AND a.bid_ntce_dt >= :since
        GROUP BY prearng_mthd, sucsfbid_mthd, cntrct_mthd, srvce_div
        ORDER BY notices DESC
        """
    )
    return pd.read_sql(sql, engine, params={"since": since})


def print_report(frame: pd.DataFrame, top: int) -> None:
    if frame.empty:
        print("조건에 맞는 미개찰 용역 공고가 없습니다.")
        return

    frame = frame.copy()
    frame["missing_lwlt"] = frame["notices"] - frame["has_lwlt"]
    frame["coverage"] = frame["has_lwlt"] / frame["notices"]
    frame["requires_lwlt"] = frame["sucsfbid_mthd"].map(requires_lower_limit)
    total = int(frame["notices"].sum())
    has_lwlt = int(frame["has_lwlt"].sum())
    print(
        f"전체 {total:,}건 / 하한율 보유 {has_lwlt:,}건 "
        f"({has_lwlt / total:.2%}) / 결측 {total - has_lwlt:,}건"
    )

    required = frame[frame["requires_lwlt"]]
    required_total = int(required["notices"].sum())
    required_has = int(required["has_lwlt"].sum())
    required_missing = required_total - required_has
    print(
        f"하한율 명시 방식 {required_total:,}건 / 보유 {required_has:,}건 "
        f"({required_has / required_total:.2%}) / 실제 누락 {required_missing:,}건"
        if required_total
        else "하한율 명시 방식 공고가 없습니다."
    )
    print(f"그 외 방식 {total - required_total:,}건")

    columns = [
        "prearng_mthd",
        "sucsfbid_mthd",
        "cntrct_mthd",
        "srvce_div",
        "notices",
        "has_lwlt",
        "missing_lwlt",
        "coverage",
        "requires_lwlt",
    ]
    print(frame.loc[:, columns].head(top).to_string(index=False))

    missing = frame[frame["missing_lwlt"] > 0]
    by_method = (
        missing.groupby("sucsfbid_mthd", as_index=False)["missing_lwlt"]
        .sum()
        .sort_values("missing_lwlt", ascending=False)
    )
    print("\n결측 상위 낙찰방법")
    print(by_method.head(top).to_string(index=False))

    actionable = required[required["missing_lwlt"] > 0]
    print("\n하한율 명시 방식 중 실제 누락")
    if actionable.empty:
        print("없음")
    else:
        print(actionable.loc[:, columns].head(top).to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2025-01-01")
    parser.add_argument("--top", type=int, default=30)
    args = parser.parse_args()
    print_report(load_unopened_coverage(args.since), args.top)


if __name__ == "__main__":
    main()
