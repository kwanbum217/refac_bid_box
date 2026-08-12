"""용역 학습 프레임에서 비예가 공고가 어느 조인 단계에서 떨어지는지 셉니다.

`data/feature_store/dataset_Servc.parquet` 에는 비예가가 전 기간 2,405건뿐이고
2025년 이후로는 0건입니다. 같은 기간 `bid_announcements` 에서 비예가는 매년
4만~5만건, 용역 공고의 약 30% 를 차지합니다. 관측 근거는
`docs/design/servc_training_frame_population_gap_20260811.md` 입니다.

`src/ml/dataset.py:169-227` 의 학습 프레임은 아래 조건만으로 만들어집니다.
비예가를 배제하는 명시적 WHERE 는 없습니다. 그렇다면 이 중 무엇이 비예가를
떨어뜨리는지 단계별로 세어 봐야 합니다.

    S0  공고 모집단              bid_announcements (category=Servc)
    S1  + 공고번호 일치 결과 존재  r.bid_ntce_no = a.bid_ntce_no
    S2  + 차수 정규화 일치        SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3) = a.bid_ntce_ord
    S3  + 업무구분 일치           r.category = a.category
    S4  + 낙찰률 비결측           r.sucsf_bid_rate IS NOT NULL
    S5  + 낙찰률 유효구간         70 <= r.sucsf_bid_rate <= 110
    S6  + 추정가격 유효구간       100,000 <= a.presmpt_prce <= 1,000,000,000,000

S6 까지 살아남은 공고가 학습 프레임에 들어갑니다. 단계 사이 낙폭이 가장 큰
곳이 원인입니다.

집계 축은 두 개입니다.

1. **예가결정방법**(`prearngPrceDcsnMthdNm`). 복수예가/단일예가를 대조군으로
   함께 세어야 비예가만 떨어지는지, 전체가 떨어지는데 비예가가 더 심한지
   구분됩니다.
2. **공고연도**(`bid_ntce_dt`). 2025년에 0 이 되는 계단이 있으므로 전 기간
   합계만 보면 원인을 놓칩니다.

판별 필드의 위치에 주의하십시오. `prearngPrceDcsnMthdNm` 은
`bid_announcements.raw_data` JSON 안에만 있습니다. `bid_results` 쪽에는 없어
결과 테이블 단독으로는 비예가를 판별할 수 없습니다
(`docs/design/servc_raw_data_key_audit_20260809.md` 2장: 결과 `raw_data` 는
2025년 이후 16.55% 만 채워져 있고 담긴 20종이 전부 개찰 후 확정값입니다).
그래서 이 스크립트는 **공고 쪽에서 출발해** 결과를 EXISTS 로 붙입니다.

사용법:
    uv run python scripts/audit_servc_nonprearng_join.py
    uv run python scripts/audit_servc_nonprearng_join.py --since 2020 --until 2026

읽기 전용입니다. SELECT 만 실행하며 parquet, 모델, 원본은 건드리지 않습니다.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# src/ml/dataset.py 의 정제 상수와 같은 값이어야 합니다. 어긋나면 단계별 낙폭이
# 실제 학습 프레임과 달라집니다.
MIN_WINNING_RATE = 70.0
MAX_WINNING_RATE = 110.0
MIN_PRESMPT_PRCE = 100_000
MAX_PRESMPT_PRCE = 1_000_000_000_000

DEFAULT_SINCE = 2015
DEFAULT_UNTIL = 2026

# 표에 이 순서로 싣습니다. 그 밖의 값과 결측은 '기타'로 접습니다.
PREARNG_ORDER = ("복수예가", "단일예가", "비예가", "기타")

STAGE_LABELS = (
    ("s0", "S0 공고 모집단"),
    ("s1", "S1 +공고번호 일치"),
    ("s2", "S2 +차수 정규화 일치"),
    ("s3", "S3 +업무구분 일치"),
    ("s4", "S4 +낙찰률 비결측"),
    ("s5", "S5 +낙찰률 70~110"),
    ("s6", "S6 +추정가격 유효"),
)

# 결과 테이블을 붙이는 조건을 단계별로 누적합니다. 각 단계는 앞 단계의 조건을
# 전부 포함합니다.
_R_NO = "r.bid_ntce_no = a.bid_ntce_no"
_R_ORD = "SUBSTR(CONCAT('000', r.bid_ntce_ord), -3, 3) = a.bid_ntce_ord"
_R_CAT = "r.category = a.category"
_R_RATE_NOTNULL = "r.sucsf_bid_rate IS NOT NULL"
_R_RATE_RANGE = f"r.sucsf_bid_rate BETWEEN {MIN_WINNING_RATE} AND {MAX_WINNING_RATE}"
_A_PRICE = f"a.presmpt_prce BETWEEN {MIN_PRESMPT_PRCE} AND {MAX_PRESMPT_PRCE}"

_STAGE_RESULT_CONDS = {
    "s1": [_R_NO],
    "s2": [_R_NO, _R_ORD],
    "s3": [_R_NO, _R_ORD, _R_CAT],
    "s4": [_R_NO, _R_ORD, _R_CAT, _R_RATE_NOTNULL],
    "s5": [_R_NO, _R_ORD, _R_CAT, _R_RATE_RANGE],
    "s6": [_R_NO, _R_ORD, _R_CAT, _R_RATE_RANGE],
}

# 공고 쪽 단독 조건. 결과 EXISTS 와 AND 로 묶습니다.
_STAGE_ANN_CONDS = {"s6": [_A_PRICE]}

PREARNG_EXPR = "NULLIF(JSON_UNQUOTE(JSON_EXTRACT(a.raw_data, '$.prearngPrceDcsnMthdNm')), '')"


def _exists(conds: list[str]) -> str:
    where = " AND ".join(conds)
    return f"EXISTS (SELECT 1 FROM bid_results r WHERE {where})"  # noqa: S608


def _stage_expr(stage: str) -> str:
    parts = [_exists(_STAGE_RESULT_CONDS[stage])]
    parts.extend(_STAGE_ANN_CONDS.get(stage, []))
    return " AND ".join(parts)


def build_stage_sql() -> str:
    """연도 하나 분량의 단계별 잔존 건수를 한 번에 집계하는 SQL 을 만듭니다."""
    stage_cols = ",\n            ".join(
        f"SUM({_stage_expr(stage)}) AS {stage}" for stage, _ in STAGE_LABELS if stage != "s0"
    )
    return (
        "SELECT\n"
        f"            {PREARNG_EXPR} AS prearng,\n"
        "            COUNT(*) AS s0,\n"
        f"            {stage_cols}\n"
        "        FROM bid_announcements a\n"
        "        WHERE a.category = 'Servc'\n"
        "          AND a.bid_ntce_dt >= :start AND a.bid_ntce_dt < :end\n"
        "        GROUP BY prearng"
    )


def build_rate_null_sql() -> str:
    """S3 를 통과한 공고에서 낙찰률이 왜 빠지는지 나눠 봅니다.

    S3 -> S4 낙폭이 결측 때문인지, S4 -> S5 낙폭이 구간 이탈 때문인지를
    한 표로 확인하기 위한 보조 집계입니다.
    """
    joined = _exists(_STAGE_RESULT_CONDS["s3"])
    rate_null = _exists([*_STAGE_RESULT_CONDS["s3"], "r.sucsf_bid_rate IS NULL"])
    rate_zero = _exists([*_STAGE_RESULT_CONDS["s3"], "r.sucsf_bid_rate = 0"])
    price_null = "a.presmpt_prce IS NULL"
    return (
        "SELECT\n"
        f"            {PREARNG_EXPR} AS prearng,\n"
        f"            SUM({joined}) AS joined_cnt,\n"
        f"            SUM({rate_null}) AS rate_null,\n"
        f"            SUM({rate_zero}) AS rate_zero,\n"
        f"            SUM({price_null}) AS price_null,\n"
        f"            SUM({joined} AND {price_null}) AS joined_price_null\n"
        "        FROM bid_announcements a\n"
        "        WHERE a.category = 'Servc'\n"
        "          AND a.bid_ntce_dt >= :start AND a.bid_ntce_dt < :end\n"
        "        GROUP BY prearng"
    )


def _bucket(prearng: str | None) -> str:
    return prearng if prearng in PREARNG_ORDER else "기타"


def _fold(rows, keys: tuple[str, ...]) -> dict[str, dict[str, int]]:
    """예가결정방법을 표기 순서대로 접습니다."""
    folded: dict[str, dict[str, int]] = {name: dict.fromkeys(keys, 0) for name in PREARNG_ORDER}
    for row in rows:
        target = folded[_bucket(row["prearng"])]
        for key in keys:
            target[key] += int(row[key] or 0)
    return folded


def _pct(part: int, whole: int) -> str:
    return "-" if not whole else f"{part / whole * 100:.2f}%"


def _print_stage_table(title: str, folded: dict[str, dict[str, int]]) -> None:
    print(f"\n### {title}\n")
    header = "| 단계 | " + " | ".join(f"{n} | {n} 잔존율" for n in PREARNG_ORDER) + " |"
    print(header)
    print("| --- | " + " | ".join(["---:"] * (len(PREARNG_ORDER) * 2)) + " |")
    for stage, label in STAGE_LABELS:
        cells = []
        for name in PREARNG_ORDER:
            count = folded[name][stage]
            cells.append(f"{count:,}")
            cells.append(_pct(count, folded[name]["s0"]))
        print(f"| {label} | " + " | ".join(cells) + " |")


def run(since: int, until: int) -> None:
    load_dotenv()
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise SystemExit("DATABASE_URL 이 없습니다. .env 를 확인하십시오.")

    engine = create_engine(url, pool_pre_ping=True)
    stage_sql = text(build_stage_sql())
    diag_sql = text(build_rate_null_sql())
    stage_keys = tuple(stage for stage, _ in STAGE_LABELS)
    diag_keys = ("joined_cnt", "rate_null", "rate_zero", "price_null", "joined_price_null")

    total_stage = {name: dict.fromkeys(stage_keys, 0) for name in PREARNG_ORDER}
    total_diag = {name: dict.fromkeys(diag_keys, 0) for name in PREARNG_ORDER}

    print("# 용역 비예가 조인 단계별 잔존 건수")
    print(f"\n대상: bid_announcements category=Servc, 공고연도 {since}~{until}")

    with engine.connect() as conn:
        for year in range(since, until + 1):
            params = {"start": f"{year}-01-01", "end": f"{year + 1}-01-01"}
            rows = conn.execute(stage_sql, params).mappings().all()
            folded = _fold(rows, stage_keys)
            _print_stage_table(f"공고연도 {year}", folded)
            for name in PREARNG_ORDER:
                for key in stage_keys:
                    total_stage[name][key] += folded[name][key]

            drows = conn.execute(diag_sql, params).mappings().all()
            dfolded = _fold(drows, diag_keys)
            for name in PREARNG_ORDER:
                for key in diag_keys:
                    total_diag[name][key] += dfolded[name][key]

    _print_stage_table(f"전 기간 합계 {since}~{until}", total_stage)

    print("\n### 낙찰률·추정가격 결측 진단 (전 기간 합계)\n")
    print(
        "| 예가결정방법 | S3 조인 성공 | 낙찰률 결측 | 낙찰률 0 | 추정가격 결측 | 조인+추정가격 결측 |"
    )
    print("| --- | ---: | ---: | ---: | ---: | ---: |")
    for name in PREARNG_ORDER:
        d = total_diag[name]
        print(
            f"| {name} | {d['joined_cnt']:,} | {d['rate_null']:,} | {d['rate_zero']:,} "
            f"| {d['price_null']:,} | {d['joined_price_null']:,} |"
        )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--since", type=int, default=DEFAULT_SINCE, help="시작 공고연도")
    parser.add_argument("--until", type=int, default=DEFAULT_UNTIL, help="종료 공고연도(포함)")
    args = parser.parse_args()
    run(args.since, args.until)


if __name__ == "__main__":
    main()
