"""용역 raw_data 에서 학습에 쓰이지 않는 필드를 찾고 무조건부 신호를 잽니다.

읽기 전용입니다. DB 는 SELECT 만 실행하고 parquet 과 모델은 건드리지 않습니다.
결과 해석은 docs/design/servc_unused_rawdata_field_audit_20260811.md 를 보십시오.
"""

from __future__ import annotations

import json
import os
import re
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

import pyarrow.parquet as pq
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SAMPLE_LIMIT = 30_000
JOIN_LIMIT = 40_000
MIN_GROUP = 200
MIN_FILL_RATIO = 40.0

# 신호를 잰 제도 플래그입니다. 무조건부 차이는 이득이 아니므로 잔차 상관까지
# 확인해야 합니다. audit_servc_flag_residuals.py 를 이어서 돌리십시오.
FLAGS = (
    "indstrytyLmtYn",
    "prdctClsfcLmtYn",
    "cmmnSpldmdMethdNm",
    "dsgntCmptYn",
    "arsltCmptYn",
    "rbidPermsnYn",
)


def _snake(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", re.sub(r"(?<!^)(?=[A-Z])", "_", name).lower())


def _used_names() -> tuple[set[str], str]:
    parquet = PROJECT_ROOT / "data/feature_store/dataset_Servc.parquet"
    columns = set(pq.ParquetFile(parquet).schema_arrow.names)
    builder = (PROJECT_ROOT / "src/ml/dataset.py").read_text(encoding="utf-8")
    return {_snake(c) for c in columns}, builder


def report_unused(engine, used: set[str], builder: str) -> None:
    filled: Counter[str] = Counter()
    total = 0
    query = text(
        "SELECT raw_data FROM bid_announcements "
        "WHERE category='Servc' AND raw_data IS NOT NULL "
        "ORDER BY id DESC LIMIT :n"
    )
    with engine.connect() as conn:
        for (raw,) in conn.execute(query, {"n": SAMPLE_LIMIT}):
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if not payload:
                continue
            total += 1
            for key, value in payload.items():
                if value not in (None, "", " "):
                    filled[key] += 1

    print(f"표본 {total:,}건, 고유 키 {len(filled)}개\n")
    print(f"{'키':<30}{'채움률':>8}")
    for key, count in sorted(filled.items(), key=lambda item: -item[1]):
        ratio = 100 * count / total
        if ratio < MIN_FILL_RATIO:
            continue
        if _snake(key) in used or f"'{key}'" in builder or f'"{key}"' in builder:
            continue
        print(f"{key:<30}{ratio:>7.1f}%")


def report_signal(engine) -> None:
    groups: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    query = text(
        "SELECT a.raw_data, r.sucsf_bid_rate FROM bid_results r "
        "JOIN bid_announcements a "
        "  ON a.bid_ntce_no = r.bid_ntce_no AND a.category = r.category "
        "WHERE r.category='Servc' AND r.sucsf_bid_rate BETWEEN 70 AND 110 "
        "  AND a.raw_data IS NOT NULL "
        "ORDER BY r.id DESC LIMIT :n"
    )
    total = 0
    with engine.connect() as conn:
        for raw, rate in conn.execute(query, {"n": JOIN_LIMIT}):
            payload = json.loads(raw) if isinstance(raw, str) else raw
            if not payload:
                continue
            total += 1
            for flag in FLAGS:
                value = payload.get(flag)
                if value not in (None, "", " "):
                    groups[flag][str(value)[:22]].append(float(rate))

    print(f"\n조인 표본 {total:,}건\n")
    for flag in FLAGS:
        levels = {k: v for k, v in groups[flag].items() if len(v) >= MIN_GROUP}
        if len(levels) < 2:
            print(f"[{flag}] 유효 수준 부족")
            continue
        pooled = [x for values in levels.values() for x in values]
        overall = st.mean(pooled)
        print(f"[{flag}]  전체 평균 {overall:.3f}")
        for name, values in sorted(levels.items(), key=lambda item: -len(item[1]))[:4]:
            mean = st.mean(values)
            err = st.pstdev(values) / len(values) ** 0.5
            print(
                f"   {name:<24} n={len(values):>6}  평균 {mean:.3f}  "
                f"차 {mean - overall:+.3f}  SE {err:.3f}  t {(mean - overall) / err:+.1f}"
            )
        print()


def main() -> None:
    load_dotenv(PROJECT_ROOT / ".env")
    used, builder = _used_names()
    print("Servc parquet 컬럼", len(used))
    engine = create_engine(os.environ["DATABASE_URL"])
    report_unused(engine, used, builder)
    report_signal(engine)


if __name__ == "__main__":
    main()
