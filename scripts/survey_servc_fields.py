#!/usr/bin/env python3
"""
용역 공고 필드와 낙찰률의 관계를 전수 조사합니다.

`bid_announcements.raw_data` 는 키가 113종입니다. 지금 모델은 그중 16종만
씁니다. 나머지에 신호가 있는지, 있다면 쓸 수 있는지를 한 번에 봅니다.

상관계수만 보면 오판합니다. 이 데이터에서 이미 두 번 겪었습니다.
낙찰하한율은 상관이 높지만 추론 시점 결측이 62.8% 이고, 기초금액은 제도상
예정가격의 1.1 배라 상관이 있어도 독립 정보가 없습니다. 그래서 세 가지를
함께 봅니다.

1. 연관도    수치는 Spearman, 범주는 eta 제곱 (집단 간 분산 비율)
2. 가용성    개찰 완료 건과 **미개찰 공고**의 채움률. 후자가 추론 시점입니다
3. 증분      기존 특징에 얹었을 때 실제로 성능이 오르는가 (2단계)

1단계는 통계만 냅니다. 2단계 증분 측정은 상위 후보에만 돌립니다.

사용법:
    .venv/bin/python scripts/survey_servc_fields.py --extract   # 추출부터
    .venv/bin/python scripts/survey_servc_fields.py             # 캐시 재사용
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402

CACHE = PROJECT_ROOT / "data" / "feature_store" / "servc_field_survey.parquet"

# 이미 학습에 쓰는 필드입니다. 대조군으로 함께 재서 신규 후보의 크기를 가늠합니다.
IN_USE = {
    "sucsfbidLwltRate": "lwlt_rate",
    "prearngPrceDcsnMthdNm": "prearng_mthd",
    "sucsfbidMthdNm": "sucsfbid_mthd_nm",
    "srvceDivNm": "srvce_div_nm",
    "pubPrcrmntLrgClsfcNm": "lrg_clsfc_nm",
    "pubPrcrmntMidClsfcNm": "mid_clsfc_nm",
    "pubPrcrmntClsfcNm": "clsfc_nm",
    "techAbltEvlRt": "tech_ablt_evl_rt",
    "bidPrceEvlRt": "bid_prce_evl_rt",
    "totPrdprcNum": "tot_prdprc_num",
    "drwtPrdprcNum": "drwt_prdprc_num",
    "intrbidYn": "intrbid_yn",
    "ppswGnrlSrvceYn": "ppsw_gnrl_srvce_yn",
}

# 미사용 후보입니다. URL, 파일명, 전화번호, 이메일은 신호가 없어 제외했습니다.
CANDIDATES = {
    "exctvNm": "exctv_nm",
    "cmmnSpldmdMethdNm": "cmmn_spldmd_methd_nm",
    "cmmnSpldmdAgrmntRcptdocMethd": "cmmn_agrmnt_rcpt_mthd",
    "cmmnSpldmdCorpRgnLmtYn": "cmmn_rgn_lmt_yn",
    "rgstDt": "rgst_dt",
    "rbidOpengDt": "rbid_openg_dt",
    "opengPlce": "openg_plce",
    "asignBdgtAmt": "asign_bdgt_amt",
    "bidBeginDt": "bid_begin_dt",
    "bidClseDt": "bid_clse_dt_raw",
    "bidQlfctRgstDt": "bid_qlfct_rgst_dt",
    "pqEvalYn": "pq_eval_yn",
    "tpEvalYn": "tp_eval_yn",
    "orderPlanUntyNo": "order_plan_unty_no",
    "rsrvtnPrceReMkngMthdNm": "rsrvtn_remaking_mthd",
    "indstrytyLmtYn": "indstryty_lmt_yn",
    "brffcBidprcPermsnYn": "brffc_bidprc_permsn_yn",
    "bfSpecRgstNo": "bf_spec_rgst_no",
    "VAT": "vat",
    "arsltApplDocRcptMthdNm": "arslt_appl_rcpt_mthd",
    "arsltCmptYn": "arslt_cmpt_yn",
    "chgNtceRsn": "chg_ntce_rsn",
    "bidPrtcptFee": "bid_prtcpt_fee",
    "infoBizYn": "info_biz_yn",
    "befBidBbancNo": "bef_bid_bbanc_no",
    "rgnLmtBidLocplcJdgmBssNm": "rgn_lmt_nm",
    "bidGrntymnyPaymntYn": "bid_grntymny_paymnt_yn",
    "bidPrtcptFeePaymntYn": "bid_prtcpt_fee_paymnt_yn",
    "dtlsBidYn": "dtls_bid_yn",
    "untyNtceNo": "unty_ntce_no",
    "ntceInsttOfclNm": "ntce_ofcl_nm",
    "sucsfbidMthdAppStd": "sucsfbid_mthd_app_std",
    "bidPrtcptLmtYn": "bid_prtcpt_lmt_yn",
    "dsgntCmptYn": "dsgnt_cmpt_yn",
    "prdctClsfcLmtYn": "prdct_clsfc_lmt_yn",
    "rbidPermsnYn": "rbid_permsn_yn",
    "reNtceYn": "re_ntce_yn",
    "cntrctCnclsMthdNm": "cntrct_cncls_mthd_nm",
}

ALL_FIELDS = {**IN_USE, **CANDIDATES}

# 고유값이 이보다 많으면 범주형으로 쓸 수 없습니다. 존재 여부만 봅니다.
MAX_CATEGORY_LEVELS = 300

# 이 미만이면 집단 평균이 잡음이라 eta 제곱이 부풀어 오릅니다.
MIN_GROUP_ROWS = 30


# 51개 JSON 키를 210만 행에서 뽑으면 십수 분이 걸립니다. 연관도 추정에 전수는
# 필요 없고, 연도별 층화 표본이면 소수점 셋째 자리까지 안정됩니다.
SAMPLE_PER_YEAR = 25_000
SURVEY_YEARS = range(2015, 2027)


def extract(engine) -> pd.DataFrame:
    cols = ",\n        ".join(
        f"NULLIF(JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.{src}')), '') AS {alias}"
        for src, alias in ALL_FIELDS.items()
    )
    sql = f"""
        SELECT
            r.sucsf_bid_rate AS winning_rate,
            r.rl_openg_dt AS openg_dt,
            a.bid_ntce_dt,
            a.presmpt_prce,
            a.cntrct_mthd_nm,
            {cols}
        FROM bid_results r
        JOIN bid_announcements a
          ON a.bid_ntce_no = r.bid_ntce_no
         AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
         AND a.category = r.category
        WHERE r.category = 'Servc' AND r.sucsf_bid_rate IS NOT NULL
          AND r.rl_openg_dt >= :start AND r.rl_openg_dt < :end
        LIMIT {SAMPLE_PER_YEAR}
    """  # nosec B608 - 보간값이 모듈 상수입니다
    frames = []
    for year in SURVEY_YEARS:
        part = pd.read_sql(
            text(sql), engine, params={"start": f"{year}-01-01", "end": f"{year + 1}-01-01"}
        )
        frames.append(part)
        print(f"[extract] {year} 개찰 완료 {len(part):,}행", flush=True)
    df = pd.concat(frames, ignore_index=True)
    print(f"[extract] 합계 {len(df):,}행", flush=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(CACHE)
    return df


def unopened_coverage(engine) -> pd.Series:
    """미개찰 공고의 필드 채움률. 이것이 추론 시점의 실제 가용성입니다."""
    cols = ",\n        ".join(
        f"NULLIF(JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.{src}')), '') AS {alias}"
        for src, alias in ALL_FIELDS.items()
    )
    sql = f"""
        SELECT {cols}
        FROM bid_announcements a
        LEFT JOIN bid_results r
          ON a.bid_ntce_no = r.bid_ntce_no
         AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
         AND a.category = r.category
        WHERE a.category = 'Servc' AND r.id IS NULL
          AND a.bid_ntce_dt >= :start
        LIMIT 60000
    """  # nosec B608 - 보간값이 모듈 상수입니다
    print("[extract] 미개찰 공고 추출 중", flush=True)
    # 최근 구간만 봅니다. 추론 시점의 가용성을 재는 것이므로 과거 미수집 건은
    # 오히려 왜곡입니다.
    df = pd.read_sql(text(sql), engine, params={"start": "2025-01-01"})
    print(f"[extract] 미개찰 {len(df):,}행", flush=True)
    return df.notna().mean()


def eta_squared(groups: pd.Series, target: pd.Series) -> float:
    """집단 간 분산 / 전체 분산. 범주형 변수의 설명력입니다."""
    frame = pd.DataFrame({"g": groups, "y": target}).dropna()
    if frame.empty:
        return 0.0
    counts = frame["g"].value_counts()
    keep = counts[counts >= MIN_GROUP_ROWS].index
    frame = frame[frame["g"].isin(keep)]
    if frame["g"].nunique() < 2:
        return 0.0
    grand = frame["y"].mean()
    between = frame.groupby("g", observed=True)["y"].agg(["count", "mean"])
    ss_between = float((between["count"] * (between["mean"] - grand) ** 2).sum())
    ss_total = float(((frame["y"] - grand) ** 2).sum())
    return ss_between / ss_total if ss_total > 0 else 0.0


def survey(df: pd.DataFrame, unopened: pd.Series | None) -> pd.DataFrame:
    target = pd.to_numeric(df["winning_rate"], errors="coerce")
    valid = target.between(50, 110)
    df, target = df[valid], target[valid]

    rows = []
    for src, alias in ALL_FIELDS.items():
        raw = df[alias]
        coverage = float(raw.notna().mean())
        numeric = pd.to_numeric(raw, errors="coerce")
        is_numeric = numeric.notna().sum() >= 0.9 * raw.notna().sum() and raw.notna().any()

        spearman = np.nan
        eta = np.nan
        levels = int(raw.nunique(dropna=True))

        if coverage > 0:
            if is_numeric:
                pair = pd.DataFrame({"x": numeric, "y": target}).dropna()
                if len(pair) > 100 and pair["x"].nunique() > 1:
                    # pandas 순위상관을 씁니다. scipy 는 sklearn 의 전이 의존이라
                    # pyproject 에 없고, 여기서 직접 쓰면 선언 없는 의존이 생깁니다.
                    spearman = float(pair["x"].corr(pair["y"], method="spearman"))
            if levels <= MAX_CATEGORY_LEVELS:
                eta = eta_squared(raw.astype("string"), target)
            else:
                # 고유값이 많으면 범주로 못 씁니다. 존재 여부만 신호가 됩니다.
                eta = eta_squared(raw.notna().map({True: "있음", False: "없음"}), target)

        rows.append(
            {
                "필드": src,
                "사용중": "O" if src in IN_USE else "",
                "커버리지": round(coverage, 4),
                "미개찰 커버리지": (
                    round(float(unopened.get(alias, np.nan)), 4) if unopened is not None else np.nan
                ),
                "고유값": levels,
                "Spearman": round(spearman, 4) if pd.notna(spearman) else np.nan,
                "eta2": round(eta, 4) if pd.notna(eta) else np.nan,
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--extract", action="store_true", help="DB 에서 다시 추출")
    parser.add_argument("--top", type=int, default=25, help="출력할 상위 후보 수")
    args = parser.parse_args()

    load_dotenv(PROJECT_ROOT / ".env")
    engine = create_engine(os.environ["DATABASE_URL"])

    if args.extract or not CACHE.exists():
        df = extract(engine)
        unopened = unopened_coverage(engine)
        unopened.to_frame("cov").to_parquet(CACHE.with_name("servc_field_unopened.parquet"))
    else:
        df = pd.read_parquet(CACHE)
        path = CACHE.with_name("servc_field_unopened.parquet")
        unopened = pd.read_parquet(path)["cov"] if path.exists() else None
        print(f"[cache] {len(df):,}행 재사용")

    result = survey(df, unopened)
    result["연관도"] = result[["Spearman", "eta2"]].abs().max(axis=1)

    pd.set_option("display.width", 200)
    print("\n" + "=" * 100)
    print("사용 중인 필드 (대조군)")
    print("=" * 100)
    print(
        result[result["사용중"] == "O"]
        .sort_values("연관도", ascending=False)
        .to_string(index=False)
    )

    print("\n" + "=" * 100)
    print(f"미사용 후보 상위 {args.top}")
    print("=" * 100)
    unused = result[result["사용중"] != "O"].sort_values("연관도", ascending=False)
    print(unused.head(args.top).to_string(index=False))

    print("\n" + "=" * 100)
    print("추론 시점 가용성이 낮아 배제해야 할 후보 (미개찰 커버리지 < 0.5)")
    print("=" * 100)
    risky = unused[(unused["연관도"] > 0.02) & (unused["미개찰 커버리지"] < 0.5)]
    print(risky.to_string(index=False) if not risky.empty else "(없음)")

    out = PROJECT_ROOT / "data" / "feature_store" / "servc_field_survey_result.csv"
    result.sort_values("연관도", ascending=False).to_csv(out, index=False)
    print(f"\n전체 결과: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
