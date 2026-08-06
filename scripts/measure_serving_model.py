"""
scripts/measure_serving_model.py

서빙 중인 모델의 지표를 운영 경로로 실측해 기록합니다.

원본에서 이식한 모델들은 학습 이력이 없어 지표가 없습니다. 지표가 없으면
재학습이 챌린저를 무엇과 비교할지 정할 수 없고, 게이트가 판단을 못 합니다
(`docs/ops/model_promotion_runbook.md` 4.1 절).

**측정은 운영 경로로 합니다.** `SingletonPredictor.predict` 를 그대로 태우므로,
학습 프레임에서 잰 값이 아니라 사용자가 실제로 받는 예측을 잽니다. 전처리나
특징 산출이 서빙에서만 달라지는 결함이 있으면 이 값에 그대로 드러납니다.

지표는 `data/model_metrics/<모델>.json` 에 씁니다. 서빙 metadata.json 에 쓰지
않는 이유는 그 파일이 **체크섬 매니페스트에 포함**돼 있기 때문입니다. 거기에
한 글자만 써도 G1 무손실 검증이 깨집니다.

사용법:

    uv run python scripts/measure_serving_model.py --model quantum_leap_v25_pro \
        --category Thng --since 2026-01-01 --sample 3000
    uv run python scripts/measure_serving_model.py --model ... --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.ml.promotion import load_serving_metrics, save_serving_metrics  # noqa: E402

FEATURE_STORE = PROJECT_ROOT / "data" / "feature_store"

# 예측 요청 키는 서빙 계약입니다. 학습 프레임 컬럼명과 다르므로 여기서 옮깁니다.
REQUEST_FIELDS = {
    "title": "bid_ntce_nm",
    "agency_name": "dminstt_nm",
    "presmpt_prce": "presmpt_prce",
}


def _request_from_row(row: dict, category: str) -> dict:
    """parquet 원본을 보존하면서 구 모델 별칭도 함께 채웁니다."""
    request = dict(row)
    request.update({key: row.get(column) for key, column in REQUEST_FIELDS.items()})
    request["category"] = category
    return request


def _load_holdout(category: str, since: str, sample: int, seed: int) -> pd.DataFrame:
    path = FEATURE_STORE / f"dataset_{category}.parquet"
    if not path.exists():
        raise FileNotFoundError(f"데이터셋이 없습니다: {path}")

    df = pd.read_parquet(path)
    notice_dt = pd.to_datetime(df["bid_ntce_dt"], errors="coerce")
    df = df[notice_dt >= pd.Timestamp(since)]
    df = df.dropna(subset=["winning_rate"])
    if df.empty:
        raise ValueError(f"{since} 이후 라벨이 있는 표본이 없습니다.")
    if sample and len(df) > sample:
        df = df.sample(n=sample, random_state=seed)
    return df


def _score(predictions: np.ndarray, actual: np.ndarray) -> dict:
    error = predictions - actual
    denominator = ((actual - actual.mean()) ** 2).sum()
    return {
        "rmse": float(np.sqrt((error**2).mean())),
        "mae": float(np.abs(error).mean()),
        "mape": float((np.abs(error) / np.abs(actual)).mean() * 100),
        "r2": float(1 - (error**2).sum() / denominator) if denominator else float("nan"),
        "bias": float(error.mean()),
    }


def measure(
    model_id: str,
    category: str,
    since: str,
    sample: int,
    seed: int,
) -> tuple[dict, int, int]:
    """운영 경로로 예측해 지표를 냅니다. 실패한 건수도 함께 돌려줍니다."""
    from src.app.core.db import SessionLocal
    from src.ml.predictor import SingletonPredictor

    frame = _load_holdout(category, since, sample, seed)
    predictor = SingletonPredictor()
    db = SessionLocal()
    predictions: list[float] = []
    actual: list[float] = []
    failed = 0
    try:
        for row in frame.to_dict("records"):
            request = _request_from_row(row, category)
            try:
                result = predictor.predict(request, model_id=model_id, session=db)
            # 한 건이 실패해도 전체 측정을 멈추지 않습니다. 실패 건수를 함께 보고합니다.
            except Exception:
                failed += 1
                continue
            rate = result.get("predicted_rate")
            if rate is None:
                failed += 1
                continue
            predictions.append(float(rate))
            actual.append(float(row["winning_rate"]))
    finally:
        db.close()

    if not predictions:
        raise RuntimeError("예측이 한 건도 성공하지 않았습니다.")
    return _score(np.array(predictions), np.array(actual)), len(predictions), failed


def main() -> int:
    parser = argparse.ArgumentParser(description="서빙 모델 지표 실측")
    parser.add_argument("--model", required=True, help="서빙 모델 이름")
    parser.add_argument("--category", required=True, help="업무구분 (Thng/Servc/Cnstwk)")
    parser.add_argument("--since", default="2026-01-01", help="홀드아웃 시작 공고일")
    parser.add_argument("--sample", type=int, default=3000, help="표본 수 (0 이면 전량)")
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--apply", action="store_true", help="사이드카에 기록합니다")
    args = parser.parse_args()

    version, existing = load_serving_metrics(args.model)
    if not version:
        print(f"서빙 중인 모델을 찾지 못했습니다: {args.model}")
        return 1

    print(f"[{args.model}] 서빙 버전 {version}")
    if existing:
        print(f"  기존 지표 {existing}")

    metrics, scored, failed = measure(
        args.model,
        args.category,
        args.since,
        args.sample,
        args.seed,
    )
    print(f"  표본 {scored:,} (실패 {failed})  기준 {args.since} 이후 {args.category}")
    print(
        "  RMSE {rmse:.4f} / MAE {mae:.4f} / MAPE {mape:.4f}% / R2 {r2:.4f} / 편향 {bias:+.4f}".format(
            **metrics
        )
    )
    if metrics["r2"] < 0:
        print("  경고: R2 가 음수입니다. 평균값 예측보다 못합니다.")

    if not args.apply:
        print("\n기록하려면 --apply 를 붙이십시오.")
        return 0

    path = save_serving_metrics(
        args.model,
        version,
        metrics,
        detail={
            "category": args.category,
            "holdout_since": args.since,
            "samples": scored,
            "failed": failed,
            "measured_via": "SingletonPredictor.predict (운영 경로)",
        },
    )
    print(f"\n기록: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
