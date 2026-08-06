#!/usr/bin/env python3
"""
운영 API 경로로 용역 낙찰률 예측을 실측합니다.

학습기 홀드아웃 지표는 **학습 프레임 위에서** 잰 값입니다. 운영은 공고 레코드
한 건에서 특징을 만들어 들어가므로, 그 사이에 값이 끊기면 홀드아웃 지표가
아무리 좋아도 예측은 틀립니다. 실제로 서빙 배선 이전에는 홀드아웃 R2 0.68 인
모델이 API 에서 MAE 6.128 을 냈습니다.

그래서 **`predict_price_api` 를 그대로 호출**합니다. 특징 생성·모델 선택·구간
산출이 전부 운영과 같은 경로를 탑니다.

사용법:
    .venv/bin/python scripts/eval_servc_api_path.py
    .venv/bin/python scripts/eval_servc_api_path.py --samples 500 --year 2025
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

from sqlalchemy import func, select  # noqa: E402

from src.app.api.v1.predictions import predict_price_api  # noqa: E402
from src.app.core.db import SessionLocal  # noqa: E402
from src.app.models.bids import BidAnnouncement, BidResult  # noqa: E402
from src.app.schemas.predictions import PredictPriceRequest  # noqa: E402

ERROR_BANDS = (0.5, 1.0, 2.0, 3.0, 5.0)


def collect(
    session,
    year: int,
    samples: int,
    seed: int,
    category: str = "Servc",
) -> pd.DataFrame:
    """실제 낙찰률이 있는 해당 업무구분 공고를 무작위로 뽑습니다."""
    stmt = (
        select(
            BidAnnouncement.id,
            BidAnnouncement.bid_ntce_no,
            BidResult.sucsf_bid_rate,
        )
        .join(BidResult, BidResult.bid_ntce_no == BidAnnouncement.bid_ntce_no)
        .where(
            BidAnnouncement.category == category,
            BidResult.sucsf_bid_rate.isnot(None),
            BidResult.sucsf_bid_rate > 0,
            func.year(BidResult.rl_openg_dt) == year,
        )
        .order_by(func.rand(seed))
        .limit(samples)
    )
    rows = session.execute(stmt).all()
    return pd.DataFrame(rows, columns=["bid_id", "bid_ntce_no", "actual_rate"])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--samples", type=int, default=300)
    parser.add_argument("--year", type=int, default=2025)
    parser.add_argument("--seed", type=int, default=42, help="표본 재현용 시드")
    parser.add_argument("--category", default="Servc", help="업무구분 코드")
    parser.add_argument(
        "--require-lwlt",
        action="store_true",
        help="낙찰하한율 보유 건만 채점합니다. 과거 실측과 조건을 맞출 때 씁니다",
    )
    args = parser.parse_args()

    session = SessionLocal()
    try:
        # 하한율 필터는 raw_data JSON 안이라 SQL 로 거르기 번거롭습니다. 넉넉히
        # 뽑아 파이썬에서 걸러 냅니다.
        pool = args.samples * 4 if args.require_lwlt else args.samples
        frame = collect(session, args.year, pool, args.seed, args.category)
        if frame.empty:
            print("표본이 없습니다. DB 연결과 연도를 확인하십시오.")
            return 1

        if args.require_lwlt:
            from src.ml.dataset import announcement_feature_payload

            keep = []
            for row in frame.itertuples():
                bid = session.get(BidAnnouncement, int(row.bid_id))
                rate = announcement_feature_payload(bid).get("lwlt_rate") if bid else None
                if rate not in (None, "", 0, "0"):
                    keep.append(row.bid_id)
                if len(keep) >= args.samples:
                    break
            frame = frame[frame["bid_id"].isin(keep)]
            print(f"하한율 보유 건만 사용합니다 ({len(frame):,}건).")

        print(f"{args.year}년 {args.category} {len(frame):,}건으로 API 경로를 호출합니다.")

        records = []
        for row in frame.itertuples():
            try:
                response = predict_price_api(
                    PredictPriceRequest(bid_id=int(row.bid_id), user_price="0"), session
                )
            except Exception as exc:
                # 기초금액·예정가격이 모두 없는 공고는 422 로 끊깁니다. 정상 동작이며
                # 예측 정확도 표본에서 제외합니다.
                records.append({"bid_id": row.bid_id, "skipped": str(exc)[:60]})
                continue
            records.append(
                {
                    "bid_id": row.bid_id,
                    "actual": float(row.actual_rate),
                    "pred": float(response.prediction_rate),
                    "model": response.model_name,
                    "low": response.rate_low,
                    "high": response.rate_high,
                    "coverage": response.interval_coverage,
                }
            )
    finally:
        session.close()

    df = pd.DataFrame(records)
    scored = df[df["pred"].notna()].copy() if "pred" in df else pd.DataFrame()
    skipped = len(df) - len(scored)
    if scored.empty:
        print("점수를 낼 수 있는 건이 없습니다.")
        return 1

    scored["err"] = scored["pred"] - scored["actual"]
    scored["abs_err"] = scored["err"].abs()

    print(f"\n채점 {len(scored):,}건 / 제외 {skipped}건 (금액 미공개 등)")
    print(f"사용 모델: {scored['model'].value_counts().to_dict()}")

    summary = {
        "MAE": round(float(scored["abs_err"].mean()), 4),
        "RMSE": round(float(np.sqrt((scored["err"] ** 2).mean())), 4),
        "편향": round(float(scored["err"].mean()), 4),
        "중앙절대오차": round(float(scored["abs_err"].median()), 4),
    }
    print(f"\n{pd.DataFrame([summary]).to_string(index=False)}")

    bands = pd.DataFrame(
        [
            {"오차": f"{band}%p 이내", "건수": int((scored["abs_err"] <= band).sum()),
             "비율": round(float((scored["abs_err"] <= band).mean()), 4)}
            for band in ERROR_BANDS
        ]
    )
    print(f"\n{bands.to_string(index=False)}")

    # 구간은 부가 정보라 없을 수 있습니다. 있으면 표기한 피복률이 지켜지는지 봅니다.
    with_interval = scored[scored["low"].notna()]
    if not with_interval.empty:
        inside = (
            (with_interval["actual"] >= with_interval["low"])
            & (with_interval["actual"] <= with_interval["high"])
        )
        nominal = float(with_interval["coverage"].dropna().iloc[0]) if with_interval["coverage"].notna().any() else None
        width = (with_interval["high"] - with_interval["low"]).median()
        print(
            f"\n예측 구간 {len(with_interval):,}건 / 실제 피복률 {inside.mean():.2%}"
            + (f" (명목 {nominal:.0%})" if nominal else "")
            + f" / 구간 폭 중앙값 {width:.3f}%p"
        )
    else:
        print("\n예측 구간 없음 (분위 아티팩트가 없는 모델입니다)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
