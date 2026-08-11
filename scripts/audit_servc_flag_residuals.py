"""용역 제도 플래그가 현행 모델 잔차에 남기는 편향을 잽니다.

무조건부 차이는 기존 특징에 흡수됐을 수 있으므로, 저장된 운영 잔차에 플래그를
붙여 다시 잽니다. 여기서 유의하지 않으면 그 축은 닫힙니다.

사용법:
    uv run python scripts/audit_servc_flag_residuals.py [연도]

읽기 전용입니다. 결과 해석은
docs/design/servc_unused_rawdata_field_audit_20260811.md 4.1, 4.2 를 보십시오.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CHUNK = 5_000
MIN_GROUP = 200

FLAGS = (
    "prdctClsfcLmtYn",
    "cmmnSpldmdMethdNm",
    "dsgntCmptYn",
    "indstrytyLmtYn",
    "rbidPermsnYn",
)


def load_residuals(year: str) -> pd.DataFrame:
    path = PROJECT_ROOT / f"data/analysis/servc_residuals/servc_residuals_{year}.parquet"
    return pd.read_parquet(path, columns=["bid_ntce_no", "actual", "pred", "err", "abs_err"])


def load_flags(engine, notices: list[str]) -> pd.DataFrame:
    # 필드명은 이 모듈의 FLAGS 상수로만 정해지고 외부 입력이 닿지 않습니다.
    selected = ", ".join(
        f"JSON_UNQUOTE(JSON_EXTRACT(raw_data,'$.{flag}')) AS {flag}" for flag in FLAGS
    )
    # 식별자는 FLAGS 상수이고 값은 바인딩 파라미터입니다.
    sql = (
        f"SELECT bid_ntce_no, {selected} FROM bid_announcements "  # noqa: S608
        "WHERE category='Servc' AND bid_ntce_no IN :notices"
    )
    query = text(sql)
    rows: list[dict] = []
    with engine.connect() as conn:
        for start in range(0, len(notices), CHUNK):
            chunk = tuple(notices[start : start + CHUNK])
            rows += [dict(r._mapping) for r in conn.execute(query, {"notices": chunk})]
    return pd.DataFrame(rows).drop_duplicates("bid_ntce_no")


def report(merged: pd.DataFrame) -> None:
    print(f"\n전체 err 평균 {merged['err'].mean():+.4f}  MAE {merged['abs_err'].mean():.4f}\n")
    for flag in FLAGS:
        subset = merged[merged[flag].notna() & (merged[flag] != "")]
        if len(subset) < MIN_GROUP:
            print(f"{flag}: 표본 부족")
            continue
        print(f"[{flag}]")
        levels = sorted(subset.groupby(flag), key=lambda item: -len(item[1]))
        for value, group in levels[:4]:
            if len(group) < MIN_GROUP:
                continue
            mean = group["err"].mean()
            err = group["err"].std(ddof=1) / len(group) ** 0.5
            print(
                f"   {str(value)[:22]:<24} n={len(group):>6}  err {mean:+.4f}  "
                f"SE {err:.4f}  t {mean / err:+.2f}  MAE {group['abs_err'].mean():.4f}"
            )
        print()


def main() -> None:
    year = sys.argv[1] if len(sys.argv) > 1 else "2025"
    load_dotenv(PROJECT_ROOT / ".env")
    residuals = load_residuals(year)
    print(f"잔차 표본 {len(residuals):,} ({year}년)")

    engine = create_engine(os.environ["DATABASE_URL"])
    notices = residuals["bid_ntce_no"].dropna().unique().tolist()
    flags = load_flags(engine, notices)

    merged = residuals.merge(flags, on="bid_ntce_no", how="inner")
    print(f"조인 성공 {len(merged):,} ({100 * len(merged) / len(residuals):.1f}%)")
    report(merged)


if __name__ == "__main__":
    main()
