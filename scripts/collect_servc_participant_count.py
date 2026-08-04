#!/usr/bin/env python3
"""
용역 개찰결과에서 참가자 수(`prtcptCnum`)를 수집합니다.

설계 문서는 참가자 수가 "조달청 개찰결과 API 에는 존재하나 수집 대상에 들어가
있지 않다" 고 적었습니다. 실제로는 **이미 수집 중인 오퍼레이션
`getScsbidListSttusServc` 가 이 필드를 내려주고 있으며**, `_item_raw_data` 가
전 필드를 `raw_data` 에 담으므로 신규 수집분에는 값이 들어옵니다. 비어 있는
것은 과거 이관분입니다.

이 스크립트는 DB 를 건드리지 않고 API 에서 직접 받아 parquet 으로 떨굽니다.
참가자 수가 낙찰률 잔차를 실제로 설명하는지 먼저 재기 위한 것이며, 스키마
변경 여부는 그 측정 결과를 보고 판단합니다.

사용법:
    .venv/bin/python scripts/collect_servc_participant_count.py
    .venv/bin/python scripts/collect_servc_participant_count.py --start 20250101 --end 20251231
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from src.app.services.api_collector import stream_bid_data  # noqa: E402

# 개찰결과에서 남길 필드. 참가자 수 외에 조인 키와 검증용 낙찰률을 함께 받습니다.
RAW_FIELDS = {
    "prtcptCnum": "prtcpt_cnum",
    "sucsfbidRate": "api_sucsf_bid_rate",
    "bidNtceOrd": "bid_ntce_ord",
}


def _rows_from_batch(batch: list[dict]) -> list[dict]:
    rows = []
    for item in batch:
        raw = item.get("raw_data") or {}
        row = {
            "bid_ntce_no": item.get("bid_ntce_no") or "",
            "rl_openg_dt": item.get("rl_openg_dt"),
        }
        for source, target in RAW_FIELDS.items():
            row[target] = raw.get(source) or None
        rows.append(row)
    return rows


async def collect(start: str, end: str) -> pd.DataFrame:
    collected: list[dict] = []

    def sink(batch: list[dict]) -> None:
        collected.extend(_rows_from_batch(batch))
        print(f"  누적 {len(collected):,}건", end="\r", flush=True)

    await stream_bid_data(start, end, sink, category="Servc")
    print()
    return pd.DataFrame(collected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="20250101")
    parser.add_argument("--end", default="20251231")
    parser.add_argument("--out", default="data/feature_store/servc_participant_count.parquet")
    args = parser.parse_args()

    print(f"용역 개찰결과 수집: {args.start} ~ {args.end}")
    df = asyncio.run(collect(args.start, args.end))
    if df.empty:
        print("수집 결과가 없습니다.")
        return 1

    df["prtcpt_cnum"] = pd.to_numeric(df["prtcpt_cnum"], errors="coerce")
    df["api_sucsf_bid_rate"] = pd.to_numeric(df["api_sucsf_bid_rate"], errors="coerce")
    # 같은 공고가 차수별로 여러 건 나옵니다. 마지막 개찰을 남깁니다.
    df = df.sort_values("rl_openg_dt").drop_duplicates(
        subset=["bid_ntce_no", "bid_ntce_ord"], keep="last"
    )

    present = df["prtcpt_cnum"].notna()
    print(f"\n총 {len(df):,}건 / 참가자 수 보유 {present.sum():,}건 ({present.mean():.1%})")
    if present.any():
        print(
            df.loc[present, "prtcpt_cnum"]
            .describe(percentiles=[0.25, 0.5, 0.75, 0.9, 0.99])
            .round(2)
            .to_string()
        )

    out_path = PROJECT_ROOT / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    print(f"\n저장: {out_path.relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
