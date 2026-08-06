#!/usr/bin/env python3
"""
두 모델을 운영 API 경로에서 **쌍대 비교**합니다.

기존 `eval_servc_api_path.py` 는 모델을 하나씩 따로 돌려 요약값만 비교했습니다.
그 방식으로는 판정이 불가능하다는 것이 2026-08-05 에 드러났습니다. 용역 낙찰률
오차는 산포가 커서(RMSE 3.12) 1,000건 표본의 MAE 표준오차가 약 0.099 인데,
리프 63 대 127 의 관측 차이는 0.0015 였습니다. **표준오차의 1.5% 를 읽고 우열을
단정한 것입니다.**

같은 공고에 두 모델을 돌리면 공고별 오차 차이를 직접 볼 수 있습니다. 두 모델은
같은 특징을 같은 공고에서 보므로 오차가 강하게 상관되고, 차이의 분산은 오차
자체의 분산보다 훨씬 작습니다. 그래서 같은 표본으로도 훨씬 작은 효과를 잡아냅니다.

전제: 비교할 두 모델이 **서빙 루트(`data/model_files/`)에 각각 다른 ID 로**
올라가 있어야 합니다. 승격본과 백업을 겨룰 때는 백업을 임시 ID 로 복제하십시오.

사용법:
    .venv/bin/python scripts/compare_servc_models_paired.py \\
        --base servc_prev_63leaf --challenger servc_institution_v1
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

from scripts.eval_servc_api_path import collect  # noqa: E402
from src.app.api.v1.predictions import predict_price_api  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement  # noqa: E402
from src.app.schemas.predictions import PredictPriceRequest  # noqa: E402
from src.ml.dataset import announcement_feature_payload  # noqa: E402
from src.ml.model_registry import ModelRegistry  # noqa: E402

# 유의 판정 기준. 쌍대 t 통계량의 절댓값이 이보다 커야 방향을 말합니다.
T_THRESHOLD = 2.0


def predict_one(session, bid_id: int, model_id: str) -> dict | None:
    try:
        response = predict_price_api(
            PredictPriceRequest(bid_id=int(bid_id), user_price="0", selected_model=model_id),
            session,
        )
    except Exception:
        return None
    if response.prediction_rate is None:
        return None
    return {
        "pred": float(response.prediction_rate),
        "model": response.model_name,
        "low": response.rate_low,
        "high": response.rate_high,
    }


def paired_stats(diff: np.ndarray, label: str, lower_is_better: bool = True) -> dict:
    """쌍대 차이의 평균과 표준오차를 냅니다. diff = challenger - base 입니다."""
    n = len(diff)
    mean = float(diff.mean())
    se = float(diff.std(ddof=1) / np.sqrt(n)) if n > 1 else float("inf")
    t = mean / se if se > 0 else 0.0
    if abs(t) < T_THRESHOLD:
        verdict = "판별 불가"
    elif (mean < 0) == lower_is_better:
        verdict = "challenger 우세"
    else:
        verdict = "base 우세"
    return {
        "지표": label,
        "평균 차이": round(mean, 5),
        "표준오차": round(se, 5),
        "t": round(t, 2),
        "판정": verdict,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", required=True, help="기준 모델 ID (서빙 루트 디렉터리명)")
    parser.add_argument("--challenger", required=True, help="비교 모델 ID")
    parser.add_argument("--samples", type=int, default=1000)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--require-lwlt", action="store_true", help="하한율 보유 건만 채점")
    parser.add_argument(
        "--model-root",
        default=None,
        help="비교용 모델 디렉터리 루트. 지정하면 이 프로세스에서만 사용",
    )
    args = parser.parse_args()

    if args.model_root:
        model_root = Path(args.model_root).resolve()
        if not model_root.is_dir():
            print(f"비교용 모델 루트가 없습니다: {model_root}")
            return 1
        ModelRegistry._get_model_root = classmethod(lambda cls: str(model_root))
        ModelRegistry.load_all_models()

    session = SessionLocal()
    try:
        pool = args.samples * 4 if args.require_lwlt else args.samples
        frame = collect(session, args.year, pool, args.seed)
        if frame.empty:
            print("표본이 없습니다. DB 연결과 연도를 확인하십시오.")
            return 1

        if args.require_lwlt:
            keep = []
            for row in frame.itertuples():
                bid = session.get(BidAnnouncement, int(row.bid_id))
                if bid and announcement_feature_payload(bid).get("lwlt_rate"):
                    keep.append(row.bid_id)
                if len(keep) >= args.samples:
                    break
            frame = frame[frame["bid_id"].isin(keep)]
            print(f"하한율 보유 건만 사용합니다 ({len(frame):,}건).")

        print(f"{args.year}년 용역 {len(frame):,}건에 두 모델을 같은 순서로 호출합니다.")
        print(f"  base       {args.base}")
        print(f"  challenger {args.challenger}\n")

        records = []
        for row in frame.itertuples():
            a = predict_one(session, row.bid_id, args.base)
            b = predict_one(session, row.bid_id, args.challenger)
            if a is None or b is None:
                continue
            actual = float(row.actual_rate)
            records.append(
                {
                    "actual": actual,
                    "base_err": abs(a["pred"] - actual),
                    "chal_err": abs(b["pred"] - actual),
                    "base_width": (a["high"] - a["low"]) if a["low"] is not None else np.nan,
                    "chal_width": (b["high"] - b["low"]) if b["low"] is not None else np.nan,
                    "base_covered": _covered(a, actual),
                    "chal_covered": _covered(b, actual),
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
                "모델": "base",
                "MAE": round(float(df["base_err"].mean()), 4),
                "RMSE": round(float(np.sqrt((df["base_err"] ** 2).mean())), 4),
                "0.5%p 적중": round(float((df["base_err"] <= 0.5).mean()), 4),
                "구간 폭": round(float(df["base_width"].median()), 4),
                "피복률": round(float(df["base_covered"].mean()), 4),
            },
            {
                "모델": "challenger",
                "MAE": round(float(df["chal_err"].mean()), 4),
                "RMSE": round(float(np.sqrt((df["chal_err"] ** 2).mean())), 4),
                "0.5%p 적중": round(float((df["chal_err"] <= 0.5).mean()), 4),
                "구간 폭": round(float(df["chal_width"].median()), 4),
                "피복률": round(float(df["chal_covered"].mean()), 4),
            },
        ]
    )
    print(f"{'=' * 92}\n요약 (이것만으로는 판정하지 마십시오)\n{'=' * 92}")
    print(summary.to_string(index=False))

    stats = pd.DataFrame(
        [
            paired_stats((df["chal_err"] - df["base_err"]).to_numpy(), "절대오차"),
            paired_stats((df["chal_err"] ** 2 - df["base_err"] ** 2).to_numpy(), "제곱오차"),
            paired_stats((df["chal_width"] - df["base_width"]).dropna().to_numpy(), "구간 폭"),
        ]
    )
    print(f"\n{'=' * 92}\n쌍대 비교 (challenger - base)\n{'=' * 92}")
    print(stats.to_string(index=False))

    better = float((df["chal_err"] < df["base_err"]).mean())
    print(f"\nchallenger 가 더 정확한 공고 비율: {better:.2%}")

    detectable = 2 * float((df["chal_err"] - df["base_err"]).std(ddof=1) / np.sqrt(n))
    print(f"이 표본이 잡아낼 수 있는 최소 MAE 차이: {detectable:.5f}")
    print(f"관측된 차이: {abs(float((df['chal_err'] - df['base_err']).mean())):.5f}")
    return 0


def _covered(result: dict, actual: float) -> bool:
    if result["low"] is None or result["high"] is None:
        return False
    return result["low"] <= actual <= result["high"]


if __name__ == "__main__":
    raise SystemExit(main())
