#!/usr/bin/env python3
"""
Servc 학습 구간의 `raw_data` 채움률과 미사용 키를 조사합니다.

인수인계 `2026-08-07_servc_next_axis_handoff.md` 4.3 의 1~2단계입니다.
새 정보의 1차 후보는 API 재수집이 아니라 **이미 저장돼 있는데 안 쓰는 키**
입니다. 그것을 확인하기 전에 재수집을 논의하면 순서가 뒤집힙니다.

1단계 채움률을 건너뛰면 안 됩니다. parquet 복구분 1,244,778행은 `raw_data`
가 비어 있고(`src/app/models/bids.py:135`), 그 구간이 Servc 학습 구간에
얼마나 걸치는지는 아직 재지 않았습니다. 겹침이 크면 이 축 자체가 좁아집니다.

2단계는 **등장 키 전량**을 셉니다. 2026-08-03 조사(`survey_servc_fields.py`)
는 손으로 고른 후보 38개만 봤으므로, 그때 눈에 안 띈 키가 남아 있는지는
전수로만 확인됩니다.

**채움 판정은 `JSON_TYPE = 'OBJECT'` 로 합니다.** `raw_data` 에는 JSON `null`
리터럴이 들어간 행이 있습니다. SQL NULL 이 아니라서 `IS NOT NULL` 을 통과하고
`JSON_LENGTH` 는 1을 돌려주므로, 두 방법 모두 빈 행을 채워진 것으로 셉니다.

사용법:
    .venv/bin/python scripts/audit_servc_raw_data_keys.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections import Counter
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

from scripts.survey_servc_fields import CANDIDATES, IN_USE  # noqa: E402

# `raw_data` 에서 직접 읽는 키 말고, 수집기가 **정규 컬럼으로 옮겨 담는** 키가
# 따로 있습니다(`_map_announcement_item`). 그 컬럼 중 일부는 이미 학습 특징이라
# 여기를 빠뜨리면 쓰고 있는 키를 미사용으로 셉니다. 실제로 `ntceKindNm` 과
# `bidMethdNm` 을 후보로 잘못 올렸다가 3단계에서 발견했습니다.
COLUMN_MAPPED = {
    "bidNtceNm": "bid_ntce_nm",
    "bidNtceNo": "bid_ntce_no",
    "bidNtceOrd": "bid_ntce_ord",
    "ntceInsttNm": "ntce_instt_nm",
    "dminsttNm": "dminstt_nm",
    "presmptPrce": "presmpt_prce",
    "bidNtceDt": "bid_ntce_dt",
    "bidClseDt": "bid_clse_dt",
    "opengDt": "openg_dt",
    "ntceKindNm": "ntce_kind_nm",
    "bidMethdNm": "bid_methd_nm",
    "cntrctCnclsMthdNm": "cntrct_mthd_nm",
}

# 학습 구간입니다. `eval_servc_year_holdout` 이 2024년까지 학습, 2025년 검증을
# 쓰므로 채움률도 같은 축으로 봐야 판단이 이어집니다.
SURVEY_YEARS = range(2015, 2027)

# 키 목록만 뽑는 것이라 전수가 필요 없습니다. 연도별로 이만큼이면 등장 빈도
# 0.1% 수준의 희소 키까지 잡힙니다.
SAMPLE_PER_YEAR = 20_000


def make_engine():
    load_dotenv(PROJECT_ROOT / ".env")
    url = os.environ["DATABASE_URL"]
    return create_engine(url, pool_pre_ping=True)


def fill_rate(engine) -> pd.DataFrame:
    """연도별 raw_data 채움률. 결과 테이블과 공고 테이블을 나눠 봅니다."""
    sql = """
        SELECT
            YEAR(r.rl_openg_dt) AS year,
            COUNT(*) AS rows_total,
            SUM(CASE WHEN JSON_TYPE(r.raw_data) = 'OBJECT' THEN 1 ELSE 0 END) AS result_filled,
            SUM(CASE WHEN JSON_TYPE(a.raw_data) = 'OBJECT' THEN 1 ELSE 0 END) AS ann_filled,
            SUM(CASE WHEN a.id IS NULL THEN 1 ELSE 0 END) AS ann_missing
        FROM bid_results r
        LEFT JOIN bid_announcements a
          ON a.bid_ntce_no = r.bid_ntce_no
         AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
         AND a.category = r.category
        WHERE r.category = 'Servc' AND r.sucsf_bid_rate IS NOT NULL
          AND r.rl_openg_dt >= '2015-01-01'
        GROUP BY YEAR(r.rl_openg_dt)
        ORDER BY year
    """
    df = pd.read_sql(text(sql), engine)
    df["result_rate"] = (df["result_filled"] / df["rows_total"]).round(4)
    df["ann_rate"] = (df["ann_filled"] / df["rows_total"]).round(4)
    df["ann_missing_rate"] = (df["ann_missing"] / df["rows_total"]).round(4)
    return df


def key_counts(engine, table: str, date_column: str) -> pd.DataFrame:
    """등장 키 전량과 빈도. JSON_KEYS 로 뽑아 파이썬에서 셉니다."""
    sql = f"""
        SELECT YEAR(t.{date_column}) AS year, JSON_KEYS(t.raw_data) AS keys_json
        FROM {table} t
        WHERE t.category = 'Servc' AND JSON_TYPE(t.raw_data) = 'OBJECT'
          AND t.{date_column} >= :start AND t.{date_column} < :end
        LIMIT {SAMPLE_PER_YEAR}
    """  # noqa: S608 - 보간값이 모듈 상수입니다
    counter: Counter[str] = Counter()
    per_year: dict[int, set[str]] = {}
    sampled = 0
    for year in SURVEY_YEARS:
        part = pd.read_sql(
            text(sql), engine, params={"start": f"{year}-01-01", "end": f"{year + 1}-01-01"}
        )
        if part.empty:
            continue
        sampled += len(part)
        seen: set[str] = set()
        for payload in part["keys_json"]:
            if isinstance(payload, str):
                keys = json.loads(payload)
            elif isinstance(payload, list):
                keys = payload
            else:
                continue
            counter.update(keys)
            seen.update(keys)
        per_year[year] = seen
        print(f"[{table}] {year} {len(part):,}행 / 누적 키 {len(counter)}종", flush=True)

    frame = pd.DataFrame(
        [
            {
                "key": key,
                "rows": count,
                "row_share": round(count / sampled, 4) if sampled else 0.0,
                "years_present": sum(1 for keys in per_year.values() if key in keys),
            }
            for key, count in counter.most_common()
        ]
    )
    frame["year_span"] = len(per_year)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="data/analysis/servc_raw_data_keys")
    args = parser.parse_args()

    engine = make_engine()
    out_dir = PROJECT_ROOT / args.out
    out_dir.mkdir(parents=True, exist_ok=True)

    print("=" * 76)
    print("1단계: raw_data 채움률")
    print("=" * 76)
    rates = fill_rate(engine)
    print(
        rates[["year", "rows_total", "result_rate", "ann_rate", "ann_missing_rate"]].to_string(
            index=False
        )
    )
    total = int(rates["rows_total"].sum())
    print(
        f"\n합계 {total:,}행 / 결과 raw_data {rates['result_filled'].sum() / total:.2%} "
        f"/ 공고 raw_data {rates['ann_filled'].sum() / total:.2%}"
    )
    rates.to_csv(out_dir / "fill_rate.csv", index=False)

    print("\n" + "=" * 76)
    print("2단계: 등장 키 전량과 미사용 키")
    print("=" * 76)

    ann_keys = key_counts(engine, "bid_announcements", "bid_ntce_dt")
    res_keys = key_counts(engine, "bid_results", "rl_openg_dt")

    for label, frame in (("공고", ann_keys), ("결과", res_keys)):
        if frame.empty:
            print(f"\n[{label}] raw_data 가 비어 표본이 없습니다")
            continue
        frame["in_use"] = frame["key"].isin(set(IN_USE) | set(COLUMN_MAPPED))
        # 2026-08-03 조사가 손으로 고른 후보입니다. 이미 연관도를 잰 것이므로
        # 새로 볼 것은 이 둘 어디에도 없는 키입니다.
        frame["surveyed"] = frame["key"].isin(CANDIDATES.keys())
        frame.to_csv(out_dir / f"keys_{label}.csv", index=False)
        fresh = frame[~frame["in_use"] & ~frame["surveyed"]]
        print(
            f"\n[{label}] 키 {len(frame)}종 / 사용 중 {int(frame['in_use'].sum())}종 "
            f"/ 2026-08-03 기조사 {int(frame['surveyed'].sum())}종 / 미조사 {len(fresh)}종"
        )
        print(f"[{label}] 미조사 키 전량")
        print(fresh.to_string(index=False))

    print(f"\n기록: {out_dir.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
