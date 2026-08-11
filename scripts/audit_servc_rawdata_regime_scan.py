"""용역 raw_data 의 나머지 필드 전수에서 2025-01 형 계단식 전환을 찾습니다.

`docs/design/servc_2025_source_regime_shift_20260811.md` 에서 세 필드
(`prdctClsfcLmtYn`, `rbidPermsnYn`, `sucsfbidLwltRate`)가 2025-01 을 경계로
계단식 전환을 겪은 것이 확인됐습니다. 이 스크립트는 아직 그 추적을 하지
않은 나머지 필드 전부를 훑습니다.

대상 필드는 두 묶음입니다.
1. `scripts/survey_servc_fields.py` 의 `IN_USE` + `CANDIDATES` (51개) 중
   `docs/design/servc_2025_source_regime_shift_20260811.md` 에서 이미
   월별 추적을 마친 11개를 뺀 나머지
2. `scripts/audit_servc_raw_data_keys.py` 실행으로 확인된, 지금까지 한 번도
   조사되지 않은 52개 키(정규 컬럼으로 옮겨 담기는 `COLUMN_MAPPED` 12개는
   이미 쓰는 값이라 제외)

`audit_servc_flag_regime.py` 는 필드 하나마다 `SUM(JSON_EXTRACT(...)='Y')`
전체 스캔 쿼리를 날립니다. 77만 행(2023년 이후 Servc)에서 필드 하나당
40~50초가 걸려 92개 필드를 다 돌리면 감당이 안 됩니다. 이 스크립트는 대신
**월별로 표본을 떠서** `raw_data` 원문을 그대로 가져온 뒤 파이썬에서 모든
필드를 한 번에 집계합니다. 월 하나에 표본 3,000행이면 쿼리가 0.1초 안팎이라
92개 필드를 합쳐도 왕복 비용이 월 수(약 44개월) 만큼만 듭니다.

계단식 전환의 정의(이 스크립트 안에서 고정):
    인접한 두 달 사이에 **값 존재율** 또는 (존재하는 값 중) **최빈값 비중**의
    변화폭이 20%p 이상이면 급변으로 표시합니다. 존재율만 보면
    `prdctClsfcLmtYn` 처럼 항상 채워져 있으면서 값 구성만 뒤집히는 경우를
    놓치므로 최빈값 비중도 함께 봅니다.

사용법:
    uv run python scripts/audit_servc_rawdata_regime_scan.py

읽기 전용입니다. SELECT 만 실행하며 parquet, 모델, 원본은 건드리지 않습니다.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import create_engine, text

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.audit_servc_raw_data_keys import COLUMN_MAPPED  # noqa: E402
from scripts.survey_servc_fields import CANDIDATES, IN_USE  # noqa: E402

SINCE_YEAR, SINCE_MONTH = 2023, 1
UNTIL_YEAR, UNTIL_MONTH = 2026, 8  # 2026-08 은 부분월. 현행 감사 문서와 맞춥니다.
SAMPLE_PER_MONTH = 3_000
JUMP_THRESHOLD = 20.0  # %p. 위 docstring 의 정의.
MIN_EXISTING_FOR_TOP = 200  # 이 미만이면 최빈값비중이 표본잡음으로 0%/100% 를 오간다

# docs/design/servc_2025_source_regime_shift_20260811.md 3.1, 3.2 에서 이미
# 월별 추적을 마친 필드입니다. 세 개는 전환 확인, 여덟 개는 무전환입니다.
ALREADY_TRACKED = {
    "prdctClsfcLmtYn",
    "rbidPermsnYn",
    "sucsfbidLwltRate",
    "indstrytyLmtYn",
    "dsgntCmptYn",
    "cmmnSpldmdMethdNm",
    "sucsfbidMthdNm",
    "prearngPrceDcsnMthdNm",
    "intrbidYn",
    "srvceDivNm",
    "totPrdprcNum",
}

# 2026-08-11 raw_data 키 전수 조사(audit_servc_raw_data_keys.py, 표본
# 연도별 5,000~20,000행)에서 확인된 113개 키 중, ALL_FIELDS 와
# COLUMN_MAPPED 어디에도 없던 52개입니다. `data/analysis/servc_raw_data_keys/
# keys_공고.csv` 의 in_use=False & surveyed=False 행과 동일합니다.
NEVER_SURVEYED = {
    "arsltReqstdocRcptDt",
    "bidNtceDtlUrl",
    "bidNtceUrl",
    "chgDt",
    "cmmnSpldmdAgrmntClseDt",
    "cmmnSpldmdMethdCd",
    "crdtrNm",
    "dcmtgOprtnDt",
    "dcmtgOprtnPlce",
    "dminsttCd",
    "dminsttOfclEmailAdrs",
    "indutyVAT",
    "jntcontrctDutyRgnNm1",
    "jntcontrctDutyRgnNm2",
    "jntcontrctDutyRgnNm3",
    "mnfctYn",
    "ntceDscrptYn",
    "ntceInsttCd",
    "ntceInsttOfclEmailAdrs",
    "ntceInsttOfclTelNo",
    "ntceSpecDocUrl1",
    "ntceSpecDocUrl10",
    "ntceSpecDocUrl2",
    "ntceSpecDocUrl3",
    "ntceSpecDocUrl4",
    "ntceSpecDocUrl5",
    "ntceSpecDocUrl6",
    "ntceSpecDocUrl7",
    "ntceSpecDocUrl8",
    "ntceSpecDocUrl9",
    "ntceSpecFileNm1",
    "ntceSpecFileNm10",
    "ntceSpecFileNm2",
    "ntceSpecFileNm3",
    "ntceSpecFileNm4",
    "ntceSpecFileNm5",
    "ntceSpecFileNm6",
    "ntceSpecFileNm7",
    "ntceSpecFileNm8",
    "ntceSpecFileNm9",
    "pqApplDocRcptDt",
    "pqApplDocRcptMthdNm",
    "pubPrcrmntClsfcNo",
    "purchsObjPrdctList",
    "refNo",
    "rgnDutyJntcontrctRt",
    "rgnLmtBidLocplcJdgmBssCd",
    "rgstTyNm",
    "stdNtceDocUrl",
    "sucsfbidMthdCd",
    "tpEvalApplClseDt",
    "tpEvalApplMthdNm",
}


def build_field_list() -> list[str]:
    all_surveyed = set(IN_USE) | set(CANDIDATES)
    remaining_surveyed = sorted(all_surveyed - ALREADY_TRACKED)
    fresh = sorted(NEVER_SURVEYED - set(COLUMN_MAPPED))
    return remaining_surveyed + fresh


@dataclass
class MonthStat:
    ym: str
    total: int = 0
    existing: int = 0
    values: Counter[str] = field(default_factory=Counter)

    @property
    def existence_rate(self) -> float:
        return 100 * self.existing / self.total if self.total else 0.0

    @property
    def top_value_share(self) -> float:
        if not self.existing:
            return 0.0
        top = self.values.most_common(1)[0][1]
        return 100 * top / self.existing

    @property
    def top_value(self) -> str:
        if not self.values:
            return "-"
        return self.values.most_common(1)[0][0]


def month_range() -> list[tuple[int, int]]:
    months = []
    y, m = SINCE_YEAR, SINCE_MONTH
    while (y, m) <= (UNTIL_YEAR, UNTIL_MONTH):
        months.append((y, m))
        m += 1
        if m > 12:
            m = 1
            y += 1
    return months


def normalize_value(val: object) -> str:
    """숫자 값의 JSON 타입 표기 차이(4 vs 4.0)를 하나로 합칩니다.

    같은 값이 월에 따라 int/float 로 다르게 파싱되면 최빈값비중 계산이
    실제 전환 없이도 흔들립니다. drwtPrdprcNum 에서 '4.0' -> '4' 가 그
    사례였습니다.
    """
    text_val = str(val)
    try:
        num = float(text_val)
    except ValueError:
        return text_val
    return str(int(num)) if num.is_integer() else text_val


def month_bounds(y: int, m: int) -> tuple[str, str]:
    start = f"{y:04d}-{m:02d}-01"
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    end = f"{ny:04d}-{nm:02d}-01"
    return start, end


def collect(engine, fields: list[str]) -> dict[str, list[MonthStat]]:
    per_field: dict[str, list[MonthStat]] = {f: [] for f in fields}
    sql = text(
        "SELECT raw_data FROM bid_announcements "  # noqa: S608
        "WHERE category='Servc' AND raw_data IS NOT NULL "
        "AND bid_ntce_dt >= :start AND bid_ntce_dt < :end "
        f"LIMIT {SAMPLE_PER_MONTH}"
    )
    with engine.connect() as conn:
        for y, m in month_range():
            start, end = month_bounds(y, m)
            rows = conn.execute(sql, {"start": start, "end": end}).fetchall()
            ym = f"{y:04d}-{m:02d}"
            stats = {f: MonthStat(ym=ym) for f in fields}
            for (raw,) in rows:
                payload = raw if isinstance(raw, dict) else json.loads(raw)
                for f in fields:
                    st = stats[f]
                    st.total += 1
                    val = payload.get(f)
                    if val not in (None, ""):
                        st.existing += 1
                        st.values[normalize_value(val)] += 1
            for f in fields:
                per_field[f].append(stats[f])
            print(f"[collect] {ym} 표본 {len(rows):,}행", flush=True)
    return per_field


@dataclass
class Jump:
    field: str
    ym: str
    metric: str
    before: float
    after: float
    before_top: str
    after_top: str


def detect_jumps(per_field: dict[str, list[MonthStat]]) -> list[Jump]:
    jumps: list[Jump] = []
    for f, months in per_field.items():
        prev: MonthStat | None = None
        for cur in months:
            if prev is not None and cur.total and prev.total:
                d_exist = cur.existence_rate - prev.existence_rate
                if abs(d_exist) >= JUMP_THRESHOLD:
                    jumps.append(
                        Jump(
                            f,
                            cur.ym,
                            "존재율",
                            prev.existence_rate,
                            cur.existence_rate,
                            prev.top_value,
                            cur.top_value,
                        )
                    )
                d_top = cur.top_value_share - prev.top_value_share
                enough_sample = (
                    prev.existing >= MIN_EXISTING_FOR_TOP
                    and cur.existing >= MIN_EXISTING_FOR_TOP
                )
                if enough_sample and abs(d_top) >= JUMP_THRESHOLD:
                    jumps.append(
                        Jump(
                            f,
                            cur.ym,
                            "최빈값비중",
                            prev.top_value_share,
                            cur.top_value_share,
                            prev.top_value,
                            cur.top_value,
                        )
                    )
            prev = cur
    return jumps


def make_engine():
    load_dotenv(PROJECT_ROOT / ".env")
    return create_engine(os.environ["DATABASE_URL"], pool_pre_ping=True)


def main() -> int:
    fields = build_field_list()
    print(f"대상 필드 {len(fields)}개 (기존 조사 11개 제외)")
    print(f"표본: 월별 최대 {SAMPLE_PER_MONTH:,}행, 급변 임계 {JUMP_THRESHOLD}p")

    engine = make_engine()
    per_field = collect(engine, fields)
    jumps = detect_jumps(per_field)

    in_use_fields = set(IN_USE)
    print("\n" + "=" * 76)
    print(f"급변 검출 {len(jumps)}건")
    print("=" * 76)
    for j in sorted(jumps, key=lambda x: (x.field, x.ym)):
        used = "학습사용" if j.field in in_use_fields else "미사용"
        print(
            f"[{used}] {j.field:32s} {j.ym} {j.metric:8s} "
            f"{j.before:6.1f}% -> {j.after:6.1f}%   "
            f"({j.before_top!r} -> {j.after_top!r})"
        )

    used_jumps = [j for j in jumps if j.field in in_use_fields]
    print(f"\n학습 사용 필드 중 급변: {len(used_jumps)}건 "
          f"({sorted({j.field for j in used_jumps})})")

    out_dir = PROJECT_ROOT / "data" / "analysis" / "servc_rawdata_regime_scan"
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "jumps.csv").open("w", encoding="utf-8") as fh:
        fh.write("field,ym,metric,before,after,before_top,after_top,in_use\n")
        for j in jumps:
            used = j.field in in_use_fields
            fh.write(
                f"{j.field},{j.ym},{j.metric},{j.before:.2f},{j.after:.2f},"
                f'"{j.before_top}","{j.after_top}",{used}\n'
            )
    print(f"\n기록: {(out_dir / 'jumps.csv').relative_to(PROJECT_ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
