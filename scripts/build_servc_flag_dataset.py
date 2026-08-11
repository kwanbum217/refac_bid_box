#!/usr/bin/env python3
"""용역 파생 parquet 에 제도 플래그 세 개를 덧붙인 실험용 데이터셋을 만듭니다.

`servc_flag_features_holdout_20260811.md` 의 측정을 재현하기 위한 스크립트입니다.
그 실험은 **분할 변동으로 판정되어 특징 추가를 되돌렸으므로**, 세 키는
`src/ml/dataset.py` 의 `INSTITUTION_FIELDS` 에 없습니다. 여기서 자체적으로
매핑을 들고 있는 이유가 그것입니다. 다시 열 근거가 생기면 이 스크립트로
같은 데이터셋을 만들 수 있습니다.

운영 파생 parquet 에는 이 세 필드가 없습니다. 전량 재생성은 비용이 크고 원본을
덮을 위험이 있으므로, 원본은 읽기 전용으로 열고 `bid_announcements.raw_data`
에서 뽑은 플래그를 공고번호로 왼쪽 조인해 **다른 경로**에 새 parquet 을 씁니다.

사용법:
    DATABASE_URL=... uv run python scripts/build_servc_flag_dataset.py \
        --parquet <원본 경로> --output <새 경로>
"""

from __future__ import annotations

import argparse
import os
import time
from pathlib import Path

import pandas as pd
from sqlalchemy import create_engine, text

# 프레임 컬럼명 -> raw_data JSON 키. 특징으로 채택되면 dataset.py 의
# INSTITUTION_FIELDS 로 옮겨야 하며, 그때 이 상수는 지웁니다.
#
# 2025-01 체제 전환이 확인된 prdctClsfcLmtYn 과 rbidPermsnYn 은 제외했습니다.
# 두 체제의 같은 수준이 다른 것을 가리켜 한 범주로 섞을 수 없습니다.
# 근거: docs/design/servc_2025_source_regime_shift_20260811.md
FLAG_FIELDS = {
    "indstrty_lmt_yn": "indstrytyLmtYn",  # 업종 제한 여부
    "cmmn_spldmd_methd_nm": "cmmnSpldmdMethdNm",  # 공동수급 방식
    "dsgnt_cmpt_yn": "dsgntCmptYn",  # 지정경쟁 여부
}
FLAG_COLUMNS = tuple(FLAG_FIELDS)

# 질의문은 리터럴로 둡니다. 키 이름을 f-string 으로 끼워 넣으면 ruff S608 이
# 걸립니다. 대신 FLAG_FIELDS 와 어긋나지 않는지 실행 시점에 확인합니다.
FLAG_QUERY = text(
    """
    SELECT
        bid_ntce_no,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.indstrytyLmtYn')), '') AS indstrty_lmt_yn,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.cmmnSpldmdMethdNm')), '')
            AS cmmn_spldmd_methd_nm,
        NULLIF(JSON_UNQUOTE(JSON_EXTRACT(raw_data, '$.dsgntCmptYn')), '') AS dsgnt_cmpt_yn
    FROM bid_announcements
    WHERE category = 'Servc'
    """
)


def fetch_flags(database_url: str) -> pd.DataFrame:
    for column, json_key in FLAG_FIELDS.items():
        if f"$.{json_key}" not in str(FLAG_QUERY) or f"AS {column}" not in str(FLAG_QUERY):
            raise ValueError(f"질의문이 FLAG_FIELDS 와 어긋납니다: {column} -> {json_key}")
    engine = create_engine(database_url)
    with engine.connect().execution_options(stream_results=True) as connection:
        frames = list(pd.read_sql(FLAG_QUERY, connection, chunksize=200_000))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def collapse_by_notice(flags: pd.DataFrame) -> tuple[pd.DataFrame, dict[str, float]]:
    """공고번호 단위로 접습니다.

    원본 parquet 에는 차수 컬럼이 없어 공고번호로만 붙일 수 있습니다. 같은
    공고번호의 차수 사이에서 값이 갈리면 그 공고는 결측으로 두어 잘못된 값을
    학습에 넣지 않습니다. 갈리는 비율은 함께 돌려주어 문서에 남깁니다.
    """
    stats: dict[str, float] = {}
    grouped = flags.groupby("bid_ntce_no", sort=False)
    out = pd.DataFrame(index=grouped.size().index)
    for column in FLAG_COLUMNS:
        nunique = grouped[column].nunique(dropna=True)
        first = grouped[column].first()
        conflict = nunique > 1
        stats[column] = float(conflict.mean() * 100)
        out[column] = first.where(~conflict)
    return out.reset_index(), stats


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--parquet", required=True, help="원본 용역 파생 parquet (읽기 전용)")
    parser.add_argument("--output", required=True, help="플래그를 덧붙인 새 parquet 경로")
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print("DATABASE_URL 이 필요합니다.")
        return 1

    source = Path(args.parquet)
    target = Path(args.output)
    if not source.exists():
        print(f"원본이 없습니다: {source}")
        return 1
    if target.resolve() == source.resolve():
        print("원본을 덮어쓸 수 없습니다. 다른 경로를 지정하십시오.")
        return 1

    started = time.perf_counter()
    base = pd.read_parquet(source)
    print(f"원본 {len(base):,}행 {len(base.columns)}컬럼 ({time.perf_counter() - started:.1f}초)")

    started = time.perf_counter()
    flags = fetch_flags(database_url)
    print(f"공고 플래그 {len(flags):,}행 조회 ({time.perf_counter() - started:.1f}초)")

    collapsed, conflict_pct = collapse_by_notice(flags)
    for column, pct in conflict_pct.items():
        print(f"  차수 간 값 충돌 {column}: {pct:.4f}%")

    merged = base.merge(collapsed, on="bid_ntce_no", how="left")
    if len(merged) != len(base):
        print(f"조인이 행 수를 바꿨습니다: {len(base):,} -> {len(merged):,}")
        return 1

    for column in FLAG_COLUMNS:
        filled = merged[column].notna().mean() * 100
        print(f"  채움률 {column}: {filled:.2f}%")
        print(f"    수준: {merged[column].value_counts(dropna=False).head(6).to_dict()}")

    target.parent.mkdir(parents=True, exist_ok=True)
    merged.to_parquet(target, index=False)
    print(f"저장: {target} ({len(merged):,}행 {len(merged.columns)}컬럼)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
