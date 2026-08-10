#!/usr/bin/env python3
"""용역 낙찰하한율 결측의 메커니즘을 예가방식과 낙찰방법으로 분해합니다.

`servc_lwlt_availability_20260804.md` 는 결측의 76.8% 가 방법명으로 설명되지
않는다고 판정했습니다. 그 판정은 `sucsfbid_mthd_nm` 을 근거로 삼았는데, 이
컬럼은 2024년 이전 전량이 `공고서참조` 라 아무 정보를 담고 있지 않습니다.
"같은 방법명 안에서 79.4% 가 값을 갖는다" 는 근거는 방법이 같다는 뜻이 아니라
방법을 모른다는 뜻이었습니다.

이 스크립트는 두 축으로 다시 분해합니다.

    prearng_mthd        예가방식. 단일예가·비예가는 하한율이 존재하지 않습니다
    sucsfbid_mthd_nm    낙찰방법. 2025년부터만 유효합니다

과거 구간은 방법명을 못 쓰므로, 낙찰률 분포가 최근 구간과 같은지로 같은
메커니즘인지 판정합니다.

사용법:
    .venv/bin/python scripts/audit_servc_lwlt_mechanism.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402

# 낙찰하한율이 제도상 존재하지 않는 낙찰방법 계열입니다. 예정가격 이하 최저가나
# 협상·종합평가로 낙찰자를 정하므로 하한선 개념이 없습니다.
NON_LWLT_METHODS = (
    "규격가격동시입찰",
    "협상에의한계약",
    "종합심사낙찰제",
    "최저가낙찰제",
    "2단계경쟁입찰",
    "안전점검수행기관지정",
    "수의시담",
)

# 낙찰방법 컬럼이 실제 방법을 담기 시작한 해입니다. 그 이전은 전량 `공고서참조`.
METHOD_VALID_YEAR = 2025

COLUMNS = ["openg_dt", "winning_rate", "lwlt_rate", "prearng_mthd", "sucsfbid_mthd_nm"]


def load(path: Path) -> pd.DataFrame:
    frame = pd.read_parquet(path, columns=COLUMNS)
    frame["openg_dt"] = pd.to_datetime(frame["openg_dt"], errors="coerce")
    frame["yr"] = frame["openg_dt"].dt.year
    frame["miss"] = frame["lwlt_rate"].isna()
    return frame


def describe(series: pd.Series) -> str:
    if series.empty:
        return "표본 없음"
    return (
        f"n={len(series):>7,} 평균={series.mean():7.3f} SD={series.std():6.3f} "
        f"중앙={series.median():7.3f} p95={series.quantile(0.95):7.3f}"
    )


def report_method_column(frame: pd.DataFrame) -> None:
    print("\n== 낙찰방법 컬럼이 정보를 담기 시작한 시점 ==")
    table = frame.groupby("yr").apply(
        lambda part: pd.Series(
            {
                "건수": len(part),
                "공고서참조%": (part["sucsfbid_mthd_nm"] == "공고서참조").mean() * 100,
                "결측%": part["miss"].mean() * 100,
            }
        ),
        include_groups=False,
    )
    print(table.round(2).to_string())
    print(
        f"\n{METHOD_VALID_YEAR}년 이전은 낙찰방법이 전량 `공고서참조` 입니다. "
        "이 구간에서 방법명은 판정 근거가 될 수 없습니다."
    )


def report_prearng(frame: pd.DataFrame) -> pd.DataFrame:
    total_missing = int(frame["miss"].sum())
    print("\n== 예가방식별 결측 구성 ==")
    grouped = frame.groupby("prearng_mthd", observed=True).agg(
        행수=("miss", "size"), 결측=("miss", "sum")
    )
    grouped["결측률%"] = (grouped["결측"] / grouped["행수"] * 100).round(2)
    grouped["전체결측중%"] = (grouped["결측"] / total_missing * 100).round(2)
    print(grouped.to_string())

    print("\n== 예가방식별 연도 결측률(%) ==")
    pivot = (
        frame.pivot_table(index="yr", columns="prearng_mthd", values="miss", aggfunc="mean") * 100
    )
    print(pivot.round(1).to_string())
    print(
        "\n비예가는 10년 내내 100%, 단일예가는 84~99% 입니다. 제도 구조이지 "
        "수집 누락이 아닙니다."
    )
    return grouped


def report_multi_prearng(frame: pd.DataFrame) -> None:
    multi = frame[frame["prearng_mthd"] == "복수예가"]
    total_missing = int(frame["miss"].sum())
    print("\n== 복수예가 내부 (유일한 잔여 후보) ==")
    print(
        f"행수 {len(multi):,} / 결측 {int(multi['miss'].sum()):,} "
        f"({multi['miss'].mean() * 100:.2f}%) / 전체 결측 대비 "
        f"{multi['miss'].sum() / total_missing * 100:.2f}%"
    )

    print("\n-- 낙찰률 분포로 본 구·신 구간 동일성 --")
    for label, mask in [
        ("구 결측(~2024)", (multi["yr"] < METHOD_VALID_YEAR) & multi["miss"]),
        ("신 결측(2025~)", (multi["yr"] >= METHOD_VALID_YEAR) & multi["miss"]),
        ("구 보유(~2024)", (multi["yr"] < METHOD_VALID_YEAR) & ~multi["miss"]),
        ("신 보유(2025~)", (multi["yr"] >= METHOD_VALID_YEAR) & ~multi["miss"]),
    ]:
        print(f"{label:14} {describe(multi[mask]['winning_rate'])}")

    recent = multi[(multi["yr"] >= METHOD_VALID_YEAR) & multi["miss"]]
    is_non_lwlt = recent["sucsfbid_mthd_nm"].astype(str).str.startswith(NON_LWLT_METHODS)
    print(
        f"\n{METHOD_VALID_YEAR}년 이후 복수예가 결측 {len(recent):,}건 중 "
        f"하한율 비적용 방식 {int(is_non_lwlt.sum()):,} ({is_non_lwlt.mean() * 100:.2f}%)"
    )
    unexplained = recent[~is_non_lwlt]
    print(f"\n미분류 {len(unexplained):,}건의 방법명:")
    print(unexplained["sucsfbid_mthd_nm"].value_counts().head(6).to_string())

    share = len(unexplained) / len(recent) * multi["miss"].sum() / total_missing
    print(f"\n전체 결측 {total_missing:,}건 중 미분류 추정 비중: {share * 100:.2f}%")
    print(
        "이 비중이 수집 경로 개선(첨부문서 파싱 포함)으로 얻을 수 있는 상한입니다."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    args = parser.parse_args()

    path = PROJECT_ROOT / args.parquet
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    frame = load(path)
    print(
        f"전체 {len(frame):,}행 / 결측 {int(frame['miss'].sum()):,} "
        f"({frame['miss'].mean() * 100:.2f}%)"
    )
    report_method_column(frame)
    report_prearng(frame)
    report_multi_prearng(frame)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
