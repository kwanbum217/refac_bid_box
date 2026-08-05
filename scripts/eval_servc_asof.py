#!/usr/bin/env python3
"""
운영 성능을 **예측 시점 기준 이력**으로 다시 잽니다.

문제는 이렇습니다. 서빙은 집계 표(`institution_win_rate_stats`)의 **현재 시점**
값을 씁니다. 실제 서비스는 미개찰 공고를 예측하므로 그것이 정확합니다. 그러나
평가는 2025년 공고를 대상으로 하므로, 모델이 학습 때 본 "그 시점까지의 이력"
대신 "2026년까지 쌓인 이력" 을 받습니다.

학습 계산이 as-of 정의와 일치함은 확인했습니다(상관 0.9999,
`verify_asof_history_parity.py`). 그러므로 평가에서 그 시점 값을 주입하면
**실제 서비스가 겪는 조건**이 재현됩니다.

`build_feature_dict` 는 payload 에 값이 있으면 조회를 건너뜁니다. 그 성질을
그대로 씁니다. API 를 고치지 않고 평가 경로에서만 주입합니다.

두 조건을 같은 표본에서 재고 차이를 봅니다.

    현행 평가   서빙 조회값 (현재 시점 이력)
    as-of 평가  그 공고 개찰일 기준 이력

as-of 쪽이 좋으면 지금까지의 운영 측정치가 실제를 과소평가한 것입니다.

사용법:
    .venv/bin/python scripts/eval_servc_asof.py --samples 2000
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
from sqlalchemy import text  # noqa: E402

from scripts.eval_servc_api_path import collect  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.ml.dataset import announcement_feature_payload  # noqa: E402
from src.ml.features import build_feature_dict  # noqa: E402
from src.ml.institution_history import (  # noqa: E402
    HISTORY_MIN_SAMPLES,
    VALID_RATE_MAX,
    VALID_RATE_MIN,
    _default_institution_rate,
)
from src.ml.model_registry import predict_interval, predict_optimal_price  # noqa: E402

MODEL_ID = "servc_institution_v1"
T_THRESHOLD = 2.0

# 학습(`attach_institution_history`)과 같은 정의입니다. 기준 시각 이전 전량이며
# 이상치 범위도 같습니다.
ASOF_SQL = text(
    """
    SELECT COUNT(*) AS n, AVG(sucsf_bid_rate) AS avg_rate
    FROM bid_results
    WHERE dminstt_nm = :inst AND category = 'Servc'
      AND rl_openg_dt < :ref
      AND sucsf_bid_rate > :lo AND sucsf_bid_rate < :hi
    """
)


def asof_history(conn, institution: str, reference) -> dict | None:
    """그 공고 시점의 기관 이력을 냅니다. 표본 부족이면 학습과 같은 기본값."""
    if not institution or reference is None:
        return None
    row = conn.execute(
        ASOF_SQL,
        {"inst": institution, "ref": reference, "lo": VALID_RATE_MIN, "hi": VALID_RATE_MAX},
    ).one()
    count = int(row.n or 0)
    if count < HISTORY_MIN_SAMPLES or row.avg_rate is None:
        return {"inst_hist_rate": _default_institution_rate("Servc"), "inst_sample_cnt": count}
    return {"inst_hist_rate": float(row.avg_rate) / 100.0, "inst_sample_cnt": float(count)}


def reference_amount_of(bid) -> float:
    """API 와 같은 순서로 기준 금액을 고릅니다."""
    for value in (bid.base_amount, bid.presmpt_prce):
        if value:
            return float(value)
    return 0.0


def predict_with(session, bid, overrides: dict | None) -> dict | None:
    """`predict_price_api` 와 같은 특징 구성을 거쳐 예측합니다.

    overrides 가 있으면 이력 조회 대신 그 값을 씁니다. `build_feature_dict` 가
    payload 에 값이 있으면 조회를 건너뛰는 성질을 이용합니다.
    """
    amount = reference_amount_of(bid)
    if amount <= 0:
        return None

    features = {
        **announcement_feature_payload(bid),
        "title": bid.bid_ntce_nm or "",
        "agency_name": bid.dminstt_nm or bid.ntce_instt_nm or "",
        "scenario_mode": "2",
        "presmpt_prce": amount,
        "presmptPrce": amount,
        "real_budget": amount,
        "bid_ntce_nm": bid.bid_ntce_nm or "",
        "ntce_instt_nm": bid.ntce_instt_nm or "",
        "ntceInsttNm": bid.ntce_instt_nm or "",
        "dminstt_nm": bid.dminstt_nm or "",
        "bidMethdNm": bid.bid_methd_nm or "",
        "cntrctCnclsMthdNm": bid.cntrct_mthd_nm or "",
        "category": bid.category or "",
        "bid_ntce_dt": bid.bid_ntce_dt,
        "bid_clse_dt": bid.bid_clse_dt,
        "openg_dt": bid.openg_dt,
    }
    if overrides:
        features.update(overrides)

    features = {**features, **build_feature_dict(features, session)}
    try:
        rate = predict_optimal_price(MODEL_ID, features)
    except Exception:
        return None

    percent = round(rate * 100, 4) if rate < 2.0 else round(rate, 4)
    bounds = predict_interval(MODEL_ID, features)
    low = high = None
    if bounds is not None:
        low, high, _ = bounds
    return {"pred": percent, "low": low, "high": high}


def paired(diff: np.ndarray, label: str) -> dict:
    n = len(diff)
    mean = float(diff.mean())
    se = float(diff.std(ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    t = mean / se if se > 0 else 0.0
    verdict = (
        "판별 불가" if abs(t) < T_THRESHOLD else ("as-of 우세" if mean < 0 else "현행 우세")
    )
    return {
        "지표": label,
        "평균 차이": round(mean, 5),
        "표준오차": round(se, 5),
        "t": round(t, 2),
        "판정": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    session = SessionLocal()
    records: list[dict] = []
    try:
        frame = collect(session, args.year, args.samples, args.seed)
        if frame.empty:
            print("표본이 없습니다. DB 연결과 연도를 확인하십시오.")
            return 1
        print(f"{args.year}년 용역 {len(frame):,}건을 두 조건으로 예측합니다.")
        print("  현행  서빙 집계 표 (현재 시점 이력)")
        print("  as-of 그 공고 개찰일 기준 이력\n")

        conn = session.connection()
        for row in frame.itertuples():
            bid = session.get(BidAnnouncement, int(row.bid_id))
            if bid is None:
                continue
            overrides = asof_history(conn, bid.dminstt_nm or "", bid.openg_dt)
            current = predict_with(session, bid, None)
            shifted = predict_with(session, bid, overrides)
            if current is None or shifted is None:
                continue
            actual = float(row.actual_rate)
            records.append(
                {
                    "cur_err": abs(current["pred"] - actual),
                    "asof_err": abs(shifted["pred"] - actual),
                    "cur_width": (current["high"] - current["low"])
                    if current["low"] is not None
                    else np.nan,
                    "asof_width": (shifted["high"] - shifted["low"])
                    if shifted["low"] is not None
                    else np.nan,
                    "cur_cov": _covered(current, actual),
                    "asof_cov": _covered(shifted, actual),
                }
            )
    finally:
        session.close()

    if not records:
        print("채점 가능한 표본이 없습니다.")
        return 1

    df = pd.DataFrame(records)
    n = len(df)
    print(f"채점 {n:,}건 / 제외 {len(frame) - n:,}건\n")

    summary = pd.DataFrame(
        [
            {
                "조건": "현행",
                "MAE": round(float(df["cur_err"].mean()), 4),
                "RMSE": round(float(np.sqrt((df["cur_err"] ** 2).mean())), 4),
                "0.5%p 적중": round(float((df["cur_err"] <= 0.5).mean()), 4),
                "구간 폭": round(float(df["cur_width"].median()), 4),
                "피복률": round(float(df["cur_cov"].mean()), 4),
            },
            {
                "조건": "as-of",
                "MAE": round(float(df["asof_err"].mean()), 4),
                "RMSE": round(float(np.sqrt((df["asof_err"] ** 2).mean())), 4),
                "0.5%p 적중": round(float((df["asof_err"] <= 0.5).mean()), 4),
                "구간 폭": round(float(df["asof_width"].median()), 4),
                "피복률": round(float(df["asof_cov"].mean()), 4),
            },
        ]
    )
    print(f"{'=' * 88}\n요약\n{'=' * 88}")
    print(summary.to_string(index=False))

    stats = pd.DataFrame(
        [
            paired((df["asof_err"] - df["cur_err"]).to_numpy(), "절대오차"),
            paired((df["asof_err"] ** 2 - df["cur_err"] ** 2).to_numpy(), "제곱오차"),
            paired((df["asof_width"] - df["cur_width"]).dropna().to_numpy(), "구간 폭"),
        ]
    )
    print(f"\n{'=' * 88}\n쌍대 비교 (as-of - 현행)\n{'=' * 88}")
    print(stats.to_string(index=False))

    changed = float((df["asof_err"] - df["cur_err"]).abs().gt(1e-9).mean())
    print(f"\n예측이 달라진 공고 비율: {changed:.2%}")
    detectable = 2 * float((df["asof_err"] - df["cur_err"]).std(ddof=1) / np.sqrt(n))
    print(f"이 표본이 잡아낼 수 있는 최소 MAE 차이: {detectable:.5f}")
    return 0


def _covered(result: dict, actual: float) -> bool:
    if result["low"] is None or result["high"] is None:
        return False
    return result["low"] <= actual <= result["high"]


if __name__ == "__main__":
    raise SystemExit(main())
