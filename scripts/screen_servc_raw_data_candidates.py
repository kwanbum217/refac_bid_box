#!/usr/bin/env python3
"""
Servc `raw_data` 미조사 후보 20종을 결측률·카디널리티·연도 안정성으로 거릅니다.

인수인계 `2026-08-07_servc_next_axis_handoff.md` 4.3 의 3단계입니다. 2단계
(`audit_servc_raw_data_keys.py`)가 113종에서 추린 20종이 대상입니다.

**추론 시점 가용성을 함께 봅니다.** 개찰 완료 건에서 채워져 있다고 쓸 수 있는
것이 아닙니다. 낙찰하한율은 개찰 완료 건에서는 채워져 있지만 미개찰 공고에서
62.8% 결측이라 서빙에서 쓸 수 없었습니다. 같은 함정을 두 번 밟지 않으려면
미개찰 공고 채움률이 판정에 들어가야 합니다.

연도 안정성은 **값 수준**으로 봅니다. 2단계에서 키 구성이 12개 연도 동일임을
확인했으나, 키가 있어도 값이 특정 연도에만 채워질 수 있습니다.

판정 기준입니다.

    개찰 결측 40% 이상        학습 구간에서 못 씁니다
    미개찰 결측 40% 이상      추론 시점에 없습니다
    연도별 채움률 폭 0.30 이상  제도 변경으로 구간마다 다른 변수입니다
    고유값 1개                상수라 신호가 없습니다
    고유값 300 초과            원값을 범주로 못 씁니다. 파생이 필요합니다

앞의 넷 중 하나라도 걸리면 제외입니다. 마지막은 제외가 아니라 파생 설계
과제로 넘깁니다.

사용법:
    .venv/bin/python scripts/screen_servc_raw_data_candidates.py
    .venv/bin/python scripts/screen_servc_raw_data_candidates.py --extract
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

# 2단계가 추린 18종입니다. 값은 (별칭, 성격) 입니다. 성격은 파생 설계를 위한
# 메모이고 판정에는 쓰지 않습니다.
#
# `ntceKindNm` 과 `bidMethdNm` 은 처음에 후보로 올렸다가 뺐습니다. 수집기가
# 두 키를 정규 컬럼으로 옮겨 담고(`_map_announcement_item`) 그 컬럼이 이미
# 학습 특징이라(`src/ml/features.py:52`) 미사용이 아닙니다.
CANDIDATES = {
    "rgnDutyJntcontrctRt": ("rgn_duty_jnt_rt", "수치. 지역의무 공동도급 비율"),
    "jntcontrctDutyRgnNm1": ("jnt_duty_rgn1", "범주. 의무 지역"),
    "jntcontrctDutyRgnNm2": ("jnt_duty_rgn2", "범주. 의무 지역"),
    "jntcontrctDutyRgnNm3": ("jnt_duty_rgn3", "범주. 의무 지역"),
    "ntceDscrptYn": ("ntce_dscrpt_yn", "이진. 설명회 실시"),
    "dcmtgOprtnDt": ("dcmtg_dt", "일시. 존재 여부로 파생"),
    "dcmtgOprtnPlce": ("dcmtg_plce", "텍스트. 존재 여부로 파생"),
    "chgDt": ("chg_dt", "일시. 변경 여부로 파생"),
    "rgstTyNm": ("rgst_ty_nm", "범주. 등록 유형"),
    "mnfctYn": ("mnfct_yn", "이진. 제조 여부"),
    "tpEvalApplMthdNm": ("tp_eval_appl_mthd", "범주. 기술평가 신청 방식"),
    "tpEvalApplClseDt": ("tp_eval_clse_dt", "일시"),
    "pqApplDocRcptMthdNm": ("pq_appl_mthd", "범주. PQ 신청 방식"),
    "pqApplDocRcptDt": ("pq_appl_dt", "일시"),
    "arsltReqstdocRcptDt": ("arslt_rcpt_dt", "일시"),
    "cmmnSpldmdAgrmntClseDt": ("cmmn_agrmnt_clse_dt", "일시"),
    "purchsObjPrdctList": ("purchs_prdct_list", "중첩. 구매 대상 품목"),
    "indutyVAT": ("induty_vat", "수치. 업종 부가세"),
}

CACHE = PROJECT_ROOT / "data" / "analysis" / "servc_raw_data_keys" / "candidate_values.parquet"
UNOPENED_CACHE = CACHE.with_name("candidate_unopened.parquet")

SURVEY_YEARS = range(2015, 2027)
SAMPLE_PER_YEAR = 15_000

# 판정 임계값입니다.
MAX_MISSING = 0.40
MAX_YEAR_SPREAD = 0.30
MAX_CATEGORY_LEVELS = 300


def _select_columns() -> str:
    return ",\n            ".join(
        f"NULLIF(JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.{src}')), '') AS {alias}"
        for src, (alias, _) in CANDIDATES.items()
    )


def extract_opened(engine) -> pd.DataFrame:
    """개찰 완료 건. 학습 구간의 가용성입니다."""
    sql = f"""
        SELECT
            YEAR(r.rl_openg_dt) AS year,
            {_select_columns()}
        FROM bid_results r
        JOIN bid_announcements a
          ON a.bid_ntce_no = r.bid_ntce_no
         AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
         AND a.category = r.category
        WHERE r.category = 'Servc' AND r.sucsf_bid_rate IS NOT NULL
          AND JSON_TYPE(a.raw_data) = 'OBJECT'
          AND r.rl_openg_dt >= :start AND r.rl_openg_dt < :end
        LIMIT {SAMPLE_PER_YEAR}
    """  # noqa: S608 - 보간값이 모듈 상수입니다
    frames = []
    for year in SURVEY_YEARS:
        part = pd.read_sql(
            text(sql), engine, params={"start": f"{year}-01-01", "end": f"{year + 1}-01-01"}
        )
        if part.empty:
            continue
        frames.append(part)
        print(f"[개찰] {year} {len(part):,}행", flush=True)
    df = pd.concat(frames, ignore_index=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE)
    return df


def extract_unopened(engine) -> pd.Series:
    """미개찰 공고. **이것이 추론 시점의 실제 가용성입니다.**"""
    sql = f"""
        SELECT {_select_columns()}
        FROM bid_announcements a
        LEFT JOIN bid_results r
          ON a.bid_ntce_no = r.bid_ntce_no
         AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
         AND a.category = r.category
        WHERE a.category = 'Servc' AND r.id IS NULL
          AND JSON_TYPE(a.raw_data) = 'OBJECT'
          AND a.bid_ntce_dt >= :start
        LIMIT 60000
    """  # noqa: S608 - 보간값이 모듈 상수입니다
    # 최근 구간만 봅니다. 과거 미개찰 건은 수집 누락이나 유찰이라 추론 시점의
    # 가용성을 대변하지 못합니다.
    df = pd.read_sql(text(sql), engine, params={"start": "2025-01-01"})
    print(f"[미개찰] {len(df):,}행", flush=True)
    coverage = df.notna().mean()
    coverage.to_frame("cov").to_parquet(UNOPENED_CACHE)
    return coverage


def verdict(row: pd.Series) -> str:
    if row["개찰 결측"] >= MAX_MISSING:
        return "제외: 학습 구간 결측"
    if pd.isna(row["미개찰 채움"]):
        return "보류: 미개찰 표본 없음"
    if 1 - row["미개찰 채움"] >= MAX_MISSING:
        return "제외: 추론 시점 결측"
    if row["연도 폭"] >= MAX_YEAR_SPREAD:
        return "제외: 연도 불안정"
    if row["고유값"] <= 1:
        return "제외: 상수"
    if row["고유값"] > MAX_CATEGORY_LEVELS:
        return "파생 필요: 고유값 과다"
    return "통과"


def screen(df: pd.DataFrame, unopened: pd.Series) -> pd.DataFrame:
    rows = []
    for src, (alias, nature) in CANDIDATES.items():
        col = df[alias]
        filled = col.notna()
        by_year = filled.groupby(df["year"]).mean()
        rows.append(
            {
                "키": src,
                "성격": nature,
                "개찰 결측": round(float(1 - filled.mean()), 4),
                "미개찰 채움": round(float(unopened.get(alias)), 4)
                if alias in unopened.index
                else pd.NA,
                "고유값": int(col.nunique(dropna=True)),
                "연도 폭": round(float(by_year.max() - by_year.min()), 4) if len(by_year) else 0.0,
                "최소 연도 채움": round(float(by_year.min()), 4) if len(by_year) else 0.0,
            }
        )
    frame = pd.DataFrame(rows)
    frame["판정"] = frame.apply(verdict, axis=1)
    return frame


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract", action="store_true", help="DB 에서 다시 추출")
    parser.add_argument("--out", default="data/analysis/servc_raw_data_keys/candidate_screen.csv")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    engine = create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)

    if args.extract or not CACHE.exists():
        df = extract_opened(engine)
        unopened = extract_unopened(engine)
    else:
        df = pd.read_parquet(CACHE)
        unopened = pd.read_parquet(UNOPENED_CACHE)["cov"]
        print(f"[cache] 개찰 {len(df):,}행 재사용")

    result = screen(df, unopened)
    pd.set_option("display.width", 220)
    print("\n" + "=" * 110)
    print(f"후보 {len(result)}종 선별 (결측 {MAX_MISSING:.0%} / 연도 폭 {MAX_YEAR_SPREAD:.0%})")
    print("=" * 110)
    print(result.sort_values(["판정", "개찰 결측"]).to_string(index=False))

    print("\n" + "=" * 110)
    for label, frame in result.groupby("판정"):
        print(f"{label}: {len(frame)}종 — {', '.join(frame['키'])}")

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    result.to_csv(out_path, index=False)
    print(f"\n기록: {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
