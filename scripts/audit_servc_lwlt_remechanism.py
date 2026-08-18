"""2025-01 체제 경계 전후로 용역 하한율 결측 메커니즘을 다시 분해합니다.

`servc_lwlt_missing_mechanism_20260810.md` 는 결측의 99.1% 를 제도적 부재로
판정했습니다. 그 판정은 2015~2026 전 구간을 한 덩어리로 본 것이었고,
`servc_2025_source_regime_shift_20260811.md` 4.1 이 전환 이후 표본으로 다시
확인할 것을 남겼습니다.

이 스크립트는 네 축으로 잽니다.

    예가방식(prearng_mthd)   구간별 결측 구성비. 단일예가·비예가는 하한율 부재
    낙찰방법(sucsfbid_mthd_nm)  전환 이후 구간만 유효합니다. 이전은 전량 `공고서참조`
    낙찰률 분포              결측·보유 집단이 구간을 넘어 같은 모집단인지
    원천 표기(raw_data)      DB 의 sucsfbidLwltRate 가 어떤 형태로 비는지

마지막 축이 핵심입니다. 파생 컬럼은 `src/ml/dataset.py` 가 0 을 NA 로 바꾸므로,
원천이 '0' 으로 쓰던 것을 빈 문자열로 바꾸어도 결측 정의는 움직이지 않습니다.

사용법:
    uv run python scripts/audit_servc_lwlt_remechanism.py
    uv run python scripts/audit_servc_lwlt_remechanism.py --skip-db

읽기 전용입니다. DB 는 SELECT 만 실행합니다. 결과 해석은
docs/design/servc_lwlt_missing_remechanism_20260811.md 를 보십시오.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# 체제 경계입니다. servc_2025_source_regime_shift_20260811.md 가 세 필드에서
# 같은 달을 찾았습니다. 관측된 경계이지 확인된 제도 변경이 아닙니다.
BOUNDARY = "2025-01-01"

# 원천 표기 변화를 볼 구간입니다. 경계 앞뒤 1년씩이면 계단 여부가 드러납니다.
RAW_SINCE = "2024-01-01"

# 하한율이 제도상 존재하지 않는 낙찰방법 계열입니다.
# audit_servc_lwlt_mechanism.py 와 같은 목록을 씁니다.
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

LWLT_FIELD = "sucsfbidLwltRate"

COLUMNS = ["bid_ntce_dt", "winning_rate", "lwlt_rate", "prearng_mthd", "sucsfbid_mthd_nm"]


def load(path: Path, boundary: str) -> pd.DataFrame:
    frame = pd.read_parquet(path, columns=COLUMNS)
    frame["bid_ntce_dt"] = pd.to_datetime(frame["bid_ntce_dt"], errors="coerce")
    frame["yr"] = frame["bid_ntce_dt"].dt.year
    frame["miss"] = frame["lwlt_rate"].isna()
    frame["seg"] = frame["bid_ntce_dt"].ge(boundary).map({False: "pre", True: "post"})
    return frame


def prearng_table(part: pd.DataFrame) -> pd.DataFrame:
    total = int(part["miss"].sum())
    table = part.groupby("prearng_mthd", observed=True).agg(
        행수=("miss", "size"), 결측=("miss", "sum")
    )
    table["결측률%"] = (table["결측"] / table["행수"] * 100).round(2)
    table["전체결측중%"] = (table["결측"] / total * 100).round(2)
    return table


def report_prearng(frame: pd.DataFrame, boundary: str) -> None:
    print(f"\n== 예가방식 축: 경계 {boundary} 전후 ==")
    for seg, label in (("pre", "경계 이전"), ("post", "경계 이후")):
        part = frame[frame["seg"] == seg]
        missing = int(part["miss"].sum())
        print(f"\n-- {label}  n={len(part):,}  결측={missing:,} ({part['miss'].mean() * 100:.2f}%)")
        print(prearng_table(part).to_string())

    print("\n-- 경계 이전을 2024년으로 좁힌 것 (구간 길이 차이를 없앤 비교)")
    recent_pre = frame[(frame["seg"] == "pre") & (frame["yr"] == 2024)]
    print(prearng_table(recent_pre).to_string())


def report_method(frame: pd.DataFrame) -> None:
    print("\n== 낙찰방법 축: 복수예가 결측 중 하한율 비적용 비율 ==")
    multi = frame[frame["prearng_mthd"] == "복수예가"]
    for seg, label in (("pre", "경계 이전"), ("post", "경계 이후")):
        part = multi[(multi["seg"] == seg) & multi["miss"]]
        names = part["sucsfbid_mthd_nm"].astype(str)
        non_lwlt = names.str.startswith(NON_LWLT_METHODS)
        unknown = (names == "공고서참조").mean() * 100
        print(
            f"{label:10} 결측={len(part):>7,}  비적용={int(non_lwlt.sum()):>7,} "
            f"({non_lwlt.mean() * 100:6.2f}%)  방법명미상={unknown:6.2f}%"
        )
        rest = part[~non_lwlt]
        if not rest.empty and unknown < 50:
            print(
                "           미분류 방법명: "
                + ", ".join(
                    f"{name} {count}"
                    for name, count in rest["sucsfbid_mthd_nm"].value_counts().head(3).items()
                )
            )
    print(
        f"\n{METHOD_VALID_YEAR}년 이전은 낙찰방법이 전량 `공고서참조` 이므로 "
        "이 축으로 판정할 수 없습니다. 아래 분포 축으로 대신합니다."
    )


def report_distribution(frame: pd.DataFrame) -> None:
    print("\n== 낙찰률 분포: 결측·보유 집단이 경계를 넘어 같은 모집단인가 ==")
    for seg, label in (("pre", "이전"), ("post", "이후")):
        for miss, group in ((True, "결측"), (False, "보유")):
            series = frame.loc[(frame["seg"] == seg) & (frame["miss"] == miss), "winning_rate"]
            print(
                f"{label} {group}  n={len(series):>7,} 평균={series.mean():7.3f} "
                f"SD={series.std():6.3f} 중앙={series.median():7.3f} "
                f"p95={series.quantile(0.95):7.3f}"
            )


def report_trend(frame: pd.DataFrame) -> None:
    print("\n== 결측 구성비의 연도 추세 (계단인가 추세인가) ==")
    table = frame.groupby("yr").apply(
        lambda part: pd.Series(
            {
                "건수": len(part),
                "결측%": part["miss"].mean() * 100,
                "단일예가비중%": (part["prearng_mthd"] == "단일예가").mean() * 100,
                "결측중단일예가%": (part.loc[part["miss"], "prearng_mthd"] == "단일예가").mean()
                * 100,
                "단일예가결측률%": part.loc[part["prearng_mthd"] == "단일예가", "miss"].mean()
                * 100,
                "복수예가결측률%": part.loc[part["prearng_mthd"] == "복수예가", "miss"].mean()
                * 100,
            }
        ),
        include_groups=False,
    )
    print(table.round(2).to_string())


def report_monthly(frame: pd.DataFrame, since: str) -> None:
    print(f"\n== 단일예가 월별 ({since} 이후): 경계가 어느 달에 있는가 ==")
    part = frame[frame["bid_ntce_dt"] >= since].copy()
    part["ym"] = part["bid_ntce_dt"].dt.to_period("M")
    table = part.groupby("ym").apply(
        lambda block: pd.Series(
            {
                "단일예가n": (block["prearng_mthd"] == "단일예가").sum(),
                "단일예가비중%": (block["prearng_mthd"] == "단일예가").mean() * 100,
                "단일예가결측률%": block.loc[block["prearng_mthd"] == "단일예가", "miss"].mean()
                * 100,
            }
        ),
        include_groups=False,
    )
    print(table.round(2).to_string())


def report_raw_encoding(engine) -> None:
    # 필드명은 이 모듈의 LWLT_FIELD 상수로만 정해지고 외부 입력이 닿지 않습니다.
    path = f"'$.{LWLT_FIELD}'"
    sql = (
        "SELECT LEFT(bid_ntce_dt,7) AS ym, COUNT(*) AS n, "  # noqa: S608
        f"SUM(JSON_EXTRACT(raw_data,{path}) IS NULL) AS key_absent, "
        f"SUM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,{path}))='') AS empty_str, "
        f"SUM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,{path}))+0=0 "
        f"AND JSON_UNQUOTE(JSON_EXTRACT(raw_data,{path}))<>'') AS zero_str, "
        f"SUM(JSON_UNQUOTE(JSON_EXTRACT(raw_data,{path}))+0>0) AS positive "
        "FROM bid_announcements "
        "WHERE category='Servc' AND raw_data IS NOT NULL AND bid_ntce_dt >= :since "
        "GROUP BY ym ORDER BY ym"
    )
    query = text(sql)
    print(f"\n== 원천 표기: raw_data.{LWLT_FIELD} 가 어떤 형태로 비는가 ==")
    print(f"{'ym':9}{'n':>9}{'키부재%':>9}{'빈값%':>8}{'0값%':>8}{'양수%':>8}")
    with engine.connect() as conn:
        for ym, total, absent, empty, zero, positive in conn.execute(query, {"since": RAW_SINCE}):
            total = int(total)
            print(
                f"{ym:9}{total:>9,}{100 * int(absent) / total:>9.2f}"
                f"{100 * int(empty) / total:>8.2f}{100 * int(zero) / total:>8.2f}"
                f"{100 * int(positive) / total:>8.2f}"
            )
    print(
        "\n양수 비율만이 실제 하한율 보유입니다. '0값' 이 '빈값' 으로 옮겨간 것은 "
        "표기 변경이며, dataset.py 가 0 을 NA 로 바꾸므로 파생 결측은 움직이지 않습니다."
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--boundary", default=BOUNDARY)
    parser.add_argument("--skip-db", action="store_true", help="원천 표기 축을 건너뜁니다")
    parser.add_argument("--monthly-since", default="", help="단일예가 월별 표를 낼 시작일")
    args = parser.parse_args()

    path = Path(args.parquet)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        print(f"데이터셋이 없습니다: {path}")
        return 1

    frame = load(path, args.boundary)
    print(
        f"전체 {len(frame):,}행 / 결측 {int(frame['miss'].sum()):,} "
        f"({frame['miss'].mean() * 100:.2f}%) / 경계 {args.boundary}"
    )
    report_prearng(frame, args.boundary)
    report_method(frame)
    report_distribution(frame)
    report_trend(frame)
    if args.monthly_since:
        report_monthly(frame, args.monthly_since)

    if args.skip_db:
        return 0
    load_dotenv(PROJECT_ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("\nDATABASE_URL 이 없어 원천 표기 축을 건너뜁니다.")
        return 0
    report_raw_encoding(create_engine(url))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
