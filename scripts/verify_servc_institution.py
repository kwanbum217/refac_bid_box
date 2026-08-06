"""용역 낙찰률 예측 설계의 제도 가정을 데이터로 검증합니다 (V1~V7).

docs/design/g2b_procurement_institution_analysis.md 6.4 절의 검증 항목입니다.

raw_data JSON 을 매 질의마다 파싱하면 200만행 스캔이 반복되므로,
Servc 조인 결과를 물리 테이블(servc_inst_verify)로 한 번만 추출한 뒤 재사용합니다.
이 테이블은 검증 전용이며 운영 스키마를 건드리지 않습니다.

사용법:
    .venv/bin/python scripts/verify_servc_institution.py            # 캐시 있으면 재사용
    .venv/bin/python scripts/verify_servc_institution.py --rebuild  # 추출 테이블 재생성
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

WORK_TABLE = "servc_inst_verify"
REGIME_DATE = "2026-05-26"

# 낙찰하한율 2%p 인상 시행일. 이 날 이후 최초 공고분부터 신 제도가 적용됩니다.
# 근거: 조달청공고 제2026-260호

JSON_FIELDS = {
    "lwlt_rate": "sucsfbidLwltRate",
    "prearng_mthd": "prearngPrceDcsnMthdNm",
    "sucsfbid_mthd_nm": "sucsfbidMthdNm",
    "sucsfbid_mthd_cd": "sucsfbidMthdCd",
    "sucsfbid_mthd_std": "sucsfbidMthdAppStd",
    "srvce_div_nm": "srvceDivNm",
    "lrg_clsfc_nm": "pubPrcrmntLrgClsfcNm",
    "mid_clsfc_nm": "pubPrcrmntMidClsfcNm",
    "clsfc_nm": "pubPrcrmntClsfcNm",
    "bid_prce_evl_rt": "bidPrceEvlRt",
    "tech_ablt_evl_rt": "techAbltEvlRt",
    "tot_prdprc_num": "totPrdprcNum",
    "drwt_prdprc_num": "drwtPrdprcNum",
    "asign_bdgt_amt": "asignBdgtAmt",
    "presmpt_prce_raw": "presmptPrce",
    "intrbid_yn": "intrbidYn",
    "ppsw_gnrl_srvce_yn": "ppswGnrlSrvceYn",
    "pq_eval_yn": "pqEvalYn",
    "tp_eval_yn": "tpEvalYn",
    "rgn_lmt_nm": "rgnLmtBidLocplcJdgmBssNm",
}


def build_work_table(conn) -> None:
    print(f"[build] {WORK_TABLE} 생성 중 (수 분 소요)")
    conn.execute(text(f"DROP TABLE IF EXISTS {WORK_TABLE}"))

    cols = ",\n        ".join(
        f"NULLIF(JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.{src}')), '') AS {alias}"
        for alias, src in JSON_FIELDS.items()
    )
    conn.execute(
        text(
            f"""
        CREATE TABLE {WORK_TABLE} AS
        SELECT
            r.bid_ntce_no,
            r.bid_ntce_ord,
            r.dminstt_nm,
            a.ntce_instt_nm,
            a.bid_ntce_nm,
            a.cntrct_mthd_nm,
            a.bid_methd_nm,
            a.ntce_kind_nm,
            a.presmpt_prce,
            a.base_amount,
            a.bid_ntce_dt,
            a.openg_dt AS ann_openg_dt,
            r.rl_openg_dt,
            r.sucsf_bid_amt,
            r.sucsf_bid_rate,
            {cols}
        FROM bid_results r
        JOIN bid_announcements a
          ON a.bid_ntce_no = r.bid_ntce_no
         AND a.bid_ntce_ord = SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3)
         AND a.category = r.category
        WHERE r.category = 'Servc'
        """  # nosec B608 - 보간값이 모듈 상수입니다
        )
    )
    conn.execute(text(f"CREATE INDEX ix_v_dt ON {WORK_TABLE} (bid_ntce_dt)"))
    conn.execute(text(f"CREATE INDEX ix_v_lwlt ON {WORK_TABLE} (lwlt_rate)"))
    conn.commit()
    print("[build] 완료")


def q(conn, sql: str) -> pd.DataFrame:
    return pd.read_sql(text(sql), conn)


def show(title: str, df: pd.DataFrame, note: str = "") -> None:
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")
    if note:
        print(note)
    if df.empty:
        print("(해당 없음)")
    else:
        print(df.to_string(index=False))


def v0_overview(conn) -> None:
    df = q(
        conn,
        f"""
        SELECT COUNT(*) AS joined_rows,
               SUM(sucsf_bid_rate IS NOT NULL) AS has_rate,
               SUM(lwlt_rate IS NOT NULL AND lwlt_rate <> '0') AS has_lwlt,
               MIN(bid_ntce_dt) AS min_dt, MAX(bid_ntce_dt) AS max_dt
        FROM {WORK_TABLE}
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V0. 조인 표본 개요", df)


def v1_regime(conn) -> None:
    df = q(
        conn,
        f"""
        SELECT CASE WHEN bid_ntce_dt >= '{REGIME_DATE}' THEN 'post_20260526' ELSE 'pre' END AS regime,
               COUNT(*) AS n,
               SUM(sucsf_bid_rate IS NOT NULL) AS n_rate,
               ROUND(AVG(NULLIF(lwlt_rate, '0') + 0), 4) AS avg_lwlt,
               ROUND(AVG(sucsf_bid_rate), 4) AS avg_rate
        FROM {WORK_TABLE}
        GROUP BY regime ORDER BY regime DESC
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V1-a. 제도 레짐별 표본", df)

    df = q(
        conn,
        f"""
        SELECT DATE_FORMAT(bid_ntce_dt, '%Y-%m') AS ym, COUNT(*) AS n,
               ROUND(AVG(NULLIF(lwlt_rate,'0')+0), 4) AS avg_lwlt,
               ROUND(AVG(sucsf_bid_rate), 4) AS avg_rate
        FROM {WORK_TABLE}
        WHERE bid_ntce_dt >= '2026-01-01'
        GROUP BY ym ORDER BY ym
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V1-b. 2026년 월별 하한율·낙찰률 추이 (계단 이동 확인)", df)

    df = q(
        conn,
        f"""
        SELECT CASE WHEN bid_ntce_dt >= '{REGIME_DATE}' THEN 'post' ELSE 'pre' END AS regime,
               lwlt_rate, COUNT(*) AS n
        FROM {WORK_TABLE}
        WHERE bid_ntce_dt >= '2026-01-01' AND lwlt_rate IS NOT NULL AND lwlt_rate <> '0'
        GROUP BY regime, lwlt_rate
        HAVING n >= 50 ORDER BY regime DESC, n DESC
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V1-c. 2026년 레짐 전후 하한율 최빈값", df)


def v2_unknown_rates(conn) -> None:
    for rate in ("88.000", "90.000", "82.995"):
        df = q(
            conn,
            f"""
            SELECT cntrct_mthd_nm, sucsfbid_mthd_nm, srvce_div_nm, lrg_clsfc_nm,
                   COUNT(*) AS n,
                   ROUND(AVG(presmpt_prce)/100000000, 3) AS avg_prce_eok
            FROM {WORK_TABLE}
            WHERE lwlt_rate + 0 = {rate}
            GROUP BY cntrct_mthd_nm, sucsfbid_mthd_nm, srvce_div_nm, lrg_clsfc_nm
            ORDER BY n DESC LIMIT 8
            """,  # nosec B608 - 보간값이 모듈 상수입니다
        )
        show(f"V2. 하한율 {rate} 의 정체", df)

    df = q(
        conn,
        f"""
        SELECT lwlt_rate, COUNT(*) AS n
        FROM {WORK_TABLE}
        WHERE lwlt_rate IS NOT NULL AND lwlt_rate <> '0'
        GROUP BY lwlt_rate ORDER BY n DESC LIMIT 25
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V2-b. 하한율 상위 25개 값", df)


def v3_presmpt_availability(conn) -> None:
    df = q(
        conn,
        f"""
        SELECT prearng_mthd,
               COUNT(*) AS n,
               SUM(presmpt_prce IS NULL OR presmpt_prce = 0) AS presmpt_missing,
               SUM(base_amount IS NULL OR base_amount = 0) AS base_missing,
               ROUND(AVG(sucsf_bid_amt / NULLIF(presmpt_prce, 0)) * 100, 4) AS avg_amt_over_presmpt
        FROM {WORK_TABLE}
        GROUP BY prearng_mthd ORDER BY n DESC
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show(
        "V3-a. 예가결정방법별 금액 필드 결측·비율",
        df,
        "sucsf_bid_amt/presmpt_prce 가 하한율대(88~90) 면 presmpt_prce 는 예정가격,\n"
        "그보다 낮으면(부가세 포함 관계) 추정가격입니다.",
    )

    df = q(
        conn,
        """  # nosec B608 - 보간값이 모듈 상수입니다
        SELECT COUNT(*) AS open_announcements,
               SUM(raw_data IS NOT NULL) AS has_raw,
               SUM(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.presmptPrce')),'') IS NOT NULL) AS has_presmpt,
               SUM(NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.sucsfbidLwltRate')),'') IS NOT NULL) AS has_lwlt
        FROM bid_announcements
        WHERE category = 'Servc' AND openg_dt > NOW()
        """,
    )
    show(
        "V3-b. 미개찰 공고(개찰일시가 미래)의 필드 보유율",
        df,
        "개찰 전에도 presmptPrce 가 채워져 있으면 추론 시점 가용 특징입니다.",
    )


def v4_award_method(conn) -> None:
    df = q(
        conn,
        f"""
        SELECT sucsfbid_mthd_nm, COUNT(*) AS n,
               ROUND(100.0*COUNT(*)/SUM(COUNT(*)) OVER (), 2) AS pct,
               ROUND(AVG(sucsf_bid_rate), 3) AS avg_rate,
               ROUND(STDDEV_SAMP(sucsf_bid_rate), 3) AS sd_rate,
               SUM(lwlt_rate IS NULL OR lwlt_rate='0') AS lwlt_missing
        FROM {WORK_TABLE}
        GROUP BY sucsfbid_mthd_nm ORDER BY n DESC LIMIT 20
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V4-a. 낙찰방법(sucsfbidMthdNm) 분포와 낙찰률 산포", df)

    df = q(
        conn,
        f"""
        SELECT cntrct_mthd_nm, COUNT(*) AS n,
               ROUND(AVG(sucsf_bid_rate), 3) AS avg_rate,
               ROUND(STDDEV_SAMP(sucsf_bid_rate), 3) AS sd_rate
        FROM {WORK_TABLE}
        GROUP BY cntrct_mthd_nm ORDER BY n DESC LIMIT 15
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V4-b. 계약방법별 낙찰률 산포", df)


def v5_negotiation(conn) -> None:
    df = q(
        conn,
        f"""
        SELECT CASE WHEN cntrct_mthd_nm LIKE '%협상%' OR sucsfbid_mthd_nm LIKE '%협상%'
                    THEN 'negotiation' ELSE 'other' END AS kind,
               COUNT(*) AS n,
               ROUND(AVG(sucsf_bid_rate),3) AS avg_rate,
               ROUND(STDDEV_SAMP(sucsf_bid_rate),3) AS sd_rate,
               ROUND(MIN(sucsf_bid_rate),3) AS min_rate,
               ROUND(MAX(sucsf_bid_rate),3) AS max_rate
        FROM {WORK_TABLE}
        WHERE sucsf_bid_rate IS NOT NULL
        GROUP BY kind
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V5-a. 협상에 의한 계약 vs 그 외 낙찰률 산포", df)

    df = q(
        conn,
        f"""
        SELECT tech_ablt_evl_rt, bid_prce_evl_rt, COUNT(*) AS n,
               ROUND(AVG(sucsf_bid_rate),3) AS avg_rate,
               ROUND(STDDEV_SAMP(sucsf_bid_rate),3) AS sd_rate
        FROM {WORK_TABLE}
        WHERE tech_ablt_evl_rt IS NOT NULL AND tech_ablt_evl_rt <> '0'
        GROUP BY tech_ablt_evl_rt, bid_prce_evl_rt
        ORDER BY n DESC LIMIT 15
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show(
        "V5-b. 기술능력/입찰가격 평가비율별 낙찰률",
        df,
        "techAbltEvlRt·bidPrceEvlRt 는 협상 계약의 배점 비율입니다. 특징 후보입니다.",
    )


def v6_base_amount(conn) -> None:
    df = q(
        conn,
        f"""
        SELECT COUNT(*) AS n,
               SUM(base_amount IS NOT NULL AND base_amount <> 0) AS base_amount_present,
               SUM(asign_bdgt_amt IS NOT NULL) AS asign_bdgt_present,
               ROUND(AVG(base_amount / NULLIF(presmpt_prce,0)), 5) AS base_over_presmpt,
               ROUND(AVG(asign_bdgt_amt / NULLIF(presmpt_prce,0)), 5) AS bdgt_over_presmpt
        FROM {WORK_TABLE}
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show(
        "V6-a. 기초금액 대체 후보 필드 보유율",
        df,
        "기초금액(bsisAmount) 키는 raw_data 에 없습니다. base_amount/asignBdgtAmt 가 대체 후보입니다.",
    )

    df = q(
        conn,
        f"""
        SELECT tot_prdprc_num, drwt_prdprc_num, COUNT(*) AS n
        FROM {WORK_TABLE}
        WHERE tot_prdprc_num IS NOT NULL
        GROUP BY tot_prdprc_num, drwt_prdprc_num ORDER BY n DESC LIMIT 10
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show(
        "V6-b. 복수예비가격 개수 구조 (totPrdprcNum / drwtPrdprcNum)",
        df,
        "제도 설계서 4장의 '15개 중 4개 추첨' 가정을 데이터로 확인합니다.",
    )


def v7_category(conn) -> None:
    df = q(
        conn,
        f"""
        SELECT srvce_div_nm, COUNT(*) AS n,
               COUNT(DISTINCT lwlt_rate) AS distinct_lwlt,
               ROUND(AVG(NULLIF(lwlt_rate,'0')+0),3) AS avg_lwlt,
               ROUND(AVG(sucsf_bid_rate),3) AS avg_rate,
               ROUND(STDDEV_SAMP(sucsf_bid_rate),3) AS sd_rate
        FROM {WORK_TABLE}
        GROUP BY srvce_div_nm ORDER BY n DESC LIMIT 15
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show(
        "V7-a. 용역구분명(srvceDivNm)별 하한율·낙찰률",
        df,
        "설계서 8.2 의 svc_category 를 텍스트 마이닝 없이 대체할 수 있는지 확인합니다.",
    )

    df = q(
        conn,
        f"""
        SELECT lrg_clsfc_nm, COUNT(*) AS n,
               ROUND(AVG(NULLIF(lwlt_rate,'0')+0),3) AS avg_lwlt,
               ROUND(AVG(sucsf_bid_rate),3) AS avg_rate
        FROM {WORK_TABLE}
        WHERE lrg_clsfc_nm IS NOT NULL
        GROUP BY lrg_clsfc_nm ORDER BY n DESC LIMIT 15
        """,  # nosec B608 - 보간값이 모듈 상수입니다
    )
    show("V7-b. 공공조달 대분류(pubPrcrmntLrgClsfcNm)별 지표", df)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rebuild", action="store_true", help="추출 테이블 재생성")
    args = parser.parse_args()

    load_dotenv()
    engine = create_engine(os.environ["DATABASE_URL"])
    with engine.connect() as conn:
        exists = conn.execute(
            text(
                "SELECT COUNT(*) FROM information_schema.tables "
                "WHERE table_schema = DATABASE() AND table_name = :t"
            ),
            {"t": WORK_TABLE},
        ).scalar()
        if args.rebuild or not exists:
            build_work_table(conn)

        v0_overview(conn)
        v1_regime(conn)
        v2_unknown_rates(conn)
        v3_presmpt_availability(conn)
        v4_award_method(conn)
        v5_negotiation(conn)
        v6_base_amount(conn)
        v7_category(conn)


if __name__ == "__main__":
    main()
