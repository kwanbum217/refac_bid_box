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

# 결측률이 이 값 이내로 0 또는 1 에 붙은 방법은 제도 속성으로 설명된 것으로 봅니다.
MIXED_TOLERANCE = 0.01


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


def split_by_explainability(stats: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """`missing_rate` 가 0 이나 1 에 붙은 그룹과 그 사이에 걸친 그룹을 가릅니다."""
    is_mixed = stats["missing_rate"].between(MIXED_TOLERANCE, 1 - MIXED_TOLERANCE)
    return stats[~is_mixed], stats[is_mixed]


def audit_training_frame(parquet: Path, top: int) -> None:
    """학습 데이터의 결측도 낙찰방법으로 설명되는지 봅니다.

    미개찰 공고만으로는 판정이 끝나지 않습니다. 예측 구간 폭 문제는 결과가 있는
    학습 모집단에서 관측된 것이고, 두 모집단은 낙찰방법 표기 관행이 다릅니다.

    방법명별 결측률이 0% 나 100% 에 붙어 있으면 그 방법의 제도 속성으로 설명됩니다.
    그 사이에 있는 그룹은 **같은 방법 안에서 어떤 공고는 값이 있고 어떤 공고는
    없다**는 뜻이므로 방법명으로 설명되지 않습니다.

    양 끝에 여유(`MIXED_TOLERANCE`)를 둡니다. 2만 8천 건 중 2건처럼 사실상 한쪽에
    붙은 그룹을 혼재로 세면 설명 불가 물량이 부풀려집니다.
    """
    df = pd.read_parquet(parquet, columns=["sucsfbid_mthd_nm", "lwlt_rate", "winning_rate"])
    df["missing"] = ~(df["lwlt_rate"].fillna(0) > 0)
    total_missing = int(df["missing"].sum())
    print(f"\n{'=' * 88}\n학습 데이터 {parquet.name}\n{'=' * 88}")
    print(f"전체 {len(df):,}행 / 결측 {total_missing:,}건 ({df['missing'].mean():.2%})")

    grouped = df.groupby("sucsfbid_mthd_nm", observed=True, dropna=False)
    stats = grouped["missing"].agg(["size", "sum", "mean"])
    stats.columns = ["notices", "missing", "missing_rate"]

    explained, mixed = split_by_explainability(stats)
    mixed_missing = int(mixed["missing"].sum())
    print(
        f"방법명으로 설명되는 결측 {int(explained['missing'].sum()):,}건 / "
        f"설명되지 않는 결측 {mixed_missing:,}건 "
        f"({mixed_missing / total_missing:.1%})"
        if total_missing
        else "결측이 없습니다."
    )

    if mixed.empty:
        return
    print("\n같은 방법명 안에서 보유와 결측이 섞인 그룹")
    view = mixed.sort_values("missing", ascending=False).head(top).copy()
    view["missing_rate"] = view["missing_rate"].map(lambda v: f"{v:.1%}")
    print(view.to_string())

    largest = mixed["missing"].idxmax()
    sub = df[df["sucsfbid_mthd_nm"] == largest]
    spread = sub.groupby("missing")["winning_rate"].agg(["count", "mean", "std"])
    print(f"\n최대 그룹 '{largest}' 의 낙찰률 분포 (False=하한율 보유)")
    print(spread.to_string())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default="2025-01-01")
    parser.add_argument("--top", type=int, default=30)
    parser.add_argument(
        "--parquet",
        default="data/feature_store/dataset_Servc.parquet",
        help="학습 데이터 결측 구조도 함께 감사합니다. 빈 값이면 건너뜁니다",
    )
    parser.add_argument("--skip-db", action="store_true", help="미개찰 공고 조회를 건너뜁니다")
    args = parser.parse_args()

    if not args.skip_db:
        print_report(load_unopened_coverage(args.since), args.top)
    if args.parquet:
        path = PROJECT_ROOT / args.parquet
        if path.exists():
            audit_training_frame(path, args.top)
        else:
            print(f"\n학습 데이터가 없어 건너뜁니다: {path}")


if __name__ == "__main__":
    main()
