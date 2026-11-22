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


# 화면 타일이 쓰는 오차 범위입니다. 단위는 낙찰률 %p 입니다.
BAND_THRESHOLDS = (0.5, 1.0, 2.0, 3.0)
# 산점도는 브라우저가 그리므로 점 수를 고정합니다.
SCATTER_LIMIT = 300


def _numeric_array(values) -> np.ndarray:
    """None 을 nan 으로 바꿔 부동소수 배열로 만듭니다."""
    return np.asarray([np.nan if value is None else float(value) for value in values], dtype=float)


def compute_distribution(
    predictions,
    actual,
    lows=None,
    highs=None,
    *,
    target: float | None = None,
    seed: int = 42,
) -> dict:
    """예측·실제 배열에서 화면용 분포를 계산합니다.

    DB·모델·파일에 기대지 않는 순수 함수입니다. `bands` 는 예측과 실제의
    차이가 기준 %p 이내인 표본 비율이고, `interval` 은 구간 예측이 실제
    낙찰률을 포함한 실측 비율입니다. 목표치(target)로 채우지 않습니다.
    구간을 낼 수 없는 표본은 평가에서 빼고 `evaluated` 로 셉니다.
    전부 낼 수 없으면 `interval` 은 None 입니다.

    `scatter` 는 seed 로 고정한 무작위 표본이며 좌표는 소수 둘째 자리입니다.
    `error_reduction` 은 1 - SSE/SST 로 r2 와 같은 값입니다.
    """
    predicted = _numeric_array(predictions)
    observed = _numeric_array(actual)
    if predicted.shape != observed.shape:
        raise ValueError("예측과 실제 배열 길이가 다릅니다.")
    original_size = observed.size

    finite = np.isfinite(predicted) & np.isfinite(observed)
    predicted = predicted[finite]
    observed = observed[finite]
    if predicted.size == 0:
        raise ValueError("분포를 계산할 표본이 없습니다.")

    error = np.abs(predicted - observed)
    bands = [
        {"within_pp": threshold, "share": float((error <= threshold).mean())}
        for threshold in BAND_THRESHOLDS
    ]

    interval: dict | None = None
    if lows is not None and highs is not None:
        low_values = _numeric_array(lows)
        high_values = _numeric_array(highs)
        if low_values.size != original_size or high_values.size != original_size:
            raise ValueError("구간 배열 길이가 예측 배열과 다릅니다.")
        low_values = low_values[finite]
        high_values = high_values[finite]
        usable = np.isfinite(low_values) & np.isfinite(high_values) & (high_values >= low_values)
        evaluated = int(usable.sum())
        if evaluated:
            covered = (observed[usable] >= low_values[usable]) & (
                observed[usable] <= high_values[usable]
            )
            interval = {
                "coverage": float(covered.mean()),
                "evaluated": evaluated,
                "target": None if target is None else float(target),
            }

    rng = np.random.default_rng(seed)
    if predicted.size > SCATTER_LIMIT:
        indices = np.sort(rng.choice(predicted.size, size=SCATTER_LIMIT, replace=False))
    else:
        indices = np.arange(predicted.size)
    points = [
        [round(float(predicted[index]), 2), round(float(observed[index]), 2)] for index in indices
    ]

    # SST 가 0 이면 설명할 변동이 없습니다. JSON 에 NaN 을 남기지 않도록 0 으로 둡니다.
    denominator = float(((observed - observed.mean()) ** 2).sum())
    residual = float(((predicted - observed) ** 2).sum())
    error_reduction = 1.0 - residual / denominator if denominator else 0.0

    return {
        "bands": bands,
        "interval": interval,
        "scatter": {"points": points, "seed": int(seed)},
        "error_reduction": error_reduction,
    }


def measure(
    model_id: str,
    category: str,
    since: str,
    sample: int,
    seed: int,
) -> tuple[dict, dict, int, int]:
    """운영 경로로 예측해 지표와 분포를 냅니다. 실패한 건수도 함께 돌려줍니다."""
    from src.app.core.db import SessionLocal
    from src.ml.prediction_api import predict_interval
    from src.ml.predictor import SingletonPredictor

    frame = _load_holdout(category, since, sample, seed)
    predictor = SingletonPredictor()
    db = SessionLocal()
    predictions: list[float] = []
    actual: list[float] = []
    lows: list[float | None] = []
    highs: list[float | None] = []
    target: float | None = None
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

            # 구간은 점 추정을 낸 모델에서 뽑습니다. 실패하거나 지원하지 않는
            # 모델이면 None 으로 두고 분포 계산에서 평가 대상만 줄입니다.
            bounds = None
            try:
                bounds = predict_interval(result.get("model_version") or model_id, request)
            except Exception:
                bounds = None
            if bounds is not None:
                low, high, coverage = bounds
                lows.append(low)
                highs.append(high)
                if target is None and coverage is not None:
                    target = float(coverage)
            else:
                lows.append(None)
                highs.append(None)
    finally:
        db.close()

    if not predictions:
        raise RuntimeError("예측이 한 건도 성공하지 않았습니다.")
    scored = np.array(predictions)
    observed = np.array(actual)
    metrics = _score(scored, observed)
    distribution = compute_distribution(predictions, actual, lows, highs, target=target, seed=seed)
    return metrics, distribution, len(predictions), failed


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

    metrics, distribution, scored, failed = measure(
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
    band_text = " / ".join(
        f"{band['within_pp']:g}%p 이내 {band['share'] * 100:.1f}%" for band in distribution["bands"]
    )
    print(f"  오차 범위 적중: {band_text}")
    interval = distribution["interval"]
    if interval is None:
        print("  예측 구간: 산출 불가 (구간을 내는 모델이 아님)")
    else:
        target = interval["target"]
        target_text = f"목표 {target * 100:.1f}%" if target is not None else "목표 미상"
        print(
            f"  예측 구간 적중률 {interval['coverage'] * 100:.1f}% ({target_text}, "
            f"평가 {interval['evaluated']:,}건)"
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
        distribution=distribution,
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
