#!/usr/bin/env python3
"""
운영 API 경로의 예측 구간을 하한율 집단·낙찰방법별로 나눠 잽니다.

`eval_servc_api_path.py` 는 피복률과 구간 폭을 **전체 한 덩어리로만** 냅니다.
그래서 전역 89.40% 가 집단별로 어떻게 쪼개지는지 알 수 없었습니다.

잔차 진단에서 하한율 결측 집단의 실제 표준편차가 5.38 로 보유 집단 2.84 의
배에 가깝다는 것이 확인됐습니다
([`servc_lwlt_residual_diagnosis_20260806.md`](../docs/design/servc_lwlt_residual_diagnosis_20260806.md)).
산포가 두 배 다른 두 집단에 같은 구간을 주고 있다면 한쪽은 좁아서 못 덮고
다른 쪽은 넓어서 쓸모가 없습니다. 그 여부를 확인합니다.

**측정만 합니다.** 세그먼트별 등각 배율은 이미 실측으로 기각됐습니다(전역
배율이 모든 구간에서 더 안정적). 이 스크립트의 결과가 어떻든 그 기각을 뒤집는
근거로 바로 쓰지 마십시오. 여기서 나올 수 있는 것은 "구간 품질이 집단별로
얼마나 다른가" 라는 사실 확인까지입니다.

`predict_price_api` 를 그대로 호출하므로 특징 생성·모델 선택·구간 산출이
전부 운영과 같은 경로를 탑니다.

사용법:
    .venv/bin/python scripts/eval_servc_interval_by_group.py
    .venv/bin/python scripts/eval_servc_interval_by_group.py --samples 2000
"""

from __future__ import annotations

import argparse
import sys
import warnings
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

warnings.filterwarnings("ignore")

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from dotenv import load_dotenv  # noqa: E402

load_dotenv(PROJECT_ROOT / ".env")

from starlette.requests import Request  # noqa: E402

from scripts.eval_servc_api_path import collect  # noqa: E402
from src.app.api.v1.predictions import predict_price_api  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.app.schemas.predictions import PredictPriceRequest  # noqa: E402
from src.ml.dataset import announcement_feature_payload  # noqa: E402

# 집단 표가 읽히려면 이만큼은 있어야 합니다. 피복률은 비율이라 표본이 작으면
# 표준오차가 커서 90% 와 80% 를 구분하지 못합니다.
MIN_GROUP_ROWS = 50


def _script_predict_request() -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/predictions/predict-price",
            "headers": [],
        }
    )


def summarize(part: pd.DataFrame) -> dict:
    """오차와 구간 품질을 함께 냅니다.

    피복률만 보면 구간을 무한히 넓혀 100% 를 만들 수 있고, 폭만 보면 좁히기만
    하면 이깁니다. 둘을 같이 놓아야 판단이 됩니다.
    """
    inside = (part["actual"] >= part["low"]) & (part["actual"] <= part["high"])
    width = part["high"] - part["low"]
    n = len(part)
    coverage = float(inside.mean())
    return {
        "건수": n,
        "MAE": round(float(part["abs_err"].mean()), 4),
        "0.5%p 적중": round(float((part["abs_err"] <= 0.5).mean()), 4),
        "실제 표준편차": round(float(part["actual"].std()), 3),
        "피복률": round(coverage, 4),
        # 명목 90% 대비 부족분입니다. 음수면 구간이 좁아 못 덮고 있습니다.
        "피복 초과분": round(coverage - 0.90, 4),
        "피복 표준오차": round(float(np.sqrt(coverage * (1 - coverage) / n)), 4) if n else np.nan,
        "구간 폭 중앙값": round(float(width.median()), 4),
    }


def group_table(scored: pd.DataFrame, key: str, min_rows: int = MIN_GROUP_ROWS) -> pd.DataFrame:
    rows = []
    for name, part in scored.groupby(key, observed=True):
        if len(part) < min_rows:
            continue
        rows.append({key: str(name), **summarize(part)})
    if not rows:
        return pd.DataFrame()
    return pd.DataFrame(rows).sort_values("건수", ascending=False)


def report(title: str, frame: pd.DataFrame | str) -> None:
    print(f"\n{'=' * 100}\n{title}\n{'=' * 100}")
    if isinstance(frame, str):
        print(frame)
    elif frame.empty:
        print("표본이 부족해 표를 만들지 않았습니다.")
    else:
        print(frame.to_string(index=False))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=4000)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=42, help="기준선과 같은 표본을 뽑습니다")
    parser.add_argument("--category", default="Servc")
    args = parser.parse_args()

    session = SessionLocal()
    try:
        frame = collect(session, args.year, args.samples, args.seed, args.category)
        if frame.empty:
            print("표본이 없습니다. DB 연결과 연도를 확인하십시오.")
            return 1

        print(f"{args.year}년 {args.category} {len(frame):,}건으로 API 경로를 호출합니다.")

        records = []
        skipped: list[str] = []
        for row in frame.itertuples():
            bid = session.get(BidAnnouncement, int(row.bid_id))
            payload = announcement_feature_payload(bid) if bid else {}
            try:
                response = predict_price_api(
                    PredictPriceRequest(bid_id=int(row.bid_id), user_price="0"),
                    _script_predict_request(),
                    db=session,
                )
            except Exception as exc:
                # 기초금액·예정가격이 모두 없는 공고는 422 로 끊깁니다. 정상 동작이며
                # 채점 표본에서 제외합니다. 건수는 아래 제외 집계로 드러납니다.
                skipped.append(str(exc)[:60])
                continue
            if response.prediction_rate is None:
                continue
            raw_lwlt = payload.get("lwlt_rate")
            missing = raw_lwlt in (None, "", 0, "0")
            records.append(
                {
                    "actual": float(row.actual_rate),
                    "pred": float(response.prediction_rate),
                    "low": response.rate_low,
                    "high": response.rate_high,
                    "coverage": response.interval_coverage,
                    "하한율": "결측" if missing else "보유",
                    "낙찰방법": str(payload.get("sucsfbid_mthd_nm") or "미상"),
                }
            )
    finally:
        session.close()

    scored = pd.DataFrame(records)
    if skipped:
        print(f"제외 {len(skipped)}건 (금액 미공개 등)")
    if scored.empty:
        print("점수를 낼 수 있는 건이 없습니다.")
        return 1

    scored["err"] = scored["pred"] - scored["actual"]
    scored["abs_err"] = scored["err"].abs()
    scored = scored[scored["low"].notna() & scored["high"].notna()]
    if scored.empty:
        print("예측 구간이 있는 건이 없습니다 (분위 아티팩트 확인).")
        return 1

    nominal = scored["coverage"].dropna()
    report(
        "0. 표본",
        f"채점 {len(scored):,}건 / 명목 피복률 {float(nominal.iloc[0]):.0%}"
        if len(nominal)
        else f"채점 {len(scored):,}건",
    )

    report("1. 전체", pd.DataFrame([summarize(scored)]))
    report("2. 하한율 보유 여부별", group_table(scored, "하한율"))
    report(
        "3. 하한율 결측 집단의 낙찰방법별",
        group_table(scored[scored["하한율"] == "결측"], "낙찰방법"),
    )
    report(
        "4. 하한율 보유 집단의 낙찰방법별",
        group_table(scored[scored["하한율"] == "보유"], "낙찰방법"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
