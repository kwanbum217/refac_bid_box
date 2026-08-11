"""제도 플래그 두 개의 2025-01 전환이 표기 변경인지 실질 구성 변화인지 가릅니다.

`servc_lwlt_missing_remechanism_20260811.md` 4.4 에서 `sucsfbidLwltRate` 의
2025-01 급변은 표기 변경이었습니다. 원천이 결측을 문자열 '0' 으로 적다가 빈
문자열로 적기 시작했을 뿐이고 실보유 비율은 완만하게만 내렸습니다.

같은 착시가 `prdctClsfcLmtYn`, `rbidPermsnYn` 에도 있는지 세 축으로 봅니다.

    상태 분해   키 부재 / 빈 문자열 / N / Y 를 월별·연도별로 셉니다
    표기 이동   부재 표기가 다른 표기로 옮겨간 것뿐인지, 값 자체가 옮겨갔는지
    정보량      Y·N 집단의 낙찰률 차이가 경계를 넘어 유지되는지

세 번째가 판정의 핵심입니다. 구성비가 뒤집혀도 두 집단의 낙찰률 차이가
유지되면 구분의 의미는 살아 있고, 차이가 사라지면 라벨의 뜻이 바뀐 것입니다.

사용법:
    uv run python scripts/audit_servc_flag_notation.py
    uv run python scripts/audit_servc_flag_notation.py --since 2015-01-01

읽기 전용입니다. DB 는 SELECT 만 실행합니다. 결과 해석은
docs/design/servc_flag_notation_verdict_20260811.md 를 보십시오.
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

# 관측된 경계입니다. 세 필드가 같은 달에 움직였습니다.
BOUNDARY = "2025-01-01"

# 전 구간을 훑으면 JSON 추출 때문에 2분가량 걸립니다. 기본은 경계 앞뒤로 잡습니다.
DEFAULT_SINCE = "2023-01-01"

FIELDS = ("prdctClsfcLmtYn", "rbidPermsnYn")

# 키 자체가 없는 행을 값과 구분하기 위한 표지입니다.
ABSENT = "<키부재>"


def fetch(engine, since: str) -> pd.DataFrame:
    # 필드명은 이 모듈의 FIELDS 상수로만 정해지고 외부 입력이 닿지 않습니다.
    selected = ", ".join(
        f"COALESCE(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.{field}')),'{ABSENT}') AS {field}"
        for field in FIELDS
    )
    sql = (
        f"SELECT bid_ntce_no, LEFT(bid_ntce_dt,7) AS ym, {selected} "  # noqa: S608
        "FROM bid_announcements "
        "WHERE category='Servc' AND raw_data IS NOT NULL AND bid_ntce_dt >= :since"
    )
    with engine.connect() as conn:
        rows = [dict(row._mapping) for row in conn.execute(text(sql), {"since": since})]
    frame = pd.DataFrame(rows)
    frame["yr"] = frame["ym"].str.slice(0, 4)
    return frame


def state_table(frame: pd.DataFrame, field: str, index: str) -> pd.DataFrame:
    counts = frame.pivot_table(index=index, columns=field, aggfunc="size", fill_value=0)
    ratio = counts.div(counts.sum(axis=1), axis=0) * 100
    ratio.insert(0, "n", counts.sum(axis=1))
    return ratio


def report_states(frame: pd.DataFrame) -> None:
    for field in FIELDS:
        print(f"\n== {field} 상태 구성 (연도, %) ==")
        print(state_table(frame, field, "yr").round(2).to_string())
        print(f"\n== {field} 상태 구성 (월, %) ==")
        monthly = state_table(frame, field, "ym")
        print(monthly[monthly.index >= "2024-06"].round(2).to_string())


def report_information(frame: pd.DataFrame, parquet: Path) -> None:
    """Y·N 집단의 낙찰률 차이가 경계를 넘어 유지되는지 봅니다."""
    outcome = pd.read_parquet(parquet, columns=["bid_ntce_no", "bid_ntce_dt", "winning_rate"])
    outcome = outcome.drop_duplicates("bid_ntce_no")
    merged = frame.drop_duplicates("bid_ntce_no").merge(outcome, on="bid_ntce_no", how="inner")
    merged["yr"] = pd.to_datetime(merged["bid_ntce_dt"], errors="coerce").dt.year
    print(f"\n조인 {len(merged):,}행 (플래그 {frame['bid_ntce_no'].nunique():,}건 기준)")

    for field in FIELDS:
        print(f"\n== {field}: Y·N 집단의 낙찰률 차이 ==")
        print(f"{'연도':6}{'Y n':>9}{'Y 평균':>9}{'N n':>9}{'N 평균':>9}{'Y-N':>9}")
        for year, part in merged.groupby("yr"):
            yes = part.loc[part[field] == "Y", "winning_rate"]
            no = part.loc[part[field] == "N", "winning_rate"]
            if len(yes) < 200 or len(no) < 200:
                continue
            print(
                f"{year:<6}{len(yes):>9,}{yes.mean():>9.3f}"
                f"{len(no):>9,}{no.mean():>9.3f}{yes.mean() - no.mean():>9.3f}"
            )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--since", default=DEFAULT_SINCE)
    parser.add_argument("--parquet", default="data/feature_store/dataset_Servc.parquet")
    parser.add_argument("--skip-outcome", action="store_true", help="낙찰률 축을 건너뜁니다")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL 이 없습니다.")
        return 1

    frame = fetch(create_engine(url), args.since)
    print(f"공고 {len(frame):,}건 / {args.since} 이후 / 경계 {BOUNDARY}")
    report_states(frame)

    if args.skip_outcome:
        return 0
    path = Path(args.parquet)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    if not path.exists():
        print(f"\n데이터셋이 없어 낙찰률 축을 건너뜁니다: {path}")
        return 0
    report_information(frame, path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
